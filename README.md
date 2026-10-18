# tpkbd

Use a ThinkPad T480 as a keyboard, TrackPoint and touchpad for another computer.

**v2 (repo root)** is in progress. A Raspberry Pi Zero 2 W plugged into the target computer acts as a real USB keyboard and mouse, and the ThinkPad feeds it over a wired link. Because the target sees ordinary USB hardware, it works in the BIOS/UEFI, in bootloaders such as GRUB, in OS installers and on any operating system, with nothing installed on the target. So far there is the USB gadget and a self-test (see [docs/gadget.md](docs/gadget.md)); the link from the ThinkPad's keyboard to the Pi is next.

**[v1](v1/)** runs over SSH and replays the input on the target through uinput. It needs a booted Linux with the receiver installed, but it works today and has tests and a setup guide. It is kept as is; see [Why v2](#why-v2).

---

## Why v2

v1 only works once the PC has booted into an OS that runs the receiver. BIOS setup, bootloader menus, disk-encryption passphrase prompts and installers still need a real keyboard, and every PC needs the receiver, an SSH server and uinput permissions.

v2 moves that work onto a small USB device, so the target needs no software at all. The trade-offs: an extra device to power and set up, a keyboard limited to the boot-protocol 6-key rollover while in firmware, and pinch-to-zoom needing a different approach (v1 fakes a touchpad on the PC, which a plain USB HID gadget can't do portably).

## License

[MIT](LICENSE).
