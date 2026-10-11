"""TradingView ↔ Python trade comparison.

You:  1) run the Python backtester on your exported CSV:
          python -m backtester --csv data/near_5m.csv --mode scalp --out-trades py_trades.csv
       2) on TradingView, load the SAME CSV (Data window → import or chart the
          same symbol/range), run the strategy with identical settings, then
          Strategy Tester → "List of Trades" → ⋯ → Export to CSV.
       3) run this tool on both files.

It aligns trades by bar time (tolerance configurable), checks side, entry
price (within slippage + ticks), and — when the TV export carries close
times / P&L — exit alignment and per-trade PnL.

Usage:
  python -m backtester.compare --py-trades py_trades.csv --tv-trades tv_trades.csv \
      [--tol-bars 1] [--price-tol-pct 0.05] [--tv-tz UTC]
"""
from __future__ import annotations

import argparse
import re
import sys

import numpy as np
import pandas as pd

from . import data as D


def _pick(cols: list[str], *patterns: str, exclude: tuple[str, ...] = ()) -> str | None:
    for pat in patterns:
        for c in cols:
            if c in exclude:
                continue
            if re.search(pat, c, re.I):
                return c
    return None


def load_tv_trades(path: str, tf_s: int, tz: str,
                   ov: dict[str, str | None] | None = None) -> pd.DataFrame:
    ov = ov or {}
    raw = pd.read_csv(path)
    cols = list(raw.columns)
    time_col = ov.get("time") or _pick(cols, r"date.*open", r"entry.*date", r"open.*date", r"^time$", r"date")
    close_col = ov.get("close") or _pick(cols, r"closed.*date", r"close.*date", r"exit.*date", r"close.*time",
                                         exclude=(time_col,) if time_col else ())
    side_col = ov.get("side") or _pick(cols, r"^type$", r"^side$", r"direction")
    price_col = ov.get("price") or _pick(cols, r"^price$", r"entry.*price", r"price", exclude=(close_col,) if close_col else ())
    pnl_col = ov.get("pnl") or _pick(cols, r"p&l", r"pnl", r"profit", r"realized", r"net.*p")
    qty_col = ov.get("qty") or _pick(cols, r"contracts", r"^qty$", r"volume", r"size")

    missing = [n for n, c in (("time", time_col), ("side", side_col), ("price", price_col)) if c is None]
    if missing:
        raise ValueError(
            f"could not identify required columns {missing} in the TV export.\n"
            f"  columns found: {cols}\n"
            "  Re-run with explicit overrides: --tv-time-col/--tv-side-col/--tv-price-col "
            "(and optionally --tv-close-col/--tv-pnl-col/--tv-qty-col)."
        )

    is_utc = (tz or "UTC").upper() in ("UTC", "UT")

    def _ts(s: pd.Series) -> pd.Series:
        x = pd.to_datetime(s, format="mixed", errors="coerce")
        if x.isna().all():
            x = pd.to_datetime(s.astype(str).str.strip(), format="mixed", errors="coerce")
        if is_utc:
            return x.dt.tz_localize("UTC", ambiguous="NaT", nonexistent="shift_forward") if x.dt.tz is None else x.dt.tz_convert("UTC")
        return x.dt.tz_localize(tz, ambiguous="NaT", nonexistent="shift_forward").dt.tz_convert("UTC")

    tv = pd.DataFrame({
        "entry_time": _ts(raw[time_col]),
        "exit_time": _ts(raw[close_col]) if close_col else pd.NaT,
        "side_raw": raw[side_col].astype(str),
        "entry": pd.to_numeric(raw[price_col], errors="coerce"),
        "pnl": pd.to_numeric(raw[pnl_col], errors="coerce") if pnl_col else np.nan,
        "qty": pd.to_numeric(raw[qty_col], errors="coerce") if qty_col else np.nan,
    })
    tv = tv.dropna(subset=["entry_time", "entry"]).reset_index(drop=True)
    tv["side"] = np.where(tv["side_raw"].str.lower().str.contains("buy|long"), "LONG",
                     np.where(tv["side_raw"].str.lower().str.contains("sell|short"), "SHORT", tv["side_raw"]))
    return tv


def compare(py: pd.DataFrame, tv: pd.DataFrame, tf_s: int, tol_bars: int, price_tol_pct: float) -> str:
    bar = pd.Timedelta(seconds=tf_s)
    L: list[str] = []
    hdr = "═" * 78
    L.append(hdr)
    L.append(" TRADINGVIEW ↔ PYTHON TRADE COMPARISON")
    L.append(hdr)
    L.append(f" Python trades: {len(py)} · TV trades: {len(tv)} · bar {tf_s//60}m · time tol ±{tol_bars} bar(s)")
    L.append("")

    py_e = py.sort_values("entry_time").reset_index(drop=True)
    tv_e = tv.sort_values("entry_time").reset_index(drop=True)
    tol = pd.Timedelta(seconds=tf_s * tol_bars)

    # greedy time-order matching via searchsorted (O(n log m))
    t_py = py_e["entry_time"].to_numpy(dtype="datetime64[ns]")
    t_tv = tv_e["entry_time"].to_numpy(dtype="datetime64[ns]")
    tol_ns = tf_s * tol_bars * 10**9
    taken = np.zeros(len(t_tv), dtype=bool)
    matched = []
    for i in range(len(t_py)):
        lo = int(np.searchsorted(t_tv, t_py[i] - tol_ns, side="left"))
        hi = int(np.searchsorted(t_tv, t_py[i] + tol_ns, side="right"))
        cands = [jj for jj in range(lo, hi) if not taken[jj]]
        if not cands:
            continue
        best = min(cands, key=lambda jj: abs(int(t_tv[jj]) - int(t_py[i])))
        taken[best] = True
        matched.append((i, best))
    unmatched_py = [i for i in range(len(t_py)) if i not in {m[0] for m in matched}]
    unmatched_tv = [j for j in range(len(t_tv)) if not taken[j]]

    n_py, n_tv = len(py_e), len(tv_e)
    L.append(f" ENTRY MATCH: {len(matched)}/{min(n_py, n_tv)} within ±{tol_bars} bar(s)")
    side_bad, price_bad = 0, 0
    deltas = []
    detail = []
    for i, j in matched:
        a, b = py_e.iloc[i], tv_e.iloc[j]
        ds = a["side"] != b["side"]
        d_price = abs(b["entry"] - a["entry"]) / a["entry"] * 100.0 if a["entry"] else 9.9
        dp = d_price > price_tol_pct
        if ds:
            side_bad += 1
        if dp:
            price_bad += 1
        deltas.append((b["entry"] - a["entry"]) / a["entry"] * 100.0)
        if ds or dp:
            detail.append(f"   py[{i}] {a['entry_time']} {a['side']} {a['entry']}  ↔  tv[{j}] {b['entry_time']} "
                          f"{b['side']} {b['entry']}  (Δ {100*(b['entry']-a['entry'])/a['entry']:+.3f}%)")
    L.append(f"   side mismatches: {side_bad} · price deltas > {price_tol_pct}%: {price_bad}")
    if deltas:
        L.append(f"   entry price Δ (TV−PY): mean {np.mean(deltas):+.4f}% · max {abs(np.max(deltas)):.4f}% · min {np.min(deltas):+.4f}%")
    if detail:
        L.append("   discrepancies (first 15):")
        L.extend(detail[:15])
    L.append("")

    if unmatched_py:
        L.append(f" Python entries with no TV match: {len(unmatched_py)}")
        L.extend(f"   {py_e['entry_time'].iloc[i]} {py_e['side'].iloc[i]} {py_e['entry'].iloc[i]}" for i in unmatched_py[:10])
    if unmatched_tv:
        L.append(f" TV entries with no Python match: {len(unmatched_tv)}")
        L.extend(f"   {tv_e['entry_time'].iloc[j]} {tv_e['side'].iloc[j]} {tv_e['entry'].iloc[j]}" for j in unmatched_tv[:10])
    L.append("")

    # exits (when the TV export carries close times)
    if tv["exit_time"].notna().any():
        ex_matched, ex_bad = 0, 0
        for i, j in matched:
            a, b = py_e.iloc[i], tv_e.iloc[j]
            if pd.isna(b["exit_time"]):
                continue
            ex_matched += 1
            if abs(b["exit_time"] - a["exit_time"]) > tol:
                ex_bad += 1
        L.append(f" EXIT TIME MATCH: {ex_matched - ex_bad}/{ex_matched} within ±{tol_bars} bar(s)")
        L.append("")

    # PnL (when the TV export carries per-trade PnL)
    if tv["pnl"].notna().any():
        diffs = []
        for i, j in matched:
            a, b = py_e.iloc[i], tv_e.iloc[j]
            if pd.isna(b["pnl"]):
                continue
            diffs.append(b["pnl"] - a["net"])
        if diffs:
            L.append(f" PER-TRADE PnL Δ (TV−PY): mean {np.mean(diffs):+.3f} · max |Δ| {max(abs(x) for x in diffs):.3f} USDT")
            L.append("   (expect small deltas: TV commissions/slippage are applied per its own fill model)")
    L.append("")

    ok = (len(unmatched_py) == 0 and len(unmatched_tv) == 0 and side_bad == 0
          and len(matched) >= max(n_py, n_tv, 1) * 0.99)
    L.append(f" VERDICT: {'MATCH — Pine and Python agree on this data (within tolerance)' if ok else 'DISCREPANCIES — investigate the items above before trusting either implementation'}")
    L.append(hdr)
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="backtester.compare", description="Compare TradingView strategy trades vs Python backtester trades")
    ap.add_argument("--py-trades", required=True, help="Python trades CSV (from --out-trades)")
    ap.add_argument("--tv-trades", required=True, help="TradingView 'List of Trades' export CSV")
    ap.add_argument("--csv", default=None, help="The market-data CSV (used for TF detection; optional)")
    ap.add_argument("--tf", default="5m", help="Entry timeframe (default 5m)")
    ap.add_argument("--tol-bars", type=int, default=1, help="Entry-time alignment tolerance in bars (default 1)")
    ap.add_argument("--price-tol-pct", type=float, default=0.05, help="Max |Δentry price| in %% (default 0.05 ≈ slippage + spread)")
    ap.add_argument("--tv-tz", default="UTC", help="Timezone of the TV export (default UTC)")
    ap.add_argument("--tv-time-col", default=None)
    ap.add_argument("--tv-side-col", default=None)
    ap.add_argument("--tv-price-col", default=None)
    ap.add_argument("--tv-close-col", default=None)
    ap.add_argument("--tv-pnl-col", default=None)
    ap.add_argument("--tv-qty-col", default=None)
    args = ap.parse_args(argv)

    tf_s = D.parse_tf(args.tf)
    py = pd.read_csv(args.py_trades)
    py["entry_time"] = pd.to_datetime(py["entry_time"], utc=True)
    if "exit_time" in py.columns:
        py["exit_time"] = pd.to_datetime(py["exit_time"], utc=True)
    try:
        tv = load_tv_trades(args.tv_trades, tf_s, args.tv_tz,
                            {"time": args.tv_time_col, "side": args.tv_side_col, "price": args.tv_price_col,
                             "close": args.tv_close_col, "pnl": args.tv_pnl_col, "qty": args.tv_qty_col})
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if "entry_time" not in py or "side" not in py or "entry" not in py:
        print("error: --py-trades must be a --out-trades file (columns entry_time, side, entry, ...)", file=sys.stderr)
        return 2
    print(compare(py, tv, tf_s, args.tol_bars, args.price_tol_pct))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
