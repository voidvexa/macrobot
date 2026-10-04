"""Fixture checks for the read-only dashboard. No network and no FRED key."""

from __future__ import annotations

import ast
import hashlib
import json
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
from urllib.error import HTTPError
from urllib.request import urlopen

import dashboard.read as reader
from dashboard.read import (
    JOB_SQL,
    SNAPSHOT_SQL,
    STATS_SQL,
    connect,
    ingestion_running,
    is_ingestion_argv,
    is_stale,
    load_job,
    load_snapshot,
    load_stats,
    resolve_db_path,
)
from dashboard.server import (
    JOB_FIELDS,
    SNAPSHOT_FIELDS,
    SNAPSHOT_RESPONSE_FIELDS,
    STATS_FIELDS,
    job_payload,
    make_server,
    snapshot_payload,
    stats_payload,
)

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


def _norm(sql: str) -> str:
    return " ".join(sql.split())


def _trace(fn):
    """Count statements the service runs after the connection is open.

    `connect` itself sets two PRAGMAs. Those are locks on the connection, not
    the feature query, so the callback is installed after they run.
    """
    statements: list[str] = []
    real = reader.connect

    def tracing(db_path: Path) -> sqlite3.Connection:
        conn = real(db_path)
        conn.set_trace_callback(lambda sql: statements.append(_norm(sql)))
        return conn

    reader.connect = tracing
    try:
        return fn(), statements
    finally:
        reader.connect = real


class ReadTests(unittest.TestCase):
    def test_job_reads_meta_once(self) -> None:
        now = datetime(2026, 10, 3, 20, 0, tzinfo=timezone.utc)
        last_run = (now - timedelta(minutes=25)).strftime("%Y-%m-%d %H:%M:%S")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "macrobot.db"
            _build_db(path, last_run, "partial")
            job, statements = _trace(lambda: load_job(path, now=now))

        self.assertEqual(statements, [_norm(JOB_SQL)])
        self.assertNotIn("observations", statements[0])
        self.assertFalse(job.stale)
        self.assertEqual(job.last_run_at, last_run)
        self.assertEqual(job.last_run_status, "partial")
        self.assertEqual(job.ingestion_running, ingestion_running())
        self.assertIsNone(job.error)
        payload = job_payload(job)
        self.assertEqual(tuple(payload), JOB_FIELDS)
        self.assertNotIn("indicator_count", payload)
        self.assertNotIn("snapshot", payload)

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
            job = load_job(path, now=now)
        self.assertTrue(job.stale)
        self.assertEqual(job.last_run_status, "failed")
        payload = job_payload(job)
        self.assertTrue(payload["stale"])
        self.assertEqual(payload["last_run_status"], "failed")

    def test_stats_are_one_statement_and_a_file_stat(self) -> None:
        now = datetime(2026, 10, 3, 20, 0, tzinfo=timezone.utc)
        last_run = (now - timedelta(minutes=25)).strftime("%Y-%m-%d %H:%M:%S")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "macrobot.db"
            _build_db(path, last_run, "partial")
            before = path.read_bytes()
            stats, statements = _trace(lambda: load_stats(path))

        self.assertEqual(statements, [_norm(STATS_SQL)])
        self.assertNotIn("FROM meta", statements[0])
        self.assertEqual(stats.indicator_count, 3)
        self.assertEqual(stats.indicators_with_observations, 2)
        self.assertEqual(stats.observation_count, 3)
        self.assertEqual(stats.newest_observation_date, "2026-10-03")
        self.assertEqual(stats.db_size_bytes, len(before))
        self.assertIsNone(stats.error)
        payload = stats_payload(stats)
        self.assertEqual(tuple(payload), STATS_FIELDS)
        self.assertNotIn("last_run_at", payload)
        self.assertNotIn("snapshot", payload)
        self.assertNotIn("ingestion_running", payload)

    def test_snapshot_uses_max_date(self) -> None:
        now = datetime(2026, 10, 3, 20, 0, tzinfo=timezone.utc)
        last_run = (now - timedelta(minutes=25)).strftime("%Y-%m-%d %H:%M:%S")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "macrobot.db"
            _build_db(path, last_run, "partial")
            snapshot, statements = _trace(lambda: load_snapshot(path))

        self.assertEqual(statements, [_norm(SNAPSHOT_SQL)])
        self.assertIn("MAX(date)", statements[0])
        self.assertNotIn("FROM meta", statements[0])
        by_key = {row.key: row for row in snapshot.rows}
        self.assertEqual(set(by_key), {"cpi", "us10y", "vix"})
        self.assertIsNone(by_key["cpi"].value)
        self.assertIsNone(by_key["cpi"].date)
        self.assertEqual(by_key["vix"].value, 20.5)
        self.assertEqual(by_key["vix"].date, "2026-10-01")
        self.assertEqual(by_key["us10y"].value, 4.25)
        self.assertEqual(by_key["us10y"].date, "2026-10-03")
        # Documented order is source, then key: fred before live.
        self.assertEqual([row.key for row in snapshot.rows], ["cpi", "us10y", "vix"])
        payload = snapshot_payload(snapshot)
        self.assertEqual(tuple(payload), SNAPSHOT_RESPONSE_FIELDS)
        for row in payload["snapshot"]:
            self.assertEqual(tuple(row), SNAPSHOT_FIELDS)
        self.assertNotIn("indicator_count", payload)
        self.assertNotIn("last_run_at", payload)
        self.assertEqual(payload["snapshot"][1]["value"], 4.25)
        self.assertNotEqual(by_key["vix"].value, 99.0)

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
            job, job_sql = _trace(lambda: load_job(path))
            stats, stats_sql = _trace(lambda: load_stats(path))
            snapshot, snapshot_sql = _trace(lambda: load_snapshot(path))
            self.assertFalse(path.exists())
        self.assertEqual(job_sql, [])
        self.assertEqual(stats_sql, [])
        self.assertEqual(snapshot_sql, [])
        self.assertFalse(job.db_exists)
        self.assertIsNone(job.last_run_at)
        self.assertIsNone(job.stale)
        self.assertFalse(stats.db_exists)
        self.assertIsNone(stats.indicator_count)
        self.assertIsNone(stats.db_size_bytes)
        self.assertFalse(snapshot.db_exists)
        self.assertEqual(snapshot.rows, ())
        self.assertFalse(job_payload(job)["db_exists"])
        self.assertIsNone(stats_payload(stats)["indicator_count"])
        self.assertEqual(snapshot_payload(snapshot)["snapshot"], [])

    def test_path_resolution_matches_env_then_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous_cwd = Path.cwd()
            previous = os.environ.get("SQLITE_DB_PATH")
            os.chdir(tmp)
            try:
                os.environ.pop("SQLITE_DB_PATH", None)
                Path(".env").write_text("SQLITE_DB_PATH=foo.db  # note\n", encoding="utf-8")
                self.assertEqual(resolve_db_path(), Path("foo.db"))
                Path(".env").write_text("sqlite_db_path=lower.db\n", encoding="utf-8")
                self.assertEqual(resolve_db_path(), Path("lower.db"))
                Path(".env").write_text('export SQLITE_DB_PATH="from-dotenv.db"\n', encoding="utf-8")
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
    def test_argv_matches_updater_module_only(self) -> None:
        self.assertTrue(is_ingestion_argv(["/opt/macrobot/.venv/bin/python", "-m", "updater"]))
        self.assertTrue(is_ingestion_argv(["python3", "-u", "-m", "updater"]))
        self.assertFalse(is_ingestion_argv(["python", "-m", "dashboard"]))
        self.assertFalse(is_ingestion_argv(["python", "-m", "updater.sources"]))
        self.assertFalse(is_ingestion_argv(["python3", "-c", "import updater"]))
        self.assertFalse(is_ingestion_argv(["python", "/opt/macrobot/updater/__main__.py"]))
        self.assertFalse(is_ingestion_argv(["python", "main.py"]))
        self.assertFalse(is_ingestion_argv(["vim", "-m", "updater"]))
        self.assertFalse(is_ingestion_argv([]))

    def test_live_process_scan_ignores_this_process_and_sees_updater(self) -> None:
        own = Path(f"/proc/{os.getpid()}/cmdline").read_bytes()
        own_args = [part for part in own.decode().split("\0") if part]
        self.assertFalse(is_ingestion_argv(own_args))

        if ingestion_running():
            self.skipTest("python -m updater is already running on this host")

        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "updater"
            package.mkdir()
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "__main__.py").write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
            proc = subprocess.Popen([sys.executable, "-m", "updater"], cwd=tmp)
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


class ApiTests(unittest.TestCase):
    def test_job_route(self) -> None:
        last_run = (datetime.now(timezone.utc) - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "macrobot.db"
            _build_db(path, last_run, "ok")
            payload = _get_route(path, "/api/job")
        self.assertEqual(tuple(payload), JOB_FIELDS)
        self.assertEqual(payload["last_run_at"], last_run)
        self.assertEqual(payload["last_run_status"], "ok")
        self.assertFalse(payload["stale"])
        self.assertEqual(payload["ingestion_running"], ingestion_running())
        self.assertIsNone(payload["error"])
        self.assertNotIn("indicator_count", payload)
        self.assertNotIn("observation_count", payload)
        self.assertNotIn("snapshot", payload)
        self.assertNotIn("db_size_bytes", payload)

    def test_stats_route(self) -> None:
        last_run = (datetime.now(timezone.utc) - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "macrobot.db"
            _build_db(path, last_run, "ok")
            size = path.stat().st_size
            payload = _get_route(path, "/api/stats")
        self.assertEqual(tuple(payload), STATS_FIELDS)
        self.assertEqual(payload["indicator_count"], 3)
        self.assertEqual(payload["indicators_with_observations"], 2)
        self.assertEqual(payload["observation_count"], 3)
        self.assertEqual(payload["newest_observation_date"], "2026-10-03")
        self.assertEqual(payload["db_size_bytes"], size)
        self.assertIsNone(payload["error"])
        self.assertNotIn("last_run_at", payload)
        self.assertNotIn("last_run_status", payload)
        self.assertNotIn("stale", payload)
        self.assertNotIn("ingestion_running", payload)
        self.assertNotIn("snapshot", payload)

    def test_snapshot_route(self) -> None:
        last_run = (datetime.now(timezone.utc) - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "macrobot.db"
            _build_db(path, last_run, "ok")
            payload = _get_route(path, "/api/snapshot")
        self.assertEqual(tuple(payload), SNAPSHOT_RESPONSE_FIELDS)
        self.assertIsNone(payload["error"])
        rows = payload["snapshot"]
        self.assertEqual([row["key"] for row in rows], ["cpi", "us10y", "vix"])
        for row in rows:
            self.assertEqual(tuple(row), SNAPSHOT_FIELDS)
        by_key = {row["key"]: row for row in rows}
        self.assertIsNone(by_key["cpi"]["value"])
        self.assertIsNone(by_key["cpi"]["date"])
        self.assertEqual(by_key["vix"]["value"], 20.5)
        self.assertEqual(by_key["vix"]["date"], "2026-10-01")
        self.assertEqual(by_key["vix"]["label"], "VIX <script>")
        self.assertEqual(by_key["us10y"]["value"], 4.25)
        self.assertNotEqual(by_key["vix"]["value"], 99.0)
        self.assertNotIn("indicator_count", payload)
        self.assertNotIn("last_run_at", payload)
        self.assertNotIn("ingestion_running", payload)
        self.assertNotIn("db_size_bytes", payload)

    def test_combined_status_route_is_gone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "macrobot.db"
            _build_db(path, "2026-10-03 18:00:00", "ok")
            server = make_server(0, path)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                _host, port = server.server_address
                with self.assertRaises(HTTPError) as caught:
                    urlopen(f"http://127.0.0.1:{port}/api/status")
                self.assertEqual(caught.exception.code, 404)
            finally:
                server.shutdown()
                server.server_close()


class PageTests(unittest.TestCase):
    def test_page_calls_three_routes_once_and_credits_voidvexa(self) -> None:
        page = Path(__file__).resolve().parent.joinpath("web", "src", "App.jsx").read_text(encoding="utf-8")
        styles = Path(__file__).resolve().parent.joinpath("web", "src", "styles.css").read_text(encoding="utf-8")
        self.assertIn('getJson("/api/job")', page)
        self.assertIn('getJson("/api/stats")', page)
        self.assertIn('getJson("/api/snapshot")', page)
        self.assertNotIn("/api/status", page)
        self.assertNotIn("setInterval", page)
        self.assertLess(page.index("latest snapshot"), page.index("<h2>status</h2>"))
        self.assertIn(">ALMA<", page)
        self.assertNotIn("<footer", page)
        self.assertNotIn("</footer>", page)
        self.assertIn("powered by ©voidvexa", page)
        self.assertNotIn("footer", styles)
        self.assertIn(".credit", styles)


class IsolationTests(unittest.TestCase):
    def test_dashboard_source_does_not_import_ingestion(self) -> None:
        root = Path(__file__).resolve().parent
        forbidden = {"updater", "yfinance", "pandas", "numpy"}
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

        self.assertNotIn("updater", sys.modules)
        self.assertNotIn("yfinance", sys.modules)
        self.assertNotIn("pandas", sys.modules)
        self.assertNotIn("numpy", sys.modules)


def _get_route(db_path: Path, route: str) -> dict:
    server = make_server(0, db_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        if host != "127.0.0.1":
            raise AssertionError(host)
        with urlopen(f"http://127.0.0.1:{port}{route}") as response:
            body = response.read().decode()
            content_type = response.headers["Content-Type"]
            status = response.status
        if status != 200:
            raise AssertionError(status)
        if "application/json" not in content_type:
            raise AssertionError(content_type)
        if "<html" in body.lower():
            raise AssertionError(body)
        return json.loads(body)
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    unittest.main()
