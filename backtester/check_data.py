"""Data quality gate — run this BEFORE any backtest on real data.

Checks:
  • expected bar grid vs actual (missing/duplicate bars for the detected TF)
  • OHLC sanity (high >= max(open,close), low <= min(open,close), high >= low)
  • non-positive/NaN prices or volume
  • window stats (e.g. verify the crash window is present)

Usage:
  python -m backtester.check_data --csv data/near_5m.csv \
      [--tf 5m] [--window 2026-10-08,2026-10-10] [--max-gap-pct 2.0]

Exit code 1 if the data fails a hard gate (gaps > max-gap-pct, NaN prices,
OHLC violations) — do not backtest on failing data.
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

from . import data as D


def audit(df: pd.DataFrame, tf_s: int | None = None) -> dict:
    tf_s = tf_s or D.detect_tf_seconds(df)
    idx = df.index
    n = len(df)
    start, end = idx[0], idx[-1]

    expected = pd.date_range(start, end, freq=f"{tf_s}s")
    missing = expected.difference(idx)
    duplicates = idx[idx.duplicated()]

    o, h, l, c, v = (df[k].to_numpy() for k in ("open", "high", "low", "close", "volume"))
    ohlc_bad = int(((h < np.maximum(o, c) - 1e-12) | (l > np.minimum(o, c) + 1e-12) | (h < l - 1e-12)).sum())
    nan_price = int((np.isnan(o) | np.isnan(h) | np.isnan(l) | np.isnan(c)).sum())
    bad_vol = int((v <= 0).sum())

    return {
        "bars": n,
        "tf_s": tf_s,
        "start": start,
        "end": end,
        "expected": len(expected),
        "missing": int(len(missing)),
        "missing_pct": 100.0 * len(missing) / len(expected) if len(expected) else 0.0,
        "duplicates": int(len(duplicates)),
        "ohlc_violations": ohlc_bad,
        "nan_prices": nan_price,
        "nonpositive_volume": bad_vol,
        "missing_first": missing[:5].tolist() if len(missing) else [],
        "duplicates_first": duplicates[:5].tolist() if len(duplicates) else [],
    }


def window_stats(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> dict | None:
    sub = df.loc[(df.index >= start) & (df.index <= end)]
    if sub.empty:
        return None
    ret = sub["close"].pct_change().dropna()
    total = float(sub["close"].iloc[-1] / sub["close"].iloc[0] - 1.0)
    return {
        "bars": len(sub),
        "open": float(sub["open"].iloc[0]),
        "close": float(sub["close"].iloc[-1]),
        "low": float(sub["low"].min()),
        "high": float(sub["high"].max()),
        "total_ret_pct": 100.0 * total,
        "max_5m_drop_pct": 100.0 * float(ret.min()),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="backtester.check_data", description="Data quality gate for backtest input")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--tf", default=None, help="Override TF auto-detection (e.g. 5m)")
    ap.add_argument("--window", default=None, help="Comma-separated start,end (YYYY-MM-DD) to report window stats")
    ap.add_argument("--max-gap-pct", type=float, default=2.0, help="Fail if missing bars exceed this %% (default 2.0)")
    args = ap.parse_args(argv)

    df = D.load_csv(args.csv)
    tf_s = D.parse_tf(args.tf) if args.tf else None
    a = audit(df, tf_s)

    tf_label = f"{a['tf_s'] // 60}m" if a["tf_s"] % 60 == 0 else f"{a['tf_s']}s"
    print("═" * 64)
    print(" DATA QUALITY GATE — " + args.csv)
    print("═" * 64)
    print(f" Bars            : {a['bars']:,}  (expected {a['expected']:,} on a full {tf_label} grid)")
    print(f" Span            : {a['start']} → {a['end']} (UTC, bar-open)")
    print(f" Missing bars    : {a['missing']:,}  ({a['missing_pct']:.2f}%)   duplicates: {a['duplicates']}")
    if a["missing_first"]:
        print(f"   first missing   : {a['missing_first']}")
    if a["duplicates_first"]:
        print(f"   first duplicates: {a['duplicates_first']}")
    print(f" OHLC violations : {a['ohlc_violations']}")
    print(f" NaN prices      : {a['nan_prices']}")
    print(f" Non-positive vol: {a['nonpositive_volume']}")
    print("")

    if args.window:
        try:
            ws, we = [pd.Timestamp(x) for x in args.window.split(",")]
            ws = ws if ws.tz is not None else ws.tz_localize("UTC")
            we = (we if we.tz is not None else we.tz_localize("UTC")).replace(hour=23, minute=59, second=59)
            w = window_stats(df, ws, we)
            if w is None:
                print(f" WINDOW {ws.date()}→{we.date()}: NOT PRESENT in this file!")
            else:
                print(f" WINDOW {ws.date()}→{we.date()}: {w['bars']:,} bars · open {w['open']:.4f} → close {w['close']:.4f} "
                      f"(total {w['total_ret_pct']:+.1f}%) · low {w['low']:.4f} · high {w['high']:.4f} · worst 5m bar {w['max_5m_drop_pct']:+.2f}%")
            print("")
        except ValueError as e:
            print(f" bad --window format: {e}", file=sys.stderr)
            return 2

    problems = []
    if a["missing_pct"] > args.max_gap_pct:
        problems.append(f"missing bars {a['missing_pct']:.2f}% > {args.max_gap_pct}%")
    if a["nan_prices"]:
        problems.append(f"{a['nan_prices']} NaN prices")
    if a["ohlc_violations"]:
        problems.append(f"{a['ohlc_violations']} OHLC violations")
    if a["duplicates"]:
        problems.append(f"{a['duplicates']} duplicate bars")
    if a["bars"] < 400:
        problems.append(f"only {a['bars']} bars (< 400, indicators need warmup)")

    if problems:
        print(" RESULT: FAIL — " + "; ".join(problems))
        print(" Fix the export (see data/README.md) before backtesting.")
        return 1
    print(" RESULT: PASS — data is clean enough to backtest.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
