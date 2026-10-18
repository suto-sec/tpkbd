# tpkbd v1

The software-only version: the PC runs a receiver and needs a booted OS. Paths below are relative to this folder, so run the installers from here (`cd v1`).

Use a ThinkPad T480 as a wireless keyboard, TrackPoint and touchpad for another Linux PC.

The ThinkPad switches off its screen, grabs its own input and sends it over the LAN (via SSH) to the PC, where it shows up as a normal keyboard, mouse and touchpad. Pinch-to-zoom works too. Holding both Ctrl keys and pressing Esc hands the input back to the ThinkPad.

There are two ways to use it:

- **Keyboard mode**: the ThinkPad's desktop closes, the panel goes off and the laptop is only a keyboard.
- **Soft mode**: the desktop stays up and a hotkey (both Ctrl keys + Space) hands the keyboard, TrackPoint and touchpad to the PC and back, like a software KVM.

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
- **Screen**: in keyboard mode the internal panel is powered off completely (DRM connector forced off) once the PC has answered, and restored on exit, or if the PC stays away for five minutes.
- **Safety**: the sender sends a heartbeat every second. If the receiver hears nothing for 3 s it releases every key and button, so a dropped connection can't leave a key repeating on the PC.

The ThinkPad side runs as a systemd service inside a dedicated target (`tpkbd-mode.target`), which is basically `multi-user.target` without the desktop. It retries every 3 s if the PC isn't reachable.

On the PC, the SSH key is restricted in `authorized_keys` to a single forced command, so it can only start the receiver.

## Repository layout

```
thinkpad/
  install.sh               installer, run with sudo
  uninstall.sh             removes everything the installer added
  tpkbd-send               sender (Python, runs as the unprivileged tpkbd user)
  tpkbd-screen             panel off/on helper (runs as root from the service)
  tpkbd-pair               pins the PC's SSH host key, prints the authorized_keys line
  tpkbd-forward.service    systemd service for keyboard mode
  tpkbd-soft.service       systemd service for soft mode
  tpkbd-mode.target        "keyboard mode" target
  tpkbd.conf.example       goes to /etc/tpkbd/tpkbd.conf
  ssh_config.example       goes to /etc/tpkbd/ssh_config
pc/
  install.sh               installer, run with sudo
  uninstall.sh             removes everything the installer added
  tpkbd-recv               receiver (Python)
  recv.conf.example        goes to ~/.config/tpkbd/recv.conf
  60-tpkbd-uinput.rules    udev rule for /dev/uinput
  tpkbd-uinput.conf        loads the uinput module at boot
  99-tpkbd.conf            Xorg fallback (flat accel), unused on Wayland
  authorized_keys.example  the restricted key line
docs/
  setup.md                 full setup and troubleshooting guide
  testing.md               how to check that each part works
tests/                     unit tests (python3 -m unittest discover -s tests -t .)
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

They can't do everything: SSH key exchange and a couple of GUI-only settings still need a manual step, which the installers print at the end. The full walkthrough, including what to do if something doesn't work, is in [docs/setup.md](docs/setup.md). Roughly, after running both installers:

**ThinkPad**
1. With the PC on, run `sudo tpkbd-pair`. It shows the PC's SSH host key fingerprint for you to compare, pins it, and prints the line to append to `~/.ssh/authorized_keys` on the PC.
2. Make the Wi-Fi connection available system-wide (no KWallet) and turn off Wi-Fi power saving.

**PC**
1. Append that line to `~/.ssh/authorized_keys`.
2. In KDE settings, set pointer acceleration to "None" for *ThinkPad remote pointer* and disable tap-to-click for *ThinkPad remote pinch*.

## Usage

On the ThinkPad, keyboard mode:

```bash
sudo systemctl isolate tpkbd-mode.target    # start keyboard mode (closes the desktop)
# Ctrl + Ctrl + Esc                         # stop, screen comes back
sudo systemctl isolate graphical.target     # back to the desktop
```

Or soft mode, which leaves the desktop alone:

```bash
sudo systemctl start tpkbd-soft             # connect, input stays on the ThinkPad
# Ctrl + Ctrl + Space                       # input goes to the PC
# Ctrl + Ctrl + Space                       # and back
cat /run/tpkbd/state                        # which side has it: local or remote
sudo systemctl stop tpkbd-soft
```

The switch happens once every key is released, so nothing gets stuck on either side. If the connection drops while the PC has the input, it comes back to the ThinkPad.

For testing with visible output, run `sudo tpkbd-send` (or `sudo tpkbd-send --soft`) from a terminal instead.

## Tuning

Settings live in config files, so updating the scripts doesn't overwrite them. Every line is optional.

| Setting | File | Default | |
|---|---|---|---|
| `scale` | `~/.config/tpkbd/recv.conf` (PC) | `1.25` | pointer multiplier: PC width in px / ThinkPad logical width |
| `jitter_ms` | `recv.conf` | `15` | smoothing buffer, `0` is fine on Ethernet |
| `watchdog_s`, `dead_s` | `recv.conf` | `3`, `30` | silence before keys are released / before the receiver exits |
| `libinput_opts` | `/etc/tpkbd/tpkbd.conf` (ThinkPad) | adaptive, speed 0, tap on | how the ThinkPad processes pointer input |
| `keyboard`, `pointing` | `tpkbd.conf` | T480 device names | from `grep Name= /proc/bus/input/devices` |
| `block_keys` | `tpkbd.conf` | sleep, suspend, wakeup, power | keys that are never forwarded |
| `escape_keys`, `toggle_keys` | `tpkbd.conf` | Ctrl+Ctrl+Esc, Ctrl+Ctrl+Space | the two hotkeys |

Restart the service (or reconnect) after editing.

## Limitations

- Only works once the PC has booted into an OS with the receiver installed. BIOS, bootloader and other OSes still need a real keyboard.
- The lid has to stay open (closing it covers the keyboard anyway).
- Three- and four-finger gestures aren't forwarded.
- In soft mode the laptop's desktop gets no input while the PC has it, so its screen lock and (on battery) suspend timers keep running.
- Pointer input relies on parsing the text output of `libinput debug-events`, which isn't a stable interface. libinput 1.31 added a repeat counter column, for example. If the pointer suddenly barely moves after an update, that's the first place to look.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```

The unit tests need no hardware. [docs/testing.md](docs/testing.md) lists what to check on the real machines.

## License

MIT, see [LICENSE](../LICENSE).
