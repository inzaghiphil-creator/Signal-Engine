# SIGNAL SPEC v1.0.0 — canonical signal model

This document is the **single source of truth** for the entry/exit logic.
Three implementations must stay in sync with it:

| Implementation        | File                                |
|-----------------------|-------------------------------------|
| Pine indicator (v6)   | `pine/signal_engine.pine`           |
| Pine strategy (v6)    | `pine/signal_engine_strategy.pine`  |
| Python backtester     | `backtester/` (see `signals.py`)    |

If any of them disagrees with this document, **this document wins** — fix the
code, bump the version, and re-run `tests/smoke_test.py`.

## 1. Timeframes & data

| Role            | Default | Input        |
|-----------------|---------|--------------|
| Trend / bias    | 45m     | `inHtf`      |
| Momentum / regime| 15m    | `inMid`      |
| Entry / execution| 5m     | `inEntry`    |

Non-repainting rules (all implementations):

1. **HTF/MID values**: only the **last completed bar** of that TF may be used
   at the open of base bar `t` — i.e. an HTF bar with open `T` is visible iff
   `T + tf_htf ≤ t`. (Pine: `request.security(..., barmerge.gaps_off,
   barmerge.lookahead_off)` with every expression shifted by `[1]`. Python:
   `data.align_htf`.)
2. **Entry-TF values**: the decision at signal bar `i` uses bar `i`'s own
   confirmed OHLCV. The Pine *indicator* observes the identical state one
   chart-bar later via `[1]` and latches once per confirmed entry bar
   (`ta.change(lastConfirmedEntryBarTime)`), so arrows/labels sit on the
   signal candle and never move.
3. No implementation may read bar `i+1` or any partial bar.

## 2. Indicators (per TF, defaults)

- EMA 9 / 21 / 55 / 200 (`ta.ema`)
- RSI 14 (Wilder), levels: weak 40, neutral 50, strong 60, OB 70, OS 30
- MACD 12/26/9: line = EMA12−EMA26, signal = EMA9(line), hist = line−signal
- Volume: SMA20; breakout = vol > 1.5 × SMA20
- ATR 14 (Wilder/RMA)
- Pivots: `ta.pivothigh/pivotlow(high/low, 5, 5)` — strict inequality,
  confirmed 5 bars after the center. State machine (entry bars):
  - `lastPh/lastPl` = value of the last **fresh** pivot (fresh = first
    appearance *or* value differs from the previous pivot's)
  - `phAge/plAge` = entry bars since that pivot was published
  - `valid` = age ≤ 120 (`inPivAgeMax`), `fresh` = age ≤ 15 (`inPivFresh`)
- ADX/DI 14 (Wilder) on the MID TF — used by regime only
- ATR% = ATR14/close×100 on MID, averaged over 100 MID bars
- Session VWAP (UTC day) on the ENTRY TF — bias display / optional gate

## 3. Market regime (MID TF)

```
volSpike  = ATR% > 1.8 × SMA100(ATR%)          → regime = ABNORMAL VOL
sepPct    = (EMA21 − EMA55) / close × 100
trendUp   = ADX ≥ 20 and sepPct ≥ +0.15 and +DI > −DI  → TRENDING UP
trendDn   = ADX ≥ 20 and sepPct ≤ −0.15 and −DI > +DI  → TRENDING DOWN
else                                                        → RANGING
```
(ABNORMAL VOL has priority. NaN → false → RANGING during warmup.)

## 4. HTF trend state (45m)

```
trend45 = +1 if EMA9 > EMA21 > EMA55
          −1 if EMA9 < EMA21 < EMA55
           0 otherwise
bias45  = trend45, plus close vs EMA200, for display (BULLISH/BEARISH/NEUTRAL)
```

## 5. SCALP scoring (100 points)

Score = Σ weight × (sub-points earned / sub-points available).
NaN comparison = false (0 points).

### LONG

| Component (weight) | Sub-conditions (points) |
|---|---|
| 45m trend (20) | full alignment 9>21>55 (2) · else 9>21 (1) · close>EMA200 (1) · close>EMA55 (1) |
| 15m momentum (20) | hist>0 (1) · hist rising (1) · RSI>50 (1) · EMA9>EMA21 (1) · RSI rising (1) |
| 5m EMA structure (15) | 9>21 (1) · 21>55 (1) · close>EMA9 (1) · EMA55 rising (1) |
| RSI (10) | RSI>50 (1) · RSI rising (1) · RSI<70 (1) |
| MACD (10) | hist>0 (1) · MACD line>0 (1) · hist rising (1) |
| Volume (15) | vol>1.5×SMA20 (2) · close>open (1) · vol rising (1) |
| Structure (10) | fresh pivot-high breakout: close>lastPh (2) · support retest hold: low≤lastPl+0.3×ATR and close>lastPl+0.1×ATR (1) · EMA21 rising (1) |

### SHORT (mirror)

| Component (weight) | Sub-conditions (points) |
|---|---|
| 45m trend (20) | full bearish alignment (2) · else 9<21 (1) · close<EMA200 (1) · close<EMA55 (1) |
| 15m momentum (20) | hist<0 (1) · hist falling (1) · RSI<50 (1) · EMA9<EMA21 (1) · RSI falling (1) |
| 5m EMA structure (15) | 9<21 (1) · 21<55 (1) · close<EMA9 (1) · EMA55 falling (1) |
| RSI (10) | RSI<50 (1) · RSI falling (1) · RSI>30 (1) |
| MACD (10) | hist<0 (1) · line<0 (1) · hist falling (1) |
| Volume (15) | vol>1.5×SMA20 (2) · close<open (1) · vol rising (1) |
| Structure (10) | fresh pivot-low breakdown: close<lastPl (2) · resistance retest rejection: high≥lastPh−0.3×ATR and close<lastPh−0.1×ATR (1) · EMA21 falling (1) |

## 6. REVERSAL scoring (100 points)

Countertrend. LONG fades a bearish move at support; SHORT mirrors at resistance.

### LONG

| Component (weight) | Sub-conditions (points) |
|---|---|
| Rejection (25) | support touch: low≤lastPl+0.25×ATR (5) · close>open reclaim (5) · wick rejection: (close−low)≥max(0.3×ATR, 0.4×range) (5) · previous bar bearish (5) · RSI in (30, 60] (5) |
| Momentum turning (25) | RSI rising (5) · hist rising (5) · MACD crossed above signal ≤3 bars ago (5) · hist was negative (5) · RSI>40 (5) |
| HTF weakening (15) | 15m hist falling (5) · 15m RSI<50 (5) · 15m −DI>+DI (5) |
| Entry-TF flip (10) | EMA9/21 cross up ≤3 bars ago (5) · MACD cross up ≤3 bars ago (5) |
| Volume (15) | vol>1.5×SMA20 (5) · vol rising (5) · close>open and vol>SMA20 (5) |
| Structure (10) | support holding: low≤lastPl+0.5×ATR and close>lastPl (5) · EMA21 rising (5) |

### SHORT (mirror): high≥lastPh−0.25×ATR · close<open · upper-wick rejection ·
previous bar bullish · RSI in [40,70) · RSI falling · hist falling · MACD cross
down ≤3 bars · hist was positive · RSI<40 · 15m hist rising · 15m RSI>50 ·
15m +DI>−DI · EMA9/21 cross down · MACD cross down · volume (mirror) ·
resistance holding · EMA21 falling.

## 7. Gates (applied after the score)

| Gate | LONG | SHORT |
|---|---|---|
| Score | score ≥ 80 (scalp) / 70 (reversal) — configurable | same |
| HTF trend | SCALP: `trend45 == +1` (strict; neutral allowed when strict off). REVERSAL: `trend45 ≠ +1` | SCALP: `trend45 == −1`. REVERSAL: `trend45 ≠ −1` |
| Regime | not ABNORMAL VOL (when blocking on) | same |
| VWAP (optional, off by default) | close > session VWAP | close < session VWAP |
| Room (R/R filter) | nearest valid pivot **above** close ≥ 2.0×ATR — if no valid pivot overhead (broke out / stale) the room is infinite → pass. Same below for shorts. |

`room = lastPh − close` (long) when `lastPh` is valid and > close, else ∞.
A signal that fails any gate is **not** actionable (table shows why).

## 8. Trade management

- Entry: signal-bar close ± slippage (Pine strategy: `process_orders_on_close`).
- Stop  = entry ∓ 1.2 × ATR(signal bar) · Target = entry ± 1.8 × ATR
- Per-bar management order (all implementations):
  1. STOP (checked before target — conservative tie-break)
  2. TARGET
  3. REVERSAL (opposite actionable signal → close & flip at close)
  4. TREND FLIP — **SCALP only** (long exits when `trend45 == −1`; the
     mirror for shorts). REVERSAL mode has no trend-flip exit: a reversal
     long *enters* on a bearish 45m trend, so "flipping against the position"
     is its normal entry state.
- Gaps: if a bar opens beyond the stop/target, fill at the open.
- No pyramiding (one position at a time).

## 9. Costs (strategy / backtester)

- Fee 0.10% per side (KuCoin taker, configurable)
- Slippage 2 ticks (≈0.02% at 0.0001 tick, configurable)
- Position = 10% of equity (configurable), initial capital 10,000

## 10. Alerts (webhook JSON)

Events: `BUY`, `SELL`, `EXIT_LONG`, `EXIT_SHORT`, `TREND_CHANGE`,
`REGIME_CHANGE`. Example (BUY):

```json
{
  "source": "signal-engine", "version": "1.0.0", "event": "BUY", "side": "LONG",
  "mode": "SCALP", "symbol": "NEAR-USDT",
  "time_ms": 1789000000000, "time": "2026-10-10T06:25:00Z", "entry_tf": "5",
  "score": 85, "threshold": 80,
  "components": {"trend45": 20, "mom15": 16, "ema5": 15, "rsi": 10, "macd": 10, "volume": 10, "structure": 4},
  "price": 5.3, "stop": 5.27, "target": 5.355, "atr": 0.025, "rr": 1.5,
  "regime": "TRENDING UP",
  "position": {"side": "FLAT", "entry": null, "stop": null, "target": null},
  "reason": "score 85 >= 80",
  "meta": {"repainting": "none", "execution": "none"}
}
```

REVERSAL-mode `components` keys: `rejection, momentum, htf_weakening, flip,
volume, structure`. `execution` is always `"none"` — this release sends
signals only; no order routing.

## 11. Known simplifications / deltas

- Pine strategy exit *reason* in the JSON for STOP/TARGET fills points at the
  strategy tester (the reason is implicit in the fill price); the indicator's
  paper tracker and the Python engine report exact reasons.
- Same-bar stop+target ambiguity: stop wins (all implementations).
- Indicator paper tracker PnL is pre-fee; the strategy/backtester are
  post-fee.
- Python max drawdown is measured on the trade-close equity curve; the Pine
  strategy tester uses its own (finer-grained) computation.
