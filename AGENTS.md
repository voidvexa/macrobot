# Macrobot

A stateless macro-data ingestion job. It runs once, fetches a fixed set of
macroeconomic/market indicators, writes any changes to a local SQLite
database, and exits. It makes no outbound calls to any AI/LLM API and sends
no notifications itself — see "Notifications" below.

Intended deployment: a cron job every two hours on a VM. Between runs there
is no running process and no in-memory state; everything persists in
`data/macrobot.db`.

## Entry points

Two programs share `data/macrobot.db`. They do not import each other.

`python -m updater` is the cron job. It calls `init_db()` then `run_check()`
and exits. It exits non-zero if the run fails. There is no server and no
daemon mode.

`python -m dashboard` is the read-only API. See "Dashboard" below.

## File map

- `updater/__main__.py` is the cron entry. It sets up logging on stderr and in
  rotating `logs/macrobot.log`, handles a failed run, and creates `logs/` if
  missing.
- `updater/config.py` loads `.env` with pydantic-settings. It reads
  `FRED_API_KEY`, `SQLITE_DB_PATH`, and `LOG_LEVEL`. Unrecognized env vars are
  ignored (`extra="ignore"`), so a stale key in `.env` does nothing.
- `updater/check.py` fetches every source, computes derived series, decides
  whether each value is a new dated observation or a same-day update, and
  records run health.
- `updater/store.py` holds the SQLite schema, the seed list
  `DEFAULT_SERIES_METADATA`, and the writes. `init_db()` upserts
  `series_metadata` on every run. Edit that list to add, rename, or
  rethreshold an indicator.
- `updater/sources/fred.py` fetches the FRED series (10Y, 10Y-2Y, 10Y-3M,
  credit spreads, SOFR/EFFR, WALCL, RRP, reserve balances, weekly TGA, M2,
  bank credit, broad USD, CPI/Core CPI/headline PCE/Core PCE/final-demand
  PPI/average hourly earnings/INDPRO YoY, 5Y breakeven, 5Y5Y forward
  inflation, payrolls, initial and continued claims, unemployment, retail
  sales, real PCE, real GDP, building permits, CFNAI, NFCI, St. Louis
  financial stress, C&I tightening, prime rate). It returns nothing when
  `FRED_API_KEY` is unset.
- `updater/sources/live.py` fetches VIX, MOVE, and SKEW from Yahoo Finance.
- `updater/sources/treasury.py` fetches the TGA closing balance from the U.S.
  Treasury Fiscal Data API.
- `dashboard/` is the read-only localhost JSON API over the same SQLite file.
  `dashboard/web` is the React page. It does not import `updater`. See
  "Dashboard" below.
- `DB_INTEGRATION.md` is the schema contract and the example queries for any
  other reader of `data/macrobot.db`.

## Data model, briefly

- `series_metadata` — one row per tracked indicator (key, label, unit,
  source, threshold, description). Seeded from `updater.store.DEFAULT_SERIES_METADATA`.
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

- `updater/sources/treasury.py`: the Fiscal Data API path is
  `/services/api/fiscal_service/v1/...` — the older `/services/api/v1/...`
  path 404s. The endpoint returns four rows per date (opening balance,
  deposits, withdrawals, closing balance); must filter
  `account_type:eq:Treasury General Account (TGA) Closing Balance` or the
  wrong figure gets picked up. `close_today_bal` is always the string
  `"null"` in this dataset — the actual closing-balance figure is in
  `open_today_bal`. That figure is millions of dollars and is stored in
  billions (`/ 1000`), the same unit as `walcl` and `rrp`.
- `updater/sources/fred.py`: credit spread series (`hy_spread`, `ig_spread`,
  `ccc_spread`) come back from FRED in percent and are converted to bps
  (`* 100`). `walcl`, `tga_weekly`, `rsafs`, and `wresbal` come back in
  millions and are converted to billions (`/ 1000`). `cpi`/`core_cpi`/
  `core_pce`/`pce`/`ppi`/`ahe`/`indpro` are fetched with `units=pc1` (FRED
  computes YoY % server-side) rather than the raw index or dollar level.
  `payems` stays in thousands of persons, `permit` stays in thousands of
  units, and `icsa` and `ccsa` are raw counts. `real_pce` (PCEC96) and
  `real_gdp` (GDPC1) are already billions of chained dollars (current BEA
  reference year). The `tga` series (and therefore `fed_net_liquidity`)
  comes from `updater/sources/treasury.py`, the authoritative daily source;
  `tga_weekly` (FRED `WDTGAL`, Wednesday level) is stored separately and
  not used in any derived calculation.
- `updater/sources/fred.py`: never log a `requests` exception verbatim — its message
  embeds the request URL, which carries `api_key` as a query parameter.
- `updater/check.py`: `fed_net_liquidity` and `sofr_effr_spread` are derived, not
  fetched — computed only if their inputs are present in the same run. Each
  is dated with the **most recent** of its input dates. Dating them by a
  specific input would pin them to that input's cadence — WALCL is weekly,
  so using its date would collapse a week of daily RRP/TGA movement into one
  row. The tradeoff is that a derived row can mix vintages (a fresh RRP with
  a WALCL up to six days older), which is inherent to the calculation.
- `updater/check.py`: a feed that briefly reports an *older* date than what's
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
.venv/bin/python -m updater
```

Then schedule it every two hours with cron (`crontab -e`), using absolute
paths. Redirect stdout/stderr to `/dev/null` so cron does not mail the
output and does not grow a second unbounded file — the app already writes
a rotating log to `logs/macrobot.log`:

```
0 */2 * * * cd <app-dir> && .venv/bin/python -m updater >/dev/null 2>&1
```

### Verify the install

A missing `.env` still exits 0, so check the result rather than trusting
the exit code:

```bash
.venv/bin/python - <<'EOF'
import sqlite3
c = sqlite3.connect("data/macrobot.db")
print("series populated:", c.execute(
    "SELECT COUNT(DISTINCT series_key) FROM observations").fetchone()[0], "of 43")
print("run status      :", dict(c.execute("SELECT key, value FROM meta")))
EOF
```

Expect **43 of 43** and `last_run_status: ok`.

- Only 4 of 43 (VIX, SKEW, MOVE, TGA) means `FRED_API_KEY` is missing — the
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
- `.env` is gitignored; `.env.example` documents every variable `updater/config.py`
  reads. Anything else in `.env` is ignored, not an error.
- Overlapping runs are safe — writes are atomic upserts keyed on
  `(series_key, date)` — so a slow run being caught by the next cron
  won't duplicate or corrupt anything.

## Update workflow

```bash
git pull
.venv/bin/pip install -r requirements.txt   # no-op if deps unchanged
```

That's it — nothing to restart. Cron runs `python -m updater` fresh from
disk each time, so the next run picks up the pulled code. To verify
immediately instead of waiting, run `.venv/bin/python -m updater` by hand.

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

## Dashboard

Two processes on the same machine as the cron job. Neither replaces cron, and
neither writes `macrobot.db`. Ingestion stays `python -m updater`.

The API is the Python reader. It opens `data/macrobot.db` (or `SQLITE_DB_PATH`
from the environment / `.env`, the same default as `updater/config.py`) with `mode=ro`
and `PRAGMA query_only`. It imports nothing from `updater`, and it
does not load the ingestion stack (`dashboard/requirements.txt` lists no
packages; the standard library is enough). SQLite stays in that process. The
React app only calls the API.

Each feature is its own route, its own service function, and its own SQL
statement:

- `GET /api/job` — last run time, `last_run_status`, stale when that time is
  older than two hours, and whether `python -m updater` is running (idle between
  cron runs). One query of the `meta` table. The process check is not a second
  SQL statement.
- `GET /api/stats` — indicator count, how many of those have an observation,
  observation count, database file size, and newest observation date. One SQL
  statement. File size is a filesystem stat beside that query.
- `GET /api/snapshot` — latest row per series by `MAX(date)`: key, label,
  value, unit, date. One SQL statement (the consumer query in
  `DB_INTEGRATION.md`).

From the repo root, in two terminals:

```bash
python -m dashboard
```

```bash
npm --prefix dashboard/web install
npm --prefix dashboard/web run dev
```

The API binds `127.0.0.1:8765`. The React app binds `127.0.0.1:5173` and
proxies `/api` to that port. If you change the API port, set `DASHBOARD_PORT`
(or pass `--port`) before starting both. There is no auth, so leave both on
localhost. `--db` overrides the file for a one-off.

The React page is titled ALMA (a lightweight macroeconomic analyst). It calls
all three routes when it opens. There is no timer. The snapshot stays above
the status block. The page is a light monospace readout: plain labels,
fixed-width figures, simple borders. No charts and no AI summary.

Checks, with a temporary database and no network:

```bash
python -m unittest dashboard.test_dashboard
.venv/bin/python -m unittest updater.test_check
```

## Notifications

There are none inside this app. Macrobot only writes to SQLite. Whatever
reads that data and turns it into an actual alert (Discord, Telegram, X/Grok
bot, etc.) is a separate process with its own credentials, living outside
this repo — see `DB_INTEGRATION.md` for example queries.
