# EzOptions-Schwab — Documentation

Per-feature reference for everything added on top of the original dashboard. Each link is a focused doc covering what the feature does, how to use it, the API surface, and notable caveats.

## Tier 1 — Trader-visible features

- [Strike-Level Alerts](alerts.md) — 5 alert types (price cross, GEX flip, DEX threshold, EM breach, wall shift) with toast + webhook delivery
- [Flow Pulse — Greek velocity heatmap](flow-pulse.md) — ΔGEX-per-minute view of dealer flow
- [IV solver + cross-check](iv-solver.md) — local Black-Scholes IV solver replacing bad/illiquid Schwab IV
- [Position P&L — manual tracker + chart overlay](positions.md) — owned strikes drawn on the price chart with live P&L

## Tier 2 — Quality / robustness

- [Multi-profile settings](settings-profiles.md) — server-side, named profiles, dropdown UI
- [Input validation + rate-limit](validation-rate-limit.md) — token bucket + payload validators on `/update*`
- [Bounded cache + observability](cache-and-stats.md) — TTL+LRU cache, `/_internal/stats` endpoint
- [Greek-math tests](tests.md) — pytest suite pinning the Black-Scholes math
- *(skipped)* Template extraction — pure refactor, deliberately not done

## Tier 3 — Bigger ideas

- [Multi-ticker watchlist sidebar](watchlist.md) — slide-out sidebar with polled quotes
- [End-of-day session report](session-reports.md) — auto-generated daily summary at 16:05 ET
- [Replay / backtest](replay.md) — scrubbable Plotly chart over stored interval data
- [Macro-adjusted risk-free rate](risk-free-rate.md) — daily T-bill yield from FRED

## Reference

- [Database schemas](database.md) — every table, every column
- [API endpoints](api-reference.md) — every route in one block
- [Smaller fixes shipped along the way](smaller-fixes.md) — GEX level lines, regime cell, stale-price fix, error banner

## Quick smoke test

```bash
cd /Users/madantv/tos/code/EzOptions-Schwab

# Run the Greek-math test suite
python -m pytest tests/ -q

# Start the server
python ezoptionsschwab.py
# → http://localhost:5001

# In another terminal, hit the observability endpoint
curl -s http://localhost:5001/_internal/stats | python -m json.tool
```
