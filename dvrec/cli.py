"""dvrec command line: check / devices / record."""

from __future__ import annotations

import argparse
import dataclasses
import logging
import signal
import sys
import tomllib
from pathlib import Path

from . import __version__
from .checks import run_checks
from .devices import list_devices
from .recorder import FORMATS, Recorder, RecordConfig, build_command, write_status


def _load_config(path: Path | None) -> RecordConfig:
    cfg = RecordConfig()
    if not path:
        return cfg
    data = tomllib.loads(path.read_text()).get("record", {})
    names = {f.name for f in dataclasses.fields(RecordConfig)}
    unknown = set(data) - names
    if unknown:
        raise SystemExit(f"설정 파일에 알 수 없는 키: {', '.join(sorted(unknown))}")
    for key, value in data.items():
        setattr(cfg, key, Path(value) if key == "out_dir" else value)
    return cfg


def cmd_devices(_args) -> int:
    devices = list_devices()
    if not devices:
        print("FireWire 장치 없음 (컨트롤러/드라이버 확인: dvrec check)")
        return 1
    for d in devices:
        kind = "컨트롤러" if d.is_local else ("캠코더(AV/C)" if d.is_avc else "기타")
        print(f"{d.node:6} {kind:10} guid={d.guid or '-':18} {d.label}")
    return 0


def cmd_check(args) -> int:
    cfg = _load_config(args.config)
    ok_all = True
    for name, ok, detail in run_checks(cfg.out_dir, cfg.dvgrab):
        ok_all &= ok
        print(f"[{'OK' if ok else 'NG'}] {name:22} {detail}")
    return 0 if ok_all else 1


def cmd_record(args) -> int:
    cfg = _load_config(args.config)
    for key in ("out_dir", "mode", "format", "name_time", "prefix", "split_size_mib",
                "min_free_gb", "guid", "dvgrab", "pulldown"):
        value = getattr(args, key)
        if value is not None:
            setattr(cfg, key, value)
    if args.no_daily_folder:
        cfg.daily_folder = False

    status_file = args.status_file or cfg.resolved_out_dir() / ".dvrec-status.json"
    cfg.resolved_out_dir().mkdir(parents=True, exist_ok=True)

    def on_event(_ev, st):
        try:
            write_status(status_file, st)
        except OSError:
            pass

    try:
        build_command(cfg, cfg.resolved_out_dir() / cfg.prefix)
    except ValueError as e:
        raise SystemExit(f"설정 오류: {e}")

    rec = Recorder(cfg, on_event=on_event)

    def handle(signum, _frame):
        logging.getLogger("dvrec").info("종료 요청 (signal %s) — 파일을 닫는 중...", signum)
        rec.stop()

    signal.signal(signal.SIGINT, handle)
    signal.signal(signal.SIGTERM, handle)

    print(f"dvrec {__version__} — mode={cfg.mode} format={cfg.format} → {cfg.resolved_out_dir()}")
    if cfg.mode == "tapeless":
        print("캠코더를 카메라 모드로 두고 REC 버튼을 누르면 녹화됩니다. 종료: Ctrl+C")
    return rec.run()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="dvrec", description="FireWire DV/HDV 테이프리스 레코더")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("-c", "--config", type=Path, help="TOML 설정 파일 ([record] 섹션)")
    p.add_argument("-v", "--verbose", action="store_true", help="dvgrab 진행 로그까지 출력")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("devices", help="FireWire 장치 목록").set_defaults(func=cmd_devices)
    sub.add_parser("check", help="녹화 환경 점검").set_defaults(func=cmd_check)

    r = sub.add_parser("record", help="녹화 시작")
    r.set_defaults(func=cmd_record)
    r.add_argument("-o", "--out-dir", dest="out_dir", type=Path)
    r.add_argument("-m", "--mode", choices=["tapeless", "continuous"])
    r.add_argument("-f", "--format", choices=sorted(FORMATS))
    r.add_argument("--name-time", dest="name_time", choices=["system", "camera"])
    r.add_argument("--prefix")
    r.add_argument("--split-size", dest="split_size_mib", type=int, metavar="MiB")
    r.add_argument("--min-free-gb", dest="min_free_gb", type=float)
    r.add_argument("--pulldown", choices=["none", "24p", "24pa"],
                   help="24P 풀다운 제거 (format=mov 전용)")
    r.add_argument("--guid", help="카메라 여러 대일 때 GUID 지정 (dvrec devices 참고)")
    r.add_argument("--dvgrab", help="dvgrab 실행 파일 경로")
    r.add_argument("--status-file", type=Path)
    r.add_argument("--no-daily-folder", action="store_true")

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
