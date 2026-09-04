# Macrobot

A stateless macro-data ingestion job. It runs once, fetches a fixed set of
macroeconomic/market indicators, writes any changes to a local SQLite
database, and exits. It makes no outbound calls to any AI/LLM API and sends
no notifications itself — see "Notifications" below.

Intended deployment: a cron job every two hours on a VM. Between runs there
is no running process and no in-memory state; everything persists in
`data/macrobot.db`.

## Entry point

`python main.py` — calls `init_db()` then `run_check()`. That's the whole
program; there is no server, no CLI args, no daemon mode. It exits non-zero
if the run fails.

## File map

- `main.py` — entry point, logging setup (stderr + rotating `logs/macrobot.log`),
  top-level error handling. Creates `logs/` if missing.
- `config.py` — `pydantic-settings` config, loaded from `.env`. Only reads
  `FRED_API_KEY`, `SQLITE_DB_PATH`, `LOG_LEVEL`. Unrecognized env vars are
  silently ignored (`extra="ignore"`), so stale keys in `.env` don't break
  anything but also don't do anything.
- `checker.py` — orchestration: fetch all sources, compute derived series,
  decide whether each value is a new dated observation or a same-day update,
  record run health.
- `db.py` — SQLite schema, seed data (`DEFAULT_SERIES_METADATA`, the
  authoritative list of tracked indicators/thresholds/units), and all
  queries. `init_db()` upserts `series_metadata` on every run, so editing
  `DEFAULT_SERIES_METADATA` is the way to add/rename/rethreshold an
  indicator.
- `macro/fred.py` — FRED API (10Y, credit spreads, SOFR/EFFR, WALCL, RRP,
  CPI/Core CPI YoY, C&I tightening, prime rate). No-ops if `FRED_API_KEY` is
  unset.
- `macro/live.py` — Yahoo Finance via `yfinance` (VIX, MOVE, SKEW).
- `macro/treasury.py` — U.S. Treasury Fiscal Data API (TGA closing balance).
- `DB_INTEGRATION.md` — the schema contract and example queries for whatever
  external agent/bot reads `data/macrobot.db`. Read that, not this, if you're
  building the consumer side.

## Data model, briefly

- `series_metadata` — one row per tracked indicator (key, label, unit,
  source, threshold, description). Seeded from `db.DEFAULT_SERIES_METADATA`.
  `threshold` isn't enforced anywhere in this app — it's descriptive
  metadata for a downstream consumer deciding what counts as a notable move.
- `observations` — one row per series per date, enforced by a UNIQUE index
  on `(series_key, date)`. A new date inserts; a same-day value change
  updates that row in place (`upsert_observation`, a single atomic
  `ON CONFLICT` statement). This is what keeps a continuously-quoted series
  like VIX from writing a new row on every run, and what makes two
  overlapping runs safe.
- `meta` — key/value run markers: `last_run_at` (UTC) and `last_run_status`
  (`ok` | `partial` | `failed`). Lets a consumer tell "the market is quiet"
  apart from "the job is dead".

"Latest" is always decided by `MAX(date)`, never by insertion order — see
the stale-reading gotcha below.

There used to be an `updates` table acting as a pending-alert queue for an
external consumer (see git history). It was removed: nothing advanced its
"last notified baseline," so once a series drifted from its first-ever
recorded value it stayed permanently staged. A future consumer that wants
alerting should compute "did this change enough to matter" itself from
`observations`, using `series_metadata.threshold` as a guideline.

## Non-obvious gotchas (from source comments — keep these in sync if you touch the fetchers)

- `macro/treasury.py`: the Fiscal Data API path is
  `/services/api/fiscal_service/v1/...` — the older `/services/api/v1/...`
  path 404s. The endpoint returns four rows per date (opening balance,
  deposits, withdrawals, closing balance); must filter
  `account_type:eq:Treasury General Account (TGA) Closing Balance` or the
  wrong figure gets picked up. `close_today_bal` is always the string
  `"null"` in this dataset — the actual closing-balance figure is in
  `open_today_bal`.
- `macro/fred.py`: credit spread series (`hy_spread`, `ig_spread`,
  `ccc_spread`) come back from FRED in percent and are converted to bps
  (`* 100`). `walcl` comes back in millions and is converted to billions
  (`/ 1000`). `cpi`/`core_cpi` are fetched with `units=pc1` (FRED computes
  YoY % server-side) rather than the raw index level. TGA is deliberately
  *not* fetched from FRED — `macro/treasury.py` is the authoritative source.
- `macro/fred.py`: never log a `requests` exception verbatim — its message
  embeds the request URL, which carries `api_key` as a query parameter.
- `checker.py`: `fed_net_liquidity` and `sofr_effr_spread` are derived, not
  fetched — computed only if their inputs are present in the same run. Each
  is dated with the **most recent** of its input dates. Dating them by a
  specific input would pin them to that input's cadence — WALCL is weekly,
  so using its date would collapse a week of daily RRP/TGA movement into one
  row. The tradeoff is that a derived row can mix vintages (a fresh RRP with
  a WALCL up to six days older), which is inherent to the calculation.
- `checker.py`: a feed that briefly reports an *older* date than what's
  already stored is ignored and logged as stale, rather than written. Storing
  it would otherwise make an outdated reading look like the newest value.

## Installation

Python 3.12+ is required (pinned `numpy` needs 3.12+, pinned `pandas` 3.11+).
Check `python3 --version` first; if it's older, install a newer Python and
use that to create the venv.

```bash
git clone <this-repo> macrobot
cd macrobot
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

cp .env.example .env
chmod 600 .env
# edit .env and set FRED_API_KEY (get one at
# https://fred.stlouisfed.org/docs/api/api_key.html)

# sanity check: one ingestion pass, creates data/macrobot.db and logs/
.venv/bin/python main.py
```

Then schedule it every two hours with cron (`crontab -e`), using absolute
paths. Redirect stdout/stderr to `/dev/null` so cron does not mail the
output and does not grow a second unbounded file — the app already writes
a rotating log to `logs/macrobot.log`:

```
0 */2 * * * cd <app-dir> && .venv/bin/python main.py >/dev/null 2>&1
```

### Verify the install

A missing `.env` still exits 0, so check the result rather than trusting
the exit code:

```bash
.venv/bin/python - <<'EOF'
import sqlite3
c = sqlite3.connect("data/macrobot.db")
print("series populated:", c.execute(
    "SELECT COUNT(DISTINCT series_key) FROM observations").fetchone()[0], "of 18")
print("run status      :", dict(c.execute("SELECT key, value FROM meta")))
EOF
```

Expect **18 of 18** and `last_run_status: ok`.

- Only 4 of 18 (VIX, SKEW, MOVE, TGA) means `FRED_API_KEY` is missing — the
  whole FRED half of the dataset is absent.
- After the cron is scheduled, re-check a couple of hours later that
  `last_run_at` has advanced. If it hasn't, the cron line isn't firing.

Notes:
- `data/` and `logs/` are created automatically on first run; both are
  gitignored, so a fresh clone has neither.
- Do **not** append cron output onto `logs/macrobot.log` (`>> logs/macrobot.log`).
  That bypasses rotation and will grow without bound. The app owns that file:
  daily rotate at midnight, gzip, keep 7 days. Happy-path is one INFO line
  per run; per-observation detail is `LOG_LEVEL=DEBUG`. Warnings and errors
  still show at the default INFO threshold.
- The `/dev/null` redirect matters: without it, cron would try to mail
  stderr (the same one-line summary) on every run.
- `.env` is gitignored; `.env.example` documents every variable `config.py`
  reads. Anything else in `.env` is ignored, not an error.
- Overlapping runs are safe — writes are atomic upserts keyed on
  `(series_key, date)` — so a slow run being caught by the next cron
  won't duplicate or corrupt anything.

## Update workflow

```bash
git pull
.venv/bin/pip install -r requirements.txt   # no-op if deps unchanged
```

That's it — nothing to restart. Cron runs `main.py` fresh from disk each
time, so the next run picks up the pulled code. To verify immediately
instead of waiting, run `.venv/bin/python main.py` by hand.

## Health check

```sql
SELECT key, value FROM meta;   -- last_run_at (UTC), last_run_status
```

`last_run_at` is how you tell "the market is quiet" from "the box was down
and cron never fired" — if it's well past the two-hour cadence, the job
isn't running.
`last_run_status` is `partial` when some sources returned nothing and
`failed` when all did (or the run raised). Individual fetch failures are
logged as warnings in `logs/macrobot.log` (rotated daily, gzipped, 7-day
retention).

## Notifications

There are none inside this app. Macrobot only writes to SQLite. Whatever
reads that data and turns it into an actual alert (Discord, Telegram, X/Grok
bot, etc.) is a separate process with its own credentials, living outside
this repo — see `DB_INTEGRATION.md` for example queries.
