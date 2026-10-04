"""One ingestion run, observed through the SQLite file it writes."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from checker import run_check
from config import settings
from db import init_db


@contextmanager
def _fresh_db():
    previous = settings.sqlite_db_path
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "macrobot.db"
        settings.sqlite_db_path = str(path)
        try:
            yield path
        finally:
            settings.sqlite_db_path = previous


def _read(path: Path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    observations = {
        (row["series_key"], row["date"]): row["value"]
        for row in conn.execute("SELECT series_key, date, value FROM observations")
    }
    meta = {row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM meta")}
    labels = {
        row["key"]: row["label"]
        for row in conn.execute("SELECT key, label FROM series_metadata")
    }
    conn.close()
    return observations, meta, labels


def _full():
    fred = {
        "sofr": {"value": 5.31, "date": "2026-10-02"},
        "effr": {"value": 5.33, "date": "2026-10-01"},
        "walcl": {"value": 7000.5, "date": "2026-09-30"},
        "rrp": {"value": 400.0, "date": "2026-10-02"},
    }
    live = {"vix": {"value": 18.5, "date": "2026-10-01"}}
    treasury = {"tga": {"value": 800.0, "date": "2026-10-02"}}
    return fred, live, treasury


def _run(fred, live, treasury) -> None:
    with (
        patch("checker.fetch_fred_data", return_value=fred),
        patch("checker.fetch_live_data", return_value=live),
        patch("checker.fetch_treasury_data", return_value=treasury),
    ):
        run_check()


class CheckTests(unittest.TestCase):
    def test_run_records_fetched_rows_and_derived_series(self) -> None:
        with _fresh_db() as path:
            init_db()
            fred, live, treasury = _full()
            _run(fred, live, treasury)
            observations, meta, _labels = _read(path)
        self.assertEqual(observations[("vix", "2026-10-01")], 18.5)
        self.assertEqual(observations[("sofr", "2026-10-02")], 5.31)
        self.assertEqual(observations[("effr", "2026-10-01")], 5.33)
        self.assertEqual(observations[("walcl", "2026-09-30")], 7000.5)
        self.assertEqual(observations[("rrp", "2026-10-02")], 400.0)
        self.assertEqual(observations[("tga", "2026-10-02")], 800.0)
        self.assertEqual(observations[("sofr_effr_spread", "2026-10-02")], -0.02)
        self.assertEqual(observations[("fed_net_liquidity", "2026-10-02")], 5800.5)
        self.assertEqual(len(observations), 8)
        self.assertEqual(meta["last_run_status"], "ok")

    def test_a_new_date_adds_a_second_row(self) -> None:
        with _fresh_db() as path:
            init_db()
            fred, live, treasury = _full()
            _run(fred, live, treasury)
            live["vix"] = {"value": 21.0, "date": "2026-10-02"}
            _run(fred, live, treasury)
            observations, _meta, _labels = _read(path)
        self.assertEqual(observations[("vix", "2026-10-01")], 18.5)
        self.assertEqual(observations[("vix", "2026-10-02")], 21.0)

    def test_same_day_value_replaces_the_row_and_a_tiny_change_does_not(self) -> None:
        with _fresh_db() as path:
            init_db()
            fred, live, treasury = _full()
            _run(fred, live, treasury)
            live["vix"] = {"value": 19.0, "date": "2026-10-01"}
            _run(fred, live, treasury)
            observations, _meta, _labels = _read(path)
            self.assertEqual(observations[("vix", "2026-10-01")], 19.0)
            self.assertEqual(sum(1 for key, _date in observations if key == "vix"), 1)
            live["vix"] = {"value": 19.00005, "date": "2026-10-01"}
            _run(fred, live, treasury)
            observations, _meta, _labels = _read(path)
        self.assertEqual(observations[("vix", "2026-10-01")], 19.0)

    def test_older_feed_date_is_left_out(self) -> None:
        with _fresh_db() as path:
            init_db()
            fred, live, treasury = _full()
            _run(fred, live, treasury)
            live["vix"] = {"value": 99.0, "date": "2026-09-01"}
            _run(fred, live, treasury)
            observations, meta, _labels = _read(path)
        self.assertEqual(observations[("vix", "2026-10-01")], 18.5)
        self.assertNotIn(("vix", "2026-09-01"), observations)
        self.assertEqual(meta["last_run_status"], "ok")

    def test_all_empty_sources_record_failed_and_write_nothing(self) -> None:
        with _fresh_db() as path:
            init_db()
            _run({}, {}, {})
            observations, meta, _labels = _read(path)
        self.assertEqual(observations, {})
        self.assertEqual(meta["last_run_status"], "failed")

    def test_one_empty_source_records_partial_and_skips_derived_series(self) -> None:
        with _fresh_db() as path:
            init_db()
            _fred, live, treasury = _full()
            _run({}, live, treasury)
            observations, meta, _labels = _read(path)
        self.assertEqual(
            observations,
            {
                ("vix", "2026-10-01"): 18.5,
                ("tga", "2026-10-02"): 800.0,
            },
        )
        self.assertEqual(meta["last_run_status"], "partial")

    def test_unknown_key_is_not_stored(self) -> None:
        with _fresh_db() as path:
            init_db()
            fred, live, treasury = _full()
            fred["nope"] = {"value": 1.0, "date": "2026-10-02"}
            _run(fred, live, treasury)
            observations, meta, _labels = _read(path)
        self.assertFalse(any(key == "nope" for key, _date in observations))
        self.assertEqual(observations[("vix", "2026-10-01")], 18.5)
        self.assertEqual(meta["last_run_status"], "ok")

    def test_init_db_restores_a_changed_label(self) -> None:
        with _fresh_db() as path:
            init_db()
            conn = sqlite3.connect(path)
            conn.execute("UPDATE series_metadata SET label = 'changed' WHERE key = 'vix'")
            conn.commit()
            conn.close()
            init_db()
            _observations, _meta, labels = _read(path)
        self.assertEqual(labels["vix"], "VIX")
        self.assertEqual(labels["fed_net_liquidity"], "Net Liq")
        self.assertEqual(labels["sofr_effr_spread"], "SOFR-EFFR")
        self.assertEqual(len(labels), 43)

    def test_init_db_keeps_the_latest_duplicate_row(self) -> None:
        with _fresh_db() as path:
            conn = sqlite3.connect(path)
            conn.executescript(
                """
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
                INSERT INTO series_metadata (key, label, unit, source, threshold, description)
                VALUES ('vix', 'VIX', '', 'live', 1.0, '');
                INSERT INTO observations (series_key, date, value) VALUES ('vix', '2026-10-01', 10.0);
                INSERT INTO observations (series_key, date, value) VALUES ('vix', '2026-10-01', 12.5);
                """
            )
            conn.commit()
            conn.close()
            init_db()
            observations, _meta, _labels = _read(path)
        self.assertEqual(observations[("vix", "2026-10-01")], 12.5)
        self.assertEqual(sum(1 for key, _date in observations if key == "vix"), 1)


if __name__ == "__main__":
    unittest.main()
