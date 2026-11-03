# Hardening the Pi

Once the wired link works, the Pi does not need Bluetooth, password logins or (eventually) Wi-Fi. `pi/harden.sh` switches them off. It is optional, and each step can be undone.

## Order

Do these in order, and stop at any point:

1. Everything works: typing, media keys, pinch, and `tpkbd-hid test-scroll` ([pi-setup.md](pi-setup.md)). Settle `recv.conf` (`scroll`, `led`, `scale`).
2. `sudo ./harden.sh`: Bluetooth off and key-only SSH.
3. `sudo ./harden.sh --wifi-off`: last, on its own.
4. Read-only root filesystem ([below](#read-only-root-filesystem)): the very last step, because it discards later edits.

## What `harden.sh` does

| Command | Effect |
|---|---|
| `sudo ./harden.sh` | `--bluetooth` and `--ssh` together |
| `--bluetooth` | Adds `dtoverlay=disable-bt` to `config.txt` and disables `hciuart`. Takes effect at the next reboot. `/dev/serial0` then points at the full UART, which is what the wire uses |
| `--ssh` | Writes `/etc/ssh/sshd_config.d/10-tpkbd.conf` (no password or keyboard-interactive logins, keys only) and reloads sshd |
| `--wifi-off` | Adds `dtoverlay=disable-wifi`. Asks you to type `yes`, and refuses to be combined with other flags |
| `--undo` | Removes the drop-in and our `config.txt` lines |

Safety nets:

- `config.txt` is copied once to `config.txt.tpkbd-orig` before the first edit. Our lines carry a `# tpkbd harden.sh` comment above them, which is how `--undo` finds them; a line you added yourself is never removed.
- `--ssh` refuses unless your `~/.ssh/authorized_keys` has a key. Copy one first: `ssh-copy-id <user>@<pi-ip>` from the ThinkPad.
- The new SSH settings are checked with `sshd -t` and `sshd -T`. If sshd rejects them, or another setting still allows passwords, the script puts the old state back.
- After `--ssh`, keep your current session open and try a new `ssh` login with your key before closing it.

## If you lose access

- **Key-only SSH locked you out:** edit the SD card's root partition on another computer and delete `/etc/ssh/sshd_config.d/10-tpkbd.conf`. Or use the wire: the receiver does not need SSH.
- **Wi-Fi off and you want it back:** put the SD card in another computer and delete the `dtoverlay=disable-wifi` line (and the comment above it) in `config.txt` on the boot partition.

## Read-only root filesystem

The Pi is powered by the target PC's USB port, so every PC shutdown cuts its power without warning. A power cut while the SD card is being written can corrupt it.

In `sudo raspi-config`: Performance Options, Overlay File System. The root filesystem becomes read-only, and anything written lives in RAM and is discarded at reboot. Nothing in tpkbd needs to persist (the gadget is recreated at each boot, the logs are in RAM anyway).

The catch is that your edits are discarded too: `recv.conf`, hardening, any update. To change something later: turn the overlay off in `raspi-config`, reboot, edit, turn it on, reboot. That is why it is the last step. The boot partition can be made read-only separately in the same menu; leave it writable if you may want to run `harden.sh --undo` or edit `config.txt` from the Pi.
