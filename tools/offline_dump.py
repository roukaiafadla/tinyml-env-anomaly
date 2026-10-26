"""Dump the rows stored by firmware/offline_logger over serial and write a CSV in the same
format as tools/serial_logger.py (host_ts,t_ms,temp_c,hum_pct,motion).

Every stored row carries an XOR checksum. Rows that arrive damaged are requested again
(up to 8 times); rows that never arrive intact are reported as missing, never guessed.

Close Serial Monitor and any other logger first (only one program can use the port).

Usage:
    python tools/offline_dump.py --port COM4 --start "2026-10-26 09:05:30"
    python tools/offline_dump.py --port COM4 --start "2026-10-26 09:05:30" --erase

--start is the LOCAL time at which the board was first powered on. Without it, times are
anchored to "now" and only approximate. After a power loss the clock restarts; boots are
assumed to follow each other with a 3 s gap, so times after a reboot are approximate.
"""
import argparse
import csv
import os
import re
import sys
import time
from datetime import datetime

import serial  # pip install pyserial

REC = 32
BLOCK = 100
RETRIES = 8
REBOOT_GAP_S = 3.0


def checksum_ok(line):
    if len(line) != REC - 1 or line[-3] != "*":
        return False
    x = 0
    for ch in line[:-3]:
        x ^= ord(ch)
    return f"{x:02X}" == line[-2:].upper()


def parse(line):
    return {"boot": int(line[0:3]), "t_ms": int(line[4:14]),
            "temp": float(line[15:20]), "hum": float(line[21:26]), "motion": int(line[27])}


def request(ser, i, n):
    ser.reset_input_buffer()
    ser.write(f"GET {i} {n}\n".encode())
    lines = []
    deadline = time.time() + 5 + n * 0.1
    while time.time() < deadline:
        raw = ser.readline()
        if not raw:
            continue
        s = raw.decode(errors="ignore").strip("\r\n")
        if s.startswith("#END"):
            break
        if s.startswith("#") or not s:
            continue
        lines.append(s)
    return lines


def fetch_one(ser, k):
    for _ in range(RETRIES):
        lines = request(ser, k, 1)
        if len(lines) == 1 and checksum_ok(lines[0]):
            return lines[0]
    return None


def fetch_block(ser, i, n):
    lines = request(ser, i, n)
    if len(lines) == n and all(checksum_ok(l) for l in lines):
        return lines
    return [fetch_one(ser, k) for k in range(i, i + n)]   # fall back to row by row


def connect(port):
    ser = serial.Serial(port, 115200, timeout=0.5)   # opening the port resets the ESP32
    t0 = time.time()
    while time.time() - t0 < 25:
        ser.write(b"HELLO\n")
        time.sleep(0.25)
        if "#SERVICE" in ser.read_all().decode(errors="ignore"):
            time.sleep(0.5)
            ser.reset_input_buffer()
            return ser
    sys.exit("No answer from the board. Is it flashed with offline_logger, and is the port free?")


def get_info(ser):
    for _ in range(5):
        ser.reset_input_buffer()
        ser.write(b"INFO\n")
        t0 = time.time()
        while time.time() - t0 < 3:
            s = ser.readline().decode(errors="ignore")
            m = re.search(r"#INFO,rows=(\d+),rec=(\d+),boot=(\d+),free=(\d+)", s)
            if m:
                return tuple(int(g) for g in m.groups())
    sys.exit("Could not read INFO from the board.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--start", default=None, help='local time of first power-on, "YYYY-MM-DD HH:MM:SS"')
    ap.add_argument("--out", default=None)
    ap.add_argument("--erase", action="store_true", help="erase the board's log after a COMPLETE dump")
    ap.add_argument("--force", action="store_true", help="with --erase: erase even if rows are missing")
    args = ap.parse_args()

    ser = connect(args.port)
    rows_n, rec, boot, free = get_info(ser)
    if rec != REC:
        sys.exit(f"Record size mismatch (board {rec}, tool {REC}).")
    print(f"board: {rows_n} rows stored, boot counter {boot}, {free} bytes free")
    if rows_n == 0:
        print("Nothing to dump.")
        return

    recs, missing = [], []
    for i in range(0, rows_n, BLOCK):
        n = min(BLOCK, rows_n - i)
        for k, line in enumerate(fetch_block(ser, i, n)):
            if line is None:
                missing.append(i + k)
                continue
            try:
                recs.append(parse(line))
            except ValueError:
                missing.append(i + k)
        print(f"\r  {min(i + n, rows_n)}/{rows_n} rows", end="", flush=True)
    print()
    if not recs:
        sys.exit("No valid rows received.")

    # Rebuild PC-clock timestamps: each boot starts when the previous one ended.
    start_ts = datetime.strptime(args.start, "%Y-%m-%d %H:%M:%S").timestamp() if args.start else 0.0
    host, prev_boot, boot_start, last = [], None, 0.0, 0.0
    for r in recs:
        if r["boot"] != prev_boot:
            boot_start = start_ts if prev_boot is None else last + REBOOT_GAP_S
            prev_boot = r["boot"]
        last = boot_start + r["t_ms"] / 1000.0
        host.append(last)
    if not args.start:
        shift = time.time() - host[-1]
        host = [h + shift for h in host]
        print("WARNING: no --start given; times are anchored to now and approximate")

    out = args.out or f"data/raw/session_{datetime.fromtimestamp(host[0]):%Y%m%d_%H%M%S}_offline.csv"
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["host_ts", "t_ms", "temp_c", "hum_pct", "motion"])
        for h, r in zip(host, recs):
            w.writerow([int(round(h)), r["t_ms"], f"{r['temp']:.1f}", f"{r['hum']:.1f}", r["motion"]])
    print(f"wrote {len(recs)} rows to {out}")
    print(f"boots found: {sorted(set(r['boot'] for r in recs))}   missing rows: {len(missing)}"
          + (f"  (first: {missing[:10]})" if missing else ""))

    if args.erase:
        if missing and not args.force:
            print("NOT erasing: some rows are missing. Dump again, or add --force.")
        else:
            ser.write(b"ERASE\n")
            t0 = time.time()
            while time.time() - t0 < 5:
                if "#OK" in ser.readline().decode(errors="ignore"):
                    print("board log erased")
                    break
    ser.close()


if __name__ == "__main__":
    main()