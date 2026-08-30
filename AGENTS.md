# Macrobot

A stateless macro-data ingestion job. It runs once, fetches a fixed set of
macroeconomic/market indicators, writes any changes to a local SQLite
database, and exits. It makes no outbound calls to any AI/LLM API and sends
no notifications itself — see "Notifications" below.

Intended deployment: a scheduled job (cron/systemd timer) on a VPS, run
hourly. Between runs there is no running process and no in-memory state;
everything persists in `data/macrobot.db`.

## Entry point

`python main.py` — calls `init_db()` then `run_check()`. That's the whole
program; there is no server, no CLI args, no daemon mode.

## File map

- `main.py` — entry point, logging setup.
- `config.py` — `pydantic-settings` config, loaded from `.env`. Only reads
  `FRED_API_KEY`, `SQLITE_DB_PATH`, `TIMEZONE`, `LOG_LEVEL`. Unrecognized env
  vars are silently ignored (`extra="ignore"`), so stale keys in `.env` don't
  break anything but also don't do anything.
- `checker.py` — orchestration: fetch all sources, compute derived series,
  decide whether each value is a new dated observation or a same-day update.
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
- `observations` — one row per series per calendar/release date. A new date
  gets a new row (`insert_observation`); if the date hasn't changed since
  the last recorded row for that series, the value is updated in place
  (`update_observation`) instead of inserting a duplicate — this is what
  keeps a continuously-quoted series like VIX from writing a new row on
  every single hourly run.

There used to be an `updates` table acting as a pending-alert queue for an
external consumer (see git history / `DB_INTEGRATION.md`'s prior versions).
It was removed: nothing advanced its "last notified baseline," so once a
series drifted from its first-ever recorded value it stayed permanently
staged. A future consumer that wants alerting should compute "did this
change enough to matter" itself from `observations`, using
`series_metadata.threshold` as a guideline.

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
  (`* 100`). `tga`/`walcl` come back in millions and are converted to
  billions (`/ 1000`). `cpi`/`core_cpi` are fetched with `units=pc1` (FRED
  computes YoY % server-side) rather than the raw index level.
- `checker.py`: `fed_net_liquidity` and `sofr_effr_spread` are derived, not
  fetched — computed only if their inputs are present in the same run.

## Installation (VPS)

Target layout assumed by the systemd units below: repo checked out at
`/opt/macrobot`. Adjust paths if deploying elsewhere.

```bash
git clone <this-repo> /opt/macrobot
cd /opt/macrobot
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

cp .env.example .env
# edit .env and set FRED_API_KEY (get one at
# https://fred.stlouisfed.org/docs/api/api_key.html)

# sanity check: runs one ingestion pass, creates data/macrobot.db
.venv/bin/python main.py
```

Then install the hourly systemd timer:

```bash
sudo cp systemd/macrobot.service systemd/macrobot.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now macrobot.timer

# verify
systemctl list-timers macrobot.timer
journalctl -u macrobot.service -f
```

Notes for whoever/whatever is provisioning this:
- `data/` and its parent dirs are created automatically by `db.py` on first
  run — no manual `mkdir` needed.
- The `logs/` directory in this repo is a leftover from a previous version
  and is not written to by the current code. With the systemd unit above,
  logs go to the journal (`journalctl -u macrobot.service`), not to disk.
- `.env` is gitignored; `.env.example` documents every variable `config.py`
  actually reads. Anything else in `.env` (e.g. leftover keys from an old
  setup) is silently ignored, not an error.
- No Python version is pinned; 3.10+ required (`db.py` uses `dict[str, dict]`
  built-in generic syntax).

## Update workflow

When told the code has changed on GitHub:

```bash
cd /opt/macrobot
git pull
.venv/bin/pip install -r requirements.txt   # picks up any dependency changes; no-op otherwise
```

That's it — there's no daemon to restart; the systemd unit runs
`python main.py` fresh from disk on every hourly trigger, so the next run
just picks up the pulled code.

Exceptions: if the `systemd/*` unit files themselves changed, re-copy them
and `sudo systemctl daemon-reload`. To verify immediately instead of waiting
for the next hour, `sudo systemctl start macrobot.service` then
`journalctl -u macrobot.service -n 50`.

## Notifications

There are none inside this app. Macrobot only writes to `observations` in
SQLite. Whatever reads that data and turns it into an actual alert
(Discord, Telegram, X/Grok bot, etc.) is a separate process with its own
credentials, living outside this repo — see `DB_INTEGRATION.md` for example
queries.
