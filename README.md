# tpkbd

Use a ThinkPad T480 as a wireless keyboard, TrackPoint and touchpad for another Linux PC.

The ThinkPad switches off its screen, grabs its own input and sends it over the LAN (via SSH) to the PC, where it shows up as a normal keyboard, mouse and touchpad. Pinch-to-zoom works too. Holding both Ctrl keys and pressing Esc hands the input back to the ThinkPad.

## How it works

```
ThinkPad                                         PC
--------                                         --
keyboard ----- evdev ------+
                           +-- tpkbd-send == SSH ==> tpkbd-recv --> uinput devices:
TrackPoint --+             |                                          - keyboard
touchpad ----+- libinput --+                                          - pointer
                                                                      - pinch (touchpad)
```

- **Keyboard**: raw key events are forwarded as-is. The PC applies its own layout.
- **TrackPoint / touchpad**: processed on the ThinkPad by `libinput debug-events`, so acceleration, tapping, scrolling and palm detection behave exactly like on the laptop. Only the resulting motion, clicks and scroll deltas are sent. Doing this on the receiving side instead makes the pointer choppy, because libinput's acceleration depends on event timing and Wi-Fi delivers packets in bursts.
- **Pinch**: there is no way to inject a gesture directly, so the PC has a virtual touchpad that is only used for pinches. The receiver places two fake fingers on it and moves them apart/together to match the zoom factor reported by the ThinkPad.
- **Smoothing**: every event carries its original timestamp and the receiver replays events with their original spacing, 15 ms behind. This hides most Wi-Fi jitter.
- **Screen**: in keyboard mode the internal panel is powered off completely (DRM connector forced off), and restored on exit.

The ThinkPad side runs as a systemd service inside a dedicated target (`tpkbd-mode.target`), which is basically `multi-user.target` without the desktop. It retries every 3 s if the PC isn't reachable.

On the PC, the SSH key is restricted in `authorized_keys` to a single forced command, so it can only start the receiver.

## Repository layout

```
thinkpad/
  install.sh               installer, run with sudo
  tpkbd-send               sender (Python, runs as root)
  tpkbd-screen             panel off/on helper
  tpkbd-forward.service    systemd service
  tpkbd-mode.target        "keyboard mode" target
  ssh_config.example       goes to /etc/tpkbd/ssh_config
pc/
  install.sh               installer, run with sudo
  tpkbd-recv               receiver (Python)
  60-tpkbd-uinput.rules    udev rule for /dev/uinput
  tpkbd-uinput.conf        loads the uinput module at boot
  99-tpkbd.conf            Xorg fallback (flat accel), unused on Wayland
  authorized_keys.example  the restricted key line
docs/
  setup.md                 full setup and troubleshooting guide
```

## Requirements

- Both machines on Arch Linux (should work on any distro with the same packages)
- ThinkPad: `python-evdev`, `openssh`, `libinput`
- PC: `python-evdev`, an SSH server, KDE Plasma on Wayland (X11 works too, but pinch support there depends on the app)
- Both on the same network

## Setup

Each side has an installer that handles the file copying, permissions, udev rule and systemd unit:

```bash
# PC
sudo pc/install.sh

# ThinkPad
sudo thinkpad/install.sh
```

They can't do everything: SSH key exchange, the receiver's IP/user, and a couple of GUI-only settings still need a manual step, which the installers print at the end. The full walkthrough, including what to do if something doesn't work, is in [docs/setup.md](docs/setup.md). Roughly, after running both installers:

**PC**
1. Add the ThinkPad's public key to `~/.ssh/authorized_keys` using the line in `authorized_keys.example` (the installer prints the key).
2. In KDE settings, set pointer acceleration to "None" for *ThinkPad remote pointer* and disable tap-to-click for *ThinkPad remote pinch*.

**ThinkPad**
1. Make the Wi-Fi connection available system-wide (no KWallet) and turn off Wi-Fi power saving.

## Usage

On the ThinkPad:

```bash
sudo systemctl isolate tpkbd-mode.target    # start keyboard mode (closes the desktop)
# Ctrl + Ctrl + Esc                         # stop, screen comes back
sudo systemctl isolate graphical.target     # back to the desktop
```

For testing with visible output, run `sudo tpkbd-send` from a terminal instead.

## Tuning

| Setting | File | Default | |
|---|---|---|---|
| `SCALE` | `tpkbd-recv` | `1.25` | pointer multiplier: PC width in px / ThinkPad logical width |
| `JITTER_MS` | `tpkbd-recv` | `15` | smoothing buffer |
| `LIBINPUT_OPTS` | `tpkbd-send` | adaptive, speed 0, tap on | how the ThinkPad processes pointer input |
| `KEYBOARD`, `POINTING` | `tpkbd-send` | T480 device names | from `grep Name= /proc/bus/input/devices` |

## Limitations

- Only works once the PC has booted into an OS with the receiver installed. BIOS, bootloader and other OSes still need a real keyboard.
- The lid has to stay open.
- Three- and four-finger gestures aren't forwarded.
- Pointer input relies on parsing the text output of `libinput debug-events`, which isn't a stable interface. libinput 1.31 added a repeat counter column, for example. If the pointer suddenly barely moves after an update, that's the first place to look.

## License

MIT, see [LICENSE](LICENSE).
