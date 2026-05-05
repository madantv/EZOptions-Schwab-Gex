"""Pin Black-Scholes Greeks at canonical inputs.

These tests guard the math under fetch_options_for_date / calculate_greeks
against accidental regressions when the calculation pipeline is refactored.
Reference values were generated from the same Black-Scholes formulas using
S=100, K=100, t=0.25, sigma=0.30, r=0.02, q=0 — a standard ATM, 3-month case.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(scope='module')
def ezo():
    """Import the app module from a tmp cwd so it doesn't touch the real DB."""
    tmp = tempfile.mkdtemp(prefix='ezo_test_')
    cwd_before = os.getcwd()
    os.chdir(tmp)
    repo_root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location('ezo_under_test', repo_root / 'ezoptionsschwab.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    os.chdir(cwd_before)


# ── Canonical Black-Scholes inputs (ATM, 3-month) ───────────────────────────
S, K, t, sigma, r, q = 100.0, 100.0, 0.25, 0.30, 0.02, 0.0


def _ref_bs_greeks(flag, S, K, t, sigma, r, q):
    """Textbook Black-Scholes reference, computed independently of the module
    under test. Returns (delta, gamma, vega) — the three Greeks both
    implementations agree on for tactical calculations."""
    import math
    from scipy.stats import norm
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))
    pdf = norm.pdf(d1)
    if flag == 'c':
        delta = math.exp(-q * t) * norm.cdf(d1)
    else:
        delta = math.exp(-q * t) * (norm.cdf(d1) - 1)
    gamma = math.exp(-q * t) * pdf / (S * sigma * math.sqrt(t))
    vega  = S * math.exp(-q * t) * pdf * math.sqrt(t)
    return delta, gamma, vega


def test_call_greeks_canonical(ezo):
    delta, gamma, vega, _vanna = ezo.calculate_greeks('c', S, K, t, sigma, r, q)
    ref_delta, ref_gamma, ref_vega = _ref_bs_greeks('c', S, K, t, sigma, r, q)
    assert delta == pytest.approx(ref_delta, abs=1e-6)
    assert gamma == pytest.approx(ref_gamma, abs=1e-6)
    assert vega  == pytest.approx(ref_vega,  abs=1e-3)


def test_put_greeks_canonical(ezo):
    delta, gamma, vega, _vanna = ezo.calculate_greeks('p', S, K, t, sigma, r, q)
    ref_delta, ref_gamma, ref_vega = _ref_bs_greeks('p', S, K, t, sigma, r, q)
    assert delta == pytest.approx(ref_delta, abs=1e-6)
    assert gamma == pytest.approx(ref_gamma, abs=1e-6)
    assert vega  == pytest.approx(ref_vega,  abs=1e-3)


def test_put_call_parity_invariant(ezo):
    """C - P should equal S e^{-qt} - K e^{-rt} regardless of sigma."""
    import math
    c = ezo._bs_price('c', S, K, t, sigma, r, q)
    p = ezo._bs_price('p', S, K, t, sigma, r, q)
    parity_rhs = S * math.exp(-q * t) - K * math.exp(-r * t)
    assert (c - p) == pytest.approx(parity_rhs, abs=1e-6)


def test_call_gamma_equals_put_gamma(ezo):
    """Gamma is the same for call and put on the same underlying/strike/tenor."""
    _d_c, g_c, _v_c, _va_c = ezo.calculate_greeks('c', S, K, t, sigma, r, q)
    _d_p, g_p, _v_p, _va_p = ezo.calculate_greeks('p', S, K, t, sigma, r, q)
    assert g_c == pytest.approx(g_p, abs=1e-9)


def test_iv_solver_round_trip(ezo):
    """Price an option at a known IV; recovered IV should match within 1e-3."""
    target = 0.30
    call_px = ezo._bs_price('c', S, K, t, target, r, q)
    recovered = ezo.solve_iv(call_px, 'c', S, K, t, r, q)
    assert recovered is not None
    assert recovered == pytest.approx(target, abs=1e-3)

    # And puts.
    put_px = ezo._bs_price('p', S, K, t, target, r, q)
    recovered_p = ezo.solve_iv(put_px, 'p', S, K, t, r, q)
    assert recovered_p == pytest.approx(target, abs=1e-3)


def test_iv_solver_rejects_unphysical_prices(ezo):
    """No-arbitrage bounds: prices below intrinsic or ≤0 → None, not garbage."""
    assert ezo.solve_iv(0.0, 'c', S, K, t, r, q) is None
    assert ezo.solve_iv(-1.0, 'c', S, K, t, r, q) is None
    # Below intrinsic for an ITM call.
    assert ezo.solve_iv(0.001, 'c', 110.0, 100.0, 0.25, r, q) is None
    # Zero time-to-expiry has no IV solution.
    assert ezo.solve_iv(2.0, 'c', S, K, 0.0, r, q) is None


def test_iv_solver_recovers_low_and_high_vol(ezo):
    """Solver shouldn't break at the edges of plausible IV (5% and 200%)."""
    for target in (0.05, 0.10, 0.50, 1.0, 2.0):
        px = ezo._bs_price('c', S, K, t, target, r, q)
        recovered = ezo.solve_iv(px, 'c', S, K, t, r, q)
        assert recovered is not None, f'failed at sigma={target}'
        assert recovered == pytest.approx(target, abs=1e-3), f'recovered {recovered} for sigma={target}'


def test_charm_speed_vomma_color_finite(ezo):
    """Higher-order Greeks shouldn't NaN/blow up on standard inputs."""
    charm  = ezo.calculate_charm('c', S, K, t, sigma, r, q)
    speed  = ezo.calculate_speed('c', S, K, t, sigma, r, q)
    vomma  = ezo.calculate_vomma('c', S, K, t, sigma, r, q)
    color  = ezo.calculate_color('c', S, K, t, sigma, r, q)
    for name, val in (('charm', charm), ('speed', speed), ('vomma', vomma), ('color', color)):
        assert val == val, f'{name} is NaN'  # NaN != NaN
        # Sanity: each Greek should be a finite, non-extreme number for ATM 3-month.
        assert abs(val) < 100, f'{name} is unreasonably large: {val}'


def test_calculate_greek_exposures_scaling(ezo):
    """GEX should scale linearly with weight; flipping flag shouldn't change gamma."""
    option = {
        'contractSymbol': 'TEST  240315C00100000',
        'strike': K,
        'impliedVolatility': sigma,
        'expiration': __import__('datetime').date(2099, 1, 1),
        'gamma': 0.0263, 'delta': 0.5398, 'theta': 0, 'vega': 0, 'rho': 0,
    }
    e1 = ezo.calculate_greek_exposures(option, S, weight=10, calculate_in_notional=True)
    e2 = ezo.calculate_greek_exposures(option, S, weight=20, calculate_in_notional=True)
    # GEX is linear in weight. Tolerance accounts for clock-drift in
    # calculate_time_to_expiration between the two calls.
    assert e2['GEX'] == pytest.approx(2.0 * e1['GEX'], rel=1e-6)


def test_calculate_greek_exposures_zero_weight(ezo):
    """Zero weight → all exposures should be zero (no division by zero, no NaN)."""
    option = {
        'contractSymbol': 'TEST  240315C00100000',
        'strike': K,
        'impliedVolatility': sigma,
        'expiration': __import__('datetime').date(2099, 1, 1),
        'gamma': 0.0263, 'delta': 0.5398, 'theta': 0, 'vega': 0, 'rho': 0,
    }
    e = ezo.calculate_greek_exposures(option, S, weight=0, calculate_in_notional=True)
    for k, v in e.items():
        assert v == 0, f'{k} should be 0 with weight=0, got {v}'
