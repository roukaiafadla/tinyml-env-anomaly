"""Generate synthetic sensor data for pipeline development and testing.

Produces synthetic CSV data matching the schema of tools/serial_logger.py:
    host_ts,t_ms,temp_c,hum_pct,light_raw,motion[,label]

The generated signals approximate daily environmental patterns, including
temperature-humidity correlation, daylight-dependent illumination, and
increased motion probability during daytime. The --anomalies option injects
synthetic anomaly segments and assigns corresponding labels for testing
detection and evaluation code.

This generator is intended for software development and pipeline validation
only. Synthetic data does not represent real sensor measurements and must not
be used to claim or report real-world anomaly detection performance.

Examples:
    python tools/fake_esp32.py --hours 24 --out data/synthetic/fake_normal.csv
    python tools/fake_esp32.py --hours 2 --anomalies --seed 1 --start-hour 20 
        --out data/synthetic/fake_anomaly.csv
"""
import argparse
import os

import numpy as np
import pandas as pd

PERIOD_S = 5            # same sampling interval as the firmware
BASE_TS = 1_790_000_000  # arbitrary fixed start (unix seconds), keeps output reproducible


def ar1(rng, n, phi=0.995, sigma=0.05):
    """Slowly varying noise (real room temperature drifts, it isn't white noise)."""
    x = np.zeros(n)
    for i in range(1, n):
        x[i] = phi * x[i - 1] + rng.normal(0, sigma)
    return x


def generate(hours, seed, start_hour):
    rng = np.random.default_rng(seed)
    n = int(hours * 3600 / PERIOD_S)
    t_s = np.arange(n) * PERIOD_S
    hod = (t_s / 3600 + start_hour) % 24                      # hour of day

    # 0 at night, peaks at noon, zero again after 18:00
    daylight = np.clip(np.sin((hod - 6) / 12 * np.pi), 0, None)

    temp = 22 + 3 * np.sin(2 * np.pi * (hod - 9) / 24) + ar1(rng, n)   # peaks ~15:00
    hum = 55 - 1.5 * (temp - 22) + ar1(rng, n, sigma=0.15)
    # DHT11 only resolves whole degrees / whole %RH, so mimic that quantization
    temp = np.round(temp)
    hum = np.clip(np.round(hum), 20, 90)

    cloud = 1 - 0.3 * np.clip(ar1(rng, n, phi=0.999, sigma=0.1), 0, 1)
    light = 150 + 2500 * daylight * cloud + rng.normal(0, 40, n)
    light = np.clip(light, 0, 4095).astype(int)

    p_motion = 0.02 + 0.15 * daylight                           # people move around by day
    motion = (rng.random(n) < p_motion).astype(int)

    df = pd.DataFrame({
        "host_ts": BASE_TS + t_s,
        "t_ms": (t_s * 1000).astype("int64"),
        "temp_c": temp,
        "hum_pct": hum,
        "light_raw": light,
        "motion": motion,
    })
    return df, daylight, rng


def inject_anomalies(df, daylight, rng):
    """Overwrite short segments (30-60 s) with joint-behavior anomalies, label=1."""
    n = len(df)
    df["label"] = 0
    k = max(3, n // 1500)
    for _ in range(k):
        length = int(rng.integers(6, 13))
        s = int(rng.integers(0, n - length))
        sl = slice(s, s + length)
        kind = int(rng.integers(0, 4))
        if kind == 0:      # light contradicts time of day (lights on at night / dark at noon)
            night = daylight[s] < 0.3
            df.loc[df.index[sl], "light_raw"] = (3000 if night else 100) + rng.integers(-50, 50, length)
        elif kind == 1:    # heat source: temperature up, humidity down
            df.loc[df.index[sl], "temp_c"] += 8
            df.loc[df.index[sl], "hum_pct"] = np.clip(df["hum_pct"].iloc[sl] - 20, 5, 95)
        elif kind == 2:    # humidity spike (steam, breath on the sensor)
            df.loc[df.index[sl], "hum_pct"] = np.clip(df["hum_pct"].iloc[sl] + 30, 5, 99)
        else:              # sustained motion
            df.loc[df.index[sl], "motion"] = 1
        df.loc[df.index[sl], "label"] = 1
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=24)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--start-hour", type=float, default=0, help="hour of day at the first sample")
    ap.add_argument("--anomalies", action="store_true", help="inject labeled anomalies")
    ap.add_argument("--out", default="data/synthetic/fake_normal.csv")
    args = ap.parse_args()

    df, daylight, rng = generate(args.hours, args.seed, args.start_hour)
    if args.anomalies:
        df = inject_anomalies(df, daylight, rng)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    df.to_csv(args.out, index=False, float_format="%.1f")
    msg = f"Wrote {len(df)} rows to {args.out}"
    if args.anomalies:
        msg += f" ({int(df['label'].sum())} anomalous rows)"
    print(msg)


if __name__ == "__main__":
    main()