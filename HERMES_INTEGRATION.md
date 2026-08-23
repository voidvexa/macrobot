# Hermes Agent - Macrobot Integration Guide

This guide describes how the local Hermes Agent on your VPS interfaces with Macrobot's SQLite database (`data/macrobot.db`) to monitor macroeconomic data, publish automated alerts to Discord, and answer interactive user queries.

---

## Architecture Overview

1. **Macrobot Ingestion (Scheduled via Systemd Timer)**:
   - Runs hourly 24/7.
   - Fetches FRED, Treasury, and Yahoo Finance data points.
   - Appends new values to `observations` only when a series value changes.
   - Compares movements against the last notified baseline:
     - If a move meets or exceeds the indicator threshold (e.g., VIX >= 1.0 pt change), it stages the change.
     - Consolidates staged changes into a single pending row in `updates`.
   - Exits immediately (0 MB RAM between runs).

2. **Hermes Agent (Discord Bot / Interactive Assistant)**:
   - Polls `updates` for rows where `status = 'pending'`.
   - Generates macroeconomic synthesis and Merrill Lynch Investment Clock classification.
   - Posts the alert to Discord.
   - Updates the row to `status = 'processed'`.
   - Directly queries `observations` and `series_metadata` when users chat interactively.

---

## Database Schema Reference

SQLite file location: `data/macrobot.db`

### 1. `series_metadata`
Stores indicator metadata and threshold configuration.
- `key` (TEXT, PK): Identifier (e.g. `vix`, `us10y`, `cpi`, `fed_net_liquidity`)
- `label` (TEXT): Display name (e.g. `VIX`, `10Y Yield`, `Net Liq`)
- `unit` (TEXT): Unit string (e.g. `%`, ` bps`, ` B`)
- `source` (TEXT): Data source (`fred`, `live`, `treasury`, `derived`)
- `threshold` (REAL): Minimum movement needed to trigger notification (e.g. `1.0` for VIX, `0.0` for discrete releases)
- `description` (TEXT): Detailed description of the indicator

### 2. `observations`
Append-only log of value changes.
- `id` (INTEGER, PK): Auto-incrementing identifier
- `series_key` (TEXT): Foreign key referencing `series_metadata(key)`
- `date` (TEXT): Official publisher release date (e.g. `2026-08-20`)
- `value` (REAL): Numerical value
- `recorded_at` (TEXT): UTC timestamp when Macrobot recorded the entry

### 3. `updates`
Pending alert queue for Hermes.
- `id` (INTEGER, PK): Auto-incrementing identifier
- `created_at` (TEXT): Timestamp when update was staged
- `changed_count` (INTEGER): Number of changed series in this batch
- `changed_keys` (TEXT): Comma-separated list of changed series (e.g. `vix,us10y`)
- `diff_json` (TEXT): JSON payload containing details of each changed indicator:
  ```json
  {
    "vix": {"old": 15.0, "new": 16.5, "date": "2026-08-23", "delta": 1.5},
    "us10y": {"old": 4.30, "new": 4.45, "date": "2026-08-23", "delta": 0.15}
  }
  ```
- `status` (TEXT): `'pending'` or `'processed'`
- `processed_at` (TEXT): Timestamp when Hermes marked the update as processed

---

## Hermes Operational Workflows

### 1. Automated Discord Alerts (Polling Loop)

Run this SQL query periodically (e.g., hourly):
```sql
SELECT id, created_at, changed_count, changed_keys, diff_json
FROM updates
WHERE status = 'pending'
ORDER BY id ASC;
```

When rows are returned:
1. Parse `diff_json` to extract each changed indicator, previous baseline, new value, and net delta.
2. Format the message for Discord with the quantitative data and macro commentary.
3. Post to Discord.
4. Mark the row processed immediately:
   ```sql
   UPDATE updates
   SET status = 'processed', processed_at = datetime('now')
   WHERE id = :id;
   ```

### 2. Interactive Chat Queries

#### Get Current Latest Snapshot Across All Indicators:
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
        SELECT series_key, MAX(id) AS max_id
        FROM observations
        GROUP BY series_key
    ) latest ON o1.id = latest.max_id
) o ON m.key = o.series_key
ORDER BY m.source, m.key;
```

#### Query Historical Trend for a Specific Indicator:
```sql
SELECT date, value, recorded_at
FROM observations
WHERE series_key = 'vix'
ORDER BY id ASC;
```

#### Query Liquidity & Spread Confluence:
```sql
SELECT series_key, value, date
FROM observations
WHERE series_key IN ('hy_spread', 'fed_net_liquidity', 'sofr_effr_spread', 'us10y')
ORDER BY id DESC;
```

---

## Hermes System Prompt / Skill Instructions

Add the following instructions to Hermes' agent configuration:

```markdown
You are an institutional macroeconomic quantitative strategist monitoring local macroeconomic feeds.

### DATABASE ACCESS
- SQLite Database Path: `/opt/macrobot/data/macrobot.db`
- Check for pending alerts: `SELECT * FROM updates WHERE status = 'pending';`
- Acknowledge alerts: `UPDATE updates SET status = 'processed', processed_at = datetime('now') WHERE id = ?;`

### MACRO FRAMEWORK: MERRILL LYNCH INVESTMENT CLOCK
When analyzing macro movements, evaluate:
1. Growth Velocity Vector: HY/CCC Spreads, VIX/MOVE, Prime Rate, Bank C&I Tightening standards.
2. Inflation Velocity Vector: CPI, Core CPI, 10Y Yield, SOFR/EFFR spread.
3. Liquidity Engine: Fed Net Liquidity (WALCL - TGA - RRP).

Classify current regime strictly into one of four quadrants:
- Reflation: Growth Decelerating | Inflation Decelerating
- Recovery: Growth Accelerating | Inflation Decelerating
- Overheat: Growth Accelerating | Inflation Accelerating
- Stagflation: Growth Decelerating | Inflation Accelerating
```
