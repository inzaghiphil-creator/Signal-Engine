# Confirmation-Entry Experiment — Evidence Report

**Charter:** SIGNAL-ENGINE-CONFIRMATION-ENTRY-EXPERIMENT · Phase 1, Change #1 only ·
2026-10-12 · Trading authority: none.

**Objective:** determine whether delayed, price-confirmed entries reduce NOISE STOP
losses and improve net expectancy on NEAR 5m.

## 1. Setup & controls

- **Data:** `data/near_5m_real.csv` — 33,984 bars, 2026-06-15 00:00 → 2026-10-10
  23:55 UTC, Binance NEARUSDT 5m, gap-free (verified), cross-checked against the
  user's KuCoin grid entries (quiet-window anchors within 0.4%).
- **Parameters:** all defaults — SCALP, thr 80, stop 1.2×ATR, target 1.8×ATR,
  room 2.0×ATR, fee 0.10%/side, slippage 2 ticks, 10,000 USDT, 10% sizing.
  Nothing else changed (charter rule 2).
- **Mechanics (charter rules 3–10):** valid signal → pending entry; confirm =
  close beyond the signal bar's extreme (long: close > signal high; short:
  close < signal low); cancel = breach of the signal bar's opposite extreme
  (breach checked before confirm on the same bar — stop-first); expire after N
  completed bars; new signal supersedes an open pending; on confirmation,
  stop/target/room re-derived from the confirmed entry price (same ATR
  multipliers, ATR at the confirm bar, the pivot level the signal was granted);
  entries failing the room requirement are rejected; no overlapping pendings,
  no duplicates, no lookahead (entry fills at the confirming bar's close —
  the existing fill convention — with the same fees/slippage).
- **Baseline invariance (charter rule 1):** with the experiment flag at 0 the
  engine output is value-identical to the pre-change engine (794 trades,
  net −3,082.54, zero differences across all columns). The baseline is
  immutable.
- **Selection rule (pre-registered):** N ∈ {1, 2, 3} ranked on TRAIN net PnL
  (tie → train PF); the selected N's TEST result is touched once.
  Split: train = entries before 2026-08-31, test = after.
- **Caveat:** this test window was already examined in the OOS cycle, so the
  selected candidate's test result is indicative, not final. A final go/retire
  decision requires fresh data (not yet available — see §8).

## 2. Headline results

| N (bars) | Trades | Win % | PF | Net | Max DD | Train net (PF) | Test net (PF) |
|---|---|---|---|---|---|---|---|
| 0 (baseline) | 794 | 32.6 | 0.28 | −3,082.54 | 3,108.64 | −2,066.82 (0.16) | −1,015.72 (0.43) |
| **1 ← selected (best train net)** | **249** | **35.7** | **0.32** | **−1,040.36** | **1,053.18** | **−598.10 (0.20)** | **−442.26 (0.44)** |
| 2 | 296 | 34.8 | 0.31 | −1,252.85 | 1,265.67 | −750.50 (0.18) | −502.35 (0.45) |
| 3 | 311 | 34.1 | 0.30 | −1,350.60 | 1,363.43 | −828.78 (0.17) | −521.83 (0.44) |

**Gates (selected N=1):** G1 net > 0 train & test → **FAIL** (−598 / −442).
G2 PF > 1.2 → **FAIL** (0.20 / 0.44). G3 DD > −15% → pass (−6.0% / −4.4%).

## 3. Required comparisons

**Signal flow** (signals = valid signals while flat):

| N | Signals | Confirmed | Expired | Cancelled (breach) | Superseded | Risk-rejected | Avg delay | Avg price move at confirm |
|---|---|---|---|---|---|---|---|---|
| 1 | 1,019 | 249 (24.4%) | 409 | 229 | 123 | 9 | 1.00 bar | +0.228% (med +0.241%) |
| 2 | 966 | 296 (30.6%) | 186 | 313 | 161 | 10 | 1.19 bars | +0.229% |
| 3 | 947 | 311 (32.8%) | 92 | 345 | 189 | 10 | 1.31 bars | +0.219% |

**Entry deterioration:** the confirmation delay costs on average ~0.23% of
price ≈ **2.3 USDT per 1,000 USDT notional — about 85% of one round-trip
cost (~2.7 USDT)**. Every confirmed trade pays this drag on top of fees.

**NOISE STOP** (exit STOP, MFE < 0.25R, ≤ 12 bars):

| N | Trades | % of all | Net (USDT) |
|---|---|---|---|
| 0 | 312 | 39.3% | −2,534.81 |
| 1 | 87 | 34.9% | −863.84 |
| 2 | 114 | 38.5% | −1,108.18 |
| 3 | 120 | 38.6% | −1,154.45 |

NOISE STOP count falls 72% at N=1 (vs 69% fewer trades overall) — a mild
selective effect — but it remains the dominant loss bucket.

**Missed trades** (baseline trades whose signal never confirmed):

| N | Missed of 794 | of which profitable | Missed-set net |
|---|---|---|---|
| 1 | 529 | 126 (+586.92) | −2,672.57 |
| 2 | 480 | 103 (+460.57) | −2,581.47 |
| 3 | 461 | 96 (+441.28) | −2,501.14 |

The skipped set is net-negative and its win rate (23.8% at N=1) is below the
baseline's 32.6% — the gate does filter somewhat correctly, but not enough.

**LONG/SHORT (full run):**

| N | LONG | SHORT |
|---|---|---|
| 0 | 526 / −1,924 / PF 0.33 | 268 / −1,158 / PF 0.17 |
| 1 | 180 / −677 / PF 0.39 | 69 / −364 / PF 0.15 |
| 2 | 212 / −830 / PF 0.37 | 84 / −423 / PF 0.18 |
| 3 | 220 / −889 / PF 0.35 | 91 / −462 / PF 0.17 |

**Regime at entry (full run):**

| N | TRENDING UP | TRENDING DOWN | RANGING |
|---|---|---|---|
| 0 | 333 / −1,309 | 184 / −833 | 277 / −941 |
| 1 | 115 / −431 | 42 / −260 | 92 / −349 |
| 2 | 138 / −558 | 54 / −318 | 104 / −377 |
| 3 | 145 / −638 | 61 / −357 | 105 / −356 |

Shorts (PF ≈ 0.15–0.18) and TRENDING-UP 5m entries remain the worst slices in
every variant.

## 4. Realised break-even (challenge #1 — accepted)

Computed from actual trade outcomes, not the nominal 1.5R target:

| N | Avg win | Avg loss | Realised break-even win % | Actual win % |
|---|---|---|---|---|
| 0 | +4.57 | −7.97 | **63.6%** | 32.6% |
| 1 | +5.56 | −9.60 | 63.3% | 35.7% |
| 2 | +5.58 | −9.47 | 62.9% | 34.8% |
| 3 | +5.49 | −9.43 | 63.2% | 34.1% |

Why the nominal 41% was wrong: at NEAR's 5m ATR (~0.4% of price), 1R ≈ 0.48%
of notional while round-trip cost ≈ 0.28% of notional — **costs are ~0.55R**,
so a "1.5R target" win nets only ~0.57R. The system needs a **~64% win rate**
to break even; it has 33%. N=1 bought +3.1 points of win rate at the cost of
~0.23% of price per entry.

## 5. Frequency vs selection (charter completion question)

Δnet vs baseline decomposed: ΔN × avg_net_baseline (frequency) + N_exp ×
Δavg_net (selection):

| N | Δnet | Frequency effect | Selection effect |
|---|---|---|---|
| 1 | +2,042.17 | **+2,115.85** | **−73.67** |
| 2 | +1,829.68 | +1,933.38 | −103.70 |
| 3 | +1,731.93 | +1,875.15 | −143.21 |

**Answer: the PnL improvement is essentially 100% reduced trading frequency.
Per-trade selection is neutral-to-slightly-negative** (confirmed trades
average −4.18 vs baseline −3.88; the PF uptick comes from a changed loss
mix, not from better entries). The experiment did not find a trade-selection
edge in price confirmation.

## 6. Grid-exposure comparison (challenge #2 — accepted)

The four leveraged margin grids that lost −4,544:

| Bot (margin) | Live window start (UTC) | Regime @ start | ABN-VOL % of window | First ABN in window |
|---|---|---|---|---|
| 2,050 (4.9–5.6) | 10/08 10:03 | RANGING | 0% | — |
| 1,500 (4.9–5.7) | 10/08 09:09 | RANGING | 0% | — |
| 925 (5.25–5.65) | 10/08 08:58 | RANGING | 0% | — |
| 1,000 (4.9–5.4) | 10/08 14:55 | TRENDING DOWN | 0% | — |

ABNORMAL VOL across the whole 4-month dataset: **207 bars (0.61%), 11
episodes of 10–160 min, last one 2026-09-23 15:30–17:55 UTC. The Oct 8 crash
never triggered the regime** (the detector, ATR% > 1.8× its own 100-bar
average, is self-normalizing: in a flash crash the average rises with it).

**Record correction:** the earlier claim that "the ABNORMAL-VOL gate did its
job during the crash" is **withdrawn**. The gate was dormant during the crash;
the strategy traded freely on Oct 8 (9 entries in the full-data run, 5 of them
TARGET exits) under RANGING / TRENDING DOWN.

**Consequence:** a "no new entries while ABNORMAL VOL" rule would have blocked
**none** of the four crash-killer grid entries (all were entered before the
regime could have flipped — and it never did). And even if it had fired mid-
window, regime gating stops *new entries*, not *held inventory* — the grid
failure mode is inventory liquidation. The strategy's regime gate, as
calibrated, provides no demonstrated protection against the actual grid loss.
If crash protection for grid deployments is a goal, the detector's calibration
(or an independent fast-volatility trigger) is a separate workstream — not
tested here, not authorised here.

## 7. Python / Pine equivalence

- **Python:** baseline invariance verified; experiment executed as specified.
- **Pine:** `pine/signal_engine_strategy.pine` now carries
  `inConfirmBars` (input, default 0 = exact baseline behaviour; 1–3 = the
  experiment). Same semantics as the Python engine (breach-before-confirm,
  supersede, room re-check, confirm-bar close fills).
- **Required before interpreting performance differences:** paste the updated
  file, run it first at **0** (must reproduce the current run exactly), then
  at **1** — trade count and net PnL must match the Python N=1 numbers above
  (249 trades / −1,040.36 on this dataset's window).

## 8. Verdict & decision points

- Selected candidate (N=1) **fails G1 and G2 in both windows**. The
  pre-registered kill criterion ("no Phase-1/2 variant clears OOS test
  PF ≥ 1.2 with net > 0 in both windows") is **met for Change #1**:
  confirmation entry does not rescue this signal family on NEAR 5m.
- No fresh holdout was available (data ends 2026-10-10); the test window was
  previously examined. This strengthens, not weakens, the conservative read.
- **Decision (yours, per the charter):**
  (a) authorise Change #2 (volatility floor) as the next single experiment;
  (b) retire the family for NEAR 5m now;
  (c) **my recommendation:** before any further entry-timing cycle, note the
      §4 finding — the binding constraint is cost-to-R (63.6% break-even).
      The two highest-leverage non-indicator levers are **15m entry TF**
      (1R scales ~1.7× → costs ≈ 0.32R → break-even ≈ 24–27%, and coarser
      noise) and/or **lower-cost execution** (limit/maker fills: fee
      0.10% → 0.04%, slippage ≈ 0 → costs ≈ 0.2R → break-even ≈ 17–20%).
      Both are testable with the existing pipeline, no new indicators.

**Open items:** (1) Pine parity run (user step, §7); (2) fresh holdout data
for any final validation (extended NEAR export past Oct 10, or DJI 5m);
(3) the TV win-count question on the 136-trade run (0 vs Python's 52) —
settled by the same Pine run.
