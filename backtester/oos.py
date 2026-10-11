"""Out-of-sample protocol — optimise on TRAIN, validate once on TEST.

Method (single pass, no peeking):
  1. A small parameter grid (threshold × stop × target × room) is ranked on
     the TRAIN window only.
  2. The top N candidates (by train net, min-trades floor) are each
     evaluated ONCE on the TEST window.
  3. The test window is never used for selection — if you re-tune to these
     test numbers, the test stops being out-of-sample.

Signals are computed on the full dataset (no lookahead — HTF data is
confirmed only); trades are attributed to a window by entry time.

Usage:
  python -m backtester.oos --csv data/near_5m.csv --mode scalp \
      --train-end 2026-09-01 [--min-trades 30] [--top-n 5]
"""
from __future__ import annotations

import argparse
import sys
from itertools import product

import numpy as np
import pandas as pd

from . import data as D
from .engine import Mechanics, resolve_slippage, run_backtest
from .report import _pf_str
from .signals import Params, compute_signals

GRID = {
    "thresholds": (75, 80, 85),       # scalp; reversal uses 65/70/75
    "stops": (1.0, 1.2, 1.5),
    "targets": (1.5, 1.8, 2.4),
    "rooms": (1.5, 2.0, 3.0),
}
REV_THRESHOLDS = (65, 70, 75)


def _window_stats(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {"n": 0, "win": 0.0, "pf": 0.0, "net": 0.0, "dd": 0.0}
    n_ = trades["net"].to_numpy()
    gp, gl = float(n_[n_ > 0].sum()), float(-n_[n_ <= 0].sum())
    eq = 10_000.0 + np.cumsum(n_)
    peak = np.maximum.accumulate(eq)
    dd = float(((eq - peak) / peak).min() * 100.0)
    return {"n": int(len(n_)), "win": 100.0 * (n_ > 0).mean(),
            "pf": (gp / gl) if gl > 0 else (float("inf") if gp > 0 else 0.0),
            "net": float(n_.sum()), "dd": dd}


def _quarter_stats(trades: pd.DataFrame, n_parts: int = 4) -> list[dict]:
    """Split a window into n equal time chunks → per-chunk stats (consistency)."""
    if trades.empty:
        return []
    t0, t1 = trades["entry_time"].min(), trades["entry_time"].max()
    edges = pd.date_range(t0, t1, periods=n_parts + 1)
    out = []
    for i in range(n_parts):
        sub = trades[(trades["entry_time"] >= edges[i]) & (trades["entry_time"] < edges[i + 1])]
        s = _window_stats(sub)
        s["label"] = f"{edges[i].date()}→{edges[i+1].date()}"
        out.append(s)
    return out


def oos(df: pd.DataFrame, mode: str, train_end: pd.Timestamp,
        min_trades: int = 30, top_n: int = 5,
        fee_pct: float = 0.10, slip_pct: float = 0.02, costs_label: str = "") -> str:
    mech = Mechanics(fee_pct=fee_pct, slippage_pct=slip_pct)
    thr_grid = REV_THRESHOLDS if mode == "REVERSAL" else GRID["thresholds"]

    # precompute signals per (threshold, room) — the only signal-affecting params
    sig_cache: dict[tuple[int, float], object] = {}

    def get_sig(thr: int, room: float):
        key = (thr, room)
        if key not in sig_cache:
            p = Params(mode=mode, min_room_atr=room,
                       scalp_thr=thr if mode == "SCALP" else Params().scalp_thr,
                       rev_thr=thr if mode == "REVERSAL" else Params().rev_thr)
            sig_cache[key] = compute_signals(df, p)
        return sig_cache[key], key[0], key[1]

    rows = []
    for thr, stop, tgt, room in product(thr_grid, GRID["stops"], GRID["targets"], GRID["rooms"]):
        sig, _, _ = get_sig(thr, room)
        p = Params(mode=mode, stop_atr=stop, tgt_atr=tgt, min_room_atr=room,
                   scalp_thr=thr if mode == "SCALP" else Params().scalp_thr,
                   rev_thr=thr if mode == "REVERSAL" else Params().rev_thr)
        trades, _, _ = run_backtest(df, sig, p, mech)
        if trades.empty:
            continue
        tr = trades[trades["entry_time"] <= train_end]
        te = trades[trades["entry_time"] > train_end]
        rows.append((thr, stop, tgt, room, tr, te))

    if not rows:
        return " no trades in any grid cell — widen the grid or check the data"

    # rank on TRAIN only
    def rank_key(r):
        s = _window_stats(r[4])
        return (s["n"] >= min_trades, s["net"])

    ranked = sorted(rows, key=lambda r: (rank_key(r)[0], rank_key(r)[1]), reverse=True)
    eligible = [r for r in ranked if rank_key(r)[0]]
    top = (eligible or ranked[:1])[:top_n]

    L: list[str] = []
    bar = "═" * 96
    L.append(bar)
    L.append(f" OUT-OF-SAMPLE PROTOCOL — {mode} · train → {train_end.date()} · test {train_end.date()} → {df.index[-1].date()}")
    L.append(bar)
    L.append(f" Grid: {len(thr_grid)} thresholds × {len(GRID['stops'])} stops × {len(GRID['targets'])} targets × "
             f"{len(GRID['rooms'])} rooms = {len(thr_grid)*len(GRID['stops'])*len(GRID['targets'])*len(GRID['rooms'])} candidates · "
             f"min {min_trades} train trades · top {top_n} carried to test")
    L.append(f" Costs: fee {fee_pct}%/side · slippage {(costs_label or f'{slip_pct:.3f}%/fill')}"
             if costs_label else f" Costs: fee {fee_pct}%/side · slippage {slip_pct:.3f}%/fill")
    L.append("")
    L.append(f" {'#':>2} {'thr':>4} {'stop':>5} {'tgt':>5} {'room':>5} | {'TRAIN':^34} | {'TEST':^34}")
    L.append(f" {'':>2} {'':>4} {'':>5} {'':>5} {'':>5} | {'n':>5}{'win%':>7}{'PF':>7}{'net':>12} | {'n':>5}{'win%':>7}{'PF':>7}{'net':>12}")
    for i, (thr, stop, tgt, room, tr, te) in enumerate(top, 1):
        s, t = _window_stats(tr), _window_stats(te)
        L.append(f" {i:>2} {thr:>4} {stop:>5.1f} {tgt:>5.1f} {room:>5.1f} | "
                 f"{s['n']:>5}{s['win']:>7.1f}{_pf_str(s['pf']):>7}{s['net']:>+12,.2f} | "
                 f"{t['n']:>5}{t['win']:>7.1f}{_pf_str(t['pf']):>7}{t['net']:>+12,.2f}")
    L.append("")

    best = top[0]
    sb, tb = _window_stats(best[4]), _window_stats(best[5])
    L.append(f" BEST (by train net): thr {best[0]} · stop {best[1]} · tgt {best[2]} · room {best[3]}")
    gates = [
        ("train net > 0", sb["net"] > 0, f"{sb['net']:+,.2f}"),
        ("test net > 0", tb["net"] > 0, f"{tb['net']:+,.2f}"),
        ("train PF > 1.2", sb["pf"] > 1.2, _pf_str(sb["pf"])),
        ("test PF > 1.2", tb["pf"] > 1.2, _pf_str(tb["pf"])),
        ("train DD > -15%", sb["dd"] > -15.0, f"{sb['dd']:.1f}%"),
        ("test DD > -15%", tb["dd"] > -15.0, f"{tb['dd']:.1f}%"),
    ]
    L.append("")
    L.append(" ACCEPTANCE GATES (best candidate)")
    for name, ok, val in gates:
        L.append(f"   [{'PASS' if ok else 'FAIL'}] {name:<18} {val}")

    q = _quarter_stats(best[5])
    if q:
        L.append("")
        L.append(" TEST-WINDOW CONSISTENCY (4 equal time chunks of the test window)")
        L.append(f"   {'chunk':<24}{'n':>5}{'win%':>7}{'PF':>7}{'net':>13}")
        for s in q:
            L.append(f"   {s['label']:<24}{s['n']:>5}{s['win']:>7.1f}{_pf_str(s['pf']):>7}{s['net']:>+13,.2f}")
        stable = all(s["net"] > -abs(sb["net"]) * 0.5 or s["n"] < 10 for s in q)
        L.append(f"   consistency: {'no chunk collapses relative to train' if stable else 'at least one chunk collapses — treat with suspicion'}")
    L.append("")
    L.append(" ⚠ The test window was evaluated ONCE for these candidates. Do not re-tune to")
    L.append("   these numbers — the moment you do, slice a NEW holdout and repeat this protocol.")
    L.append(bar)
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="backtester.oos", description="Single-pass out-of-sample validation")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--mode", choices=["scalp", "reversal"], default="scalp")
    ap.add_argument("--train-end", required=True, help="YYYY-MM-DD — train on bars up to this date, test after")
    ap.add_argument("--min-trades", type=int, default=30, help="Minimum train trades to be eligible (default 30)")
    ap.add_argument("--top-n", type=int, default=5)
    ap.add_argument("--fee-pct", type=float, default=0.10)
    ap.add_argument("--slippage-ticks", type=int, default=2,
                    help="Slippage in MINTICKS per fill (matches the Pine strategy default)")
    ap.add_argument("--tick", type=float, default=None, help="Symbol mintick (default: auto from CSV)")
    ap.add_argument("--slippage-pct", type=float, default=None, help="Explicit %% (overrides ticks)")
    args = ap.parse_args(argv)

    df = D.load_csv(args.csv)
    train_end = pd.Timestamp(args.train_end, tz="UTC")
    if not (df.index[0] < train_end < df.index[-1]):
        print(f"error: --train-end {args.train_end} must lie inside {df.index[0].date()} → {df.index[-1].date()}",
              file=sys.stderr)
        return 2
    slip_pct, slip_label = resolve_slippage(df, args.slippage_pct, args.slippage_ticks, args.tick)
    print(oos(df, "SCALP" if args.mode == "scalp" else "REVERSAL", train_end,
              args.min_trades, args.top_n, args.fee_pct, slip_pct, costs_label=slip_label))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
