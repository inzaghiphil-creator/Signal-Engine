"""Unit tests for the long-grid START detector (backtester/grid_start.py).

Synthetic 1h fixtures: a 24-bar consolidation "box" on a nearly flat tape,
then controlled sweep/reclaim bars. Box geometry (in ATR units of the tape):
box width ~2.6 ATR (qualifies: 2.0 <= w <= 8.0), close sits ~1.2 ATR above
the box low, so a close 0.2 ATR below the box low keeps the rolling box
qualifying (drift ~1.4 ATR <= 1.5) -- the first-breach rule therefore has
real work to do (it is not masked by box disqualification).
"""
import pandas as pd

from backtester import grid_start as GS
from backtester.grid_window import add_features


def _box(n=70, w=0.0005):
    """Flat tape: close 10.0000, wick +-w. Two wicks at bars 34/35 define the
    box: high[34] = +2.8w (box high), low[35] = -2.4w (box low) -> box
    [9.9988, 10.0014] ~ 2.6 ATR wide, close 1.2 ATR above the box low."""
    idx = pd.date_range("2026-03-01", periods=n, freq="h", tz="UTC")
    c = 10.0000
    df = pd.DataFrame(
        {
            "open": c, "close": c,
            "high": c + w, "low": c - w,
            "volume": 1000.0,
        },
        index=idx,
    )
    df.loc[df.index[34], "high"] = c + 2.8 * w   # box high
    df.loc[df.index[35], "low"] = c - 2.4 * w    # box low
    return df


def _feat(df):
    return GS._box_features(add_features(df))


def _long_tape(days, close_fn):
    """1h tape of `days` days; close_fn(bar_idx) -> close.
    Alternating two-sided wicks (+0.0024/-0.0016, then +0.0016/-0.0024):
    a constant wick would zero one direction's DM and pin ADX at 100."""
    n = days * 24
    idx = pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC")
    close = [close_fn(i) for i in range(n)]
    hi, lo = [], []
    for i, c in enumerate(close):
        if i % 2 == 0:
            hi.append(c + 0.0024); lo.append(c - 0.0016)
        else:
            hi.append(c + 0.0016); lo.append(c - 0.0024)
    return pd.DataFrame(
        {"open": close, "close": close, "high": hi, "low": lo, "volume": 1000.0},
        index=idx,
    )


def test_box_qualifies():
    b = _feat(_box())
    i = 49
    assert b["box_ok"].iloc[i], (
        f"box should qualify at bar {i}: w24={b['w24'].iloc[i]:.2f} "
        f"drift={b['drift24'].iloc[i]:.2f} adx={b['adx'].iloc[i]:.1f}"
    )
    assert 2.0 <= b["w24"].iloc[i] <= 8.0
    assert b["drift24"].iloc[i] <= 1.5
    assert b["adx"].iloc[i] <= 25.0


def test_same_bar_reclaim_is_setup():
    df = _box()
    b = _feat(df)
    i = 50
    L, H, a = b["L24"].iloc[i], b["H24"].iloc[i], b["atr"].iloc[i]
    # sweep bar: wick 0.5 ATR below the box low, close back mid-box (reclaim
    # on the same bar) -> setup, entry = close, stop = sweep low
    df.loc[df.index[i], "low"] = L - 0.5 * a
    df.loc[df.index[i], "close"] = (L + H) / 2
    setups = GS.find_setups(df)
    assert len(setups) == 1
    st = setups[0]
    assert st.sweep == df.index[i]
    assert st.signal == df.index[i]
    assert abs(st.stop - (L - 0.5 * a)) < 1e-9
    assert abs(st.entry - (L + H) / 2) < 1e-9


def test_no_reclaim_within_window_no_setup():
    df = _box()
    b = _feat(df)
    i = 50
    L, a = b["L24"].iloc[i], b["atr"].iloc[i]
    # sweep bar closes below the box; the next 12 bars stay below too
    df.loc[df.index[i], "low"] = L - 0.5 * a
    for j in range(i, i + 13):
        df.loc[df.index[j], "close"] = L - 0.3 * a
        df.loc[df.index[j], "low"] = min(float(df["low"].iloc[j]), L - 0.3 * a)
    setups = GS.find_setups(df)
    assert len(setups) == 0


def test_deep_sweep_rejected():
    df = _box()
    b = _feat(df)
    i = 50
    L, H, a = b["L24"].iloc[i], b["H24"].iloc[i], b["atr"].iloc[i]
    # sweep 2.0 ATR below the box low (> SWEEP_DEPTH_MAX = 1.5), even though
    # price reclaims mid-box on the same bar -> still rejected
    df.loc[df.index[i], "low"] = L - 2.0 * a
    df.loc[df.index[i], "close"] = (L + H) / 2
    setups = GS.find_setups(df)
    assert len(setups) == 0


def test_first_breach_required():
    """A sweep is NOT a setup if the box was already broken: the bar before
    the sweep must not have closed below the box that existed before it."""
    df = _box()
    b = _feat(df)
    i = 50
    L, a = b["L24"].iloc[i], b["atr"].iloc[i]
    # bar i-1 closes 0.2 ATR below the box low (shallow enough that the
    # rolling box still qualifies on bar i: drift ~1.4 ATR)
    prev = df.index[i - 1]
    df.loc[prev, "close"] = L - 0.2 * a
    df.loc[prev, "low"] = L - 0.2 * a
    # bar i: a further sweep 0.2 ATR below the (redefined) box low, price
    # never comes back into the box
    df.loc[df.index[i], "low"] = L - 0.4 * a
    for j in range(i, i + 13):
        df.loc[df.index[j], "close"] = L - 0.4 * a
        df.loc[df.index[j], "low"] = min(float(df["low"].iloc[j]), L - 0.4 * a)
    b2 = _feat(df)
    assert b2["box_ok"].iloc[i], "precondition: rolling box still qualifies"
    setups = GS.find_setups(df)
    assert len(setups) == 0, "breakdown continuation must not be a setup"


# ── Phase 3: 1d close > 1d 21-EMA gate ──────────────────────────────────────

def test_gate_uptrend_vs_downtrend():
    # 40 days: flat 10.0, then a step to 11.0 on day 26
    up = _long_tape(40, lambda i: 10.0 if i < 25 * 24 else 11.0)
    g = GS.gate_1d(up)
    assert not g.iloc[10 * 24:20 * 24].any(), "warmup days must be False"
    assert not g.iloc[21 * 24:25 * 24].any(), "flat: close == EMA -> False (strict >)"
    assert g.iloc[26 * 24:].all(), "after step up: close > EMA -> True"
    # mirror: flat 11.0 then step DOWN to 10.0 -> False after warmup (EMA
    # decays from above, close stays below it)
    dn = _long_tape(40, lambda i: 11.0 if i < 25 * 24 else 10.0)
    g = GS.gate_1d(dn)
    assert not g.iloc[21 * 24:].any(), "downtrend: close < EMA -> False"


def _add_box_and_sweep(df, flat_start):
    """In a flat region: two wicks defining a ~4-6 ATR box, then a 0.5 ATR
    sweep 5 bars later with same-bar reclaim mid-box. Returns sweep bar idx."""
    wick_hi, wick_lo, sweep = flat_start + 330, flat_start + 335, flat_start + 340
    c = float(df["close"].iloc[sweep])
    df.loc[df.index[wick_hi], "high"] = c + 0.012
    df.loc[df.index[wick_lo], "low"] = c - 0.012
    b = _feat(df)  # recompute after the wicks
    L, H, a = b["L24"].iloc[sweep], b["H24"].iloc[sweep], b["atr"].iloc[sweep]
    df.loc[df.index[sweep], "low"] = L - 0.5 * a
    df.loc[df.index[sweep], "close"] = (L + H) / 2
    return sweep


def test_find_setups_respects_gate():
    # 60 days: 30-day drift (up/down), then 30 days flat with one
    # consolidation box + sweep + reclaim in the flat.
    for s in (1, -1):
        def f(i, s=s):
            if i < 720:
                return (10.0 + 0.0004 * i) if s > 0 else (10.2876 - 0.0004 * i)
            return 10.2876 if s > 0 else 10.0
        df = _long_tape(60, f)
        sweep = _add_box_and_sweep(df, 720)
        plain = GS.find_setups(df)
        gated = GS.find_setups(df, use_gate=True)
        if s > 0:
            assert len(plain) == 1, "uptrend: pattern must be detected ungated"
            assert len(gated) == 1, "uptrend: gate must pass"
            assert gated[0].sweep == df.index[sweep]
        else:
            assert len(plain) == 1, "downtrend: pattern shape still detected"
            assert len(gated) == 0, "downtrend: gate must reject"


def test_defaults_equal_frozen_point():
    """A no-kwargs call must equal the explicit frozen parameter set —
    the frozen pre-registered runs (docs §2/§4) rely on the defaults being
    the frozen point forever, even after the sensitivity harness threaded
    the shape thresholds through as parameters."""
    df = _box()
    b = _feat(df)
    i = 50
    L, H, a = b["L24"].iloc[i], b["H24"].iloc[i], b["atr"].iloc[i]
    df.loc[df.index[i], "low"] = L - 0.5 * a
    df.loc[df.index[i], "close"] = (L + H) / 2
    plain = GS.find_setups(df)
    frozen = GS.find_setups(
        df, box_bars=GS.BOX_LOOKBACK, reclaim_bars=GS.RECLAIM_BARS,
        cooldown_bars=GS.COOLDOWN, sweep_depth_max=GS.SWEEP_DEPTH_MAX,
        w_min=GS.BOX_W_MIN, w_max=GS.BOX_W_MAX,
        drift_max=GS.DRIFT_MAX, adx_max=GS.ADX_MAX_BOX)
    assert len(plain) == len(frozen) == 1
    for s1, s2 in zip(plain, frozen):
        for fld in ("box_start", "sweep", "signal", "box_low", "box_high",
                    "stop", "entry", "width_atr", "depth_atr"):
            assert getattr(s1, fld) == getattr(s2, fld), fld


def test_box_bars_parameter_scales_box():
    """box_bars must scale the consolidation window (5m variant wiring)."""
    def f(i):
        if i < 720:
            return 10.0 + 0.0004 * i
        return 10.2876
    df = _long_tape(60, f)
    sweep = _add_box_and_sweep(df, 720)
    s24 = GS.find_setups(df, box_bars=24)
    s48 = GS.find_setups(df, box_bars=48)
    assert len(s24) == 1 and len(s48) == 1, "one designed setup for both box sizes"
    assert s24[0].sweep == s48[0].sweep == df.index[sweep]
    assert s48[0].box_start < s24[0].box_start, "wider box starts earlier"
