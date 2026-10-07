#!/usr/bin/env python3
"""Stand-in for dvgrab: prints status lines like a tapeless REC session."""
import os
import sys
import time

base = sys.argv[-1]
lines = [
    "Capture Started",
    f'"{base}2026.10.07_17-00-01.dv":     3.57 MiB    26 frames timecode 00:00:01.01 date 2026.10.07 17:00:01',
    f'"{base}2026.10.07_17-00-01.dv":     7.15 MiB    52 frames timecode 00:00:02.02 date 2026.10.07 17:00:02',
    "Capture Stopped",
]
for ln in lines:
    sys.stdout.write(ln + "\r\n" if "MiB" in ln else ln + "\n")
    sys.stdout.flush()
    time.sleep(0.05)
if os.environ.get("FAKE_DVGRAB_HOLD"):
    try:
        while True:  # keep "recording" until SIGINT, like dvgrab
            time.sleep(0.05)
    except KeyboardInterrupt:
        sys.exit(0)
sys.exit(1)  # simulate camera unplug
