# Development cycle — real-data validation (post-V2.0)

**Goal (agreed):** demonstrate that the *existing* signals produce positive
results on real NEAR data without overfitting. **No new indicators, no new
features** in this cycle — only evidence tooling.

## Acceptance gates (minimum bar before paper trading)

Engineering gates, not guarantees of future profitability:

| # | Gate | Measurement | Pass |
|---|---|---|---|
| G1 | Positive net expectancy after realistic costs | `oos.py` best candidate, train **and** test windows, fee 0.10%/side + 2-tick slippage (defaults) | net > 0 in both |
| G2 | Profit factor > 1.2 | same | PF > 1.2 in both windows |
| G3 | Controlled drawdown | max DD per window (trade-close equity) | > −15% per window |
| G4 | Consistent performance across market conditions | test window split into 4 equal time chunks + by-regime table | no single chunk collapses relative to train; both regimes represented |

A mode that fails any gate is **not** paper-tradeable, regardless of how well
it looks on the other window.

## The four work items

### 1. Real NEAR data (BLOCKING — nothing else is meaningful before this)

Target file: **NEARUSDT.P (KuCoin, as charted in TradingView) 5m OHLCV**

- Range: **2026-06-15 00:00 → 2026-10-11 00:00 UTC** (≈32k bars). The
  2026-06-15 start gives ~1500 bars of indicator warmup headroom before the
  2026-07-01 study start; the end captures the Oct 8–9 crash plus recovery.
- Export: TradingView → 5m chart → toolbar **Export chart data → CSV**
  (format already accepted by `backtester.data.load_csv`).
- Save as `data/near_5m_real.csv` (git-ignored — real data stays local).
- **Why TradingView's own export:** item 4 compares Pine vs Python; using the
  same feed for both removes data-source disagreement as a variable.
- Validate first:
  ```bash
  python -m backtester.check_data --csv data/near_5m_real.csv \
      --window 2026-10-08,2026-10-10   # confirm the crash window is present
  ```
  Do not backtest on data that fails the quality gate.

### 2. Signal quality — loss diagnosis

```bash
python -m backtester.diagnose --csv data/near_5m_real.csv --mode scalp
python -m backtester.diagnose --csv data/near_5m_real.csv --mode reversal
```

Per-trade MFE/MAE (in R) + priority-ordered failure taxonomy:

1. **COST-DOMINATED** — gross > 0, net < 0: the trade was right, costs were not.
2. **NOISE STOP** — stopped out < 0.25R within 3 hours: entered with no
   development (false trigger / bad entry timing).
3. **FAILED BREAKOUT** — reached ≥ 0.75R then gave it all back: real move,
   wrong persistence (stop too tight or target too far).
4. **PREMATURE REVERSAL** (REVERSAL mode) — faded a trend that flipped back:
   the "weakening momentum" condition fired too early.
5. **LOW-VOL CHOP** — RANGING-regime entry with ATR% in the dataset's bottom
   quartile: no-edge environment.
6. residual buckets by exit reason (developed stops, targets, trend flips).

Plus: entry-volatility quartile table, per-month table, and a **cost
sensitivity grid** (fee × slippage) showing at what cost level any edge
dies. Interpretation discipline: fix the *dominant* failure bucket first,
one at a time, and re-run OOS — do not stack changes.

### 3. Out-of-sample (single pass, no peeking)

Proposed split for this dataset: **train 2026-07-01 → 2026-08-31**
(≈2 months), **test 2026-09-01 → 2026-10-11** (≈6 weeks, **includes the
crash** — an out-of-distribution stress the training window never saw).

```bash
python -m backtester.oos --csv data/near_5m_real.csv --mode scalp --train-end 2026-08-31
python -m backtester.oos --csv data/near_5m_real.csv --mode reversal --train-end 2026-08-31
```

Method: small grid (threshold × stop × target × room) ranked on train only
(min 30 train trades); top 5 candidates evaluated **once** on test. The test
window is never used for selection. If you are tempted to re-tune to the
test numbers: the test has stopped being out-of-sample — slice a new holdout.

### 4. TradingView verification (compile + compare)

On TradingView (sandbox has no TV access — this is a user step):

1. Paste `pine/signal_engine.pine` (indicator) and `pine/signal_engine_strategy.pine`
   (strategy) — note any compile errors verbatim and report them.
2. Strategy tester: same symbol/TF/range as the CSV, identical settings
   (mode, thresholds, ATR multipliers, room, fees 0.10%, slippage 2 ticks,
   10% of equity, initial 10,000).
3. Confirm visually: no disappearing arrows on confirmed bars; signals
   appear on the signal candle close, not before.
4. **List of Trades → ⋯ → Export to CSV.**
5. Compare:
   ```bash
   python -m backtester --csv data/near_5m_real.csv --mode scalp \
       --out-trades /tmp/py_trades.csv
   python -m backtester.compare --py-trades /tmp/py_trades.csv \
       --tv-trades /tmp/tv_trades.csv
   ```
   Expectation: 100% entry alignment within ±1 bar, side match, entry prices
   within ~0.05% (slippage/spread). Exit times should align; small PnL
   deltas are expected (TV applies its own fill model). Systematic
   divergence = an equivalence bug → report the first mismatched bars and we
   trace it to the specific component.

## REVERSAL mode — separate investigation (not threshold tuning)

V2 synth: 25% win rate, PF 0.18 — that is the wrong shape for a mean-reversion
entry set (reversal entries should win often, small, with a high stop-out
rate). Investigate **on real data** via `diagnose.py --mode reversal`, with
attention to:

- Is the rejection component actually binding at entry (score-component
  breakdown of winners vs losers)?
- Does "weakening momentum" fire before the 45m trend has genuinely rolled
  (PREMATURE REVERSAL bucket)?
- Are REVERSAL longs/shorts symmetric, or is one direction doing all the damage?
- Does the mode only fail in RANGING (chop) — i.e., does the regime gate
  need to be RANGING-only for reversals? (That is a *gate* question, not a
  scoring-threshold question.)

Explicitly out of scope for the rescue: changing `rev_thr` to hide the
problem. A reversal strategy that only works with an inflated minimum score
has no edge.

## Status

- [ ] Real data file in place + `check_data` PASS (with crash window confirmed)
- [ ] `diagnose` run + dominant failure bucket identified (per mode)
- [ ] `oos` single-pass result per mode, gates evaluated
- [ ] TradingView compile clean; `compare` verdict = MATCH
- [ ] REVERSAL preliminary diagnosis written up (keep/fix/retire decision)
- [ ] Gate table filled with real numbers → go/no-go on paper trading
