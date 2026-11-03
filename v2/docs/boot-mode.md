# Keyboard mode, soft mode and booting into it

The ThinkPad side works the same for v1 and v2 and for both links ([wired](wired.md), [Wi-Fi](wifi.md)): it has two modes. Make sure `sudo tpkbd-send` works by hand before using either.

| | Keyboard mode | Soft mode |
|---|---|---|
| What happens | The desktop closes, the panel switches off, the ThinkPad is only a keyboard | The desktop stays; a hotkey hands input to the target and back |
| Start | `sudo systemctl isolate tpkbd-mode.target` | `sudo systemctl start tpkbd-soft` |
| Back to the ThinkPad | Left Ctrl + Right Ctrl + Esc, then log in on tty1 and run `sudo systemctl isolate graphical.target` | The same hotkey: Left Ctrl + Right Ctrl + Space |
| Stop | Left Ctrl + Right Ctrl + Esc | `sudo systemctl stop tpkbd-soft` |

Both use whichever link `/etc/tpkbd/tpkbd.conf` selects (`link = serial` for the wire, `ssh` or nothing for SSH). The `isolate` command saves nothing: save your work first, the desktop closes.

**Soft mode keeps the laptop awake while input is on the PC.** Otherwise the laptop would see no input, suspend after its idle time, and need the power button. While input goes to the PC, `tpkbd-send` holds a systemd sleep and idle inhibitor (`systemd-inhibit`), and lets go when you switch back or stop the service. Check with `systemd-inhibit --list` (a `tpkbd` row). It does not stop the screen from dimming or locking, and closing the lid still follows your normal lid setting. To turn it off, set `inhibit_sleep = no` in `/etc/tpkbd/tpkbd.conf` and restart `tpkbd-soft`. Keyboard mode does not use it.

If the panel stays black after leaving keyboard mode, press the power button: the forced-off state doesn't survive a reboot.

## A GRUB entry that boots straight into keyboard mode

This is optional. It boots your normal system with `systemd.unit=tpkbd-mode.target`, so no desktop ever starts. Your normal entry stays in the menu, so nothing is lost if keyboard mode fails.

1. Find your entry's title: `grep ^menuentry /boot/grub/grub.cfg`.
2. Run this on the ThinkPad, replacing `Arch Linux` with that title if it differs (the `$TMPDIR` fallback is `/tmp`):
   ```bash
   T=${TMPDIR:-/tmp}
   sudo awk "/^menuentry 'Arch Linux'/,/^}/" /boot/grub/grub.cfg > "$T/tpkbd-entry"
   sed -i -e "1s/'Arch Linux'/'Arch (keyboard mode)'/" \
          -e "1s/gnulinux-simple-/tpkbd-mode-/" \
          -e '/^\s*linux\s/s/$/ systemd.unit=tpkbd-mode.target/' "$T/tpkbd-entry"
   cat "$T/tpkbd-entry"       # check: the title changed, the linux line ends with systemd.unit=tpkbd-mode.target
   { echo; cat "$T/tpkbd-entry"; } | sudo tee -a /etc/grub.d/40_custom > /dev/null
   sudo grub-mkconfig -o /boot/grub/grub.cfg
   ```
3. Reboot and choose "Arch (keyboard mode)".

Things to know:

- No user session logs in, so with the **SSH link** Wi-Fi has to be available system-wide ([v1/docs/setup.md](../../v1/docs/setup.md#10-sender-wi-fi)). The **wire** needs no network.
- The sender grabs the ThinkPad's keyboard as soon as the Pi's receiver answers, even if the Pi isn't plugged into a target, so the keys then go nowhere. Left Ctrl + Right Ctrl + Esc stops it. If the Pi is off or unreachable it never grabs the keyboard and the panel stays on.
- The full v1 explanation of the entry is in [v1/docs/setup.md](../../v1/docs/setup.md#18-optional-grub-entry).
