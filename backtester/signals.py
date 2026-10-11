"""Signal model — canonical port of the Pine scoring system.

KEEP IN SYNC with pine/signal_engine.pine and pine/signal_engine_strategy.pine.
docs/SIGNAL_SPEC.md is the single source of truth for every sub-condition.

Conventions (identical to the Pine files):
  • Decision bar i uses bar i's OWN confirmed OHLCV (the signal fires at the
    close of bar i; the Pine indicator observes the same state one bar later
    via [1] — identical information set).
  • HTF/MID values are those of the last COMPLETED bar of that TF strictly
    before bar i opens (see data.align_htf).
  • NaN comparison == False (Pine treats na comparisons as false too).
  • Score = sum over components of weight * (sub_points / max_sub_points).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import data as D
from . import indicators as I


@dataclass
class Params:
    # mode
    mode: str = "SCALP"                      # SCALP | REVERSAL
    # timeframes (seconds)
    tf_base_s: int = 300                     # entry TF
    tf_mid_s: int = 15 * 60
    tf_htf_s: int = 45 * 60
    # indicators
    ema_fast: int = 9
    ema_mid: int = 21
    ema_slow: int = 55
    ema_trend: int = 200
    rsi_len: int = 14
    rsi_weak: int = 40
    rsi_mid: int = 50
    rsi_strong: int = 60
    rsi_ob: int = 70
    rsi_os: int = 30
    macd_fast: int = 12
    macd_slow: int = 26
    macd_sig: int = 9
    vol_len: int = 20
    vol_mult: float = 1.5
    atr_len: int = 14
    piv_len: int = 5
    recency: int = 3
    # scalp weights (sum 100)
    w_t45: int = 20
    w_m15: int = 20
    w_e5: int = 15
    w_rsi: int = 10
    w_mcd: int = 10
    w_vol: int = 15
    w_str: int = 10
    scalp_thr: int = 80
    # reversal weights (sum 100)
    w_rej: int = 25
    w_mtn: int = 25
    w_hwf: int = 15
    w_flp: int = 10
    w_rvl: int = 15
    w_rst: int = 10
    rev_thr: int = 70
    # risk & filters
    stop_atr: float = 1.2
    tgt_atr: float = 1.8
    min_room_atr: float = 2.0
    piv_age_max: int = 120
    piv_fresh: int = 15
    require_room: bool = True
    trend_exit: bool = True
    # regime
    adx_len: int = 14
    adx_trend: float = 20.0
    vol_spike: float = 1.8
    vol_sma_len: int = 100
    sep_min: float = 0.15
    block_abnormal: bool = True
    # gates
    strict_trend: bool = True
    vwap_gate: bool = False

    @property
    def is_scalp(self) -> bool:
        return self.mode.upper() == "SCALP"

    @property
    def threshold(self) -> int:
        return self.scalp_thr if self.is_scalp else self.rev_thr


def _pts(cond: pd.Series) -> pd.Series:
    """bool/NaN-safe condition -> 0/1 float series (NaN -> False)."""
    return cond.fillna(False).astype(float)


def build_tf_frame(df: pd.DataFrame, p: Params, role: str = "entry") -> pd.DataFrame:
    """Per-TF indicator columns, computed directly on that TF's bars.

    Mirrors the Pine packs — only the fields each role actually uses:
      trend: c, ef, em, es, et                                   (5)
      mid:   + rsi, rsip, mh, mhp, dip, dim, adx, ap, apavg     (14)
      entry: full set (OHLCV, slopes, rsi, macd, cross ages, atr,
             vavg, pivots, vwap)                                 (30)
    """
    c = df["close"]
    f = pd.DataFrame(index=df.index)
    f["c"] = c
    ef = I.ema(c, p.ema_fast)
    em = I.ema(c, p.ema_mid)
    es = I.ema(c, p.ema_slow)
    et = I.ema(c, p.ema_trend)
    f["ef"], f["em"], f["es"], f["et"] = ef, em, es, et

    if role == "trend":
        return f

    rsi = I.rsi(c, p.rsi_len)
    f["rsi"] = rsi
    f["rsip"] = rsi.shift(1)
    ml, ms, mh = I.macd(c, p.macd_fast, p.macd_slow, p.macd_sig)
    f["mh"], f["mhp"] = mh, mh.shift(1)
    dip, dim, adxv = I.adx(df, p.adx_len)
    f["dip"], f["dim"], f["adx"] = dip, dim, adxv
    atr_s = I.atr(df, p.atr_len)
    f["ap"] = atr_s / c * 100.0
    f["apavg"] = f["ap"].rolling(p.vol_sma_len).mean()

    if role == "mid":
        return f

    # entry role — full set
    f["o"] = df["open"]
    f["h"] = df["high"]
    f["l"] = df["low"]
    f["v"] = df["volume"]
    f["vup"] = df["volume"] > df["volume"].shift(1)
    f["pbear"] = c.shift(1) < df["open"].shift(1)
    f["pbull"] = c.shift(1) > df["open"].shift(1)
    f["emr"] = em > em.shift(1)
    f["esr"] = es > es.shift(1)
    f["ml"], f["mlp"] = ml, ml.shift(1)
    f["cru_age"] = pd.Series(_barssince(_crossover(ef, em)), index=df.index)
    f["crd_age"] = pd.Series(_barssince(_crossunder(ef, em)), index=df.index)
    f["mcru_age"] = pd.Series(_barssince(_crossover(ml, ms)), index=df.index)
    f["mcrd_age"] = pd.Series(_barssince(_crossunder(ml, ms)), index=df.index)
    f["atr"] = atr_s
    f["vavg"] = df["volume"].rolling(p.vol_len).mean()
    ph, pl = I.pivots(df, p.piv_len)
    f["pph"], f["ppl"] = ph, pl
    f["vwap"] = I.session_vwap(df)
    return f


def _crossover(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a > b) & (a.shift(1) <= b.shift(1))


def _crossunder(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a < b) & (a.shift(1) >= b.shift(1))


def _barssince(cond: pd.Series) -> np.ndarray:
    """Bars elapsed since cond was last True (NaN if never). Matches
    ta.barssince (0 on the bar where cond is true)."""
    vals = cond.to_numpy()
    n = len(vals)
    out = np.full(n, np.nan)
    last = np.nan
    for i in range(n):
        if vals[i]:
            last = i
        if not np.isnan(last):
            out[i] = i - last
    return out


def _cross(a: pd.Series, b: pd.Series) -> pd.Series:  # pragma: no cover - kept for clarity
    return _crossover(a, b)


@dataclass
class Signals:
    idx: pd.Index
    score_long: pd.Series
    score_short: pd.Series
    rev_score_long: pd.Series
    rev_score_short: pd.Series
    long_sig: pd.Series
    short_sig: pd.Series
    regime: pd.Series
    regime_label: pd.Series
    bias45: pd.Series
    trend45: pd.Series
    atr: pd.Series
    score_components_long: dict = field(default_factory=dict)
    score_components_short: dict = field(default_factory=dict)
    gates_long: dict = field(default_factory=dict)
    gates_short: dict = field(default_factory=dict)
    room_long: pd.Series | None = None
    room_short: pd.Series | None = None


def compute_signals(base: pd.DataFrame, p: Params) -> Signals:
    """Full signal model. `base` = raw base-TF OHLCV (must be the entry TF)."""
    base_f = build_tf_frame(base, p, "entry")
    mid_raw = D.resample_ohlcv(base, p.tf_mid_s)
    htf_raw = D.resample_ohlcv(base, p.tf_htf_s)
    mid_f = build_tf_frame(mid_raw, p, "mid")
    htf_f = build_tf_frame(htf_raw, p, "trend")
    mid_a = D.align_htf(base.index, mid_f, p.tf_base_s, p.tf_mid_s).reindex(base.index)
    htf_a = D.align_htf(base.index, htf_f, p.tf_base_s, p.tf_htf_s).reindex(base.index)

    e = base_f
    m = mid_a
    h = htf_a

    piv = I.pivot_state(e["pph"], e["ppl"], p.piv_age_max, p.piv_fresh)

    # ── regime (MID TF) ──────────────────────────────────────────────────
    vol_spike = (m["apavg"] > 0) & (m["ap"] / m["apavg"] > p.vol_spike)
    sep_pct = np.where(m["c"] > 0, (m["em"] - m["es"]) / m["c"] * 100.0, 0.0)
    trend_up_r = (m["adx"] >= p.adx_trend) & (sep_pct >= p.sep_min) & (m["dip"] > m["dim"])
    trend_dn_r = (m["adx"] >= p.adx_trend) & (sep_pct <= -p.sep_min) & (m["dim"] > m["dip"])
    regime = pd.Series(
        np.where(vol_spike, 3, np.where(trend_up_r, 1, np.where(trend_dn_r, -1, 0))),
        index=base.index,
    )
    regime_label = regime.map({3: "ABNORMAL VOL", 1: "TRENDING UP", -1: "TRENDING DOWN", 0: "RANGING"})

    # ── HTF trend + bias ─────────────────────────────────────────────────
    trend45_up = (h["ef"] > h["em"]) & (h["em"] > h["es"])
    trend45_dn = (h["ef"] < h["em"]) & (h["em"] < h["es"])
    trend45 = pd.Series(np.where(trend45_up, 1, np.where(trend45_dn, -1, 0)), index=base.index)
    bias_up = trend45_up & (h["c"] > h["et"])
    bias_dn = trend45_dn & (h["c"] < h["et"])
    bias45 = pd.Series(np.where(bias_up, 1, np.where(bias_dn, -1, 0)), index=base.index)

    BIG = 1e18
    atr_e = e["atr"]

    # ── SCALP LONG ────────────────────────────────────────────────────────
    s_t45 = np.where(trend45_up, 2.0, np.where(h["ef"] > h["em"], 1.0, 0.0))
    score_t45_l = p.w_t45 * (s_t45 + _pts(h["c"] > h["et"]).to_numpy() + _pts(h["c"] > h["es"]).to_numpy()) / 4

    s_m15 = (
        _pts(m["mh"] > 0).to_numpy() + _pts(m["mh"] > m["mhp"]).to_numpy()
        + _pts(m["rsi"] > p.rsi_mid).to_numpy() + _pts(m["ef"] > m["em"]).to_numpy()
        + _pts(m["rsi"] > m["rsip"]).to_numpy()
    )
    score_m15_l = p.w_m15 * s_m15 / 5

    s_e5 = (
        _pts(e["ef"] > e["em"]).to_numpy() + _pts(e["em"] > e["es"]).to_numpy()
        + _pts(e["c"] > e["ef"]).to_numpy() + _pts(e["esr"]).to_numpy()
    )
    score_e5_l = p.w_e5 * s_e5 / 4

    s_rsi = _pts(e["rsi"] > p.rsi_mid).to_numpy() + _pts(e["rsi"] > e["rsip"]).to_numpy() + _pts(e["rsi"] < p.rsi_ob).to_numpy()
    score_rsi_l = p.w_rsi * s_rsi / 3

    s_mcd = _pts(e["mh"] > 0).to_numpy() + _pts(e["ml"] > 0).to_numpy() + _pts(e["mh"] > e["mhp"]).to_numpy()
    score_mcd_l = p.w_mcd * s_mcd / 3

    s_vol = np.where(e["v"] > p.vol_mult * e["vavg"], 2.0, 0.0) + _pts(e["c"] > e["o"]).to_numpy() + _pts(e["vup"]).to_numpy()
    s_vol = np.where(e["vavg"].notna(), s_vol, 0.0)
    score_vol_l = p.w_vol * s_vol / 4

    ph_fresh = piv["ph_fresh"].to_numpy()
    ph_valid = piv["ph_valid"].to_numpy()
    pl_valid = piv["pl_valid"].to_numpy()
    last_ph = piv["last_ph"].to_numpy()
    last_pl = piv["last_pl"].to_numpy()
    c_e = e["c"].to_numpy()
    l_e = e["l"].to_numpy()
    h_e = e["h"].to_numpy()
    atr_n = atr_e.to_numpy()

    s_str = (
        np.where(ph_fresh & (c_e > last_ph), 2.0, 0.0)
        + np.where(pl_valid & (l_e <= last_pl + 0.3 * atr_n) & (c_e > last_pl + 0.1 * atr_n), 1.0, 0.0)
        + _pts(e["emr"]).to_numpy()
    )
    s_str = np.where(np.isfinite(atr_n), s_str, 0.0)
    score_str_l = p.w_str * s_str / 4

    score_long = score_t45_l + score_m15_l + score_e5_l + score_rsi_l + score_mcd_l + score_vol_l + score_str_l

    # ── SCALP SHORT (mirror) ─────────────────────────────────────────────
    s_t45s = np.where(trend45_dn, 2.0, np.where(h["ef"] < h["em"], 1.0, 0.0))
    score_t45_s = p.w_t45 * (s_t45s + _pts(h["c"] < h["et"]).to_numpy() + _pts(h["c"] < h["es"]).to_numpy()) / 4

    s_m15s = (
        _pts(m["mh"] < 0).to_numpy() + _pts(m["mh"] < m["mhp"]).to_numpy()
        + _pts(m["rsi"] < p.rsi_mid).to_numpy() + _pts(m["ef"] < m["em"]).to_numpy()
        + _pts(m["rsi"] < m["rsip"]).to_numpy()
    )
    score_m15_s = p.w_m15 * s_m15s / 5

    e_mr_dn = e["emr"].fillna(False)
    e_sr_dn = e["esr"].fillna(False)
    s_e5s = (
        _pts(e["ef"] < e["em"]).to_numpy() + _pts(e["em"] < e["es"]).to_numpy()
        + _pts(e["c"] < e["ef"]).to_numpy() + e_mr_dn.to_numpy(dtype=float)
    )
    score_e5_s = p.w_e5 * s_e5s / 4

    s_rsiss = _pts(e["rsi"] < p.rsi_mid).to_numpy() + _pts(e["rsi"] < e["rsip"]).to_numpy() + _pts(e["rsi"] > p.rsi_os).to_numpy()
    score_rsi_s = p.w_rsi * s_rsiss / 3

    s_mcds = _pts(e["mh"] < 0).to_numpy() + _pts(e["ml"] < 0).to_numpy() + _pts(e["mh"] < e["mhp"]).to_numpy()
    score_mcd_s = p.w_mcd * s_mcds / 3

    s_vols = np.where(e["v"] > p.vol_mult * e["vavg"], 2.0, 0.0) + _pts(e["c"] < e["o"]).to_numpy() + _pts(e["vup"]).to_numpy()
    s_vols = np.where(e["vavg"].notna(), s_vols, 0.0)
    score_vol_s = p.w_vol * s_vols / 4

    s_sts = (
        np.where(piv["pl_fresh"].to_numpy() & (c_e < last_pl), 2.0, 0.0)
        + np.where(ph_valid & (h_e >= last_ph - 0.3 * atr_n) & (c_e < last_ph - 0.1 * atr_n), 1.0, 0.0)
        + e_mr_dn.to_numpy(dtype=float)
    )
    s_sts = np.where(np.isfinite(atr_n), s_sts, 0.0)
    score_str_s = p.w_str * s_sts / 4

    score_short = score_t45_s + score_m15_s + score_e5_s + score_rsi_s + score_mcd_s + score_vol_s + score_str_s

    # ── REVERSAL LONG (fade bearish move at support) ─────────────────────
    s_rej1 = np.where(pl_valid & (l_e <= last_pl + 0.25 * atr_n), 5.0, 0.0)
    s_rej2 = _pts(e["c"] > e["o"]).to_numpy() * 5.0
    s_rej3 = np.where((c_e - l_e) >= np.maximum(0.3 * atr_n, 0.4 * (h_e - l_e)), 5.0, 0.0)
    s_rej4 = _pts(e["pbear"]).to_numpy() * 5.0
    s_rej5 = _pts(e["rsi"] > p.rsi_os).to_numpy() * _pts(e["rsi"] <= p.rsi_strong).to_numpy() * 5.0
    score_rej_l = p.w_rej * (s_rej1 + s_rej2 + s_rej3 + s_rej4 + s_rej5) / 25

    cru = e["cru_age"].to_numpy()
    mcr = e["mcru_age"].to_numpy()
    s_mtn1 = _pts(e["rsi"] > e["rsip"]).to_numpy() * 5.0
    s_mtn2 = _pts(e["mh"] > e["mhp"]).to_numpy() * 5.0
    s_mtn3 = np.where(~np.isnan(mcr) & (mcr <= p.recency), 5.0, 0.0)
    s_mtn4 = _pts(e["mhp"] < 0).to_numpy() * 5.0
    s_mtn5 = _pts(e["rsi"] > p.rsi_weak).to_numpy() * 5.0
    score_mtn_l = p.w_mtn * (s_mtn1 + s_mtn2 + s_mtn3 + s_mtn4 + s_mtn5) / 25

    s_hwf1 = _pts(m["mh"] < m["mhp"]).to_numpy() * 5.0
    s_hwf2 = _pts(m["rsi"] < p.rsi_mid).to_numpy() * 5.0
    s_hwf3 = _pts(m["dim"] > m["dip"]).to_numpy() * 5.0
    score_hwf_l = p.w_hwf * (s_hwf1 + s_hwf2 + s_hwf3) / 15

    s_flp1 = np.where(~np.isnan(cru) & (cru <= p.recency), 5.0, 0.0)
    s_flp2 = np.where(~np.isnan(mcr) & (mcr <= p.recency), 5.0, 0.0)
    score_flp_l = p.w_flp * (s_flp1 + s_flp2) / 10

    s_rvl1 = _pts(e["v"] > p.vol_mult * e["vavg"]).to_numpy() * 5.0
    s_rvl2 = _pts(e["vup"]).to_numpy() * 5.0
    s_rvl3 = _pts(e["c"] > e["o"]).to_numpy() * _pts(e["v"] > e["vavg"]).to_numpy() * 5.0
    score_rvl_l = p.w_rvl * (s_rvl1 + s_rvl2 + s_rvl3) / 15

    s_rst1 = np.where(pl_valid & (l_e <= last_pl + 0.5 * atr_n) & (c_e > last_pl), 5.0, 0.0)
    s_rst2 = _pts(e["emr"]).to_numpy() * 5.0
    score_rst_l = p.w_rst * (s_rst1 + s_rst2) / 10

    rev_score_long = score_rej_l + score_mtn_l + score_hwf_l + score_flp_l + score_rvl_l + score_rst_l

    # ── REVERSAL SHORT (mirror) ───────────────────────────────────────────
    s_rej1s = np.where(ph_valid & (h_e >= last_ph - 0.25 * atr_n), 5.0, 0.0)
    s_rej2s = _pts(e["c"] < e["o"]).to_numpy() * 5.0
    s_rej3s = np.where((h_e - c_e) >= np.maximum(0.3 * atr_n, 0.4 * (h_e - l_e)), 5.0, 0.0)
    s_rej4s = _pts(e["pbull"]).to_numpy() * 5.0
    s_rej5s = _pts(e["rsi"] < p.rsi_ob).to_numpy() * _pts(e["rsi"] >= p.rsi_weak).to_numpy() * 5.0
    score_rej_s = p.w_rej * (s_rej1s + s_rej2s + s_rej3s + s_rej4s + s_rej5s) / 25

    crd = e["crd_age"].to_numpy()
    mcdr = e["mcrd_age"].to_numpy()
    s_mtn1s = _pts(e["rsi"] < e["rsip"]).to_numpy() * 5.0
    s_mtn2s = _pts(e["mh"] < e["mhp"]).to_numpy() * 5.0
    s_mtn3s = np.where(~np.isnan(mcdr) & (mcdr <= p.recency), 5.0, 0.0)
    s_mtn4s = _pts(e["mhp"] > 0).to_numpy() * 5.0
    s_mtn5s = _pts(e["rsi"] < p.rsi_weak).to_numpy() * 5.0
    score_mtn_s = p.w_mtn * (s_mtn1s + s_mtn2s + s_mtn3s + s_mtn4s + s_mtn5s) / 25

    s_hwf1s = _pts(m["mh"] > m["mhp"]).to_numpy() * 5.0
    s_hwf2s = _pts(m["rsi"] > p.rsi_mid).to_numpy() * 5.0
    s_hwf3s = _pts(m["dip"] > m["dim"]).to_numpy() * 5.0
    score_hwf_s = p.w_hwf * (s_hwf1s + s_hwf2s + s_hwf3s) / 15

    s_flp1s = np.where(~np.isnan(crd) & (crd <= p.recency), 5.0, 0.0)
    s_flp2s = np.where(~np.isnan(mcdr) & (mcdr <= p.recency), 5.0, 0.0)
    score_flp_s = p.w_flp * (s_flp1s + s_flp2s) / 10

    s_rvl1s = _pts(e["v"] > p.vol_mult * e["vavg"]).to_numpy() * 5.0
    s_rvl2s = _pts(e["vup"]).to_numpy() * 5.0
    s_rvl3s = _pts(e["c"] < e["o"]).to_numpy() * _pts(e["v"] > e["vavg"]).to_numpy() * 5.0
    score_rvl_s = p.w_rvl * (s_rvl1s + s_rvl2s + s_rvl3s) / 15

    s_rst1s = np.where(ph_valid & (h_e >= last_ph - 0.5 * atr_n) & (c_e < last_ph), 5.0, 0.0)
    s_rst2s = e_mr_dn.to_numpy(dtype=float) * 5.0
    score_rst_s = p.w_rst * (s_rst1s + s_rst2s) / 10

    rev_score_short = score_rej_s + score_mtn_s + score_hwf_s + score_flp_s + score_rvl_s + score_rst_s

    # ── gates ─────────────────────────────────────────────────────────────
    room_long = np.where(ph_valid & (last_ph > c_e), last_ph - c_e, BIG)
    room_short = np.where(pl_valid & (last_pl < c_e), c_e - last_pl, BIG)
    # NOTE: use `not` (logical). `~` on a Python bool is BITWISE NOT —
    # ~True == -2 and ~False == -1, both truthy — which silently turns every
    # gate into `True` (caught by the filter tests in V2.0).
    atr_e_np = atr_e.to_numpy()
    regime_ok = pd.Series((not p.block_abnormal) or (regime != 3), index=base.index)
    vwap_long_ok = pd.Series((not p.vwap_gate) or (e["c"] > e["vwap"]), index=base.index)
    vwap_short_ok = pd.Series((not p.vwap_gate) or (e["c"] < e["vwap"]), index=base.index)
    room_long_ok = pd.Series((not p.require_room) or (room_long >= p.min_room_atr * atr_e_np), index=base.index)
    room_short_ok = pd.Series((not p.require_room) or (room_short >= p.min_room_atr * atr_e_np), index=base.index)
    trend_long_ok = (trend45 == 1) if p.strict_trend else (trend45 != -1)
    trend_short_ok = (trend45 == -1) if p.strict_trend else (trend45 != 1)
    rev_long_ok = trend45 != 1
    rev_short_ok = trend45 != -1

    long_sig = pd.Series(
        np.where(
            p.is_scalp,
            (score_long >= p.scalp_thr) & trend_long_ok.to_numpy() & regime_ok.to_numpy()
            & vwap_long_ok.to_numpy() & room_long_ok.to_numpy(),
            (rev_score_long >= p.rev_thr) & rev_long_ok.to_numpy() & regime_ok.to_numpy()
            & vwap_long_ok.to_numpy() & room_long_ok.to_numpy(),
        ),
        index=base.index,
    )
    short_sig = pd.Series(
        np.where(
            p.is_scalp,
            (score_short >= p.scalp_thr) & trend_short_ok.to_numpy() & regime_ok.to_numpy()
            & vwap_short_ok.to_numpy() & room_short_ok.to_numpy(),
            (rev_score_short >= p.rev_thr) & rev_short_ok.to_numpy() & regime_ok.to_numpy()
            & vwap_short_ok.to_numpy() & room_short_ok.to_numpy(),
        ),
        index=base.index,
    )

    idx = base.index
    ser = lambda x: pd.Series(np.asarray(x, dtype=float), index=idx)
    return Signals(
        idx=idx,
        score_long=ser(score_long),
        score_short=ser(score_short),
        rev_score_long=ser(rev_score_long),
        rev_score_short=ser(rev_score_short),
        long_sig=long_sig.fillna(False),
        short_sig=short_sig.fillna(False),
        regime=regime,
        regime_label=regime_label,
        bias45=bias45,
        trend45=trend45,
        atr=atr_e,
        score_components_long={
            "trend45": ser(score_t45_l), "mom15": ser(score_m15_l), "ema5": ser(score_e5_l),
            "rsi": ser(score_rsi_l), "macd": ser(score_mcd_l), "volume": ser(score_vol_l),
            "structure": ser(score_str_l),
        },
        score_components_short={
            "trend45": ser(score_t45_s), "mom15": ser(score_m15_s), "ema5": ser(score_e5_s),
            "rsi": ser(score_rsi_s), "macd": ser(score_mcd_s), "volume": ser(score_vol_s),
            "structure": ser(score_str_s),
        },
        gates_long={
            "htf_trend": trend_long_ok.fillna(False), "regime": regime_ok.fillna(False),
            "vwap": vwap_long_ok.fillna(False), "room": room_long_ok.fillna(False),
        },
        gates_short={
            "htf_trend": trend_short_ok.fillna(False), "regime": regime_ok.fillna(False),
            "vwap": vwap_short_ok.fillna(False), "room": room_short_ok.fillna(False),
        },
        room_long=ser(room_long),
        room_short=ser(room_short),
    )
