"""Quick quality report for a logged session CSV.

Usage:
    python tools/check_session.py data/raw/session_X.csv
"""
import sys

import pandas as pd

path = sys.argv[1]
d = pd.read_csv(path, comment="#")
ts = pd.to_datetime(d["host_ts"], unit="s", utc=True)
dur_h = (d["host_ts"].iloc[-1] - d["host_ts"].iloc[0]) / 3600

print(f"file: {path}")
print(f"rows: {len(d)}   duration: {dur_h:.2f} h   expected rows: {int(dur_h * 720) + 1}")
print(f"start (UTC): {ts.iloc[0]}   end (UTC): {ts.iloc[-1]}")

dh = d["host_ts"].diff()
dt = d["t_ms"].diff()
print(f"gaps > 7 s (PC clock): {int((dh > 7).sum())}  (largest {dh.max():.0f} s)")

# A real reboot restarts t_ms AND leaves a hole of 30+ s (the PIR warm-up).
# A t_ms drop with no hole is a damaged number (leading digits lost in transit).
drop = dt < 0
print(f"reboots detected: {int((drop & (dh > 20)).sum())}")
print(f"t_ms glitches (drop, no hole): {int((drop & (dh <= 20)).sum())}")
print(f"rows with a missing field: {int(d.isna().any(axis=1).sum())}")

for c in ("temp_c", "hum_pct"):
    print(f"{c}: min {d[c].min()}  max {d[c].max()}  mean {d[c].mean():.2f}  "
          f"std {d[c].std():.3f}  unique {d[c].nunique()}")
print(f"motion: {int(d['motion'].sum())} rows with motion ({d['motion'].mean():.1%})")