"""Performance metrics and report rendering."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .engine import Mechanics
from .signals import Params

REGIMES = ["TRENDING UP", "TRENDING DOWN", "RANGING", "ABNORMAL VOL"]


def max_drawdown_pct(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    peak = equity.cummax()
    dd = (equity - peak) / peak * 100.0
    return float(min(0.0, dd.min()))


def compute_metrics(trades: pd.DataFrame, equity: pd.Series, p: Params, mech: Mechanics) -> dict:
    m: dict = {}
    m["initial_capital"] = mech.initial_capital
    if trades.empty:
        m.update(
            trades=0, win_rate=0.0, profit_factor=0.0, net_pnl=0.0, max_dd_pct=0.0,
            avg_win=0.0, avg_loss=0.0, avg_rr_realized=0.0, exit_mix={}, regime_table=pd.DataFrame(),
            long_trades=0, short_trades=0,
        )
        return m

    net = trades["net"].to_numpy()
    wins = net > 0
    gross_profit = float(net[wins].sum())
    gross_loss = float(-net[~wins].sum())
    m["trades"] = int(len(trades))
    m["win_rate"] = 100.0 * wins.sum() / len(trades)
    m["profit_factor"] = (gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
    m["gross_profit"] = gross_profit
    m["gross_loss"] = gross_loss
    m["net_pnl"] = float(net.sum())
    m["max_dd_pct"] = max_drawdown_pct(equity)
    m["avg_win"] = float(net[wins].mean()) if wins.any() else 0.0
    m["avg_loss"] = float(net[~wins].mean()) if (~wins).any() else 0.0

    # realized reward/risk vs the planned risk (stop distance)
    risk_amt = np.where(trades["side"] == "LONG",
                        (trades["entry"] - trades["stop"]).to_numpy(),
                        (trades["stop"] - trades["entry"]).to_numpy()) * trades["qty"].to_numpy()
    m["avg_rr_realized"] = float(net.mean() / risk_amt.mean()) if risk_amt.mean() > 0 else 0.0
    m["planned_rr"] = p.tgt_atr / p.stop_atr

    m["exit_mix"] = trades["exit_reason"].value_counts().to_dict()
    m["long_trades"] = int((trades["side"] == "LONG").sum())
    m["short_trades"] = int((trades["side"] == "SHORT").sum())
    m["final_equity"] = float(equity.iloc[-1])

    rows = []
    for reg in REGIMES:
        sub = trades[trades["regime"] == reg]
        if sub.empty:
            rows.append({"regime": reg, "trades": 0, "win_rate": np.nan, "pf": np.nan, "net": 0.0})
            continue
        n_ = sub["net"].to_numpy()
        w = n_ > 0
        gp, gl = float(n_[w].sum()), float(-n_[~w].sum())
        rows.append(
            {
                "regime": reg,
                "trades": int(len(sub)),
                "win_rate": 100.0 * w.sum() / len(sub),
                "pf": (gp / gl) if gl > 0 else (float("inf") if gp > 0 else 0.0),
                "net": float(n_.sum()),
            }
        )
    m["regime_table"] = pd.DataFrame(rows)
    return m


def _pf_str(x) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    if x == float("inf"):
        return "∞"
    return f"{x:.2f}"


def render_report(m: dict, p: Params, mech: Mechanics, data_info: dict) -> str:
    L: list[str] = []
    bar = "═" * 64
    L.append(bar)
    L.append(" SIGNAL ENGINE BACKTEST — " + data_info.get("label", "OHLCV data"))
    L.append(bar)
    L.append(f" Data        : {data_info['bars']} bars @ {data_info['tf']}  ·  {data_info['start']} → {data_info['end']}  (UTC, bar-open)")
    L.append(f" Mode        : {p.mode} (threshold {p.threshold}/100) · TFs {p.tf_htf_s//60}m bias / {p.tf_mid_s//60}m momentum / {p.tf_base_s//60}m entry")
    L.append(f" Costs       : fee {mech.fee_pct:.2f}%/side · slippage {mech.slippage_pct:.3f}%/fill")
    L.append(f" Position    : {mech.qty_pct:.0f}% of equity · initial {mech.initial_capital:,.2f} USDT")
    L.append("")
    if m["trades"] == 0:
        L.append(" NO TRADES — the signal never reached the threshold / gates on this dataset.")
        L.append(" (Try REVERSAL mode, a lower threshold, or different data.)")
        L.append(bar)
        return "\n".join(L)

    L.append(" OVERALL (fees & slippage included)")
    L.append(f"   Trades            : {m['trades']}  ({m['long_trades']} long / {m['short_trades']} short)")
    L.append(f"   Win rate          : {m['win_rate']:.1f}%")
    L.append(f"   Profit factor     : {_pf_str(m['profit_factor'])}")
    L.append(f"   Net PnL (USDT)    : {m['net_pnl']:+,.2f}   (equity {m['initial_capital']:,.2f} → {m['final_equity']:,.2f})")
    L.append(f"   Max drawdown      : {m['max_dd_pct']:.2f}%")
    L.append(f"   Avg win / loss    : {m['avg_win']:+,.2f} / {m['avg_loss']:+,.2f}")
    L.append(f"   Avg reward/risk   : {m['avg_rr_realized']:.2f} realized  (planned {m['planned_rr']:.2f})")
    mix = " · ".join(f"{k} {v}" for k, v in sorted(m["exit_mix"].items()))
    L.append(f"   Exit mix          : {mix}")
    L.append("")
    L.append(" BY MARKET REGIME (regime at entry)")
    rt = m["regime_table"]
    L.append(f"   {'REGIME':<15} {'TRADES':>7} {'WIN%':>7} {'PF':>7} {'NET (USDT)':>12}")
    for _, r in rt.iterrows():
        wr = "—" if np.isnan(r["win_rate"]) else f"{r['win_rate']:.1f}"
        L.append(f"   {r['regime']:<15} {r['trades']:>7} {wr:>7} {_pf_str(r['pf']):>7} {r['net']:>+12,.2f}")
    L.append("")
    L.append(" NOTE: synthetic or short data → pipeline validation only, NOT a performance claim.")
    L.append(bar)
    return "\n".join(L)
