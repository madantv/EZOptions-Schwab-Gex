# Input validation + rate-limit

Server-side hardening on the three `/update*` routes. No UI changes — purely defensive.

## Rate limit

Token bucket per IP on `/update`, `/update_price`, `/update_heatmap`:

- **20-token burst** (allows quick bursts when toggling settings)
- **4 tokens/sec sustained** (well above the auto-refresh streaming rate of ~1 Hz)

Over-limit → `429` with `{"error": "Rate limit exceeded — slow down requests."}`.

The IP key uses `X-Forwarded-For` if present, falling back to `request.remote_addr`. So on a reverse-proxy deployment the limiter works per real client IP, not per proxy.

## Payload validation

`_validate_update_payload` checks:

| Field | Rule |
|---|---|
| `ticker` | required, ≤ 12 chars, regex `^[\$/]?[A-Za-z0-9._-]+$` |
| `expiry` | required on `/update` (lenient on `/update_price`); string or list of strings |
| `strike_range` | numeric in `(0, 1]` |
| `levels_count` | integer in `[1, 20]` |
| `timeframe` | one of `{1, 5, 15, 30, 60}` |
| `exposure_metric` | one of `Open Interest`, `Volume`, `Max OI vs Volume`, `OI + Volume` |
| `coloring_mode` | one of `Solid`, `Linear Intensity`, `Ranked Intensity` |
| `heatmap_coloring_mode` | one of `Global`, `Per Expiration` |
| `max_level_mode` | one of `Absolute`, `Per Expiration`, `Per Type` |
| `levels_types` | list of ≤ 12 strings |

Validation failure → `400` with the specific field name in the error message.

## Why

- Stops a runaway client (or a JS bug) from saturating the Schwab API quota.
- Stops malformed payloads from reaching `fetch_options_for_date` and crashing in unexpected ways.
- Centralised: any new `/update*`-style route just calls `_guard_update_request()` at the top to inherit both rate-limit and validation.

## Caveats

- The limiter is in-memory; restarting the server resets all buckets.
- No 429 retry-after header yet. Add if anyone needs it.
