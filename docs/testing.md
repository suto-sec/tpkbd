# Checking that it works

Two kinds of checks:

- **Automated**: no hardware needed. They cover the logic: parsing, the protocol, the hotkey state machine, the receiver's safety net, the screen script (against a fake `/sys`).
- **On the machines**: things only the real ThinkPad and PC can show: the devices, systemd, the panel, a real network.

```bash
python3 -m unittest discover -s tests -t .        # every automated check
bash -n pc/*.sh thinkpad/*.sh thinkpad/tpkbd-screen
python3 -m py_compile pc/tpkbd-recv thinkpad/tpkbd-send thinkpad/tpkbd-pair
shellcheck pc/*.sh thinkpad/*.sh thinkpad/tpkbd-screen    # if installed; CI runs it too
```

On the ThinkPad, read the log of whatever you are testing with:

```bash
journalctl -u tpkbd-forward -b -f       # keyboard mode
journalctl -u tpkbd-soft -f             # soft mode
```

Or run `sudo tpkbd-send` (`sudo tpkbd-send --soft`) in a terminal. Stop the services first, the two can't share the devices.

Unless it says otherwise, "the ThinkPad" is the sender and "the PC" the receiver.

---

## 1. The receiver's errors reach the sender's log

*Automated:* `tests.test_send.LinkReady`.

*On the machines:* make `/dev/uinput` unusable on the PC, then try to connect.

```bash
# PC
sudo chmod 600 /dev/uinput
# ThinkPad
sudo tpkbd-send
```

You should see `tpkbd: pc: ...PermissionError...` followed by `PC not reachable or receiver not ready (will retry)`. Before this change only the second line appeared. Put it back on the PC:

```bash
sudo udevadm trigger --subsystem-match=misc --sysname-match=uinput
```

## 2. Protocol version check

*Automated:* `LinkReady.test_old_receiver_is_named`, `test_other_version`.

*On the machines:* temporarily put an old-style receiver on the PC.

```bash
# PC
sudo cp /usr/local/bin/tpkbd-recv /usr/local/bin/tpkbd-recv.real
printf '#!/bin/sh\necho READY\nsleep 30\n' | sudo tee /usr/local/bin/tpkbd-recv >/dev/null
# ThinkPad
sudo tpkbd-send        # tpkbd: receiver speaks protocol 1 ... re-run pc/install.sh
# PC, put it back
sudo mv /usr/local/bin/tpkbd-recv.real /usr/local/bin/tpkbd-recv
```

## 3. No stuck keys when the link dies

*Automated:* `tests.test_recv.Serve` (silence, heartbeats, EOF), `tests.test_send.KeyboardMode.test_escape_chord_exits_42_and_releases_on_the_pc`, `tests.test_integration`.

*On the machines:* freeze the sender while a key is held. This is what a dead Wi-Fi link looks like to the receiver, without the cleanup a clean disconnect does.

1. Start keyboard mode or `sudo tpkbd-send`. Open a text field on the PC.
2. From the PC, schedule the freeze (`-t` so sudo can ask for a password, and systemd signals only the sender, not the ssh and libinput processes it started):
   `ssh -t <thinkpad> 'sleep 8; sudo systemctl kill --kill-whom=main --signal=SIGSTOP tpkbd-forward'`
   (for a manual `sudo tpkbd-send` run: `sudo pkill -STOP -f '^python3 /usr/local/bin/tpkbd-send'`; the `^` keeps it from matching the shell running the command)
3. Hold down `a` on the ThinkPad.

**Expected:** `aaaa...` appears on the PC for about 8 s, then stops within about 3 s of the freeze, although the key is still down. Without the heartbeat it would repeat until you restarted something.

4. About 30 s after the freeze the receiver exits: `grep 'ThinkPad remote' /proc/bus/input/devices` on the PC prints nothing and `pgrep -a tpkbd-recv` is empty.
5. Resume it: `ssh -t <thinkpad> sudo systemctl kill --kill-whom=main --signal=SIGCONT tpkbd-forward` (or `pkill -CONT` with the same anchored pattern). The sender notices the closed connection and reconnects.

Also try the real thing once: hold a key and turn Wi-Fi off (`nmcli radio wifi off` from another login, or pull the cable). Same result.

**Release on exit:** press Ctrl + Ctrl + Esc. The PC must not behave as if Ctrl is still down (click, type a letter).

**Release on a service stop:** hold `a` on the ThinkPad so the PC repeats it, and have a stop scheduled from the PC: `ssh -t <thinkpad> 'sleep 8; sudo systemctl stop tpkbd-forward'`. The PC must stop typing the moment the service stops, not 3 s later. The unit uses `KillMode=mixed`, so only the sender gets SIGTERM and can release everything over ssh before it closes.

## 4. The panel goes off only once the PC has answered

*Automated:* `tests.test_screen` (the script against a fake sysfs).

*On the machines:*

1. Switch the PC off. On the ThinkPad: `sudo systemctl isolate tpkbd-mode.target`.
   **Expected:** the desktop closes, a login prompt on tty1 stays visible, and the log repeats `PC not reachable ... (will retry)`. Before: the panel went dark immediately.
2. Still without the PC: note the brightness, then `sudo systemctl isolate graphical.target`. **Expected:** the brightness is exactly what it was, not maxed out (nothing was turned off, so nothing is "restored"). Then `sudo systemctl isolate tpkbd-mode.target` again.
3. Switch the PC on. **Expected:** once the receiver answers, the panel goes off (after about 2 s).
4. Give-up timer. Shorten it, then take the PC away: `sudo systemctl edit tpkbd-forward` and add `[Service]` / `Environment=TPKBD_SCREEN_GIVEUP=30`. With the panel off, power the PC off. **Expected:** after about 30 s plus a retry the panel comes back on with the previous brightness. Remove the override afterwards.

## 5. Reconnecting is fast, brightness is saved per device

*Automated:* `tests.test_screen`.

*On the machines:*

```bash
journalctl -u tpkbd-forward -b -o short-precise | tail -30   # note the timestamps
```

1. While in keyboard mode, `sudo systemctl restart sshd` on the PC. **Expected:** `connection lost`, then `CONNECTED` a few seconds later. The gap used to include a fixed 2 s wait and a vt switch; now it is the 3 s restart delay plus the connect time.
2. While the panel is off: `ls /run/tpkbd-brightness.*`. **Expected:** one file per directory in `/sys/class/backlight/`, each holding that device's own old value.
3. Ctrl + Ctrl + Esc. **Expected:** the brightness is what it was before. Try again after setting the brightness to 0 first (`echo 0 | sudo tee /sys/class/backlight/*/brightness`): the panel must come back at full brightness, not black.

## 6. A changed libinput format is noticed

*Automated:* `tests.test_send.ParseLibinput`, `LibinputPipe.test_format_change_is_logged_not_silent`. **Note:** the fixture lines are written to look like `libinput debug-events` output; they were not captured from your machine.

*On the machines:* make sure your real libinput matches. Run `sudo tpkbd-send`, then move the pointer, click, scroll with two fingers, pinch.

**Expected:** no `unparsed libinput line` messages. If one shows up, the line it prints is the new format: update the regexes at the top of `thinkpad/tpkbd-send` and add that line to `tests/test_send.py`. To see the raw output:

```bash
grep -A4 TrackPoint /proc/bus/input/devices | grep Handlers
sudo script -qc "libinput debug-events --device /dev/input/eventN" /dev/null | cat -v
```

## 7. Settings are in config files

*Automated:* `Config` in `tests.test_send` and `tests.test_recv`.

*On the machines:*

- PC: set `scale = 2` in `~/.config/tpkbd/recv.conf` and reconnect. **Expected:** the pointer is clearly faster. Set it back.
- ThinkPad: in `/etc/tpkbd/tpkbd.conf` set `libinput_opts = --set-profile=flat --set-speed=0 --enable-tap --disable-dwt` and restart the service. **Expected:** the pointer feels linear.
- Updates keep your settings: `sudo thinkpad/install.sh` and `sudo pc/install.sh` again. **Expected:** both files unchanged.
- A bad name is reported: `toggle_keys = KEY_NOPE`, then `sudo tpkbd-send --soft` prints `bad config ...: unknown key name 'KEY_NOPE'`.

## 8. Fn+4 can't suspend the PC

*Automated:* `KeyboardMode.test_blocked_keys_stay_local`.

*On the machines:* the real test would suspend your PC, so test with a harmless key. Set `block_keys = KEY_A` in `tpkbd.conf`, restart, and type `a` in a text field on the PC: nothing appears, other letters do. Put the default back. Then Fn+4 is safe to try.

## 9. Pairing helper

*Automated:* `tests.test_pair` (the parsing, the subnet detection, the line it prints).

*On the machines:* with the PC on:

```bash
sudo tpkbd-pair
```

**Expected:**
1. The fingerprint it shows equals `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` on the PC.
2. Answering `n` aborts and leaves `/etc/tpkbd/known_hosts` unchanged.
3. After `y`, `sudo cat /etc/tpkbd/known_hosts` has a `tpkbd-pc ssh-ed25519 ...` line owned by `tpkbd`.
4. The `from="..."` in the printed line is your laptop's real network (compare with `ip -4 -o addr`).
5. After appending it on the PC, `sudo -u tpkbd ssh -F /etc/tpkbd/ssh_config tpkbd-pc` hangs silently (that is the receiver waiting), no password prompt, no host key question.

## 10. Install and uninstall scripts

*Automated:* `bash -n` and shellcheck only.

*On the machines (best on a spare install):*

- `pc/install.sh` run as plain root (`sudo -i`) refuses. As your user via sudo it asks before enabling sshd (answer `n` and check `systemctl is-enabled sshd` didn't change).
- `thinkpad/install.sh` with `a/b` as the user name aborts with "unexpected characters".
- After install: `id tpkbd`, `ls -ld /etc/tpkbd` (owner `tpkbd`, mode 700).
- `sudo thinkpad/uninstall.sh`: `systemctl list-unit-files 'tpkbd*'` is empty, `ls /usr/local/bin/tpkbd*` finds nothing, and if the panel was off it is on again. Answering `y` removes `/etc/tpkbd` and the user.
- `sudo pc/uninstall.sh`: `grep tpkbd ~/.ssh/authorized_keys` finds nothing, `~/.ssh/authorized_keys.tpkbd-backup` exists, `/usr/local/bin/tpkbd-recv` is gone.

## 11. The sender runs without root, in a sandbox

*Automated:* none (needs systemd).

*On the ThinkPad:* with the service installed.

```bash
systemd-analyze verify /etc/systemd/system/tpkbd-forward.service /etc/systemd/system/tpkbd-soft.service
sudo systemctl isolate tpkbd-mode.target      # or: sudo systemctl start tpkbd-soft
ps -o user=,pid=,cmd= -C python3 | grep tpkbd-send     # user is tpkbd, not root
systemd-analyze security tpkbd-forward        # exposure score; lower is better
journalctl -u tpkbd-forward -b | grep -i 'denied\|permission'    # should print nothing
```

**Expected:** it connects exactly as before, input works, the pinch and scrolling work. If it fails with a permission error, that is the likely cause of an issue with the sandbox: `sudo systemctl edit tpkbd-forward`, add `[Service]` / `User=root`, restart. If that works, one of the sandbox lines is too strict for your system; the journal says which path.

## 12. Long pinches keep zooming

*Automated:* `tests.test_recv.Pinch.test_long_pinch_reseats_instead_of_stalling`.

*On the machines:* on the PC open something zoomable (a PDF, a browser page) and do one long, slow pinch-out on the ThinkPad's touchpad. **Expected:** the zoom keeps growing for the whole gesture instead of freezing at some size. To see the re-seat, run `sudo libinput debug-events | grep GESTURE_PINCH` on the PC: a `GESTURE_PINCH_END` followed by a new `GESTURE_PINCH_BEGIN` in the middle of the gesture.

## 13. Hotkey toggle (soft mode)

*Automated:* `tests.test_send.SoftToggle`, `Heartbeat`.

*On the machines:*

```bash
sudo systemctl start tpkbd-soft
cat /run/tpkbd/state                  # local
```

1. **Local by default.** Type on the ThinkPad: it works locally. Nothing appears on the PC.
2. **To the PC.** Hold Ctrl + Ctrl, press Space, release everything. The log says `hotkey: switching to remote once all keys are released`, then `input is now remote`. `cat /run/tpkbd/state` prints `remote`. Typing, TrackPoint and touchpad now act on the PC and the laptop's desktop gets nothing.
3. **Back.** Same chord. The laptop reacts again; the state is `local`.
4. **Nothing sticks.** Do 2 and 3 several times. Afterwards type normally on both machines: no stuck Ctrl, Shift or Space on either.
5. **Held key.** While the PC has the input, hold `a` (the PC repeats it), then add Ctrl + Ctrl + Space. The PC must stop repeating `a` at once; control moves to the laptop once you let go of everything.
6. **Held key the other way.** On the laptop hold Shift, press the chord, keep holding. Release everything: the switch happens only then, and Shift isn't stuck on the PC.
7. **Link loss.** While the PC has the input: `sudo systemctl stop sshd` on the PC. Within about 10 s the laptop takes the input back and `journalctl -u tpkbd-soft` shows `connection lost`; the unit restarts and the state is `local` again.
8. **Modes exclude each other.** `sudo systemctl start tpkbd-forward` stops `tpkbd-soft` (and the reverse).
9. **Busy device.** If another program has grabbed the keyboard, the switch fails with `switching to remote failed` and the input stays on the laptop.
10. **Idle laptop.** While the PC has the input, the laptop's desktop receives no events, so its idle timer runs: the screen locks, and on battery it may suspend, which ends the link. Leave the PC in control for longer than the laptop's lock/suspend timeouts (System Settings → Power Management) and see what happens. If it bothers you, raise those timeouts or keep the laptop on AC; see the limitation in the README.
