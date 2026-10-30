# What is forwarded, and what isn't

The keyboard, pointer and vertical scroll rows were verified with the earlier gadget. **Media keys, horizontal scroll and pinch are written and unit-tested but not yet tried on hardware**, and the brightness keys may come from an input device the sender doesn't grab (check `grep Name= /proc/bus/input/devices` and the `keyboard` setting).

| ThinkPad input | On the target | Notes |
|---|---|---|
| Letters, digits, punctuation, modifiers, F1-F12, navigation, keypad | USB keyboard (boot protocol) | 6 keys at once plus modifiers. A 7th key reports "too many keys" until one is released. |
| Volume, mute, play/pause, next/previous, stop, brightness, calculator, mail, home page | USB consumer-control device (`/dev/hidg2`) | One media key at a time. Needs a gadget recreated by the current installer (reboot after updating). Not seen by a BIOS. |
| TrackPoint, touchpad motion and buttons | USB mouse | Processed by libinput on the ThinkPad (acceleration, tap, palm detection). Pointer speed: `scale` in `recv.conf`. |
| Scroll, vertical and horizontal | Mouse wheel and AC Pan | Horizontal scroll needs a host that understands AC Pan; boot-protocol hosts ignore it. |
| Pinch to zoom | Ctrl + mouse wheel | A plain USB device can't do a touchpad gesture, so spreading fingers sends Ctrl + wheel up (zoom in), pinching sends Ctrl + wheel down. `pinch_clicks` in `recv.conf` is the number of wheel clicks per doubling (default 6). |
| Fn+4 (sleep), power | **Not forwarded** | Blocked on purpose (`block_keys`), so it can't suspend the target. |
| Other Fn combinations that have no standard USB code | Not forwarded | |

## In the BIOS and bootloaders

Firmware reads the boot-protocol keyboard and, if it polls it at all, the first three bytes of the mouse report. So keys work, and the mouse often does not (GRUB ignores it). Media keys, horizontal scroll and pinch only exist once an OS is running. Many BIOSes need "USB legacy support".

## Settings

On the Pi, `/etc/tpkbd/recv.conf` (the UART service) or `~/.config/tpkbd/recv.conf` (SSH link), from `recv.conf.example`:

| Key | Default | Meaning |
|---|---|---|
| `scale` | `1.0` | Pointer speed multiplier |
| `pinch_clicks` | `6` | Ctrl+wheel clicks per doubling of the pinch distance |
| `watchdog_s` | `3` | Silence this long: release every key and button |
| `dead_s` | `30` | SSH link only: silence this long, the sender is gone, exit |

On the ThinkPad, `/etc/tpkbd/tpkbd.conf` (`link`, `serial_port`, `baud`, the device names, `block_keys`, `escape_keys`, `toggle_keys`), from `v1/thinkpad/tpkbd.conf.example`.

## Safety behaviour

- A write to the host never blocks for long: mouse motion is dropped at once when the host isn't reading, so a BIOS that ignores the mouse can't stall your typing.
- Everything is released on disconnect, on silence and on exit, including a Ctrl held for a pinch.
- The Pi is a high-trust device: whatever can talk to its serial port or SSH can type on the target.
