# NEAR 5m Signal Strategy — Research-Closure Report

**Charter:** SIGNAL-ENGINE-NEAR5M-RETIREMENT · Lifecycle REVIEW/CLEANUP ·
**AUTHORISED 2026-10-12** · Reference commit `65a46ff`.

## 0. Status

| Item | Status |
|---|---|
| SCALP signal family (NEAR 5m) | **RETIRED FOR NEAR 5M** |
| REVERSAL signal family (NEAR 5m) | **RETIRED FOR NEAR 5M** |
| Confirmation-entry variant (Phase 1 change #1) | **RETIRED** (kill criterion met) |
| Variants passing the profitability acceptance gates | **NONE** (of 160+ tested) |
| Pine strategy / indicator | Retained — marked RETIRED, research artifact only |
| Python backtester, data-validation, tests | Retained — reusable infrastructure |
| Automated trading / deployment configuration | **None exists in this repository** |
| 15m / limit-order follow-on programmes | **NOT started** (require separate authorisation) |

Retirement applies to NEAR 5m as the research target. It is a research
conclusion about this signal family on this market/timeframe — not a
statement that the infrastructure is broken.

## 1. What was tested (complete variant list)

All runs: `data/near_5m_real.csv` — 33,984 Binance NEARUSDT 5m bars,
2026-06-15 → 2026-10-10 23:55 UTC, gap-free, cross-validated against the
user's KuCoin grid entries (14 quiet-window anchors, within 0.4%).
Cost model: 0.10% fee/side + 2-tick slippage/fill; 10,000 USDT, 10% sizing.

**A. Baselines (all default parameters):**

| Variant | Trades | Win % | PF | Net (USDT) | Max DD |
|---|---|---|---|---|---|
| SCALP thr 80 (running config) | 794 | 32.6 | 0.28 | −3,082.54 | −31.0% |
| SCALP zero-cost (cost sensitivity) | 794 | — | 0.75 | −663.40 | — |
| REVERSAL thr 70 | 914 | 40.0 | 0.27 | −3,159.30 | — |
| TV strategy file, v6 baseline repro | 13 (3 wk window) | 0 | — | −661.38 | — |

Monthly PF, SCALP: 0.19 / 0.19 / 0.13 / 0.43 / 0.43 (Jun–Oct) — never
near 1 in any month. Failure taxonomy: NOISE STOP = 58.3% of losing PnL
(312 trades); FAILED BREAKOUT 9%; developed stops 26%.

**B. OOS parameter grids (train → 2026-08-31, test → 2026-10-10, single
pass, train-only ranking):**

| Grid | Size | Best candidate (by train) | Train (PF) | Test (PF) | Gates |
|---|---|---|---|---|---|
| SCALP: thr 75/80/85 × stop × target × room | 81 | thr 85 | −973.60 (0.29) | −940.83 (0.41) | net>0 F/F, PF>1.2 F/F |
| REVERSAL: thr 65/70/75 | 63 | thr 75 | −599.34 (0.41) | −403.96 (0.46) | net>0 F/F, PF>1.2 F/F |

162 grid candidates, every top-5 negative in **both** windows.

**C. Confirmation-entry experiment (Phase 1 change #1 — the final
experiment; full report in `docs/CONFIRMATION_ENTRY_EXPERIMENT.md`):**

| N (bars) | Trades | Win % | PF | Net | Train net (PF) | Test net (PF) |
|---|---|---|---|---|---|---|
| 0 (baseline, preserved) | 794 | 32.6 | 0.28 | −3,082.54 | −2,066.82 (0.16) | −1,015.72 (0.43) |
| 1 (selected on train) | 249 | 35.7 | 0.32 | −1,040.36 | −598.10 (0.20) | −442.26 (0.44) |
| 2 | 296 | 34.8 | 0.31 | −1,252.85 | −750.50 (0.18) | −502.35 (0.45) |
| 3 | 311 | 34.1 | 0.30 | −1,350.60 | −828.78 (0.17) | −521.83 (0.44) |

**No tested variant — baseline, any grid candidate, or confirmation-entry
window — passed the profitability acceptance gates** (net > 0 and PF ≥ 1.2
in both windows). The best ever recorded test PF is 0.46 (REVERSAL OOS);
the best net in any window of any variant is −403.96.

## 2. Performance evidence — why it closes

1. **No edge, consistently negative.** Every month, both modes, every
   window: PF 0.13–0.46. The 13-trade TV baseline (−661.38) was a small
   sample of the same system, not a fluke.
2. **Cost-to-R is the binding constraint.** Realised break-even win rate is
   **63.6%** (from actual winners +4.57 / losers −7.97), not the nominal
   41%: at NEAR's 5m ATR, round-trip costs ≈ 0.55R and 1.5R targets rarely
   fill. Costs are ≈78% of total loss (zero-cost net −663.40 vs −3,082.54).
   Actual win rate: 32.6%. No tested entry-timing filter came close to
   closing that 31-point gap.
3. **Entry timing is the second problem, and it was tested directly.**
   NOISE STOP (entered, price never develops, stopped in ~2.6 bars) = 58%
   of losing PnL. The confirmation-entry experiment attacks exactly this:
   it cut NOISE STOP 312→87, but the PnL improvement was **~100%
   frequency-driven** (Δnet +2,042 = +2,116 fewer trades + −74 selection);
   per-trade selection was neutral-to-negative.
4. **The regime gate did not protect the October grid positions.**
   Correction of record (also applied in `docs/NEXT_STEPS.md`): the earlier
   claim that "the ABNORMAL-VOL gate did its job during the crash" is
   **withdrawn**. The detector (ATR% > 1.8× its own 100-bar average) is
   self-normalizing and the regime **never classified ABNORMAL-VOL during
   Oct 7–10** (207 ABN bars over 4 months = 0.61%; last episode
   2026-09-23 15:30–17:55Z). The strategy traded freely on Oct 8 (9
   entries, 5 TARGET exits), and the four crash-killer margin grids all
   started while the regime was RANGING (×3) / TRENDING DOWN (×1) with 0%
   ABNORMAL-VOL in every window. A regime-gated entry rule would have
   blocked **none** of the grid losses — and regime gating cannot protect
   held grid inventory at all.

## 3. Known limitations

- **Single market, single timeframe.** Results speak to NEAR 5m (a ~$5,
  high-spread, low-R instrument). They do not establish that the signal
  model fails on other instruments/TFs — but no other market was in scope.
- **Test window was examined.** The Sep→Oct test window (incl. the crash)
  was used once for selection-adjacent reading in the OOS cycle; the
  confirmation-entry test touch inherits that caveat. No truly fresh
  holdout was available (data ends 2026-10-10).
- **One cost model.** 0.10% taker fee + 2 ticks. The break-even finding
  (63.6%) is robust to direction but its exact value is model-dependent;
  maker/limit execution would materially change it (estimated ~17–20%) —
  untested, not authorised.
- **Parity gap open (see §4).** TV win count 0 vs Python 52 on the same
  139-trade window; aggregate PnL matches (−573.85 vs −490.79).
- **Grid comparison is indicative.** The four margin bots' live windows
  were reconstructed from the user's grid export; the per-bot detail table
  was lost in a workspace restart and survives as aggregates
  (`data/grid_history_2026-10-12.md`).

## 4. Outstanding parity work (user step, unblocked by exports)

To be completed **when matching exports become available** (charter item 6):

1. **TV List of Trades** for the Sep 21 → Oct 11 NEAR 5m run (136 trades,
   TV stats) vs Python 139 / 52 wins — settle the **win count 0-vs-52**
   mismatch (aggregate PnL already matches; feed confirmed Binance;
   all-default settings confirmed).
2. **Pine `inConfirmBars` parity run** on the updated
   `pine/signal_engine_strategy.pine`: first `0` (must exactly reproduce
   the existing TV baseline), then `1` (must match Python N=1: 249 trades /
   −1,040.36 on this data's window). This is a retention/parity check on a
   retired experiment — it validates the mirror for the infrastructure's
   future reuse, not a new research question.
3. Optional: an extended NEAR 5m export (past Oct 10) or DJI 5m for the
   fresh holdout — only needed if a separate charter reopens research on
   this or another market.

## 5. Reusable components (retained, unmodified in this closure)

| Component | Path | Reuse notes |
|---|---|---|
| Python backtester | `backtester/` | Generic engine: any OHLCV CSV, SCALP/REVERSAL modes, cost model, pending/confirmation mechanics (`Mechanics.confirm_bars`, default 0 = exact baseline). |
| Data validation | `backtester/check_data.py`, `data.py` | Gap/quality checks; load_csv contract (UTC DatetimeIndex). |
| Diagnostics | `backtester/diagnose.py` | NOISE STOP / FAILED BREAKOUT taxonomy, MFE/MAE in R, cost-sensitivity grid. |
| OOS protocol | `backtester/oos.py` | Pre-registered train-only selection, single test touch, G1–G4 gates. |
| TV comparison | `backtester/compare.py` | Auto-detects TV List-of-Trades CSV, per-trade and aggregate deltas. |
| Pine strategy (marked RETIRED) | `pine/signal_engine_strategy.pine` | `strategy()` with fees/slippage/regime table; `inConfirmBars` mirror; parity reference for Pine↔Python equivalence rules. |
| Pine indicator (marked RETIRED) | `pine/signal_engine.pine` | Alert/ingestion interface: webhook-ready JSON alert contract (`docs/SIGNAL_SPEC.md` §10) — reusable for any future signal model's ingestion pipeline. |
| Canonical spec | `docs/SIGNAL_SPEC.md` | Signal model documentation, alert contract, versioning convention. |
| Tests | `tests/` (1 test + 2 subtests; `tests/smoke_test.py` ALL CHECKS PASSED) | Non-repainting + invariant checks, Pine alert-contract tests. |
| Evidence record | `docs/NEXT_STEPS.md`, `docs/CONFIRMATION_ENTRY_EXPERIMENT.md`, this report | Full diagnosis → OOS → experiment trail incl. corrections. |

Signal logic, indicators, gates, stops, targets and cost model are
**unmodified** by this closure (charter rule 8) — the files are preserved
exactly as of reference commit `65a46ff`, with status banners added.

## 6. Automated-trading / deployment check (charter item 7)

- The repository contains **no order execution, no exchange API
  integration, no deployment configuration, and no live-trading config** —
  verified by full-repository search (only references are explicit
  "no orders are ever sent" statements).
- Both Pine files carry a header status block and (strategy) an on-chart
  NOTES line: **RETIRED — research artifact, not an authorised trade
  recommendation**.
- The webhook JSON alerts remain for research monitoring only; the alert
  contract in `docs/SIGNAL_SPEC.md` §10 must not be treated as an
  authorisation to trade.
- **Rule going forward:** the retired SCALP/REVERSAL signals must not be
  referenced as authorised trade recommendations in any configuration,
  alert, or deployment; any future use of this infrastructure requires a
  new charter with fresh data and fresh acceptance gates.

## 7. What was explicitly NOT done

- No signal-logic changes; no new optimisation cycle started (rule 8).
- No 15-minute-timeframe or limit-order execution programme started —
  both remain **parked options** recorded in `docs/NEXT_STEPS.md` and this
  report, requiring **separate authorisation** to proceed.
- No data or code was deleted; the only removals are none — corrections
  were made to two inaccurate claims (ABNORMAL-VOL "did its job"; "not a
  cost problem"), both marked CORRECTION in place.

**Programme closed 2026-10-12. End of report.**
