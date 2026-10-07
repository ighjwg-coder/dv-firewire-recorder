#!/usr/bin/env bash
# PCIe FireWire 카드용 Pi 5 부팅 옵션 (Jeff Geerling "Using FireWire on a Raspberry Pi" 기준)
#  - dtparam=pciex1          : 외부 PCIe 커넥터 활성화
#  - dtoverlay=pcie-32bit-dma: TI XIO2213A / VIA VT6315N 등은 64비트 DMA 미지원
#  - pcie_aspm=off           : PCIe 절전(ASPM) 끄기
# 실행: sudo bash deploy/pi5/setup-boot.sh
set -euo pipefail
CONFIG=/boot/firmware/config.txt
CMDLINE=/boot/firmware/cmdline.txt
[ "$(id -u)" = 0 ] || { echo "sudo로 실행하세요"; exit 1; }

[ -f "$CONFIG.dvrec-bak" ] || cp "$CONFIG" "$CONFIG.dvrec-bak"
[ -f "$CMDLINE.dvrec-bak" ] || cp "$CMDLINE" "$CMDLINE.dvrec-bak"

add_config() {
    grep -qxF "$1" "$CONFIG" || { echo "$1" >> "$CONFIG"; echo "config.txt += $1"; }
}
# 파일 끝이 [all] 섹션이 되도록 보장
last=$(grep '^\[' "$CONFIG" | tail -n 1 || true)
if [ -n "$last" ] && [ "$last" != "[all]" ]; then
    printf '\n[all]\n' >> "$CONFIG"
fi
add_config "dtparam=pciex1"
add_config "dtoverlay=pcie-32bit-dma"

# cmdline.txt는 반드시 한 줄
if ! grep -qw "pcie_aspm=off" "$CMDLINE"; then
    sed -i '1 s/$/ pcie_aspm=off/' "$CMDLINE"
    echo "cmdline.txt += pcie_aspm=off"
fi

# OLED 패널용 I2C
command -v raspi-config >/dev/null && raspi-config nonint do_i2c 0 || true

echo "완료. 재부팅 후 확인: lspci | grep -i 1394 ; dvrec check"
