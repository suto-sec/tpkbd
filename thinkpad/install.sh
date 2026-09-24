#!/usr/bin/env bash
# Installs the sender side. Run with sudo from the repo (or after
# copying the thinkpad/ directory anywhere, the script finds its own files).
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "run as root: sudo $0" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if command -v pacman >/dev/null 2>&1; then
    pacman -S --needed --noconfirm python-evdev openssh libinput
fi

install -m 755 "$SCRIPT_DIR/tpkbd-send" /usr/local/bin/tpkbd-send
install -m 755 "$SCRIPT_DIR/tpkbd-screen" /usr/local/bin/tpkbd-screen

install -d -m 700 /etc/tpkbd

if [[ ! -f /etc/tpkbd/id_ed25519 ]]; then
    ssh-keygen -t ed25519 -N "" -C tpkbd -f /etc/tpkbd/id_ed25519
else
    echo "/etc/tpkbd/id_ed25519 already exists, keeping it"
fi

if [[ ! -f /etc/tpkbd/ssh_config ]]; then
    read -rp "Receiver's IP address: " receiver_ip
    read -rp "Receiver's username: " receiver_user
    sed -e "s/^\( *HostName \).*/\1$receiver_ip/" \
        -e "s/^\( *User \).*/\1$receiver_user/" \
        "$SCRIPT_DIR/ssh_config.example" > /etc/tpkbd/ssh_config
    chmod 600 /etc/tpkbd/ssh_config
else
    echo "/etc/tpkbd/ssh_config already exists, keeping it"
fi

install -m 644 "$SCRIPT_DIR/tpkbd-mode.target" /etc/systemd/system/tpkbd-mode.target
install -m 644 "$SCRIPT_DIR/tpkbd-forward.service" /etc/systemd/system/tpkbd-forward.service
systemctl daemon-reload
systemctl enable tpkbd-forward.service

echo
echo "Public key (authorize this on the receiver, see pc/authorized_keys.example):"
cat /etc/tpkbd/id_ed25519.pub
echo
echo "Remaining manual steps (see docs/setup.md):"
echo "  1. Double-check /etc/tpkbd/ssh_config (HostName and User)."
echo "  2. Authorize the key above on the receiver (section 7)."
echo "  3. Verify the SSH host key fingerprint matches (section 7)."
echo "  4. Make Wi-Fi available system-wide and disable power saving (section 10)."
echo "  5. Test with: sudo tpkbd-send"
echo
echo "Then start keyboard mode with: sudo systemctl isolate tpkbd-mode.target"
