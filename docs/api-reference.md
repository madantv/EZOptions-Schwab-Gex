# API reference

Every HTTP route the dashboard exposes, in one block. Each one links to the feature doc that describes it in detail.

## Existing (unchanged)

```
POST /update                        Fetch chain + render all charts
POST /update_price                  Render price chart only (lightweight)
POST /update_heatmap                Render heatmap only
GET  /price_stream/<ticker>         SSE: live candles + quotes
GET  /expirations/<ticker>          List of expiry dates
GET  /favicon.{svg,ico}             Favicon
GET  /token_health                  Schwab token status
POST /token_delete                  Clear stored Schwab token
```

The three `/update*` routes are now [rate-limited and validated](validation-rate-limit.md).

## Settings — [docs](settings-profiles.md)

```
POST /save_settings?profile=NAME    Persist settings to a named profile
GET  /load_settings?profile=NAME    Load a profile
GET  /profiles                      List profiles
DELETE /profiles/<name>             Delete a profile
```

## Alerts — [docs](alerts.md)

```
GET    /alerts                      List (filter by ticker, status)
POST   /alerts                      Create
PATCH  /alerts/<id>                 Pause / re-arm / re-label
DELETE /alerts/<id>                 Delete (also clears events)
GET    /alerts/<id>/events          Fire history
GET    /alert_stream                SSE: live fire feed
```

## Positions — [docs](positions.md)

```
GET    /positions                   List (filter by ticker, status)
POST   /positions                   Create
PATCH  /positions/<id>              Close / re-label
DELETE /positions/<id>              Delete
```

## Watchlist — [docs](watchlist.md)

```
GET    /watchlist                   List with live quotes
POST   /watchlist                   Add ticker
DELETE /watchlist/<ticker>          Remove
```

## Session reports — [docs](session-reports.md)

```
GET  /reports                       List (filter by ticker)
GET  /reports/<date>?ticker=X       Full report JSON
POST /reports/run {ticker, date}    Manual back-fill
GET  /reports/view                  HTML index
```

## Replay — [docs](replay.md)

```
GET  /replay/<date>?ticker=X        JSON per-bar data
GET  /replay/<date>/view?ticker=X   Interactive Plotly viewer
```

## Observability — [docs](cache-and-stats.md)

```
GET  /_internal/stats               Cache, Schwab, stream, risk-free rate
```

## Conventions

- All routes return JSON unless noted otherwise (a few endpoints are HTML viewers — `/reports/view`, `/replay/<date>/view`).
- Errors are `{"error": "..."}` with the appropriate HTTP status (`400` validation, `404` not found, `409` conflict, `429` rate-limit, `500` internal).
- `POST` bodies are JSON (`Content-Type: application/json`).
- URL-encode parameters that may contain spaces or special characters (`%20`, etc.).
