"""Read macrobot.db the way DB_INTEGRATION.md describes, and nothing else.

The connection is `mode=ro`. Do not import `checker`, `macro`, or `db`:
`db.get_db_connection` opens the file writable and turns on WAL, which is a
write. The cron job already enables WAL, so a reader can run while it writes.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Cron is `0 */2 * * *`. A last_run_at older than that cadence is stale.
CRON_CADENCE = timedelta(hours=2)
DEFAULT_DB_PATH = "data/macrobot.db"

# One statement per feature. Job reads meta. Stats counts. Snapshot is latest-by-date.
JOB_SQL = "SELECT key, value FROM meta"

STATS_SQL = """
SELECT
    (SELECT COUNT(*) FROM series_metadata) AS indicator_count,
    (
        SELECT COUNT(*) FROM series_metadata m
        WHERE EXISTS (
            SELECT 1 FROM observations o WHERE o.series_key = m.key
        )
    ) AS indicators_with_observations,
    (SELECT COUNT(*) FROM observations) AS observation_count,
    (SELECT MAX(date) FROM observations) AS newest_observation_date
"""

SNAPSHOT_SQL = """
SELECT
    m.key,
    m.label,
    o.value,
    m.unit,
    o.date
FROM series_metadata m
LEFT JOIN (
    SELECT o1.series_key, o1.value, o1.date
    FROM observations o1
    INNER JOIN (
        SELECT series_key, MAX(date) AS max_date
        FROM observations
        GROUP BY series_key
    ) latest
      ON o1.series_key = latest.series_key AND o1.date = latest.max_date
) o ON m.key = o.series_key
ORDER BY m.source, m.key
"""


@dataclass(frozen=True)
class SnapshotRow:
    key: str
    label: str
    value: float | None
    unit: str | None
    date: str | None


@dataclass(frozen=True)
class JobStatus:
    db_path: str
    db_exists: bool
    error: str | None
    last_run_at: str | None
    last_run_status: str | None
    stale: bool | None
    ingestion_running: bool


@dataclass(frozen=True)
class Stats:
    db_path: str
    db_exists: bool
    db_size_bytes: int | None
    error: str | None
    indicator_count: int | None
    indicators_with_observations: int | None
    observation_count: int | None
    newest_observation_date: str | None


@dataclass(frozen=True)
class Snapshot:
    db_path: str
    db_exists: bool
    error: str | None
    rows: tuple[SnapshotRow, ...]


@dataclass(frozen=True)
class _Read:
    rows: tuple[sqlite3.Row, ...] | None
    db_exists: bool
    error: str | None


def resolve_db_path(explicit: str | None = None) -> Path:
    """Same path the job uses: env, then `.env`, then `data/macrobot.db`.

    `config.py` loads `SQLITE_DB_PATH` that way. Relative paths stay relative
    to the current working directory, so start this process from the repo root.
    """
    raw = (explicit or "").strip()
    if not raw:
        raw = os.environ.get("SQLITE_DB_PATH", "").strip()
    if not raw:
        raw = _dotenv_value(Path.cwd() / ".env", "SQLITE_DB_PATH")
    if not raw:
        raw = DEFAULT_DB_PATH
    return Path(raw)


def connect(db_path: Path) -> sqlite3.Connection:
    """Open the database with no write privilege.

    `mode=ro` refuses writes even when the file itself is writable.
    `query_only` is a second lock on this connection. `journal_mode` is left
    alone: setting WAL would write the file.
    """
    uri = f"{db_path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def load_job(db_path: Path, now: datetime | None = None) -> JobStatus:
    """Last run, its status, staleness, and whether `python main.py` is running.

    One query of `meta`. The process check reads `/proc`, not SQLite.
    """
    running = ingestion_running()
    path_text = str(db_path)
    read = _read_one(db_path, JOB_SQL)
    if read.rows is None:
        return JobStatus(
            db_path=path_text,
            db_exists=read.db_exists,
            error=read.error,
            last_run_at=None,
            last_run_status=None,
            stale=None,
            ingestion_running=running,
        )
    meta = {row["key"]: row["value"] for row in read.rows}
    last_run_at = meta.get("last_run_at")
    moment = now or datetime.now(timezone.utc)
    return JobStatus(
        db_path=path_text,
        db_exists=True,
        error=None,
        last_run_at=last_run_at,
        last_run_status=meta.get("last_run_status"),
        stale=is_stale(last_run_at, moment),
        ingestion_running=running,
    )


def load_stats(db_path: Path) -> Stats:
    """Counts, newest observation date, and the database file size.

    One SQL statement. File size is `stat`, beside that query.
    """
    path_text = str(db_path)
    size = db_path.stat().st_size if db_path.is_file() else None
    read = _read_one(db_path, STATS_SQL)
    if read.rows is None:
        return Stats(
            db_path=path_text,
            db_exists=read.db_exists,
            db_size_bytes=size,
            error=read.error,
            indicator_count=None,
            indicators_with_observations=None,
            observation_count=None,
            newest_observation_date=None,
        )
    row = read.rows[0]
    return Stats(
        db_path=path_text,
        db_exists=True,
        db_size_bytes=size,
        error=None,
        indicator_count=int(row["indicator_count"] or 0),
        indicators_with_observations=int(row["indicators_with_observations"] or 0),
        observation_count=int(row["observation_count"] or 0),
        newest_observation_date=row["newest_observation_date"],
    )


def load_snapshot(db_path: Path) -> Snapshot:
    """Latest row per series by MAX(date): key, label, value, unit, date."""
    path_text = str(db_path)
    read = _read_one(db_path, SNAPSHOT_SQL)
    if read.rows is None:
        return Snapshot(
            db_path=path_text,
            db_exists=read.db_exists,
            error=read.error,
            rows=(),
        )
    rows = tuple(
        SnapshotRow(
            key=row["key"],
            label=row["label"],
            value=row["value"],
            unit=row["unit"],
            date=row["date"],
        )
        for row in read.rows
    )
    return Snapshot(db_path=path_text, db_exists=True, error=None, rows=rows)


def _read_one(db_path: Path, sql: str) -> _Read:
    """Run one statement. A missing file is not created and is not queried."""
    if not db_path.is_file():
        return _Read(rows=None, db_exists=False, error=None)
    try:
        with closing(connect(db_path)) as conn:
            return _Read(rows=tuple(conn.execute(sql)), db_exists=True, error=None)
    except sqlite3.Error as exc:
        return _Read(rows=None, db_exists=True, error=str(exc))


def is_stale(last_run_at: str | None, now: datetime) -> bool:
    """True when the last run is missing or older than the two-hour cadence."""
    parsed = parse_run_timestamp(last_run_at)
    if parsed is None:
        return True
    return now - parsed > CRON_CADENCE


def parse_run_timestamp(value: str | None) -> datetime | None:
    """Parse `meta.last_run_at`. The job writes SQLite `datetime('now')`, UTC."""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def ingestion_running() -> bool:
    """True while `python main.py` is in the process list on this host.

    Between cron runs the job has exited, so the honest status is idle.
    `python -m dashboard` is not a match.
    """
    own = os.getpid()
    for pid, args in _process_argvs():
        if pid == own:
            continue
        if is_ingestion_argv(args):
            return True
    return False


def is_ingestion_argv(args: list[str]) -> bool:
    """Whether this argv is the ingestion job (`python main.py`).

    Module and `-c` invocations are excluded so the dashboard process, and
    anything that merely mentions `main.py` inside Python code, does not count.
    """
    if not args or not _is_python(args[0]):
        return False
    if "-m" in args or "-c" in args:
        return False
    return any(Path(arg).name == "main.py" for arg in args[1:] if not arg.startswith("-"))


def _is_python(argv0: str) -> bool:
    name = Path(argv0).name
    return name == "python" or name.startswith("python3")


def _process_argvs() -> list[tuple[int, list[str]]]:
    proc = Path("/proc")
    found: list[tuple[int, list[str]]] = []
    if not proc.is_dir():
        return found
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        args = [part for part in raw.decode("utf-8", "replace").split("\0") if part]
        if args:
            found.append((int(entry.name), args))
    return found


def _dotenv_value(path: Path, key: str) -> str:
    if not path.is_file():
        return ""
    found = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].strip()
        if "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        if name.strip() != key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        found = value.strip()
    return found
