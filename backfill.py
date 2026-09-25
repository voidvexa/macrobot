"""One-off historical backfill. Delete this file once the backfill is done.

Fills `observations` from --start (default 2023-01-01) up to the day before
each series' earliest stored date, so it never touches a row the cron job
wrote. Cutoffs are read from the database, not hard-coded.

    .venv/bin/python backfill.py --dry-run   # fetch + report, write nothing
    .venv/bin/python backfill.py             # backs up the DB, then writes

Backfilled rows get recorded_at = their observation date (midnight), not the
time the script ran, so they read as if recorded when published.

Safe to re-run: inserts are ON CONFLICT DO NOTHING, so existing rows are
never overwritten. A series that was already backfilled gets a new cutoff of
--start and so is skipped; to retry series that failed, use --only.
"""
import argparse
import bisect
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta, timezone

import requests
import yfinance as yf

from config import settings
from db import get_db_connection, get_db_path, init_db
from macro.fred import (
    BPS_SERIES,
    FRED_BASE,
    MILLIONS_TO_BILLIONS_SERIES,
    SERIES as FRED_SERIES,
    YOY_SERIES,
)
from macro.live import LIVE_TICKERS
from macro.treasury import TGA_CLOSING, TREASURY_API, VALUE_FIELD

HTTP_TIMEOUT = 60
MAX_RETRIES = 5

# FRED allows 120 requests/minute per key; ~37 series at one per 1.5s stays
# far below that. Yahoo has no published limit but throttles bursts.
FRED_DELAY = 1.5
YAHOO_DELAY = 5.0

# Pull a year of extra history so pc1 (YoY) values at the start of the window
# are computed, and so derived series have an as-of WALCL for early January.
LOOKBACK_DAYS = 366

DERIVED = {
    "sofr_effr_spread": (("sofr", "effr"), lambda v: round(v["sofr"] - v["effr"], 4)),
    "fed_net_liquidity": (
        ("walcl", "rrp", "tga"),
        lambda v: round(v["walcl"] - v["rrp"] - v["tga"], 3),
    ),
}


def log(msg: str) -> None:
    print(msg, flush=True)


def get_with_retry(url: str, params: dict, label: str) -> requests.Response | None:
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, params=params, timeout=HTTP_TIMEOUT)
        except requests.RequestException as exc:
            # Never print the exception itself: its message embeds the URL,
            # which carries the FRED api_key.
            detail = type(exc).__name__
        else:
            if resp.ok:
                return resp
            detail = f"HTTP {resp.status_code}"
            if resp.status_code not in (429, 500, 502, 503, 504):
                log(f"  ! {label}: {detail}, not retrying")
                return None
            retry_after = resp.headers.get("Retry-After", "")
            if retry_after.isdigit():
                wait = int(retry_after)
                log(f"  ! {label}: {detail}, server asked to wait {wait}s")
                time.sleep(wait)
                continue
        wait = 5 * 2 ** attempt
        log(f"  ! {label}: {detail}, retry {attempt + 1}/{MAX_RETRIES} in {wait}s")
        time.sleep(wait)
    log(f"  ! {label}: giving up")
    return None


def fetch_fred(key: str, series_id: str, start: str) -> dict[str, float]:
    units = "pc1" if key in YOY_SERIES else "lin"
    params = {
        "series_id": series_id,
        "api_key": settings.fred_api_key,
        "file_type": "json",
        "sort_order": "asc",
        "observation_start": start,
        "units": units,
    }
    resp = get_with_retry(FRED_BASE, params, f"FRED {series_id}")
    if resp is None:
        return {}
    out = {}
    for o in resp.json().get("observations", []):
        try:
            v = float(o["value"])
        except (KeyError, TypeError, ValueError):
            continue  # "." = no value for that date
        # Same transforms as macro/fred.py, so history matches live rows.
        if key in BPS_SERIES:
            v = round(v * 100, 1)
        elif key in YOY_SERIES:
            v = round(v, 1)
        elif key in MILLIONS_TO_BILLIONS_SERIES:
            v = round(v / 1000, 3)
        out[o["date"]] = v
    return out


def fetch_treasury_tga(start: str) -> dict[str, float]:
    out = {}
    page = 1
    while True:
        params = {
            "filter": f"account_type:eq:{TGA_CLOSING},record_date:gte:{start}",
            "sort": "record_date",
            "fields": f"record_date,{VALUE_FIELD}",
            "page[size]": 1000,
            "page[number]": page,
        }
        resp = get_with_retry(TREASURY_API, params, f"Treasury TGA page {page}")
        if resp is None:
            return out
        body = resp.json()
        for row in body.get("data", []):
            raw = row.get(VALUE_FIELD)
            if raw in (None, "", "null"):
                continue
            out[row["record_date"]] = round(float(raw) / 1000, 3)
        if page >= body.get("meta", {}).get("total-pages", 1):
            return out
        page += 1
        time.sleep(1)


def fetch_yahoo(symbol: str, start: str) -> dict[str, float]:
    for attempt in range(MAX_RETRIES):
        try:
            hist = yf.Ticker(symbol).history(start=start, auto_adjust=False)
            return {
                idx.date().isoformat(): round(float(row["Close"]), 2)
                for idx, row in hist.iterrows()
            }
        except Exception as exc:
            wait = 10 * 2 ** attempt
            log(f"  ! Yahoo {symbol}: {exc}, retry {attempt + 1}/{MAX_RETRIES} in {wait}s")
            time.sleep(wait)
    log(f"  ! Yahoo {symbol}: giving up")
    return {}


def earliest_dates() -> dict[str, str]:
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT series_key, MIN(date) AS d FROM observations GROUP BY series_key"
        ).fetchall()
    return {r["series_key"]: r["d"] for r in rows}


def stored_series(key: str) -> dict[str, float]:
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT date, value FROM observations WHERE series_key = ?", (key,)
        ).fetchall()
    return {r["date"]: r["value"] for r in rows}


def derive(inputs: dict[str, dict[str, float]], fn) -> dict[str, float]:
    """Replay what the cron would have computed on each date.

    For every date on which any input printed, take each input's latest
    value on or before that date — the same "dated by the most recent input"
    rule checker.py applies to a single run.
    """
    sorted_dates = {k: sorted(s) for k, s in inputs.items()}
    all_dates = sorted(set().union(*sorted_dates.values()))
    out = {}
    for d in all_dates:
        vals = {}
        for k, dates in sorted_dates.items():
            i = bisect.bisect_right(dates, d)
            if i == 0:
                break
            vals[k] = inputs[k][dates[i - 1]]
        else:
            out[d] = fn(vals)
    return out


def backup_db() -> None:
    src_path = get_db_path()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst_path = src_path.with_name(f"{src_path.stem}.pre-backfill-{stamp}{src_path.suffix}")
    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(dst_path)
    with dst:
        src.backup(dst)  # consistent copy, WAL included
    src.close()
    dst.close()
    log(f"Backup written to {dst_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", default="2023-01-01", help="first date to backfill (YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true", help="fetch and report, write nothing")
    parser.add_argument("--only", help="comma-separated series keys to limit the run to")
    args = parser.parse_args()

    date.fromisoformat(args.start)  # validate
    only = set(args.only.split(",")) if args.only else None
    fetch_start = (date.fromisoformat(args.start) - timedelta(days=LOOKBACK_DAYS)).isoformat()
    today = datetime.now(timezone.utc).date().isoformat()

    if not get_db_path().exists():
        log(f"No database at {get_db_path()} — run main.py at least once first.")
        return 1
    if not settings.fred_api_key:
        log("FRED_API_KEY is not set in .env — aborting (that's most of the dataset).")
        return 1

    init_db()  # make sure series_metadata is current before inserting
    cutoffs = earliest_dates()

    def wanted(key: str) -> bool:
        return only is None or key in only

    # Derived series need their inputs even when only the derived key is asked for.
    needed = set(only or ())
    for dkey, (ins, _) in DERIVED.items():
        if wanted(dkey):
            needed.update(ins)

    def need(key: str) -> bool:
        return only is None or key in needed

    fetched: dict[str, dict[str, float]] = {}
    failed: list[str] = []

    fred_keys = [k for k in FRED_SERIES if need(k)]
    log(f"Fetching {len(fred_keys)} FRED series ({FRED_DELAY}s apart)...")
    for i, key in enumerate(fred_keys):
        if i:
            time.sleep(FRED_DELAY)
        fetched[key] = fetch_fred(key, FRED_SERIES[key], fetch_start)
        log(f"  {key:<18} {len(fetched[key]):>6} rows")
        if not fetched[key]:
            failed.append(key)

    if need("tga"):
        log("Fetching Treasury TGA...")
        fetched["tga"] = fetch_treasury_tga(fetch_start)
        log(f"  {'tga':<18} {len(fetched['tga']):>6} rows")
        if not fetched["tga"]:
            failed.append("tga")

    yahoo_keys = [k for k in LIVE_TICKERS if need(k)]
    if yahoo_keys:
        log(f"Fetching {len(yahoo_keys)} Yahoo tickers ({YAHOO_DELAY}s apart)...")
    for i, key in enumerate(yahoo_keys):
        if i:
            time.sleep(YAHOO_DELAY)
        fetched[key] = fetch_yahoo(LIVE_TICKERS[key], fetch_start)
        log(f"  {key:<18} {len(fetched[key]):>6} rows")
        if not fetched[key]:
            failed.append(key)

    for dkey, (ins, fn) in DERIVED.items():
        if not wanted(dkey):
            continue
        if any(not fetched.get(k) for k in ins):
            log(f"  {dkey:<18} skipped: missing input(s)")
            failed.append(dkey)
            continue
        # Stored input rows win over fetched ones: they're what the cron saw.
        inputs = {k: {**fetched[k], **stored_series(k)} for k in ins}
        fetched[dkey] = derive(inputs, fn)

    # Keep only [start, earliest stored date) per series.
    to_write: dict[str, list[tuple[str, float]]] = {}
    log("")
    log(f"{'series':<18} {'cutoff (excl.)':<15} {'rows':>6}  range")
    for key in sorted(fetched):
        if not wanted(key):
            continue
        cutoff = cutoffs.get(key, today)
        rows = sorted((d, v) for d, v in fetched[key].items() if args.start <= d < cutoff)
        to_write[key] = rows
        span = f"{rows[0][0]} .. {rows[-1][0]}" if rows else "-"
        note = "" if key in cutoffs else "  (no stored rows; filling to today)"
        log(f"{key:<18} {cutoff:<15} {len(rows):>6}  {span}{note}")

    total = sum(len(r) for r in to_write.values())
    log(f"\n{total} rows across {len(to_write)} series.")
    if failed:
        log(f"FAILED (nothing fetched): {', '.join(failed)} — re-run later with --only {','.join(failed)}")

    if args.dry_run:
        log("Dry run: nothing written.")
        return 1 if failed else 0

    backup_db()
    inserted = 0
    with get_db_connection() as conn:
        for key, rows in to_write.items():
            cur = conn.executemany(
                """
                INSERT INTO observations (series_key, date, value, recorded_at)
                VALUES (?, ?, ?, datetime(?))
                ON CONFLICT(series_key, date) DO NOTHING
                """,
                [(key, d, v, d) for d, v in rows],
            )
            inserted += cur.rowcount
    log(f"Inserted {inserted} rows.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
