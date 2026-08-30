# Macrobot Database Integration Guide

Macrobot is a stateless data-ingestion job: it fetches macroeconomic data points, writes them to a local SQLite database, and exits. It makes no outbound calls to any AI/agent API and sends no notifications itself.

Any downstream agent (e.g. a bot running on the same VPS, such as an x.ai/Grok-based bot) is expected to read `data/macrobot.db` directly, on demand, to answer questions about the data or notice trends — Macrobot has no knowledge of, and no dependency on, whatever reads the database. There is no built-in alert/notification queue; Macrobot only ever writes `observations`.

---

## Architecture Overview

1. **Macrobot Ingestion (run as a scheduled job — e.g. cron/systemd timer — hourly)**:
   - Fetches FRED, Treasury, and Yahoo Finance data points.
   - Writes to `observations` one row per series per calendar/release date: a new date gets a new row; if the date hasn't changed since the last recorded row (e.g. an intraday VIX quote shifting within the same trading day), that row's value is updated in place instead of inserting a duplicate.
   - Exits immediately after each run (no persistent process).

2. **Downstream Consumer (any agent with filesystem access to the VPS)**:
   - Queries `observations` and `series_metadata` directly — for a current snapshot, a historical trend, or to notice that a series moved meaningfully (there's nothing pre-computed to poll; the consumer decides what's "notable" itself, e.g. using `series_metadata.threshold` as a guideline).
   - Should check `meta` first when freshness matters — a quiet market and a dead ingestion job look identical in `observations` alone.
   - Sends whatever it wants via whatever channel it owns (Discord, Telegram, X/Grok, etc.) — entirely outside Macrobot's scope.

The database is opened in WAL mode, so reading it concurrently with Macrobot's hourly write is safe — no need to schedule around the job.

---

## Database Schema Reference

SQLite file location: `data/macrobot.db`

### 1. `series_metadata`
Stores indicator metadata and threshold configuration.
- `key` (TEXT, PK): Identifier (e.g. `vix`, `us10y`, `cpi`, `fed_net_liquidity`)
- `label` (TEXT): Display name (e.g. `VIX`, `10Y Yield`, `Net Liq`)
- `unit` (TEXT): Unit string (e.g. `%`, ` bps`, ` B`)
- `source` (TEXT): Data source (`fred`, `live`, `treasury`, `derived`)
- `threshold` (REAL): Not enforced by Macrobot — a guideline for a consumer deciding what counts as a notable move for this indicator (e.g. `1.0` for VIX, `0.0` meaning "any change is notable," typical for discrete monthly releases)
- `description` (TEXT): Detailed description of the indicator

### 2. `observations`
One row per series per calendar/release date, enforced by a UNIQUE index on `(series_key, date)`. Not append-only in the strict sense: a same-day value change updates the existing row rather than inserting a duplicate (see Architecture Overview above).
- `id` (INTEGER, PK): Auto-incrementing identifier
- `series_key` (TEXT): Foreign key referencing `series_metadata(key)`
- `date` (TEXT): Official publisher release date, or trading date for live tickers (e.g. `2026-08-20`)
- `value` (REAL): Numerical value — the latest known value for that date
- `recorded_at` (TEXT): UTC timestamp of the most recent write to this row (insert or update)

**Order by `date`, not by `id`.** Rows are not guaranteed to be inserted in date order, so `MAX(id)` is not reliably the newest reading — use `MAX(date)`.

**Derived series** (`fed_net_liquidity`, `sofr_effr_spread`) are dated with the most recent of their input dates, so a derived row can combine inputs of slightly different vintages — e.g. a net-liquidity row may pair a same-day RRP with a WALCL up to six days older, since WALCL is only published weekly.

### 3. `meta`
Run markers, so a consumer can tell a quiet market from a dead job.
- `key` (TEXT, PK): `last_run_at` or `last_run_status`
- `value` (TEXT): For `last_run_at`, a UTC timestamp. For `last_run_status`, one of `ok` (all sources returned data), `partial` (some source returned nothing), `failed` (all sources failed, or the run raised).
- `updated_at` (TEXT): UTC timestamp of the last write to this key

---

## Example Consumer Queries

### Check data freshness first:
```sql
SELECT key, value FROM meta;
-- last_run_at    -> UTC timestamp of the last run
-- last_run_status -> ok | partial | failed
```

### Get current latest snapshot across all indicators:
```sql
SELECT
    m.key,
    m.label,
    o.value,
    m.unit,
    o.date,
    o.recorded_at
FROM series_metadata m
LEFT JOIN (
    SELECT o1.series_key, o1.value, o1.date, o1.recorded_at
    FROM observations o1
    INNER JOIN (
        SELECT series_key, MAX(date) AS max_date
        FROM observations
        GROUP BY series_key
    ) latest
      ON o1.series_key = latest.series_key AND o1.date = latest.max_date
) o ON m.key = o.series_key
ORDER BY m.source, m.key;
```

### Query historical trend for a specific indicator:
```sql
SELECT date, value, recorded_at
FROM observations
WHERE series_key = 'vix'
ORDER BY date ASC;
```

### Query liquidity & spread confluence:
```sql
SELECT series_key, value, date
FROM observations
WHERE series_key IN ('hy_spread', 'fed_net_liquidity', 'sofr_effr_spread', 'us10y')
ORDER BY date DESC;
```

---

## Suggested Macro Framework (optional, for whatever agent does the synthesis)

When analyzing macro movements, one useful lens is the Merrill Lynch Investment Clock:

1. Growth Velocity Vector: HY/CCC Spreads, VIX/MOVE, Prime Rate, Bank C&I Tightening standards.
2. Inflation Velocity Vector: CPI, Core CPI, 10Y Yield, SOFR/EFFR spread.
3. Liquidity Engine: Fed Net Liquidity (WALCL - TGA - RRP).

Classify the current regime into one of four quadrants:
- Reflation: Growth Decelerating | Inflation Decelerating
- Recovery: Growth Accelerating | Inflation Decelerating
- Overheat: Growth Accelerating | Inflation Accelerating
- Stagflation: Growth Decelerating | Inflation Accelerating
