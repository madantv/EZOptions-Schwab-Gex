# Strike-Level Alerts

Alerts that fire when configurable conditions are met against the live options chain or price stream. Delivered as in-app toasts and (optionally) Discord/Slack-style webhooks.

## Five alert types

| Type | Triggers when |
|---|---|
| `price_cross` | Spot crosses a chosen strike (`above` / `below` / `either`) |
| `gex_flip` | Net GEX at a chosen strike (or ATM) changes sign between minute bars |
| `dex_threshold` | \|net DEX\| crosses an absolute dollar threshold |
| `em_breach` | Spot exits the expected-move band (latest snapshot) |
| `wall_shift` | The largest GEX wall jumps ≥ N price units between minute bars |

## Repeat modes

- **`one_shot`** (default) — fires once, then status flips to `triggered`.
- **`rearm`** — fires again only after price moves the configured % away from the trigger price.
- **`always`** — fires on every match (noisy; use sparingly).

## How to use

1. Click **🔔 Alerts** in the header.
2. In the modal, fill out the form: type, params, repeat mode, optional label, optional webhook URL.
3. Hit **Create alert**. The badge on the button shows the number of active alerts.
4. When an alert fires you get a toast in the top-right (auto-dismisses in 8s) and an optional browser notification (you'll be asked for permission once).
5. Use **Pause** / **Re-arm** / **Delete** in the row to manage existing alerts.

## Webhooks

Each alert can carry an optional webhook URL. On fire, the server posts JSON to it on a fire-and-forget thread:

```json
{
  "content": "🔔 [SPY] my alert: price_cross fired",
  "event": {
    "alert_id": 42,
    "ticker": "SPY",
    "alert_type": "price_cross",
    "label": "my alert",
    "fired_at": 1714759200,
    "snapshot": { "price": 500.5, "prev_price": 499.8, "strike": 500, "direction": "up" }
  }
}
```

Compatible with Discord and Slack incoming-webhook URLs out of the box.

## API

```
GET    /alerts                  list (filter by ticker, status)
POST   /alerts                  create
PATCH  /alerts/<id>             pause / re-arm / re-label
DELETE /alerts/<id>             delete (also clears events)
GET    /alerts/<id>/events      fire history (last 200)
GET    /alert_stream            SSE: live fire feed
```

## Tables

- `alerts` — definition + crossing state (`last_value` reset on app boot to avoid phantom fires).
- `alert_events` — append-only fire log.

## Caveats

- Alerts only evaluate against the **active streaming ticker** for `price_cross`/`em_breach`. Greek alerts (`gex_flip`/`dex_threshold`/`wall_shift`) only evaluate when `store_interval_data()` runs, which happens during the regular `/update` flow.
- Webhook delivery is best-effort with an 8s timeout. There's no retry queue.
