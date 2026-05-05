# Position P&L — manual tracker + chart overlay

Local table of open option positions. Real-time P&L computed from the cached options chain. Owned strikes drawn on the price chart.

## How to use

1. Click **📈 Positions** in the header (next to 🔔 Alerts).
2. Fill the form:
   - Ticker (auto-fills with the active dashboard ticker)
   - Side: Call / Put
   - Qty: positive = long, negative = short
   - Strike, Expiry (`YYYY-MM-DD`), Entry price (per contract)
   - Optional label (e.g. "earnings hedge")
3. Click **Add position**.

## What you see

| Where | What |
|---|---|
| **Modal list** | Each row: summary (`Long 2x CALL 500 @ 2026-06-20`), entry mid, current mid, P&L in green/red. Close + Delete buttons per row. |
| **Price chart** | Solid horizontal line at each owned strike, labelled `±qty SIDE @ strike`. Bullish exposure (long call / short put) uses call colour; bearish uses put colour. |
| **Header badge** | `📈 Positions [N]` shows count of open positions for the active ticker. |

## P&L formula

```
pnl_per_contract = (current_mid − entry_price) × 100
pnl_total        = pnl_per_contract × qty
```

`current_mid` comes from `_options_cache` for the (ticker, expiry) pair. If the chain hasn't been fetched yet for that ticker/expiry, P&L shows `—`.

## Refresh cadence

P&L refreshes on every `/update` response (driven by Auto-Update streaming or settings changes), **not** on every SSE price tick. If you want per-tick mark-to-market via Black-Scholes on the underlying instead of on the cached chain, say so — that's a small additional pass.

## API

```
GET    /positions                  list (filter by ticker, status)
POST   /positions                  create
PATCH  /positions/<id>             close / re-label
DELETE /positions/<id>             delete
```

## Tables

`positions` — id, ticker, side, qty, strike, expiry, entry_price, label, status, opened_at, closed_at.

## Caveats

- This is **manual entry**. No Schwab account-positions integration yet (would require accounts.read scope).
- Closed positions are kept in the DB for history but hidden from the modal by default. Filter via `GET /positions?status=closed`.
