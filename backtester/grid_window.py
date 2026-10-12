"""Grid-window detector — research module.

Charter: SIGNAL-ENGINE-GRID-WINDOW-DETECTOR (authorised 2026-10-13, the
"let's do it" follow-on to the NEAR 5m retirement closure). Scope: detect
grid-friendly RANGE windows on the 1h timeframe and score the detector
against the documented grid anchors (four crash-killer margin-grid starts,
2026-10-08; two known grid-profitable boxes).

STANDALONE by design: it does not touch the retired signal engine
(engine.py/signals.py) and is not part of it. Research/monitoring only —
NOT an authorised trade recommendation.

Pre-registered parameters (frozen BEFORE scoring; no tuning against the
anchor outcomes):

    DONCHIAN      = 20 bars (1h)   channel = last 20 COMPLETED bars
    ADX_LEN       = 14 (Wilder)
    ADX_MAX       = 22.0           deploy ceiling
    SIG_ATR       = 2.0 x ATR(14)  bar range = crash/2-sigma bar
    VOL_LEN/VOL_X = 20, 2.0        volume surge confirmation
    RECONTAIN     = 3 bars         bars inside channel before re-deploy
    BB            = 20 / 2.0       Bollinger width
    BB_RANK_WIN   = 720 (30 d)     trailing window for the width rank
    BB_RANK_MAX   = 0.10           bottom decile = coiled (deploy veto)
    SIG_LOOKBACK  = 24 bars        no 2-sigma bar in the last 24h

State machine (evaluated on COMPLETED 1h bars, close of the bar):

    EXPOSED_UP / EXPOSED_DN : close beyond the 20-bar channel edge
    BREAK_SIG               : inside channel but bar range >= 2 x ATR
    SETTLING                : inside, but fewer than RECONTAIN bars
                              since the last channel exit
    COILED                  : BB width rank in the bottom decile
                              (squeeze — breakout imminent, do not start)
    TRENDING                : ADX >= 22
    DEPLOYABLE              : everything else (inside, quiet, uncoiled,
                              recent, ADX below ceiling)

The BTC tripwire (soft exit) and funding/OI overlays are chart-side tools:
the Pine indicator (pine/grid_window.pine) implements the BTC leg via
request.security; the Python scorer has no BTC data in-repo and reports the
leg as N/A (limitation, see docs/GRID_WINDOW.md).
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .data import load_csv, resample_ohlcv

# ── pre-registered parameters (frozen) ──────────────────────────────────────
DONCHIAN = 20
ADX_LEN = 14
ADX_MAX = 22.0
SIG_ATR = 2.0
VOL_LEN = 20
VOL_X = 2.0
RECONTAIN = 3
BB_LEN = 20
BB_K = 2.0
BB_RANK_WIN = 720
BB_RANK_MINP = 100
BB_RANK_MAX = 0.10
SIG_LOOKBACK = 24

DEPLOYABLE = "DEPLOYABLE"
SETTLING = "SETTLING"
COILED = "COILED"
TRENDING = "TRENDING"
BREAK_SIG = "BREAK_SIG"
CALM_SIG = "CALM_SIG"
EXPOSED_UP = "EXPOSED_UP"
EXPOSED_DN = "EXPOSED_DN"


def _wilder(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(alpha=1.0 / n, adjust=False).mean()


def resample_1h(df5: pd.DataFrame) -> pd.DataFrame:
    """5m (or any base TF) OHLCV -> 1h, open-indexed. The last bucket may be
    partial; callers wanting confirmed bars only should drop the final row
    if it is incomplete."""
    return resample_ohlcv(df5, 3600)


def add_features(df1: pd.DataFrame) -> pd.DataFrame:
    """Compute all detector features on a 1h open-indexed OHLCV frame."""
    h, l, c, v = df1["high"], df1["low"], df1["close"], df1["volume"]

    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = _wilder(tr, ADX_LEN)

    up, dn = h.diff(), -l.diff()
    pdm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df1.index)
    mdm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df1.index)
    pdi = 100.0 * _wilder(pdm, ADX_LEN) / atr
    mdi = 100.0 * _wilder(mdm, ADX_LEN) / atr
    dx = 100.0 * (pdi - mdi).abs() / (pdi + mdi)
    adx = _wilder(dx.fillna(0.0), ADX_LEN)

    up_chan = h.rolling(DONCHIAN).max().shift(1)   # last 20 completed bars
    dn_chan = l.rolling(DONCHIAN).min().shift(1)
    volma = v.rolling(VOL_LEN).mean().shift(1)

    bb_basis = c.rolling(BB_LEN).mean()
    bb_sd = c.rolling(BB_LEN).std(ddof=0)
    bbw = (BB_K * bb_sd / bb_basis) * 2.0          # (upper-lower)/basis
    lo = bbw.rolling(BB_RANK_WIN, min_periods=BB_RANK_MINP).min()
    hi = bbw.rolling(BB_RANK_WIN, min_periods=BB_RANK_MINP).max()
    bbw_rank = (bbw - lo) / (hi - lo)              # 0..1; NaN where undefined

    out = df1.copy()
    out["atr"] = atr
    out["adx"] = adx
    out["pdi"], out["mdi"] = pdi, mdi
    out["up_chan"] = up_chan
    out["dn_chan"] = dn_chan
    out["volma"] = volma
    out["bbw_rank"] = bbw_rank
    return out


def run_states(df1: pd.DataFrame) -> pd.DataFrame:
    """Feature frame (from add_features) -> frame with a `state` column."""
    h, l, c, v = df1["high"], df1["low"], df1["close"], df1["volume"]
    out = df1.copy()

    up_c, dn_c = out["up_chan"], out["dn_chan"]
    inside = (c <= up_c) & (c >= dn_c)
    sig = (h - l) >= SIG_ATR * out["atr"]
    volspike = v >= VOL_X * out["volma"]

    # consecutive-inside run length (recontainment)
    inside_run = inside.groupby((~inside).cumsum()).cumsum()
    recont = inside & (inside_run >= RECONTAIN)

    coiled = out["bbw_rank"].le(BB_RANK_MAX) & out["bbw_rank"].notna()
    sig_recent = sig.rolling(SIG_LOOKBACK, min_periods=1).sum() > 0

    state = pd.Series(np.nan, index=out.index, dtype=object)
    state[c > up_c] = EXPOSED_UP
    state[c < dn_c] = EXPOSED_DN
    state[(state.isna()) & inside & sig] = BREAK_SIG
    state[(state.isna()) & inside & ~recont] = SETTLING
    state[(state.isna()) & inside & recont & coiled] = COILED
    state[(state.isna()) & inside & recont & ~coiled & (out["adx"] >= ADX_MAX)] = TRENDING
    state[(state.isna()) & inside & recont & ~coiled & (out["adx"] < ADX_MAX) & ~sig_recent] = DEPLOYABLE
    state[(state.isna()) & inside & recont & ~coiled & (out["adx"] < ADX_MAX) & sig_recent] = CALM_SIG  # recent 2σ, do not trust the calm

    out["inside"] = inside
    out["sig"] = sig
    out["volspike"] = volspike
    out["recont"] = recont
    out["coiled"] = coiled
    out["state"] = state

    # CUSHION — distance from close to the NEARST channel edge, in ATR units.
    # This is the "how much adverse move can the box absorb" gauge. The core
    # risk number for a grid: a long grid sitting on the box floor lives on
    # the downside cushion, a short grid on the upside cushion.
    atr = out["atr"]
    down_cush = (c - dn_c) / atr
    up_cush = (up_c - c) / atr
    out["cush_down"] = down_cush
    out["cush_up"] = up_cush
    out["cush_near"] = pd.concat([down_cush, up_cush], axis=1).min(axis=1)
    out["box_w_atr"] = (up_c - dn_c) / atr
    return out


def box_hazard(df1: pd.DataFrame, min_hours: int = 6) -> pd.DataFrame:
    """Per-box break hazard: for each grid box (maximal non-EXPOSED run) with
    at least min_hours bars, its width (ATR units) at start, duration, exit
    side, and the worst adverse move from the box start until the exit bar —
    i.e. the distance a grid at the wrong edge of that box would have been
    carried. Aggregated by width bucket below."""
    wins = window_log(df1)
    rows = []
    for w in wins:
        if w.hours < min_hours:
            continue
        i0 = df1.index.get_loc(w.start)
        i1 = df1.index.get_loc(w.end)
        w0 = df1["box_w_atr"].iloc[i0]
        if not (w0 == w0):  # NaN
            continue
        if w.exit == "DOWN":
            adv = float((df1["low"].iloc[i0:i1 + 2].min() / df1["close"].iloc[i0] - 1.0) * 100)
        elif w.exit == "UP":
            adv = float((1.0 - df1["high"].iloc[i0:i1 + 2].max() / df1["close"].iloc[i0]) * 100)
        else:
            adv = 0.0
        rows.append({"start": w.start, "hours": w.hours, "w_atr": round(float(w0), 1),
                     "exit": w.exit, "adv_pct": round(adv, 2),
                     "dep_frac": round(w.deployable_frac, 2)})
    out = pd.DataFrame(rows)
    if len(out) == 0:
        return out
    # cushion at the bar BEFORE the exit (last calm bar inside the box)
    return out


def cushion_profile(df1: pd.DataFrame) -> dict:
    """Distribution of the near-edge cushion across all in-box bars, plus the
    hazard: among bars whose near cushion was <= 1.0 ATR, the fraction that
    saw a 2-sigma bar or channel break within the next 6/12/24h."""
    inside = df1["inside"].fillna(False)
    c = df1.loc[inside, "cush_near"]
    c_full = df1["cush_near"]
    brk = (df1["close"] > df1["up_chan"]) | (df1["close"] < df1["dn_chan"])
    danger = ((df1["sig"].fillna(False)) | brk).astype(float)

    def fwd(x: int) -> pd.Series:
        # 1 if a danger bar occurs within the NEXT x bars (excluding current)
        return danger.shift(-1).rolling(x, min_periods=1).max().fillna(0.0)

    f6, f24 = fwd(6), fwd(24)
    out = {
        "cush_q": {q: round(float(c.quantile(q)), 2) for q in (0.1, 0.25, 0.5, 0.75, 0.9)},
        "frac_cush_le_1atr": round(float((c <= 1.0).mean()) * 100, 1),
        "frac_cush_le_2atr": round(float((c <= 2.0).mean()) * 100, 1),
    }
    m1 = (c_full <= 1.0) & inside
    out["hazard_cush_le_1"] = {
        "n": int(m1.sum()),
        "danger_6h": round(float(f6.loc[m1].mean() * 100), 1) if m1.sum() else 0.0,
        "danger_24h": round(float(f24.loc[m1].mean() * 100), 1) if m1.sum() else 0.0,
    }
    m2 = (c_full > 2.0) & inside
    out["hazard_cush_gt_2"] = {
        "n": int(m2.sum()),
        "danger_6h": round(float(f6.loc[m2].mean() * 100), 1) if m2.sum() else 0.0,
        "danger_24h": round(float(f24.loc[m2].mean() * 100), 1) if m2.sum() else 0.0,
    }
    return out


@dataclass
class Window:
    start: pd.Timestamp
    end: pd.Timestamp
    hours: int
    exit: str                      # "UP" / "DOWN" / "DATA_END"
    deployable_frac: float
    n_bars: int


def window_log(df1: pd.DataFrame) -> list[Window]:
    """Maximal runs of non-EXPOSED bars. Each run is a candidate grid window;
    its exit is the channel side the next bar broke."""
    st = df1["state"].fillna("")
    exposed_up = st == EXPOSED_UP
    exposed_dn = st == EXPOSED_DN
    in_win = ~(exposed_up | exposed_dn)
    if not in_win.any():
        return []
    runs = in_win.groupby((~in_win).cumsum()).cumsum() > 0
    idx = np.where(in_win.to_numpy())[0]
    # split idx into contiguous runs
    splits = np.where(np.diff(idx) > 1)[0] + 1
    chunks = np.split(idx, splits)
    wins: list[Window] = []
    for ch in chunks:
        s, e = int(ch[0]), int(ch[-1])
        i_end = e + 1
        if i_end < len(df1):
            nxt = df1["state"].iloc[i_end]
            exit_side = "UP" if nxt == EXPOSED_UP else "DOWN" if nxt == EXPOSED_DN else "OTHER"
        else:
            exit_side = "DATA_END"
        dep = (df1["state"].iloc[s:e + 1] == DEPLOYABLE).mean()
        wins.append(Window(
            start=df1.index[s], end=df1.index[e], hours=e - s + 1,
            exit=exit_side, deployable_frac=float(dep), n_bars=len(ch),
        ))
    return wins


# ── scoring ─────────────────────────────────────────────────────────────────

# Documented anchors (data/grid_history_2026-10-12.md): the four leveraged
# margin grids that produced the Oct-8 crash losses, with their live-window
# starts (UTC) and entry prices.
CRASH_ANCHORS = [
    ("margin-925", "2026-10-08 08:58", 5.212),
    ("margin-1500", "2026-10-08 09:09", 5.197),
    ("margin-2050", "2026-10-08 10:03", 5.305),
    ("margin-1000", "2026-10-08 14:55", 5.005),
]

# Known grid-relevant boxes (user's 1h chart, Oct 3-13 window + grid history;
# indicative, documented BEFORE scoring).
GOOD_BOXES = [
    ("pre-crash box 4.6-5.4 (bots' range)", "2026-10-03 00:00", "2026-10-07 12:00"),
    ("post-crash box 4.4-5.4", "2026-10-09 00:00", "2026-10-10 23:00"),
]


def _bar_completed_before(ts: pd.Timestamp, idx: pd.DatetimeIndex) -> int:
    """Index of the last 1h bar (open-indexed) that COMPLETED strictly
    before ts: bar with open T completes at T+1h, so T + 1h <= ts."""
    target = ts - pd.Timedelta(hours=1)
    pos = int(idx.searchsorted(target, side="left"))
    return pos - 1


def score_crash_anchors(df1: pd.DataFrame) -> list[dict]:
    rows = []
    for name, ts_s, px in CRASH_ANCHORS:
        ts = pd.Timestamp(ts_s, tz="UTC")
        i = _bar_completed_before(ts, df1.index)
        if i < 20:
            rows.append({"name": name, "error": "warmup"})
            continue
        bar = df1.iloc[i]
        st = bar["state"]
        fwd = df1.iloc[i + 1:]
        # first hard exit after the start: close outside the bar's own
        # channel edge, or a 2-sigma bar
        hard = ((fwd["close"] > fwd["up_chan"]) | (fwd["close"] < fwd["dn_chan"]) | fwd["sig"])
        hard_idx = fwd.index[hard.to_numpy()]
        j = hard_idx[0] if len(hard_idx) else None
        ttf = None
        if j is not None:
            ttf = (j - ts).total_seconds() / 3600.0
        w24 = df1[(df1.index >= ts) & (df1.index <= ts + pd.Timedelta(hours=24))]
        adv24 = float((w24["low"].min() / px - 1.0)) if len(w24) else np.nan
        rows.append({
            "name": name, "start": str(ts), "px": px,
            "state_at": st, "adx": round(float(bar["adx"]), 1),
            "would_allow_deploy": st == DEPLOYABLE,
            "first_hard_exit_h_after": round(ttf, 1) if ttf is not None else None,
            "min_price_24h_adv": round(adv24 * 100, 2),
        })
    return rows


def score_good_boxes(df1: pd.DataFrame) -> list[dict]:
    rows = []
    for name, s, e in GOOD_BOXES:
        m = (df1.index >= pd.Timestamp(s, tz="UTC")) & (df1.index <= pd.Timestamp(e, tz="UTC"))
        sub = df1[m]
        if len(sub) == 0:
            rows.append({"name": name, "bars": 0})
            continue
        counts = sub["state"].value_counts()
        rows.append({
            "name": name, "bars": len(sub),
            "deployable_frac": round(float((sub["state"] == DEPLOYABLE).mean()), 3),
            "states": {k: int(v) for k, v in counts.items()},
        })
    return rows


def sigma_census(df1: pd.DataFrame) -> list[dict]:
    """Every 2-sigma 1h bar, with the forward 12h/24h extreme moves —
    the bars that a margin grid cannot survive."""
    rows = []
    sig_idx = df1.index[df1["sig"].fillna(False)]
    for t in sig_idx:
        i = df1.index.get_loc(t)
        px = float(df1["low"].iloc[i])
        for H in (12, 24):
            w = df1.iloc[i + 1:i + 1 + H]
            if len(w):
                down = float((w["low"].min() / px - 1.0) * 100)
                up = float((w["high"].max() / px - 1.0) * 100)
                rows.append({"time": str(t), "horizon_h": H,
                             "down_pct": round(down, 2), "up_pct": round(up, 2),
                             "volspike": bool(df1["volspike"].iloc[i])})
    return rows


# ── report ──────────────────────────────────────────────────────────────────

def build_report(csv_path: str) -> str:
    df5 = load_csv(csv_path)
    df1 = resample_1h(df5)
    if len(df1) < 200:
        raise ValueError("Not enough 1h bars")
    f = run_states(add_features(df1))

    L: list[str] = []
    A = L.append
    A("GRID-WINDOW DETECTOR — 1h NEAR (pre-registered parameters, no tuning)")
    A(f"data: {csv_path} · 1h bars {len(f)} · {f.index[0]} → {f.index[-1]}")
    A("")
    A("STATE DISTRIBUTION (fraction of bars):")
    dist = f["state"].value_counts(normalize=True)
    for k, v in dist.items():
        A(f"  {k:<12} {v*100:5.1f}%")
    A("")
    A("CUSHION — distance from close to the NEARST box edge, in ATR units")
    A("(in-box bars only). The 'how much adverse move can the box absorb' gauge:")
    cp = cushion_profile(f)
    q = cp["cush_q"]
    A(f"  quantiles: p10 {q[0.1]}  p25 {q[0.25]}  p50 {q[0.5]}  p75 {q[0.75]}  p90 {q[0.9]} ATR")
    A(f"  bars with cushion <= 1 ATR: {cp['frac_cush_le_1atr']}%   <= 2 ATR: {cp['frac_cush_le_2atr']}%")
    A("")
    A("FORWARD HAZARD — probability of a channel break or 2-sigma bar within")
    A("the next 6h / 24h, by starting cushion (in-box bars):")
    h1, h2 = cp["hazard_cush_le_1"], cp["hazard_cush_gt_2"]
    A(f"  cushion <= 1 ATR (n={h1['n']:>5}):  6h {h1['danger_6h']:5.1f}%   24h {h1['danger_24h']:5.1f}%")
    A(f"  cushion >  2 ATR (n={h2['n']:>5}):  6h {h2['danger_6h']:5.1f}%   24h {h2['danger_24h']:5.1f}%")
    A("")
    bh = box_hazard(f)
    if len(bh):
        A("BOX BREAK HAZARD — per box (>=6h): width at start, exit side, and the")
        A("adverse move a grid on the broken edge would have been carried:")
        A(f"  {'start':<17} {'h':>4} {'wATR':>5} {'exit':<6} {'adv%':>7}   (deployable frac of box)")
        for _, r in bh.iterrows():
            A(f"  {str(r['start'])[:16]:<17} {r['hours']:>4} {r['w_atr']:>5} {r['exit']:<6} {r['adv_pct']:>7}   {r['dep_frac']:.0%}")
        dn = bh[bh.exit == "DOWN"]
        if len(dn):
            A(f"  DOWN-exit boxes: {len(dn)} · median width {dn.w_atr.median():.1f} ATR · "
              f"median adverse {dn.adv_pct.median():.1f}% · worst {dn.adv_pct.min():.1f}%")
    A("")
    A("CRASH-KILLER ANCHORS — what the detector said at each grid start:")
    A(f"  {'bot':<12} {'start (UTC)':<18} {'state@start':<12} {'ADX':>5} {'deploy?':<9} {'1st hard exit +h':>17} {'min px 24h':>11}")
    for r in score_crash_anchors(f):
        if "error" in r:
            A(f"  {r['name']:<12} {r['error']}")
            continue
        A(f"  {r['name']:<12} {r['start']:<18} {str(r['state_at']):<12} {r['adx']:>5} "
          f"{'YES' if r['would_allow_deploy'] else 'no':<9} "
          f"{('+' + str(r['first_hard_exit_h_after'])) if r['first_hard_exit_h_after'] is not None else '—':>17} "
          f"{r['min_price_24h_adv']:>10.2f}%")
    A("  (BTC tripwire leg: N/A in Python — no BTC data in repo; see the Pine")
    A("   indicator. It would be evaluated on BTC's own 20-bar channel.)")
    A("")
    A("KNOWN GOOD BOXES — fraction of bars the detector marked DEPLOYABLE:")
    for r in score_good_boxes(f):
        if r.get("bars", 0) == 0:
            A(f"  {r['name']}: no data in range")
        else:
            A(f"  {r['name']:<28} {r['bars']} bars · deployable {r['deployable_frac']*100:.0f}% · {r['states']}")
    A("")
    A("2-SIGMA 1h BAR CENSUS (the bars a margin grid cannot survive):")
    cens = sigma_census(f)
    per_bar = {r["time"]: r for r in cens if r["horizon_h"] == 24}
    A(f"  {len(per_bar)} sigma bars of {len(f)} (1h) = "
      f"{len(per_bar)/len(f)*100:.1f}%. Forward 24h extremes (from bar low):")
    worst = sorted(per_bar.items(), key=lambda kv: kv[1]["down_pct"])[:10]
    for t, r in worst:
        A(f"  {t}  down {r['down_pct']:>7.2f}% / up {r['up_pct']:>7.2f}%  vol-spike {r['volspike']}")
    vol_share = sum(1 for r in per_bar.values() if r["volspike"])
    A(f"  volume-spike confirmation present on {vol_share}/{len(per_bar)} sigma bars.")
    crash = [r for t, r in per_bar.items() if "2026-10-08" in t or "2026-10-09" in t]
    if crash:
        A(f"  Oct 8-9 crash cluster: {len(crash)} sigma bars; worst forward down "
          f"{min(r['down_pct'] for r in crash):.2f}%.")
    A("")
    A("WINDOW LOG (maximal non-EXPOSED runs):")
    for w in window_log(f):
        A(f"  {w.start:%Y-%m-%d %H:%M} → {w.end:%Y-%m-%d %H:%M}  {w.hours:>4}h  exit {w.exit:<8} "
          f"deployable {w.deployable_frac*100:.0f}% of bars")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Grid-window detector (research)")
    ap.add_argument("--csv", required=True, help="base-TF OHLCV CSV (resampled to 1h)")
    args = ap.parse_args(argv)
    print(build_report(args.csv))
    return 0


if __name__ == "__main__":
    sys.exit(main())
