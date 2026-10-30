#!/usr/bin/env bash
# Installs the sender side. Run with sudo from the repo (or after
# copying the thinkpad/ directory anywhere, the script finds its own files).
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "run as root: sudo $0" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --serial: the receiver is the Pi on the UART wire, so no ssh key or address is needed
SERIAL=0
if [[ "${1:-}" == "--serial" ]]; then
    SERIAL=1
fi

if command -v pacman >/dev/null 2>&1; then
    pacman -S --needed --noconfirm python-evdev openssh libinput
fi

install -m 755 "$SCRIPT_DIR/tpkbd-send" /usr/local/bin/tpkbd-send
install -m 755 "$SCRIPT_DIR/tpkbd-screen" /usr/local/bin/tpkbd-screen
install -m 755 "$SCRIPT_DIR/tpkbd-pair" /usr/local/bin/tpkbd-pair

# the service runs as its own user instead of root; "input" gives it the devices
if ! id tpkbd >/dev/null 2>&1; then
    useradd --system --no-create-home --home-dir /nonexistent \
            --shell "$(command -v nologin || echo /usr/bin/nologin)" tpkbd
fi
usermod -aG input tpkbd
# serial ports belong to uucp (Arch) or dialout (Debian and friends)
for grp in uucp dialout; do
    if getent group "$grp" >/dev/null; then
        usermod -aG "$grp" tpkbd
    fi
done

install -d -m 700 /etc/tpkbd

if [[ $SERIAL -eq 1 ]]; then
    echo "--serial: skipping the ssh key and address"
elif [[ ! -f /etc/tpkbd/id_ed25519 ]]; then
    ssh-keygen -t ed25519 -N "" -C tpkbd -f /etc/tpkbd/id_ed25519
else
    echo "/etc/tpkbd/id_ed25519 already exists, keeping it"
fi

if [[ $SERIAL -eq 1 ]]; then
    :
elif [[ ! -f /etc/tpkbd/ssh_config ]]; then
    read -rp "Receiver's IP address: " receiver_ip
    read -rp "Receiver's username: " receiver_user
    # the values go into sed replacements: refuse anything that could break them
    re='^[A-Za-z0-9._:-]+$'
    if [[ ! "$receiver_ip" =~ $re || ! "$receiver_user" =~ $re ]]; then
        echo "IP address or username has unexpected characters, aborting" >&2
        exit 1
    fi
    sed -e "s/^\( *HostName \).*/\1$receiver_ip/" \
        -e "s/^\( *User \).*/\1$receiver_user/" \
        "$SCRIPT_DIR/ssh_config.example" > /etc/tpkbd/ssh_config
else
    echo "/etc/tpkbd/ssh_config already exists, keeping it"
fi

if [[ ! -f /etc/tpkbd/tpkbd.conf ]]; then
    install -m 644 "$SCRIPT_DIR/tpkbd.conf.example" /etc/tpkbd/tpkbd.conf
fi

if [[ $SERIAL -eq 1 ]]; then
    if grep -q '^[[:space:]]*link[[:space:]]*=' /etc/tpkbd/tpkbd.conf; then
        sed -i 's|^[[:space:]]*link[[:space:]]*=.*|link = serial|' /etc/tpkbd/tpkbd.conf
    else
        sed -i '/^\[sender\]/a link = serial' /etc/tpkbd/tpkbd.conf
    fi
    echo "set link = serial in /etc/tpkbd/tpkbd.conf"
fi

# older installs left these root-owned; the service user has to read them
chown -R tpkbd:tpkbd /etc/tpkbd
chmod 700 /etc/tpkbd
if [[ $SERIAL -eq 0 ]]; then
    chmod 600 /etc/tpkbd/id_ed25519 /etc/tpkbd/ssh_config
fi

install -m 644 "$SCRIPT_DIR/tpkbd-mode.target" /etc/systemd/system/tpkbd-mode.target
install -m 644 "$SCRIPT_DIR/tpkbd-forward.service" /etc/systemd/system/tpkbd-forward.service
install -m 644 "$SCRIPT_DIR/tpkbd-soft.service" /etc/systemd/system/tpkbd-soft.service
systemctl daemon-reload
systemctl enable tpkbd-forward.service

if [[ $SERIAL -eq 1 ]]; then
    echo
    echo "Serial link ready (port: serial_port in /etc/tpkbd/tpkbd.conf, default /dev/ttyUSB0)."
    echo "Test with: sudo tpkbd-send    (docs/gadget.md section 7 at the repo root)"
    echo "Then either keyboard mode or soft mode:"
    echo "  sudo systemctl isolate tpkbd-mode.target    or    sudo systemctl start tpkbd-soft"
    exit 0
fi

echo
echo "Remaining manual steps (see docs/setup.md):"
echo "  1. Double-check /etc/tpkbd/ssh_config (HostName and User)."
echo "  2. With the PC on, run: sudo tpkbd-pair"
echo "     It pins the PC's SSH host key (you compare the fingerprint) and"
echo "     prints the line to append to ~/.ssh/authorized_keys on the PC."
echo "  3. Make Wi-Fi available system-wide and disable power saving (section 10)."
echo "  4. Test with: sudo -u tpkbd tpkbd-send   (or as root: sudo tpkbd-send)"
echo
echo "Then either:"
echo "  keyboard mode (closes the desktop, panel off):"
echo "      sudo systemctl isolate tpkbd-mode.target"
echo "  soft mode (desktop stays, Ctrl + Ctrl + Space switches between laptop and PC):"
echo "      sudo systemctl start tpkbd-soft"
