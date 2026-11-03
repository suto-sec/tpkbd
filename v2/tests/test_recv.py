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
        self.assertEqual(mouse.reports[-1], bytes(5))

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
        self.assertEqual(mouse.reports, [bytes([0, 3, 0xFE, 0, 0])])

    def test_fractions_accumulate(self):
        rp, _, mouse = make()
        for _ in range(4):
            rp.handle("m 0.5 0 1")
        self.assertEqual(sum(r[1] if r[1] < 128 else r[1] - 256 for r in mouse.reports), 2)

    def test_scale(self):
        rp, _, mouse = make(scale=2.0)
        rp.handle("m 3 0 1")
        self.assertEqual(mouse.reports, [bytes([0, 6, 0, 0, 0])])

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
        self.assertEqual(mouse.reports, [bytes([0, 0, 0, 0xFF, 0])])

    def test_scroll_up_and_accumulation(self):
        rp, _, mouse = make()
        for _ in range(3):
            rp.handle("s -5 0 1")   # three fifths of a click each, upward
        self.assertEqual(mouse.reports, [bytes([0, 0, 0, 1, 0])])

    def test_heartbeat_is_ignored(self):
        rp, kbd, mouse = make()
        rp.handle("h 12345")
        self.assertEqual((kbd.reports, mouse.reports), ([], []))

    def test_scroll_right_and_left(self):
        rp, _, mouse = make()
        rp.handle("s 0 15 1")       # one click to the right
        rp.handle("s 0 -15 1")
        self.assertEqual(mouse.reports, [bytes([0, 0, 0, 0, 1]), bytes([0, 0, 0, 0, 0xFF])])

    def test_diagonal_scroll_is_one_report(self):
        rp, _, mouse = make()
        rp.handle("s 15 15 1")
        self.assertEqual(mouse.reports, [bytes([0, 0, 0, 0xFF, 1])])

    def test_horizontal_fractions_accumulate(self):
        rp, _, mouse = make()
        for _ in range(3):
            rp.handle("s 0 5 1")
        self.assertEqual(mouse.reports, [bytes([0, 0, 0, 0, 1])])


class MediaKeys(unittest.TestCase):
    def make(self, **kw):
        consumer = FakeOut()
        kbd, mouse = FakeOut(), FakeOut()
        return recv.Replayer(kbd, mouse, {**CFG, **kw}, consumer_out=consumer), kbd, consumer

    def test_volume_up_goes_to_the_consumer_device(self):
        rp, kbd, consumer = self.make()
        key(rp, 115, 1)
        key(rp, 115, 0)
        self.assertEqual(consumer.reports, [bytes([0xE9, 0]), bytes(2)])
        self.assertEqual(kbd.reports, [])

    def test_ordinary_keys_stay_on_the_keyboard(self):
        rp, kbd, consumer = self.make()
        key(rp, 30, 1)
        self.assertEqual(len(kbd.reports), 1)
        self.assertEqual(consumer.reports, [])

    def test_without_the_device_media_keys_are_dropped(self):
        rp, kbd, _ = make()
        key(rp, 115, 1)
        self.assertEqual(kbd.reports, [])

    def test_release_all_releases_media_keys(self):
        rp, _, consumer = self.make()
        key(rp, 115, 1)
        rp.release_all()
        self.assertEqual(consumer.reports[-1], bytes(2))

    def test_media_key_and_letter_in_one_frame(self):
        rp, kbd, consumer = self.make()
        rp.handle("k 1 115 1")
        rp.handle("k 1 30 1")
        rp.handle("k 0 0 1")
        self.assertEqual((len(kbd.reports), len(consumer.reports)), (1, 1))


class Pinch(unittest.TestCase):
    CTRL_DOWN = bytes([0x01, 0, 0, 0, 0, 0, 0, 0])

    def clicks(self, mouse):
        return [int.from_bytes(r[3:4], "little", signed=True) for r in mouse.reports]

    def test_spreading_zooms_in_with_ctrl_held(self):
        rp, kbd, mouse = make(pinch_clicks=6.0)
        rp.handle("g b 1 1")
        rp.handle("g u 2.0 1")          # doubled: 6 clicks up
        self.assertEqual(kbd.reports, [self.CTRL_DOWN])
        self.assertEqual(sum(self.clicks(mouse)), 6)
        rp.handle("g e 1 1")
        self.assertEqual(kbd.reports[-1], bytes(8))

    def test_pinching_zooms_out(self):
        rp, kbd, mouse = make(pinch_clicks=6.0)
        rp.handle("g b 1 1")
        rp.handle("g u 0.5 1")
        self.assertEqual(sum(self.clicks(mouse)), -6)

    def test_updates_send_only_the_difference(self):
        rp, _, mouse = make(pinch_clicks=6.0)
        rp.handle("g b 1 1")
        for scale in (1.1, 1.2, 1.4, 2.0):
            rp.handle(f"g u {scale} 1")
        self.assertEqual(sum(self.clicks(mouse)), 6)

    def test_small_changes_do_not_press_ctrl(self):
        rp, kbd, _ = make(pinch_clicks=6.0)
        rp.handle("g b 1 1")
        rp.handle("g u 1.02 1")
        self.assertEqual(kbd.reports, [])

    def test_ctrl_is_pressed_once(self):
        rp, kbd, _ = make(pinch_clicks=6.0)
        rp.handle("g b 1 1")
        rp.handle("g u 1.5 1")
        rp.handle("g u 2.0 1")
        self.assertEqual(kbd.reports.count(self.CTRL_DOWN), 1)

    def test_it_combines_with_a_held_real_modifier(self):
        rp, kbd, _ = make(pinch_clicks=6.0)
        key(rp, 42, 1)                  # shift
        rp.handle("g b 1 1")
        rp.handle("g u 2.0 1")
        self.assertEqual(kbd.reports[-1][0], 0x03)
        rp.handle("g e 1 1")
        self.assertEqual(kbd.reports[-1][0], 0x02)      # shift stays down

    def test_a_new_pinch_starts_from_scratch(self):
        rp, _, mouse = make(pinch_clicks=6.0)
        for _ in range(2):
            rp.handle("g b 1 1")
            rp.handle("g u 2.0 1")
            rp.handle("g e 1 1")
        self.assertEqual(sum(self.clicks(mouse)), 12)

    def test_release_all_lets_go_of_ctrl(self):
        rp, kbd, _ = make(pinch_clicks=6.0)
        rp.handle("g b 1 1")
        rp.handle("g u 2.0 1")
        rp.release_all()
        self.assertEqual(kbd.reports[-1], bytes(8))
        rp.handle("g e 1 1")            # a late end changes nothing
        self.assertEqual(kbd.reports[-1], bytes(8))

    def test_nonsense_scale_is_ignored(self):
        rp, kbd, mouse = make()
        with mock.patch.object(recv, "say"):
            rp.handle("g u 0 1")
            rp.handle("g u -1 1")
        self.assertEqual((kbd.reports, mouse.reports), ([], []))

    def test_update_without_begin_still_works(self):
        rp, _, mouse = make(pinch_clicks=6.0)
        rp.handle("g u 2.0 1")
        self.assertEqual(sum(self.clicks(mouse)), 6)


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


class Gone(unittest.TestCase):
    def test_a_vanished_port_releases_and_returns(self):
        rp, kbd, mouse = make()
        r, w = os.pipe()
        os.write(w, b"k 1 30 1\nk 0 0 1\n")
        os.close(w)
        os.close(r)     # reading a closed descriptor: EBADF, like a port that went away
        with mock.patch.object(recv, "say"):
            recv.serve(rp, r, 0.1, 0)
        self.assertEqual(kbd.reports[-1], bytes(8))


class Config(unittest.TestCase):
    def test_defaults_without_a_file(self):
        cfg = recv.load_config("/nonexistent/recv.conf")
        self.assertEqual(cfg, {"scale": 1.0, "pinch_clicks": 6.0, "watchdog_s": 3.0, "dead_s": 30.0,
                               "half0": 400.0, "pinch": "touchpad", "led": "on"})

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
        self.assertEqual(mouse.reports[-1], bytes(5))

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


class TouchpadPinch(unittest.TestCase):
    def make(self, **cfg):
        kbd, mouse, touch = FakeOut(), FakeOut(), FakeOut()
        rp = recv.Replayer(kbd, mouse, {**CFG, **cfg}, touch_out=touch)
        return rp, kbd, mouse, touch

    @staticmethod
    def half(report):
        return int.from_bytes(report[6:8], "little") - 2000

    def test_begin_puts_two_fingers_down(self):
        rp, kbd, mouse, touch = self.make()
        rp.handle("g b 1 1")
        self.assertEqual(touch.reports, [recv.hid.Touchpad().begin(400)])
        self.assertEqual(touch.timeouts, [recv.BUTTON_WAIT_S])

    def test_updates_move_the_fingers_apart_and_together(self):
        rp, _, _, touch = self.make()
        rp.handle("g b 1 1")
        rp.handle("g u 2.0 1")
        rp.handle("g u 0.5 1")
        self.assertEqual([self.half(r) for r in touch.reports], [400, 800, 200])
        self.assertEqual(touch.timeouts[1:], [recv.MOTION_WAIT_S] * 2)

    def test_the_end_lifts_them(self):
        rp, _, _, touch = self.make()
        rp.handle("g b 1 1")
        rp.handle("g u 1.5 1")
        rp.handle("g e 1 1")
        self.assertEqual((touch.reports[-1][0], touch.reports[-1][5]), (0x00, 0x10))
        self.assertEqual(touch.timeouts[-1], recv.BUTTON_WAIT_S)
        self.assertFalse(rp.touch.down)

    def test_no_ctrl_and_no_wheel(self):
        rp, kbd, mouse, _ = self.make()
        rp.handle("g b 1 1")
        rp.handle("g u 3.0 1")
        rp.handle("g e 1 1")
        self.assertEqual((kbd.reports, mouse.reports), ([], []))

    def test_a_long_pinch_starts_over_in_the_middle(self):
        rp, _, _, touch = self.make()
        rp.handle("g b 1 1")
        rp.handle("g u 4.0 1")          # 1600: still on the pad
        n = len(touch.reports)
        rp.handle("g u 5.0 1")          # 2000: off the pad
        lift, down = touch.reports[n], touch.reports[n + 1]
        self.assertEqual(lift[0], 0x00)
        self.assertEqual(self.half(down), 400)
        rp.handle("g u 6.0 1")          # measured from where it started over
        self.assertEqual(self.half(touch.reports[-1]), round(400 * 6.0 / 5.0))

    def test_an_update_without_a_begin_starts_there(self):
        rp, _, _, touch = self.make()
        rp.handle("g u 1.7 1")
        rp.handle("g u 3.4 1")
        self.assertEqual([self.half(r) for r in touch.reports], [400, 800])

    def test_pinch_ctrlwheel_setting_uses_ctrl_and_wheel(self):
        rp, kbd, mouse, touch = self.make(pinch="ctrlwheel", pinch_clicks=6.0)
        rp.handle("g b 1 1")
        rp.handle("g u 2.0 1")
        rp.handle("g e 1 1")
        self.assertEqual(touch.reports, [])
        self.assertEqual(len(kbd.reports), 2)
        self.assertTrue(mouse.reports)

    def test_losing_the_sender_lifts_the_fingers(self):
        rp, _, _, touch = self.make()
        rp.handle("g b 1 1")
        rp.release_all()
        self.assertEqual(touch.reports[-1][0], 0x00)
        n = len(touch.reports)
        rp.release_all()                # nothing down: nothing more to lift
        self.assertEqual(len(touch.reports), n)

    def test_half0_setting(self):
        rp, _, _, touch = self.make(half0=600.0)
        rp.handle("g b 1 1")
        self.assertEqual(self.half(touch.reports[0]), 600)

    def test_config_default_and_unknown_mode(self):
        self.assertEqual(recv.load_config("/nonexistent/recv.conf")["pinch"], "touchpad")
        with tempfile.TemporaryDirectory() as t:
            path = os.path.join(t, "recv.conf")
            with open(path, "w") as f:
                f.write("[receiver]\npinch = CtrlWheel\n")
            self.assertEqual(recv.load_config(path)["pinch"], "ctrlwheel")
            with open(path, "w") as f:
                f.write("[receiver]\npinch = gesture\n")
            with self.assertRaises(ValueError):
                recv.load_config(path)


class FakeLedDir:
    """A pretend /sys/class/leds/ACT in a temp directory."""

    def __init__(self, trigger="none [mmc0] heartbeat"):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = self.tmp.name
        self.put("trigger", trigger)
        self.put("brightness", "0")

    def put(self, name, text):
        with open(os.path.join(self.path, name), "w") as f:
            f.write(text)

    def get(self, name):
        with open(os.path.join(self.path, name)) as f:
            return f.read()


class LedSetting(unittest.TestCase):
    def setUp(self):
        self.d = FakeLedDir()
        self.addCleanup(self.d.tmp.cleanup)
        patch = mock.patch.object(recv, "say")
        patch.start()
        self.addCleanup(patch.stop)

    def led(self, mode):
        return recv.Led(mode, dirs=(self.d.path,))

    def test_config_default_and_override(self):
        with tempfile.TemporaryDirectory() as t:
            path = os.path.join(t, "recv.conf")
            with open(path, "w") as f:
                f.write("[receiver]\nled = OFF\n")
            self.assertEqual(recv.load_config(path)["led"], "off")

    def test_config_rejects_unknown_mode(self):
        with tempfile.TemporaryDirectory() as t:
            path = os.path.join(t, "recv.conf")
            with open(path, "w") as f:
                f.write("[receiver]\nled = blink\n")
            with self.assertRaises(ValueError):
                recv.load_config(path)

    def test_off_and_on_take_over_the_led(self):
        self.led("on")
        self.assertEqual((self.d.get("trigger"), self.d.get("brightness")), ("none", "1"))
        self.led("off")
        self.assertEqual(self.d.get("brightness"), "0")

    def test_close_leaves_the_led_as_set(self):
        led = self.led("on")
        led.close()
        self.assertEqual((self.d.get("trigger"), self.d.get("brightness")), ("none", "1"))

    def test_close_darkens_activity_mode(self):
        led = self.led("activity")
        led.flash(1.0)
        led.close()
        self.assertEqual(self.d.get("brightness"), "0")

    def test_on_is_the_default(self):
        self.assertEqual(recv.load_config("/nonexistent/recv.conf")["led"], "on")

    def test_activity_lights_on_input_then_goes_dark(self):
        led = self.led("activity")
        self.assertEqual(self.d.get("brightness"), "0")
        led.flash(100.0)
        self.assertEqual(self.d.get("brightness"), "1")
        led.tick(100.0 + recv.LED_FLASH_S / 2)
        self.assertEqual(self.d.get("brightness"), "1")
        led.tick(100.0 + recv.LED_FLASH_S + 0.01)
        self.assertEqual(self.d.get("brightness"), "0")

    def test_activity_extends_while_input_continues(self):
        led = self.led("activity")
        led.flash(100.0)
        led.flash(100.05)
        led.tick(100.0 + recv.LED_FLASH_S + 0.01)   # first flash would be over, second is not
        self.assertEqual(self.d.get("brightness"), "1")

    def test_off_and_on_ignore_input(self):
        led = self.led("off")
        led.flash(1.0)
        self.assertEqual(self.d.get("brightness"), "0")

    def test_serve_may_sleep_only_until_the_led_must_go_dark(self):
        led = self.led("activity")
        self.assertEqual(led.timeout(5.0, 0.5), 0.5)
        led.flash(5.0)
        self.assertAlmostEqual(led.timeout(5.0, 0.5), recv.LED_FLASH_S)

    def test_no_led_is_not_an_error(self):
        led = recv.Led("activity", dirs=("/nonexistent/led",))
        led.flash(1.0)
        led.tick(5.0)
        led.close()
        self.assertEqual(led.timeout(1.0, 0.5), 0.5)

    def test_no_permission_is_not_an_error(self):
        trigger = os.path.join(self.d.path, "trigger")
        os.remove(trigger)
        os.mkdir(trigger)       # opening it for writing fails, like a root-only file would
        led = self.led("on")
        led.flash(1.0)
        self.assertIsNone(led.dir)

    def test_input_lines_flash_but_heartbeats_do_not(self):
        led = self.led("activity")
        rp = recv.Replayer(FakeOut(), FakeOut(), CFG, led=led)
        rp.handle("h 1")
        self.assertEqual(self.d.get("brightness"), "0")
        rp.handle("m 3 4 1")
        self.assertEqual(self.d.get("brightness"), "1")

    def test_serve_turns_the_led_off_after_the_input_stops(self):
        led = self.led("activity")
        rp = recv.Replayer(FakeOut(), FakeOut(), CFG, led=led)
        r, w = os.pipe()
        t = threading.Thread(target=recv.serve, args=(rp, r, 5.0, 0))
        t.start()
        try:
            os.write(w, b"m 3 4 1\n")
            time.sleep(0.05)
            self.assertEqual(self.d.get("brightness"), "1")
            time.sleep(0.4)
            self.assertEqual(self.d.get("brightness"), "0")
        finally:
            os.close(w)     # EOF ends serve()
            t.join(5)
            os.close(r)


if __name__ == "__main__":
    unittest.main()
