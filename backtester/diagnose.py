"""Signal-quality diagnosis — WHY did losing trades happen?

For every closed trade it measures:
  • MFE / MAE in R-multiples (max favorable / adverse excursion after entry)
  • a priority-ordered failure taxonomy:
      1 COST-DOMINATED   gross > 0 but net < 0 (costs ate a winning trade)
      2 NOISE STOP       stopped out with < 0.25R excursion within 12 bars
                         (entered with no development — often a false trigger)
      3 FAILED BREAKOUT  reached >= 0.75R in favor, then stopped out
                         (real move that reversed before target)
      4 PREMATURE REVERSAL  (REVERSAL mode) faded a trend that flipped back
      5 LOW-VOL CHOP     entry in RANGING regime with ATR% in the dataset's
                         bottom quartile (no edge environment)
      6 otherwise: bucketed by exit reason
  • cost sensitivity: net/PF at fee x slippage grid (sizing held constant)
  • entry ATR%-quartile, regime, and per-month performance tables

Usage:
  python -m backtester.diagnose --csv data/near_5m.csv --mode scalp \
      [--out trades.csv]   (re-runs the same backtest as the CLI defaults)
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from . import data as D
from .engine import Mechanics, run_backtest
from .report import _pf_str
from .signals import Params, compute_signals

R_SMALL = 0.25   # below this MFE: no development
R_CLOSE = 0.75   # at/above this MFE: "close miss" of target
NOISE_BARS = 12  # 3 hours of 5m bars


def _mfe_mae(df: pd.DataFrame, t: pd.Series) -> tuple[float, float]:
    """MFE/MAE (raw price units) between entry and exit, exclusive of entry bar."""
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    i0 = df.index.get_loc(t["entry_time"])
    i1 = df.index.get_loc(t["exit_time"])
    seg_h = h[i0 + 1: i1 + 1]
    seg_l = l[i0 + 1: i1 + 1]
    entry = t["entry"]
    if t["side"] == "LONG":
        mfe = max(0.0, float(seg_h.max() - entry)) if len(seg_h) else 0.0
        mae = max(0.0, float(entry - seg_l.min())) if len(seg_l) else 0.0
    else:
        mfe = max(0.0, float(entry - seg_l.min())) if len(seg_l) else 0.0
        mae = max(0.0, float(seg_h.max() - entry)) if len(seg_h) else 0.0
    return mfe, mae


def _raw_fill(df: pd.DataFrame, t: pd.Series) -> tuple[float, float]:
    """Recover pre-slippage fill prices (entry, exit) from data + trade row."""
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    i0 = df.index.get_loc(t["entry_time"])
    i1 = df.index.get_loc(t["exit_time"])
    entry_raw = c[i0]
    long = t["side"] == "LONG"
    if t["exit_reason"] == "STOP":
        stop = t["stop"]
        raw = o[i1] if (o[i1] < stop if long else o[i1] > stop) else stop
    elif t["exit_reason"] == "TARGET":
        tgt = t["target"]
        raw = o[i1] if (o[i1] > tgt if long else o[i1] < tgt) else tgt
    else:
        raw = c[i1]
    return float(entry_raw), float(raw)


def classify(trades: pd.DataFrame, df: pd.DataFrame, sig, p: Params) -> pd.DataFrame:
    out = []
    entry_atr_pct = []
    for _, t in trades.iterrows():
        mfe, mae = _mfe_mae(df, t)
        R = abs(t["target"] - t["entry"])
        mfe_r = mfe / R if R > 0 else 0.0
        mae_r = mae / R if R > 0 else 0.0
        i0 = df.index.get_loc(t["entry_time"])
        i1 = df.index.get_loc(t["exit_time"])
        entry_atr_pct.append(t["atr"] / df["close"].iloc[i0] * 100.0)

        if t["gross"] > 0 and t["net"] < 0:
            reason = "COST-DOMINATED"
        elif t["exit_reason"] == "STOP" and mfe_r < R_SMALL and t["bars_held"] <= NOISE_BARS:
            reason = "NOISE STOP"
        elif t["exit_reason"] == "STOP" and mfe_r >= R_CLOSE:
            reason = "FAILED BREAKOUT"
        elif p.mode == "REVERSAL" and t["exit_reason"] == "REVERSAL":
            trend_at_exit = float(sig.trend45.iloc[i1])
            if (t["side"] == "LONG" and trend_at_exit == 1) or (t["side"] == "SHORT" and trend_at_exit == -1):
                reason = "PREMATURE REVERSAL"
            else:
                reason = "REVERSAL EXIT (trend held)"
        else:
            reason = {"STOP": "STOP (developed)", "TARGET": "TARGET",
                      "REVERSAL": "REVERSAL EXIT", "TREND FLIP": "TREND FLIP"}.get(t["exit_reason"], t["exit_reason"])
        out.append({**t.to_dict(), "mfe_r": mfe_r, "mae_r": mae_r,
                    "entry_atr_pct": entry_atr_pct[-1], "fail_reason": reason})
    return pd.DataFrame(out)


def cost_sensitivity(trades: pd.DataFrame, df: pd.DataFrame) -> pd.DataFrame:
    """Net/PF at a fee x slippage grid. Sizing held constant (original qty)."""
    rows = []
    fee_grid = (0.02, 0.05, 0.10)
    slip_grid = (0.0, 0.02, 0.05)
    for fee in fee_grid:
        for slip in slip_grid:
            fee_d = fee / 100.0    # grid values are percents
            slip_d = slip / 100.0
            gp = gl = 0.0          # net-based PF (matches compute_metrics)
            net = 0.0
            wins = 0
            for _, t in trades.iterrows():
                e_raw, x_raw = _raw_fill(df, t)
                long = t["side"] == "LONG"
                e = e_raw * (1 + slip_d) if long else e_raw * (1 - slip_d)
                x = x_raw * (1 - slip_d) if long else x_raw * (1 + slip_d)
                g = (x - e) * t["qty"] if long else (e - x) * t["qty"]
                n = g - (e + x) * t["qty"] * fee_d
                net += n
                if n > 0:
                    gp += n
                    wins += 1
                else:
                    gl += -n
            pf = (gp / gl) if gl > 0 else (float("inf") if gp > 0 else 0.0)
            rows.append({"fee_%": fee, "slippage_%": slip, "net": round(net, 2),
                         "pf": pf, "win%": 100.0 * wins / len(trades) if len(trades) else 0.0})
    return pd.DataFrame(rows)


def diagnose(df: pd.DataFrame, trades: pd.DataFrame, sig, p: Params, mech: Mechanics) -> str:
    L: list[str] = []
    bar = "═" * 78
    L.append(bar)
    L.append(f" SIGNAL QUALITY DIAGNOSIS — {p.mode} ({len(trades)} trades)")
    L.append(bar)
    if trades.empty:
        L.append(" no trades to diagnose")
        return "\n".join(L)

    d = classify(trades, df, sig, p)
    losing = d[d["net"] < 0]
    tot_net = float(d["net"].sum())

    avg_cost_pct = float(((d["fees"] / (d["entry"] * d["qty"])).mean()) * 2 +
                         2 * (mech.slippage_pct / 100.0)) * 100.0 if len(d) else 0.0
    # (fees per side as %% of notional, both sides, plus slippage both fills, in bps-ish %)
    L.append(f" Avg round-trip cost (fees both sides + slippage both fills): ~{avg_cost_pct:.2f}% of position notional")
    L.append(f" Total net: {tot_net:+,.2f} · losing trades: {len(losing)} ({100.0*len(losing)/len(d):.1f}%) "
             f"· losing net: {float(losing['net'].sum()):+,.2f}")
    L.append("")

    order = ["COST-DOMINATED", "NOISE STOP", "FAILED BREAKOUT", "PREMATURE REVERSAL",
             "LOW-VOL CHOP", "REVERSAL EXIT (trend held)", "STOP (developed)",
             "REVERSAL EXIT", "TREND FLIP", "TARGET"]
    # low-vol chop is a post-hoc overlay on the residual stop buckets
    q25 = float(d["entry_atr_pct"].quantile(0.25))
    lowvol = (d["entry_atr_pct"] <= q25) & (d["regime"] == "RANGING")
    overlay = lowvol & (d["net"] < 0) & (d["fail_reason"].str.startswith("STOP"))
    d.loc[overlay, "fail_reason"] = "LOW-VOL CHOP"

    L.append(f" {'FAILURE TAXONOMY':72} ")
    L.append(f" {'bucket':<26}{'n':>5}{'%all':>7}{'%loss':>7}{'net':>12}{'avgMFE':>8}{'avgMAE':>8}{'avgBars':>8}")
    for bucket in order:
        sub = d[d["fail_reason"] == bucket]
        if sub.empty:
            continue
        L.append(f" {bucket:<26}{len(sub):>5}{100.0*len(sub)/len(d):>7.1f}"
                 f"{100.0*len(sub[sub['net']<0])/max(len(losing),1):>7.1f}"
                 f"{float(sub['net'].sum()):>+12,.2f}"
                 f"{float(sub['mfe_r'].mean()):>8.2f}{float(sub['mae_r'].mean()):>8.2f}"
                 f"{float(sub['bars_held'].mean()):>8.1f}")
    L.append("")
    L.append(" MFE/MAE in R (1R = full stop→target distance). NOISE STOP = never developed;")
    L.append(" FAILED BREAKOUT = reached >=0.75R then gave it back; LOW-VOL CHOP = RANGING entry")
    L.append(f" with ATR% in the bottom quartile (<= {q25:.3f}%).")
    L.append("")

    # entry ATR% quartiles
    d["atr_q"] = pd.qcut(d["entry_atr_pct"], 4, labels=["Q1(low)", "Q2", "Q3", "Q4(high)"])
    L.append(" ENTRY VOLATILITY (ATR% at entry, quartiles)")
    L.append(f" {'quartile':<12}{'n':>6}{'win%':>8}{'PF':>7}{'net':>13}")
    for q in ("Q1(low)", "Q2", "Q3", "Q4(high)"):
        sub = d[d["atr_q"] == q]
        if sub.empty:
            continue
        n_ = sub["net"].to_numpy()
        gp, gl = float(n_[n_ > 0].sum()), float(-n_[n_ <= 0].sum())
        L.append(f" {q:<12}{len(sub):>6}{100.0*(n_>0).mean():>8.1f}{_pf_str(gp/gl if gl>0 else float('inf') if gp>0 else 0.0):>7}{float(n_.sum()):>+13,.2f}")
    L.append("")

    # per month
    d["month"] = pd.to_datetime(d["entry_time"], utc=True).dt.tz_convert("UTC").dt.to_period("M").astype(str)
    L.append(" PER-MONTH (entry month)")
    L.append(f" {'month':<10}{'n':>6}{'win%':>8}{'PF':>7}{'net':>13}")
    for mo, sub in d.groupby("month"):
        n_ = sub["net"].to_numpy()
        gp, gl = float(n_[n_ > 0].sum()), float(-n_[n_ <= 0].sum())
        L.append(f" {str(mo):<10}{len(sub):>6}{100.0*(n_>0).mean():>8.1f}"
                 f"{_pf_str(gp/gl if gl>0 else float('inf') if gp>0 else 0.0):>7}{float(n_.sum()):>+13,.2f}")
    L.append("")

    # cost sensitivity
    cs = cost_sensitivity(trades, df)
    L.append(f" COST SENSITIVITY (sizing held constant; base = fee {mech.fee_pct}%/side + slip {mech.slippage_pct}%/fill)")
    L.append(f" {'fee%':>6}{'slip%':>7}   {'net':>13}{'PF':>7}{'win%':>8}")
    for _, r in cs.iterrows():
        L.append(f" {r['fee_%']:>6.2f}{r['slippage_%']:>7.2f}   {r['net']:>+13,.2f}{_pf_str(r['pf']):>7}{r['win%']:>8.1f}")
    L.append(bar)
    L.append(" NOTE: diagnosis on synthetic data = pipeline check only. Run on real data.")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    import sys
    ap = argparse.ArgumentParser(prog="backtester.diagnose", description="Loss-taxonomy diagnosis of a backtest")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--mode", choices=["scalp", "reversal"], default="scalp")
    ap.add_argument("--threshold", type=int, default=None)
    ap.add_argument("--stop-atr", type=float, default=1.2)
    ap.add_argument("--target-atr", type=float, default=1.8)
    ap.add_argument("--min-room-atr", type=float, default=2.0)
    ap.add_argument("--fee-pct", type=float, default=0.10)
    ap.add_argument("--slippage-pct", type=float, default=0.02)
    args = ap.parse_args(argv)

    df = D.load_csv(args.csv)
    p = Params(mode="SCALP" if args.mode == "scalp" else "REVERSAL",
               stop_atr=args.stop_atr, tgt_atr=args.target_atr, min_room_atr=args.min_room_atr)
    if args.threshold is not None:
        if args.mode == "scalp":
            p.scalp_thr = args.threshold
        else:
            p.rev_thr = args.threshold
    mech = Mechanics(fee_pct=args.fee_pct, slippage_pct=args.slippage_pct)
    sig = compute_signals(df, p)
    trades, _, _ = run_backtest(df, sig, p, mech)
    print(diagnose(df, trades, sig, p, mech))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
