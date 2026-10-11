# NEAR Signal Engine

Multi-timeframe, weighted-scoring signal engine for intraday crypto scalping
and countertrend reversals — built for TradingView (Pine Script v6), with a
matching `strategy()` for performance measurement and a Python backtester for
offline analysis of exported OHLCV data.

**Initial release scope: signals and alerts only. No order execution, no live
trading, no hard-coded NEAR price targets.** Everything is configurable.

> ⚠️ Not financial advice. A score of 85/100 is a weighted confidence
> composite — **not** an 85% win probability. Validate on real historical
> data before trusting any parameter.

---

## Repository map

```
pine/signal_engine.pine              ← ① TradingView INDICATOR (start here)
pine/signal_engine_strategy.pine     ← ② TradingView STRATEGY (fees, slippage, stats)
backtester/                          ← ③ Python backtester (CSV in, report out)
backtester/sample_data.py            ← synthetic data generator (pipeline validation)
tests/smoke_test.py                  ← non-repainting + invariant tests
docs/SIGNAL_SPEC.md                  ← canonical signal model (source of truth)
data/                                ← exported / sample OHLCV data
```

All three implementations share one signal model, documented canonically in
[`docs/SIGNAL_SPEC.md`](docs/SIGNAL_SPEC.md). **Keep them in sync** — that
document wins any conflict; bump the version string when you change the model.

---

## ① The Pine indicator (priority deliverable)

### Install

1. TradingView → Pine Editor → paste `pine/signal_engine.pine` → **Add to chart**.
2. Chart: **NEAR-USDT on the 5m timeframe** (your entry TF). Any TF works, but
   the table shows the chart TF so you can verify.
3. Defaults: 45m bias / 15m momentum / 5m entry, SCALP mode, threshold 80/100.

### What you see

- **BUY/SELL arrows + labels** on the *signal candle* (the confirmed bar that
  triggered), with entry/stop/target.
- **Info table** (top-left): 45M/15M/5M bias, market regime (TRENDING UP /
  TRENDING DOWN / RANGING / ABNORMAL VOL), current score vs threshold,
  paper-position tracking with stop/target lines, last exit, and a full
  **score breakdown + gate pass/fail explanation** for both directions.
- **Session VWAP** (bias only — not required for entries by default).

### Non-repainting guarantees

- HTF/MID values come from `request.security(..., barmerge.gaps_off,
  barmerge.lookahead_off)` with `[1]` — i.e. the **last completed bar** only.
- Entry decisions are made on the **last confirmed 5m candle** and latched
  once per entry bar (`ta.change` on the confirmed bar time).
- Arrows/labels are drawn on the signal candle and **never move or disappear**.
- Alerts fire the moment the signal candle closes.

### Signals & scoring (defaults)

Weighted 100-point model — full detail in [`docs/SIGNAL_SPEC.md`](docs/SIGNAL_SPEC.md):

| Component (SCALP) | Weight |
|---|---|
| 45m trend alignment | 20 |
| 15m momentum confirmation | 20 |
| 5m EMA structure | 15 |
| RSI momentum | 10 |
| MACD momentum | 10 |
| Volume confirmation | 15 |
| Market structure breakout | 10 |

Gates applied on top of the score (all configurable): strict 45m alignment
(SCALP), regime block in ABNORMAL VOL, optional VWAP alignment, and the
**room filter** — distance to the nearest valid pivot S/R must be ≥ 2.0×ATR so
the 1.8×ATR target physically fits. Stops = 1.2×ATR, targets = 1.8×ATR.

**REVERSAL mode** uses a separate 100-point model (rejection at S/R, momentum
turning, HTF momentum weakening, entry-TF flip, volume, structure) with a
70/100 default threshold — it requires rejection evidence + weakening
momentum, not just overbought/oversold RSI.

### Alerts (webhook-ready)

Six `alertcondition` entries (BUY, SELL, EXIT LONG, EXIT SHORT, TREND CHANGE,
REGIME CHANGE) **plus** `alert()` calls that emit **structured JSON**
(webhook-compatible for future KuCoin automation — no orders are ever sent):

```
{"source":"signal-engine","event":"BUY","side":"LONG","mode":"SCALP",
 "symbol":"NEAR-USDT","time_ms":1789000000000,"score":85,"threshold":80,
 "components":{"trend45":20,"mom15":16,"ema5":15,"rsi":10,"macd":10,
               "volume":10,"structure":4},
 "price":5.3,"stop":5.27,"target":5.355,"atr":0.025,"rr":1.5,
 "regime":"TRENDING UP","position":{...},"reason":"score 85 >= 80",
 "meta":{"repainting":"none","execution":"none"}}
```

Create an alert on the indicator, add your webhook URL, and TradingView
delivers the JSON the instant the signal candle closes.

---

## ② The Pine strategy (measure before you trust)

`pine/signal_engine_strategy.pine` — **chart it on 5m**. It reuses the same
signal logic (same indicators, scores, gates, stop/target math) and runs it as
a `strategy()` with:

- **fees** (default 0.10%/side — KuCoin taker) and **slippage** (default 2 ticks)
- entries at the **signal-bar close** (`process_orders_on_close=true`) — the
  same execution convention as the indicator display and the Python engine
- a live table: net profit, profit factor, max drawdown, win rate, **and
  performance broken out by market regime** (at entry)
- the same alert contract as the indicator

**How to test it (in-sample / out-of-sample):**
1. Set the chart range to your in-sample window (e.g. 2025-01 → 2026-03),
   open the Strategy Tester, note PF / DD / win rate / regime table.
2. Keep the parameters, move the range to out-of-sample (e.g. 2026-04 → now)
   and compare. Only then tune — and re-check out-of-sample after any change.
3. Test both modes (SCALP and REVERSAL) and both TF configs you care about.

---

## ③ The Python backtester

```bash
pip install -r requirements.txt

# validate the pipeline on the bundled synthetic sample (NOT a performance claim)
python -m backtester.sample_data --out data/sample_near_5m_synth.csv --days 100
python -m backtester --csv data/sample_near_5m_synth.csv --mode scalp

# your real export (TradingView or KuCoin format — see data/README.md)
python -m backtester --csv data/near_5m.csv --mode scalp --fee-pct 0.1 --slippage-pct 0.02
python -m backtester --csv data/near_5m.csv --mode reversal --out-trades data/trades.csv
python tests/smoke_test.py   # non-repainting truncation test + engine invariants
```

CLI mirrors the Pine settings: `--mode`, `--threshold`, `--stop-atr`,
`--target-atr`, `--min-room-atr`, `--fee-pct`, `--slippage-pct`, `--qty-pct`,
`--no-strict-trend`, `--vwap-gate`, `--no-block-abnormal`, `--out-trades`,
`--out-signals` (per-bar scores/signals/regime CSV), `--check-norepaint`
(truncation test on your own data — exits non-zero on any mismatch), …
(run `python -m backtester --help`).

**Equivalence with the Pine strategy:** entry at signal-bar close, slippage
on **all fills** (entries and exits, adverse direction), stop-before-target
tie-break, gap fills at the open, same fee model, same 10%-of-equity sizing.
Known minor deltas are listed in `docs/SIGNAL_SPEC.md` §11.

### Validation tooling (analysis only — no model changes)

```bash
# data quality gate (run first on any real export)
python -m backtester.check_data --csv data/near_5m_real.csv --window 2026-10-08,2026-10-10
# loss taxonomy: WHY did losing trades happen (MFE/MAE, cost sensitivity)
python -m backtester.diagnose --csv data/near_5m_real.csv --mode scalp
# out-of-sample: optimise on train, validate once on test
python -m backtester.oos --csv data/near_5m_real.csv --mode scalp --train-end 2026-08-31
# TradingView strategy export vs Python trades
python -m backtester.compare --py-trades py_trades.csv --tv-trades tv_trades.csv
```

The current development cycle (real data, loss diagnosis, OOS, TradingView
verification, acceptance gates) is specified in **`docs/NEXT_STEPS.md`**.

### Running the non-repainting check

`tests/smoke_test.py` includes a **truncation test**: signals computed on
`data[:k]` must be bit-identical (scores, signals, regime) to the full run on
those bars. This is the programmatic equivalent of "no disappearing arrows".

---

## Market regime handling

| Regime | Meaning | Default behavior |
|---|---|---|
| TRENDING UP / DOWN | ADX ≥ 20 + EMA separation + DI dominance (15m) | SCALP trades with the trend only; REVERSAL fades the prevailing 45m trend at S/R |
| RANGING | low ADX / small EMA separation | both sides possible — structure breakout + room filter do the filtering |
| ABNORMAL VOL | ATR% > 1.8× its 100-bar average | **entries blocked** (toggle: "Block entries in ABNORMAL VOL") |

A breakout strategy and a grid/range strategy should not share entry logic —
the regime label in the table and in every JSON alert exists so your
automation can route accordingly.

---

## Refinement loop (the plan we agreed on)

1. Indicator live on NEAR-USDT 5m → observe signals vs actual price action.
2. Strategy tester on in/out-of-sample windows → PF, DD, win rate, **by regime**.
3. Python backtester on your own exports → independent cross-check of the same logic.
4. Tune from results (threshold, weights, ATR multipliers, room filter, regime
   thresholds) — never from assumptions. Keep the three implementations in
   sync per `docs/SIGNAL_SPEC.md`.
5. Only after validation: extend the JSON alerts toward KuCoin automation
   (the payload already carries entry/stop/target, score, regime and position
   state — nothing order-related, by design, in this release).

---

## Changelog

### v2.0.0

**Correctness fixes (found by adversarial self-review):**

- **Gates silently disabled (Python)** — the regime/VWAP/room gates used
  `~` (bitwise NOT) on Python bools, where `~True == -2` (truthy), so every
  gate evaluated to `True` and never filtered anything. Fixed to logical
  `not`; now covered by dedicated tests (room filter, abnormal-vol block,
  VWAP gate invariants). Pine was unaffected (`not` is logical in Pine).
- **Exit fills had no slippage (Python)** — slippage was applied to entries
  only, unlike the Pine strategy tester which slips every fill. Now applied
  to all fills in all implementations; spec §8/§9 updated.
- **Stale stop/target display in the Pine strategy** — after a stop/target
  fill the table kept showing the previous levels; levels are now cleared
  when flat, and the JSON exit alert infers STOP/TARGET from bar OHLC vs the
  pending levels (the strategy API does not expose close reasons).

**Upgrades:**

- Pine data layer split into role-specific packs — 45m trend: 5 fields,
  15m momentum: 14, 5m entry: 29 (was one 35-field pack fetched three
  times) — lower compile cost and a clearer contract per TF.
- Python per-TF frames built by role (trend/mid/entry) — fewer wasted
  indicator passes.
- Report: per-direction (LONG/SHORT) stats, average bars held, and an
  explicit "open position at data end" note (excluded from stats, as in
  the strategy tester).
- New CLI: `--out-signals` (per-bar scores/signals/regime export) and
  `--check-norepaint` (truncation test on your own data).
- Test suite: 26 checks — added exact exit-slippage recompute for every
  trade, filter invariants, gap-fill unit test (forced signal), no-trend-flip
  in reversal mode, open-position reporting.
- Alert JSON schema version bumped to `2.0.0`.

### v1.0.0

Initial release: multi-timeframe weighted-scoring indicator (SCALP +
REVERSAL), equivalent strategy with regime attribution, Python backtester,
webhook-ready JSON alerts, synthetic sample + smoke tests.
