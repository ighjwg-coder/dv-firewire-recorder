"""Linux FireWire (juju stack) device discovery via sysfs."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

SYSFS_FIREWIRE = Path("/sys/bus/firewire/devices")

# IEEE 1394 Trade Association AV/C unit: specifier_id 0x00a02d, version 0x010001
AVC_SPECIFIER_ID = 0x00A02D
AVC_VERSION = 0x010001


@dataclass
class FireWireDevice:
    node: str
    guid: str | None
    vendor: str
    model: str
    is_local: bool
    is_avc: bool

    @property
    def dev_path(self) -> Path:
        return Path("/dev") / self.node

    def accessible(self) -> bool:
        return os.access(self.dev_path, os.R_OK | os.W_OK)

    @property
    def label(self) -> str:
        name = " ".join(p for p in (self.vendor, self.model) if p) or "(unknown)"
        return name


def _read(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except OSError:
        return None


def _parse_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value, 0)
    except ValueError:
        return None


def _is_avc_pair(spec: int | None, ver: int | None) -> bool:
    return spec == AVC_SPECIFIER_ID and ver == AVC_VERSION


def _has_avc_unit(node_dir: Path) -> bool:
    # "units" lists "specifier_id:version" pairs separated by spaces
    for pair in (_read(node_dir / "units") or "").split():
        spec, _, ver = pair.partition(":")
        if _is_avc_pair(_parse_int(spec), _parse_int(ver)):
            return True
    # fall back to unit sub-directories (fw1.0, fw1.1, ...)
    for unit in node_dir.parent.glob(f"{node_dir.name}.*"):
        if _is_avc_pair(_parse_int(_read(unit / "specifier_id")),
                        _parse_int(_read(unit / "version"))):
            return True
    return False


def list_devices(root: Path = SYSFS_FIREWIRE) -> list[FireWireDevice]:
    if not root.is_dir():
        return []
    devices = []
    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        if "." in entry.name or not entry.name.startswith("fw"):
            continue
        guid = _read(entry / "guid")
        devices.append(FireWireDevice(
            node=entry.name,
            guid=guid.lower().removeprefix("0x") if guid else None,
            vendor=_read(entry / "vendor_name") or "",
            model=_read(entry / "model_name") or "",
            is_local=_read(entry / "is_local") == "1",
            is_avc=_has_avc_unit(entry),
        ))
    return devices


def find_cameras(root: Path = SYSFS_FIREWIRE) -> list[FireWireDevice]:
    return [d for d in list_devices(root) if d.is_avc and not d.is_local]
