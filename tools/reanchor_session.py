"""Re-anchor host_ts of a single-boot offline dump to the real clock time.

Use when a dump was made without --start. Give EITHER the local time the board was
powered on (--start) OR the local time of the last logged row, for example the moment
you unplugged it (--end).

Usage:
    python tools/reanchor_session.py --in data/raw/classroom_raw_20261026.csv --out data/raw/session_20261026_HHMMSS_classroom.csv --end "2026-10-26 HH:MM:SS"
"""
import argparse
from datetime import datetime

import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--in", dest="inp", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--start", help="local time the board was powered on")
ap.add_argument("--end", help="local time of the last logged row (unplug time)")
args = ap.parse_args()
if bool(args.start) == bool(args.end):
    raise SystemExit("Give exactly one of --start or --end")

d = pd.read_csv(args.inp)
if (d["t_ms"].diff().dropna() < 0).any():
    raise SystemExit("t_ms is not monotonic (several boots or damaged values); cannot re-anchor safely")

fmt = "%Y-%m-%d %H:%M:%S"
if args.start:
    t0 = datetime.strptime(args.start, fmt).timestamp()   # power-on moment
    d["host_ts"] = (t0 + d["t_ms"] / 1000).round().astype(int)
else:
    t_end = datetime.strptime(args.end, fmt).timestamp()
    d["host_ts"] = (t_end - (d["t_ms"].iloc[-1] - d["t_ms"]) / 1000).round().astype(int)

d.to_csv(args.out, index=False)
print(f"wrote {len(d)} rows to {args.out}")
print("first row:", datetime.fromtimestamp(d["host_ts"].iloc[0]),
      "  last row:", datetime.fromtimestamp(d["host_ts"].iloc[-1]))