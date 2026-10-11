"""CLI: python -m backtester --csv data/near_5m.csv --mode scalp ...

Accepts exported OHLCV CSV (TradingView or KuCoin format). See README.md.
"""
from __future__ import annotations

import argparse
import sys

from . import __version__
from . import data as D
from .engine import Mechanics, run_backtest
from .report import compute_metrics, render_report
from .signals import Params, compute_signals


def _str2bool(v: str) -> bool:
    return v.lower() in ("1", "true", "yes", "on")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="backtester", description="Signal Engine Python backtester (Pine-equivalent logic)")
    ap.add_argument("--csv", required=True, help="Path to exported OHLCV CSV (base/entry timeframe)")
    ap.add_argument("--timeframe", default=None, help="Entry TF of the CSV, e.g. 5m (default: auto-detect)")
    ap.add_argument("--mid-tf", default="15m", help="Momentum TF (default 15m)")
    ap.add_argument("--htf-tf", default="45m", help="Trend/bias TF (default 45m)")
    ap.add_argument("--label", default=None, help="Dataset label for the report (default: file name)")

    g = ap.add_argument_group("mode & scoring")
    g.add_argument("--mode", choices=["scalp", "reversal"], default="scalp")
    g.add_argument("--threshold", type=int, default=None, help="Override min score (scalp default 80, reversal 70)")

    g = ap.add_argument_group("risk & filters")
    g.add_argument("--stop-atr", type=float, default=1.2)
    g.add_argument("--target-atr", type=float, default=1.8)
    g.add_argument("--min-room-atr", type=float, default=2.0)
    g.add_argument("--piv-age-max", type=int, default=120)
    g.add_argument("--piv-fresh", type=int, default=15)
    g.add_argument("--no-room-filter", action="store_true", help="Disable the R/R room filter")
    g.add_argument("--no-trend-exit", action="store_true", help="Disable HTF trend-flip exits")
    g.add_argument("--no-strict-trend", action="store_true", help="SCALP: allow neutral HTF alignment")
    g.add_argument("--vwap-gate", action="store_true", help="Require session VWAP alignment")
    g.add_argument("--no-block-abnormal", action="store_true", help="Allow entries in ABNORMAL VOL regime")

    g = ap.add_argument_group("strategy mechanics")
    g.add_argument("--fee-pct", type=float, default=0.10, help="Commission %% per side (default 0.10 = KuCoin taker)")
    g.add_argument("--slippage-pct", type=float, default=0.02, help="Slippage %% per fill (default 0.02 ≈ 2 ticks @ 0.0001)")
    g.add_argument("--initial-capital", type=float, default=10000.0)
    g.add_argument("--qty-pct", type=float, default=10.0, help="Position size %% of equity (default 10)")

    g = ap.add_argument_group("output")
    g.add_argument("--out-trades", default=None, help="Write trades to CSV at this path")
    ap.add_argument("--version", action="version", version=f"backtester {__version__}")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    df = D.load_csv(args.csv)
    tf_base = D.parse_tf(args.timeframe) if args.timeframe else D.detect_tf_seconds(df)
    tf_mid = D.parse_tf(args.mid_tf)
    tf_htf = D.parse_tf(args.htf_tf)
    if tf_mid % tf_base != 0 or tf_htf % tf_base != 0:
        print("error: mid/htf timeframes must be multiples of the entry timeframe", file=sys.stderr)
        return 2
    if len(df) < 400:
        print(f"warning: only {len(df)} bars — indicators need warmup; results will be thin", file=sys.stderr)

    p = Params(
        mode=args.mode.upper(),
        tf_base_s=tf_base,
        tf_mid_s=tf_mid,
        tf_htf_s=tf_htf,
        stop_atr=args.stop_atr,
        tgt_atr=args.target_atr,
        min_room_atr=args.min_room_atr,
        piv_age_max=args.piv_age_max,
        piv_fresh=args.piv_fresh,
        require_room=not args.no_room_filter,
        trend_exit=not args.no_trend_exit,
        strict_trend=not args.no_strict_trend,
        vwap_gate=args.vwap_gate,
        block_abnormal=not args.no_block_abnormal,
    )
    if args.threshold is not None:
        if p.is_scalp:
            p.scalp_thr = args.threshold
        else:
            p.rev_thr = args.threshold

    mech = Mechanics(
        initial_capital=args.initial_capital,
        qty_pct=args.qty_pct,
        fee_pct=args.fee_pct,
        slippage_pct=args.slippage_pct,
    )

    sig = compute_signals(df, p)
    trades, equity = run_backtest(df, sig, p, mech)
    m = compute_metrics(trades, equity, p, mech)

    data_info = {
        "label": args.label or args.csv,
        "bars": len(df),
        "tf": f"{tf_base // 60}m" if tf_base % 60 == 0 else f"{tf_base}s",
        "start": df.index[0].strftime("%Y-%m-%d %H:%M"),
        "end": df.index[-1].strftime("%Y-%m-%d %H:%M"),
    }
    print(render_report(m, p, mech, data_info))

    if args.out_trades and not trades.empty:
        trades.to_csv(args.out_trades, index=False)
        print(f"\ntrades written to {args.out_trades}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
