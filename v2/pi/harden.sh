#!/bin/sh
# Shrink the Pi's attack surface once the wired link works. Run with sudo:
#
#   sudo ./harden.sh               Bluetooth off and key-only SSH (the safe pair)
#   sudo ./harden.sh --bluetooth   only Bluetooth off
#   sudo ./harden.sh --ssh         only key-only SSH
#   sudo ./harden.sh --wifi-off    Wi-Fi off. Alone, and last: it cuts SSH over Wi-Fi
#   sudo ./harden.sh --undo        put all of it back
#
# Bluetooth and Wi-Fi are switched off with dtoverlay lines in config.txt, so they take
# effect at the next reboot. Details and the order to do things in: v2/docs/hardening.md
set -eu

# overrides, for the tests
boot_config=${TPKBD_BOOT_CONFIG:-}
sshd_dir=${TPKBD_SSHD_DIR:-/etc/ssh/sshd_config.d}
auth_keys=${TPKBD_AUTH_KEYS:-}
sshd=${TPKBD_SSHD:-sshd}
systemctl=${TPKBD_SYSTEMCTL:-systemctl}

dropin="$sshd_dir/10-tpkbd.conf"
tag="# tpkbd harden.sh"

do_bt=0 do_ssh=0 do_wifi=0 do_undo=0
for arg in "$@"; do
    case $arg in
        --bluetooth) do_bt=1 ;;
        --ssh) do_ssh=1 ;;
        --wifi-off) do_wifi=1 ;;
        --undo) do_undo=1 ;;
        -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
        *) echo "unknown option: $arg (see $0 --help)" >&2; exit 2 ;;
    esac
done
if [ $((do_bt + do_ssh + do_wifi + do_undo)) -eq 0 ]; then
    do_bt=1 do_ssh=1
fi
if [ "$do_wifi" -eq 1 ] && [ $((do_bt + do_ssh + do_undo)) -gt 0 ]; then
    echo "--wifi-off goes on its own, as the very last step: it cuts SSH over Wi-Fi." >&2
    exit 2
fi
if [ "$do_undo" -eq 1 ] && [ $((do_bt + do_ssh)) -gt 0 ]; then
    echo "--undo goes on its own." >&2
    exit 2
fi

[ -n "${TPKBD_SKIP_ROOT_CHECK:-}" ] || [ "$(id -u)" -eq 0 ] || { echo "run with sudo: sudo $0" >&2; exit 1; }

if [ -z "$boot_config" ]; then
    boot_config=/boot/firmware/config.txt
    [ -f "$boot_config" ] || boot_config=/boot/config.txt
fi
[ -f "$boot_config" ] || { echo "cannot find config.txt (looked in /boot/firmware and /boot)" >&2; exit 1; }

backup_config() {
    # once, so the original is never overwritten by a later run
    [ -f "$boot_config.tpkbd-orig" ] || cp -p "$boot_config" "$boot_config.tpkbd-orig"
}

add_overlay() {     # $1 = line, $2 = what it does
    if grep -qxF "$1" "$boot_config"; then
        echo "config.txt already has $1"
        return
    fi
    backup_config
    # a line after a filter like [pi4] would only apply to that board: make sure it is under [all]
    last=$(grep -E '^\[.*\]$' "$boot_config" | tail -n 1 || true)
    {
        [ -z "$last" ] || [ "$last" = "[all]" ] || echo "[all]"
        echo "$tag: $2"
        echo "$1"
    } >>"$boot_config"
    echo "config.txt: added $1 ($2)"
}

remove_overlays() {
    grep -q "^$tag" "$boot_config" || { echo "config.txt: nothing of ours to remove"; return; }
    backup_config
    tmp=$(mktemp)
    # drop each of our comment lines and the line right after it
    awk -v tag="$tag" 'skip { skip = 0; next } index($0, tag) == 1 { skip = 1; next } { print }' \
        "$boot_config" >"$tmp"
    cat "$tmp" >"$boot_config"
    rm -f "$tmp"
    echo "config.txt: removed our overlay lines"
}

reload_sshd() {
    "$systemctl" reload ssh 2>/dev/null || "$systemctl" reload sshd 2>/dev/null \
        || echo "could not reload sshd; the change applies after a reboot" >&2
}

harden_ssh() {
    if [ -z "$auth_keys" ]; then
        user=${SUDO_USER:-}
        if [ -z "$user" ] || [ "$user" = root ]; then
            echo "run it as sudo from your login user, so I can find your authorized_keys" >&2
            exit 1
        fi
        auth_keys="$(getent passwd "$user" | cut -d: -f6)/.ssh/authorized_keys"
    fi
    # a plain key line starts with the key type; a line starting with options (command="..."
    # forced-command lines, like authorized_keys.example) gives no interactive login
    if ! grep -qE '^[[:space:]]*(ssh-|ecdsa-|sk-)' "$auth_keys" 2>/dev/null; then
        echo "refusing: $auth_keys has no ordinary key, so key-only SSH would lock you out." >&2
        echo "from the ThinkPad: ssh-copy-id <user>@<pi-ip>   then run this again." >&2
        exit 1
    fi
    install -d -m 755 "$sshd_dir"
    old=
    if [ -f "$dropin" ]; then old=$(cat "$dropin"); fi
    cat >"$dropin" <<'EOF'
# written by tpkbd harden.sh; remove with: sudo ./harden.sh --undo
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
EOF
    chmod 644 "$dropin"
    rollback() {
        if [ -n "$old" ]; then printf '%s\n' "$old" >"$dropin"; else rm -f "$dropin"; fi
    }
    if ! "$sshd" -t; then
        rollback
        echo "sshd rejected the new settings, so I put things back." >&2
        exit 1
    fi
    # the first setting sshd sees wins, so another file could still allow passwords: check
    if ! "$sshd" -T | grep -qi '^passwordauthentication no$'; then
        rollback
        echo "another sshd setting overrides ours (look in /etc/ssh/sshd_config and $sshd_dir); put things back." >&2
        exit 1
    fi
    reload_sshd
    echo "ssh: password logins are off ($dropin)"
    echo "     keep this session open and try a NEW ssh login with your key before you close it."
}

undo_ssh() {
    if [ -f "$dropin" ]; then
        rm -f "$dropin"
        reload_sshd
        echo "ssh: removed $dropin, password logins are back to the system default"
    else
        echo "ssh: nothing of ours to remove"
    fi
}

if [ "$do_undo" -eq 1 ]; then
    undo_ssh
    remove_overlays
    echo "Reboot to bring Bluetooth and Wi-Fi back."
    exit 0
fi

if [ "$do_wifi" -eq 1 ]; then
    cat <<'EOF'
This turns Wi-Fi off for good (after a reboot). Afterwards the Pi can only be reached
over the wired link, and SSH over Wi-Fi stops working. Do it only when:
  - the wired link types correctly on the target, and
  - everything you want to tune (recv.conf, scroll, led) is settled.
To get Wi-Fi back later: put the SD card in another computer and delete the
"dtoverlay=disable-wifi" line (and the comment line above it) in config.txt on the boot partition.
EOF
    printf 'Type yes to turn Wi-Fi off: '
    read -r answer || answer=
    [ "$answer" = yes ] || { echo "not changed."; exit 1; }
    add_overlay dtoverlay=disable-wifi "Wi-Fi off, wired link only"
    echo "Reboot for it to apply."
    exit 0
fi

[ "$do_bt" -eq 0 ] || {
    add_overlay dtoverlay=disable-bt "Bluetooth off"
    "$systemctl" disable hciuart.service >/dev/null 2>&1 || true
    echo "Reboot for Bluetooth to go off. /dev/serial0 then points at the full UART, which the wire uses."
}
[ "$do_ssh" -eq 0 ] || harden_ssh
