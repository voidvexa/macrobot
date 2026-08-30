import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Generator, Optional
from config import settings

# `threshold` is not enforced by this app (there's no alerting logic here
# anymore) — it's descriptive metadata for a downstream consumer deciding
# what counts as a notable move for a given indicator.
DEFAULT_SERIES_METADATA = [
    {"key": "vix", "label": "VIX", "unit": "", "source": "live", "threshold": 1.0, "description": "CBOE Volatility Index"},
    {"key": "move", "label": "MOVE", "unit": "", "source": "live", "threshold": 0.0, "description": "ICE BofA MOVE Index"},
    {"key": "skew", "label": "SKEW", "unit": "", "source": "live", "threshold": 0.0, "description": "CBOE SKEW Index"},
    {"key": "us10y", "label": "10Y Yield", "unit": "%", "source": "fred", "threshold": 0.0, "description": "10-Year Treasury Constant Maturity Rate"},
    {"key": "hy_spread", "label": "HY Spread", "unit": " bps", "source": "fred", "threshold": 0.0, "description": "ICE BofA US High Yield Option-Adjusted Spread"},
    {"key": "ccc_spread", "label": "CCC Spread", "unit": " bps", "source": "fred", "threshold": 0.0, "description": "ICE BofA CCC & Lower US High Yield OAS"},
    {"key": "ig_spread", "label": "IG Spread", "unit": " bps", "source": "fred", "threshold": 0.0, "description": "ICE BofA US Corporate Index Option-Adjusted Spread"},
    {"key": "cpi", "label": "CPI", "unit": "%", "source": "fred", "threshold": 0.0, "description": "Consumer Price Index for All Urban Consumers (YoY)"},
    {"key": "core_cpi", "label": "Core CPI", "unit": "%", "source": "fred", "threshold": 0.0, "description": "Core CPI (YoY, Less Food and Energy)"},
    {"key": "sofr", "label": "SOFR", "unit": "%", "source": "fred", "threshold": 0.0, "description": "Secured Overnight Financing Rate"},
    {"key": "effr", "label": "EFFR", "unit": "%", "source": "fred", "threshold": 0.0, "description": "Effective Federal Funds Rate"},
    {"key": "sofr_effr_spread", "label": "SOFR-EFFR", "unit": "%", "source": "derived", "threshold": 0.0, "description": "SOFR minus EFFR Spread"},
    {"key": "walcl", "label": "WALCL", "unit": " B", "source": "fred", "threshold": 0.0, "description": "Fed Total Assets (Less Eliminations from Consolidation)"},
    {"key": "rrp", "label": "RRP", "unit": " B", "source": "fred", "threshold": 0.0, "description": "Overnight Reverse Repurchase Agreements"},
    {"key": "tga", "label": "TGA", "unit": " B", "source": "treasury", "threshold": 0.0, "description": "Treasury General Account Closing Balance"},
    {"key": "fed_net_liquidity", "label": "Net Liq", "unit": " B", "source": "derived", "threshold": 0.0, "description": "Fed Net Liquidity (WALCL - RRP - TGA)"},
    {"key": "drtscilm", "label": "C&I Tighten", "unit": "%", "source": "fred", "threshold": 0.0, "description": "Net % of Domestic Banks Tightening Standards for C&I Loans"},
    {"key": "usblr", "label": "Prime Rate", "unit": "%", "source": "fred", "threshold": 0.0, "description": "Bank Prime Loan Rate"},
]


def get_db_path(custom_path: Optional[str] = None) -> Path:
    return Path(custom_path or settings.sqlite_db_path)


@contextmanager
def get_db_connection(custom_path: Optional[str] = None) -> Generator[sqlite3.Connection, None, None]:
    path = get_db_path(custom_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(custom_path: Optional[str] = None) -> None:
    with get_db_connection(custom_path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS series_metadata (
                key TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                unit TEXT NOT NULL,
                source TEXT NOT NULL,
                threshold REAL NOT NULL DEFAULT 0.0,
                description TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                series_key TEXT NOT NULL,
                date TEXT NOT NULL,
                value REAL NOT NULL,
                recorded_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (series_key) REFERENCES series_metadata(key)
            );

            CREATE INDEX IF NOT EXISTS idx_obs_key_date ON observations(series_key, date);
            CREATE INDEX IF NOT EXISTS idx_obs_key_id ON observations(series_key, id DESC);
        """)

        for meta in DEFAULT_SERIES_METADATA:
            conn.execute("""
                INSERT INTO series_metadata (key, label, unit, source, threshold, description)
                VALUES (:key, :label, :unit, :source, :threshold, :description)
                ON CONFLICT(key) DO UPDATE SET
                    label = excluded.label,
                    unit = excluded.unit,
                    source = excluded.source,
                    threshold = excluded.threshold,
                    description = excluded.description
            """, meta)


def get_series_metadata(custom_path: Optional[str] = None) -> dict[str, dict]:
    with get_db_connection(custom_path) as conn:
        cursor = conn.execute("SELECT key, label, unit, source, threshold, description FROM series_metadata")
        return {row["key"]: dict(row) for row in cursor.fetchall()}


def get_latest_observations(custom_path: Optional[str] = None) -> dict[str, dict]:
    with get_db_connection(custom_path) as conn:
        cursor = conn.execute("""
            SELECT o.id, o.series_key, o.date, o.value, o.recorded_at
            FROM observations o
            INNER JOIN (
                SELECT series_key, MAX(id) AS max_id
                FROM observations
                GROUP BY series_key
            ) latest ON o.id = latest.max_id
        """)
        return {row["series_key"]: dict(row) for row in cursor.fetchall()}


def insert_observation(series_key: str, date: str, value: float, custom_path: Optional[str] = None) -> int:
    with get_db_connection(custom_path) as conn:
        cursor = conn.execute("""
            INSERT INTO observations (series_key, date, value, recorded_at)
            VALUES (?, ?, ?, datetime('now'))
        """, (series_key, date, value))
        return cursor.lastrowid


def update_observation(observation_id: int, value: float, custom_path: Optional[str] = None) -> None:
    with get_db_connection(custom_path) as conn:
        conn.execute("""
            UPDATE observations
            SET value = ?, recorded_at = datetime('now')
            WHERE id = ?
        """, (value, observation_id))
