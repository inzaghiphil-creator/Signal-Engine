"""Vectorized indicator implementations (Wilder-convention where Pine uses it).

Every function here mirrors the Pine v6 builtin used in the scripts:
  ema      <- ta.ema            (alpha = 2/(n+1), ewm adjust=False)
  rsi      <- ta.rsi            (RMA smoothing)
  macd     <- ta.macd           (EMA-based)
  atr      <- ta.atr            (RMA of true range)
  adx      <- manual Wilder DMI (same formula family as ta.dmi)
  pivots   <- ta.pivothigh / ta.pivotlow  (strict inequality, R-bar confirm)
  vwap     <- ta.vwap           (session-anchored, UTC day)
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def rma(s: pd.Series, n: int) -> pd.Series:
    """Wilder's moving average (alpha = 1/n)."""
    return s.ewm(alpha=1.0 / n, adjust=False).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0.0)
    dn = -d.clip(upper=0.0)
    ru = rma(up, n)
    rd = rma(dn, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = ru / rd
    out = 100.0 - 100.0 / (1.0 + rs)  # rd == 0, ru > 0  -> inf -> 100
    out = out.mask((rd == 0) & (ru == 0), 50.0)
    return out


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    line = ema(close, fast) - ema(close, slow)
    sig = ema(line, signal)
    return line, sig, line - sig


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    return pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return rma(true_range(df), n)


def adx(df: pd.DataFrame, n: int = 14):
    """Returns (plusDI, minusDI, ADX) — Wilder's DMI, matches the manual
    computation in the Pine scripts."""
    up = df["high"].diff()
    dn = -df["low"].diff()
    plus_dm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    trn = rma(true_range(df), n)
    pdm = rma(plus_dm, n)
    mdm = rma(minus_dm, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        di_plus = 100.0 * pdm / trn
        di_minus = 100.0 * mdm / trn
    di_plus = di_plus.where(trn > 0, 0.0)
    di_minus = di_minus.where(trn > 0, 0.0)
    di_sum = di_plus + di_minus
    dx = 100.0 * (di_plus - di_minus).abs() / di_sum
    dx = dx.where(di_sum > 0, 0.0)
    return di_plus, di_minus, rma(dx, n)


def pivots(df: pd.DataFrame, L: int = 5):
    """Confirmed pivots. A pivot centered at bar i (high strictly greater
    than the L bars before and after) is CONFIRMED at bar i+L and the value
    is published there — exactly ta.pivothigh(h, L, L) semantics."""
    n = len(df)
    h = df["high"].to_numpy()
    l = df["low"].to_numpy()
    ph = np.full(n, np.nan)
    pl = np.full(n, np.nan)
    for i in range(L, n - L):
        # strict inequality on both wings (ties -> no pivot, Pine semantics)
        if (h[i] > h[i - L: i]).all() and (h[i] > h[i + 1: i + L + 1]).all():
            ph[i + L] = h[i]
        if (l[i] < l[i - L: i]).all() and (l[i] < l[i + 1: i + L + 1]).all():
            pl[i + L] = l[i]
    idx = df.index
    return pd.Series(ph, index=idx), pd.Series(pl, index=idx)


def pivot_state(ph: pd.Series, pl: pd.Series, age_max: int, fresh_max: int):
    """Mirror of the Pine pivot state machine:
    lastPh/lastPl (value at the last *fresh* pivot — a pivot whose value
    differs from the previous pivot's), plus age in bars since that pivot
    was published, and freshness (age <= fresh_max)."""

    def _state(p: pd.Series):
        pos = np.arange(len(p))
        fresh_arr = (p.notna() & (p.ffill().shift(1).isna() | (p != p.ffill().shift(1)))).to_numpy()
        last_fresh_pos = pd.Series(pos, index=p.index).where(fresh_arr).ffill()
        age = pos - last_fresh_pos.to_numpy()
        val = p.where(fresh_arr).ffill()
        valid = last_fresh_pos.notna().to_numpy() & (age <= age_max)
        fresh_ok = last_fresh_pos.notna().to_numpy() & (age <= fresh_max)
        return (
            val,
            pd.Series(age, index=p.index),
            pd.Series(valid, index=p.index),
            pd.Series(fresh_ok, index=p.index),
        )

    return {
        "last_ph": _state(ph)[0],
        "ph_age": _state(ph)[1],
        "ph_valid": _state(ph)[2],
        "ph_fresh": _state(ph)[3],
        "last_pl": _state(pl)[0],
        "pl_age": _state(pl)[1],
        "pl_valid": _state(pl)[2],
        "pl_fresh": _state(pl)[3],
    }


def session_vwap(df: pd.DataFrame) -> pd.Series:
    """UTC-day anchored VWAP, cumulative within the session (== ta.vwap on a
    default daily session). At bar i it uses bars up to and including i —
    no future data."""
    hl2 = (df["high"] + df["low"] + df["close"]) / 3.0
    day = df.index.floor("1D")
    pv = (hl2 * df["volume"]).groupby(day).cumsum()
    vv = df["volume"].groupby(day).cumsum()
    with np.errstate(divide="ignore", invalid="ignore"):
        vwap = pv / vv
    return vwap
