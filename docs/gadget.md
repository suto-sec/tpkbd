# The Pi as a USB keyboard and mouse

Milestone 1 of v2: the Pi shows up as a real USB keyboard and mouse, and a self-test proves it. Nothing here talks to the ThinkPad's keyboard yet.

Placeholders: `<user>` and `<host>` are the user name and host name you gave the Pi in the imager.

## Why the test runs on the Pi only

While the Pi's USB cable is in the ThinkPad, the ThinkPad is the computer that receives the Pi's key presses. Do not run v1's `tpkbd-send` on the ThinkPad during these tests: its output would be typed straight back into it. The self-test types a fixed string and moves the pointer in a small square, then releases everything and exits.

## 1. Free the USB port from `g_ether`

The cable test used the old `g_ether` gadget. It holds the USB controller, so the new gadget can't start while it is loaded.

On the Pi, edit `/boot/firmware/cmdline.txt` (it must stay a single line) and change

```
modules-load=dwc2,g_ether
```

to

```
modules-load=dwc2
```

then `sudo reboot`. Keep `dtoverlay=dwc2` in `config.txt`, and keep Wi-Fi on: it is how you reach the Pi for now.

## 2. Install

From the ThinkPad, in the repo folder:

```bash
scp -r pi <user>@<host>.local:tpkbd-pi
ssh <user>@<host>.local
```

On the Pi:

```bash
sudo ./tpkbd-pi/install.sh
```

It installs `/usr/local/bin/tpkbd-hid`, a systemd unit that creates the gadget at every boot, a udev rule that lets the `tpkbd` group use `/dev/hidg*`, and the module list. It adds you to the `tpkbd` group (log out and in again for that to apply) and starts the gadget.

**Expected:** the last lines print `gadget: <controller>: ...`. A bare `down` or an error means something above isn't done; the script tells you which.

## 3. Check each part

| Check | Command (on the Pi) | Expected |
|---|---|---|
| Gadget exists | `ls /dev/hidg*` | `/dev/hidg0 /dev/hidg1` |
| Group access | `ls -l /dev/hidg*` | group `tpkbd`, mode `crw-rw----` |
| Host sees it | `tpkbd-hid gadget status` | `<controller>: configured` (`not attached` means no cable or a power-only cable) |
| Survives reboot | `sudo reboot`, then the commands above | same results |
| Idempotent | `sudo tpkbd-hid gadget up` twice | no error, status unchanged |

On the ThinkPad, with the Pi plugged in:

```bash
lsusb | grep -i 1d6b      # Linux Foundation, "tpkbd keyboard and mouse"
sudo libinput list-devices | grep -A3 tpkbd
```

**Expected:** a keyboard and a mouse called `tpkbd keyboard and mouse`, as two separate devices.

## 4. Run the self-test

On the ThinkPad, open a second terminal and watch the events:

```bash
sudo libinput debug-events --show-keycodes
```

Click into an empty text editor, then on the Pi:

```bash
tpkbd-hid test
```

After a 3 second countdown it types `Tpkbd test` and moves the pointer in a small square, then one scroll click down and up.

**Expected:**

- The text `Tpkbd test` appears in the editor, with a capital T (this checks the Shift modifier).
- The pointer draws a small square and ends where it began. On a laptop with pointer acceleration it may end a few pixels off; it must not drift away.
- `libinput debug-events` shows `KEYBOARD_KEY` events for the letters and `POINTER_MOTION` for the square, from the tpkbd devices.
- No key stays pressed afterwards: the editor doesn't keep typing, and `libinput debug-events` shows a matching release for every press.

Safety checks:

- **Interrupt mid-way.** Press Ctrl+C while it types. **Expected:** no stuck key afterwards (the final all-released report is sent even when you interrupt).
- **Host gone.** Unplug the Pi's cable from the ThinkPad while `tpkbd-hid test` runs, or run the test with nothing attached to the Pi's USB port. **Expected:** it stops with `the computer isn't reading the keyboard`, within a few seconds, instead of hanging.

## 5. The real target: BIOS and GRUB

Plug the Pi's USB port into the target PC instead, with the Pi powered from its own supply (PWR IN) if the PC cuts USB power when it is off. Reboot the PC and, in the BIOS or boot menu, run `tpkbd-hid test` over Wi-Fi/SSH. **Expected:** the text shows in a BIOS field or the GRUB command line (`c`). Many BIOSes need "USB legacy support" turned on.

This is the check that proves the whole point of v2. Report what you see: which BIOS, whether it saw the keyboard, and whether the mouse did anything.

## Known limits of this milestone

- The keyboard is a boot-protocol keyboard: 6 keys at once plus modifiers. A seventh key makes it report "too many keys" until one is released.
- Media and Fn keys (volume, brightness) aren't mapped: they need a different report.
- The mouse has a vertical wheel but no horizontal one.
- There is no pinch-to-zoom.
- The ThinkPad isn't connected to the Pi's keyboard yet: that comes next, and needs the USB-to-TTL adapter (or the temporary Wi-Fi link) to carry the events.
