"""Supervises dvgrab as a tapeless DV/HDV recorder."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .status import RecorderState, apply_line

log = logging.getLogger("dvrec")

FORMATS = {
    "dv": "raw",    # .dv  (Premiere/Resolve/FFmpeg 모두 읽음)
    "dif": "dif",
    "avi": "dv2",   # Type-2 DV AVI
    "mov": "qt",    # QuickTime DV
    "hdv": "hdv",   # MPEG-2 TS (.m2t)
}

_LINE_SPLIT = re.compile(rb"[\r\n]")


@dataclass
class RecordConfig:
    out_dir: Path = Path("~/dv-captures")
    mode: str = "tapeless"        # tapeless: REC 버튼 연동 / continuous: 들어오는 스트림 전부
    format: str = "dv"
    name_time: str = "system"     # system: PC 시계 / camera: 카메라 녹화일시
    prefix: str = "clip-"
    split_size_mib: int = 0       # 0 = 크기 분할 없음 (FAT32면 4000 권장)
    min_free_gb: float = 2.0
    guid: str | None = None
    retry_delay: float = 3.0
    dvgrab: str = "dvgrab"
    daily_folder: bool = True

    def resolved_out_dir(self) -> Path:
        return Path(os.path.expanduser(str(self.out_dir))).resolve()


def build_command(cfg: RecordConfig, basename: Path) -> list[str]:
    if cfg.format not in FORMATS:
        raise ValueError(f"unknown format: {cfg.format}")
    cmd = [cfg.dvgrab, "-format", FORMATS[cfg.format], "-showstatus",
           "-size", str(cfg.split_size_mib)]
    cmd.append("-timesys" if cfg.name_time == "system" else "-timestamp")
    if cfg.format == "avi":
        cmd.append("-opendml")
    if cfg.mode == "tapeless":
        # -r: 카메라가 REC 상태일 때만 저장, -a: REC 누를 때마다 새 파일
        # -noavc: 카메라 모드에서 AV/C play/stop 명령을 보내지 않음
        cmd += ["-r", "-a", "-noavc"]
    elif cfg.mode == "continuous":
        cmd += ["-a"]
    else:
        raise ValueError(f"unknown mode: {cfg.mode}")
    if cfg.guid:
        cmd += ["-guid", cfg.guid]
    cmd.append(str(basename))
    return cmd


def free_gb(path: Path) -> float:
    return shutil.disk_usage(path).free / 1e9


class Recorder:
    def __init__(self, cfg: RecordConfig, on_event=None):
        self.cfg = cfg
        self.state = RecorderState()
        self.on_event = on_event or (lambda ev, st: None)
        self._stop = threading.Event()
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    # ---- public -------------------------------------------------------
    def stop(self) -> None:
        self._stop.set()
        self._interrupt_child()

    def run(self) -> int:
        out = self.cfg.resolved_out_dir()
        out.mkdir(parents=True, exist_ok=True)
        if self.cfg.mode == "tapeless" and self.cfg.format == "hdv":
            log.warning("HDV + tapeless(-r) 조합은 카메라에 따라 REC 플래그가 "
                        "전달되지 않을 수 있습니다. 먼저 테스트하세요.")

        while not self._stop.is_set():
            target = self._target_dir(out)
            if free_gb(target) < self.cfg.min_free_gb:
                self._set("error", f"디스크 여유공간 부족 (< {self.cfg.min_free_gb} GB)")
                self._stop.wait(10)
                continue

            cmd = build_command(self.cfg, target / self.cfg.prefix)
            log.info("실행: %s", " ".join(cmd))
            code = self._run_once(cmd, target)
            if self._stop.is_set():
                break
            log.warning("dvgrab 종료 (code %s). %.0f초 후 재시작 — 카메라 연결/전원을 확인하세요.",
                        code, self.cfg.retry_delay)
            self._set("waiting", "카메라 대기 중")
            self._stop.wait(self.cfg.retry_delay)

        self._set("stopped", None)
        return 0

    # ---- internals ----------------------------------------------------
    def _target_dir(self, out: Path) -> Path:
        if not self.cfg.daily_folder:
            return out
        d = out / datetime.now().strftime("%Y-%m-%d")
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _run_once(self, cmd: list[str], target: Path) -> int | None:
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL, start_new_session=True)
        except FileNotFoundError:
            self._set("error", f"{cmd[0]} 실행 파일을 찾을 수 없습니다 (sudo apt install dvgrab)")
            self._stop.wait(self.cfg.retry_delay)
            return None
        with self._lock:
            self._proc = proc

        watchdog = threading.Thread(target=self._disk_watchdog, args=(proc, target), daemon=True)
        watchdog.start()

        buf = b""
        assert proc.stdout is not None
        while True:
            chunk = proc.stdout.read1(4096)
            if not chunk:
                break
            buf += chunk
            *lines, buf = _LINE_SPLIT.split(buf)
            for raw in lines:
                self._handle_line(raw.decode("utf-8", "replace"))
        if buf:
            self._handle_line(buf.decode("utf-8", "replace"))

        code = proc.wait()
        with self._lock:
            self._proc = None
        return code

    def _handle_line(self, line: str) -> None:
        if not line.strip():
            return
        ev = apply_line(self.state, line)
        if ev == "progress":
            log.debug(line.strip())
        elif ev:
            log.info("[%s] %s", ev, line.strip())
        else:
            log.info("dvgrab: %s", line.strip())
        if ev:
            self.on_event(ev, self.state)

    def _disk_watchdog(self, proc: subprocess.Popen, target: Path) -> None:
        while proc.poll() is None:
            if free_gb(target) < self.cfg.min_free_gb:
                log.error("디스크 여유공간 부족 — 현재 클립을 안전하게 닫습니다.")
                self._set("error", "디스크 여유공간 부족")
                self.stop()
                return
            time.sleep(5)

    def _interrupt_child(self) -> None:
        with self._lock:
            proc = self._proc
        if not proc or proc.poll() is not None:
            return
        # SIGINT → dvgrab이 현재 파일을 정상적으로 닫고 종료
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    def _set(self, state: str, message: str | None) -> None:
        self.state.state = state
        self.state.message = message
        if message:
            log.info(message)
        self.on_event(state, self.state)


def write_status(path: Path, st: RecorderState) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({**st.to_dict(), "updated": datetime.now().isoformat()},
                              ensure_ascii=False, indent=2))
    tmp.replace(path)
