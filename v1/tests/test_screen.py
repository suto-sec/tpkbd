"""tpkbd-screen against a fake /sys and /run, with sleep and chvt stubbed out."""
import os
import subprocess
import tempfile
import unittest

from tests.loader import ROOT


class Screen(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.t = tmp.name
        with open(os.path.join(ROOT, "thinkpad/tpkbd-screen")) as f:
            src = f.read()
        src = src.replace("/sys/class", f"{self.t}/sys/class").replace("/run/tpkbd", f"{self.t}/run/tpkbd")
        self.script = os.path.join(self.t, "tpkbd-screen")
        with open(self.script, "w") as f:
            f.write(src)
        os.makedirs(f"{self.t}/run")
        self.bin = os.path.join(self.t, "bin")
        os.makedirs(self.bin)
        self.calls = os.path.join(self.t, "calls")
        for name in ("sleep", "chvt"):
            path = os.path.join(self.bin, name)
            with open(path, "w") as f:
                f.write(f'#!/bin/sh\necho "{name} $*" >> {self.calls}\n')
            os.chmod(path, 0o755)
        # two backlight devices with different scales, like some laptops have
        self.bl = {"intel_backlight": (400, 937), "acpi_video0": (5, 10)}
        for name, (cur, mx) in self.bl.items():
            d = f"{self.t}/sys/class/backlight/{name}"
            os.makedirs(d)
            self.write(f"{d}/brightness", cur)
            self.write(f"{d}/max_brightness", mx)
        os.makedirs(f"{self.t}/sys/class/drm/card0-eDP-1")
        self.write(f"{self.t}/sys/class/drm/card0-eDP-1/status", "connected")

    def write(self, path, value):
        with open(path, "w") as f:
            f.write(f"{value}\n")

    def read(self, path):
        with open(path) as f:
            return f.read().strip()

    def brightness(self, name):
        return int(self.read(f"{self.t}/sys/class/backlight/{name}/brightness"))

    def status(self):
        return self.read(f"{self.t}/sys/class/drm/card0-eDP-1/status")

    def called(self):
        if not os.path.exists(self.calls):
            return []
        return self.read(self.calls).splitlines()

    def run_script(self, *args, **env):
        e = {"PATH": f"{self.bin}:/usr/bin:/bin", **env}
        subprocess.run(["sh", self.script, *args], env=e, check=True)

    def test_off_blanks_every_backlight_and_the_connector(self):
        self.run_script("off")
        self.assertEqual((self.brightness("intel_backlight"), self.brightness("acpi_video0")), (0, 0))
        self.assertEqual(self.status(), "off")
        self.assertIn("chvt 1", self.called())
        self.assertIn("sleep 2", self.called())

    def test_reconnect_skips_the_wait_and_keeps_the_saved_brightness(self):
        self.run_script("off")
        os.remove(self.calls)
        self.run_script("off")
        self.assertEqual(self.called(), [])   # no "sleep 2", no chvt
        self.run_script("post", EXIT_STATUS="42")
        self.assertEqual(self.brightness("intel_backlight"), 400)   # not overwritten by 0

    def test_restore_uses_each_devices_own_value(self):
        self.run_script("off")
        self.run_script("post", EXIT_STATUS="42")
        self.assertEqual((self.brightness("intel_backlight"), self.brightness("acpi_video0")), (400, 5))
        self.assertEqual(self.status(), "detect")
        self.assertEqual([f for f in os.listdir(f"{self.t}/run")], [])

    def test_restore_on_clean_stop_and_term(self):
        for status in ("0", "TERM", "INT"):
            self.run_script("off")
            self.run_script("post", EXIT_STATUS=status)
            self.assertEqual(self.brightness("intel_backlight"), 400, status)

    def test_saved_zero_falls_back_to_max(self):
        self.write(f"{self.t}/sys/class/backlight/intel_backlight/brightness", 0)
        self.run_script("off")
        self.run_script("post", EXIT_STATUS="42")
        self.assertEqual(self.brightness("intel_backlight"), 937)

    def test_stop_without_ever_going_off_leaves_the_brightness_alone(self):
        for status in ("0", "42", "TERM", "INT"):
            self.run_script("post", EXIT_STATUS=status)
            self.assertEqual(self.brightness("intel_backlight"), 400, status)
            self.assertEqual(self.status(), "connected", status)

    def test_second_stop_after_a_giveup_restore_changes_nothing(self):
        self.run_script("off")
        self.run_script("post", EXIT_STATUS="1")
        self.write(f"{self.t}/run/tpkbd-lost", 1)
        self.run_script("pre", TPKBD_SCREEN_GIVEUP="10")           # restores
        self.write(f"{self.t}/sys/class/backlight/intel_backlight/brightness", 123)
        self.run_script("post", EXIT_STATUS="0")                    # the user changed it since
        self.assertEqual(self.brightness("intel_backlight"), 123)

    def test_machine_without_a_backlight_still_comes_back(self):
        for name in self.bl:
            for f in ("brightness", "max_brightness"):
                os.remove(f"{self.t}/sys/class/backlight/{name}/{f}")
            os.rmdir(f"{self.t}/sys/class/backlight/{name}")
        self.run_script("off")
        self.assertEqual(self.status(), "off")
        self.run_script("post", EXIT_STATUS="42")
        self.assertEqual(self.status(), "detect")

    def test_failure_keeps_the_panel_off_and_notes_the_time(self):
        self.run_script("off")
        self.run_script("post", EXIT_STATUS="1")
        self.assertEqual(self.brightness("intel_backlight"), 0)
        self.assertTrue(os.path.exists(f"{self.t}/run/tpkbd-lost"))

    def test_failure_before_the_panel_was_ever_off_changes_nothing(self):
        self.run_script("post", EXIT_STATUS="1")
        self.assertFalse(os.path.exists(f"{self.t}/run/tpkbd-lost"))
        self.assertEqual(self.brightness("intel_backlight"), 400)

    def test_gives_up_after_the_limit(self):
        self.run_script("off")
        self.run_script("post", EXIT_STATUS="1")
        self.run_script("pre", TPKBD_SCREEN_GIVEUP="1000")
        self.assertEqual(self.brightness("intel_backlight"), 0)    # not long enough yet
        self.write(f"{self.t}/run/tpkbd-lost", 1)                   # lost long ago
        self.run_script("pre", TPKBD_SCREEN_GIVEUP="1000")
        self.assertEqual(self.brightness("intel_backlight"), 400)
        self.assertEqual(self.status(), "detect")

    def test_reconnect_clears_the_lost_note(self):
        self.run_script("off")
        self.run_script("post", EXIT_STATUS="1")
        self.run_script("off")
        self.assertFalse(os.path.exists(f"{self.t}/run/tpkbd-lost"))


if __name__ == "__main__":
    unittest.main()
