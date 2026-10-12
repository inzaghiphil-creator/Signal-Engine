"""Pinned tests for the grid-window detector state machine (synthetic data).

Charter: SIGNAL-ENGINE-GRID-WINDOW-DETECTOR. These lock the state-machine
semantics (state precedence, recontainment, exposure, window log) so the
Python reference and the Pine mirror stay comparable.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backtester import grid_window as G


def _synthetic(n: int = 260) -> pd.DataFrame:
    """Two-sided flat 10.00 range (bars 0-199), a single walk bar that breaks
    the 20-bar channel up WITHOUT being a 2σ bar (bar 200), back to range
    (201+). 1h, open-indexed, UTC.

    Two-sided noise is deliberate: a one-sided synthetic makes one DI
    identically zero, which drives DX (and hence ADX) to 100 — correct ADX
    behaviour on degenerate data, but useless for testing the DEPLOYABLE
    branch.
    """
    idx = pd.date_range("2026-01-05 00:00", periods=n, freq="1h", tz="UTC")
    close = np.where(np.arange(n) % 2 == 0, 10.000, 10.001)
    o = np.empty(n)
    o[0] = 10.000
    o[1:] = close[:-1]
    # alternate the wick side so BOTH +DM and -DM fire across the range
    h = np.maximum(o, close) + np.where(np.arange(n) % 2 == 0, 0.002, 0.0005)
    l = np.minimum(o, close) - np.where(np.arange(n) % 2 == 0, 0.0005, 0.002)
    v = np.full(n, 1000.0)
    i = 200  # walk bar: closes above the 20-bar high, small range (not 2σ)
    o[i], close[i] = 10.001, 10.006
    h[i] = 10.0065
    l[i] = 10.0005
    return pd.DataFrame(
        {"open": o, "high": h, "low": l, "close": close, "volume": v}, index=idx
    )


def test_quiet_range_is_deployable():
    f = G.run_states(G.add_features(_synthetic()))
    quiet = f.iloc[40:200]
    assert (quiet["state"] == G.DEPLOYABLE).sum() >= 30, (
        quiet["state"].value_counts().to_dict()
    )
    assert quiet["state"].isin([G.EXPOSED_UP, G.EXPOSED_DN, G.BREAK_SIG]).sum() == 0


def test_breakout_bar_is_exposed():
    f = G.run_states(G.add_features(_synthetic()))
    # bar 200 closes above the 20-bar high → EXPOSED_UP (range is small,
    # so it is NOT a 2σ bar — it routes to exposure, not BREAK_SIG)
    assert f.iloc[200]["state"] == G.EXPOSED_UP
    assert f.iloc[200]["sig"] is np.False_ or f.iloc[200]["sig"] == False


def test_recontainment_then_redeployable():
    f = G.run_states(G.add_features(_synthetic()))
    # bar 201 = first bar back inside → SETTLING (recontain < 3)
    assert f.iloc[201]["state"] == G.SETTLING
    # after >= 3 bars back inside, the box is contained again and (with no
    # 2σ bar and quiet ADX) should be DEPLOYABLE or a settled non-exposed
    assert f.iloc[204]["state"] in {G.DEPLOYABLE, G.CALM_SIG, G.TRENDING, G.COILED}
    assert f.iloc[204]["state"] not in {G.EXPOSED_UP, G.EXPOSED_DN, G.BREAK_SIG, G.SETTLING}


def test_window_log_captures_break_side():
    f = G.run_states(G.add_features(_synthetic()))
    wins = G.window_log(f)
    assert wins[0].exit == "UP"
    assert wins[0].start == f.index[0]
    assert wins[0].end == f.index[199]
    assert wins[1].start == f.index[201]


def test_cushion_and_box_width_finite_in_range():
    f = G.run_states(G.add_features(_synthetic()))
    r = f.iloc[100]
    assert np.isfinite(r["cush_near"]) and r["cush_near"] > 0
    assert np.isfinite(r["box_w_atr"]) and r["box_w_atr"] > 0
    assert np.isfinite(r["cush_down"]) and np.isfinite(r["cush_up"])


def test_cushion_profile_shapes():
    f = G.run_states(G.add_features(_synthetic()))
    cp = G.cushion_profile(f)
    assert set(cp["hazard_cush_le_1"]) == {"n", "danger_6h", "danger_24h"}
    assert 0.0 <= cp["hazard_cush_le_1"]["danger_24h"] <= 100.0
    assert 0.0 <= cp["hazard_cush_gt_2"]["danger_24h"] <= 100.0
