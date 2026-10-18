import os
import sys
import tempfile
import unittest

from tests.loader import load

send = load("thinkpad/tpkbd-send")
e = send.e


class Ev:
    def __init__(self, type, code, value, sec=0, usec=0):
        self.type, self.code, self.value, self.sec, self.usec = type, code, value, sec, usec


class FakeLink:
    proc = True
    eof = False

    def __init__(self):
        self.sent = []

    def send(self, lines):
        self.sent.extend(lines)

    def close(self):
        pass


class OfflineSender(send.Sender):
    """A Sender without devices or libinput."""

    grabbed = False

    def _grab_all(self):
        self.grabbed = True

    def _ungrab_all(self):
        self.grabbed = False

    def start_libinput(self):
        pass

    def stop_libinput(self):
        pass


def make(soft=False, state="local", conf=None):
    s = OfflineSender(send.load_config(conf or "/nonexistent"), soft=soft, link=FakeLink())
    if state == "remote":
        s.enter_remote()
    return s


def tap(s, code, value):
    s.handle_key(Ev(e.EV_KEY, code, value))
    s.handle_key(Ev(e.EV_SYN, e.SYN_REPORT, 0))


class ParseLibinput(unittest.TestCase):
    # lines shaped like `libinput debug-events` output
    def test_motion(self):
        line = " event5   POINTER_MOTION    +1.23s\t 0.87/ -1.40 ( +0.87/ -1.40 unaccelerated)"
        self.assertEqual(send.parse_libinput_line(line), "m 0.87 -1.40")

    def test_motion_with_repeat_counter(self):
        line = "-event5   POINTER_MOTION    3  +1.23s\t 0.87/ -1.40 ( +0.87/ -1.40 unaccelerated)"
        self.assertEqual(send.parse_libinput_line(line), "m 0.87 -1.40")

    def test_buttons(self):
        down = " event5   POINTER_BUTTON    +2.10s\t BTN_LEFT (272) pressed, seat count: 1"
        up = " event5   POINTER_BUTTON    +2.20s\t BTN_LEFT (272) released, seat count: 0"
        self.assertEqual(send.parse_libinput_line(down), "b 272 1")
        self.assertEqual(send.parse_libinput_line(up), "b 272 0")

    def test_scroll(self):
        line = " event5   POINTER_SCROLL_FINGER +3.00s\t vert 0.00/0.0 horiz 15.00/0.0* (finger)"
        self.assertEqual(send.parse_libinput_line(line), "s 0.00 15.00")

    def test_pinch(self):
        self.assertEqual(send.parse_libinput_line(" event5   GESTURE_PINCH_BEGIN +5.0s\t 2"), "g b 1")
        upd = " event5   GESTURE_PINCH_UPDATE +5.1s\t 2  0.60/ 0.20 ( 0.60/ 0.20 unaccelerated)  1.05 @ 3.20"
        self.assertEqual(send.parse_libinput_line(upd), "g u 1.05")
        self.assertEqual(send.parse_libinput_line(" event5   GESTURE_PINCH_END +5.2s\t 2"), "g e 1")

    def test_ignored_lines_are_not_suspicious(self):
        for line in ("-event5   DEVICE_ADDED     TPPS/2 IBM TrackPoint",
                     " event5   GESTURE_SWIPE_BEGIN +1.0s\t 3",
                     " event5   POINTER_MOTION_ABSOLUTE +1.0s\t 1.0/ 2.0"):
            self.assertIsNone(send.parse_libinput_line(line))
            self.assertFalse(send.looks_parseable(line), line)

    def test_changed_format_is_noticed(self):
        line = " event5   POINTER_MOTION    +1.23s\t dx=0.87 dy=-1.40"
        self.assertIsNone(send.parse_libinput_line(line))
        self.assertTrue(send.looks_parseable(line))


class Config(unittest.TestCase):
    def test_defaults(self):
        cfg = send.load_config("/nonexistent")
        self.assertEqual(cfg["host"], "tpkbd-pc")
        self.assertIn("TrackPoint", cfg["pointing"])
        self.assertIn(e.KEY_SLEEP, cfg["block_keys"])
        self.assertEqual(cfg["toggle_keys"], {e.KEY_LEFTCTRL, e.KEY_RIGHTCTRL, e.KEY_SPACE})

    def test_override(self):
        with tempfile.NamedTemporaryFile("w", suffix=".conf") as f:
            f.write("[sender]\nkeyboard = Foo, Bar baz\nblock_keys = KEY_A\nheartbeat_s = 0.25\n")
            f.flush()
            cfg = send.load_config(f.name)
        self.assertEqual(cfg["keyboard"], ["Foo", "Bar baz"])
        self.assertEqual(cfg["block_keys"], {e.KEY_A})
        self.assertEqual(cfg["heartbeat_s"], 0.25)

    def test_unknown_key_name(self):
        with tempfile.NamedTemporaryFile("w", suffix=".conf") as f:
            f.write("[sender]\ntoggle_keys = KEY_NOPE\n")
            f.flush()
            with self.assertRaises(ValueError):
                send.load_config(f.name)


class Helpers(unittest.TestCase):
    def test_empty_chord_never_fires(self):
        self.assertFalse(send.chord_active(frozenset(), {1, 2}))
        self.assertTrue(send.chord_active(frozenset({1, 2}), {1, 2, 3}))
        self.assertFalse(send.chord_active(frozenset({1, 2}), {1}))

    def test_release_lines(self):
        self.assertEqual(send.release_lines(set(), set(), 9), [])
        self.assertEqual(send.release_lines({30, 29}, {272}, 9),
                         ["k 1 29 0", "k 1 30 0", "k 0 0 9", "b 272 0 9"])

    def test_rate_limited(self):
        r = send.RateLimited(first=2, every=10)
        self.assertEqual([r.ok(now=t) for t in (100, 101, 102, 105, 111)],
                         [True, True, False, False, True])

    def test_protocol_versions_agree(self):
        recv = load("pc/tpkbd-recv")
        self.assertEqual(send.PROTO, recv.PROTO)


def child(code):
    return [sys.executable, "-I", "-c", code]


class LinkReady(unittest.TestCase):
    def link(self, code):
        link = send.Link(send.load_config("/nonexistent"), argv=child(code))
        link.start()
        self.addCleanup(link.close)
        return link

    def test_ready_in_the_same_chunk_as_other_lines(self):
        link = self.link("import sys; sys.stdout.write('hello\\nREADY 2\\n'); "
                         "sys.stdout.flush(); sys.stdin.read()")
        logged = []
        link.wait_ready(5, log=logged.append)
        self.assertEqual(logged, ["pc: hello"])

    def test_old_receiver_is_named(self):
        link = self.link("import sys; print('READY', flush=True); sys.stdin.read()")
        with self.assertRaisesRegex(send.LinkError, "protocol 1.*re-run pc/install.sh"):
            link.wait_ready(5, log=lambda m: None)

    def test_other_version(self):
        link = self.link("import sys; print('READY 9', flush=True); sys.stdin.read()")
        with self.assertRaisesRegex(send.LinkError, "protocol 9"):
            link.wait_ready(5, log=lambda m: None)

    def test_receiver_error_is_not_swallowed(self):
        link = self.link("print('PermissionError: /dev/uinput', flush=True)")
        logged = []
        with self.assertRaises(send.LinkError):
            link.wait_ready(5, log=logged.append)
        self.assertEqual(logged, ["pc: PermissionError: /dev/uinput"])

    def test_timeout(self):
        link = self.link("import sys; sys.stdin.read()")
        with self.assertRaisesRegex(send.LinkError, "not reachable"):
            link.wait_ready(0.3, log=lambda m: None)

    def test_send_reaches_the_child(self):
        link = self.link("import sys; print('READY 2', flush=True); "
                         "print('got', sys.stdin.readline().strip(), flush=True)")
        link.wait_ready(5, log=lambda m: None)
        link.send(["h 1"])
        logged = []
        while not logged:
            import select
            select.select([link.fd], [], [], 5)
            logged = link.read_lines()
        self.assertEqual(logged, ["got h 1"])


class KeyboardMode(unittest.TestCase):
    def test_keys_are_forwarded_in_batches(self):
        s = make(state="remote")
        tap(s, e.KEY_A, 1)
        tap(s, e.KEY_A, 0)
        self.assertEqual(s.link.sent, ["k 1 30 1", "k 0 0 0", "k 1 30 0", "k 0 0 0"])

    def test_autorepeat_is_dropped(self):
        s = make(state="remote")
        tap(s, e.KEY_A, 2)
        self.assertEqual(s.link.sent, [])

    def test_blocked_keys_stay_local(self):
        s = make(state="remote")
        tap(s, e.KEY_SLEEP, 1)
        self.assertEqual(s.link.sent, [])
        self.assertNotIn(e.KEY_SLEEP, s.forwarded)

    def test_escape_chord_exits_42_and_releases_on_the_pc(self):
        s = make(state="remote")
        tap(s, e.KEY_LEFTCTRL, 1)
        tap(s, e.KEY_RIGHTCTRL, 1)
        with self.assertRaises(SystemExit) as cm:
            tap(s, e.KEY_ESC, 1)
        self.assertEqual(cm.exception.code, 42)
        s.link.sent.clear()
        s.shutdown()
        self.assertEqual(s.link.sent[:2], ["k 1 29 0", "k 1 97 0"])
        self.assertFalse(s.grabbed)

    def test_toggle_chord_does_nothing_in_keyboard_mode(self):
        s = make(state="remote")
        for code in (e.KEY_LEFTCTRL, e.KEY_RIGHTCTRL, e.KEY_SPACE):
            tap(s, code, 1)
        self.assertIsNone(s.want)
        self.assertIn(e.KEY_SPACE, s.forwarded)


class SoftToggle(unittest.TestCase):
    def chord(self, s):
        for code in (e.KEY_LEFTCTRL, e.KEY_RIGHTCTRL, e.KEY_SPACE):
            tap(s, code, 1)

    def release(self, s, *codes):
        for code in codes:
            tap(s, code, 0)

    def test_local_keys_are_not_forwarded(self):
        s = make(soft=True)
        tap(s, e.KEY_A, 1)
        self.assertEqual(s.link.sent, [])

    def test_escape_chord_is_ignored_in_soft_mode(self):
        s = make(soft=True)
        for code in (e.KEY_LEFTCTRL, e.KEY_RIGHTCTRL, e.KEY_ESC):
            tap(s, code, 1)  # must not exit

    def test_grab_waits_until_every_key_is_up(self):
        s = make(soft=True)
        self.chord(s)
        self.assertEqual(s.want, "remote")
        s.apply_toggle()
        self.assertEqual((s.state, s.grabbed), ("local", False))
        self.release(s, e.KEY_SPACE, e.KEY_RIGHTCTRL)
        s.apply_toggle()
        self.assertEqual(s.state, "local")  # Ctrl is still down
        self.release(s, e.KEY_LEFTCTRL)
        s.apply_toggle()
        self.assertEqual((s.state, s.grabbed, s.want), ("remote", True, None))
        self.assertEqual(s.link.sent, [])  # the chord never reached the PC

    def test_back_to_local_releases_what_the_pc_saw(self):
        s = make(soft=True, state="remote")
        tap(s, e.KEY_A, 1)                    # held while the chord is pressed
        s.link.sent.clear()
        self.chord(s)
        self.assertEqual(s.want, "local")
        # the first two chord keys had already reached the PC; all of them are let go,
        # and the completing key (Space) never gets there
        self.assertEqual([x for x in s.link.sent if x.endswith(" 0") and x.startswith("k 1")],
                         ["k 1 29 0", "k 1 30 0", "k 1 97 0"])
        self.assertNotIn("k 1 57 1", s.link.sent)
        self.assertNotIn(e.KEY_SPACE, s.forwarded)
        s.link.sent.clear()
        self.release(s, e.KEY_SPACE, e.KEY_RIGHTCTRL, e.KEY_LEFTCTRL)
        self.assertEqual(s.link.sent, [])     # releases are suppressed while switching
        self.assertEqual(s.state, "remote")   # key A is still down
        self.release(s, e.KEY_A)
        s.apply_toggle()
        self.assertEqual((s.state, s.grabbed), ("local", False))
        self.assertTrue(any(x.startswith("g e 1") for x in s.link.sent))

    def test_mouse_buttons_are_released_when_leaving(self):
        s = make(soft=True, state="remote")
        s.buttons.add(272)
        self.chord(s)
        self.assertIn("b 272 0", " ".join(s.link.sent))
        self.assertEqual(s.buttons, set())

    def test_failed_grab_stays_local(self):
        s = make(soft=True)

        def busy():
            raise OSError("device busy")
        s._grab_all = busy
        logged = []
        send.log, old = logged.append, send.log
        try:
            self.chord(s)
            self.release(s, e.KEY_SPACE, e.KEY_RIGHTCTRL, e.KEY_LEFTCTRL)
            s.apply_toggle()
        finally:
            send.log = old
        self.assertEqual((s.state, s.want), ("local", None))
        self.assertTrue(any("failed" in m for m in logged))

    def test_state_is_published(self):
        s = make(soft=True)
        with tempfile.TemporaryDirectory() as d:
            send.STATE_PATH, old = os.path.join(d, "state"), send.STATE_PATH
            try:
                s.set_state("remote")
                with open(send.STATE_PATH) as f:
                    self.assertEqual(f.read(), "remote\n")
            finally:
                send.STATE_PATH = old


class Heartbeat(unittest.TestCase):
    def test_sent_on_schedule(self):
        s = make()
        s.heartbeat(10.0)
        s.heartbeat(10.5)
        s.heartbeat(11.0)
        self.assertEqual(len(s.link.sent), 2)
        self.assertTrue(all(x.startswith("h ") and len(x.split()) == 2 for x in s.link.sent))


class LibinputPipe(unittest.TestCase):
    def feed(self, s, text):
        r, w = os.pipe()
        s.master = r
        os.write(w, text.encode())
        os.close(w)
        s.handle_libinput()
        os.close(r)
        s.master = None

    def test_lines_become_messages_with_timestamps(self):
        s = make(state="remote")
        self.feed(s, " event5   POINTER_MOTION    +1.0s\t 1.00/ 2.00 ( 1.00/ 2.00 unaccelerated)\n"
                     " event5   POINTER_BUTTON    +1.1s\t BTN_LEFT (272) pressed, seat count: 1\n")
        self.assertEqual([x.rsplit(" ", 1)[0] for x in s.link.sent], ["m 1.00 2.00", "b 272 1"])
        self.assertTrue(all(x.rsplit(" ", 1)[1].isdigit() for x in s.link.sent))
        self.assertEqual(s.buttons, {272})

    def test_format_change_is_logged_not_silent(self):
        s = make(state="remote")
        logged = []
        send.log, old = logged.append, send.log
        try:
            self.feed(s, " event5   POINTER_MOTION    +1.0s\t dx=1 dy=2\n")
        finally:
            send.log = old
        self.assertEqual(s.link.sent, [])
        self.assertEqual(len(logged), 1)
        self.assertIn("unparsed libinput line", logged[0])


if __name__ == "__main__":
    unittest.main()
