"""Sensitivity analysis for the long-grid START pattern (one-at-a-time).

NOT a new signal. The frozen pre-registered runs (1h, 1h+gate, 5m) all
showed no forward edge over their own baselines. This harness maps how
ROBUST that null is to small adjustments, the way a sensitivity analysis
should:

* ONE-AT-A-TIME: each variant changes a single parameter around the
  frozen point (no combinatorial search — that is how a null becomes a
  fake edge).
* Each variant is scored against ITS OWN baseline (the shape filters
  define the qualifying-box population, so each variant's control group
  is rebuilt from the same data, same seed).
* The whole surface is reported; nothing is cherry-picked.
* Pre-stated credibility rule (see docs/GRID_START_SIGNAL.md §4.3): with
  ~20 variants per TF, a single isolated improvement is expected under
  pure noise. A credible direction needs (a) lift >= +2.0pp on MFE median
  AND positive +1 ATR lift AND n >= 8, and (b) at least one NEIGHBOURING
  variant (same parameter, either side) also showing positive MFE lift.
  Anything else leaves the verdict unchanged.

Research/monitoring only — NOT an authorised trade recommendation.
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

from .data import detect_tf_seconds, load_csv
from .grid_window import add_features, resample_1h
from . import grid_start as GS


def _row(label: str, f: pd.DataFrame, horizon_bars: int, **params) -> dict:
    """Run one variant: setups + its own baseline, lift metrics."""
    box_kw = {k: v for k, v in params.items()
              if k in ("box_bars", "w_min", "w_max", "drift_max", "adx_max")}
    b = GS._box_features(f, **box_kw)
    setups = GS.find_setups(f, **params)
    GS.score_setups(b, setups, horizon_bars)
    base = GS.baseline_sample(b, setups, horizon_bars=horizon_bars)
    n = len(setups)
    if n == 0 or base.empty:
        return {"variant": label, "n": 0, "mfe": np.nan, "bmfe": np.nan,
                "lift": np.nan, "u1": np.nan, "bu1": np.nan,
                "inv": np.nan, "binv": np.nan, "worst_mae": np.nan}
    u1 = sum(s.up1_atr for s in setups) / n
    inv = sum(s.invalid for s in setups) / n
    return {
        "variant": label,
        "n": n,
        "mfe": float(np.median([s.mfe_pct for s in setups])),
        "bmfe": float(base["mfe_pct"].median()),
        "lift": float(np.median([s.mfe_pct for s in setups])) - float(base["mfe_pct"].median()),
        "u1": u1 * 100, "bu1": float(base["up1_atr"].mean() * 100),
        "inv": inv * 100, "binv": float(base["invalid"].mean() * 100),
        "worst_mae": float(min(s.mae_pct for s in setups)),
    }


def _grid_1h(base: dict) -> list[tuple[str, dict]]:
    """One-at-a-time neighbours of the frozen 1h point (pre-registered)."""
    g = []
    g.append(("box=18", {**base, "box_bars": 18}))
    g.append(("box=36", {**base, "box_bars": 36}))
    g.append(("w_max=6", {**base, "w_max": 6.0}))
    g.append(("w_min=3", {**base, "w_min": 3.0}))
    g.append(("drift=1.0", {**base, "drift_max": 1.0}))
    g.append(("drift=2.0", {**base, "drift_max": 2.0}))
    g.append(("adx=20", {**base, "adx_max": 20.0}))
    g.append(("adx=30", {**base, "adx_max": 30.0}))
    g.append(("depth=1.0", {**base, "sweep_depth_max": 1.0}))
    g.append(("depth=2.0", {**base, "sweep_depth_max": 2.0}))
    g.append(("reclaim=6", {**base, "reclaim_bars": 6}))
    g.append(("reclaim=18", {**base, "reclaim_bars": 18}))
    g.append(("cooldown=24", {**base, "cooldown_bars": 24}))
    g.append(("cooldown=96", {**base, "cooldown_bars": 96}))
    return g


def _grid_5m(base: dict) -> list[tuple[str, dict]]:
    """One-at-a-time neighbours of the frozen 5m point (pre-registered)."""
    g = []
    g.append(("box=36", {**base, "box_bars": 36}))
    g.append(("box=60", {**base, "box_bars": 60}))
    g.append(("w_max=6", {**base, "w_max": 6.0}))
    g.append(("w_min=3", {**base, "w_min": 3.0}))
    g.append(("drift=1.0", {**base, "drift_max": 1.0}))
    g.append(("drift=2.0", {**base, "drift_max": 2.0}))
    g.append(("adx=20", {**base, "adx_max": 20.0}))
    g.append(("adx=30", {**base, "adx_max": 30.0}))
    g.append(("depth=1.0", {**base, "sweep_depth_max": 1.0}))
    g.append(("depth=2.0", {**base, "sweep_depth_max": 2.0}))
    g.append(("reclaim=6", {**base, "reclaim_bars": 6}))
    g.append(("reclaim=18", {**base, "reclaim_bars": 18}))
    g.append(("cooldown=288", {**base, "cooldown_bars": 288}))
    g.append(("cooldown=1152", {**base, "cooldown_bars": 1152}))
    return g


def run(csv_path: str, tf: str) -> str:
    df5 = load_csv(csv_path)
    if tf == "1h":
        f = add_features(resample_1h(df5))
        base = {"box_bars": 24, "reclaim_bars": 12, "cooldown_bars": 48,
                "w_min": 2.0, "w_max": 8.0, "drift_max": 1.5,
                "adx_max": 25.0, "sweep_depth_max": 1.5}
        horizon = 96
        grid = _grid_1h(base)
    elif tf == "5m":
        if detect_tf_seconds(df5) != 300:
            raise SystemExit("--tf 5m requires a native 5m CSV")
        f = add_features(df5)
        base = {"box_bars": 48, "reclaim_bars": 12, "cooldown_bars": 576,
                "w_min": 2.0, "w_max": 8.0, "drift_max": 1.5,
                "adx_max": 25.0, "sweep_depth_max": 1.5}
        horizon = 1152
        grid = _grid_5m(base)
    else:
        raise SystemExit(f"unsupported tf {tf!r}")

    rows = [_row("FROZEN (base)", f, horizon, **base)]
    for label, p in grid:
        rows.append(_row(label, f, horizon, **p))
    df = pd.DataFrame(rows)

    L: list[str] = []
    A = L.append
    A(f"SENSITIVITY — long-grid START, one-at-a-time around the frozen {tf} point")
    A(f"data: {csv_path} · {len(f)} bars · horizon {horizon} bars · "
      f"each variant vs ITS OWN baseline (n=400, seed 7)")
    A("")
    A(f"{'variant':<15} {'n':>3}  {'MFE%':>7} {'base':>7} {'lift':>7}  "
      f"{'u1%':>6} {'base':>6} {'inv%':>6} {'base':>6} {'worstMAE':>9}")
    for r in rows:
        if r["n"] == 0:
            A(f"{r['variant']:<15} {0:>3}  {'—':>7} {'—':>7} {'—':>7}  "
              f"{'—':>6} {'—':>6} {'—':>6} {'—':>6} {'—':>9}   (no setups)")
            continue
        A(f"{r['variant']:<15} {r['n']:>3}  {r['mfe']:>+7.2f} {r['bmfe']:>+7.2f} "
          f"{r['lift']:>+7.2f}  {r['u1']:>6.1f} {r['bu1']:>6.1f} "
          f"{r['inv']:>6.1f} {r['binv']:>6.1f} {r['worst_mae']:>+9.2f}"
          + ("   *" if r["n"] < 8 else ""))
    A("")
    A("* n < 8: too few setups to read (median of <8 outcomes).")
    A("Credibility rule (pre-stated): lift >= +2.0pp MFE AND positive +1 ATR lift")
    A("AND n >= 8 AND a neighbouring variant (same parameter) also positive.")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Long-grid START sensitivity (research)")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--tf", choices=["1h", "5m"], default="1h")
    args = ap.parse_args(argv)
    print(run(args.csv, args.tf))
    return 0


if __name__ == "__main__":
    sys.exit(main())
