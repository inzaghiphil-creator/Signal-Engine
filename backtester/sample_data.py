"""Synthetic NEAR-like 5m OHLCV generator (for pipeline validation ONLY).

Produces a clearly-synthetic series with alternating trending / ranging /
volatility-spike regimes so every code path (all four regimes, both signal
modes, stops, targets, reversals) gets exercised. NOT a simulation of real
NEAR price action — never use its results as a performance claim.

Usage:
    python -m backtester.sample_data --out data/sample_near_5m_synth.csv --days 100
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

BARS_PER_DAY = 288  # 5m bars


def generate(days: int = 100, seed: int = 42, start_price: float = 5.0, tf_seconds: int = 300) -> pd.DataFrame:
    n = days * BARS_PER_DAY
    rng = np.random.default_rng(seed)

    # regime cycle every 10 days: up-trend, range, down-trend, range, up+spike, down+spike
    block_days = 10
    blocks = [
        {"drift": 0.00035, "vol": 0.0016},
        {"drift": 0.0, "vol": 0.0011},
        {"drift": -0.00035, "vol": 0.0016},
        {"drift": 0.0, "vol": 0.0011},
        {"drift": 0.00045, "vol": 0.0035},
        {"drift": -0.00045, "vol": 0.0035},
    ]
    block_bars = block_days * BARS_PER_DAY
    cycles = n // (len(blocks) * block_bars) + 1
    drift = np.tile(np.repeat([b["drift"] for b in blocks], block_bars), cycles)[:n]
    vol = np.tile(np.repeat([b["vol"] for b in blocks], block_bars), cycles)[:n]

    # slow sinusoidal regime modulation so transitions are not knife-edges
    t = np.arange(n)
    drift = drift + 0.00012 * np.sin(2 * np.pi * t / (5 * BARS_PER_DAY))

    rets = drift + rng.normal(0.0, 1.0, n) * vol
    # occasional gaps
    gaps = np.zeros(n)
    gap_mask = rng.random(n) < 0.02
    gaps[gap_mask] = rng.normal(0.0, vol[gap_mask])
    rets = rets + gaps

    close = start_price * np.exp(np.cumsum(rets))
    open_ = np.empty(n)
    open_[0] = start_price
    open_[1:] = close[:-1] * (1 + gaps[1:] * 0.5)

    spread = np.abs(rng.normal(0.0, 1.0, n)) * vol * 0.6
    high = np.maximum(open_, close) * (1 + spread)
    low = np.minimum(open_, close) * (1 - spread)

    volume = 1000.0 * np.exp(rng.normal(0.0, 0.35, n)) * (1 + 30 * np.abs(rets))
    volume[gap_mask] *= 2.5

    start = pd.Timestamp("2026-06-01 00:00:00", tz="UTC")
    idx = pd.date_range(start=start, periods=n, freq=pd.Timedelta(seconds=tf_seconds), tz="UTC")
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=idx,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Generate a synthetic 5m OHLCV CSV (pipeline validation only)")
    ap.add_argument("--out", default="data/sample_near_5m_synth.csv")
    ap.add_argument("--days", type=int, default=100)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--start-price", type=float, default=5.0)
    args = ap.parse_args(argv)

    df = generate(days=args.days, seed=args.seed, start_price=args.start_price)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out_df = df.copy()
    out_df.index.name = "time"
    out_df.index = out_df.index.strftime("%Y-%m-%d %H:%M:%S")
    out_df.to_csv(out)
    print(f"wrote {len(df)} bars to {out}  ({df.index[0]} → {df.index[-1]} UTC) — SYNTHETIC DATA, pipeline validation only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
