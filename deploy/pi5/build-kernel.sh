#!/usr/bin/env bash
# Raspberry Pi 5 커널을 FireWire(IEEE 1394) 지원으로 재빌드합니다.
# 실행: Pi 5에서 직접 (Raspberry Pi OS 64-bit, 빌드 약 1시간 / 디스크 여유 10GB 이상)
#   bash deploy/pi5/build-kernel.sh
# 공식 절차: https://www.raspberrypi.com/documentation/computers/linux_kernel.html
set -euo pipefail

if modinfo firewire-ohci >/dev/null 2>&1; then
    echo "현재 커널에 firewire-ohci 모듈이 이미 있습니다. 재빌드가 필요 없습니다."
    exit 0
fi

KERNEL=kernel_2712            # Pi 5 (BCM2712)
SRC=${SRC:-$HOME/linux}
JOBS=${JOBS:-$(nproc)}

sudo apt-get update
sudo apt-get install -y git bc bison flex libssl-dev make libncurses-dev

if [ ! -d "$SRC" ]; then
    git clone --depth=1 https://github.com/raspberrypi/linux "$SRC"
fi
cd "$SRC"

make bcm2712_defconfig
./scripts/config --module CONFIG_FIREWIRE \
                 --module CONFIG_FIREWIRE_OHCI \
                 --set-str CONFIG_LOCALVERSION "-v8-16k-firewire"
make olddefconfig
grep -E '^CONFIG_FIREWIRE(_OHCI)?=' .config

make -j"$JOBS" Image.gz modules dtbs
sudo make -j"$JOBS" modules_install

sudo cp /boot/firmware/$KERNEL.img /boot/firmware/$KERNEL-backup.img
sudo cp arch/arm64/boot/Image.gz /boot/firmware/$KERNEL.img
sudo cp arch/arm64/boot/dts/broadcom/*.dtb /boot/firmware/
sudo cp arch/arm64/boot/dts/overlays/*.dtb* /boot/firmware/overlays/
sudo cp arch/arm64/boot/dts/overlays/README /boot/firmware/overlays/

echo
echo "완료. 기존 커널은 /boot/firmware/$KERNEL-backup.img 로 백업했습니다."
echo "다음: sudo bash deploy/pi5/setup-boot.sh  →  sudo reboot"
echo "주의: apt 커널 업데이트가 이 커널을 덮어쓸 수 있습니다. 업데이트 후 이 스크립트를 다시 실행하세요."
