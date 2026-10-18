import os
import threading
import time
import unittest

from tests.loader import Rec, load

recv = load("pc/tpkbd-recv")
e = recv.e


def make(**over):
    cfg = recv.load_config("/nonexistent")
    cfg.update(jitter_ms=0, **over)
    kbd, ptr, pinch = Rec(), Rec(), Rec()
    rp = recv.Replayer(kbd, ptr, pinch, cfg, sleep=lambda s: None)
    return rp, kbd, ptr, pinch


def feed(rp, *lines):
    for line in lines:
        rp.handle(line)


class Config(unittest.TestCase):
    def test_defaults(self):
        cfg = recv.load_config("/nonexistent")
        self.assertEqual((cfg["scale"], cfg["jitter_ms"], cfg["watchdog_s"], cfg["dead_s"]),
                         (1.25, 15, 3, 30))

    def test_override(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".conf") as f:
            f.write("[receiver]\nscale = 2\njitter_ms = 0\n")
            f.flush()
            cfg = recv.load_config(f.name)
        self.assertEqual((cfg["scale"], cfg["jitter_ms"], cfg["dead_s"]), (2, 0, 30))


class Keyboard(unittest.TestCase):
    def test_batch_is_written_at_the_sync_line(self):
        rp, kbd, *_ = make()
        feed(rp, "k 1 30 1")
        self.assertEqual(kbd.events, [])
        feed(rp, "k 0 0 5")
        self.assertEqual(kbd.events, [(e.EV_KEY, 30, 1), "SYN"])

    def test_heartbeat_and_garbage_are_ignored(self):
        rp, kbd, ptr, pinch = make()
        feed(rp, "h 12345", "", "x 1 2 3", "m 1", "k a b c")
        self.assertEqual((kbd.events, ptr.events, pinch.events), ([], [], []))

    def test_release_all_lets_go_of_held_keys_and_buttons(self):
        rp, kbd, ptr, _ = make()
        feed(rp, "k 1 30 1", "k 0 0 1", "k 1 29 1", "k 0 0 2", "b 272 1 3")
        kbd.clear(); ptr.clear()
        rp.release_all()
        self.assertEqual(kbd.events, [(e.EV_KEY, 29, 0), (e.EV_KEY, 30, 0), "SYN"])
        self.assertEqual(ptr.events, [(e.EV_KEY, 272, 0), "SYN"])
        kbd.clear(); ptr.clear()
        rp.release_all()   # nothing left to release
        self.assertEqual((kbd.events, ptr.events), ([], []))

    def test_released_keys_are_not_released_again(self):
        rp, kbd, *_ = make()
        feed(rp, "k 1 30 1", "k 0 0 1", "k 1 30 0", "k 0 0 2")
        kbd.clear()
        rp.release_all()
        self.assertEqual(kbd.events, [])


class Pointer(unittest.TestCase):
    def test_motion_is_scaled_and_remainders_carry_over(self):
        rp, _, ptr, _ = make(scale=1.5)
        feed(rp, "m 1 0 1", "m 1 0 2")   # 1.5 then 3.0 in total -> 1, then 2 more
        moves = [ev[2] for ev in ptr.events if ev != "SYN" and ev[1] == e.REL_X]
        self.assertEqual(moves, [1, 2])

    def test_button(self):
        rp, _, ptr, _ = make()
        feed(rp, "b 272 1 1", "b 272 0 2")
        self.assertEqual(ptr.events, [(e.EV_KEY, 272, 1), "SYN", (e.EV_KEY, 272, 0), "SYN"])

    def test_scroll_down_is_negative_wheel(self):
        rp, _, ptr, _ = make()
        feed(rp, "s 15 0 1")   # one wheel click down
        self.assertIn((e.EV_REL, e.REL_WHEEL_HI_RES, -120), ptr.events)
        self.assertIn((e.EV_REL, e.REL_WHEEL, -1), ptr.events)


class Pinch(unittest.TestCase):
    def ids(self, pinch):
        return [ev[2] for ev in pinch.events
                if ev != "SYN" and ev[1] == e.ABS_MT_TRACKING_ID]

    def xs(self, pinch):
        return [ev[2] for ev in pinch.events if ev != "SYN" and ev[1] == e.ABS_MT_POSITION_X]

    def test_begin_update_end(self):
        rp, _, _, pinch = make()
        feed(rp, "g b 1 1")
        self.assertTrue(rp.pinching)
        self.assertEqual(self.xs(pinch), [recv.CX - 400, recv.CX + 400])
        pinch.clear()
        feed(rp, "g u 2.0 2")
        self.assertEqual(self.xs(pinch), [recv.CX - 800, recv.CX + 800])
        pinch.clear()
        feed(rp, "g e 1 3")
        self.assertFalse(rp.pinching)
        self.assertEqual(self.ids(pinch), [-1, -1])

    def test_update_without_begin_is_ignored(self):
        rp, _, _, pinch = make()
        feed(rp, "g u 2.0 1")
        self.assertEqual(pinch.events, [])

    def test_long_pinch_reseats_instead_of_stalling(self):
        rp, _, _, pinch = make()
        feed(rp, "g b 1 1", "g u 4.0 2")
        pinch.clear()
        feed(rp, "g u 6.0 3")      # past the edge of the fake touchpad
        ids = self.ids(pinch)
        self.assertEqual(ids[:2], [-1, -1])        # fingers lifted ...
        self.assertTrue(all(i >= 0 for i in ids[2:4]))   # ... and put down again
        self.assertTrue(rp.pinching)
        pinch.clear()
        feed(rp, "g u 7.5 4")      # 1.25x since the re-seat: the fingers keep moving
        xs = self.xs(pinch)
        self.assertEqual(xs, [recv.CX - 500, recv.CX + 500])

    def test_release_all_ends_a_pinch(self):
        rp, _, _, pinch = make()
        feed(rp, "g b 1 1")
        rp.release_all()
        self.assertFalse(rp.pinching)


class Serve(unittest.TestCase):
    """serve() on a real pipe: heartbeat, silence and EOF."""

    def run_serve(self, rp, watchdog, dead):
        r, w = os.pipe()
        t = threading.Thread(target=recv.serve, args=(rp, r, watchdog, dead), daemon=True)
        t.start()
        self.addCleanup(lambda: (os.close(r),))
        return w, t

    def test_silence_releases_keys_then_exits(self):
        rp, kbd, *_ = make()
        w, t = self.run_serve(rp, 0.15, 0.6)
        os.write(w, b"k 1 30 1\nk 0 0 1\n")
        time.sleep(0.05)
        self.assertEqual(rp.keys_down, {30})
        time.sleep(0.25)                       # past the watchdog, before "dead"
        self.assertEqual(rp.keys_down, set())
        self.assertIn((e.EV_KEY, 30, 0), kbd.events)
        self.assertTrue(t.is_alive())          # still waiting for the sender
        t.join(2)
        self.assertFalse(t.is_alive())         # gave up after dead_s
        os.close(w)

    def test_heartbeats_keep_a_held_key_down(self):
        rp, kbd, *_ = make()
        w, t = self.run_serve(rp, 0.2, 5)
        os.write(w, b"k 1 30 1\nk 0 0 1\n")
        for _ in range(8):
            time.sleep(0.05)
            os.write(w, b"h 1\n")
        self.assertEqual(rp.keys_down, {30})   # 0.4 s without events, but heartbeats
        os.close(w)
        t.join(2)
        self.assertFalse(t.is_alive())         # EOF: the sender closed the connection
        self.assertEqual(rp.keys_down, set())  # and everything was let go

    def test_lines_split_across_reads(self):
        rp, kbd, *_ = make()
        w, t = self.run_serve(rp, 5, 10)
        os.write(w, b"k 1 3")
        time.sleep(0.05)
        os.write(w, b"0 1\nk 0 0 1\n")
        time.sleep(0.1)
        self.assertEqual(rp.keys_down, {30})
        os.close(w)
        t.join(2)


if __name__ == "__main__":
    unittest.main()
