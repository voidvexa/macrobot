# Macrobot

Macrobot fetches a fixed set of U.S. macro and market indicators, writes them to a local SQLite file, and exits. Run it on a schedule — every two hours is the intended cadence. Between runs nothing stays up. The database is the whole state.

Alerts live outside this repo. A reader opens `data/macrobot.db` and decides what is worth flagging. The schema and example queries are in [DB_INTEGRATION.md](DB_INTEGRATION.md).

## What it tracks

Forty-three series, from three places: FRED, the Treasury Fiscal Data API, and Yahoo Finance.

| Area | Examples |
| --- | --- |
| Markets | VIX, MOVE, SKEW |
| Rates and credit | 10Y yield, 10Y–2Y, 10Y–3M, HY / IG / CCC spreads, SOFR, EFFR, prime rate |
| Liquidity | Fed assets, RRP, TGA, reserve balances, M2, bank credit, net liquidity |
| Prices | CPI, core CPI, PCE, core PCE, PPI, wage growth, 5Y breakeven, 5Y5Y forward |
| Activity | Payrolls, claims, unemployment, industrial production, retail sales, real PCE, real GDP, permits, CFNAI |
| Stress | NFCI, St. Louis financial stress, C&I loan tightening, broad dollar |

Two series are computed here: net liquidity (Fed assets minus RRP minus TGA) and the SOFR–EFFR spread.

## Setup

Python 3.12 or newer.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Add a [FRED API key](https://fred.stlouisfed.org/docs/api/api_key.html) to `.env`. Without one, FRED series are skipped and only VIX, MOVE, SKEW, and TGA are stored.

```bash
.venv/bin/python main.py
```

That creates `data/macrobot.db` and a rotating log at `logs/macrobot.log`. A healthy first run fills all 43 series and records `last_run_status` as `ok`.

Every two hours, with cron output discarded (the app already rotates its own log):

```
0 */2 * * * cd /path/to/macrobot && .venv/bin/python main.py >/dev/null 2>&1
```

## The database

`data/macrobot.db` has three tables:

- **observations** — one row per series per date. A new date inserts a row. A same-day change updates that row.
- **series_metadata** — label, unit, source, and a suggested threshold for “is this move notable?”
- **meta** — `last_run_at` and `last_run_status` (`ok`, `partial`, or `failed`). That is how you tell a quiet market from a job that never ran.

The latest value for a series is the row with the greatest `date`. Overlapping runs are safe: each write is an upsert on `(series_key, date)`.
