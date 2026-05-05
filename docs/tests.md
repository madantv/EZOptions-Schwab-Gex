# Greek-math tests

`tests/test_greeks.py` — pytest suite that pins the Black-Scholes math against an independent reference. Catches regressions if `calculate_greeks` or `solve_iv` ever drift from the textbook formulas.

## Run

```bash
cd /Users/madantv/tos/code/EzOptions-Schwab
python -m pytest tests/ -q
```

Or for verbose:

```bash
python -m pytest tests/ -v
```

## Coverage

10 tests:

| Test | What it verifies |
|---|---|
| `test_call_greeks_canonical` | Call delta/gamma/vega match a textbook BS reference at S=100, K=100, t=0.25, σ=0.30 |
| `test_put_greeks_canonical` | Put delta/gamma/vega match the reference |
| `test_put_call_parity_invariant` | C − P == S·e^(−qt) − K·e^(−rt) |
| `test_call_gamma_equals_put_gamma` | Same gamma for call and put on identical underlying |
| `test_iv_solver_round_trip` | Price an option at known σ, recover σ within 1e-3 |
| `test_iv_solver_rejects_unphysical_prices` | Below intrinsic, ≤ 0, t=0 → returns `None` instead of garbage |
| `test_iv_solver_recovers_low_and_high_vol` | Solver works across σ ∈ {5%, 10%, 50%, 100%, 200%} |
| `test_charm_speed_vomma_color_finite` | Higher-order Greeks aren't NaN or unreasonably large |
| `test_calculate_greek_exposures_scaling` | GEX scales linearly with weight |
| `test_calculate_greek_exposures_zero_weight` | weight=0 → all exposures == 0 (no division by zero) |

## Test fixtures

The `ezo` module-scoped fixture imports the app from a tmp working directory so the test DB doesn't collide with `options_data.db`. Greek calculations are pure-Python so no Schwab credentials are needed.

## Adding tests

Follow the existing pattern:

```python
def test_my_thing(ezo):
    result = ezo.some_function(...)
    assert result == pytest.approx(expected, abs=1e-6)
```

Name fixtures with the `ezo` parameter to get the pre-imported module.
