"""Front panel for a Raspberry Pi recorder box: 128x64 OLED + push buttons.

Pages (Open MRU style): RECORD / STORAGE / NETWORK / POWER.
Hardware libraries (luma.oled, gpiozero) are optional; without them the panel
falls back to printing page changes on the console.
"""

from __future__ import annotations

import logging
import shutil
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .devices import find_cameras
from .recorder import Recorder

log = logging.getLogger("dvrec.panel")

PAGES = ("RECORD", "STORAGE", "NETWORK", "POWER")
POWER_CHOICES = ("Cancel", "Shutdown", "Reboot")
DV_GB_PER_HOUR = 13.0


@dataclass
class PanelConfig:
    display: str = "console"      # oled | console | none
    driver: str = "ssd1306"       # ssd1306 | sh1106
    i2c_port: int = 1
    i2c_address: int = 0x3C
    btn_rec: int | None = 17      # BCM 핀 번호, None이면 미사용
    btn_page: int | None = 27
    btn_select: int | None = 22
    refresh_hz: float = 4.0


@dataclass
class Snapshot:
    camera: bool
    state: str
    armed: bool
    mode: str
    elapsed: float
    clips: int
    total_gb: float
    used_gb: float
    free_gb: float
    ip: str | None
    hostname: str


def fmt_elapsed(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def fmt_remaining(free_gb: float) -> str:
    minutes = int(free_gb / DV_GB_PER_HOUR * 60)
    return f"{minutes // 60}h{minutes % 60:02d}m" if minutes >= 60 else f"{minutes}m"


def render(page: str, snap: Snapshot, power_choice: int = 0) -> list[str]:
    """Return up to 4 text lines (~21 chars each) for a 128x64 display."""
    pct = int(snap.free_gb / snap.total_gb * 100) if snap.total_gb else 0
    header = f"{page:<8}{pct:>3}% {fmt_remaining(snap.free_gb):>7}"

    if page == "RECORD":
        if not snap.camera:
            big = "NO CAM"
        elif snap.state == "recording":
            big = fmt_elapsed(snap.elapsed)
        elif snap.state == "error":
            big = "ERROR"
        else:
            big = "STBY"
        status = {"recording": "* REC", "paused": "PAUSE"}.get(snap.state, snap.state.upper())
        return [header, "", big, f"{status:<10}clips {snap.clips:>3}"]
    if page == "STORAGE":
        return [header, f"Total: {snap.total_gb:6.1f} GB",
                f"Used:  {snap.used_gb:6.1f} GB", f"Free:  {snap.free_gb:6.1f} GB"]
    if page == "NETWORK":
        return [header, "IP address:", snap.ip or "(none)", f"{snap.hostname}.local"]
    if page == "POWER":
        opts = [("> " if i == power_choice else "  ") + c for i, c in enumerate(POWER_CHOICES)]
        return [header] + opts
    raise ValueError(page)


def local_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # no packet is sent
            return s.getsockname()[0]
    except OSError:
        return None


# ---- display backends ---------------------------------------------------

class ConsoleDisplay:
    """Prints the screen when it changes (at most every 10 s while only the timer ticks)."""

    def __init__(self):
        self._key = None
        self._at = 0.0

    def show(self, lines: list[str], big_line: int | None = None) -> None:
        key = tuple(ln for i, ln in enumerate(lines) if i not in (0, big_line))
        now = time.monotonic()
        if key == self._key and now - self._at < 10:
            return
        self._key, self._at = key, now
        print("┌" + "─" * 22 + "┐")
        for ln in lines:
            print(f"│ {ln:<21}│")
        print("└" + "─" * 22 + "┘", flush=True)

    def close(self) -> None:
        pass


class OledDisplay:
    def __init__(self, cfg: PanelConfig):
        from luma.core.interface.serial import i2c
        from luma.core.render import canvas
        from luma.oled import device as oled
        from PIL import ImageFont

        serial = i2c(port=cfg.i2c_port, address=cfg.i2c_address)
        self._dev = getattr(oled, cfg.driver)(serial)
        self._canvas = canvas
        self._font = ImageFont.load_default()
        try:
            self._big = ImageFont.load_default(size=20)
        except TypeError:  # Pillow < 10.1
            self._big = self._font

    def show(self, lines: list[str], big_line: int | None = None) -> None:
        with self._canvas(self._dev) as draw:
            y = 0
            for i, ln in enumerate(lines):
                if i == big_line:
                    draw.text((4, y), ln, font=self._big, fill="white")
                    y += 22
                else:
                    draw.text((0, y), ln, font=self._font, fill="white")
                    y += 12 if i else 16
            draw.line((0, 13, 127, 13), fill="white")

    def close(self) -> None:
        self._dev.cleanup()


# ---- panel controller ---------------------------------------------------

class Panel:
    def __init__(self, recorder: Recorder, cfg: PanelConfig, power_cmd=None):
        self.rec = recorder
        self.cfg = cfg
        self.page = 0
        self.power_choice = 0
        self._stop = threading.Event()
        self._buttons = []
        self._select_was_held = False
        self._power_cmd = power_cmd or self._system_power
        self.display = self._make_display()

    def _make_display(self):
        if self.cfg.display == "oled":
            try:
                return OledDisplay(self.cfg)
            except Exception as e:  # missing library or no I2C device
                log.warning("OLED 초기화 실패 (%s) — 콘솔 표시로 전환", e)
        return ConsoleDisplay() if self.cfg.display != "none" else None

    def _setup_buttons(self) -> None:
        pins = {"rec": self.cfg.btn_rec, "page": self.cfg.btn_page, "select": self.cfg.btn_select}
        if not any(p is not None for p in pins.values()):
            return
        try:
            from gpiozero import Button
        except ImportError:
            log.warning("gpiozero 미설치 — 버튼 비활성화 (sudo apt install python3-gpiozero)")
            return
        handlers = {"rec": self.on_rec, "page": self.on_page}
        for name, pin in pins.items():
            if pin is None:
                continue
            try:
                b = Button(pin, bounce_time=0.05, hold_time=2.0)
            except Exception as e:
                log.warning("GPIO%s 버튼 초기화 실패: %s", pin, e)
                continue
            if name == "select":
                b.when_released = self._select_released
                b.when_held = self.on_select_hold
            else:
                b.when_pressed = handlers[name]
            self._buttons.append(b)

    def _select_released(self) -> None:
        if self._select_was_held:
            self._select_was_held = False
        else:
            self.on_select()

    # button handlers
    def on_rec(self) -> None:
        threading.Thread(target=self.rec.toggle_record, daemon=True).start()
        self.page = 0

    def on_page(self) -> None:
        self.page = (self.page + 1) % len(PAGES)
        self.power_choice = 0

    def on_select(self) -> None:
        """POWER 페이지: 짧게 누르면 다음 항목."""
        if PAGES[self.page] == "POWER":
            self.power_choice = (self.power_choice + 1) % len(POWER_CHOICES)

    def on_select_hold(self) -> None:
        """POWER 페이지: 2초 누르면 선택 항목 실행."""
        self._select_was_held = True
        if PAGES[self.page] != "POWER":
            return
        choice = POWER_CHOICES[self.power_choice]
        if choice == "Cancel":
            self.page = self.power_choice = 0
        else:
            self._execute_power(choice)

    def _execute_power(self, choice: str) -> None:
        log.info("%s 요청 — 녹화를 안전하게 종료합니다", choice)
        if self.display:
            self.display.show(["POWER", "", f"{choice}...", ""], big_line=2)
        self.rec.stop()
        self._power_cmd("poweroff" if choice == "Shutdown" else "reboot")

    @staticmethod
    def _system_power(action: str) -> None:
        subprocess.run(["sudo", "-n", "systemctl", action], check=False)

    # main loop
    def snapshot(self) -> Snapshot:
        out = self.rec.cfg.resolved_out_dir()
        try:
            du = shutil.disk_usage(out if out.exists() else Path("/"))
            total, used, free = du.total / 1e9, du.used / 1e9, du.free / 1e9
        except OSError:
            total = used = free = 0.0
        st = self.rec.state
        return Snapshot(
            camera=bool(find_cameras()),
            state=st.state,
            armed=self.rec.armed,
            mode=self.rec.cfg.mode,
            elapsed=time.monotonic() - st.rec_since if st.rec_since else 0.0,
            clips=len(st.clips),
            total_gb=total, used_gb=used, free_gb=free,
            ip=local_ip(),
            hostname=socket.gethostname(),
        )

    def run(self) -> None:
        self._setup_buttons()
        period = 1.0 / self.cfg.refresh_hz
        while not self._stop.is_set():
            if self.display:
                page = PAGES[self.page]
                lines = render(page, self.snapshot(), self.power_choice)
                self.display.show(lines, big_line=2 if page == "RECORD" else None)
            self._stop.wait(period)

    def start(self) -> threading.Thread:
        t = threading.Thread(target=self.run, name="panel", daemon=True)
        t.start()
        return t

    def stop(self) -> None:
        self._stop.set()
        for b in self._buttons:
            b.close()
        if self.display:
            self.display.close()
