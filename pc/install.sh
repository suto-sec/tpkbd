#!/usr/bin/env bash
# Installs the receiver side. Run with sudo from the repo (or after
# copying the pc/ directory anywhere, the script finds its own files).
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "run as root: sudo $0" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_USER="${SUDO_USER:-$USER}"

if command -v pacman >/dev/null 2>&1; then
    pacman -S --needed --noconfirm python-evdev openssh
fi
systemctl enable --now sshd

getent group uinput >/dev/null || groupadd --system uinput
usermod -aG uinput "$TARGET_USER"

install -m 644 "$SCRIPT_DIR/tpkbd-uinput.conf" /etc/modules-load.d/tpkbd-uinput.conf
install -m 644 "$SCRIPT_DIR/60-tpkbd-uinput.rules" /etc/udev/rules.d/60-tpkbd-uinput.rules
udevadm control --reload
modprobe uinput
udevadm trigger --subsystem-match=misc --sysname-match=uinput

install -m 755 "$SCRIPT_DIR/tpkbd-recv" /usr/local/bin/tpkbd-recv

read -rp "Also install the X11 fallback config (99-tpkbd.conf)? [y/N] " x11_reply
if [[ "$x11_reply" =~ ^[Yy]$ ]]; then
    install -d -m 755 /etc/X11/xorg.conf.d
    install -m 644 "$SCRIPT_DIR/99-tpkbd.conf" /etc/X11/xorg.conf.d/99-tpkbd.conf
fi

echo
echo "/dev/uinput:"
ls -l /dev/uinput 2>/dev/null || echo "  not present yet; load the uinput module or reboot"
echo
echo "Remaining manual steps (see docs/setup.md):"
echo "  1. Append the ThinkPad's public key to ~/.ssh/authorized_keys"
echo "     with the restrictions from pc/authorized_keys.example (section 7)."
echo "  2. Once connected, in KDE:"
echo "       Mouse -> 'ThinkPad remote pointer' -> acceleration None"
echo "       Touchpad -> 'ThinkPad remote pinch' -> tap-to-click off (section 9)."
echo
echo "$TARGET_USER was added to the uinput group; that takes effect on the next SSH login, no logout needed."
