"""Data loading, resampling and confirmed-HTF alignment.

Non-repainting rule (mirrors Pine `request.security(..., lookahead_off)`
with `[1]` inside the expression): for a base bar that OPENS at time `t`,
only higher-timeframe bars that COMPLETED before `t` are visible, i.e. an
HTF bar with open `T` is usable iff `T + tf_htf <= t`.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

_OHLCV_COLS = ["open", "high", "low", "close", "volume"]


def parse_tf(tf: str) -> int:
    """'5m' -> 300 seconds. Supports s/m/h/d/w."""
    tf = tf.strip().lower()
    m = re.fullmatch(r"(\d+)([smhdw])", tf)
    if not m:
        raise ValueError(f"Unsupported timeframe: {tf!r} (use e.g. '5m', '15m', '45m', '1h')")
    n, unit = int(m.group(1)), m.group(2)
    return n * {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[unit]


def load_csv(path: str | Path) -> pd.DataFrame:
    """Load OHLCV CSV. Accepts TradingView export ('Date,Time,Open,...' or a
    single ISO 'Date' column) and KuCoin-style ('time,open,high,low,close,
    volume' with epoch ms/s). Returns a DataFrame indexed by UTC bar-open
    time with columns open/high/low/close/volume, sorted ascending."""
    df = pd.read_csv(path)
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]

    if "date" in df.columns and "time" in df.columns:
        raw = df["date"].astype(str) + " " + df["time"].astype(str)
        idx = pd.to_datetime(raw, utc=True, format="mixed")
    else:
        tc = None
        for cand in ("time", "datetime", "date", "timestamp", "ts"):
            if cand in df.columns:
                tc = cand
                break
        if tc is None:
            raise ValueError(f"Cannot find a time column in {path} (columns: {list(df.columns)})")
        s = df[tc]
        if pd.api.types.is_numeric_dtype(s):
            med = float(s.median())
            unit = "ms" if med > 1e11 else "s"
            idx = pd.to_datetime(s, unit=unit, utc=True)
        else:
            idx = pd.to_datetime(s, utc=True, format="mixed")

    missing = [c for c in _OHLCV_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns {missing} in {path} (columns: {list(df.columns)})")

    out = df[_OHLCV_COLS].copy()
    out.index = idx
    out = out[~out.index.duplicated(keep="last")].sort_index()
    out = out.dropna(subset=_OHLCV_COLS)
    return out


def detect_tf_seconds(df: pd.DataFrame) -> int:
    if len(df) < 3:
        raise ValueError("Not enough bars to detect the timeframe")
    diffs = df.index.to_series().diff().dropna()
    med = int(round(diffs.dt.total_seconds().median()))
    if med <= 0:
        raise ValueError("Could not detect a positive bar interval")
    return med


def resample_ohlcv(df: pd.DataFrame, tf_s: int) -> pd.DataFrame:
    """Resample base bars into tf_s bars (bars are open-indexed). The last
    bucket may be a PARTIAL bar — callers must respect the confirmed-only
    alignment rule in align_htf."""
    t = pd.Timedelta(seconds=tf_s)
    bucket = df.index.floor(t)
    g = df.groupby(bucket)
    out = pd.DataFrame(
        {
            "open": g["open"].first(),
            "high": g["high"].max(),
            "low": g["low"].min(),
            "close": g["close"].last(),
            "volume": g["volume"].sum(),
        }
    )
    out = out.sort_index()
    return out


def align_htf(base_index: pd.DatetimeIndex, htf_df: pd.DataFrame, tf_base_s: int, tf_htf_s: int) -> pd.DataFrame:
    """For each base bar (open time t), return the values of the last
    COMPLETED HTF bar: open T with T + tf_htf <= t. Rows where no such HTF
    bar exists (data start) are all-NaN."""
    if tf_htf_s % tf_base_s != 0:
        raise ValueError(f"HTF {tf_htf_s}s must be a multiple of base {tf_base_s}s")
    t_base = base_index.to_series()
    target = t_base.subtract(pd.Timedelta(seconds=tf_htf_s)).dt.floor(pd.Timedelta(seconds=tf_htf_s))
    # NOTE: pass the Series (not .values) — pandas 3.x reindex(DatetimeArray)
    # silently fails to match a tz-aware index.
    aligned = htf_df.reindex(target)
    aligned = aligned.ffill()
    aligned.index = base_index
    # an HTF bar that is not fully inside the data (last partial bucket) must
    # never leak: its completion time is beyond the data end for no base bar,
    # so the T + tf_htf <= t constraint already excludes it — ffill() only
    # propagates values that existed at valid T. Drop the partial tail bucket.
    last_htf_open = htf_df.index[-1]
    data_end = base_index[-1] + pd.Timedelta(seconds=tf_base_s)
    if last_htf_open + pd.Timedelta(seconds=tf_htf_s) > data_end:
        bad = target >= last_htf_open
        aligned[bad.values] = np.nan
    return aligned
