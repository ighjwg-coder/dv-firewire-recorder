# dv-firewire-recorder (`dvrec`)

FireWire(IEEE 1394 / i.LINK)로 DV·HDV 캠코더 영상을 **테이프 없이 PC 디스크에 바로 녹화**하는 레코더입니다.
Sony HVR-MRC1, Focus Enhancements FS-4/FS-5 같은 외장 DV 레코더를 리눅스 PC로 대체합니다.

- 캠코더 **REC 버튼과 연동**: 누르면 녹화, 다시 누르면 정지, 누를 때마다 새 클립 생성
- 카메라 케이블이 빠지거나 전원이 꺼져도 **자동 재연결** (dvgrab 자동 재시작)
- **디스크 여유공간 감시**: 기준 이하로 내려가면 현재 클립을 정상 종료
- 날짜별 폴더, 시간 기반 파일명, 상태 JSON 파일 (외부 모니터링용)
- systemd 서비스로 **헤드리스 녹화 박스** 구성 가능
- **Raspberry Pi 5 + PCIe FireWire 카드 + OLED/버튼 패널**로 휴대용 녹화 박스 구성 (Jeff Geerling 영상 *"Apple Abandoned It. I Saved It with a Raspberry Pi."* 속 Open MRU와 같은 구성)

캡처 엔진은 [dvgrab](https://github.com/ddennedy/dvgrab)이며, `dvrec`은 이를 관리하는 Python 래퍼입니다. 기본 기능은 표준 라이브러리만 쓰고, OLED 패널을 쓸 때만 `luma.oled`와 `gpiozero`가 필요합니다.

---

## 1. 준비물

### 전제 조건
FireWire **출력 단자가 있는 DV/HDV 캠코더**가 필요합니다. 최신 미러리스/시네마 카메라(FS7, a7 시리즈, Lumix S 등)와 HXR-NX30은 FireWire가 없어서 대상이 아닙니다.

| 항목 | 권장 | 비고 |
|---|---|---|
| 카메라 | DV/HDV 캠코더 (VX2100, PD170, HVR-Z1/A1, HC1, XH-A1, HV20, DVX100 등) | 기종에 따라 카메라 모드에서 DV를 내보내려면 **테이프가 들어 있어야** 함 |
| PC | x86 리눅스 (Ubuntu 22.04+ / Debian 12+) **또는 Raspberry Pi 5** | 오래된 노트북이나 미니PC로 충분 (DV 25Mbps). Pi 5는 [6장](#6-raspberry-pi-5-녹화-박스) 참고 |
| FireWire 컨트롤러 | **TI 칩셋** OHCI (PCIe / ExpressCard / 내장) | VIA·Ricoh 칩셋은 프레임 드롭이 생기기 쉬움 |
| 케이블 | 4핀(캠코더) ↔ 4핀/6핀(PC) FW400 | |
| 저장장치 | SSD / USB3 외장디스크, ext4 또는 exFAT | DV ≈ **13 GB/시간** |

> 라즈베리파이는 **Pi 5만** 가능합니다. PCIe가 있는 모델이 Pi 5뿐이기 때문입니다. 커널을 FireWire 지원으로 재빌드해야 하며, 스크립트를 제공합니다.

## 2. 설치

```bash
sudo apt install dvgrab python3 git
git clone https://github.com/ighjwg-coder/dv-firewire-recorder.git
cd dv-firewire-recorder
sudo pip install .            # 또는: python3 -m dvrec ... 로 설치 없이 실행

# /dev/fw* 접근 권한 (매번 sudo 없이 녹화)
sudo cp deploy/99-firewire-dv.rules /etc/udev/rules.d/
sudo udevadm control --reload && sudo udevadm trigger
sudo usermod -aG video $USER   # 재로그인 필요
```

## 3. 점검

캠코더를 연결하고 전원을 켠 뒤:

```bash
dvrec check
```
```
[OK] dvgrab 설치              /usr/bin/dvgrab
[OK] firewire-ohci 드라이버     로드됨
[OK] FireWire 컨트롤러          fw0 Texas Instruments
[OK] AV/C 캠코더               fw1 SONY DCR-VX2100 (guid 080046...)
[OK] /dev/fw* 권한             OK
[OK] 저장 경로                  /home/user/dv-captures (여유 412.0 GB ≈ DV 31.7시간)
```

`dvrec devices`로 연결된 FireWire 장치 목록과 GUID를 볼 수 있습니다.

## 4. 녹화

```bash
# 테이프리스: 캠코더 REC 버튼 연동 (기본값)
dvrec record -o ~/dv-captures

# 수동: 테이프 없이 카메라 출력을 저장, 시작/정지는 Pi 패널 REC 버튼
dvrec record -m manual --panel oled

# 연속 저장: 들어오는 스트림을 전부 저장 (테이프 재생본 캡처 등)
dvrec record -m continuous

# HDV 캠코더
dvrec record -f hdv

# 설정 파일 사용
dvrec -c deploy/dvrec.toml record
```

종료는 `Ctrl+C`입니다. dvgrab에 SIGINT를 보내 현재 파일을 정상적으로 닫습니다.

### 저장 구조
```
~/dv-captures/
├── .dvrec-status.json          # 현재 상태 (state, file, size_mib, timecode, clips...)
└── 2026-10-07/
    ├── clip-2026.10.07_14-02-11.dv
    └── clip-2026.10.07_14-15-40.dv
```

### 옵션

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `-o, --out-dir` | `~/dv-captures` | 저장 위치 |
| `-m, --mode` | `tapeless` | `tapeless`(캠코더 REC 연동, `dvgrab -r -a -noavc`) / `manual`(패널 REC 버튼) / `continuous` |
| `--panel` | `none` | `oled`(Pi OLED + 버튼) / `console`(터미널에 패널 화면 출력) |
| `-f, --format` | `dv` | `dv`(raw .dv), `avi`(Type-2 OpenDML), `mov`(QuickTime), `dif`, `hdv`(.m2t) |
| `--name-time` | `system` | 파일명 시간: `system`(PC 시계) / `camera`(카메라 녹화일시) |
| `--split-size` | `0` | MiB 단위 파일 분할 (FAT32면 `4000`) |
| `--min-free-gb` | `2.0` | 여유공간 하한 |
| `--pulldown` | `none` | `24p` / `24pa`: 녹화하면서 풀다운 제거 (`-f mov` 전용) |
| `--guid` | | 카메라가 여러 대일 때 지정 |
| `--no-daily-folder` | | 날짜 폴더 생성 안 함 |
| `-v` | | dvgrab 진행 로그까지 출력 |

### 포맷 선택 가이드 (Premiere Pro 기준)
- **`dv`** (기본): 원본 DIF 스트림을 그대로 저장. Premiere·Resolve·FFmpeg 모두 바로 읽고, 재래핑 손실 없음
- **`mov`**: 맥/파이널컷 호환이 필요할 때
- **`avi`**: 구형 윈도우 NLE 호환용
- **`hdv`**: HDV 캠코더(1080i MPEG-2 TS). Premiere에서 바로 열림

## 5. Panasonic AG-DVX100B

프리셋: `dvrec -c deploy/dvx100b.toml record`

### 연결
- 카메라 뒷면 **DV 단자(4핀)** ↔ PC FireWire 포트
- NTSC 720×480, 29.97fps, DV25 (≈ 13GB/시간)

### 촬영 모드별 저장 방법

| 카메라 모드 | 실제 기록 | 권장 저장 방법 |
|---|---|---|
| 60i | 59.94i 인터레이스 | `-f dv` (기본) |
| 30P | 29.97p (60i 안에 프로그레시브) | `-f dv` |
| 24P (표준, 2:3 풀다운) | 59.94i 안에 23.976p | `-f dv` → 편집 시 풀다운 제거, 또는 `-f mov --pulldown 24p` |
| **24P Advanced** (2:3:3:2) | 59.94i 안에 23.976p | `-f dv` → Premiere에서 제거 **또는** `-f mov --pulldown 24pa`로 녹화 단계에서 제거 |

- **원본 보존이 우선이면 `-f dv`**를 권장합니다. Premiere Pro: 클립 우클릭 → *Modify → Interpret Footage* → **Remove 24p DV Pulldown** 체크
- 바로 23.976p 타임라인에 올리고 싶으면 `dvrec record -f mov --pulldown 24pa`

### 녹화 전 확인할 것 (실기 테스트 필요)
1. **테이프를 넣고 테스트하세요.** 테이프리스 모드(`-r`)는 DV 스트림 속 "녹화 중" 표시를 보고 동작하는데, 이 표시는 캠코더가 실제로 녹화 상태가 되어야 켜집니다. 테이프가 없으면 REC 버튼이 동작하지 않을 수 있습니다. 이 경우 테이프와 디스크에 **동시에 기록**되니 테이프가 백업 역할을 합니다.
2. 테이프 없이 녹화하려면 `-m manual`을 쓰세요. Pi 패널의 REC 버튼으로 시작과 정지를 합니다. 패널이 없으면 `-m continuous`로 실행 중인 동안 전부 저장합니다.
3. 오디오는 카메라 메뉴에서 **48kHz/16bit**로 설정하세요. 32kHz 모드도 캡처는 되지만, 편집할 때 샘플레이트 변환이 생깁니다.
4. 16:9(스퀴즈)로 찍었다면 Premiere에서 픽셀 종횡비를 *D1/DV NTSC Widescreen (1.2121)*로 지정하세요.

## 6. Raspberry Pi 5 녹화 박스

영상 속 구성입니다. Pi 5의 PCIe 커넥터에 FireWire 카드를 연결하고, OLED 화면과 버튼으로 조작합니다.

### 부품

| 부품 | 영상 속 구성 / 권장 | 비고 |
|---|---|---|
| Raspberry Pi 5 | 4GB 이상 | 공식 27W USB-C 전원 권장 |
| PCIe HAT / 어댑터 | Pi 5 PCIe FFC → **PCIe x1 슬롯** 어댑터 | FireWire 카드에 별도 전원 커넥터가 있으면 전원 공급 필요 |
| FireWire 카드 | **TI XIO2213A/B** 칩셋 (영상 `lspci` 화면) | VIA VT6315N도 가능. 둘 다 64비트 DMA를 지원하지 않아 `pcie-32bit-dma` 오버레이 필수 |
| OLED | 128×64 I2C (SSD1306 / SH1106), 주소 0x3C | 3.3V, SDA=GPIO2, SCL=GPIO3 |
| 버튼 3개 | 택트 스위치: 한쪽은 GPIO, 다른 쪽은 GND (내부 풀업 사용) | REC=GPIO17, PAGE=GPIO27, SELECT=GPIO22 (설정 변경 가능) |
| 저장장치 | USB3 SSD (`/srv/dv-captures`에 마운트) | microSD에 장시간 녹화하는 것은 비권장 |

### 설치 순서 (Pi 5, Raspberry Pi OS 64-bit)

```bash
git clone https://github.com/ighjwg-coder/dv-firewire-recorder.git
cd dv-firewire-recorder

bash deploy/pi5/build-kernel.sh      # 1) FireWire 커널 빌드 (약 1시간)
sudo bash deploy/pi5/setup-boot.sh   # 2) PCIe/I2C 부팅 옵션
sudo reboot

lspci | grep -i 1394                 # 3) FireWire 컨트롤러 인식 확인
sudo bash deploy/pi5/install.sh      # 4) dvrec + 패널 + 자동 시작 서비스 설치
dvrec -c /etc/dvrec.toml check
```

각 스크립트가 하는 일:

| 스크립트 | 내용 |
|---|---|
| `build-kernel.sh` | 공식 `raspberrypi/linux` 소스를 받아 `CONFIG_FIREWIRE`, `CONFIG_FIREWIRE_OHCI`를 켜고 빌드·설치. 기존 커널은 `kernel_2712-backup.img`로 백업. 이미 모듈이 있으면 건너뜀 |
| `setup-boot.sh` | `config.txt` `[all]`에 `dtparam=pciex1`, `dtoverlay=pcie-32bit-dma`를 추가하고, `cmdline.txt`에 `pcie_aspm=off`를 추가. I2C 활성화. 원본은 `*.dvrec-bak`으로 백업하며, 여러 번 실행해도 중복되지 않음 |
| `install.sh` | dvgrab 설치, `/opt/dvrec` venv(+luma.oled), udev 규칙, `dvrec` 사용자 생성, 종료/재부팅 sudo 권한, systemd 서비스 등록 |

> apt로 커널이 업데이트되면 FireWire 커널이 덮어써질 수 있습니다. 업데이트 후 `dvrec check`에서 드라이버가 NG로 나오면 `build-kernel.sh`를 다시 실행하세요.

### 패널 조작

| 페이지 | 표시 내용 |
|---|---|
| RECORD | 상단: 여유공간 %·남은 녹화시간 / 중앙: `NO CAM`, `STBY`, 녹화 경과시간 / 하단: 상태·클립 수 |
| STORAGE | Total / Used / Free (GB) |
| NETWORK | IP 주소, `호스트명.local` (Pi 호스트명을 `firepi`로 바꾸면 `firepi.local`) |
| POWER | Cancel / Shutdown / Reboot |

| 버튼 | 동작 |
|---|---|
| REC | `manual` 모드: 녹화 시작/정지 (`tapeless` 모드에서는 캠코더 REC 버튼을 사용) |
| PAGE | 다음 페이지 |
| SELECT | POWER 페이지에서 짧게 누르면 항목 이동, **2초 누르면 실행**. 종료 전에 녹화 파일을 안전하게 닫음 |

설정은 `/etc/dvrec.toml`의 `[panel]` 섹션에서 바꿀 수 있습니다(`deploy/pi5/dvrec-pi.toml` 참고). 하드웨어 없이 화면 구성을 확인하려면 `dvrec record --panel console`을 실행하세요.

## 7. 헤드리스 녹화 박스 (x86 PC, 부팅 시 자동 대기)

```bash
sudo useradd -r -G video -m dvrec
sudo mkdir -p /srv/dv-captures && sudo chown dvrec /srv/dv-captures
sudo cp deploy/dvrec.toml /etc/dvrec.toml
sudo cp deploy/dvrec.service /etc/systemd/system/
sudo systemctl enable --now dvrec
journalctl -u dvrec -f        # 로그 확인
```

PC를 켜고 캠코더를 연결하면 바로 녹화 대기 상태가 되고, 모니터 없이 REC 버튼만으로 운용할 수 있습니다.

## 8. 문제 해결

| 증상 | 원인 / 조치 |
|---|---|
| `AV/C 캠코더` NG | 캠코더 전원 확인, 카메라 모드 확인, 케이블 재연결, `dmesg \| grep -i firewire` 확인 |
| REC를 눌러도 파일이 안 생김 | 테이프 미삽입 시 DV 출력을 막는 기종이 있음 → 테이프 삽입 / 메뉴에서 i.LINK·DV OUT 설정 확인 |
| HDV 카메라인데 DV로 들어옴 | 카메라 메뉴 `i.LINK CONV` / `HDV→DV 변환` 끄기, `-f hdv` 사용 |
| HDV에서 REC 연동 안 됨 | 기종에 따라 HDV 스트림에 REC 플래그가 없음 → `-m continuous`로 녹화 |
| 프레임 드롭 / 끊김 | TI 칩셋 카드로 교체, USB 허브 경유 외장디스크 피하기, 절전(USB autosuspend) 끄기 |
| `Permission denied` | udev 규칙 설치 + `video` 그룹 추가 후 재로그인 |
| (Pi 5) `lspci`에 1394 장치 없음 | FFC 케이블 방향·HAT 전원 확인, `config.txt`에 `dtparam=pciex1` 있는지 확인 |
| (Pi 5) 카드는 보이는데 캡처 오류·멈춤 | `dtoverlay=pcie-32bit-dma`, `pcie_aspm=off` 적용 여부 확인 (`setup-boot.sh`) |
| (Pi 5) OLED가 안 켜짐 | `i2cdetect -y 1`로 0x3C 확인, 1.3인치 모듈은 `driver = "sh1106"` |

## 9. 개발

```bash
python3 -m unittest discover -s tests -t . -v
```

`tests/fake_dvgrab.py`가 dvgrab 출력을 흉내 내기 때문에 FireWire 하드웨어 없이도 감시·재시작 로직을 테스트할 수 있습니다.
