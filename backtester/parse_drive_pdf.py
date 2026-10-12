"""Rebuild a 5m OHLCV CSV from the user's 'data 5 min.pdf' (Google Drive export).

PDF layout: text dump, header 'time open high low close volume' repeated on
each page (~176 data lines/page, 194 pages). Each data line is
'<epoch_ms in 6-sig-digit scientific notation> open high low close volume',
e.g. '1.79167E+12 5.323 5.332 5.308 5.331 91310.1'.

The displayed epoch is rounded to 6 significant digits, so each value carries
up to ~+/-5e6 ms (83 min) of rounding error. The true 5m grid is recovered as
the set of 5-minute-aligned t0 values consistent with EVERY displayed epoch
(t_i = t0 + 300000*i within that epoch's own rounding window), then
disambiguated in favour of the hour-aligned start, verified by the 1h
resample bar count.

Usage:
    python -m backtester.parse_drive_pdf <pdf_path> <out_csv> [--expect-bars N]

--expect-bars: if given, the candidate t0 must produce exactly N 1h bars in
the resample; the candidate is printed for verification either way.
"""
from __future__ import annotations

import argparse
import re
import sys

import pandas as pd
from pypdf import PdfReader

ROW = re.compile(
    r"(\d\.\d{1,6}E\+\d{2,3})"                        # epoch ms, 6-sig sci
    r"\s+(\d+(?:\.\d+)?)"                             # open
    r"\s+(\d+(?:\.\d+)?)"                             # high
    r"\s+(\d+(?:\.\d+)?)"                             # low
    r"\s+(\d+(?:\.\d+)?)"                             # close
    r"\s+(\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)"            # volume
)

STEP_MS = 300_000          # 5m grid


def parse_pdf(pdf_path: str) -> list[tuple]:
    r = PdfReader(pdf_path)
    text = "\n".join((p.extract_text() or "") for p in r.pages)
    text = re.sub(r"\s+", " ", text)
    return ROW.findall(text)


def half_ulp(epoch_str: str) -> int:
    """Half the last displayed digit's place value. '1.78334E+12' has 5
    digits after the point -> ulp 1e7 ms -> half-ulp 5e6 ms (the export
    rounds to 6 significant digits, so most epochs carry ~+/-83 min)."""
    k = len(epoch_str.split(".")[1].split("E")[0])
    return 10 ** (12 - k) // 2 + 1


def candidate_t0s(rows: list[tuple]) -> list[int]:
    """5-minute-aligned t0 values consistent with EVERY displayed epoch
    (each within its own rounding window)."""
    shown = [int(float(e)) for e, *_ in rows]
    ws = [half_ulp(e) for e, *_ in rows]
    lo = max(d - STEP_MS * i - w for i, (d, w) in enumerate(zip(shown, ws)))
    hi = min(d - STEP_MS * i + w for i, (d, w) in enumerate(zip(shown, ws)))
    if hi < lo:
        return []
    first = (lo // STEP_MS + 1) * STEP_MS
    return list(range(first, hi + 1, STEP_MS))


def resample_1h_range(t0: int, n: int) -> tuple[pd.Timestamp, pd.Timestamp, int]:
    idx = pd.to_datetime(
        [t0 + STEP_MS * i for i in range(n)], unit="ms", utc=True
    )
    s = pd.Series(idx, index=idx)
    h1 = s.groupby(s.dt.floor("h")).last()
    return h1.index[0], h1.index[-1], len(h1)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pdf")
    ap.add_argument("out")
    ap.add_argument("--expect-bars", type=int, default=None,
                    help="required count of 1h bars in the resample")
    args = ap.parse_args(argv)

    rows = parse_pdf(args.pdf)
    n = len(rows)
    print(f"parsed {n} data rows from {args.pdf}")
    if n < 100:
        raise SystemExit("suspiciously few rows — inspect PDF text")

    cands = candidate_t0s(rows)
    print(f"{len(cands)} candidate 5m-aligned start(s) consistent with all epochs")
    if not cands:
        raise SystemExit("no consistent grid — PDF format changed?")
    med = int(pd.Series(
        [int(float(e)) - STEP_MS * i for i, (e, *_r) in enumerate(rows)]
    ).median())
    for t0 in cands:
        s0, s1, nb = resample_1h_range(t0, n)
        tag = ""
        if args.expect_bars and nb != args.expect_bars:
            tag = "  <-- WRONG bar count"
        print(f"  t0={t0} ({pd.Timestamp(t0, unit='ms', tz='UTC')}) "
              f"-> 1h resample {nb} bars {s0} .. {s1}{tag}")
    # disambiguate: hour-aligned starts (the established grid), then closest
    # to the median of the de-trended displayed epochs
    hour = [t0 for t0 in cands if t0 % 3_600_000 == 0]
    pool = hour if hour else cands
    t0 = min(pool, key=lambda t: abs(t - med))
    if not hour:
        print("WARNING: no hour-aligned candidate — using median-closest")
    s0, s1, nb = resample_1h_range(t0, n)
    if args.expect_bars and nb != args.expect_bars:
        raise SystemExit(f"chosen t0 gives {nb} 1h bars, expected {args.expect_bars}")

    with open(args.out, "w") as f:
        f.write("time,open,high,low,close,volume\n")
        for i, (_e, o, h, l, c, v) in enumerate(rows):
            f.write(f"{t0 + STEP_MS * i},{o},{h},{l},{c},{v}\n")
    s0, s1, nb = resample_1h_range(t0, n)
    print(f"wrote {args.out}: {n} rows, first {pd.Timestamp(t0, unit='ms', tz='UTC')}, "
          f"1h resample {nb} bars {s0} .. {s1}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
