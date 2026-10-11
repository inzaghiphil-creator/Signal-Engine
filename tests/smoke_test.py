"""Smoke tests for the Python backtester (no pytest dependency).

Run:  python tests/smoke_test.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from backtester import data as D  # noqa: E402
from backtester.engine import Mechanics, run_backtest  # noqa: E402
from backtester.report import compute_metrics, render_report  # noqa: E402
from backtester.sample_data import generate  # noqa: E402
from backtester.signals import Params, compute_signals  # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def main() -> int:
    df = generate(days=60, seed=7)
    check("sample data shape", df.shape[0] == 60 * 288 and (df["high"] >= df[["open", "close"]].max(axis=1) - 1e-12).all())
    check("tf detection", D.detect_tf_seconds(df) == 300)

    p = Params(mode="SCALP")
    sig = compute_signals(df, p)
    n = len(df)
    warm = 300  # skip indicator warmup region

    s_l = sig.score_long.iloc[warm:].to_numpy()
    s_s = sig.score_short.iloc[warm:].to_numpy()
    check("scores bounded [0,100]", bool(((s_l >= -1e-9) & (s_l <= 100 + 1e-9)).all() and ((s_s >= -1e-9) & (s_s <= 100 + 1e-9)).all()))
    check("no NaN scores after warmup", bool(np.isfinite(s_l).all() and np.isfinite(s_s).all()))
    check("regime labels valid", set(sig.regime_label.iloc[warm:].unique()) <= {"TRENDING UP", "TRENDING DOWN", "RANGING", "ABNORMAL VOL"})
    check("bias/trend values valid", set(sig.bias45.unique()) <= {-1, 0, 1} and set(sig.trend45.unique()) <= {-1, 0, 1})
    check("no simultaneous long+short signals", bool((~(sig.long_sig & sig.short_sig)).all()))

    # ── NON-REPAINT: truncation test ──────────────────────────────────────
    # Signals computed on a truncated prefix must be identical for every bar
    # of that prefix (no future data anywhere in the pipeline).
    for cut in (1500, 4000):
        sig_cut = compute_signals(df.iloc[:cut], p)
        ok = True
        ok &= bool(np.allclose(sig_cut.score_long.to_numpy(), sig.score_long.iloc[:cut].to_numpy(), equal_nan=True))
        ok &= bool(np.allclose(sig_cut.score_short.to_numpy(), sig.score_short.iloc[:cut].to_numpy(), equal_nan=True))
        ok &= bool((sig_cut.long_sig.to_numpy() == sig.long_sig.iloc[:cut].to_numpy()).all())
        ok &= bool((sig_cut.short_sig.to_numpy() == sig.short_sig.iloc[:cut].to_numpy()).all())
        ok &= bool((sig_cut.regime.to_numpy() == sig.regime.iloc[:cut].to_numpy()).all())
        check(f"non-repaint truncation @ {cut}", ok)

    # ── engine sanity ─────────────────────────────────────────────────────
    mech = Mechanics(fee_pct=0.10, slippage_pct=0.02)
    trades, equity = run_backtest(df, sig, p, mech)
    check("engine runs (scalp)", isinstance(trades, pd.DataFrame) and equity.shape[0] >= 1)
    if not trades.empty:
        t0 = trades.iloc[0]
        slip = 0.0002
        raw_close = float(df["close"].loc[t0["entry_time"]])
        implied = t0["entry"] / (1 + slip) if t0["side"] == "LONG" else t0["entry"] / (1 - slip)
        # trade prices are stored rounded to 8dp — allow for that
        check("entry at signal-bar close", abs(implied - raw_close) < 1e-6,
              f"side={t0['side']} entry={t0['entry']} close={raw_close}")
        check("stop distance = 1.2*ATR (long)",
              abs((t0["entry"] / (1 + 0.0002) - t0["stop"]) / t0["atr"] - 1.2) < 1e-4)
        check("target distance = 1.8*ATR",
              abs((t0["target"] - t0["entry"] / (1 + 0.0002)) / t0["atr"] - 1.8) < 1e-4)
        check("net = gross - fees", bool(np.allclose(trades["net"], trades["gross"] - trades["fees"], atol=2e-4)))
        check("regime attribution valid", set(trades["regime"]) <= {"TRENDING UP", "TRENDING DOWN", "RANGING", "ABNORMAL VOL"})

    # reversal mode runs end-to-end
    p_rev = Params(mode="REVERSAL")
    sig_rev = compute_signals(df, p_rev)
    trades_rev, equity_rev = run_backtest(df, sig_rev, p_rev, mech)
    check("engine runs (reversal)", isinstance(trades_rev, pd.DataFrame))

    # report renders
    m = compute_metrics(trades, equity, p, mech)
    rep = render_report(m, p, mech, {"label": "smoke", "bars": n, "tf": "5m",
                                     "start": str(df.index[0]), "end": str(df.index[-1])})
    check("report renders", "OVERALL" in rep or "NO TRADES" in rep)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
