#!/usr/bin/env bash
# Installs the receiver side. Run with sudo from the repo (or after
# copying the pc/ directory anywhere, the script finds its own files).
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "run as root: sudo $0" >&2
    exit 1
fi
if [[ -z "${SUDO_USER:-}" || "$SUDO_USER" == root ]]; then
    echo "run it with sudo from your normal user, so the right user joins the uinput group" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_USER="$SUDO_USER"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

if command -v pacman >/dev/null 2>&1; then
    pacman -S --needed --noconfirm python-evdev openssh
fi

# the sender connects over SSH, so sshd has to run. Don't turn on a network
# service without asking.
if ! systemctl is-enabled --quiet sshd 2>/dev/null; then
    read -rp "sshd is not enabled. Enable and start it now? [y/N] " ssh_reply
    if [[ "$ssh_reply" =~ ^[Yy]$ ]]; then
        systemctl enable --now sshd
    else
        echo "skipped: the ThinkPad can't connect until sshd runs"
    fi
fi

getent group uinput >/dev/null || groupadd --system uinput
usermod -aG uinput "$TARGET_USER"

install -m 644 "$SCRIPT_DIR/tpkbd-uinput.conf" /etc/modules-load.d/tpkbd-uinput.conf
install -m 644 "$SCRIPT_DIR/60-tpkbd-uinput.rules" /etc/udev/rules.d/60-tpkbd-uinput.rules
udevadm control --reload
modprobe uinput
udevadm trigger --subsystem-match=misc --sysname-match=uinput

install -m 755 "$SCRIPT_DIR/tpkbd-recv" /usr/local/bin/tpkbd-recv

conf_dir="$TARGET_HOME/.config/tpkbd"
if [[ ! -f "$conf_dir/recv.conf" ]]; then
    install -d -o "$TARGET_USER" -g "$TARGET_USER" -m 755 "$conf_dir"
    install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
            "$SCRIPT_DIR/recv.conf.example" "$conf_dir/recv.conf"
fi

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
echo "  1. On the ThinkPad run 'sudo tpkbd-pair'; it prints the line to append to"
echo "     ~/.ssh/authorized_keys (restricted to the receiver, section 7)."
echo "  2. Once connected, in KDE:"
echo "       Mouse -> 'ThinkPad remote pointer' -> acceleration None"
echo "       Touchpad -> 'ThinkPad remote pinch' -> tap-to-click off (section 9)."
echo
echo "$TARGET_USER was added to the uinput group; that takes effect on the next SSH login, no logout needed."
echo "Tuning: $conf_dir/recv.conf"
