import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional
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
    {"key": "payems", "label": "Payrolls", "unit": " K", "source": "fred", "threshold": 0.0, "description": "All Employees, Total Nonfarm (thousands of persons)"},
    {"key": "icsa", "label": "Initial Claims", "unit": "", "source": "fred", "threshold": 0.0, "description": "Initial Jobless Claims (weekly, seasonally adjusted)"},
    {"key": "unrate", "label": "Unemployment", "unit": "%", "source": "fred", "threshold": 0.0, "description": "Unemployment Rate"},
    {"key": "indpro", "label": "Ind. Production", "unit": "%", "source": "fred", "threshold": 0.0, "description": "Industrial Production: Total Index (YoY)"},
    {"key": "rsafs", "label": "Retail Sales", "unit": " B", "source": "fred", "threshold": 0.0, "description": "Advance Retail Sales: Retail Trade and Food Services"},
    {"key": "core_pce", "label": "Core PCE", "unit": "%", "source": "fred", "threshold": 0.0, "description": "Core PCE Price Index (YoY, Excluding Food and Energy)"},
    {"key": "tga_weekly", "label": "TGA (Weekly)", "unit": " B", "source": "fred", "threshold": 0.0, "description": "Treasury General Account, Wednesday Level (H.4.1)"},
    {"key": "m2sl", "label": "M2", "unit": " B", "source": "fred", "threshold": 0.0, "description": "M2 Money Stock"},
    {"key": "totbkcr", "label": "Bank Credit", "unit": " B", "source": "fred", "threshold": 0.0, "description": "Bank Credit, All Commercial Banks"},
    {"key": "dtwexbgs", "label": "Broad USD", "unit": "", "source": "fred", "threshold": 0.0, "description": "Nominal Broad U.S. Dollar Index"},
    {"key": "t10y2y", "label": "10Y-2Y", "unit": "%", "source": "fred", "threshold": 0.0, "description": "10-Year minus 2-Year Treasury Constant Maturity Spread"},
    {"key": "cfnai", "label": "CFNAI", "unit": "", "source": "fred", "threshold": 0.0, "description": "Chicago Fed National Activity Index (0 = trend growth)"},
    {"key": "permit", "label": "Permits", "unit": " K", "source": "fred", "threshold": 0.0, "description": "New Private Housing Units Authorized by Building Permits (thousands of units, SAAR)"},
    {"key": "real_pce", "label": "Real PCE", "unit": " B", "source": "fred", "threshold": 0.0, "description": "Real Personal Consumption Expenditures (PCEC96, billions of chained 2017 dollars, SAAR)"},
    {"key": "real_gdp", "label": "Real GDP", "unit": " B", "source": "fred", "threshold": 0.0, "description": "Real Gross Domestic Product (GDPC1, billions of chained 2017 dollars, SAAR)"},
    {"key": "ccsa", "label": "Continued Claims", "unit": "", "source": "fred", "threshold": 0.0, "description": "Continued Claims (Insured Unemployment, weekly, seasonally adjusted)"},
    {"key": "pce", "label": "PCE", "unit": "%", "source": "fred", "threshold": 0.0, "description": "PCE Price Index (PCEPI, YoY)"},
    {"key": "ppi", "label": "PPI", "unit": "%", "source": "fred", "threshold": 0.0, "description": "Producer Price Index: Final Demand (PPIFIS, YoY)"},
    {"key": "ahe", "label": "Hourly Earnings", "unit": " $/hr", "source": "fred", "threshold": 0.0, "description": "Average Hourly Earnings of All Employees, Total Private (CES0500000003)"},
    {"key": "t5yie", "label": "5Y Breakeven", "unit": "%", "source": "fred", "threshold": 0.0, "description": "5-Year Breakeven Inflation Rate"},
    {"key": "t5yifr", "label": "5Y5Y Forward", "unit": "%", "source": "fred", "threshold": 0.0, "description": "5-Year, 5-Year Forward Inflation Expectation Rate"},
    {"key": "wresbal", "label": "Reserves", "unit": " B", "source": "fred", "threshold": 0.0, "description": "Reserve Balances with Federal Reserve Banks (H.4.1 week average)"},
    {"key": "nfci", "label": "NFCI", "unit": "", "source": "fred", "threshold": 0.0, "description": "Chicago Fed National Financial Conditions Index (positive = tighter than average)"},
    {"key": "stlfsi4", "label": "STL FSI", "unit": "", "source": "fred", "threshold": 0.0, "description": "St. Louis Fed Financial Stress Index (positive = above-average stress)"},
    {"key": "t10y3m", "label": "10Y-3M", "unit": "%", "source": "fred", "threshold": 0.0, "description": "10-Year minus 3-Month Treasury Constant Maturity Spread"},
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
    # WAL + busy_timeout so a concurrent reader (e.g. an agent querying this
    # file directly) doesn't hit "database is locked" during our brief write.
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
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

            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            -- One row per (series, date) is the core invariant. Databases
            -- created before this constraint existed may hold duplicates, so
            -- collapse them (keeping the most recently written) before the
            -- unique index is applied.
            DELETE FROM observations
            WHERE id NOT IN (
                SELECT MAX(id) FROM observations GROUP BY series_key, date
            );

            DROP INDEX IF EXISTS idx_obs_key_date;
            CREATE UNIQUE INDEX IF NOT EXISTS idx_obs_key_date ON observations(series_key, date);
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
    # Latest is decided by `date`, not by insertion order: a feed that briefly
    # reports an older date must not be able to masquerade as the newest value.
    with get_db_connection(custom_path) as conn:
        cursor = conn.execute("""
            SELECT o.id, o.series_key, o.date, o.value, o.recorded_at
            FROM observations o
            INNER JOIN (
                SELECT series_key, MAX(date) AS max_date
                FROM observations
                GROUP BY series_key
            ) latest
              ON o.series_key = latest.series_key AND o.date = latest.max_date
        """)
        return {row["series_key"]: dict(row) for row in cursor.fetchall()}


def upsert_observation(series_key: str, date: str, value: float, custom_path: Optional[str] = None) -> None:
    # Atomic insert-or-update keyed on (series_key, date), so two overlapping
    # runs can't create duplicate rows for the same day.
    with get_db_connection(custom_path) as conn:
        conn.execute("""
            INSERT INTO observations (series_key, date, value, recorded_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(series_key, date) DO UPDATE SET
                value = excluded.value,
                recorded_at = datetime('now')
        """, (series_key, date, value))


def record_run(status: str, custom_path: Optional[str] = None) -> None:
    """Stamp when the job last ran and how it went ('ok' | 'partial' | 'failed').

    Lets a consumer tell "the data is quiet" apart from "the job is dead".
    """
    with get_db_connection(custom_path) as conn:
        conn.execute("""
            INSERT INTO meta (key, value, updated_at)
            VALUES ('last_run_status', ?, datetime('now'))
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = datetime('now')
        """, (status,))
        conn.execute("""
            INSERT INTO meta (key, value, updated_at)
            VALUES ('last_run_at', datetime('now'), datetime('now'))
            ON CONFLICT(key) DO UPDATE SET
                value = datetime('now'),
                updated_at = datetime('now')
        """)


def get_meta(key: str, custom_path: Optional[str] = None) -> Optional[str]:
    with get_db_connection(custom_path) as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None
