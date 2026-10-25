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

gaps = d["host_ts"].diff()
print(f"gaps > 7 s: {int((gaps > 7).sum())}  (largest {gaps.max():.0f} s)")
print(f"reboots detected: {int((d['t_ms'].diff() < 0).sum())}")

for c in ("temp_c", "hum_pct"):
    print(f"{c}: min {d[c].min()}  max {d[c].max()}  mean {d[c].mean():.2f}  "
          f"std {d[c].std():.3f}  unique {d[c].nunique()}")
print(f"motion: {int(d['motion'].sum())} rows with motion ({d['motion'].mean():.1%})")