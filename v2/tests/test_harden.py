"""pi/harden.sh run for real, against a temporary config.txt and sshd drop-in directory,
with stub `sshd` and `systemctl` programs."""
import os
import stat
import subprocess
import tempfile
import unittest

from tests.loader import ROOT

SCRIPT = os.path.join(ROOT, "pi", "harden.sh")

# `sshd -t` fails when STUB_SSHD_FAIL exists; `sshd -T` echoes the drop-in lowercased,
# unless STUB_SSHD_IGNORE exists (another file overrides ours)
SSHD_STUB = """#!/bin/sh
case "$1" in
    -t) [ ! -e "$STUB_DIR/sshd-fail" ] ;;
    -T) if [ -e "$STUB_DIR/sshd-ignore" ]; then echo "passwordauthentication yes"
        else tr 'A-Z' 'a-z' <"$TPKBD_SSHD_DIR/10-tpkbd.conf" | grep -v '^#'; fi ;;
esac
"""
# `is-enabled UNIT` succeeds for the units listed in $STUB_DIR/enabled-units
SYSTEMCTL_STUB = """#!/bin/sh
echo "$*" >>"$STUB_DIR/systemctl.log"
if [ "$1" = is-enabled ]; then
    grep -qxF "$2" "$STUB_DIR/enabled-units" 2>/dev/null
fi
"""

BASE_CONFIG = "dtparam=audio=on\n[pi4]\narm_boost=1\n"


class Harden(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        self.config = os.path.join(self.dir, "config.txt")
        self.sshd_dir = os.path.join(self.dir, "sshd_config.d")
        self.keys = os.path.join(self.dir, "authorized_keys")
        self.write(self.config, BASE_CONFIG)
        self.write(self.keys, "# a comment\nssh-ed25519 AAAA test@laptop\n")
        for name, body in (("sshd", SSHD_STUB), ("systemctl", SYSTEMCTL_STUB)):
            path = os.path.join(self.dir, name)
            self.write(path, body)
            os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)

    def tearDown(self):
        self._tmp.cleanup()

    @staticmethod
    def write(path, text):
        with open(path, "w") as f:
            f.write(text)

    @staticmethod
    def read(path):
        with open(path) as f:
            return f.read()

    @property
    def dropin(self):
        return os.path.join(self.sshd_dir, "10-tpkbd.conf")

    def run_script(self, *args, stdin=""):
        env = dict(os.environ, STUB_DIR=self.dir, TPKBD_SKIP_ROOT_CHECK="1",
                   TPKBD_BOOT_CONFIG=self.config, TPKBD_SSHD_DIR=self.sshd_dir,
                   TPKBD_AUTH_KEYS=self.keys,
                   TPKBD_SYSTEMD_CONF_DIR=os.path.join(self.dir, "system.conf.d"),
                   TPKBD_STATE_DIR=os.path.join(self.dir, "state"), TPKBD_SSHD=os.path.join(self.dir, "sshd"),
                   TPKBD_SYSTEMCTL=os.path.join(self.dir, "systemctl"))
        return subprocess.run(["sh", SCRIPT, *args], input=stdin, env=env,
                              capture_output=True, text=True)

    def systemctl_log(self):
        path = os.path.join(self.dir, "systemctl.log")
        return self.read(path) if os.path.exists(path) else ""

    def test_default_is_bluetooth_and_ssh(self):
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("dtoverlay=disable-bt", self.read(self.config))
        self.assertNotIn("disable-wifi", self.read(self.config))
        self.assertIn("PasswordAuthentication no", self.read(self.dropin))
        self.assertIn("reload ssh", self.systemctl_log())

    def test_overlay_goes_under_all_and_the_original_is_kept(self):
        self.run_script("--bluetooth")
        text = self.read(self.config)
        self.assertTrue(text.startswith(BASE_CONFIG))
        self.assertLess(text.index("[all]"), text.index("dtoverlay=disable-bt"))
        self.assertEqual(self.read(self.config + ".tpkbd-orig"), BASE_CONFIG)

    def test_no_second_all_header_when_already_in_all(self):
        self.write(self.config, "[all]\ndtoverlay=dwc2\n")
        self.run_script("--bluetooth")
        self.assertEqual(self.read(self.config).count("[all]"), 1)

    def test_bluetooth_twice_changes_nothing(self):
        self.run_script("--bluetooth")
        once = self.read(self.config)
        r = self.run_script("--bluetooth")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.read(self.config), once)

    def test_ssh_refused_without_a_key(self):
        self.write(self.keys, "# only a comment\n\n")
        r = self.run_script("--ssh")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no ordinary key", r.stderr)
        self.assertFalse(os.path.exists(self.dropin))

    def test_ssh_refused_with_only_a_forced_command_key(self):
        self.write(self.keys, 'command="/usr/local/bin/tpkbd-recv",no-pty ssh-ed25519 AAAA t@l\n')
        r = self.run_script("--ssh")
        self.assertEqual(r.returncode, 1)
        self.assertFalse(os.path.exists(self.dropin))

    def test_ssh_accepts_an_ecdsa_key(self):
        self.write(self.keys, "ecdsa-sha2-nistp256 AAAA t@l\n")
        self.assertEqual(self.run_script("--ssh").returncode, 0)

    def test_ssh_refused_when_the_key_file_is_missing(self):
        os.remove(self.keys)
        r = self.run_script("--ssh")
        self.assertEqual(r.returncode, 1)
        self.assertFalse(os.path.exists(self.dropin))

    def test_ssh_rolled_back_when_sshd_rejects_it(self):
        self.write(os.path.join(self.dir, "sshd-fail"), "")
        r = self.run_script("--ssh")
        self.assertEqual(r.returncode, 1)
        self.assertIn("put things back", r.stderr)
        self.assertFalse(os.path.exists(self.dropin))

    def test_ssh_rolled_back_when_another_file_wins(self):
        self.write(os.path.join(self.dir, "sshd-ignore"), "")
        r = self.run_script("--ssh")
        self.assertEqual(r.returncode, 1)
        self.assertIn("overrides", r.stderr)
        self.assertFalse(os.path.exists(self.dropin))

    def test_rollback_keeps_an_earlier_good_dropin(self):
        self.run_script("--ssh")
        good = self.read(self.dropin)
        self.write(os.path.join(self.dir, "sshd-fail"), "")
        self.run_script("--ssh")
        self.assertEqual(self.read(self.dropin), good)

    def test_wifi_off_asks_first(self):
        r = self.run_script("--wifi-off", stdin="no\n")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.read(self.config), BASE_CONFIG)
        r = self.run_script("--wifi-off", stdin="")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.read(self.config), BASE_CONFIG)

    def test_wifi_off_after_yes(self):
        r = self.run_script("--wifi-off", stdin="yes\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("dtoverlay=disable-wifi", self.read(self.config))
        self.assertFalse(os.path.exists(self.dropin))

    def test_wifi_off_cannot_be_combined(self):
        for other in ("--ssh", "--bluetooth", "--undo"):
            r = self.run_script("--wifi-off", other, stdin="yes\n")
            self.assertEqual(r.returncode, 2, other)
        self.assertEqual(self.read(self.config), BASE_CONFIG)

    def test_unknown_option(self):
        self.assertEqual(self.run_script("--frobnicate").returncode, 2)

    def test_undo_restores_everything(self):
        self.run_script()
        self.run_script("--wifi-off", stdin="yes\n")
        r = self.run_script("--undo")
        self.assertEqual(r.returncode, 0, r.stderr)
        text = self.read(self.config)
        self.assertNotIn("disable-bt", text)
        self.assertNotIn("disable-wifi", text)
        self.assertNotIn("tpkbd harden.sh", text)
        self.assertFalse(os.path.exists(self.dropin))
        self.assertTrue(text.startswith(BASE_CONFIG))

    def test_undo_keeps_a_line_the_user_added_themselves(self):
        self.write(self.config, BASE_CONFIG + "dtoverlay=disable-bt\n")
        self.run_script("--bluetooth")     # already there: not ours, not tagged
        self.run_script("--undo")
        self.assertIn("dtoverlay=disable-bt", self.read(self.config))

    @property
    def watchdog(self):
        return os.path.join(self.dir, "system.conf.d", "10-tpkbd-watchdog.conf")

    def test_watchdog_writes_the_systemd_setting(self):
        r = self.run_script("--watchdog")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("RuntimeWatchdogSec=15", self.read(self.watchdog))
        self.assertIn("daemon-reexec", self.systemctl_log())
        self.assertEqual(self.read(self.config), BASE_CONFIG)       # nothing else touched
        self.assertFalse(os.path.exists(self.dropin))

    def test_fast_boot_disables_only_enabled_units(self):
        self.write(os.path.join(self.dir, "enabled-units"), "apt-daily.timer\navahi-daemon.service\n")
        r = self.run_script("--fast-boot")
        self.assertEqual(r.returncode, 0, r.stderr)
        log = self.systemctl_log()
        self.assertIn("disable --now apt-daily.timer", log)
        self.assertIn("disable --now avahi-daemon.service", log)
        self.assertNotIn("disable --now man-db.timer", log)
        text = self.read(self.config)
        self.assertIn("disable_splash=1", text)
        self.assertIn("boot_delay=0", text)
        self.assertEqual(text.count("[all]"), 1)

    def test_fast_boot_never_touches_the_wire_services(self):
        everything = "\n".join(["tpkbd-recv.service", "tpkbd-gadget.service", "ssh.service",
                                "serial-getty@ttyS0.service", "apt-daily.timer"])
        self.write(os.path.join(self.dir, "enabled-units"), everything + "\n")
        self.run_script("--fast-boot")
        log = self.systemctl_log()
        for keep in ("tpkbd", "ssh", "getty"):
            self.assertNotIn(f"disable --now {keep}", log)
            self.assertNotIn(keep, "".join(l for l in log.splitlines() if l.startswith("disable")))

    def test_undo_brings_back_watchdog_and_services(self):
        self.write(os.path.join(self.dir, "enabled-units"), "apt-daily.timer\n")
        self.run_script("--watchdog")
        self.run_script("--fast-boot")
        r = self.run_script("--undo")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(self.watchdog))
        self.assertIn("enable apt-daily.timer", self.systemctl_log())
        text = self.read(self.config)
        self.assertNotIn("disable_splash", text)
        self.assertNotIn("boot_delay", text)

    def test_undo_does_not_enable_what_we_never_disabled(self):
        self.run_script("--undo")
        self.assertNotIn("enable ", self.systemctl_log())

    def test_watchdog_and_fast_boot_cannot_join_wifi_off(self):
        for other in ("--watchdog", "--fast-boot"):
            self.assertEqual(self.run_script("--wifi-off", other, stdin="yes\n").returncode, 2)

    def test_undo_with_nothing_to_undo(self):
        r = self.run_script("--undo")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read(self.config), BASE_CONFIG)


if __name__ == "__main__":
    unittest.main()
