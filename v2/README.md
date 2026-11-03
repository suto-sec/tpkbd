# tpkbd v2: a Raspberry Pi as the USB keyboard and mouse

A Raspberry Pi Zero 2 W plugged into the target computer acts as a real USB keyboard, mouse and media-key device. The ThinkPad feeds it over a wire. The target sees ordinary USB hardware, so it works in the BIOS/UEFI, in bootloaders such as GRUB, in OS installers and on any operating system, with **nothing installed on the target**.

```
 ThinkPad T480                          Raspberry Pi Zero 2 W              target PC
 ------------                           ---------------------              ---------
 keyboard, TrackPoint, touchpad
   |  grabbed by tpkbd-send
   v
 [ wired: CP2102 adapter --3 wires--> GPIO UART ]--> tpkbd-recv --> USB gadget --USB--> sees a keyboard,
 [ or Wi-Fi: SSH ---------------------> sshd     ]    (v2/pi)       (tpkbd-hid)          a mouse, media keys
```

## Two links to the Pi

| | **Wired (UART)** | **Wireless (SSH over Wi-Fi)** |
|---|---|---|
| Role | **The real setup** | Temporary scaffolding, and how you manage the Pi |
| Needs | 3.3 V USB-to-TTL adapter + 3 jumper wires | Nothing extra, but a network and the Pi's IP |
| Typing path | No network | Wi-Fi: jitter, address changes |
| Pi side | `tpkbd-recv.service` always running | `sshd` starts `tpkbd-recv` per login |
| Sender setting | `link = serial` | `link = ssh` (the default) |
| Guide | [docs/wired.md](docs/wired.md) | [docs/wifi.md](docs/wifi.md) |

The ThinkPad sender (`v1/thinkpad/`) is **shared by v1 and v2**. It lives under `v1/` because v1 came first; it is the same program with a `link` setting.

## Start here

1. [docs/pi-setup.md](docs/pi-setup.md): USB gadget on the Pi, install, self-test. Do this first.
2. [docs/wired.md](docs/wired.md) (recommended) or [docs/wifi.md](docs/wifi.md): connect the ThinkPad.
3. [docs/boot-mode.md](docs/boot-mode.md): keyboard mode, soft mode, a GRUB entry that boots into it.
4. [docs/features.md](docs/features.md): what is forwarded, settings, limits.

## What is in this folder

| Path | What |
|---|---|
| `pi/tpkbd-hid` | Creates the USB gadget (configfs), the HID report builders, the self-test |
| `pi/tpkbd-recv` | Turns the line protocol into USB reports; stdin (SSH) or serial (UART) |
| `pi/install.sh`, `pi/uninstall.sh` | Install or remove everything on the Pi |
| `pi/*.service`, `pi/*.rules`, `pi/*.conf` | systemd units, udev rule, module list |
| `pi/recv.conf.example`, `pi/authorized_keys.example` | Receiver settings, the SSH forced-command line |
| `docs/` | The guides above |
| `tests/` | Unit tests, no hardware needed |

Run the tests from this folder: `python3 -m unittest discover -s tests -t .` (the wire tests need `python-evdev`, like v1's).

## Status

| Part | State |
|---|---|
| USB gadget, keyboard and mouse, self-test | Verified on real hardware, with the earlier two-function gadget |
| Wired link (UART) typing from the ThinkPad | Verified on real hardware, with the earlier gadget |
| The current gadget (four functions, 5-byte mouse report) | Verified: BIOS typing works with it. Pinch (touchpad) and volume also verified |
| Wi-Fi link | Written and unit-tested; the wire was used in practice |
| Media keys | Verified on real hardware |
| Pinch as a virtual touchpad (zoom around the pointer) | Verified on real hardware |
| Horizontal scroll | Written and unit-tested; **not yet tried on hardware** |
| Smooth (high-resolution) scrolling, `scroll = smooth` | Written and unit-tested; **not yet tried on hardware** (`scroll = click` is the verified descriptor) |
| Booting the ThinkPad into keyboard mode from GRUB | Documented, not yet tried |
| Typing in a real BIOS on the target over the wire | Verified on real hardware, also with the current four-function gadget (GRUB not tried) |
| Pointer speed (`scale`) tuned for a real USB mouse | Default 1.0, not tuned |

## Limits

- Boot-protocol keyboard: 6 keys at once plus modifiers.
- A pinch is two virtual fingers on a USB touchpad, so it is a real gesture on Linux targets. On other targets, or if the Pi can't bind the touchpad function, it falls back to Ctrl + wheel.
- The Pi must stay powered (PWR IN) and takes 20-30 s to boot. A microcontroller board such as a Raspberry Pi Pico boots instantly and would catch early key presses; a possible later port.
- The wire is unauthenticated. Keep it short and private.

## Planned, not built

- **Clipboard sharing in soft mode.** A plain USB keyboard has no way back from the target, so the two directions differ:
  - ThinkPad to target: possible by typing the clipboard text as key presses (a hotkey in soft mode). It would be slow, limited to what the target's keyboard layout can type, and no good for images.
  - Target to ThinkPad: not possible with a plain keyboard and mouse. It would need a second USB function on the Pi (a serial or storage device) and a small program on the target, which is what v2 avoids.
- **Pi powered only while the keyboard command runs.** Needs a switch for the Pi's power that the sender controls (a hub with per-port power switching, a switch driven by the adapter's DTR pin, or a smart plug). Pair it with a read-only root filesystem on the Pi.

See [../v1/](../v1/) for the software-only version.
