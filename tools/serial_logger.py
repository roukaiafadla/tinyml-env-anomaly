"""Serial-to-CSV logger for the ESP32 data logger firmware.

Reads lines from the ESP32 over USB serial and writes a CSV with an extra
host timestamp column. The ESP32 has no RTC and its millis() counter resets on
every reboot, so host_ts (unix seconds) is the only reliable time reference.

Usage:
    python tools/serial_logger.py --port COM3
"""
import argparse
import os
import time
from datetime import datetime

import serial  # pip install pyserial

HEADER_PREFIX = "t_ms"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True, help="e.g. COM3 (Windows), /dev/ttyUSB0 (Linux)")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--out", default=None, help="output CSV path (default: auto-named in data/raw)")
    args = ap.parse_args()

    out = args.out or f"data/raw/session_{datetime.now():%Y%m%d_%H%M%S}.csv"
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    header_written = os.path.exists(out) and os.path.getsize(out) > 0

    print(f"Logging to {out} (Ctrl+C to stop)")
    while True:
        try:
            # Opening the port toggles DTR and reboots the ESP32, so the header
            # line will be printed again; we write it only once.
            with serial.Serial(args.port, args.baud, timeout=2) as ser, \
                 open(out, "a", buffering=1, encoding="utf-8") as f:
                while True:
                    line = ser.readline().decode(errors="ignore").strip()
                    if not line:
                        continue
                    if line.startswith("#"):              # firmware diagnostics
                        f.write(line + "\n")
                    elif line.startswith(HEADER_PREFIX):  # CSV header
                        if not header_written:
                            f.write("host_ts," + line + "\n")
                            header_written = True
                    elif line[0].isdigit():               # data row
                        f.write(f"{int(time.time())},{line}\n")
                    print(line)
        except serial.SerialException as e:
            print(f"Serial error ({e}); retrying in 2 s...")
            time.sleep(2)
        except KeyboardInterrupt:
            print("Stopped.")
            break


if __name__ == "__main__":
    main()