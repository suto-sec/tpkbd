# The wired link (UART)

**This is the real v2 link.** A 3.3 V USB-to-TTL adapter on the ThinkPad talks to the Pi's GPIO serial port over three wires. No network is involved in the typing path. Wi-Fi/SSH stays only as your way to manage the Pi, and can be switched off for good later.

```
ThinkPad --USB--> [CP2102 adapter] --3 wires--> Pi GPIO UART --USB gadget--> target PC
 tpkbd-send                                    tpkbd-recv (service)
```

Do [pi-setup.md](pi-setup.md) first. Placeholders: `<user>` and `<pi-ip>` as there.

## Parts

- A **3.3 V** USB-to-TTL serial adapter: CP2102/CP2104, CH340 or FTDI. Never 5 V logic. The red CP2102 module with a USB-A plug and a 5-pin header is fine.
- Three **female-to-female Dupont jumper wires** (2.54 mm). Some adapters include them.

## Wiring

Everything unplugged. Hold the Pi with the **SD card slot on the left** and the header along the top. The header's top row is pins 2, 4, 6, 8, 10, ... counted from the left. **Pins 2 and 4 are 5 V: leave them empty.** Pins 6, 8 and 10 are the three wires. On the adapter, read the labels printed next to its pins.

| Adapter pin | Pi pin |
|---|---|
| GND | 6 (GND) |
| TXD | 10 (GPIO15, the Pi's RXD) |
| RXD | 8 (GPIO14, the Pi's TXD) |

TX and RX are crossed on purpose. **Never connect the adapter's 5 V or 3V3 pin.** Swapping the TX and RX wires by mistake just means nothing works; swap them back.

## Pi setup (over SSH)

1. `sudo nano /boot/firmware/config.txt` and add `enable_uart=1` under `[all]`.
2. `sudo nano /boot/firmware/cmdline.txt` and delete `console=serial0,115200` (or `console=ttyAMA0,115200`) so the login console stops using the port. It stays one line.
3. `sudo systemctl disable --now serial-getty@ttyS0.service` (and the same for `serial-getty@ttyAMA0.service` if it exists).
4. Copy the current `v2/pi/` folder over and run `sudo ./tpkbd-pi/install.sh` again ([pi-setup.md](pi-setup.md) section 2). It installs `tpkbd-recv.service` and a `tpkbd` user for it.
5. `sudo reboot`, then `ls -l /dev/serial0` (a link to `ttyS0` or `ttyAMA0`) and `systemctl status tpkbd-recv`.

**Expected:** `active (running)`, and `listening on /dev/serial0 at 115200 baud` in `journalctl -u tpkbd-recv`.

## ThinkPad setup

1. Plug the adapter in: `ls /dev/ttyUSB*` shows `/dev/ttyUSB0`. Add yourself to the serial group, log out and in: `sudo usermod -aG uucp $USER` (Arch; `dialout` on Debian-based systems).
2. Optional loopback test of the adapter alone: put one jumper between its TXD and RXD pins and run
   ```bash
   python3 -c "
   import os,tty
   fd=os.open('/dev/ttyUSB0',os.O_RDWR|os.O_NOCTTY); tty.setraw(fd)
   os.write(fd,b'ping'); print(os.read(fd,4))"
   ```
   It prints `b'ping'`. Remove that jumper afterwards.
3. From `v1/` in the repo: `sudo thinkpad/install.sh --serial`. It skips the SSH key and address, adds the `tpkbd` user to the serial group and sets `link = serial` under the existing `[sender]` line of `/etc/tpkbd/tpkbd.conf`. (The ThinkPad side is shared by v1 and v2, which is why it lives in `v1/thinkpad/`.)
4. The port defaults to `/dev/ttyUSB0`. To change it, add `serial_port = ...` under the same `[sender]` line (never a second `[sender]` header). `ls /dev/serial/by-id/` gives a name that survives the adapter landing on another port.
5. Plug the Pi's USB port into the target and run:
   ```bash
   sudo tpkbd-send
   ```
   **Expected:** `CONNECTED after 0.x s`, and the ThinkPad's keyboard and TrackPoint drive the target. Left Ctrl + Right Ctrl + Esc stops it.

Then use it for real: [boot-mode.md](boot-mode.md).

## How it works

- `tpkbd-recv.service` runs on the Pi at every boot, listening on `/dev/serial0`.
- `tpkbd-send` says `hello` until the Pi answers `READY 2`, then grabs the ThinkPad's input. It sends a heartbeat every second; the Pi answers `ok`.
- If nothing comes back for 5 s the sender treats the link as dead and systemd retries. If the Pi hears nothing for 3 s it releases every key and button.
- The line protocol is the v1 one (`k`/`m`/`b`/`s`/`g`/`h`). The baud rate is 115200 on both sides; change `baud` in `tpkbd.conf` and `--baud` in the unit together if the pointer lags.

## If it doesn't connect

| Symptom | Check |
|---|---|
| `PC not reachable or receiver not ready` | The Pi isn't answering: `systemctl status tpkbd-recv` on the Pi, is `/dev/serial0` the port in the unit, is the serial console really off (steps 2 and 3)? |
| `cannot open /dev/ttyUSB0` | Wrong name (`dmesg \| tail` after plugging in), or you aren't in the serial group (log in again). |
| Nothing at all | Swap the TX and RX wires; check GND is on pin 6; run the loopback test. |
| Connects, then drops | Loose jumper wire; a long or poor USB extension to the adapter. |

## Security

The wire is not authenticated: anything that can write to the Pi's serial port can type on the target. Keep it short and private. For the final wired-only product also consider `dtoverlay=disable-wifi` and `dtoverlay=disable-bt` on the Pi (after you no longer need SSH over Wi-Fi) and key-only SSH.
