# The Wi-Fi link (SSH): temporary scaffolding

The Pi can also be fed over SSH on Wi-Fi. It uses the same sender and the same line protocol as the wire, so it is the quickest way to try the Pi without buying the adapter. **It is not the intended final link:** it needs a network, the Pi's address changes unless you reserve it, and Wi-Fi adds jitter. Use the [wired link](wired.md) for daily use.

Do [pi-setup.md](pi-setup.md) first. Placeholders: `<user>` and `<pi-ip>` as there.

```
ThinkPad --Wi-Fi/SSH--> Pi (sshd runs tpkbd-recv per login) --USB gadget--> target PC
 tpkbd-send
```

## Setup

1. **Pi:** copy the current `v2/pi/` folder over and run `sudo ./tpkbd-pi/install.sh` again ([pi-setup.md](pi-setup.md) section 2). An older install doesn't have `tpkbd-recv`.
2. **ThinkPad:** run `sudo thinkpad/install.sh` from `v1/` if the sender isn't installed yet. If `/etc/tpkbd/ssh_config` already exists the installer keeps it and doesn't ask for an address. Edit it with sudo and change only these two lines:
   ```
   HostName <the Pi's IP>
   User <the Pi's user name>
   ```
   Leave the `Host` line (the tools look it up by that name) and everything else alone. Use the IP, not a host name. The sender talks to **one** host, so v1 to an old PC stops working until you change these back.
3. **ThinkPad, with the Pi on:** `sudo tpkbd-pair`. It shows the Pi's host key fingerprint. Compare it with `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` on the Pi, answer `y`, and it prints one line.
4. **Pi:** append that line to `~/.ssh/authorized_keys` with `>>`, never `>` (that would wipe your own key). `authorized_keys.example` shows its shape. It runs only `tpkbd-recv`, never a shell.
5. **ThinkPad:** make sure `/etc/tpkbd/tpkbd.conf` has no `link = serial` line (or says `link = ssh`), plug the Pi into the target and run `sudo tpkbd-send`.

**Expected:** `CONNECTED after …`, and the ThinkPad's keyboard and TrackPoint drive the target. Left Ctrl + Right Ctrl + Esc stops it.

## Notes

- In keyboard mode nobody is logged in, so Wi-Fi must be available system-wide, with power saving off ([v1/docs/setup.md](../../v1/docs/setup.md#10-sender-wi-fi)).
- Pointer speed is `scale` in `~/.config/tpkbd/recv.conf` on the Pi (`recv.conf.example`).
- A DHCP reservation for the Pi in your router stops its address from changing.
- `Permission denied (publickey)` when you SSH to the Pi yourself: wrong user or address, or the Pi is still booting. `ssh -v <user>@<pi-ip> 2>&1 | tail` shows which address and keys it tried.
