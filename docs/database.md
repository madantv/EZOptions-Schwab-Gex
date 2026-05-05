# Database reference

All features add tables to the existing `options_data.db` (SQLite). Schemas are migrated idempotently in `init_db()` via `CREATE TABLE IF NOT EXISTS` + ALTER fallbacks.

## Table summary

| Table | Added by | Purpose |
|---|---|---|
| `interval_data` | original | Minute-level per-strike Greek snapshots |
| `interval_session_data` | original | Minute-level expected-move band |
| `centroid_data` | original | Call/put volume centroid |
| `alerts` | [Tier 1 #1](alerts.md) | Alert definitions + crossing state |
| `alert_events` | [Tier 1 #1](alerts.md) | Alert fire history |
| `positions` | [Tier 1 #4](positions.md) | Manual option positions |
| `user_settings` | [Tier 2 #6](settings-profiles.md) | Multi-profile UI settings |
| `watchlist` | [Tier 3 #10](watchlist.md) | Tickers tracked in the sidebar |
| `session_reports` | [Tier 3 #11](session-reports.md) | Daily session summaries |

## Retention

- `interval_data`, `interval_session_data`, `centroid_data` are pruned to **the last 2 session dates** by `clear_old_data()` (pre-existing). Runs on every write to keep DB size bounded.
- All other tables (alerts, positions, settings, watchlist, session_reports) are kept indefinitely.

## Schemas

### `alerts`
```
id              INTEGER PRIMARY KEY AUTOINCREMENT
ticker          TEXT NOT NULL
alert_type      TEXT NOT NULL              -- price_cross | gex_flip | dex_threshold | em_breach | wall_shift
params_json     TEXT NOT NULL              -- type-specific parameters
status          TEXT NOT NULL DEFAULT 'active'   -- active | triggered | disabled
repeat_mode     TEXT NOT NULL DEFAULT 'one_shot'  -- one_shot | rearm | always
rearm_pct       REAL                       -- for rearm mode
last_value      REAL                       -- crossing-detection state
last_triggered_at INTEGER
webhook_url     TEXT
label           TEXT
created_at      INTEGER NOT NULL

INDEX idx_alerts_active (ticker, status)
```

### `alert_events`
```
id            INTEGER PRIMARY KEY AUTOINCREMENT
alert_id      INTEGER NOT NULL
fired_at      INTEGER NOT NULL
snapshot_json TEXT

INDEX idx_alert_events_alert (alert_id, fired_at)
```

### `positions`
```
id           INTEGER PRIMARY KEY AUTOINCREMENT
ticker       TEXT NOT NULL
side         TEXT NOT NULL              -- CALL | PUT
qty          INTEGER NOT NULL           -- positive = long, negative = short
strike       REAL NOT NULL
expiry       TEXT NOT NULL              -- YYYY-MM-DD
entry_price  REAL NOT NULL
label        TEXT
status       TEXT NOT NULL DEFAULT 'open'  -- open | closed
opened_at    INTEGER NOT NULL
closed_at    INTEGER

INDEX idx_positions_active (ticker, status)
```

### `user_settings`
```
profile_name TEXT PRIMARY KEY            -- 'default' is the back-compat slot
payload_json TEXT NOT NULL
updated_at   INTEGER NOT NULL
```

### `watchlist`
```
id          INTEGER PRIMARY KEY AUTOINCREMENT
ticker      TEXT NOT NULL UNIQUE
label       TEXT
position    INTEGER NOT NULL DEFAULT 0  -- manual sort order
created_at  INTEGER NOT NULL
```

### `session_reports`
```
id              INTEGER PRIMARY KEY AUTOINCREMENT
date            TEXT NOT NULL
ticker          TEXT NOT NULL
peak_gex_strike REAL
peak_gex_value  REAL
em_accuracy_pct REAL
centroid_drift  REAL
summary_json    TEXT NOT NULL              -- full computed report
created_at      INTEGER NOT NULL
UNIQUE(date, ticker)

INDEX idx_session_reports_date (date)
```

## Migrating an existing DB

`init_db()` runs at module load and is idempotent. Existing databases are auto-upgraded with the new tables. No manual migration needed.
