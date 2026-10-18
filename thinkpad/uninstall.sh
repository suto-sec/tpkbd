#!/usr/bin/env bash
# Removes the sender side. Run with sudo. Keeps /etc/tpkbd (your keys and
# config) unless you say otherwise.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "run as root: sudo $0" >&2
    exit 1
fi

systemctl disable --now tpkbd-forward.service tpkbd-soft.service 2>/dev/null || true
# the stop runs tpkbd-screen post, which turns the panel back on; do it again in
# case the service wasn't running but the panel is still forced off
if compgen -G '/run/tpkbd-brightness.*' >/dev/null; then
    EXIT_STATUS=0 /usr/local/bin/tpkbd-screen post || true
fi

rm -f /etc/systemd/system/tpkbd-forward.service \
      /etc/systemd/system/tpkbd-soft.service \
      /etc/systemd/system/tpkbd-mode.target
systemctl daemon-reload
rm -f /usr/local/bin/tpkbd-send /usr/local/bin/tpkbd-screen /usr/local/bin/tpkbd-pair

read -rp "Also delete /etc/tpkbd (SSH key, config, pinned host key) and the tpkbd user? [y/N] " reply
if [[ "$reply" =~ ^[Yy]$ ]]; then
    rm -r /etc/tpkbd
    userdel tpkbd 2>/dev/null || true
else
    echo "kept /etc/tpkbd and the tpkbd user"
fi

echo
echo "On the PC: run pc/uninstall.sh, which also removes the key from authorized_keys."
