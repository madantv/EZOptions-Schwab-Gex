# Replay / backtest

Scrubbable Plotly chart that animates through every stored minute bar of a session. Lets you watch the gamma walls migrate through e.g. an FOMC day or earnings.

## How to use

Open in your browser:

```
/replay/<YYYY-MM-DD>/view?ticker=X
```

Examples:
- `/replay/2026-04-30/view?ticker=SPY`
- `/replay/2026-04-30/view?ticker=$SPX&strike_range=0.03`

Then:
- **Drag the slider** to scrub by minute
- **▶ Play** to animate at 200ms per frame
- **⏸ Pause** to stop

## Reading the chart

- **Y axis**: strikes
- **X axis**: net GEX (call − put), centred on zero
- **Bars**: per-strike net GEX at the current minute. Call colour = positive (call dealer GEX dominant), put colour = negative.
- **Dashed line**: spot price at that minute
- **Slider label**: clock time in ET

## Query parameters

| Param | Default | Description |
|---|---|---|
| `ticker` | `SPY` | The ticker to replay |
| `strike_range` | none | Optional decimal — clamps strikes to ±X% around the latest spot |

## API

```
GET /replay/<date>?ticker=X            JSON: per-bar (timestamp, price, strike, net_gamma)
GET /replay/<date>/view?ticker=X       Standalone HTML viewer
```

## Data source

Reads `interval_data` rows for (ticker, date). No new Schwab API calls. Falls back to a "no data" placeholder for missing dates (404 on the JSON endpoint).

## Implementation note

Uses Plotly's built-in **frames + slider** animation feature. Server builds the figure with one `go.Frame` per minute; client renders via `Plotly.newPlot` + `Plotly.addFrames`. No custom JS scrubber — Plotly handles play/pause and slider sync natively.

## Caveats

- Replay is **GEX-only** for now. Adding DEX/Vanna/Charm panes is straightforward; ask if you want them as a multi-row layout.
- 200ms frame rate is hardcoded. Easy to add a speed selector if useful.

Related: [session reports](session-reports.md), [Flow Pulse](flow-pulse.md) — same data source, different views.
