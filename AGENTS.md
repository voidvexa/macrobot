# Macrobot

A stateless macro-data ingestion job. It runs once, fetches a fixed set of
macroeconomic/market indicators, writes any changes to a local SQLite
database, and exits. It makes no outbound calls to any AI/LLM API and sends
no notifications itself — see "Notifications" below.

Intended deployment: a scheduled job (systemd timer) on a VPS, run hourly.
Between runs there is no running process and no in-memory state; everything
persists in `data/macrobot.db`.

## Entry point

`python main.py` — calls `init_db()` then `run_check()`. That's the whole
program; there is no server, no CLI args, no daemon mode. It exits non-zero
if the run fails, so systemd marks the unit failed.

## File map

- `main.py` — entry point, logging setup, top-level error handling.
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
  like VIX from writing a new row on every hourly run, and what makes two
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

## Installation (VPS)

Assumes the repo at `/opt/macrobot`, running as a dedicated `macrobot`
service account. Adjust paths if deploying elsewhere.

Python 3.12+ is required (pinned `numpy` needs 3.12+, pinned `pandas` 3.11+).
Check `python3 --version` first; if it's older, install a newer Python (e.g.
the `deadsnakes` PPA on Ubuntu) and use that to create the venv.

```bash
sudo git clone <this-repo> /opt/macrobot
cd /opt/macrobot
sudo python3 -m venv .venv
sudo .venv/bin/pip install -r requirements.txt

sudo cp .env.example .env
# edit .env and set FRED_API_KEY (get one at
# https://fred.stlouisfed.org/docs/api/api_key.html)

# dedicated service account; home is set to the repo so yfinance's cache
# has somewhere writable to live
sudo useradd --system --home-dir /opt/macrobot --shell /usr/sbin/nologin macrobot
sudo chown -R macrobot:macrobot /opt/macrobot
sudo chmod 600 /opt/macrobot/.env

# sanity check: one ingestion pass, creates data/macrobot.db
sudo -u macrobot .venv/bin/python main.py
```

Then install the hourly timer:

```bash
sudo cp systemd/macrobot.service systemd/macrobot.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now macrobot.timer

# verify
systemctl list-timers macrobot.timer
journalctl -u macrobot.service -f
```

Notes:
- `data/` is created automatically by `db.py` on first run — no manual
  `mkdir` needed. It must stay writable by `macrobot`.
- Logs go to the journal (`journalctl -u macrobot.service`), not to disk.
  The `logs/` directory in this repo is a leftover from an older version and
  is not written to.
- `.env` is gitignored; `.env.example` documents every variable `config.py`
  reads. Anything else in `.env` is ignored, not an error.
- The service unit is deliberately only lightly hardened (`NoNewPrivileges`,
  `PrivateTmp`). Stronger sandboxing (`ProtectSystem=strict`, `ProtectHome`)
  blocks yfinance's cache writes and fails in ways that are awkward to debug
  remotely.

## Update workflow

When told the code has changed on GitHub:

```bash
cd /opt/macrobot
sudo -u macrobot git pull
sudo -u macrobot .venv/bin/pip install -r requirements.txt   # no-op if deps unchanged
```

Run these as `macrobot` (not root) so file ownership stays consistent.

That's it — there's no daemon to restart; the unit runs `python main.py`
fresh from disk on every hourly trigger, so the next run picks up the pulled
code.

Exceptions: if the `systemd/*` unit files themselves changed, re-copy them
and `sudo systemctl daemon-reload`. To verify immediately instead of waiting
for the next hour, `sudo systemctl start macrobot.service` then
`journalctl -u macrobot.service -n 50`.

## Health check

```sql
SELECT key, value FROM meta;   -- last_run_at (UTC), last_run_status
```

`last_run_status` is `partial` when some sources returned nothing and
`failed` when all did (or the run raised). Individual fetch failures are
logged as warnings in the journal.

## Notifications

There are none inside this app. Macrobot only writes to SQLite. Whatever
reads that data and turns it into an actual alert (Discord, Telegram, X/Grok
bot, etc.) is a separate process with its own credentials, living outside
this repo — see `DB_INTEGRATION.md` for example queries.
