# Macro-adjusted risk-free rate

`r=0.02` was hardcoded everywhere, biasing every Greek when rates moved. Now we pull the 3-month Treasury yield from FRED's `DGS3MO` series once per 24h and use that for all Greek calculations.

## How it works

`_get_risk_free_rate()`:

1. Returns the cached value if it's < 24h old.
2. Otherwise calls FRED's CSV endpoint:
   ```
   https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS3MO
   ```
3. Parses the last non-empty value (yield in percent), divides by 100 → decimal rate.
4. Caches the result.
5. On any failure (network, parse error, value out of `[0, 0.25]`): caches the fallback constant `0.02` and retries in 10 minutes (not 24h).

No API key required — FRED's `fredgraph` CSV is unauthenticated.

## Where it's used

Two hardcoded `r = 0.02` sites were replaced:

- `fetch_options_for_date` — initial Greek computation in the chain parser
- `calculate_greek_exposures` — Greek recomputation per option in the exposure pass

The function-signature defaults (e.g. `def calculate_greeks(..., r=0.02, q=0)`) are unchanged — they're fallbacks if a caller doesn't pass `r`. The main code paths now pass the dynamically-fetched rate.

## How to verify

`/_internal/stats` exposes:

```json
{
  "risk_free_rate": 0.0533,
  "risk_free_rate_age_minutes": 12.4
}
```

If `risk_free_rate` stays at `0.02` for hours, FRED is unreachable from the host (firewall? DNS?). Check by hitting the URL above directly with curl.

## Caveats

- 3-month yield is the standard pick for short-dated Greeks. For LEAPS-heavy use a longer tenor; trivial to switch to `DGS1` (1-year) or `DGS10` (10-year) — change the `id=` query param.
- No interpolation across the curve yet. Same `r` is used for 0DTE and LEAPS. The bias from this is small relative to other modeling assumptions.

Related: [cache + stats](cache-and-stats.md) — same observability endpoint surfaces the rate.
