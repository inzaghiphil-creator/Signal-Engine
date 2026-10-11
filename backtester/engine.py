"""Trade engine — mirrors the Pine strategy exactly.

Execution convention (shared by Pine strategy, indicator display and here):
  • Entry at the CLOSE of the signal bar; slippage applied to ALL fills
    (entries and exits, adverse direction) — matching the Pine strategy
    tester, which applies slippage to every execution.
  • Stop = entry ∓ stop_atr × ATR(signal bar); target = entry ± tgt_atr × ATR.
  • Per-bar management order: STOP → TARGET → REVERSAL → TREND FLIP → entry.
    STOP is checked before TARGET on the same bar (conservative tie-break).
  • Gaps: if the bar opens beyond the stop/target, fill at the open
    (then slippage on that fill).
  • A new position's first exit check happens on the bar AFTER entry
    (matches the strategy's exit order becoming active the next bar).
  • Fees: fee_pct per side on notional; position = qty_pct of current equity.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .signals import Params, Signals


@dataclass
class Mechanics:
    initial_capital: float = 10000.0
    qty_pct: float = 10.0        # % of equity per position
    fee_pct: float = 0.10        # per side, percent of notional (KuCoin taker)
    slippage_pct: float = 0.02   # percent of price per fill (≈2 ticks @0.0001)


def run_backtest(base: pd.DataFrame, sig: Signals, p: Params, mech: Mechanics) -> tuple[pd.DataFrame, pd.Series]:
    """Returns (trades DataFrame, equity curve indexed by trade close time)."""
    o = base["open"].to_numpy()
    h = base["high"].to_numpy()
    l = base["low"].to_numpy()
    c = base["close"].to_numpy()
    atr_v = sig.atr.to_numpy()
    long_sig = sig.long_sig.to_numpy()
    short_sig = sig.short_sig.to_numpy()
    trend45 = sig.trend45.to_numpy()
    regime = sig.regime.to_numpy()
    regime_label = sig.regime_label.to_numpy()
    score_l = sig.score_long.to_numpy()
    score_s = sig.score_short.to_numpy()
    score_rl = sig.rev_score_long.to_numpy()
    score_rs = sig.rev_score_short.to_numpy()
    idx = base.index

    n = len(base)
    pos = 0
    entry_px = stop = tgt = qty = 0.0
    entry_i = -1
    entry_score = 0.0
    equity = mech.initial_capital
    slip = mech.slippage_pct / 100.0
    fee = mech.fee_pct / 100.0

    trades: list[dict] = []
    equity_points: list[tuple[pd.Timestamp, float]] = [(idx[0], equity)]

    def slip_fill(px: float) -> float:
        """Adverse-direction slippage on any fill (long exits lower, short exits higher)."""
        return px * (1.0 - slip) if pos == 1 else px * (1.0 + slip)

    def close_trade(i: int, reason: str, px_raw: float) -> None:
        nonlocal equity, pos
        px = slip_fill(px_raw)
        if pos == 1:
            gross = (px - entry_px) * qty
        else:
            gross = (entry_px - px) * qty
        fees = (entry_px + px) * qty * fee
        net = gross - fees
        equity += net
        trades.append(
            {
                "entry_time": idx[entry_i],
                "exit_time": idx[i],
                "side": "LONG" if pos == 1 else "SHORT",
                "entry": round(entry_px, 8),
                "exit": round(px, 8),
                "stop": round(stop, 8),
                "target": round(tgt, 8),
                "atr": round(float(atr_v[entry_i]), 8),
                "score": round(float(entry_score), 1),
                "regime": regime_label[entry_i],
                "exit_reason": reason,
                "qty": round(qty, 6),
                "gross": round(gross, 4),
                "fees": round(fees, 4),
                "net": round(net, 4),
                "bars_held": i - entry_i,
            }
        )
        equity_points.append((idx[i], equity))
        pos = 0

    for i in range(n):
        # 1) manage open position
        if pos == 1:
            if np.isfinite(stop) and l[i] <= stop:
                close_trade(i, "STOP", o[i] if o[i] < stop else stop)
            elif np.isfinite(tgt) and h[i] >= tgt:
                close_trade(i, "TARGET", o[i] if o[i] > tgt else tgt)
            elif short_sig[i]:
                close_trade(i, "REVERSAL", c[i])
            elif p.trend_exit and p.is_scalp and trend45[i] == -1:
                # SCALP only — a reversal long enters on a bearish HTF trend,
                # so a trend-flip exit would be self-contradictory there.
                close_trade(i, "TREND FLIP", c[i])
        elif pos == -1:
            if np.isfinite(stop) and h[i] >= stop:
                close_trade(i, "STOP", o[i] if o[i] > stop else stop)
            elif np.isfinite(tgt) and l[i] <= tgt:
                close_trade(i, "TARGET", o[i] if o[i] < tgt else tgt)
            elif long_sig[i]:
                close_trade(i, "REVERSAL", c[i])
            elif p.trend_exit and p.is_scalp and trend45[i] == 1:
                close_trade(i, "TREND FLIP", c[i])
        # 2) open new position (entry at signal-bar close ± slippage)
        if pos == 0 and np.isfinite(atr_v[i]):
            if long_sig[i]:
                entry_px = c[i] * (1 + slip)
                stop = c[i] - p.stop_atr * atr_v[i]
                tgt = c[i] + p.tgt_atr * atr_v[i]
                qty = (equity * mech.qty_pct / 100.0) / entry_px
                entry_i = i
                entry_score = score_l[i] if p.is_scalp else score_rl[i]
                pos = 1
            elif short_sig[i]:
                entry_px = c[i] * (1 - slip)
                stop = c[i] + p.stop_atr * atr_v[i]
                tgt = c[i] - p.tgt_atr * atr_v[i]
                qty = (equity * mech.qty_pct / 100.0) / entry_px
                entry_i = i
                entry_score = score_s[i] if p.is_scalp else score_rs[i]
                pos = -1

    # an open position at the end of data is reported separately and excluded
    # from closed-trade stats (same as the Pine strategy tester's "open" position)
    open_pos = None
    if pos != 0:
        open_pos = {
            "side": "LONG" if pos == 1 else "SHORT",
            "entry_time": idx[entry_i],
            "entry": round(entry_px, 8),
            "stop": round(stop, 8),
            "target": round(tgt, 8),
            "last_close": round(float(c[-1]), 8),
        }
    trades_df = pd.DataFrame(trades)
    eq = pd.Series([v for _, v in equity_points], index=pd.DatetimeIndex([t for t, _ in equity_points]), name="equity")
    return trades_df, eq, open_pos
