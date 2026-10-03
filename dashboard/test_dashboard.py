"""Fixture checks for the read-only dashboard. No network and no FRED key."""

from __future__ import annotations

import ast
import hashlib
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import urlopen

from dashboard.read import connect, ingestion_running, is_ingestion_argv, is_stale, load_status, resolve_db_path
from dashboard.server import render_page, make_server

SCHEMA = """
CREATE TABLE series_metadata (
    key TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    unit TEXT NOT NULL,
    source TEXT NOT NULL,
    threshold REAL NOT NULL DEFAULT 0.0,
    description TEXT DEFAULT ''
);
CREATE TABLE observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    series_key TEXT NOT NULL,
    date TEXT NOT NULL,
    value REAL NOT NULL,
    recorded_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX idx_obs_key_date ON observations(series_key, date);
"""


def _build_db(path: Path, last_run_at: str, status: str = "ok") -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT INTO series_metadata (key, label, unit, source, threshold, description) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("cpi", "CPI", "%", "fred", 0.0, "Consumer prices"),
                ("us10y", "10Y Yield", "%", "fred", 0.0, "Ten year"),
                ("vix", "VIX <script>", "", "live", 1.0, "Volatility"),
            ],
        )
        # Newer id with an older date must not win. Latest is MAX(date).
        conn.execute(
            "INSERT INTO observations (series_key, date, value) VALUES (?, ?, ?)",
            ("vix", "2026-10-01", 20.5),
        )
        conn.execute(
            "INSERT INTO observations (series_key, date, value) VALUES (?, ?, ?)",
            ("vix", "2026-09-01", 99.0),
        )
        conn.execute(
            "INSERT INTO observations (series_key, date, value) VALUES (?, ?, ?)",
            ("us10y", "2026-10-03", 4.25),
        )
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?)",
            ("last_run_at", last_run_at),
        )
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?)",
            ("last_run_status", status),
        )
        conn.commit()
    finally:
        conn.close()


class ReadTests(unittest.TestCase):
    def test_stats_and_snapshot_use_max_date(self) -> None:
        now = datetime(2026, 10, 3, 20, 0, tzinfo=timezone.utc)
        last_run = (now - timedelta(minutes=25)).strftime("%Y-%m-%d %H:%M:%S")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "macrobot.db"
            _build_db(path, last_run, "partial")
            before = path.read_bytes()
            status = load_status(path, now=now)

        self.assertTrue(status.db_exists)
        self.assertIsNone(status.error)
        self.assertEqual(status.indicator_count, 3)
        self.assertEqual(status.indicators_with_observations, 2)
        self.assertEqual(status.observation_count, 3)
        self.assertEqual(status.last_run_at, last_run)
        self.assertEqual(status.last_run_status, "partial")
        self.assertFalse(status.stale)
        self.assertEqual(status.newest_observation_date, "2026-10-03")
        self.assertEqual(status.db_size_bytes, len(before))

        by_key = {row.key: row for row in status.snapshot}
        self.assertEqual(set(by_key), {"cpi", "us10y", "vix"})
        self.assertIsNone(by_key["cpi"].value)
        self.assertIsNone(by_key["cpi"].date)
        self.assertEqual(by_key["vix"].value, 20.5)
        self.assertEqual(by_key["vix"].date, "2026-10-01")
        self.assertEqual(by_key["us10y"].value, 4.25)
        self.assertEqual(by_key["us10y"].date, "2026-10-03")
        # Documented order is source, then key: fred before live.
        self.assertEqual([row.key for row in status.snapshot], ["cpi", "us10y", "vix"])

        page = render_page(status, now=now)
        self.assertIn("3", page)
        self.assertIn("2", page)
        self.assertIn(last_run, page)
        self.assertIn("partial", page)
        self.assertIn("current", page)
        self.assertIn("2026-10-03", page)
        self.assertIn("20.5", page)
        self.assertIn("4.25", page)
        self.assertNotIn("99", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertNotIn("<script>", page)

    def test_stale_when_last_run_is_older_than_two_hours(self) -> None:
        now = datetime(2026, 10, 3, 20, 0, tzinfo=timezone.utc)
        self.assertFalse(is_stale((now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"), now))
        self.assertTrue(is_stale((now - timedelta(hours=2, seconds=1)).strftime("%Y-%m-%d %H:%M:%S"), now))
        self.assertTrue(is_stale(None, now))
        self.assertTrue(is_stale("not-a-timestamp", now))

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "macrobot.db"
            old = (now - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")
            _build_db(path, old, "failed")
            status = load_status(path, now=now)
        self.assertTrue(status.stale)
        self.assertEqual(status.last_run_status, "failed")
        page = render_page(status, now=now)
        self.assertIn("stale", page)
        self.assertIn("failed", page)

    def test_connection_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "macrobot.db"
            _build_db(path, "2026-10-03 18:00:00", "ok")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            conn = connect(path)
            try:
                self.assertEqual(conn.execute("PRAGMA query_only").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 3)
                with self.assertRaises(sqlite3.OperationalError):
                    conn.execute("INSERT INTO meta (key, value) VALUES ('x', 'y')")
                with self.assertRaises(sqlite3.OperationalError):
                    conn.execute("UPDATE observations SET value = 0")
                with self.assertRaises(sqlite3.OperationalError):
                    conn.execute("DELETE FROM series_metadata")
            finally:
                conn.close()
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
            # A normal connection still sees the original rows.
            with closing(sqlite3.connect(path)) as check:
                self.assertEqual(check.execute("SELECT COUNT(*) FROM meta").fetchone()[0], 2)
                self.assertEqual(check.execute("SELECT value FROM observations WHERE series_key = 'vix' AND date = '2026-10-01'").fetchone()[0], 20.5)

    def test_missing_database_is_not_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.db"
            status = load_status(path)
            self.assertFalse(path.exists())
            self.assertFalse(status.db_exists)
            self.assertIsNone(status.indicator_count)
            page = render_page(status)
            self.assertIn("not there yet", page)

    def test_path_resolution_matches_env_then_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous_cwd = Path.cwd()
            previous = os.environ.get("SQLITE_DB_PATH")
            os.chdir(tmp)
            try:
                Path(".env").write_text('export SQLITE_DB_PATH="from-dotenv.db"\n', encoding="utf-8")
                os.environ.pop("SQLITE_DB_PATH", None)
                self.assertEqual(resolve_db_path(), Path("from-dotenv.db"))
                os.environ["SQLITE_DB_PATH"] = "from-env.db"
                self.assertEqual(resolve_db_path(), Path("from-env.db"))
                self.assertEqual(resolve_db_path("explicit.db"), Path("explicit.db"))
            finally:
                os.chdir(previous_cwd)
                if previous is None:
                    os.environ.pop("SQLITE_DB_PATH", None)
                else:
                    os.environ["SQLITE_DB_PATH"] = previous


class ProcessTests(unittest.TestCase):
    def test_argv_matches_main_py_only(self) -> None:
        self.assertTrue(is_ingestion_argv(["/opt/macrobot/.venv/bin/python", "main.py"]))
        self.assertTrue(is_ingestion_argv(["python3", "/opt/macrobot/main.py"]))
        self.assertTrue(is_ingestion_argv(["python", "-u", "main.py"]))
        self.assertFalse(is_ingestion_argv(["python", "-m", "dashboard"]))
        self.assertFalse(is_ingestion_argv(["python3", "-c", "import main"]))
        self.assertFalse(is_ingestion_argv(["python", "/opt/macrobot/dashboard/__main__.py"]))
        self.assertFalse(is_ingestion_argv(["vim", "main.py"]))
        self.assertFalse(is_ingestion_argv([]))

    def test_live_process_scan_ignores_this_process_and_sees_main_py(self) -> None:
        own = Path(f"/proc/{os.getpid()}/cmdline").read_bytes()
        own_args = [part for part in own.decode().split("\0") if part]
        self.assertFalse(is_ingestion_argv(own_args))

        if ingestion_running():
            self.skipTest("python main.py is already running on this host")

        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "main.py"
            script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
            proc = subprocess.Popen([sys.executable, str(script)])
            try:
                seen = False
                for _ in range(50):
                    if ingestion_running():
                        seen = True
                        break
                    threading.Event().wait(0.05)
                self.assertTrue(seen)
            finally:
                proc.kill()
                proc.wait(timeout=5)
        self.assertFalse(ingestion_running())


class PageServerTests(unittest.TestCase):
    def test_localhost_page_serves_fixture_stats(self) -> None:
        now_run = datetime.now(timezone.utc) - timedelta(minutes=10)
        last_run = now_run.strftime("%Y-%m-%d %H:%M:%S")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "macrobot.db"
            _build_db(path, last_run, "ok")
            server = make_server(0, path)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                self.assertEqual(server.server_address[0], "127.0.0.1")
                with urlopen(f"http://127.0.0.1:{port}/") as response:
                    body = response.read().decode()
                    self.assertEqual(response.status, 200)
                self.assertIn("Indicators", body)
                self.assertIn(last_run, body)
                self.assertIn("ok", body)
                self.assertIn("20.5", body)
                self.assertIn("4.25", body)
                self.assertIn("2026-10-03", body)
                word = "running" if ingestion_running() else "idle"
                self.assertIn(word, body)
            finally:
                server.shutdown()
                server.server_close()


class IsolationTests(unittest.TestCase):
    def test_dashboard_source_does_not_import_ingestion(self) -> None:
        root = Path(__file__).resolve().parent
        forbidden = {"checker", "macro", "db", "config", "yfinance", "pandas", "numpy"}
        for path in root.glob("*.py"):
            if path.name.startswith("test_"):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [(node.module or "").split(".")[0]]
                self.assertTrue(forbidden.isdisjoint(names), f"{path.name} imports {names}")

        self.assertNotIn("checker", sys.modules)
        self.assertNotIn("yfinance", sys.modules)
        self.assertNotIn("pandas", sys.modules)
        self.assertNotIn("numpy", sys.modules)


if __name__ == "__main__":
    unittest.main()
