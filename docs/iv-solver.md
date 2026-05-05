# IV solver + cross-check

Local Black-Scholes IV solver via `scipy.optimize.brentq`. Replaces Schwab's IV silently when it's missing/zero/illiquid, so every Greek you see is built on a sane volatility input.

## Logic

In `_pick_iv` inside `fetch_options_for_date`:

| Schwab IV | Volume | Resolved IV |
|---|---|---|
| > 0 | ≥ 10 | Schwab's value (trusted) |
| > 0 | < 10 | solved if available, else Schwab |
| ≤ 0 / missing | any | solved from market mid; falls back to 20% if solver can't bracket |

Each option carries `schwab_iv` and `solved_iv` fields internally for diagnostic comparison; they aren't surfaced in any chart yet.

## Solver

`solve_iv(market_price, flag, S, K, t, r, q)` — Brent's method on `_bs_price` over `[0.01, 5.0]` vol bracket. Rejects unphysical inputs:

- Price ≤ 0 or t ≤ 0 → `None`
- Price below intrinsic or above no-arbitrage upper bound → `None`
- Bracket doesn't capture a root → `None`

Recovers σ within 1e-3 across [5%, 200%] vol — see `tests/test_greeks.py::test_iv_solver_recovers_low_and_high_vol`.

## No UI yet

The IV smile chart was a *bonus* in the original design and was deliberately skipped. Three options if you want visibility:

(a) Add `Schwab IV` + `Solved IV` columns to the Options Chain table, highlighted on >10% divergence.
(b) Render an IV smile chart (X = strike, Y = IV, separate call/put traces, optionally with term-structure dropdown) as a new chart-grid toggle.
(c) Both.

Say which.

## Tables

None — pure in-memory computation that flows through `fetch_options_for_date`.

Related: [Greek-math tests](tests.md) cover the solver's edge cases.
