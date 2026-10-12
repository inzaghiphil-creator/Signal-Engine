# Long-Grid Start Signal — Consolidation → Liquidity Sweep → Reclaim
## Charter & Results (2026-10-13, Phases 2–3 of the grid-window workstream)

**Status (end of Phase 3.6, 2026-10-13):** the pattern — 1h ungated (§2),
1h with the a-priori uptrend gate (§4.1, kill rule triggered), the 5m
variant (§4.2), and a one-at-a-time sensitivity analysis of small
adjustments (§4.3) — shows **no forward edge over its baseline in any
variant**; the null is robust to small parameter changes. The pattern is
**retired as a mechanical start signal**; it is kept for its **stop design**
(the sweep-low invalidation — which did its job on Oct 8) and as a
**monitoring trigger** in the live Pine (watchlist, not a start signal).
Live Pine: `pine/grid_window.pine` (LONG GRID box/reclaim/cooldown are
inputs; set box = 48 on a 5m chart, 24 on 1h; the 1d gate is displayed as
context). One pre-registered candidate awaits fresh data: 1h box=36 (§4.3).

**Charter:** SIGNAL-ENGINE-GRID-WINDOW-DETECTOR, Phase 2 — user-directed
refinement, 2026-10-13.

**Priority reset (user, 2026-10-13).** The programme's primary aim is to
find the **key data that is a strong indication to START a LONG GRID**;
loss avoidance (crash / market-beta factors) is a **secondary** filter. The
user also corrected the record: the Oct 8 crash "wasn't as big a problem as
it was made out — external factors contributed" (corroborated by the BTC
1h chart: the market leader broke its own box into the same window — part
of that event was beta, not a NEAR-specific signal failure). The crash
material in `GRID_WINDOW.md` is repositioned as a known-risk appendix.

## 1. The pattern (user's description, made precise, PRE-REGISTERED)

> "After a period of consolidation we see a tell-tale liquidity sweep
> down; when the price comes back up through the consolidation area,
> that's when I would look to start a long grid."

Frozen before scoring (single run, no tuning against outcomes):

| Step | Definition (1h bars) |
|---|---|
| **Consolidation** | last 24 completed bars form a box: width 2.0–8.0×ATR, net drift ≤ 1.5×ATR, ADX(14) ≤ 25 |
| **Liquidity sweep** | next bar's **low** breaches the box low (first breach), depth ≤ 1.5×ATR — a sweep, not a collapse |
| **Reclaim** | within 12 bars a close returns into the box; **no close above the box top in between** (breakout-in-between = different pattern) |
| **Signal** | reclaim bar; entry = its close |
| **Stop / invalidation** | the **sweep low** — a close back below it voids the setup |
| **Suggested grid** | long grid from just above the stop up to the box top |
| Cooldown / horizon | 48h between setups; scored forward 96h |

## 2. Results (single pre-registered run, 2,832 1h bars, Jun 15 → Oct 10 2026)

**18 setups** (~1.1/week). Forward 96h vs a baseline of 400 random
qualifying boxes with no sweep:

| Metric | Setups (n=18) | Baseline (n=393) | Δ |
|---|---|---|---|
| +1×ATR reached in 96h | 83.3% | 86.0% | −2.7pp |
| +2×ATR reached in 96h | 72.2% | 77.2% | −5.0pp |
| Invalidation (close < stop) | 88.9% | 89.5% | −0.6pp |
| MFE median | +7.48% | +7.05% | +0.43pp |
| MAE median | −6.03% | −5.35% | −0.68pp |
| Closes above box low (96h) | 52% | 69% | — |
| Close @ 96h median | −0.68% | (n/r) | — |

**Verdict: as specified, the pattern shows no measurable edge over an
uneventful qualifying box in this sample.** Every delta is inside noise,
and n=18 is underpowered to reject "no effect" either. This is a null
result, reported as such.

### What the detail table shows (diagnostic — single-run observations, NOT validated)

- **Time structure:** rally-phase setups (Aug 15 → Oct 10, n=9): MFE median
  **+13.5%**, close@96 **+5.9%**. Pre-rally (Jun 15 → Aug 14, n=9): MFE
  **+4.1%**, close@96 **−2.5%**. Directionally consistent with the
  long-grid-in-an-up-market intuition — but n=9/9 is a hypothesis, not a
  finding. (The 1h 200-EMA split went the *other* way, n=7/10 — not
  credible; do not fit to it.)
- **Best setup in the sample:** 2026-09-23 16:00 — consolidation 4.23–4.81,
  sweep to 4.150, reclaim close 4.318. MFE **+27.4%**, **never
  invalidated**, 98% of closes above the box, close@96 **+19.7%**. Textbook
  instance of the pattern in a trending market.
- **The Oct 8 crash setup (2026-10-08 13:00):** sweep to 4.899, reclaim
  4.998, stop 4.899. Invalidation fired **2h later** (15:00 close 4.633,
  **−7.3%**), before the final low of 4.301 (−13.9%) — the sweep-low stop
  **avoided roughly half the worst case** during the one genuine beta event
  in the sample. The pattern's risk design did its job even on its worst
  call.
- **Worst call:** 2026-10-01 10:00 — invalidated in 3h, −2.3% @ 96h.
  Bounded, as designed.

Full 18-setup table: `python -m backtester.grid_start --csv data/near_5m_real.csv`.

## 3. What this means

1. **The pattern is not (yet) a "strong indication" by itself** on NEAR 1h,
   Jun→Oct 2026. Do not size a long grid on it alone.
2. **Its stop design is the part that worked**: sweep-low invalidation
   capped the only beta-event setup at −7.3% vs −13.9% worst case. Keep
   that as the risk contract for any long grid entered from this pattern.
3. **Frequency is the practical bottleneck:** 18 setups in 4 months is too
   few to validate the edge question either way. The pattern needs more
   history (or the same detection on more 1h alts) before a go/retire
   call is honest.
4. **Directional context is the live hypothesis** (rally-phase setups
   outperform 3:1 on MFE median, n=9/9) — but it must be tested
   pre-registered, not fitted.

## 4. Proposed next step — REQUIRES AUTHORISATION (one pre-registered run)

Same pattern, plus one long-context gate chosen **a priori for a long grid**
(not fitted to the sample): **1d close above the 1d 21-EMA** (market in an
uptrend), with **≥ 6 months of NEAR 1h history** (user export) to reach
n ≥ ~40 setups. Scored identically (96h horizon, same baseline construction).
Kill rule: if the gated variant still shows no MFE lift over its own
baseline, the pattern is retired as a start signal (kept only for its stop
design / monitoring value).

**Open data asks (user):** (1) NEAR 1h (or 5m resample) from ~Apr 2026 →
present; (2) optional: 2–3 other high-beta alt 1h series for cross-market
checks; (3) BTC 1h (already requested in Phase 1) for the beta leg.

## 4.1 Phase 3 — long-context gate run (authorised 2026-10-13, run 2026-10-13)

**Design (pre-registered before the run):**

- Gate: **1d close above the 1d 21-EMA** (a priori; what a live 1d chart
  shows intraday), evaluated at the **signal bar** (the reclaim close = the
  entry bar). ≥21 daily bars required before the EMA is trusted, else the
  gate fails (conservative).
- If the reclaim close is in the box but the gate is off, the setup is
  **consumed and rejected** (the entry moment has passed; no re-evaluation
  on later bars). A dropped setup does not hold the cooldown.
- Baseline: same construction as Phase 2 (random qualifying boxes, no
  sweep), restricted to **gate-passing bars** — the gated variant's own
  baseline. Same seed, same 96h horizon.
- Kill rule (as pre-registered): *if the gated variant still shows no MFE
  lift over its own baseline, the pattern is retired as a start signal
  (kept only for its stop design / monitoring value).*

**Run caveat (honesty note):** the pre-registration specified ≥6 months of
history (n ≥ ~40 setups); only 4 months (2,832 1h bars) is on file, so this
is an **early feasibility run on partial data** — n=10 gated setups,
underpowered in both directions. The formal pre-registered run remains the
user's 6-month export. The kill-rule verdict below is on this evidence.

**Results (single run, params frozen):**

| | Setups ungated (n=18) | **Setups gated (n=10)** | **Gated baseline (n=256)** |
|---|---|---|---|
| MFE median 96h | +7.48% | **+8.24%** | **+14.35%** |
| +1 ATR reached | 83.3% | 90.0% | 89.5% |
| +2 ATR reached | 72.2% | 70.0% | 83.2% |
| Invalidation (close < sweep low) | 88.9% | 90.0% | 84.4% |
| Closes above box low (median share) | 52% | 35% | 78% |
| close@96h median | −0.68% | −0.88% | — |

Gate behaviour: 10 of 18 ungated setups passed; all 9 dropped ones are
Jun 17 – Aug 18 (the pre-rally chop — exactly where an uptrend gate should
cut). One **gated-only** setup (2026-07-07) appeared because the dropped
07-05 setup did not hold the cooldown window.

**Reading:** the gate works as designed — it selects uptrend periods, and
the gated baseline's +14.35% MFE median *is* the uptrend drift (a random
box in an uptrend drifts up over 96h). The pattern adds **no increment on
top of trend context**: gated setups −6.11pp MFE vs their own baseline,
−13.2pp on +2 ATR, worse invalidation, and price spends most of the 96h
*below* the box (35% vs 78%).

**Verdict — KILL RULE TRIGGERED (on this evidence):** no MFE lift over the
gated variant's own baseline. Per the pre-registration, the pattern is
**retired as a START SIGNAL**. Kept for: (1) its **stop design** — the
sweep-low invalidation, which capped the Oct 8 loss at −7.3% ~2h in, before
the −13.9% final low; and (2) **monitoring** — the Pine LONG GRID SETUP
alert remains as a watchlist trigger (consolidation + stop-hunt + reclaim
happened, with the uptrend gate displayed), not as an authorisation to
start a grid.

**Residual uncertainty / user decision point:** n=10, single run, partial
history — underpowered either way. If a 6-month NEAR export (or 2–3
high-beta alts) is supplied, one final pre-registered run (same gate, same
kill rule, n ≥ ~40) settles it formally; otherwise close the workstream and
retain the stop-design + monitoring value.

Reproduce: `python -m backtester.grid_start --csv data/near_5m_real.csv --gate`

## 4.2 Phase 3.5 — 5m variant (authorised 2026-10-13, run 2026-10-13)

**Why:** the user annotated the pattern on a 5m chart (consolidation ~2–4h,
sweep, reclaim — see his chart of the ~22:00 NEAR sweep from ~5.556 back
through the 5.593–5.651 box). The same shape at 5m is a different, faster
phenomenon than the 1h box, so it gets its own pre-registered run.

**Design (pre-registered before the run):**

| Param | 1h (Phase 2) | **5m (this run)** |
|---|---|---|
| Box | 24 bars = 24h | **48 bars = 4h** (top of the ~2–4h consolidation seen on the user's 5m chart) |
| Box shape | w 2–8 ATR, drift ≤1.5 ATR, ADX ≤25 | same, in 5m-ATR units |
| Sweep | first breach, depth ≤1.5 ATR | same |
| Reclaim | ≤12 bars = 12h | **12 bars = 1h**, no breakout in between |
| Cooldown | 48h | 48h (576 bars) |
| Horizon | 96h | 96h (1152 bars) |
| Gate | — | **none** (Phase 3 verdict: test the raw pattern first) |
| Baseline | 400 random qualifying boxes, seed 7 | same (its own baseline) |

Single run, 33,984 gap-free 5m bars, Jun 15 → Oct 10 2026, no tuning.

**Results:**

| | Setups (n=12) | Own baseline (n=400) |
|---|---|---|
| MFE median 96h | **+6.85%** | **+7.76%** |
| +1 ATR reached | 100% | 98.0% |
| +2 ATR reached | 100% | 97.2% |
| Invalidation (close < sweep low, 96h) | 100% | 97.5% |
| Closes above box low (median share) | 54% | 63% |
| close@96h median | −0.50% | — |

**Reading:** the ATR metrics saturate on 5m (a 96h window is ~100× the 5m
ATR, so nearly everything "reaches +1/+2 ATR") — the ATR metrics are
non-discriminative on this TF and the honest comparison is MFE: **−0.91pp
vs own baseline, no lift**, invalidation worse, close@96h ≈ flat. The two
worst setups (Jun 15/22) died within ~1h of entry at the start of the
sample; the two best (Aug 20, Sep 19: +24.8%/+25.3% MFE) are the rally
periods — the same regime dependence seen on 1h.

**Verdict:** no measurable edge on 5m either. **Consolidated verdict across
all three pre-registered runs (1h, 1h+gate, 5m): the pattern is real,
frequent and regime-dependent, but it carries no forward edge over a
qualifying box by itself — retired as a mechanical start signal; retained
for its stop design (sweep-low invalidation) and as a monitoring trigger.**
The 5m Pine (box input = 48 on a 5m chart) marks these setups live as
watchlist items.

Reproduce: `python -m backtester.grid_start --csv data/near_5m_real.csv --tf 5m`

## 4.3 Sensitivity analysis (one-at-a-time, 2026-10-13)

User question: *what small adjustments improve the score?* Answered as a
sensitivity surface, **not** an optimisation (a combinatorial search on a
known-null result manufactures fake edges). Pre-stated rules, frozen before
running:

- ONE parameter changed at a time around the frozen point (14 variants per
  TF, no combinations);
- each variant scored against **its own** baseline (the shape filters define
  the qualifying-box population, so the control group is rebuilt per
  variant; same seed 7, n=400);
- whole surface reported, nothing cherry-picked;
- **credibility rule**: lift ≥ +2.0pp MFE median AND positive +1 ATR lift
  AND n ≥ 8 AND at least one neighbouring variant (same parameter) also
  positive — with ~15 variants per TF, isolated bumps are expected under
  noise; a real direction shows a plateau, not a spike.

Reproduce: `python -m backtester.grid_start_sensitivity --csv data/near_5m_real.csv --tf 1h` (and `--tf 5m`)

**1h surface** (frozen point: box 24 / w 2–8 / drift 1.5 / ADX 25 / depth 1.5 / reclaim 12 / cooldown 48):

| variant | n | MFE med | base | lift | +1 ATR | base | invalid | base |
|---|---|---|---|---|---|---|---|---|
| **frozen** | 18 | +7.48 | +7.05 | **+0.43** | 83.3% | 86.0% | 88.9% | 89.5% |
| box=18 | 18 | +6.62 | +7.24 | −0.62 | 77.8% | 87.0% | 77.8% | 88.2% |
| **box=36** | 16 | +9.76 | +7.29 | **+2.47** | 93.8% | 89.8% | **68.8%** | 92.0% |
| w_max=6 | 18 | +7.48 | +6.86 | +0.62 | 83.3% | 88.0% | 88.9% | 89.0% |
| w_min=3 | 18 | +7.48 | +7.46 | +0.02 | 88.9% | 86.5% | 83.3% | 89.2% |
| drift=1.0 | 16 | +7.76 | +6.80 | +0.96 | 81.2% | 86.5% | 93.8% | 90.2% |
| drift=2.0 | 19 | +7.32 | +7.18 | +0.15 | 84.2% | 88.8% | 89.5% | 89.2% |
| adx=20 | 12 | +7.48 | +7.13 | +0.35 | 83.3% | 88.8% | 91.7% | 91.5% |
| adx=30 | 19 | +7.64 | +7.38 | +0.26 | 84.2% | 88.5% | 84.2% | 89.5% |
| depth=1.0 | 18 | +7.60 | +6.85 | +0.75 | 83.3% | 87.0% | 88.9% | 89.8% |
| depth=2.0 | 18 | +7.48 | +7.05 | +0.43 | 83.3% | 86.0% | 88.9% | 89.5% |
| reclaim=6 | 19 | +7.76 | +7.05 | +0.72 | 84.2% | 87.0% | 89.5% | 89.8% |
| reclaim=18 | 19 | +7.64 | +6.84 | +0.80 | 84.2% | 86.5% | 94.7% | 89.8% |
| cooldown=24 | 29 | +7.32 | +6.86 | +0.46 | 86.2% | 87.2% | 86.2% | 89.5% |
| cooldown=96 | 11 | +7.64 | +7.63 | +0.00 | 81.8% | 88.5% | 90.9% | 90.0% |

**5m surface** (frozen point: box 48 / … / cooldown 576):

| variant | n | MFE med | base | lift | +1 ATR | base | invalid | base |
|---|---|---|---|---|---|---|---|---|
| **frozen** | 12 | +6.85 | +7.76 | **−0.91** | 100% | 98.0% | 100% | 97.5% |
| box=36 | 6* | +8.83 | +7.64 | +1.19 | 100% | 98.5% | 66.7% | 97.2% |
| box=60 | 18 | +7.36 | +7.66 | −0.31 | 94.4% | 98.5% | 100% | 97.5% |
| w_max=6 | 17 | +9.68 | +8.20 | +1.49 | 100% | 98.8% | 94.1% | 97.8% |
| w_min=3 | 12 | +6.85 | +7.74 | −0.89 | 100% | 97.2% | 100% | 97.0% |
| drift=1.0 | 18 | +7.48 | +7.60 | −0.12 | 100% | 97.8% | 100% | 96.0% |
| drift=2.0 | 7* | +5.13 | +7.58 | −2.45 | 100% | 97.8% | 100% | 97.0% |
| adx=20 | 16 | +3.65 | +8.00 | **−4.36** | 100% | 97.2% | 100% | 97.2% |
| adx=30 | 7* | +5.13 | +7.39 | −2.26 | 100% | 98.0% | 100% | 96.5% |
| depth=1.0 | 15 | +8.57 | +7.66 | +0.91 | 100% | 98.0% | 100% | 97.2% |
| depth=2.0 | 12 | +4.40 | +7.77 | −3.37 | 100% | 98.2% | 100% | 97.5% |
| reclaim=6 | 12 | +6.85 | +7.76 | −0.91 | 100% | 98.0% | 100% | 97.5% |
| reclaim=18 | 12 | +6.85 | +7.70 | −0.85 | 100% | 97.8% | 100% | 97.5% |
| cooldown=288 | 37 | +6.74 | +7.71 | −0.97 | 97.3% | 97.8% | 100% | 97.0% |
| cooldown=1152 | 2* | +4.36 | +8.00 | −3.64 | 100% | 98.2% | 100% | 97.5% |

\* n < 8: median of <8 outcomes — not readable.

**Reading:**

1. **The null is robust.** On 5m every lift sits in [−4.4, +1.5]pp with no
   consistent direction (loosening ADX or depth actually hurts). On 1h all
   variants except one sit in [−0.6, +1.0]pp. The frozen point is on a flat
   surface (5m) / a shallow ridge (1h, box dimension) — nothing was badly
   chosen, and nothing nearby is an edge.
2. **One bump: 1h box=36** (+2.47pp, +1 ATR +4.0pp, invalidation 68.8% vs
   92% — the clearest single number on either surface). It technically
   clears the letter of the credibility rule (neighbour box=24 is positive
   at +0.43pp), but the neighbourhood shape is −0.62 / +0.43 / +2.47 — a
   **spike, not a plateau** — and 16/16 of its setups are positive-MFE only
   because 5 of the 16 are the Aug–Sep rally winners (the same regime
   dependence as the frozen set; the Jun–Jul setups are small-MFE
   invalidations). **Not promoted to a finding.**
3. **Practical:** the frozen parameters are as good as any small
   adjustment — do not re-tune the live Pine. The 48h cooldown is doing
   real work (5m cooldown=288 just triples n with no quality change).
4. **Candidate for the next data drop (pre-register, do not test here):**
   1h box=36 vs its own baseline on a FRESH holdout (NEAR 5m/1h export
   past Oct 10). If the +2–4pp lift reproduces out-of-sample it is a lead;
   if not, it was a spike and the file stays closed. One run, either way.

## 5. Components

| Component | Path |
|---|---|
| Pattern detector + scorer (Python, CLI; `--gate` for Phase 3) | `backtester/grid_start.py` |
| Live detector (sweep + reclaim alerts, stop marked) — **watchlist trigger only, not a start signal (Phase 3 verdict)** | `pine/grid_window.pine` — "LONG GRID SETUP" |
| Pinned detection tests (incl. gate) | `tests/test_grid_start.py` |
| 5m CSV recovery from the Drive PDF (post-wipe restore) | `backtester/parse_drive_pdf.py` |

Research/monitoring only — NOT an authorised trade recommendation. No order
execution anywhere. End of report.
