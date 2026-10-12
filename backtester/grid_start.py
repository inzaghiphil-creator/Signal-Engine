"""Long-grid start signal: consolidation → liquidity sweep → reclaim.

Charter: SIGNAL-ENGINE-GRID-WINDOW-DETECTOR, Phase 2 (user-directed,
2026-10-13). The user's priority for this workstream: find the KEY DATA
that is a strong indication to START A LONG GRID. Loss-avoidance (crash /
market-beta factors) is a secondary filter — see docs/GRID_START_SIGNAL.md
and the risk appendix in docs/GRID_WINDOW.md.

The pattern (as described by the user, made precise and PRE-REGISTERED
below before any scoring — single run, no tuning against outcomes):

  1. CONSOLIDATION — the last 24 completed 1h bars form a box:
       width  (H24 - L24) / ATR  in [2.0, 8.0]
       drift  |close[i-1] - close[i-24]| / ATR  <= 1.5
       ADX(14) <= 25
  2. LIQUIDITY SWEEP — the next bar's LOW breaches L24 (the box low, the
     stop/liquidity pool), as the FIRST breach (close[i-1] >= the box low as
     measured before bar i-1, so a breakdown continuation is not a sweep), with
     depth (L24 - low) / ATR <= 1.5  (a sweep, not a collapse).
  3. RECLAIM — within 12 bars a close returns above L24, with NO close
     above H24 in between (a breakout-in-between is a different pattern).

  SIGNAL  = the reclaim bar; entry price = its close.
  STOP    = the sweep bar's low (invalidation: any later close below it).
  GRID    = suggested range sweep-low → box top H24 (levels in between).

Scored forward from the signal close (HORIZON bars): MFE/MAE, P(+1 ATR /
+2 ATR), invalidation (first close < stop) + time, fraction of closes back
above the box. Baseline = all bars whose box qualifies (step 1) but no
sweep/reclaim — the lift of the pattern over the uneventful box.

Research/monitoring only — NOT an authorised trade recommendation.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .data import detect_tf_seconds, load_csv
from .grid_window import add_features, resample_1h

# ── pre-registered parameters (frozen before scoring) ──────────────────────
BOX_LOOKBACK = 24          # bars (1 day of 1h) for the consolidation box
BOX_W_MIN = 2.0            # box width in ATR units
BOX_W_MAX = 8.0
DRIFT_MAX = 1.5            # net move across the box, ATR units
ADX_MAX_BOX = 25.0
SWEEP_DEPTH_MAX = 1.5      # how far the sweep may dip below the box low
RECLAIM_BARS = 12          # reclaim window after the sweep bar
COOLDOWN = 48              # bars between setups
HORIZON = 96               # forward scoring window (4 days of 1h)

# Phase 3 (authorised 2026-10-13): long-context gate, chosen a priori for a
# long grid (NOT fitted to the Phase 2 sample):
#   gate = 1d close above the 1d 21-EMA (market in an uptrend)
GATE_EMA = 21              # 1d EMA span
GATE_WARMUP_DAYS = 21      # min daily bars before the EMA is trusted

# Phase 3.5 (authorised 2026-10-13): 5m variant — same ATR-normalised shape
# filters, box duration scaled to the consolidation length seen on the
# user's 5m chart (~2-4h; 48 bars = 4h chosen). Frozen before scoring:
#   box 48 · reclaim 12 (1h) · cooldown 576 (48h) · horizon 1152 (96h)
#   NO gate (Phase 3 verdict: test the raw pattern first). Docs §4.2.
TF5M = {"box": 48, "reclaim": 12, "cooldown": 576, "horizon": 1152}


@dataclass
class Setup:
    box_start: pd.Timestamp
    sweep: pd.Timestamp
    signal: pd.Timestamp
    box_low: float
    box_high: float
    stop: float             # sweep low = invalidation
    entry: float            # signal-bar close
    width_atr: float
    depth_atr: float
    # forward metrics (filled by score_forward):
    mfe_pct: float = np.nan
    mae_pct: float = np.nan
    up1_atr: bool = False
    up2_atr: bool = False
    invalid: bool = False
    invalid_h: float = np.nan
    above_frac: float = np.nan
    close96_pct: float = np.nan


def _box_features(f: pd.DataFrame, box_bars: int = BOX_LOOKBACK,
                  w_min: float = BOX_W_MIN, w_max: float = BOX_W_MAX,
                  drift_max: float = DRIFT_MAX,
                  adx_max: float = ADX_MAX_BOX) -> pd.DataFrame:
    out = f.copy()
    L = out["low"].rolling(box_bars).min().shift(1)
    H = out["high"].rolling(box_bars).max().shift(1)
    w = (H - L) / out["atr"]
    drift = (out["close"].shift(1) - out["close"].shift(box_bars)).abs() / out["atr"]
    out["L24"], out["H24"], out["w24"], out["drift24"] = L, H, w, drift
    out["box_ok"] = (
        (w >= w_min) & (w <= w_max)
        & (drift <= drift_max)
        & (out["adx"] <= adx_max)
    )
    return out


def find_setups(f: pd.DataFrame, use_gate: bool = False,
               box_bars: int = BOX_LOOKBACK, reclaim_bars: int = RECLAIM_BARS,
               cooldown_bars: int = COOLDOWN,
               sweep_depth_max: float = SWEEP_DEPTH_MAX,
               w_min: float = BOX_W_MIN, w_max: float = BOX_W_MAX,
               drift_max: float = DRIFT_MAX,
               adx_max: float = ADX_MAX_BOX) -> list[Setup]:
    """Accepts either a raw 1h OHLCV frame or a feature frame (from
    grid_window.add_features); featureises automatically if needed.

    use_gate (Phase 3): a setup only counts if the gate passes on the
    reclaim bar (the entry bar). If the reclaim bar's close is in the box
    but the gate fails, the setup is consumed and rejected — the entry
    moment has passed (no re-evaluation on later bars).

    box_bars / reclaim_bars / cooldown_bars: bar counts scale with the
    chart timeframe. Defaults = the frozen 1h pre-registered set. The 5m
    pre-registered set (Phase 3.5, docs §4.2) passes 48 / 12 / 576.
    sweep_depth_max / w_min / w_max / drift_max / adx_max: ATR-normalised
    shape thresholds, defaulted to the frozen values (only the sensitivity
    harness passes anything else)."""
    if "atr" not in f.columns:
        f = add_features(f)
    b = _box_features(f, box_bars, w_min=w_min, w_max=w_max,
                      drift_max=drift_max, adx_max=adx_max)
    gate = gate_1d(f).to_numpy() if use_gate else None
    lo, hi, cl = b["low"].to_numpy(), b["high"].to_numpy(), b["close"].to_numpy()
    L24, H24, atr = b["L24"].to_numpy(), b["H24"].to_numpy(), b["atr"].to_numpy()
    box_ok = b["box_ok"].to_numpy()
    idx = b.index
    setups: list[Setup] = []
    last_sig = -10**9
    n = len(b)
    for i in range(box_bars + 1, n):
        if not (box_ok[i] and np.isfinite(L24[i])):
            continue
        # must be the FIRST breach: the box was intact on the previous bar,
        # i.e. close[i-1] >= the box low as measured BEFORE bar i-1 (L24[i-1]).
        # (Comparing against L24[i] would let a breakdown bar redefine the
        # box low and let a breakdown continuation masquerade as a sweep.)
        if cl[i - 1] < L24[i - 1]:
            continue
        if lo[i] >= L24[i]:               # no sweep on this bar
            continue
        depth = (L24[i] - lo[i]) / atr[i]
        if depth > sweep_depth_max:
            continue
        # search the reclaim window
        for k in range(i, min(i + reclaim_bars, n)):
            if cl[k] > L24[i] and cl[k] <= H24[i]:
                if gate is not None and not gate[k]:
                    # in-box close but context wrong (gate off): the entry
                    # moment has passed — consume the sweep, reject the setup
                    break
                if i - last_sig >= cooldown_bars:
                    setups.append(Setup(
                        box_start=idx[i - box_bars], sweep=idx[i], signal=idx[k],
                        box_low=float(L24[i]), box_high=float(H24[i]),
                        stop=float(lo[i]), entry=float(cl[k]),
                        width_atr=float((H24[i] - L24[i]) / atr[i]),
                        depth_atr=float(depth),
                    ))
                last_sig = k
                break
            if cl[k] > H24[i]:            # breakout-in-between: pattern dead
                break
    return setups


def _forward(b: pd.DataFrame, i: int, entry: float, stop: float, box_low: float,
             horizon_bars: int = HORIZON) -> dict:
    atr_i = float(b["atr"].iloc[i])
    j0, j1 = i + 1, min(i + 1 + horizon_bars, len(b))
    if j1 <= j0:
        return {}
    fwd_lo = float(b["low"].iloc[j0:j1].min())
    fwd_hi = float(b["high"].iloc[j0:j1].max())
    closes = b["close"].iloc[j0:j1].to_numpy()
    below_stop = np.where(closes < stop)[0]
    return {
        "mfe_pct": (fwd_hi / entry - 1.0) * 100,
        "mae_pct": (fwd_lo / entry - 1.0) * 100,
        "up1_atr": bool(fwd_hi >= entry + 1.0 * atr_i),
        "up2_atr": bool(fwd_hi >= entry + 2.0 * atr_i),
        "invalid": bool(len(below_stop) > 0),
        "invalid_h": float(below_stop[0] + 1) if len(below_stop) else np.nan,
        "above_frac": float(np.mean(closes > box_low)),
        "close96_pct": float((closes[-1] / entry - 1.0) * 100),
    }


def gate_1d(f1h: pd.DataFrame) -> pd.Series:
    """A-priori long-context gate (Phase 3): 1d close above the 1d 21-EMA.

    Computed on 1h bars with no lookahead: on day D at hour t, "today's"
    1d value is the latest 1h close (what a live 1d chart shows intraday)
    and prior days use their day-end closes, so
        EMA_D(t) = alpha * v_D(t) + (1 - alpha) * EMA_{D-1, dayend}
    The gate needs >= GATE_WARMUP_DAYS of daily data, else it fails
    (conservative).
    """
    day = f1h.index.normalize()
    c_day = f1h["close"].groupby(day).last()
    ema_dayend = c_day.ewm(span=GATE_EMA, adjust=False).mean()
    alpha = 2.0 / (GATE_EMA + 1.0)
    v = f1h["close"]
    e_prev = ema_dayend.shift(1).reindex(f1h.index, method="ffill")
    ema_now = alpha * v + (1.0 - alpha) * e_prev
    # day position per bar (bar-ordered array; reindexing by `day` would put
    # the result on duplicated midnight labels and break boolean alignment)
    uniq = pd.Index(np.sort(day.unique()))
    codes = uniq.get_indexer(day)
    valid = pd.Series(codes >= GATE_WARMUP_DAYS - 1, index=f1h.index)
    g = (v > ema_now) & valid & np.isfinite(ema_now)
    return g


def score_setups(b: pd.DataFrame, setups: list[Setup],
                 horizon_bars: int = HORIZON) -> None:
    for s in setups:
        i = b.index.get_loc(s.signal)
        m = _forward(b, i, s.entry, s.stop, s.box_low, horizon_bars)
        for k, v in m.items():
            setattr(s, k, v)


def baseline_sample(b: pd.DataFrame, setups: list[Setup], n_samples: int = 400,
                    seed: int = 7, use_gate: bool = False,
                    horizon_bars: int = HORIZON) -> pd.DataFrame:
    """Forward metrics for random bars whose box qualifies but which are NOT
    setups/sweeps — the control group for the pattern's lift. With use_gate
    (Phase 3) the sample is restricted to gate-passing bars, so the baseline
    is the gated variant's OWN baseline (same construction, same seed)."""
    ok = b["box_ok"].to_numpy() & np.isfinite(b["L24"].to_numpy())
    ok[~np.isfinite(b["atr"].to_numpy())] = False
    if use_gate:
        ok &= gate_1d(b).to_numpy()
    sig_i = {b.index.get_loc(s.signal) for s in setups}
    swp_i = {b.index.get_loc(s.sweep) for s in setups}
    cands = [i for i in range(len(b)) if ok[i] and i not in sig_i and i not in swp_i
             and i + horizon_bars < len(b)]
    rng = np.random.default_rng(seed)
    pick = rng.choice(cands, size=min(n_samples, len(cands)), replace=False) if cands else []
    rows = []
    for i in pick:
        entry = float(b["close"].iloc[i])
        stop = float(b["low"].iloc[i])          # control: "stop" at bar low
        m = _forward(b, i, entry, stop, float(b["L24"].iloc[i]), horizon_bars)
        if m:
            rows.append({"i": i, **m})
    return pd.DataFrame(rows)


# ── report ──────────────────────────────────────────────────────────────────

def build_report(csv_path: str, use_gate: bool = False, tf: str = "1h") -> str:
    """Pre-registered parameter sets (frozen before scoring):
    - tf=1h (Phase 2): box 24 / reclaim 12 / cooldown 48 / horizon 96 bars.
    - tf=5m (Phase 3.5, docs §4.2): box 48 bars (4h, the consolidation
      duration seen on the user's 5m chart) / reclaim 12 (1h) /
      cooldown 576 (48h) / horizon 1152 (96h). Same ATR-normalised shape
      filters, no gate (Phase 3 verdict: test the raw pattern)."""
    df5 = load_csv(csv_path)
    if tf == "1h":
        f = add_features(resample_1h(df5))
        box_bars, reclaim_bars, cooldown_bars, horizon_bars = 24, 12, 48, 96
        bar_min = 60
    elif tf == "5m":
        if detect_tf_seconds(df5) != 300:
            raise SystemExit("--tf 5m requires a native 5m CSV")
        f = add_features(df5)
        box_bars = TF5M["box"]
        reclaim_bars = TF5M["reclaim"]
        cooldown_bars = TF5M["cooldown"]
        horizon_bars = TF5M["horizon"]
        bar_min = 5
    else:
        raise SystemExit(f"unsupported tf {tf!r} (use 1h or 5m)")
    h = bar_min / 60.0
    horizon_h = horizon_bars * h

    b = _box_features(f, box_bars)
    setups_all = find_setups(f)                    # ungated reference
    setups = find_setups(f, use_gate=use_gate, box_bars=box_bars,
                         reclaim_bars=reclaim_bars, cooldown_bars=cooldown_bars)
    score_setups(b, setups, horizon_bars)
    base = baseline_sample(b, setups, use_gate=use_gate, horizon_bars=horizon_bars)

    L: list[str] = []
    A = L.append
    A("LONG-GRID START SIGNAL — consolidation → liquidity sweep → reclaim"
      + (f"  [{tf.upper()} variant]" if tf != "1h" else "")
      + ("  [+ GATE: 1d close > 1d 21-EMA]" if use_gate else ""))
    A(f"data: {csv_path} · {tf} bars {len(f)} · {f.index[0]} → {f.index[-1]}")
    A(f"pre-registered: box {box_bars} bars ({box_bars * h:g}h) "
      f"w∈[{BOX_W_MIN},{BOX_W_MAX}] ATR drift≤{DRIFT_MAX} ADX≤{ADX_MAX_BOX} · "
      f"sweep depth≤{SWEEP_DEPTH_MAX} ATR first-breach · "
      f"reclaim ≤{reclaim_bars} bars ({reclaim_bars * h:g}h) no-breakout · "
      f"cooldown {cooldown_bars} bars ({cooldown_bars * h:g}h) · horizon {horizon_h:g}h"
      + (f" · GATE 1d close > 1d {GATE_EMA}-EMA (warmup {GATE_WARMUP_DAYS}d, at signal bar)"
         if use_gate else ""))
    A("")
    if use_gate:
        gated_sig = {s.signal for s in setups}
        all_sig = {s.signal for s in setups_all}
        dropped = [s for s in setups_all if s.signal not in gated_sig]
        extra = [s for s in setups if s.signal not in all_sig]
        line = f"gate: {len(setups)} of {len(setups_all)} ungated setups pass"
        if dropped:
            line += (f" ({len(dropped)} dropped: "
                     + ", ".join(str(s.signal)[:10] for s in dropped) + ")")
        if extra:  # gated-only: a dropped setup reopened the cooldown window
            line += (f" · {len(extra)} gated-only (cooldown reopened): "
                     + ", ".join(str(s.signal)[:10] for s in extra))
        A(line)
        A("")
    if len(setups) == 0:
        A("NO SETUPS FOUND.")
        return "\n".join(L)
    n = len(setups)
    inv = [s for s in setups if s.invalid]
    up1 = [s for s in setups if s.up1_atr]
    up2 = [s for s in setups if s.up2_atr]
    A(f"SETUPS: {n} of {len(f)} bars")
    A(f"  forward {horizon_h:g}h:  +1 ATR reached {len(up1)/n*100:5.1f}%   +2 ATR {len(up2)/n*100:5.1f}%   "
      f"invalidated (close < sweep low) {len(inv)/n*100:5.1f}%")
    med = lambda xs: float(np.median(xs))
    A(f"  MFE  median {med([s.mfe_pct for s in setups]):+.2f}%  (p25 {np.percentile([s.mfe_pct for s in setups],25):+.2f} / p75 {np.percentile([s.mfe_pct for s in setups],75):+.2f})")
    A(f"  MAE  median {med([s.mae_pct for s in setups]):+.2f}%  (worst {min(s.mae_pct for s in setups):+.2f})")
    A(f"  above box after: median {med([s.above_frac for s in setups])*100:.0f}% of closes above box low")
    A(f"  close@{horizon_h:g}h median {med([s.close96_pct for s in setups]):+.2f}%")
    A("")
    A("BASELINE (random qualifying boxes, no sweep; n=%d):" % len(base))
    if len(base):
        A(f"  +1 ATR {base['up1_atr'].mean()*100:5.1f}%   +2 ATR {base['up2_atr'].mean()*100:5.1f}%   "
          f"invalidated {base['invalid'].mean()*100:5.1f}%   MFE med {base['mfe_pct'].median():+.2f}%   "
          f"MAE med {base['mae_pct'].median():+.2f}%   above-box {base['above_frac'].mean()*100:.0f}%")
        A("")
        A("LIFT vs baseline:  +1 ATR "
          f"{(up1 and (len(up1)/n - base['up1_atr'].mean()))*100:+.1f}pp · "
          f"invalidation {(len(inv)/n - base['invalid'].mean())*100:+.1f}pp · "
          f"MFE med {med([s.mfe_pct for s in setups]) - base['mfe_pct'].median():+.2f}pp")
        A("")
    A("SETUP DETAIL (entry = reclaim close; stop = sweep low = invalidation):")
    A(f"  {'signal':<17} {'box low':>8} {'box high':>9} {'entry':>8} {'stop':>8} {'depth':>5}  "
      f"{'MFE%':>7} {'MAE%':>7} {'+1A':>4} {'+2A':>4} {'inv':>4} {'inv@h':>6} {'>box':>5} {'c96%':>7}")
    for s in setups:
        A(f"  {str(s.signal)[:16]:<17} {s.box_low:8.3f} {s.box_high:9.3f} {s.entry:8.3f} {s.stop:8.3f} "
          f"{s.depth_atr:5.2f}  {s.mfe_pct:7.2f} {s.mae_pct:7.2f} "
          f"{'Y' if s.up1_atr else '—':>4} {'Y' if s.up2_atr else '—':>4} "
          f"{'Y' if s.invalid else '—':>4} {(f'{s.invalid_h * h:.0f}' if s.invalid else '—'):>6} "
          f"{s.above_frac*100:5.0f} {s.close96_pct:7.2f}")
    A("")
    A("Suggested grid per setup: LONG grid from just above the stop (sweep low)")
    A("up to the box top; a close back below the stop = setup invalidated.")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Long-grid start signal (research)")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--tf", choices=["1h", "5m"], default="1h",
                    help="bar timeframe of the detection (1h = Phase 2 frozen "
                         "set; 5m = Phase 3.5 pre-registered set, docs §4.2)")
    ap.add_argument("--gate", action="store_true",
                    help="Phase 3: require 1d close > 1d 21-EMA at the signal bar")
    args = ap.parse_args(argv)
    print(build_report(args.csv, use_gate=args.gate, tf=args.tf))
    return 0


if __name__ == "__main__":
    sys.exit(main())
