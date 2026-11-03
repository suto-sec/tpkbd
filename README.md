# tpkbd

Use a ThinkPad T480 as the keyboard, TrackPoint and touchpad for **another computer**.

The ThinkPad grabs its own input and sends it away; the other computer sees it as an ordinary keyboard and mouse. There are two generations, and two ways of connecting the newer one.

## Which one do I want?

| | **[v1](v1/)** | **[v2](v2/)** |
|---|---|---|
| How | The target runs a receiver; input arrives over SSH and is replayed through uinput | A Raspberry Pi plugged into the target *is* a USB keyboard and mouse |
| Target needs | A booted Linux, `tpkbd-recv`, an SSH server | **Nothing** |
| Link | SSH over the LAN | **Wired (UART)** or SSH over Wi-Fi, to the Pi |
| Works in BIOS, GRUB, installers, passphrase prompts | No | Yes, in principle (the real-BIOS check is still open) |
| Extra hardware | None | Raspberry Pi Zero 2 W, a 3.3 V USB-to-TTL adapter, 3 jumper wires |
| Pinch to zoom | Real pinch gesture | Real pinch gesture on Linux targets (virtual touchpad), Ctrl + scroll elsewhere |
| State | Finished, kept as is | Wired link works; see the [status](v2/README.md#status) |

Pick **v1** for a Linux PC you can already boot and don't want extra hardware for. Pick **v2** when the target has no OS yet, isn't yours to install software on, or isn't Linux.

## v2 links at a glance

- **Wired (UART)**: the real setup. ThinkPad -> USB-to-TTL adapter -> 3 wires -> Pi GPIO. No network in the typing path. [v2/docs/wired.md](v2/docs/wired.md)
- **Wireless (SSH over Wi-Fi)**: temporary scaffolding, and how you manage the Pi. [v2/docs/wifi.md](v2/docs/wifi.md)

## Repository map

```
README.md           this page
v1/                 software-only version
  pc/                 the receiver for the target PC (v1 only)
  thinkpad/           the sender, SHARED: v1 and v2 both use it
  docs/, tests/
v2/                 the Raspberry Pi version
  pi/                 everything that runs on the Pi
  docs/               pi-setup, wired, wifi, boot-mode, features
  tests/
.github/workflows/  CI: one job per generation
```

The sender lives in `v1/thinkpad/` because v1 came first. Its `link` setting (`ssh` or `serial`) is what selects v1-style SSH or the v2 wire.

## Start

- v1: [v1/README.md](v1/README.md) and [v1/docs/setup.md](v1/docs/setup.md).
- v2: [v2/README.md](v2/README.md), then [v2/docs/pi-setup.md](v2/docs/pi-setup.md).

## License

[MIT](LICENSE).
