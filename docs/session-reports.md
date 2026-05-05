# End-of-day session report

Background thread runs at 16:05–16:30 ET on weekdays, computes a per-ticker session summary from stored `interval_data` + `interval_session_data` + `centroid_data`, and persists to `session_reports`. Idempotent — never overwrites an existing report.

## Per-report fields

| Field | Description |
|---|---|
| `open_price`, `close_price`, `high_price`, `low_price` | First/last/min/max underlying observed during the session |
| `session_range_pct` | (high − low) / open × 100 |
| `peak_gex_strike` + `peak_gex_value` + `peak_gex_time` | Strike with the largest \|net gamma\| at any minute, with timestamp |
| `atm_gex_flips` | Sign-changes of net GEX at the open-price-ATM strike — proxy for choppiness |
| `em_accuracy_pct` | % of minute observations where price stayed inside the expected-move band |
| `em_breached_upper`, `em_breached_lower` | Did price ever close above/below the band? |
| `centroid_drift` | Closing call-vs-put centroid spread minus opening — directional bias evolution |
| `centroid_open`, `centroid_close`, `centroid_min`, `centroid_max` | Individual snapshots of the spread |
| `minute_bars` | How many minute snapshots fed the report |

## How to view

| Path | Use |
|---|---|
| **`/reports/view`** | HTML index — table of recent reports with key metrics + JSON link per row |
| `GET /reports?ticker=X` | JSON list (ticker filter optional) |
| `GET /reports/<YYYY-MM-DD>?ticker=X` | Full report JSON |
| `POST /reports/run {ticker, date}` | Manual back-fill — useful for missed days or testing |

## Tables

`session_reports(date, ticker UNIQUE, peak_gex_strike, peak_gex_value, em_accuracy_pct, centroid_drift, summary_json, created_at)`.

The full computed report is stored in `summary_json` so the columns are queryable without parsing JSON for the most common metrics.

## Scheduler

A daemon thread (`_session_report_scheduler`) wakes every 5 minutes. If it's a weekday between 16:05 and 16:30 ET, it scans `interval_data` for distinct tickers seen today, compares against `session_reports` to skip duplicates, and runs `_save_session_report(ticker, today)` for each new one.

No cron config required — runs as part of the Flask process. Reports show up after market close on any day with at least some `interval_data` written.

## Caveats

- The 16:05–16:30 window relies on the server clock being correct. If you run in a non-ET timezone, `pytz.timezone('US/Eastern')` handles the conversion.
- Reports are **per-ticker** but the dashboard's primary view is single-ticker, so most days you'll see exactly one report. Multi-ticker sessions (e.g. when watchlist tickers had `interval_data` stored) get one row each.

Related: [replay](replay.md) — same data source, scrubbing UI rather than summary.
