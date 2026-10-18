import os
import tempfile
import threading
import time
import unittest
from unittest import mock

from tests.loader import load

recv = load("pi/tpkbd-recv")

CFG = {"scale": 1.0, "watchdog_s": 0.2, "dead_s": 5.0}


class FakeOut:
    def __init__(self, accept=True):
        self.reports = []
        self.timeouts = []
        self.accept = accept

    def send(self, report, timeout=0.5):
        self.reports.append(report)
        self.timeouts.append(timeout)
        return self.accept


def make(**cfg):
    kbd, mouse = FakeOut(), FakeOut()
    return recv.Replayer(kbd, mouse, {**CFG, **cfg}), kbd, mouse


def key(rp, code, value, ts=1):
    rp.handle(f"k 1 {code} {value}")
    rp.handle(f"k 0 0 {ts}")


class Keys(unittest.TestCase):
    def test_press_and_release(self):
        rp, kbd, _ = make()
        key(rp, 30, 1)      # KEY_A
        key(rp, 30, 0)
        self.assertEqual(kbd.reports, [bytes([0, 0, 0x04, 0, 0, 0, 0, 0]), bytes(8)])

    def test_nothing_is_sent_before_the_syn(self):
        rp, kbd, _ = make()
        rp.handle("k 1 30 1")
        self.assertEqual(kbd.reports, [])

    def test_chord_in_one_frame_is_one_report(self):
        rp, kbd, _ = make()
        rp.handle("k 1 29 1")       # left ctrl
        rp.handle("k 1 30 1")       # a
        rp.handle("k 0 0 1")
        self.assertEqual(kbd.reports, [bytes([0x01, 0, 0x04, 0, 0, 0, 0, 0])])

    def test_repeat_and_unknown_keys_send_nothing(self):
        rp, kbd, _ = make()
        key(rp, 30, 1)
        key(rp, 30, 2)              # autorepeat: the host does it
        key(rp, 240, 1)             # no HID usage
        self.assertEqual(len(kbd.reports), 1)

    def test_scan_codes_and_other_event_types_are_dropped(self):
        rp, kbd, _ = make()
        rp.handle("k 4 4 30")       # EV_MSC scancode
        rp.handle("k 0 0 1")
        self.assertEqual(kbd.reports, [])

    def test_release_all_releases_keys_and_buttons(self):
        rp, kbd, mouse = make()
        key(rp, 30, 1)
        rp.handle("b 272 1 1")
        rp.release_all()
        self.assertEqual(kbd.reports[-1], bytes(8))
        self.assertEqual(mouse.reports[-1], bytes(4))

    def test_release_all_drops_half_a_frame(self):
        rp, kbd, _ = make()
        rp.handle("k 1 30 1")
        rp.release_all()
        rp.handle("k 0 0 1")
        self.assertEqual(kbd.reports, [bytes(8)])


class Pointer(unittest.TestCase):
    def test_motion(self):
        rp, _, mouse = make()
        rp.handle("m 3 -2 1")
        self.assertEqual(mouse.reports, [bytes([0, 3, 0xFE, 0])])

    def test_fractions_accumulate(self):
        rp, _, mouse = make()
        for _ in range(4):
            rp.handle("m 0.5 0 1")
        self.assertEqual(sum(r[1] if r[1] < 128 else r[1] - 256 for r in mouse.reports), 2)

    def test_scale(self):
        rp, _, mouse = make(scale=2.0)
        rp.handle("m 3 0 1")
        self.assertEqual(mouse.reports, [bytes([0, 6, 0, 0])])

    def test_large_motion_is_split(self):
        rp, _, mouse = make()
        rp.handle("m 200 0 1")
        self.assertEqual([r[1] for r in mouse.reports], [127, 73])

    def test_buttons(self):
        rp, _, mouse = make()
        rp.handle("b 272 1 1")
        rp.handle("b 273 1 1")
        rp.handle("b 272 0 1")
        self.assertEqual([r[0] for r in mouse.reports], [1, 3, 2])

    def test_unknown_button_is_ignored(self):
        rp, _, mouse = make()
        rp.handle("b 999 1 1")
        self.assertEqual(mouse.reports, [])

    def test_scroll_down_is_negative_wheel(self):
        rp, _, mouse = make()
        rp.handle("s 15 0 1")       # one click down
        self.assertEqual(mouse.reports, [bytes([0, 0, 0, 0xFF])])

    def test_scroll_up_and_accumulation(self):
        rp, _, mouse = make()
        for _ in range(3):
            rp.handle("s -5 0 1")   # three fifths of a click each, upward
        self.assertEqual(mouse.reports, [bytes([0, 0, 0, 1])])

    def test_gesture_and_heartbeat_are_ignored(self):
        rp, kbd, mouse = make()
        rp.handle("g b 1 1")
        rp.handle("g u 1.5 1")
        rp.handle("h 12345")
        self.assertEqual((kbd.reports, mouse.reports), ([], []))


class BadInput(unittest.TestCase):
    def test_garbage_never_raises(self):
        rp, kbd, mouse = make()
        for line in ("", "x", "k 1 a b", "m x y z", "k 1 30", "m 1 2 3 4"):
            rp.handle(line)
        self.assertEqual((kbd.reports, mouse.reports), ([], []))

    def test_gone_host_is_not_fatal(self):
        class Gone(FakeOut):
            def send(self, report, timeout=0.5):
                raise OSError(5, "I/O error")

        rp = recv.Replayer(Gone(), Gone(), CFG)
        with mock.patch.object(recv, "say"):
            key(rp, 30, 1)
            rp.handle("m 1 1 1")
            rp.release_all()


class Stalls(unittest.TestCase):
    def test_motion_never_waits_for_the_host(self):
        rp, _, mouse = make()
        rp.handle("m 3 0 1")
        rp.handle("s 15 0 1")
        self.assertEqual(mouse.timeouts, [0, 0])

    def test_keys_and_buttons_wait_only_briefly(self):
        rp, kbd, mouse = make()
        key(rp, 30, 1)
        rp.handle("b 272 1 1")
        self.assertTrue(0 < kbd.timeouts[0] <= 0.2)
        self.assertTrue(0 < mouse.timeouts[0] <= 0.2)

    def test_a_mouse_the_host_never_reads_does_not_hold_up_the_keyboard(self):
        # GRUB: the mouse endpoint is never polled, so its pipe stays full
        r, w = os.pipe()
        os.set_blocking(w, False)
        try:
            while True:
                os.write(w, b"x" * 4096)
        except BlockingIOError:
            pass
        kbd = FakeOut()
        rp = recv.Replayer(kbd, recv.hid.HidOut(w), CFG)
        start = time.monotonic()
        for _ in range(100):
            rp.handle("m 5 5 1")
        key(rp, 30, 1)
        elapsed = time.monotonic() - start
        os.close(r)
        os.close(w)
        self.assertLess(elapsed, 0.2)
        self.assertEqual(len(kbd.reports), 1)


class Config(unittest.TestCase):
    def test_defaults_without_a_file(self):
        cfg = recv.load_config("/nonexistent/recv.conf")
        self.assertEqual(cfg, {"scale": 1.0, "watchdog_s": 3.0, "dead_s": 30.0})

    def test_override(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "recv.conf")
            with open(path, "w") as f:
                f.write("[receiver]\nscale = 1.5\n")
            self.assertEqual(recv.load_config(path)["scale"], 1.5)


class Serve(unittest.TestCase):
    def run_serve(self, feed, **kw):
        rp, kbd, mouse = make(**kw)
        r, w = os.pipe()
        t = threading.Thread(target=recv.serve, args=(rp, r, CFG["watchdog_s"], CFG["dead_s"]))
        t.start()
        feed(w)
        t.join(5)
        os.close(r)
        self.assertFalse(t.is_alive())
        return kbd, mouse

    def test_eof_releases_everything(self):
        def feed(w):
            os.write(w, b"k 1 30 1\nk 0 0 1\nb 272 1 1\n")
            os.close(w)

        kbd, mouse = self.run_serve(feed)
        self.assertEqual(kbd.reports[-1], bytes(8))
        self.assertEqual(mouse.reports[-1], bytes(4))

    def test_lines_split_across_reads(self):
        def feed(w):
            os.write(w, b"k 1 30 1\nk 0")
            os.write(w, b" 0 1\n")
            os.close(w)

        kbd, _ = self.run_serve(feed)
        self.assertEqual(kbd.reports[0], bytes([0, 0, 0x04, 0, 0, 0, 0, 0]))

    def test_silence_releases_then_dead_exits(self):
        with mock.patch.object(recv, "say"):
            rp, kbd, _ = make()
            r, w = os.pipe()
            try:
                os.write(w, b"k 1 30 1\nk 0 0 1\n")
                recv.serve(rp, r, 0.1, 0.4)     # returns by itself after 0.4 s of silence
            finally:
                os.close(r)
                os.close(w)
        # released once by the watchdog, once on the way out
        self.assertEqual(kbd.reports.count(bytes(8)), 2)


if __name__ == "__main__":
    unittest.main()
