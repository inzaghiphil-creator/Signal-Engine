# Development cycle — real-data validation (post-V2.0)

> ## ⛔ PROGRAMME CLOSED — 2026-10-12 (charter SIGNAL-ENGINE-NEAR5M-RETIREMENT)
>
> **SCALP and REVERSAL are RETIRED FOR NEAR 5M.** No tested variant
> (160+ candidates: baselines, OOS grids, confirmation-entry windows) passed
> the profitability acceptance gates — best-ever test PF 0.46, best-ever net
> −403.96. **Final research-closure report:
> [`RESEARCH_CLOSURE_REPORT.md`](RESEARCH_CLOSURE_REPORT.md).**
>
> Corrections of record preserved here and in the closure report: (1) the
> ABNORMAL-VOL gate did **not** protect the October grid positions — the
> regime never classified ABNORMAL-VOL during the Oct 7–10 crash; (2) costs
> ARE the dominant PnL component (realised break-even 63.6%, not the nominal
> 41%).
>
> Everything below is the historical development record, retained for the
> evidence trail and for reusing the infrastructure. **No further
> optimisation cycle is open.** 15m-timeframe and limit-order work are
> parked and require separate authorisation to start.
>
> **New workstream (separate charter, authorised 2026-10-13):** the
> grid-window detector for 1h grid timing — `docs/GRID_WINDOW.md`,
> `backtester/grid_window.py`, `pine/grid_window.pine` ("Grid Box Guardian").
> It does not touch the retired signal family.
>
> **Phase 2 + 3 + 3.5 + 3.6 of that workstream (2026-10-13):** long-grid
> START pattern (consolidation → liquidity sweep → reclaim) — 1h ungated,
> 1h with the a-priori 1d-close-above-1d-21-EMA gate (kill rule triggered),
> the 5m variant (4h box), and a one-at-a-time sensitivity analysis of small
> adjustments — shows **no forward edge** over its baselines in any variant,
> and the null is robust to small parameter changes; retired as a start
> signal, kept for stop design + monitoring. `docs/GRID_START_SIGNAL.md`
> (§4.1–§4.3). Live Pine is TF-relative: set box = 24 on 1H, 48 on 5m. One
> candidate awaits a fresh holdout: 1h box=36 (§4.3) — a single
> pre-registered run on a NEAR export past Oct 10, either way.

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

Target file: **NEAR/USDT (Binance spot) 5m OHLCV** — the symbol as charted
in TradingView (the chart's feed is the single source of truth).

- Range: **2026-06-15 00:00 → 2026-10-11 00:00 UTC** (≈32k bars). The
  2026-06-15 start gives ~1500 bars of indicator warmup headroom before the
  2026-07-01 study start; the end captures the Oct 8–9 crash plus recovery.
  The chart must be zoomed/set to this full range before exporting (the
  current 9-day view is not enough).
- Export: TradingView → 5m chart → toolbar **Export chart data → CSV**
  (format already accepted by `backtester.data.load_csv`).
- Save as `data/near_5m_real.csv` (git-ignored — real data stays local).
- **Why TradingView's own export:** item 4 compares Pine vs Python; using the
  same feed for both removes data-source disagreement as a variable.
- **Costs for this symbol:** fee 0.10%/side (Binance spot taker); slippage
  2 minticks = 2 × 0.001 ≈ **0.038%/fill** at ~$5.2 — the CLI resolves this
  automatically from the CSV's price precision (3 dp → tick 0.001).
- Validate first:
  ```bash
  python -m backtester.check_data --csv data/near_5m_real.csv \
      --window 2026-10-08,2026-10-10   # confirm the crash window is present
  ```
  Do not backtest on data that fails the quality gate.

**Delivered 2026-10-11 (deviation from spec, accepted):** the file arrived as a
printed PDF (an exchange CSV rendered through Excel, whose scientific-notation
display truncated the epoch-ms column to ~10^7 ms precision). The exact 5m grid
was reconstructed by fitting original epoch ms to the coarse value pattern — a
unique solution, t₀ = 2026-06-15 00:00:00 UTC, all 33,984 rows verified
(0/33,984 mismatches), so the series is a gap-free 5m grid ending
2026-10-10 23:55 UTC. `check_data` **PASS** (0 missing, 0 dup, 0 OHLC
violations). Residual risk: the exact chart feed (exchange) is unconfirmed —
it only matters for the price-tolerance in step 4's `compare`.

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

## TradingView baseline (real data, first read — 2026-10-11)

SCALP, NEAR/USDT (Binance) 5m, **Sep 21 → Oct 11 2026**, 10k USDT,
fee 0.10%/side, slip 2 ticks:

| Metric | Value |
|---|---|
| Net profit | **−661.38 USDT (−6.6%)** |
| Trades | 13 |
| Wins | **0 (0.00%)** |
| Max DD | 661.38 (never recovered) |
| Regime at entry | ~10 TRENDING DOWN · ~3 RANGING · **0 ABNORMAL VOL** |
| Current state | FLAT, 45m NEUTRAL / RANGING, scores ≈1.7/5.2 (thr 80) |

**File verification (2026-10-11):** the fixed v2.1 script (hardcoded mechanics,
typed `f_json`, v6-safe `na()`/`max_drawdown`/`strategy.cancel` forms) compiles
in TradingView and **reproduces this baseline exactly** on the same window —
13 trades, 0 wins, −661.38, max DD 661.38. The file reconciliation is verified
end-to-end. All 13 trades fall inside the Oct 8–11 crash week; zero entries
Sep 21–Oct 8. REVERSAL mode, same window: 0 wins / 12 trades, −339.99 (thr 70).

**Independent market corroboration (user's KuCoin grid history, Sep 24–Oct 12):**
NEAR/USDT fell from ~5.4 to ~4.3 overnight Oct 8–9 (~20%) and recovered to
~5.5 by Oct 11 — the exact window of all 13 baseline trades. In that move four
leveraged margin grids lost −4,544 USDT (stopped 10/09 01:50–02:07, ranges
4.9–5.7 broken down). Grid portfolio over the period: −2,169 USDT net; NEAR
chop-profit excluding the crash cluster was +1,968 USDT.

*Running script:* `SIGENG1` — same signal logic as
`pine/signal_engine_strategy.pine`, strategy mechanics hardcoded (10k capital ·
10% sizing · 0.1%/side fee · 2-tick slippage — identical to the input defaults),
with `ta.tr(true)` in `f_pack_mom`. The repo strategy file now matches this
running file, so the baseline stays directly comparable to the Python
backtester.

**Why the repo-only strategy variant was rejected by TradingView (root cause,
confirmed 2026-10-11):** Pine v6 `strategy()` requires **const** literals for
`initial_capital`, `default_qty_value`, `commission_value`, `slippage` —
`input.*` values are illegal there (set them in Strategy Properties instead).
The rejected build also carried four more v6 compile errors, now fixed in
**both** pine files: `na()` on a bool (`eMrDnE`/`eSDnE`),
`strategy.max_drawdown` called as a function (it is a variable; value is in
USDT, not %), `strategy.cancel(id, order_type)` (v6 accepts one argument —
the order ID only, CE10115), and an untyped `f_json(...)` receiving untyped
`na` arguments (CE10189) — the header is now explicitly typed. The indicator file had the
same latent bugs (it had never been compiled in TV) plus an `sE5dS`
divergence — it checked EMA55-falling where the strategy and the Python
backtester check EMA21-falling; now synced to EMA21-falling (spec updated to
match). Open design question for the diagnosis phase — NOT a model change now:
the long/short EMA-trend asymmetry (long = EMA55 rising, short = EMA21
falling).

Reading (CONFIRMED by the real-data diagnosis — see "Real-data verdict"
below; kept as the original hypothesis):

- The **ABNORMAL-VOL gate "did its job"** — CORRECTION (2026-10-12, see the
  Confirmation-Entry report §6): the Oct 8–9 crash was **never classified
  ABNORMAL-VOL** (last ABN episode: Sep 23 15:30–17:55Z; 207 ABN bars = 0.61%
  of the dataset). The strategy traded freely on Oct 8 (9 entries, 5 TARGET
  exits). "0 ABNORMAL-VOL trades" describes a dormant gate, not blocking.
- Every trade lost ≈1R + costs (exits ≈ −175…−180 USDT on a ~10% position),
  i.e. the entries are firing at score ≥ 80 but **not developing** — the
  leading suspects are NOISE STOP (no follow-through) and FAILED BREAKOUT
  (worked, then gave it back), concentrated in the downtrend before the
  crash and in the range.
- 13 trades / 3 weeks is *sparse* vs the synthetic ~9/day — real-data gates
  are filtering hard (or ATR/room are sized differently at ~$5). Both
  questions are answered by the data, not by tweaking.

**Discipline:** no model changes until `diagnose` + `oos` on the CSV say
what to change. This baseline is the "before" for everything after.

## Real-data verdict (2026-10-11) — diagnosis + OOS complete

**SCALP (thr 80 — the running config), full data Jun 15 → Oct 10:**
794 trades · win 32.6% · **PF 0.28 · net −3,082.54** · max DD −31.0%.
Per-month PF never nears 1: **0.19 / 0.19 / 0.13 / 0.43 / 0.43** (Jun–Oct).
Taxonomy: **NOISE STOP = 58% of losing PnL** (312 trades, avg MFE 0.05R,
avg 2.6 bars — entries never develop); FAILED BREAKOUT 9% (avg MFE 0.89R);
developed stops 26%. Cost sensitivity: still negative at zero cost
(−663.40, PF 0.75) — CORRECTION (2026-10-12): costs ARE the dominant PnL
component (zero-cost −663 vs actual −3,083 ⇒ costs ≈ 78% of the loss,
≈0.55R per round trip at this ATR scale; realised break-even win rate is
**63.6%**, not the nominal 41% — see Confirmation-Entry report §4).
ABNORMAL-VOL regime: **0 trades** — CORRECTION (2026-10-12):
this is *not* evidence of gate action; the regime never once classified
ABNORMAL-VOL during the crash (last episode Sep 23). See Confirmation-Entry
report §6.

**REVERSAL (thr 70), same data:** 914 trades · win 40% · **PF 0.27 ·
net −3,159.30**; per-month PF 0.13–0.45; same NOISE STOP pathology (54% of
losing PnL).

**OOS (train → 2026-08-31, test 2026-08-31 → 10-10, single pass):**
- SCALP grid (thr 75/80/85 × stop × target × room = 81): every top-5
  candidate negative in **both** windows. Best (by train): thr 85 →
  train −973.60 (PF 0.29), test −940.83 (PF 0.41).
  Gates: net>0 **FAIL/FAIL** · PF>1.2 **FAIL/FAIL** · DD>−15% pass/pass.
- REVERSAL grid (65/70/75): best thr 75 → train −599.34 (PF 0.41),
  test −403.96 (PF 0.46). Gates: net>0 **FAIL/FAIL** · PF>1.2 **FAIL/FAIL**.
- Scalp test chunks all negative and degrading over time (PF 0.45 → 0.60 →
  0.34 → 0.24).

**Verdict: the existing signal family — both modes, within their parameter
ranges — has no real-data edge on NEAR 5m in this period.** The 13-trade TV
baseline (−661.38) was not a crash-week fluke; it is a small sample of a
system that loses money in every month of the dataset. What is broken is
entry *timing*, not parameters: the dominant loss bucket is NOISE STOP
(score ≥ 80 fires, price never develops, stopped in ~13 minutes). The next
workstream must change **when the system takes a trade** (development
confirmation / entry-timing gate) — not ATR multipliers or thresholds.
Held pending user decision per the "no indicators or complexity yet"
directive.

**Open (blocks the final comparison):** TV **List of Trades** (13 rows).
Preliminary mismatch to explain in `compare`: the Python engine on the full
CSV fires **139 trades Sep 21 → Oct 11** (28 of them Oct 7–11) vs the 13 the
TV tester produced — candidates: TV chart data-start / indicator warmup,
chart feed, or a config difference.

## Confirmation-entry experiment results (2026-10-12) — Change #1: RETIRED

Full report: `docs/CONFIRMATION_ENTRY_EXPERIMENT.md`. Charter: pre-registered
selection on train (< 2026-08-31) only, test touched once, baseline
immutable (flag 0 = value-identical engine output, verified).

| N | Trades | Win % | PF | Net | Train net (PF) | Test net (PF) |
|---|---|---|---|---|---|---|
| 0 | 794 | 32.6 | 0.28 | −3,082.54 | −2,066.82 (0.16) | −1,015.72 (0.43) |
| **1 ← selected** | **249** | **35.7** | **0.32** | **−1,040.36** | **−598.10 (0.20)** | **−442.26 (0.44)** |
| 2 | 296 | 34.8 | 0.31 | −1,252.85 | −750.50 (0.18) | −502.35 (0.45) |
| 3 | 311 | 34.1 | 0.30 | −1,350.60 | −828.78 (0.17) | −521.83 (0.44) |

- **Gates (N=1): G1 net>0 FAIL/FAIL · G2 PF>1.2 FAIL/FAIL · G3 DD pass.**
  Kill criterion for Change #1 met.
- **Frequency vs selection:** Δnet +2,042 = +2,116 frequency + −74 selection.
  The improvement is ~100% from trading less; per-trade selection is neutral-
  to-negative.
- NOISE STOP: 312/−2,535 → 87/−864 (N=1) — still the dominant loss bucket.
- The confirmation delay itself costs ~0.23% of price per entry (≈85% of a
  round-trip cost).
- **Realised break-even: 63.6%** (actual 32.6%) — the system needs to more
  than double its win rate just to break even; no entry-timing filter tested
  comes close.
- **Grid-exposure challenge (answered negative):** the 4 crash-killer margin
  grids all started with regime RANGING (×3) / TRENDING DOWN (×1); ABNORMAL-
  VOL was 0% in every window and never triggered 10/07–10/10 (last episode
  Sep 23). A regime-gated entry rule would have blocked **none** of them —
  and regime gating cannot protect held grid inventory at all. The earlier
  "gate did its job" claim is withdrawn (see corrections above).

**Decision point (user):** (a) authorise Change #2 (volatility floor) as the
next single experiment; (b) retire the family for NEAR 5m; (c) recommended —
address the cost-to-R binding constraint first (15m entry TF and/or
limit-order execution, both testable with the existing pipeline, no new
indicators). **No further experiment may start without explicit
authorisation.**

Pine: `pine/signal_engine_strategy.pine` now has `inConfirmBars` (default 0
= exact baseline; 1 = this experiment). **Parity run required before
interpreting any TV difference:** run at 0 (must match the existing TV
baseline), then at 1 (must match Python: 249 trades / −1,040.36 on this
data's window).

## Next cycle plan (post-verdict, 2026-10-12) — SUPERSEDED by retirement

> **Note (closure 2026-10-12):** this plan was the proposed follow-on. The
> programme was retired instead (charter SIGNAL-ENGINE-NEAR5M-RETIREMENT),
> before Phase 1 change #2 or Phase 2 could start. Retained below as the
> historical decision record. See the closure banner above and
> `RESEARCH_CLOSURE_REPORT.md`.

Context: diagnosis + OOS verdict = the current signal family has **no edge on
NEAR 5m** (both modes, every month, all 162 OOS candidates). Per the
interpretation discipline ("fix the *dominant* failure bucket first, one at a
time, and re-run OOS"), the next cycle attacks the measured failure —
**NOISE STOP** (58% of scalp losing PnL: entries that never develop, stopped
in ~2.6 bars) — without adding new indicators.

Break-even math: nominal 1.5R:1 + ~0.3% round-trip ⇒ ≈41% — but the
realised calculation (from actual winners/losers, corrected 2026-10-12)
gives **63.6%**, because costs consume ~0.55R and 5m targets rarely reach
1.5R. Actual: 32.6% (full run). Entry timing must close a 31-point gap —
and any timing improvement pays its own price drag. (See the experiment
results below: it could not.)

**Phase 1 — entry-timing changes (one at a time; all reuse existing fields):**

1. **Confirmation entry (primary candidate)** — ✅ TESTED 2026-10-12, **RETIRED**
   (no variant cleared the gates; improvement was frequency-driven; see
   results section above). Implemented in both engines (`Mechanics.confirm_bars`
   / Pine `inConfirmBars`); kept in the codebase, default 0 = baseline.
2. **Volatility floor:** ATR% at entry ≥ dataset 25th percentile (kills the
   Q1 chop entries: 199 trades, PF 0.04). **Requires separate authorisation
   per the 2026-10-12 charter.**
3. **Directional conditioning** if the slices warrant it (longs PF 0.33 vs
   shorts 0.17; TRENDING-UP 5m entries carry most of the loss).

**Phase 2 — timeframe:** re-test the best Phase-1 variant with 15m entry TF
(same indicators, coarser noise, ~⅓ the cost drag). One flag, no new logic.

**Phase 3 — validation & deployment:**

- Every variant: Python + Pine in lockstep → `diagnose` → single-pass OOS
  → G1–G4 gates → TV comparison (aggregate + trade list).
- Holdout caveat: the Jun 15 → Oct 10 test window has now been peeked at, so
  variant iteration on it carries overfit risk — keep the variant grid small
  and the selection rule pre-registered (train-only ranking, test touched
  once). A truly fresh holdout should come from extended data: a re-export of
  NEAR 5m past Oct 10 when convenient, or DJI 5m data (the user is now
  charting it) as an out-of-market check.
- **Kill switch:** if no Phase-1/2 variant clears OOS test PF ≥ 1.2 with net
  > 0 in both windows, the family is retired for this market/TF. The
  infrastructure (backtester, OOS protocol, Pine↔Python parity, cost model,
  the ABNORMAL-VOL gate that sat flat through the user's −4,544 crash window)
  is retained and reusable — on other instruments/TFs or for the grid
  workstream. No open-ended parameter cycles beyond that.

Open parity item: TV win count on the 136-trade NEAR run (0 vs Python's 52).
Aggregate PnL already matches (−573.85 vs −490.79; 136 vs 139 trades;
Binance feed confirmed; all-default settings confirmed from the param strip).
Settle via the native Strategy Tester's List of Trades or a close-up of the
NEAR stats table when convenient.

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

- [x] Strategy compiles and runs on TradingView (screenshot 2026-10-11):
      "NEARUSDT SIGNAL ENGINE STRATEGY", SCALP, 5m, range **Sep 21 → Oct 11,
      2026**, 10k USDT, fee 0.10% · slip 2tk — tester status OK.
      (The earlier screenshot with triangle markers was a *different*
      indicator — not ours.) The tester header read "v1.0" due to stale
      version labels in the Pine files (fixed → "v2.1"; re-paste the files
      when convenient).
- [x] Real data file in place + `check_data` PASS (crash window confirmed;
      delivered as PDF, grid reconstructed + verified — see item 1 note)
- [x] `diagnose` run + dominant failure bucket identified (per mode)
      → NOISE STOP dominant in both (58% / 54% of losing PnL)
- [x] `oos` single-pass result per mode, gates evaluated
      → both modes FAIL net>0 and PF>1.2 in train AND test
- [x] Gate table filled with real numbers → **no-go on paper trading**
      (verdict section above; both modes)
- [ ] TradingView compile clean; `compare` verdict = MATCH
      (blocked on the user's List of Trades; 139-vs-13 trade-count gap
      to explain — see verdict section)
- [ ] REVERSAL keep/fix/retire decision (diagnosis now in: no edge in this
      window either — decision is the user's)
