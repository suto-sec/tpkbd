#!/usr/bin/env bash
# Removes the receiver side. Run with sudo from your normal user.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "run as root: sudo $0" >&2
    exit 1
fi
if [[ -z "${SUDO_USER:-}" || "$SUDO_USER" == root ]]; then
    echo "run it with sudo from your normal user" >&2
    exit 1
fi

TARGET_USER="$SUDO_USER"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
keys="$TARGET_HOME/.ssh/authorized_keys"

# the key line is recognisable by its forced command; the comment above it is ours
if [[ -f "$keys" ]] && grep -qF 'exec /usr/local/bin/tpkbd-recv' "$keys"; then
    read -rp "Remove the tpkbd key from $keys (a backup is kept)? [y/N] " reply
    if [[ "$reply" =~ ^[Yy]$ ]]; then
        cp -p "$keys" "$keys.tpkbd-backup"
        grep -vF 'exec /usr/local/bin/tpkbd-recv' "$keys.tpkbd-backup" | grep -vx '# tpkbd' > "$keys" || true
        chown "$TARGET_USER": "$keys"
        echo "removed; the old file is $keys.tpkbd-backup"
    fi
fi

rm -f /usr/local/bin/tpkbd-recv \
      /etc/modules-load.d/tpkbd-uinput.conf \
      /etc/udev/rules.d/60-tpkbd-uinput.rules \
      /etc/X11/xorg.conf.d/99-tpkbd.conf
udevadm control --reload
gpasswd -d "$TARGET_USER" uinput 2>/dev/null || true
echo "left $TARGET_HOME/.config/tpkbd/recv.conf and the uinput group in place"
