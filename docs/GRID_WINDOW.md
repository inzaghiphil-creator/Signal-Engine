# Grid-Window Detector — Charter & Results (2026-10-13)

**Charter:** SIGNAL-ENGINE-GRID-WINDOW-DETECTOR · Lifecycle EXECUTION (research) ·
**Authorised 2026-10-13** (user: "lets do it, make something special" — the
follow-on to the 1h-chart indicator discussion).

**Scope.** A separate workstream from the RETIRED NEAR 5m signal family
(closed under SIGNAL-ENGINE-NEAR5M-RETIREMENT; that closure is untouched).
Objective: for a grid operator, detect **grid-friendly range windows on the
1h timeframe** and — more importantly — the **box state** (how much adverse
move the current box can absorb, and when it breaks). No trading authority;
signals/alerts/monitoring only; no order execution anywhere.

**Rules honoured.** Parameters frozen (pre-registered) *before* scoring;
single run; no tuning against anchor outcomes; no changes to the retired
signal logic; 15m / limit-order programmes NOT started (still parked,
separate authorisation required).

## 1. Data & method

- `data/near_5m_real.csv` — 33,984 Binance NEARUSDT 5m bars, 2026-06-15 →
  2026-10-10 23:55 UTC (re-extracted from the user's Drive PDF after the
  workspace restart; verified: 33,984 rows, endpoints exact, every displayed
  PDF epoch within its 10-second rounding bound of the reconstructed
  timeline, `check_data` PASS, baseline 794/−3,082.54 and CB1 249/−1,040.36
  reproduce exactly).
- Resampled to 1h (2,832 bars). Context: NEAR traded ~2.4 (Jun) → 1.6 (Aug)
  → 5.0 (late Sep) → 5.9 (Oct 13): a tripling market; the grid's window
  (Sep 25 → Oct 12) sits in the high-price phase. The user's 1h chart window
  (Oct 3–13) shows the bots' 4.9–5.7 box (Oct 3–7), the Oct 8 crash, and the
  post-crash box.
- **Python:** `backtester/grid_window.py` — features, state machine, window
  log, cushion, forward hazard, box-break hazard, anchor scoring.
- **Pine:** `pine/grid_window.pine` — "Grid Box Guardian v1": live box
  drawing, state + cushion table, window journal, **BTC tripwire** via
  `request.security` (last confirmed BTC bar), 2σ markers, alerts
  (DEPLOY_OK / HARD_EXIT / SOFT_EXIT_BTC / SIGMA_BAR) + webhook JSON.
  Static-review parity with the Python state machine (same precedence,
  same [1] non-repainting convention, same windowing); TV compile is a
  user step.

### Pre-registered parameters (frozen before scoring)

| Param | Value | Meaning |
|---|---|---|
| Donchian | 20 × 1h | box = last 20 completed bars |
| ATR / ADX | Wilder 14 | strength / trend |
| ADX ceiling | 22 | deploy ceiling |
| Sigma bar | range ≥ 2.0 × ATR | the crash-bar detector |
| Volume surge | ≥ 2.0 × SMA20 | confidence layer |
| Recontain | 3 bars | bars inside before re-settling |
| BB coil | (20, 2.0) width rank ≤ 10th pctile of trailing 720 | squeeze veto |
| Sigma lookback | 24 bars | "don't trust the calm" |

State machine: `EXPOSED_UP/DN` (close beyond box edge) → `BREAK_SIG`
(2σ inside) → `SETTLING` (<3 bars re-contained) → `COILED` → `TRENDING`
(ADX ≥ 22) → `CALM_SIG` (recent 2σ) → `DEPLOYABLE`.

## 2. Results (single run, pre-registered params)

**State distribution (2,832 bars):** TRENDING 36.2% · CALM_SIG 15.3% ·
SETTLING 13.3% · DEPLOYABLE 13.0% · COILED 11.0% · EXPOSED_UP 6.0% ·
EXPOSED_DN 4.0% · BREAK_SIG 1.3%.

**Cushion — the headline gauge.** In-box bars, distance from close to the
nearest box edge (ATR units): p10 0.34 · p25 0.68 · **p50 1.10** · p75 1.54 ·
p90 1.97. 44.2% of in-box bars have cushion ≤ 1 ATR; 90.9% ≤ 2 ATR. A 20h
box on 1h NEAR is typically a ~1–2 ATR walk from each edge.

**Forward hazard (the decision number):**

| Starting cushion | n bars | break or 2σ bar within 6h | within 24h |
|---|---|---|---|
| ≤ 1 ATR | 1,118 | **49.4%** | 90.9% |
| > 2 ATR | 230 | **14.8%** | 98.3% |

Price within one ATR of a box edge is a **coin-flip (49%) that the box
breaks within 6 hours**; >2 ATR out it's 3.3× safer. (The ~91–98% 24h
column is mostly tautology — a 20h box expires within 24h — the 6h column
is the actionable one.)

**Box-break hazard (94 boxes ≥ 6h):** 62 exited DOWN, median width 5.0 ATR,
**median adverse carry −3.6%, worst −12.1%**. At 7× leverage, a −3.6%
adverse carry is −25% of margin; −12% is ~−84% — liquidation territory.
Largest single-box adverse carries: Sep 21 −17.4% (UP box, short-side
carry), Aug 22 −12.1%, Sep 11 −12.0%, Sep 23 −11.8%.

**Crash anchors — what the detector said at the four margin-grid starts:**

| Bot | Start (UTC) | State @ start | ADX | Deploy? | 1st hard exit | Min px 24h |
|---|---|---|---|---|---|---|
| margin-925 | 10/08 08:58 | DEPLOYABLE | 20.1 | YES | +4.0h | −17.5% |
| margin-1500 | 10/08 09:09 | DEPLOYABLE | 19.1 | YES | +3.9h | −17.2% |
| margin-2050 | 10/08 10:03 | DEPLOYABLE | 17.7 | YES | +3.0h | −18.9% |
| margin-1000 | 10/08 14:55 | EXPOSED_DN | 17.4 | no | +0.1h | −14.1% |

Timeline detail: the box broke **UP** on Oct 7 18:00–20:00 (fakeout to
5.41), settled, then slid all morning of Oct 8 (channel position 0.84 →
0.10, ADX staying 14–20). The first hard-exit flip — **EXPOSED_DN at
Oct 8 13:00 (close 4.998)** — came ~2h before the 15:00 crash bar and
**~14% above the final low (4.30)**. The last bot (14:55) started after
that flip and was flagged "no" — the only one the detector declined.

**2σ census:** 86 of 2,832 1h bars (3.0%) with range ≥ 2×ATR; 65/86 with
volume-spike confirmation. Worst forward-24h carries from the bar low:
Aug 22 −13.6%, Sep 23 −8.5%, Jul 27 −8.5%. Oct 8 15:00 crash bar flagged
with vol-spike (forward −6.9% from its own low). Note: ATR self-adapts
*within* a crash cluster (only the first cluster bar flags) — the same
self-normalising weakness as the retired ABN-VOL gate, but the first-bar
flag is the actionable one.

**Known good boxes (deployable share):** pre-crash box Oct 3–7: 3%
(50/109 bars TRENDING); post-crash box Oct 9–10: 15%. The detector's
DEPLOYABLE state is rare on this dataset (13% overall) — see limitations.

## 3. Verdict

1. **The start-side filter cannot prevent a flash crash.** Three of the
   four fatal grids started while the 1h detector said DEPLOYABLE (ADX
   17–20, price inside the box). A 2-day grind from 5.6 → 5.0 looks like a
   calm box to trend-strength measures; the 15:00 crash bar was a genuine
   surprise on the 1h timeframe. This is the same lesson as the retirement
   study, confirmed from the grid side: **the value of timing tools is on
   the END side, not the START side.**
2. **The end-side signal is usable, with an honest size.** The 13:00
   EXPOSED_DN flip gave ~2h warning before the crash bar and ~14% of
   price-cushion above the final low — enough for a *human* (or a
   de-risking rule) to act, but for a margin grid whose stop sits at the
   box edge it fires at roughly the same moment the exchange stop does.
   It is an exit *alert*, not a substitute for the stop.
3. **The genuinely new number is the cushion hazard:** ≤1 ATR of edge
   cushion ⇒ 49% chance of a break within 6h. That is the quantity to
   watch while a grid runs, and it's what the Pine tool displays live.
4. **The BTC tripwire is the leading leg.** From the user's BTC 1h chart:
   BTC held an 82–88 box for ~2 weeks and broke it down into the Oct 8–9
   window — NEAR's crash followed its market leader. The Python scorer has
   no BTC data in-repo (N/A leg); the Pine indicator carries it via
   `request.security`.

## 4. Known limitations

- **Single market, 4 months, tripling trend.** The ADX-22 deploy ceiling
  was pre-registered for "quiet range" and is miscalibrated for a market
  that nearly tripled (TRENDING 36% of bars; the profitable grid period
  was an uptrend, which the detector mostly flags TRENDING). A calibration
  pass is a *separate* follow-up — not done here (charter discipline).
- **BTC leg absent from Python scoring** (no BTC data in repo); Pine only.
- **No funding/OI overlay** (exchange-side data; the user can eyeball it —
  it is not in the detector).
- **Anchors are partial:** the 100-bot per-day PnL table was lost in the
  workspace restart; scoring uses the four documented grid starts, the two
  chart boxes, and the full window log.
- **Pine warmup:** Wilder-seed differences between Pine and pandas can
  shift ADX/ATR in the first ~14 bars; states from bar ~40 on are
  comparable. TV compile/parity run is the user step.

## 5. Outstanding (user steps, no new cycle implied)

1. **TV compile + run `pine/grid_window.pine`** on the KuCoin 1h chart
   (set the BTC tripwire symbol to the feed's BTC pair, e.g. `KOIN:BTCUSDT`).
2. **BTC 1h CSV export** (KuCoin or Binance, Jun 15 → Oct 13) to add the
   tripwire leg to the Python scorer.
3. Optionally, a **per-day grid PnL re-export** to score windows against
   actual grid PnL instead of anchors.

## 6. Reusable components

| Component | Path |
|---|---|
| Python detector (state machine, cushion, hazard, window log, anchors) | `backtester/grid_window.py` (CLI: `python -m backtester.grid_window --csv <ohlcv>`) |
| Pine chart tool (box, table, journal, BTC tripwire, alerts) | `pine/grid_window.pine` |
| Pinned state-machine tests | `tests/test_grid_window.py` (6 tests, all passing) |
| Full run report | regenerated via the CLI (last run: `2026-10-13`) |

**Discipline:** no signal-logic changes to the retired family; no new
optimisation cycle started beyond this single pre-registered run; no 15m or
limit-order programme started. End of report.
