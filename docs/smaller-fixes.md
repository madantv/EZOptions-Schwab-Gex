# Smaller fixes shipped along the way

Not headline features, but worth knowing about.

## Live GEX level lines on the price chart

When you tick **GEX** in the chart's Levels picker, you get up to 13 lines per refresh:

- **3 net-GEX lines** (or whatever Top # is set to) — `dashed`, label `GEX: $X` (signed value, top-N strikes by `|put_GEX − call_GEX|` in dealer convention; positive = dealers long gamma at that strike, drawn in call colour)
- **5 call walls** — `dotted`, your call colour, label `GEX Call: $X` (5 strikes with the largest call-side GEX — direction-agnostic concentration view)
- **5 put walls** — `dotted`, your put colour, label `GEX Put: $X` (5 strikes with the largest put-side GEX)

Plus the GEX regime cell (below).

Both rendering paths in `prepare_price_chart_data` (lightweight chart) and `applyPriceData` (client-side TradingView render). Lines refresh on every `/update_price` response and clear on ticker change.

The 5+5 split is hardcoded. The net top-N count follows the existing **Top #** input. Tell me if you want them tied together.

## GEX regime cell in the price-info row

The price-info strip (Current Price · Day High · Day Low · Change · Vol Ratio · Expected Move · Expiries) now ends with a **GEX Regime** cell. Label depends on the active sign convention (toggle in the advanced controls — see below):

| Convention | Positive label | Negative label |
|---|---|---|
| **Dealer** (`put − call`) | ▲ Long Gamma | ▼ Short Gamma |
| **Raw** (`call − put`) | ▲ Call-dominant | ▼ Put-dominant |

Computed across the **visible strike range** (the strike-range slider value). Hover the cell to see which convention is active plus the calls vs puts breakdown.

Lives in the `/update` payload as `info.gex_regime` with `{net, sign, label, convention, total_call, total_put}`. Refreshes with the rest of the price-info row.

## GEX sign convention toggle

Advanced controls now have a **GEX Sign** dropdown:

- **Dealer (put − call)** — default. Positive means dealers are net long gamma (assumes customers buy calls / sell puts). Matches SqueezeMetrics, SpotGamma, and most institutional desks.
- **Raw (call − put)** — direction-agnostic. Positive means call OI/gamma is the heavier side. No dealer assumption.

The choice flips the sign of:

- The **GEX regime cell** label and value
- The **net top-N GEX lines** drawn on the price chart
- The **net Gamma Exposure chart** trace
- The **exposure heatmap** in `Net` mode

The **5+5 per-side walls** on the price chart stay direction-agnostic regardless of the toggle — they're concentration markers, not directional.

Implementation: a request-scoped `_get_gex_sign()` in Python, set by `_guard_update_request()` on each `/update*` request from the payload's `gex_sign` field. The `gex_net(call, put)` helper reads from this context, so chart builders don't need to thread the convention through their signatures.

## Stale current-price fix on ticker change

Two stale-price paths used to show the **old** ticker's price after switching:

1. `livePrice` global (set on every SSE quote) — used by `updatePriceInfo` if non-null.
2. `plotlyPriceUpdateTimer` — 500ms-debounced call to `updateAllPlotlyPriceLines` that could fire with the old ticker's `last` value after the switch.

Fixed by resetting both in the `if (tickerChanged)` block in `updateData()`, plus blanking the Current Price cell to `$—` until the new ticker's first SSE tick arrives. Position strike-lines on the price chart are also wiped.

## Error banner on `/update_price`

Instead of silently leaving the chart blank when Schwab fails, a red banner now appears across the top of the price chart with the actual error message — e.g. `401 Unauthorized`, rate-limit, or "Malformed price history data from Schwab API".

Implemented as `showPriceChartError(msg)` / `clearPriceChartError()` in the inline JS. Banner is positioned absolute over `.price-chart-container` with z-index 50.

This was added because the old code path swallowed `/update_price` errors silently in `.catch(err => console.error(...))`, leaving the user with a blank chart and no idea why.
