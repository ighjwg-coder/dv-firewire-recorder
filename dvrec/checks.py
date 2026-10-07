"""Environment checks: kernel driver, controller, camera, permissions, disk."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from .devices import SYSFS_FIREWIRE, list_devices


def run_checks(out_dir: Path, dvgrab: str = "dvgrab",
               sysfs: Path = SYSFS_FIREWIRE) -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []

    path = shutil.which(dvgrab)
    results.append(("dvgrab 설치", bool(path), path or "sudo apt install dvgrab"))

    driver = Path("/sys/module/firewire_ohci").exists() or sysfs.is_dir()
    results.append(("firewire-ohci 드라이버", driver,
                    "로드됨" if driver else "sudo modprobe firewire-ohci / 컨트롤러 미장착"))

    devices = list_devices(sysfs)
    local = [d for d in devices if d.is_local]
    results.append(("FireWire 컨트롤러", bool(local),
                    ", ".join(f"{d.node} {d.label}" for d in local) or "인식된 컨트롤러 없음"))

    cams = [d for d in devices if d.is_avc and not d.is_local]
    results.append(("AV/C 캠코더", bool(cams),
                    ", ".join(f"{d.node} {d.label} (guid {d.guid})" for d in cams)
                    or "카메라 전원·케이블·카메라 모드 확인"))

    if cams:
        denied = [d.node for d in cams if not d.accessible()]
        results.append(("/dev/fw* 권한", not denied,
                        "OK" if not denied else
                        f"{', '.join(denied)} 접근 불가 → deploy/99-firewire-dv.rules 설치"))

    out = Path(os.path.expanduser(str(out_dir)))
    probe = out if out.exists() else out.parent
    writable = probe.exists() and os.access(probe, os.W_OK)
    detail = str(out)
    if probe.exists():
        free = shutil.disk_usage(probe).free / 1e9
        detail += f" (여유 {free:.1f} GB ≈ DV {free / 13:.1f}시간)"
    results.append(("저장 경로", writable, detail))
    return results
