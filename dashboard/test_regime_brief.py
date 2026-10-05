"""Regime brief scoring. Temporary databases, no network."""

from __future__ import annotations

import math
import sqlite3
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from urllib.request import urlopen

from dashboard.regime_brief import (
    RELEASE_RULE,
    UNMAPPED,
    VERSION,
    brief_payload,
    load_regime_brief,
)
from dashboard.server import make_server

START = date(2025, 1, 2)
END = date(2026, 10, 2)
NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
SPIKE = date(2026, 9, 19)

SCHEMA = """
CREATE TABLE observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    series_key TEXT NOT NULL,
    date TEXT NOT NULL,
    value REAL NOT NULL,
    recorded_at TEXT NOT NULL
);
"""


def _months(day: date) -> int:
    return (day.year - START.year) * 12 + (day.month - START.month)


def _wave(day: date) -> float:
    """Variation inside the z-score window, flat before the scored weeks."""
    if day > date(2026, 4, 30):
        return 0.0
    index = (day - START).days
    return math.sin(index / 10.0) + 0.4 * math.sin(index / 4.0)


def _level(day: date, base: float, amplitude: float, spike: float, spiked: bool) -> float:
    value = base + amplitude * _wave(day)
    if spiked and day >= SPIKE:
        return value + spike
    return value


def _seed(path: Path, spike: bool, stale_tga: bool = False) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA)
        rows: list[tuple] = []
        day = START
        while day <= END:
            stamp = f"{day.isoformat()} 18:00:00"
            if day.weekday() < 5:
                rows.append(("hy_spread", day, _level(day, 320.0, 6.0, -50.0, spike), stamp))
                rows.append(("move", day, _level(day, 90.0, 6.0, 50.0, spike), stamp))
                rows.append(("vix", day, _level(day, 16.0, 0.8, 14.0, spike), stamp))
                rows.append(("rrp", day, 12.0 - (day - START).days * 0.01, stamp))
                if not stale_tga or day <= date(2026, 8, 1):
                    rows.append(("tga", day, 820.0 - (day - START).days * 0.02, stamp))
                rows.append(("fed_net_liquidity", day, 5900.0 - (day - START).days * 0.4, stamp))
            if day.weekday() == 4:
                rows.append(("icsa", day, 218000.0 if day >= date(2026, 9, 5) else 224000.0, stamp))
                rows.append(("nfci", day, -0.32, stamp))
                rows.append(("stlfsi4", day, 0.41 if spike and day >= SPIKE else -0.41, stamp))
            if day.day == 1:
                month = _months(day)
                rows.append(("payems", day, 150000.0 + month * 30.0, stamp))
                rows.append(("unrate", day, 4.2, stamp))
                rows.append(("cfnai", day, 0.12, stamp))
                rows.append(("real_pce", day, 17000.0 - month * 10.0, stamp))
                rows.append(("core_pce", day, 3.6 - month * 0.1, stamp))
                rows.append(("core_cpi", day, 3.9 - month * 0.1, stamp))
                rows.append(("cpi", day, 4.2 - month * 0.1, stamp))
                rows.append(("ahe", day, 4.4 - month * 0.1, stamp))
            day += timedelta(days=1)
        # Written after the read, and a future print. Neither may enter the score.
        rows.append(("payems", date(2026, 10, 1), 1.0, "2026-10-04 00:00:00"))
        rows.append(("payems", date(2026, 10, 4), 1.0, "2026-10-03 18:00:00"))
        conn.executemany(
            "INSERT INTO observations (series_key, date, value, recorded_at) VALUES (?, ?, ?, ?)",
            [(key, when.isoformat(), value, recorded) for key, when, value, recorded in rows],
        )
        conn.commit()
    finally:
        conn.close()


def _by_id(checks: list[dict]) -> dict[str, dict]:
    return {check["id"]: check for check in checks}


class RegimeBriefTests(TestCase):
    def test_goldilocks_is_unchanged_when_history_agrees(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "macrobot.db"
            _seed(path, spike=False)
            brief = load_regime_brief(path, now=NOW)
        payload = brief_payload(brief)
        self.assertEqual(payload["version"], VERSION)
        self.assertEqual(payload["as_of"], "2026-10-02")
        self.assertEqual(payload["release_rule"], RELEASE_RULE)
        self.assertEqual(list(payload["unmapped"]), list(UNMAPPED))
        self.assertIsNone(payload["error"])

        economy = payload["economy"]
        self.assertEqual(economy["name"], "Goldilocks")
        self.assertEqual(economy["qualifier"], "soft")
        self.assertEqual(economy["status"], "unchanged")
        self.assertEqual(economy["raw"], "Goldilocks")
        self.assertEqual(
            economy["why"],
            "Growth is up and inflation is cooling, so the map stays in Goldilocks.",
        )
        self.assertEqual(economy["growth"], {"direction": "UP", "score": 4, "of": 5, "threshold": 3})
        self.assertEqual(economy["inflation"]["direction"], "DOWN")
        self.assertEqual(economy["inflation"]["net"], -4)
        checks = _by_id(economy["checks"])
        self.assertEqual(checks["g1"]["result"], "PASS")
        self.assertTrue(checks["g1"]["value"].startswith("3m +"))
        self.assertEqual(checks["g2"]["result"], "PASS")
        self.assertEqual(checks["g5"]["result"], "FAIL")
        self.assertTrue(checks["g5"]["value"].startswith("3m ann. \u2212"))
        for key in ("i1", "i2", "i3", "i4"):
            self.assertEqual(checks[key]["result"], "DOWN", key)
        self.assertTrue(all(not week["diverged"] for week in economy["weeks"]))
        self.assertEqual(len(economy["weeks"]), 5)

        liquidity = payload["liquidity"]
        self.assertEqual(liquidity["name"], "Calm")
        self.assertEqual(liquidity["status"], "unchanged")
        self.assertEqual(liquidity["raw"], "Calm")
        self.assertIsNone(liquidity["toward"])
        self.assertEqual(liquidity["stress"]["score"], 0)
        self.assertEqual(liquidity["trend"]["direction"], "FLAT")
        self.assertEqual(
            liquidity["why"],
            "Stress is 0/5 and the phase stays Calm.",
        )
        stress = _by_id(liquidity["checks"])
        for key in ("s1", "s2", "s3", "s4", "s5"):
            self.assertEqual(stress[key]["result"], "FAIL", key)
        self.assertEqual(stress["t1"]["result"], "FLAT")
        self.assertEqual(stress["spec"]["result"], "OFF")
        self.assertEqual(payload["context"]["speculation_gate"]["state"], "off")
        self.assertEqual(payload["context"]["speculation_gate"]["rule"], "HY 2w z < \u22121.5")
        flags = {flag["id"] for flag in payload["context"]["flags"]}
        self.assertIn("tentative", flags)
        self.assertNotIn("stale", flags)

    def test_pending_hysteresis_keeps_calm_until_the_third_week(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "macrobot.db"
            _seed(path, spike=True, stale_tga=True)
            brief = load_regime_brief(path, now=NOW)
        payload = brief_payload(brief)
        liquidity = payload["liquidity"]
        self.assertEqual(liquidity["name"], "Calm")
        self.assertEqual(liquidity["raw"], "Turbulence")
        self.assertEqual(liquidity["status"], "pending")
        self.assertEqual(liquidity["pending_week"], 2)
        self.assertEqual(liquidity["status_label"], "pending · 2nd week")
        self.assertEqual(liquidity["toward"], "Turbulence")
        self.assertEqual(liquidity["arrow"], "up")
        self.assertEqual(liquidity["why"], "Raw Turbulence for 2 weeks. Confirms on the 3rd.")
        self.assertGreaterEqual(liquidity["stress"]["score"], 3)
        stress = _by_id(liquidity["checks"])
        self.assertEqual(stress["s1"]["result"], "FAIL")
        self.assertEqual(stress["s2"]["result"], "PASS")
        self.assertEqual(stress["s3"]["result"], "PASS")
        self.assertEqual(stress["s5"]["result"], "PASS")
        self.assertEqual(stress["spec"]["result"], "ON")
        self.assertEqual(payload["context"]["speculation_gate"]["state"], "on")
        diverged = [week for week in liquidity["weeks"] if week["diverged"]]
        self.assertEqual([week["date"] for week in diverged], ["2026-09-25", "2026-10-02"])
        self.assertTrue(any(flag["id"] == "stale" and "tga" in flag["series"] for flag in payload["context"]["flags"]))
        self.assertEqual(payload["economy"]["name"], "Goldilocks")
        self.assertEqual(payload["economy"]["status"], "unchanged")

    def test_route_returns_the_brief(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "macrobot.db"
            _seed(path, spike=False)
            server = make_server(0, path)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                self.assertEqual(host, "127.0.0.1")
                with urlopen(f"http://127.0.0.1:{port}/api/regime-brief") as response:
                    body = response.read().decode()
                    self.assertEqual(response.status, 200)
                    self.assertIn("application/json", response.headers["Content-Type"])
            finally:
                server.shutdown()
                server.server_close()
        self.assertIn('"version": "1.0.0"', body)
        self.assertIn("Goldilocks", body)
        self.assertNotIn("<html", body.lower())

    def test_missing_database(self) -> None:
        brief = load_regime_brief(Path("/tmp/does-not-exist-macrobot.db"), now=NOW)
        payload = brief_payload(brief)
        self.assertFalse(payload["db_exists"])
        self.assertIsNone(payload["economy"])
        self.assertIsNone(payload["error"])
