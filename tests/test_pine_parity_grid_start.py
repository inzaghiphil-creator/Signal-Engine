"""Pine <-> Python parity for the LONG GRID block (pine/grid_window.pine).

``_pine_mirror`` is a strict line-by-line transcription of the shipped Pine
long-grid block (box/sweep/reclaim state machine, including: a new sweep bar
OVERWRITES the pending sweep, and an in-box reclaim close advances the
cooldown anchor even when the setup is cooldown-rejected — both pinned by
comments in the Pine file). The tests assert the mirror reproduces the
pre-registered Python engine (backtester/grid_start.py) on the real NEAR
data:

* 5m variant (48/12/576): EXACT — every setup (close bar, box, stop, entry).
* 1h variant (24/12/48): same setup count; at most one divergent setup, and
  only the known double-sweep case (Python searches each sweep's reclaim
  independently; Pine keeps a single pending sweep).

The divergence is cosmetic for the watchlist use (same pattern, same
window, entries ~0.4% apart) — see docs/GRID_START_SIGNAL.md.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backtester import grid_start as GS

DATA = Path(__file__).resolve().parent.parent / "data" / "near_5m_real.csv"


def _pine_mirror(f: pd.DataFrame, box: int, reclaim: int, cooldown: int):
    """Line-by-line transcription of pine/grid_window.pine (long grid block).

    Returns a list of (close_bar_idx, box_low, box_high, stop, entry).
    """
    lo = f["low"].to_numpy(float)
    hi = f["high"].to_numpy(float)
    cl = f["close"].to_numpy(float)
    atr = f["atr"].to_numpy(float)
    adx = f["adx"].to_numpy(float)
    n = len(f)
    # L24 = ta.lowest(low, box)[1];  H24 = ta.highest(high, box)[1]
    L = pd.Series(lo).rolling(box).min().shift(1).to_numpy()
    H = pd.Series(hi).rolling(box).max().shift(1).to_numpy()
    # first-breach box: ta.lowest(low, box)[2]  (box of bar i-1)
    L2 = pd.Series(lo).rolling(box).min().shift(2).to_numpy()
    c1 = np.full(n, np.nan)
    c1[1:] = cl[:-1]          # close[1]
    cb = np.full(n, np.nan)
    cb[box:] = cl[:-box]      # close[box]
    with np.errstate(invalid="ignore", divide="ignore"):
        w = (H - L) / atr                       # nz() applied below (Pine nz)
        drift = np.abs(c1 - cb) / atr
        depth = (L - lo) / atr
    nz_w = np.where(np.isnan(w), 0.0, w)
    box_ok = (
        (nz_w >= 2.0) & (nz_w <= 8.0) & (drift <= 1.5) & (adx <= 25.0)
        & np.isfinite(L)
    )
    # Pine: any na in a comparison is false.
    sweep = box_ok & (c1 >= L2) & (lo < L) & (depth <= 1.5)
    pend = -1
    pL = pStop = np.nan
    pH = np.nan
    last = -10**9
    setups = []
    for i in range(n):
        if sweep[i]:                    # if sweep: pendSweep := bar_index; ...
            pend, pL, pH, pStop = i, L[i], H[i], lo[i]
        if pend >= 0:                   # if not na(pendSweep)
            if i > pend + reclaim - 1:
                pend = -1               # reclaim window expired
            elif cl[i] > pH:
                pend = -1               # breakout in between: dead
            elif cl[i] > pL:
                if last < -10**8 or i - last >= cooldown:
                    setups.append((i, pL, pH, pStop, cl[i]))
                last = i                # parity: anchor advances unconditionally
                pend = -1
    return setups


@pytest.fixture(scope="module")
def frames():
    if not DATA.exists():
        pytest.skip("data/near_5m_real.csv not present")
    df5 = GS.load_csv(str(DATA))
    f5 = GS.add_features(df5)
    f1 = GS.add_features(GS.resample_1h(df5))
    return f1, f5


def _assert_same_setups(pine, py_setups, f, max_divergent=0, entry_tol=1e-9):
    assert len(pine) == len(py_setups)
    divergent = 0
    for a, b in zip(pine, py_setups):
        bi = f.index.get_loc(b.signal)
        exact = (
            a[0] == bi
            and abs(a[1] - b.box_low) < 1e-9
            and abs(a[2] - b.box_high) < 1e-9
            and abs(a[3] - b.stop) < 1e-9
            and abs(a[4] - b.entry) < entry_tol
        )
        if exact:
            continue
        # known double-sweep case: same pattern window, entry ~0.4% apart
        divergent += 1
        assert divergent <= max_divergent, f"too many divergent setups: {divergent}"
        assert abs(a[0] - bi) <= 12, f"divergence outside reclaim window: {a[0]} vs {bi}"
        assert abs(a[4] - b.entry) / b.entry <= 0.01, "entry divergence > 1%"


def test_pine_parity_5m_pre_registered(frames):
    f1, f5 = frames
    pine = _pine_mirror(f5, 48, 12, 576)
    py = GS.find_setups(f5, box_bars=48, reclaim_bars=12, cooldown_bars=576)
    assert len(pine) == 12, f"pre-registered 5m run expects 12 setups, got {len(pine)}"
    _assert_same_setups(pine, py, f5, max_divergent=0)


def test_pine_parity_1h(frames):
    f1, _ = frames
    pine = _pine_mirror(f1, 24, 12, 48)
    py = GS.find_setups(f1, box_bars=24, reclaim_bars=12, cooldown_bars=48)
    assert len(pine) == 18, f"pre-registered 1h run expects 18 setups, got {len(pine)}"
    _assert_same_setups(pine, py, f1, max_divergent=1)
