import os
import tempfile
import unittest

from tests.loader import load

notify = load("thinkpad/tpkbd-notify")


class Watching(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "state")
        self.shown = []
        self.w = notify.Watcher(self.path, show=lambda: self.shown.append(1))

    def put(self, text):
        with open(self.path, "w") as f:
            f.write(text)
        self.w.step()

    def test_shown_when_input_comes_back(self):
        self.put("local\n")
        self.put("remote\n")
        self.assertEqual(self.shown, [])
        self.put("local\n")
        self.assertEqual(self.shown, [1])

    def test_not_shown_for_the_first_read_or_repeats(self):
        self.put("local\n")
        self.put("local\n")
        self.assertEqual(self.shown, [])

    def test_service_stopping_while_remote_is_silent(self):
        self.put("remote\n")
        os.remove(self.path)
        self.w.step()
        self.assertEqual(self.shown, [])

    def test_garbage_is_ignored(self):
        self.put("remote\n")
        self.put("")
        self.put("sideways\n")
        self.assertEqual(self.shown, [])
        self.put("local\n")
        self.assertEqual(self.shown, [1])


class Notifier(unittest.TestCase):
    def test_runs_the_command_with_title_and_body(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "args")
            script = os.path.join(d, "fake-notify")
            with open(script, "w") as f:
                f.write(f'#!/bin/sh\nprintf "%s|" "$@" >{out}\n')
            os.chmod(script, 0o755)
            notify.notify("T", "B", cmd=[script, "-x"])
            with open(out) as f:
                self.assertEqual(f.read(), "-x|T|B|")

    def test_missing_notifier_is_not_fatal(self):
        notify.notify("T", "B", cmd=["/nonexistent/notify-send"])

    def test_default_is_three_seconds(self):
        self.assertIn("--expire-time=3000", notify.NOTIFY)


if __name__ == "__main__":
    unittest.main()
