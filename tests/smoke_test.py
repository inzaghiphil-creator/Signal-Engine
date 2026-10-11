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
from backtester import indicators as I  # noqa: E402
from backtester import check_data, diagnose as DIAG, oos as OOS, compare as CMP  # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def _check_exit_slippage(df: pd.DataFrame, trades: pd.DataFrame, slip_pct: float) -> bool:
    """Recompute every trade's exit price: raw fill price per reason, then
    adverse slippage (long exits lower, short exits higher)."""
    if trades.empty:
        return True
    slip = slip_pct / 100.0
    o = df["open"].to_numpy(); h = df["high"].to_numpy(); l = df["low"].to_numpy(); c = df["close"].to_numpy()
    idx = df.index
    for _, t in trades.iterrows():
        i = idx.get_loc(t["exit_time"])
        long = t["side"] == "LONG"
        if t["exit_reason"] == "STOP":
            raw = o[i] if (o[i] < t["stop"] if long else o[i] > t["stop"]) else t["stop"]
        elif t["exit_reason"] == "TARGET":
            raw = o[i] if (o[i] > t["target"] if long else o[i] < t["target"]) else t["target"]
        else:  # REVERSAL / TREND FLIP — close-of-bar exit
            raw = c[i]
        exp = raw * (1 - slip) if long else raw * (1 + slip)
        if abs(exp - t["exit"]) > 1e-6:
            return False
    return True


def _gap_unit(df: pd.DataFrame, p: Params) -> tuple:
    """Force a single long entry, then bar+1 gaps below the stop."""
    import dataclasses
    mech = Mechanics(fee_pct=0.10, slippage_pct=0.02)
    sig = compute_signals(df, p)
    e = 100
    df2 = df.copy()
    atr_at_e = float(sig.atr.iloc[e])
    stop = float(df["close"].iloc[e]) - p.stop_atr * atr_at_e
    o2 = float(df["open"].iloc[e + 1])
    # gap case: open well below stop
    gap_open = stop - 0.5 * atr_at_e
    df2.loc[df2.index[e + 1], "open"] = gap_open
    df2.loc[df2.index[e + 1], "low"] = min(gap_open, float(df["low"].iloc[e + 1]))
    df2.loc[df2.index[e + 1], "close"] = gap_open
    df2.loc[df2.index[e + 1], "high"] = max(gap_open, float(df["high"].iloc[e + 1]))
    long_sig = pd.Series(False, index=df.index); long_sig.iloc[e] = True
    short_sig = pd.Series(False, index=df.index)
    sig2 = dataclasses.replace(sig, long_sig=long_sig, short_sig=short_sig)
    sig2_atr = sig2.atr  # unchanged
    trades, equity, open_pos = run_backtest(df2, sig2, p, mech)
    if trades.empty:
        return None, False
    t0 = trades.iloc[0]
    ok = (t0["exit_reason"] == "STOP"
          and abs(t0["exit"] - gap_open * (1 - 0.0002)) < 1e-6
          and t0["bars_held"] == 1)
    return t0, bool(ok)


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
    trades, equity, open_pos = run_backtest(df, sig, p, mech)
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
    trades_rev, equity_rev, open_pos_rev = run_backtest(df, sig_rev, p_rev, mech)
    check("engine runs (reversal)", isinstance(trades_rev, pd.DataFrame))

    # report renders
    m = compute_metrics(trades, equity, p, mech)
    rep = render_report(m, p, mech, {"label": "smoke", "bars": n, "tf": "5m",
                                     "start": str(df.index[0]), "end": str(df.index[-1])}, open_pos)
    check("report renders", "OVERALL" in rep or "NO TRADES" in rep)

    # ── V2: exit slippage on all fills ───────────────────────────────────
    check("exit slippage on all fills", _check_exit_slippage(df, trades, slip_pct=0.02))
    check("exit slippage on all fills (reversal)", _check_exit_slippage(df, trades_rev, slip_pct=0.02))

    # ── V2: filters actually filter ─────────────────────────────────────
    sig_base = compute_signals(df, p)
    p_room = Params(mode="SCALP", min_room_atr=999.0)
    sig_room = compute_signals(df, p_room)
    atr_e = sig_base.atr.to_numpy()
    subset = bool(
        (~sig_room.long_sig | sig_base.long_sig).all() and (~sig_room.short_sig | sig_base.short_sig).all()
    )
    # surviving signals may only come from bars with no valid pivot (BIG sentinel)
    surv_ok = bool(
        (~sig_room.long_sig | (sig_room.room_long.to_numpy() >= 999.0 * atr_e)).all()
        and (~sig_room.short_sig | (sig_room.room_short.to_numpy() >= 999.0 * atr_e)).all()
    )
    blocked_any = int((sig_base.long_sig & ~sig_room.long_sig).sum() + (sig_base.short_sig & ~sig_room.short_sig).sum()) > 0
    check("room filter blocks narrow-room entries", subset and surv_ok and blocked_any,
          f"subset={subset} surv_ok={surv_ok} blocked={blocked_any}")

    p_vol = Params(mode="SCALP", vol_spike=0.0)
    sig_vol = compute_signals(df, p_vol)
    # vol-sma warmup is measured in MID-TF bars (apavg comes from the 15m frame):
    cut = p.vol_sma_len * (p.tf_mid_s // p.tf_base_s) + 10
    all_abn = bool((sig_vol.regime.iloc[cut:] == 3).all())
    no_sig = bool((~sig_vol.long_sig.iloc[cut:]).all() and (~sig_vol.short_sig.iloc[cut:]).all())
    check("abnormal-vol block stops entries", all_abn and no_sig)

    p_vwap = Params(mode="SCALP", vwap_gate=True)
    sig_vwap = compute_signals(df, p_vwap)
    vwap = I.session_vwap(df)
    ok_l = bool((~sig_vwap.long_sig | (df["close"] > vwap)).all())
    ok_s = bool((~sig_vwap.short_sig | (df["close"] < vwap)).all())
    check("vwap gate invariant (long above / short below)", ok_l and ok_s)

    # ── V2: gap handling (forced signal, unit level) ─────────────────────
    g_trades, g_op = _gap_unit(df, p)
    check("gap below stop fills at open (with slippage)", g_trades is not None and g_op is True,
          str(None if g_trades is None else g_trades.to_dict()))

    # ── V2: no TREND FLIP exits in reversal mode ─────────────────────────
    check("no TREND FLIP exits in reversal mode", "TREND FLIP" not in set(trades_rev["exit_reason"]))

    # ── V2: per-side stats present ───────────────────────────────────────
    check("per-side stats in report", "LONG" in rep and "SHORT" in rep and "Avg bars held" in rep)

    # ── V2.1: data quality gate ──────────────────────────────────────────
    a = check_data.audit(df)
    check("check_data passes on clean data",
          a["missing"] == 0 and a["duplicates"] == 0 and a["ohlc_violations"] == 0
          and a["nan_prices"] == 0 and a["nonpositive_volume"] == 0)
    w = check_data.window_stats(df, df.index[0], df.index[500])
    check("window stats computed", w is not None and w["bars"] == 501)

    # ── V2.1: loss diagnosis ─────────────────────────────────────────────
    d = DIAG.classify(trades, df, sig, p)
    ok = (len(d) == len(trades)
          and d["fail_reason"].notna().all()
          and set(d["fail_reason"]) <= {"COST-DOMINATED", "NOISE STOP", "FAILED BREAKOUT",
                                        "PREMATURE REVERSAL", "REVERSAL EXIT (trend held)",
                                        "STOP (developed)", "TARGET", "REVERSAL EXIT",
                                        "TREND FLIP", "LOW-VOL CHOP"}
          and d["mfe_r"].ge(0).all())
    check("diagnosis classifies every trade", bool(ok))
    cs = DIAG.cost_sensitivity(trades, df)
    base = cs[(cs["fee_%"] == mech.fee_pct) & (cs["slippage_%"] == mech.slippage_pct)].iloc[0]
    actual_net = float(trades["net"].sum())
    check("cost-sensitivity base cell == actual net",
          abs(base["net"] - actual_net) < max(1.0, 0.005 * abs(actual_net)),
          f"base={base['net']} actual={actual_net}")
    rep_d = DIAG.diagnose(df, trades, sig, p, mech)
    check("diagnosis report renders", "FAILURE TAXONOMY" in rep_d and "COST SENSITIVITY" in rep_d)

    # ── V2.1: out-of-sample protocol ─────────────────────────────────────
    out_oos = OOS.oos(df, "SCALP", df.index[len(df) * 2 // 3].normalize(), min_trades=30, top_n=3)
    check("OOS protocol runs and evaluates gates",
          "ACCEPTANCE GATES" in out_oos and "TEST-WINDOW CONSISTENCY" in out_oos
          and out_oos.count("PASS") + out_oos.count("FAIL") >= 6)

    # ── V2.1: TradingView compare (self-consistency) ─────────────────────
    import tempfile, os
    with tempfile.TemporaryDirectory() as td:
        pyf = os.path.join(td, "py.csv")
        tvf = os.path.join(td, "tv.csv")
        trades.to_csv(pyf, index=False)
        rng = np.random.default_rng(3)
        tv = pd.DataFrame({
            "Date/Time (open)": trades["entry_time"].astype(str),
            "Type": np.where(trades["side"] == "LONG", "Buy", "Sell"),
            "Price": trades["entry"].to_numpy() + rng.integers(1, 4, size=len(trades)) * 0.0001,
            "Contracts": trades["qty"].to_numpy(),
            "Closed Date/Time": trades["exit_time"].astype(str),
            "P&L": trades["net"].to_numpy(),
        })
        tv.to_csv(tvf, index=False)
        tv_loaded = CMP.load_tv_trades(tvf, 300, "UTC")
        py_loaded = pd.read_csv(pyf)
        py_loaded["entry_time"] = pd.to_datetime(py_loaded["entry_time"], utc=True)
        py_loaded["exit_time"] = pd.to_datetime(py_loaded["exit_time"], utc=True)
        out_cmp = CMP.compare(py_loaded, tv_loaded, 300, 1, 0.05)
        check("compare matches self-generated TV export", "VERDICT: MATCH" in out_cmp
              and "side mismatches: 0" in out_cmp)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
