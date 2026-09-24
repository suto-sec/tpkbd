# Setup guide

Two machines are involved:

- **Sender**: the ThinkPad whose keyboard, TrackPoint and touchpad you want to use.
- **Receiver**: the PC that should receive the input.

Both run Arch Linux here. The receiver runs KDE Plasma on Wayland. Both need to be on the same network, and the receiver needs a fixed IP (a DHCP reservation in the router is enough). The sender's IP doesn't matter, since it always connects to the receiver and never the other way round.

Throughout this guide, `192.168.1.X` is the receiver's IP and `your-user` is the receiver's user. Commands are marked with the machine they run on.

## Contents

1. [How it works](#1-how-it-works)
2. [Packages](#2-packages)
3. [Receiver: uinput access](#3-receiver-uinput-access)
4. [Receiver: install the script](#4-receiver-install-the-script)
5. [Sender: find the input devices](#5-sender-find-the-input-devices)
6. [Sender: install the scripts](#6-sender-install-the-scripts)
7. [SSH](#7-ssh)
8. [First test](#8-first-test)
9. [Receiver: KDE settings](#9-receiver-kde-settings)
10. [Sender: Wi-Fi](#10-sender-wi-fi)
11. [Sender: keyboard mode (systemd)](#11-sender-keyboard-mode-systemd)
12. [Daily use](#12-daily-use)
13. [Tuning](#13-tuning)
14. [Protocol](#14-protocol)
15. [Troubleshooting](#15-troubleshooting)
16. [Security](#16-security)
17. [Uninstall](#17-uninstall)
18. [Optional: GRUB entry](#18-optional-grub-entry)

---

## 1. How it works

```
SENDER (keyboard mode, panel off)                              RECEIVER
keyboard ---- evdev -------+
                           +-- tpkbd-send == SSH ==> sshd --> tpkbd-recv
TrackPoint --+             |   (root)                         (forced command)
touchpad ----+- libinput --+                                      |
                                                                  +--> ThinkPad remote keyboard
                                                                  +--> ThinkPad remote pointer
                                                                  +--> ThinkPad remote pinch
```

### Start

1. `systemctl isolate tpkbd-mode.target` on the sender stops the desktop and starts `tpkbd-forward.service`.
2. `tpkbd-screen off` waits 2 s for the desktop to close, switches to tty1, saves the brightness, sets the backlight to 0 and forces the internal display connector off, so the panel is completely powered down.
3. `tpkbd-send` opens an SSH connection with its own key and config from `/etc/tpkbd/`.
4. On the receiver, `authorized_keys` forces that key to run `tpkbd-recv` and nothing else.
5. `tpkbd-recv` creates three uinput devices, waits 0.5 s and prints `READY`.
6. Only then does `tpkbd-send` grab the sender's devices. Until that point input still goes to the sender, so nothing gets lost.

### Keyboard

Raw key events are read with python-evdev and sent as they are. The receiver applies its own layout and repeat rate. The kernel's autorepeat events (value 2) are dropped for that reason.

### TrackPoint and touchpad

These are processed on the sender by `libinput debug-events --grab`, and `tpkbd-send` parses its output. Only the result is sent: accelerated motion, button presses, scroll deltas and pinch scale.

The reason is timing. libinput computes acceleration from how fast events arrive. If raw events are sent over Wi-Fi and libinput runs on the receiver, packets arriving in bursts look like sudden fast movements. The TrackPoint gets choppy and the touchpad "teleports". Running libinput on the sender avoids that, and as a bonus the sender's libinput quirks apply (e.g. the T480's TrackPoint multiplier of 0.75).

On the receiver, motion goes through a plain relative pointer with acceleration turned off, multiplied by `SCALE`.

### Pinch

A gesture can't be injected directly. libinput only produces one when it sees two fingers on a touchpad. So the receiver has a touchpad device that is used for nothing but pinches. On pinch begin it puts two fingers down 20 mm apart, moves them according to the scale the sender reports, and lifts them on pinch end. The compositor sees a normal pinch and zooms wherever the cursor is.

Three- and four-finger swipes are not forwarded.

### Smoothing

Every message has the sender's timestamp. The receiver replays messages with their original spacing, `JITTER_MS` (15 ms) behind the fastest delivery in the last 2 s. Bursts shorter than that are smoothed out. This only affects smoothness, never speed.

### Stopping and retries

| Event | What happens | Panel |
|---|---|---|
| Ctrl + Ctrl + Esc | `tpkbd-send` exits with 42, the service doesn't restart | back on, previous brightness, tty1 login |
| Receiver unreachable at start | gives up after 15 s, systemd retries every 3 s | stays off |
| Connection lost | detected within ~10 s (SSH keepalive), retried | stays off |
| Shutdown | service gets SIGTERM | restored first (see [section 11](#11-sender-keyboard-mode-systemd)) |

The uinput devices on the receiver only exist while the connection is open, so no key can stay stuck.

### Why SSH

It gives encryption and authentication for free, and the receiver usually runs sshd already. `-tt` is used because ssh only enables `TCP_NODELAY` when a pty is allocated. Without it, small writes get delayed by tens of milliseconds. `-e none` disables the `~` escape character. On the receiver side, `stty -echo` stops the pty from echoing everything back.

---

## 2. Packages

```bash
# sender
sudo pacman -S --needed python-evdev openssh libinput
# receiver
sudo pacman -S --needed python-evdev openssh
sudo systemctl enable --now sshd
```

---

## 3. Receiver: uinput access

`tpkbd-recv` runs as your normal user and needs write access to `/dev/uinput`, which is root-only by default.

```bash
sudo groupadd --system uinput
sudo usermod -aG uinput your-user
sudo install -m 644 pc/tpkbd-uinput.conf /etc/modules-load.d/tpkbd-uinput.conf
sudo install -m 644 pc/60-tpkbd-uinput.rules /etc/udev/rules.d/60-tpkbd-uinput.rules
sudo udevadm control --reload
sudo modprobe uinput
sudo udevadm trigger --subsystem-match=misc --sysname-match=uinput
ls -l /dev/uinput
```

It should show `crw-rw---- 1 root uinput`. If it still says `root root`, reboot. A dedicated group is used instead of `input`, because members of `input` can read every keyboard on the system.

You don't need to log out: every SSH login picks up the new group.

---

## 4. Receiver: install the script

```bash
sudo install -m 755 pc/tpkbd-recv /usr/local/bin/tpkbd-recv
```

If you ever use an X11 session, also install the Xorg snippet. It turns off acceleration for the pointer device, which Wayland handles through KDE settings instead:

```bash
sudo install -m 644 pc/99-tpkbd.conf /etc/X11/xorg.conf.d/99-tpkbd.conf
```

---

## 5. Sender: find the input devices

```bash
grep Name= /proc/bus/input/devices
```

On a T480 the relevant ones are `AT Translated Set 2 keyboard`, `ThinkPad Extra Buttons` (Fn keys), `TPPS/2 IBM TrackPoint` and `Synaptics TM3276-022`. If yours differ, edit `KEYBOARD` and `POINTING` in `tpkbd-send`. Substrings are enough.

To check that the three buttons above the touchpad report through the TrackPoint:

```bash
grep -A4 TrackPoint /proc/bus/input/devices | grep Handlers   # e.g. event13
sudo evtest /dev/input/event13
```

Clicking should print `BTN_LEFT`, `BTN_MIDDLE` and `BTN_RIGHT`.

---

## 6. Sender: install the scripts

```bash
sudo install -m 755 thinkpad/tpkbd-send /usr/local/bin/tpkbd-send
sudo install -m 755 thinkpad/tpkbd-screen /usr/local/bin/tpkbd-screen
```

---

## 7. SSH

### Key (sender)

```bash
sudo install -d -m 700 /etc/tpkbd
sudo ssh-keygen -t ed25519 -N "" -C tpkbd -f /etc/tpkbd/id_ed25519
sudo ssh-keygen -lf /etc/tpkbd/id_ed25519.pub
```

The key has no passphrase because the service starts unattended. That's acceptable because it's only readable by root and is heavily restricted on the receiver.

### Config (sender)

```bash
sudo install -m 600 thinkpad/ssh_config.example /etc/tpkbd/ssh_config
sudo nano /etc/tpkbd/ssh_config    # set HostName and User
```

| Line | Purpose |
|---|---|
| `IdentityFile` + `IdentitiesOnly yes` | only ever use this key |
| `UserKnownHostsFile` | keep the receiver's host key separate from your own `~/.ssh` |
| `HostKeyAlias` | store the host key under a fixed name, not the IP. Useful if several OSes share the receiver's IP |
| `StrictHostKeyChecking yes` | refuse unknown or changed host keys |

### Host key (once)

On the receiver:

```bash
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

On the sender:

```bash
sudo ssh -F /etc/tpkbd/ssh_config -o StrictHostKeyChecking=accept-new -o BatchMode=yes tpkbd-pc true
sudo ssh-keygen -lF tpkbd-pc -f /etc/tpkbd/known_hosts
```

The two fingerprints must match. The first command ends with `Permission denied (publickey)` at this point, which is expected.

### Authorize the key (receiver)

Get `/etc/tpkbd/id_ed25519.pub` from the sender to the receiver: a USB stick, `scp`, or temporarily serving it with `python -m http.server` from a folder that contains only the `.pub` file. Check its fingerprint, then **append** it with the restrictions from `pc/authorized_keys.example`:

```bash
ssh-keygen -lf tpkbd.pub           # must match the sender's fingerprint
key=$(cat tpkbd.pub)
printf '\n# tpkbd\nfrom="192.168.1.0/24",restrict,pty,command="stty -echo; exec /usr/local/bin/tpkbd-recv" %s\n' "$key" >> ~/.ssh/authorized_keys
```

| Option | Effect |
|---|---|
| `from="192.168.1.0/24"` | only accepted from the local network (adjust to yours) |
| `restrict` | no forwarding, no pty, nothing |
| `pty` | re-allow a pty, needed for `-tt` |
| `command="..."` | always runs the receiver, whatever the client requests |

Use `>>`, not `>`, or any existing keys in that file are gone.

---

## 8. First test

On the sender, from a normal desktop session:

```bash
sudo tpkbd-send
```

It prints `connecting to the PC...`, then `CONNECTED after X.X s`. On the receiver:

```bash
grep 'ThinkPad remote' /proc/bus/input/devices
```

should list the keyboard, the pointer and the pinch device. Ctrl + Ctrl + Esc ends the test.

---

## 9. Receiver: KDE settings

While connected, so the devices exist:

- System Settings → Mouse → **ThinkPad remote pointer** → pointer acceleration **None**, speed at default. Motion is already accelerated on the sender, and accelerating it twice feels jumpy.
- System Settings → Touchpad → **ThinkPad remote pinch** → **tap-to-click off**, otherwise a tiny pinch can register as a two-finger tap (right click).

KDE stores these per device name and reapplies them on every reconnect.

---

## 10. Sender: Wi-Fi

In keyboard mode nobody is logged in, so the Wi-Fi password can't come from KWallet. Store it system-wide and turn off power saving, which otherwise causes lag spikes of 50-100 ms:

```bash
nmcli -t -f NAME,TYPE connection show | grep wireless
sudo nmcli connection modify "YOUR_SSID" \
    connection.permissions "" \
    connection.autoconnect yes \
    802-11-wireless-security.psk-flags 0 \
    802-11-wireless-security.psk 'YOUR_WIFI_PASSWORD' \
    802-11-wireless.powersave 2
sudo nmcli connection up "YOUR_SSID"
iw dev wlan0 get power_save        # Power save: off
```

---

## 11. Sender: keyboard mode (systemd)

```bash
sudo install -m 644 thinkpad/tpkbd-mode.target /etc/systemd/system/
sudo install -m 644 thinkpad/tpkbd-forward.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable tpkbd-forward.service
```

`tpkbd-mode.target` is `multi-user.target` (networking, ttys) without the graphical session, plus the service. `systemctl isolate` switches to it and stops everything else, including the display manager. The service is only wanted by this target, so normal boots never start it.

Service details:

| Line | Purpose |
|---|---|
| `After=... display-manager.service getty@tty1.service` | wait until the desktop has actually stopped, otherwise it turns the backlight back on while closing |
| `StartLimitIntervalSec=0` | never give up retrying |
| `Restart=always`, `RestartSec=3` | retry 3 s after any failure |
| `RestartPreventExitStatus=42` | Ctrl + Ctrl + Esc means stop for real |
| `ExecStopPost=... post` | `tpkbd-screen` checks `$EXIT_STATUS`, and only turns the panel back on for 42 (escape) or TERM/INT (shutdown) |

The panel is restored on shutdown because `systemd-backlight` saves the brightness when the system goes down. If it saved 0, the next boot would start almost black. Forcing the connector off isn't persistent, so a reboot always brings the panel back.

---

## 12. Daily use

| What | Where | How |
|---|---|---|
| Start keyboard mode | sender | `sudo systemctl isolate tpkbd-mode.target` (save your work, the desktop closes) |
| Stop | sender | hold both Ctrl, press Esc |
| Back to the desktop | sender, tty1 | log in, `sudo systemctl isolate graphical.target` |
| Shut down | sender | short press on the power button, works with the panel off |
| Logs | sender | `journalctl -u tpkbd-forward -b` |

The receiver must be booted into the OS where `tpkbd-recv` is installed. The devices work from the login screen onwards.

---

## 13. Tuning

| Setting | File | Default | Notes |
|---|---|---|---|
| `SCALE` | `tpkbd-recv` | `1.25` | receiver width in px / sender logical width. The T480 runs 1920x1080 at 125 % = 1536 logical, the receiver 1920 at 100 %. Check with `kscreen-doctor -o` on both |
| `JITTER_MS` | `tpkbd-recv` | `15` | more = smoother on bad Wi-Fi, but more delay |
| `HALF0` | `tpkbd-recv` | `400` | half the starting finger distance for pinches (40 units/mm) |
| `LIBINPUT_OPTS` | `tpkbd-send` | adaptive, speed 0, tap on, dwt off | same options as `libinput debug-events --help` |
| `KEYBOARD`, `POINTING` | `tpkbd-send` | T480 names | see [section 5](#5-sender-find-the-input-devices) |
| `READY_TIMEOUT` | `tpkbd-send` | `15` | seconds to wait for the receiver |

---

## 14. Protocol

Plain text, one message per line, sender to receiver. `ts` is the sender's time in microseconds.

| Line | Meaning |
|---|---|
| `k <type> <code> <value>` | raw key event |
| `k 0 0 <ts>` | end of a keyboard batch |
| `m <dx> <dy> <ts>` | accelerated motion |
| `b <code> <1\|0> <ts>` | button press/release (272, 273, 274) |
| `s <vert> <horiz> <ts>` | scroll, libinput units (15 = one wheel click) |
| `g b\|u\|e <value> <ts>` | pinch begin / update (scale) / end |

The only message the other way is `READY`.

---

## 15. Troubleshooting

| Symptom | Fix |
|---|---|
| `missing devices: keyboard=[] pointing=[]` | run it with `sudo`. If it still fails, the device names changed ([section 5](#5-sender-find-the-input-devices)) |
| `PC not reachable or receiver not ready` | receiver off or wrong OS. Test with `sudo ssh -F /etc/tpkbd/ssh_config tpkbd-pc`, which should just hang silently |
| `Permission denied (publickey)` | check the `authorized_keys` line, and that the sender is in the `from=` range |
| host key changed | verify it on the receiver, then `sudo ssh-keygen -R tpkbd-pc -f /etc/tpkbd/known_hosts` and accept it again |
| drops right after connecting | `/dev/uinput` permissions ([section 3](#3-receiver-uinput-access)) |
| keyboard fine, pointer and scroll barely move | libinput's output format probably changed after an update. Compare `sudo script -qc "libinput debug-events --device /dev/input/eventN" /dev/null \| cat -v` with the regexes in `tpkbd-send` |
| pointer jumpy | acceleration isn't off on the receiver ([section 9](#9-receiver-kde-settings)) |
| pointer too fast/slow | `SCALE` |
| stutter | Wi-Fi power saving, signal, or raise `JITTER_MS` |
| small pinch = right click | tap-to-click is on for the pinch device |
| panel doesn't turn off | `ls /sys/class/drm/card*-eDP-*/status` should show exactly one file |
| panel stays off after escape | press the power button, the forced-off state doesn't survive a reboot |
| works from the desktop but not in keyboard mode | Wi-Fi isn't available without a login ([section 10](#10-sender-wi-fi)) |

---

## 16. Security

- On the receiver, the key can only start `tpkbd-recv`, and only from the local network. Anyone holding it can still type into the receiver's session, so treat the sender as trusted, and remove the line from `authorized_keys` if the laptop gets lost.
- Members of the `uinput` group can create input devices.
- `StrictHostKeyChecking yes` means the sender won't talk to an unknown host.

---

## 17. Uninstall

Sender:

```bash
sudo systemctl disable tpkbd-forward.service
sudo rm /etc/systemd/system/tpkbd-forward.service /etc/systemd/system/tpkbd-mode.target
sudo systemctl daemon-reload
sudo rm /usr/local/bin/tpkbd-send /usr/local/bin/tpkbd-screen
sudo rm -r /etc/tpkbd
```

Receiver: remove the `# tpkbd` line and the key line from `~/.ssh/authorized_keys`, then:

```bash
sudo rm /usr/local/bin/tpkbd-recv /etc/modules-load.d/tpkbd-uinput.conf \
        /etc/udev/rules.d/60-tpkbd-uinput.rules /etc/X11/xorg.conf.d/99-tpkbd.conf
sudo gpasswd -d your-user uinput
```

---

## 18. Optional: GRUB entry

To boot straight into keyboard mode instead of switching from the desktop:

```bash
sudo awk "/^menuentry 'Arch Linux'/,/^}/" /boot/grub/grub.cfg > /tmp/tpkbd-entry
sed -i -e "1s/'Arch Linux'/'Arch (keyboard mode)'/" \
       -e "1s/gnulinux-simple-/tpkbd-mode-/" \
       -e '/^\s*linux\s/s/$/ systemd.unit=tpkbd-mode.target/' /tmp/tpkbd-entry
cat /tmp/tpkbd-entry                                  # check it
{ echo; cat /tmp/tpkbd-entry; } | sudo tee -a /etc/grub.d/40_custom > /dev/null
sudo grub-mkconfig -o /boot/grub/grub.cfg
```

Power usage ends up the same as with `isolate`. Booting directly is just a bit cleaner, since no desktop session ever runs.
