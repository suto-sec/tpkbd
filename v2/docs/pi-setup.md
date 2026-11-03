# Pi setup: the USB keyboard and mouse

Do this first, whichever link you use afterwards ([wired](wired.md) or [Wi-Fi](wifi.md)). At the end the Pi shows up as a real USB keyboard, mouse and media-key device, and a self-test proves it.

Placeholders: `<user>` is the user name you gave the Pi in the imager, `<pi-ip>` its Wi-Fi address (`ip -br addr show wlan0` on the Pi). Use the IP: `<host>.local` doesn't resolve on a ThinkPad without mDNS.

## Hardware

- **Raspberry Pi Zero 2 W** with the GPIO header (the "WH" model).
- **Use the middle micro-USB port, labelled "USB".** It is the data (OTG) port and goes to the target PC. The corner port, "PWR IN", is power only.
- **Power the Pi from PWR IN**, so it keeps running when the PC reboots or cuts USB power. The two ports share a 5 V rail, so plugging both in can feed power back into the PC's USB port; a data-only cable on the "USB" port avoids that.
- **Cable quality matters.** A bad or long cable gives `-110`/`-71` errors and `disabled by hub (EMI?)` in the target's `dmesg`, and `tpkbd-hid gadget status` stays `not attached`. Use a short cable that carries data.

## Why the test runs on the Pi only

While the Pi's USB cable is in the ThinkPad, the ThinkPad is the computer that receives the Pi's key presses. Don't run `tpkbd-send` on the ThinkPad during these tests: its output would be typed straight back into it.

## 1. Free the USB port from `g_ether`

An old cable test may have left the `g_ether` gadget loaded. It holds the USB controller, so the new gadget can't start. On the Pi, edit `/boot/firmware/cmdline.txt` (it must stay a single line) and change

```
modules-load=dwc2,g_ether
```

to

```
modules-load=dwc2
```

Make sure `/boot/firmware/config.txt` has `dtoverlay=dwc2` under `[all]` (adding `dr_mode=peripheral`, as `dtoverlay=dwc2,dr_mode=peripheral`, makes the port more stable). Then `sudo reboot`. Keep Wi-Fi on: it is how you reach the Pi for setup.

## 2. Install

From the ThinkPad, in the repo folder:

```bash
scp -r v2/pi <user>@<pi-ip>:tpkbd-pi
ssh <user>@<pi-ip>
```

If `tpkbd-pi` already exists on the Pi, remove it there first (`rm -rf tpkbd-pi`), or `scp -r` nests the new copy inside the old one. On the Pi:

```bash
sudo ./tpkbd-pi/install.sh
```

It installs `tpkbd-hid` and `tpkbd-recv` in `/usr/local/bin`, the systemd units (`tpkbd-gadget` creates the USB gadget at every boot, `tpkbd-recv` is the UART receiver), a udev rule that lets the `tpkbd` group use `/dev/hidg*`, and the module list. It adds you to the `tpkbd` group (log out and in again) and starts the gadget. After updating an older install, reboot once so the gadget is recreated with the newest functions.

**Expected:** the last lines print `gadget: <controller>: ...`. A bare `down` or an error means something above isn't done; the script says which.

## 3. Check each part

| Check | Command (on the Pi) | Expected |
|---|---|---|
| Gadget exists | `ls /dev/hidg*` | `/dev/hidg0 /dev/hidg1 /dev/hidg2 /dev/hidg3` (three if the controller refused the touchpad: see below) |
| Group access | `ls -l /dev/hidg*` | group `tpkbd`, mode `crw-rw----` |
| Host sees it | `tpkbd-hid gadget status` | `<controller>: configured` (`not attached`: no cable, a power-only cable, or a bad one) |
| Survives reboot | `sudo reboot`, then the commands above | same results |
| Idempotent | `sudo tpkbd-hid gadget up` twice | no error, status unchanged |

`hidg0` is the keyboard, `hidg1` the mouse, `hidg2` the media keys, `hidg3` the touchpad used for pinch.

If only three devices exist, the Pi's USB controller has too few endpoints for a fourth function. `tpkbd-hid gadget up` then retries without the touchpad (the keyboard and mouse still work) and says so in `journalctl -u tpkbd-gadget`; pinch falls back to Ctrl + wheel. `dmesg | grep -i -E "dwc2|gadget"` shows the controller's complaint.

On the ThinkPad, with the Pi plugged in:

```bash
lsusb | grep -i 1d6b      # Linux Foundation, "tpkbd keyboard and mouse"
sudo libinput list-devices | grep -A3 tpkbd
```

**Expected:** the keyboard, mouse, consumer-control and touchpad devices called `tpkbd keyboard and mouse`, as separate devices.

## 4. Run the self-test

On the ThinkPad, watch the events in a second terminal:

```bash
sudo libinput debug-events --show-keycodes
```

Click into an empty text editor, then on the Pi:

```bash
tpkbd-hid test
```

After a 3 second countdown it types `Tpkbd test`, moves the pointer in a small square, then does one scroll click down and up.

**Expected:**

- `Tpkbd test` appears in the editor, with a capital T (this checks the Shift modifier).
- The pointer draws a small square and ends where it began. With pointer acceleration it may end a few pixels off; it must not drift away.
- `libinput debug-events` shows `KEYBOARD_KEY` for the letters and `POINTER_MOTION` for the square.
- No key stays pressed afterwards.

Safety checks:

- **Interrupt mid-way.** Press Ctrl+C while it types. **Expected:** no stuck key.
- **Host gone.** Unplug the Pi's cable while `tpkbd-hid test` runs. **Expected:** it stops with `the computer isn't reading the keyboard` within a few seconds, instead of hanging.

### Pinch test (Linux target)

On the Pi, with a browser open on the target and the pointer over a page or an image:

```bash
tpkbd-hid test-pinch
```

After a 3 second countdown two virtual fingers spread to three times their distance, then pinch back. **Expected:** the page zooms in around the pointer, then back out, and nothing stays held afterwards. Check on the target:

```bash
sudo libinput list-devices | grep -B1 -A12 -i "touchpad"   # the tpkbd device, with "Gestures: pinch"
sudo libinput debug-events                                  # while test-pinch runs
```

| What you see | Meaning |
|---|---|
| `GESTURE_PINCH_BEGIN`, `UPDATE` with a changing scale, `END` | Working. If the app still doesn't zoom, the app doesn't take touchpad pinches |
| `POINTER_SCROLL_FINGER` (or `GESTURE_SWIPE_*`) instead | The fingers' movement was read as a scroll: tune `half0` (distance between the fingers) in `recv.conf` |
| No new touchpad device | `hid-multitouch` didn't bind: on the target `dmesg \| grep -i -E "hid|multitouch"`, and check `ls /dev/hidg*` on the Pi shows four devices |

## 5. The real target: BIOS and GRUB

This is the check that proves the point of v2, and it has not been done yet.

1. Plug the Pi's "USB" port into the target PC and power the Pi from PWR IN. Let the Pi finish booting (20-30 s) *before* the target starts.
2. Reboot the target and, in the BIOS or GRUB menu, run `tpkbd-hid test` from an SSH session to the Pi. Or use the link you set up ([wired](wired.md), [Wi-Fi](wifi.md)) and type with the ThinkPad.
3. **Expected:** the text shows in a BIOS field or the GRUB command line (press `c` in GRUB). Many BIOSes need "USB legacy support" turned on.

If the firmware doesn't see the keyboard: the gadget gained interfaces (media keys, a touchpad) and a longer mouse report after the earlier tests, so suspect those first (and now the fourth function, the touchpad). `tpkbd-hid gadget down`, then recreate the gadget with an older checkout, tells you whether the new descriptors are the cause.

Record which BIOS you tried, whether it saw the keyboard, and whether the mouse or the media keys did anything. GRUB and many BIOSes never poll the mouse; that is normal.

## Next

- [wired.md](wired.md): the UART wire (the real setup).
- [wifi.md](wifi.md): SSH over Wi-Fi (temporary, easier to start with).
- [boot-mode.md](boot-mode.md): boot the ThinkPad straight into keyboard mode.
- [features.md](features.md): what is forwarded, and what isn't.
