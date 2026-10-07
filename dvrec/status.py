"""Parse dvgrab console output into recorder state."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict

# "clip-2026.10.07_17-00-01.dv":    12.34 MiB    90 frames timecode 00:00:03.15 date 2026.10.07 17:00:01
_FILE_RE = re.compile(
    r'^"(?P<file>[^"]+)":\s+(?P<mib>[\d.]+)\s+MiB\s+(?P<frames>\d+)\s+frames'
    r'(?:\s+timecode\s+(?P<tc>\S+))?(?:\s+date\s+(?P<date>.+?))?\s*$'
)


@dataclass
class RecorderState:
    state: str = "idle"          # idle | standby | waiting | recording | paused | error | stopped
    file: str | None = None
    size_mib: float = 0.0
    frames: int = 0
    timecode: str | None = None
    date: str | None = None
    clips: list[str] = field(default_factory=list)
    message: str | None = None
    rec_since: float | None = None   # time.monotonic() 녹화 시작 시각

    def to_dict(self) -> dict:
        return asdict(self)


def apply_line(st: RecorderState, line: str) -> str | None:
    """Update state from one dvgrab line; return an event name if notable."""
    line = line.strip()
    if not line:
        return None

    m = _FILE_RE.match(line)
    if m:
        st.file = m["file"]
        st.size_mib = float(m["mib"])
        st.frames = int(m["frames"])
        st.timecode = m["tc"]
        st.date = m["date"]
        st.state = "recording"
        if st.file not in st.clips:
            st.clips.append(st.file)
            return "clip"
        return "progress"

    low = line.lower()
    if "capture started" in low:
        st.state = "recording"
        return "started"
    if "capture stopped" in low:
        st.state = "paused"
        return "stopped"
    if "waiting for dv" in low:
        st.state = "waiting"
        return "waiting"
    if low.startswith("error") or "no camera" in low or "not found" in low:
        st.state = "error"
        st.message = line
        return "error"
    return None
