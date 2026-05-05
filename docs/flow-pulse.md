# Flow Pulse — Greek velocity heatmap

ΔGEX-per-minute view derived from the existing `interval_data` snapshots. Shows the *change* in dealer gamma at each strike vs the prior minute — call colour where gamma is being added, put colour where it's unwound.

The **rate** of dealer flow is what front-runners watch; the absolute level is already covered by GEX charts.

## How to use

1. Reload the page so the new chart appears in the chart-grid checkboxes.
2. Tick **Flow Pulse (ΔGEX)** (between "Centroid Map" and "Premium").
3. Wait for ≥ 2 minute bars of session data. (Outside market hours the chart shows a placeholder; it falls back to the most recent session that has data.)

## Reading the chart

- **Y axis**: strikes (high on top, like a price chart)
- **X axis**: clock time (last 15 minutes), Eastern Time
- **Color**: ΔGEX intensity. Bright green = gamma being added. Bright red = unwound. Dark = no change.
- **Dashed line**: latest spot price reference

## Data source

Pure derived view — no extra Schwab API calls. Reads `interval_data` rows that the dashboard already writes every minute during market hours.

## Caveats

- "Lookback" is hardcoded to 15 minutes for now. Easy to make configurable if you want — say so.
- The heatmap is sized by the strike range slider's current value, so the grid changes shape when you adjust the range.

Related: [session reports](session-reports.md), [replay](replay.md) — both also derive from `interval_data`.
