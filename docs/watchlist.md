# Multi-ticker watchlist sidebar

Slide-out right sidebar that polls quotes for a list of tickers every 5s. Click any row to focus the dashboard on that ticker.

## How to use

1. Click **📋 Watchlist** in the header. The sidebar slides in from the right.
2. Type a ticker in the input + click **＋** (or press Enter) to add.
3. Each row shows: ticker, last price, day change %.
4. Click a row → the main dashboard switches to that ticker (same flow as typing in the ticker box).
5. **✕** on a row removes it.
6. Sidebar auto-refreshes every 5s while open. Closing pauses polling.

The header **📋 Watchlist [N]** badge shows total count, even when the sidebar is closed.

## Quote source

`/watchlist` calls Schwab's `client.quote()` per ticker. For 5–10 tickers this is fast and cheap. The cost is folded into `_internal/stats.schwab.quote`.

If you want to scale to dozens of tickers, the right move is a single batched quotes call (Schwab's `quotes()` accepts comma-separated symbols) — say so and I'll switch.

## API

```
GET    /watchlist                  list with live quotes
POST   /watchlist {ticker, label?} add
DELETE /watchlist/<ticker>         remove (URL-encode the ticker)
```

Add returns `409` if the ticker is already in the watchlist.

## Tables

`watchlist(ticker UNIQUE, label, position, created_at)`. Manual sort by `position` is supported by the schema but no UI yet — drag-to-reorder would be additive.

## Caveats

- Quotes are **polled** every 5s rather than live SSE. Means you can be up to 5s stale on the inactive tickers. For live-tick precision use the main dashboard view.
- No persistence of which sidebar tickers are currently subscribed in `PriceStreamer` — the sidebar deliberately doesn't open extra websockets.
