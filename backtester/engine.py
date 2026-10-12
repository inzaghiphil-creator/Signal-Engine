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

from . import data as D

from .signals import Params, Signals


@dataclass
class Mechanics:
    initial_capital: float = 10000.0
    qty_pct: float = 10.0        # % of equity per position
    fee_pct: float = 0.10        # per side, percent of notional (KuCoin taker)
    slippage_pct: float = 0.02   # legacy fallback; prefer resolve_slippage()
    confirm_bars: int = 0        # 0 = baseline (immediate fill at signal close)
                                 # >0 = confirmation-entry experiment: wait up to
                                 # N completed bars for a confirming close before
                                 # entering (see run_backtest pending logic)


def resolve_slippage(df, slippage_pct: float | None, slippage_ticks: int = 2,
                     tick: float | None = None) -> tuple[float, str]:
    """Slippage as %/fill, matching the Pine strategy's tick-based default.

    The TV strategy applies `slippage = inSlipTicks` in MINTICKS, which is a
    different percent per symbol (Binance NEARUSDT 0.001-tick: 2 ticks ≈
    0.038%; KuCoin 0.0001-tick: ≈ 0.004%). An explicit `slippage_pct`
    overrides (legacy, exact). Otherwise: ticks x tick / median price.
    """
    if slippage_pct is not None:
        return slippage_pct, f"{slippage_pct:.3f}%/fill (explicit)"
    if tick is None:
        tick = D.estimate_mintick(df)
    px = float(df["close"].dropna().median())
    pct = slippage_ticks * tick / px * 100.0
    return pct, f"{slippage_ticks} ticks (tick {tick:g} \u2248 {pct:.3f}%/fill @ {px:g})"


def run_backtest(base: pd.DataFrame, sig: Signals, p: Params, mech: Mechanics) -> tuple[pd.DataFrame, pd.Series, dict | None]:
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

    # ── confirmation-entry experiment (mech.confirm_bars > 0) ──────────────
    # A valid signal opens a PENDING entry instead of filling. Over the next
    # N completed bars:
    #   LONG  : cancel if any low < signal bar's low;   confirm if any close > signal bar's high
    #   SHORT : cancel if any high > signal bar's high; confirm if any close < signal bar's low
    #   (breach checked before confirmation on the same bar — stop-first)
    # Unconfirmed pendings expire after N bars. A new signal while a pending
    # is open supersedes it. On confirmation, stop/target/room are re-derived
    # from the confirmed entry price (same ATR multipliers); entries that no
    # longer meet the room requirement are rejected. cb == 0 ⇒ the code below
    # is inert and the baseline path is bit-identical.
    cb = mech.confirm_bars
    room_l = (sig.room_long.to_numpy() if sig.room_long is not None
              else np.full(n, np.inf))
    room_s = (sig.room_short.to_numpy() if sig.room_short is not None
              else np.full(n, np.inf))
    pend = None  # {"side", "sig_i", "sig_high", "sig_low", "deadline", "room_base"}
    pend_events: list[dict] = []

    def _pend_event(outcome: str, i: int | None = None, entry_px: float | None = None) -> None:
        nonlocal pend
        if pend is None:
            return
        sig_i = pend["sig_i"]
        pend_events.append({
            "signal_time": idx[sig_i],
            "side": "LONG" if pend["side"] == 1 else "SHORT",
            "signal_close": float(c[sig_i]),
            "signal_high": float(pend["sig_high"]),
            "signal_low": float(pend["sig_low"]),
            "outcome": outcome,
            "resolve_time": idx[i] if i is not None else None,
            "delay_bars": (i - sig_i) if i is not None else None,
            "confirm_close": float(c[i]) if (i is not None and outcome == "CONFIRMED") else None,
            "entry_price": float(entry_px) if entry_px is not None else None,
        })
        pend = None

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
        # 1.5) manage pending entry (confirmation experiment only)
        if cb > 0 and pend is not None and pos == 0:
            if i > pend["deadline"]:
                _pend_event("EXPIRED", i)
            elif pend["side"] == 1:
                if l[i] < pend["sig_low"]:
                    _pend_event("CANCELLED_BREACH", i)
                elif c[i] > pend["sig_high"]:
                    atr_j = atr_v[i]
                    if np.isfinite(atr_j):
                        room_base = pend["room_base"]
                        if np.isfinite(room_base):
                            pivot_px = room_base + c[pend["sig_i"]]
                            room_new = (pivot_px - c[i]) if c[i] < pivot_px else np.inf
                        else:
                            room_new = np.inf
                        if (not p.require_room) or room_new >= p.min_room_atr * atr_j:
                            entry_px = c[i] * (1 + slip)
                            stop = c[i] - p.stop_atr * atr_j
                            tgt = c[i] + p.tgt_atr * atr_j
                            qty = (equity * mech.qty_pct / 100.0) / entry_px
                            entry_i = i
                            entry_score = score_l[i] if p.is_scalp else score_rl[i]
                            pos = 1
                            _pend_event("CONFIRMED", i, entry_px)
                        else:
                            _pend_event("REJECTED_RISK", i)
            else:  # pend["side"] == -1
                if h[i] > pend["sig_high"]:
                    _pend_event("CANCELLED_BREACH", i)
                elif c[i] < pend["sig_low"]:
                    atr_j = atr_v[i]
                    if np.isfinite(atr_j):
                        room_base = pend["room_base"]
                        if np.isfinite(room_base):
                            pivot_px = c[pend["sig_i"]] - room_base
                            room_new = (c[i] - pivot_px) if c[i] > pivot_px else np.inf
                        else:
                            room_new = np.inf
                        if (not p.require_room) or room_new >= p.min_room_atr * atr_j:
                            entry_px = c[i] * (1 - slip)
                            stop = c[i] + p.stop_atr * atr_j
                            tgt = c[i] - p.tgt_atr * atr_j
                            qty = (equity * mech.qty_pct / 100.0) / entry_px
                            entry_i = i
                            entry_score = score_s[i] if p.is_scalp else score_rs[i]
                            pos = -1
                            _pend_event("CONFIRMED", i, entry_px)
                        else:
                            _pend_event("REJECTED_RISK", i)
        # 2) open new position (entry at signal-bar close ± slippage)
        if pos == 0 and np.isfinite(atr_v[i]):
            if cb == 0:
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
            else:
                if long_sig[i] or short_sig[i]:
                    if pend is not None:
                        _pend_event("OVERRIDDEN", i)  # newest signal supersedes
                    pend = {
                        "side": 1 if long_sig[i] else -1,
                        "sig_i": i,
                        "sig_high": float(h[i]),
                        "sig_low": float(l[i]),
                        "deadline": i + cb,
                        "room_base": float(room_l[i]) if long_sig[i] else float(room_s[i]),
                    }

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
    if cb > 0 and pend is not None:  # unresolved at data end
        _pend_event("OPEN_AT_END", n - 1)
    trades_df = pd.DataFrame(trades)
    trades_df.attrs["pending_events"] = pend_events
    eq = pd.Series([v for _, v in equity_points], index=pd.DatetimeIndex([t for t, _ in equity_points]), name="equity")
    return trades_df, eq, open_pos
