#!/usr/bin/env bash
# dvrec 녹화 박스 설치 (Pi 5, 커널/부팅 설정 이후)
# 실행: sudo bash deploy/pi5/install.sh
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "sudo로 실행하세요"; exit 1; }
REPO=$(cd "$(dirname "$0")/../.." && pwd)

apt-get install -y dvgrab python3-venv python3-gpiozero python3-lgpio python3-pil i2c-tools

id dvrec >/dev/null 2>&1 || useradd -r -m -s /usr/sbin/nologin dvrec
usermod -aG video,gpio,i2c dvrec

python3 -m venv --system-site-packages /opt/dvrec
/opt/dvrec/bin/pip install --upgrade pip
/opt/dvrec/bin/pip install "$REPO" luma.oled
ln -sf /opt/dvrec/bin/dvrec /usr/local/bin/dvrec

install -m 0644 "$REPO/deploy/99-firewire-dv.rules" /etc/udev/rules.d/
udevadm control --reload && udevadm trigger

[ -f /etc/dvrec.toml ] || install -m 0644 "$REPO/deploy/pi5/dvrec-pi.toml" /etc/dvrec.toml
mkdir -p /srv/dv-captures && chown dvrec:dvrec /srv/dv-captures

install -m 0440 "$REPO/deploy/pi5/dvrec-sudoers" /etc/sudoers.d/dvrec
visudo -cf /etc/sudoers.d/dvrec

install -m 0644 "$REPO/deploy/dvrec.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now dvrec

echo "설치 완료. 로그: journalctl -u dvrec -f   설정: /etc/dvrec.toml"
