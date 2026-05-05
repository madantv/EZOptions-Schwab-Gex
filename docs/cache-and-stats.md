# Bounded cache + observability

Two related improvements: a properly-bounded options cache and a `/_internal/stats` endpoint to inspect it (plus other runtime state).

## Bounded cache

`_options_cache` was an unbounded dict. Now it's a `_BoundedTTLCache`:

- **maxsize**: 32 entries (LRU eviction)
- **ttl_seconds**: 60 (entries expire even if not evicted)
- Drop-in dict interface for `[]`, `.get()`, `.items()`, `.__contains__()`
- Tracks `hits`, `misses`, `evictions` for observability

The cache is keyed by `(ticker, expiry_key)`. Each value is a dict `{calls: DataFrame, puts: DataFrame, S: float}`.

## `/_internal/stats`

Lightweight observability. No auth; intended for debug + ops, not public.

```bash
curl -s http://localhost:5001/_internal/stats | python -m json.tool
```

Returns:

```json
{
  "cache": {
    "size": 4, "max_size": 32, "ttl_seconds": 60.0,
    "hits": 142, "misses": 8, "evictions": 0
  },
  "schwab": {
    "option_chains": 8, "quotes": 0, "quote": 12,
    "option_expiration_chain": 3, "price_history": 5,
    "last_error": null, "last_error_at": null
  },
  "stream": {
    "started": true,
    "subscribed_tickers": ["SPY", "QQQ"],
    "subscriber_count": 2
  },
  "risk_free_rate": 0.0533,
  "risk_free_rate_age_minutes": 12.4,
  "time": 1714759200
}
```

## When to look at this

- **"Why is the dashboard slow?"** — check `cache.hits` vs `misses`; check `schwab.last_error`.
- **"Is my Schwab token actually working?"** — `last_error` will surface 401/429/etc. with the timestamp of the last failure. Counters increment on every call site.
- **"Why is real-time not coming through?"** — `stream.started` and `subscribed_tickers` show whether the websocket is alive and what it's subscribed to.
- **"Are Greeks using current rates?"** — `risk_free_rate_age_minutes` should be < 1440 (24h). If FRED is unreachable it sticks at the 0.02 fallback.

Related: [risk-free rate](risk-free-rate.md), [validation + rate-limit](validation-rate-limit.md).
