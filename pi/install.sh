#!/bin/sh
# Install the tpkbd USB gadget on the Pi. Run with sudo from this folder (or a copy of it):
#
#   sudo ./install.sh
#
# It does not touch /boot/firmware: dtoverlay=dwc2 in config.txt is a manual step (docs/gadget.md).
set -eu

here=$(cd "$(dirname "$0")" && pwd)
[ "$(id -u)" -eq 0 ] || { echo "run with sudo: sudo $0" >&2; exit 1; }

if [ ! -d /sys/class/udc ] || [ -z "$(ls /sys/class/udc 2>/dev/null)" ]; then
    echo "warning: no USB device controller yet. Add dtoverlay=dwc2 to /boot/firmware/config.txt and reboot." >&2
fi
if [ -d /sys/module/g_ether ]; then
    echo "warning: g_ether is loaded and will keep the USB port busy." >&2
    echo "         remove it from /boot/firmware/cmdline.txt (modules-load=dwc2,g_ether -> modules-load=dwc2) and reboot." >&2
fi

getent group tpkbd >/dev/null || groupadd --system tpkbd
install -m 755 "$here/tpkbd-hid" /usr/local/bin/tpkbd-hid
install -m 644 "$here/tpkbd-gadget.service" /etc/systemd/system/tpkbd-gadget.service
install -m 644 "$here/60-tpkbd-hid.rules" /etc/udev/rules.d/60-tpkbd-hid.rules
install -m 644 "$here/tpkbd-modules.conf" /etc/modules-load.d/tpkbd.conf

user=${SUDO_USER:-}
if [ -n "$user" ] && [ "$user" != root ]; then
    usermod -aG tpkbd "$user"
    echo "added $user to the tpkbd group (log out and in again for it to apply)"
fi

udevadm control --reload
systemctl daemon-reload
systemctl enable tpkbd-gadget.service
if systemctl restart tpkbd-gadget.service; then
    echo "gadget: $(/usr/local/bin/tpkbd-hid gadget status)"
else
    echo "the gadget failed to start: journalctl -u tpkbd-gadget" >&2
    exit 1
fi
echo "Next: plug the Pi's USB port into a computer and run: tpkbd-hid test (see docs/gadget.md)"
