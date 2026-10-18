#!/bin/sh
# Remove what pi/install.sh added. /boot/firmware is left alone.
set -eu

[ "$(id -u)" -eq 0 ] || { echo "run with sudo: sudo $0" >&2; exit 1; }

systemctl disable --now tpkbd-gadget.service 2>/dev/null || true
rm -f /etc/systemd/system/tpkbd-gadget.service
rm -f /etc/udev/rules.d/60-tpkbd-hid.rules
rm -f /etc/modules-load.d/tpkbd.conf
rm -f /usr/local/bin/tpkbd-hid /usr/local/bin/tpkbd-recv
if getent group tpkbd >/dev/null; then
    groupdel tpkbd
fi
udevadm control --reload
systemctl daemon-reload
echo "removed. dtoverlay=dwc2 in /boot/firmware/config.txt is still there; remove it by hand if you want."
