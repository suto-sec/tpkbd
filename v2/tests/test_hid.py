import errno
import os
import tempfile
import unittest
from unittest import mock

from tests.loader import load

hid = load("pi/tpkbd-hid")


def input_bytes(desc):
    """Size in bytes of the input report a HID report descriptor declares."""
    size = count = bits = 0
    i = 0
    while i < len(desc):
        prefix = desc[i]
        n = (0, 1, 2, 4)[prefix & 3]
        kind, tag = (prefix >> 2) & 3, prefix >> 4
        if kind == 1 and tag == 7:
            size = desc[i + 1]
        elif kind == 1 and tag == 9:
            count = desc[i + 1]
        elif kind == 0 and tag == 8:    # Input
            bits += size * count
        i += 1 + n
    return bits // 8


def walk(desc):
    """Every Input item of a short-item HID report descriptor, with the global state it saw."""
    glob, local, depth, items = {}, {}, 0, []
    i = 0
    while i < len(desc):
        prefix = desc[i]
        n = (0, 1, 2, 4)[prefix & 3]
        raw = desc[i + 1:i + 1 + n]
        kind, tag = (prefix >> 2) & 3, prefix >> 4
        value = int.from_bytes(raw, "little", signed=True) if n else 0
        if kind == 1:
            name = {0: "page", 1: "lmin", 2: "lmax", 3: "pmin", 4: "pmax", 5: "exp", 6: "unit",
                    7: "size", 9: "count"}.get(tag)
            if name == "exp":
                value = (value & 0xF) - 16 if value & 0x8 else value & 0xF
            if name:
                glob[name] = value
        elif kind == 2 and tag == 0:
            local.setdefault("usages", []).append(value)
        elif kind == 0:
            if tag == 8:
                items.append({**glob, **local})
            elif tag == 0xA:
                depth += 1
            elif tag == 0xC:
                depth -= 1
                assert depth >= 0, "unbalanced End Collection"
            local = {}
        i += 1 + n
    assert depth == 0, "a collection is never closed"
    return items


class TouchDescriptor(unittest.TestCase):
    def test_report_length(self):
        self.assertEqual(input_bytes(hid.TOUCH_DESC), hid.TOUCH_REPORT_LEN)

    def test_layout_is_two_fingers_a_count_and_a_button(self):
        items = walk(hid.TOUCH_DESC)
        shape = [(it.get("usages", []), it["size"], it["count"]) for it in items]
        finger = [([0x42], 1, 1), ([], 3, 1), ([0x51], 4, 1), ([0x30], 16, 1), ([0x31], 16, 1)]
        self.assertEqual(shape, finger + finger + [([0x54], 8, 1), ([1], 1, 1), ([], 7, 1)])

    def test_the_pad_is_100_by_65_mm_at_40_units_per_mm(self):
        x, y = walk(hid.TOUCH_DESC)[3:5]
        for axis, logical, physical in ((x, hid.TOUCH_W, 100), (y, hid.TOUCH_H, 65)):
            self.assertEqual((axis["lmin"], axis["lmax"]), (0, logical))
            self.assertEqual((axis["pmin"], axis["pmax"]), (0, physical))
            self.assertEqual((axis["unit"], axis["exp"]), (0x11, -1))      # centimetres * 10^-1
            self.assertEqual(logical / physical, 40)

    def test_units_do_not_leak_into_the_contact_count(self):
        count = walk(hid.TOUCH_DESC)[10]
        self.assertEqual((count["pmin"], count["pmax"], count["unit"], count["exp"]), (0, 0, 0, 0))
        self.assertEqual(count["lmax"], 2)

    def test_it_is_a_touch_pad_application(self):
        self.assertEqual(hid.TOUCH_DESC[:6], bytes([0x05, 0x0D, 0x09, 0x05, 0xA1, 0x01]))
        self.assertEqual(hid.TOUCH_DESC[-1], 0xC0)


class TouchpadReports(unittest.TestCase):
    def test_fingers_down_side_by_side(self):
        pad = hid.Touchpad()
        r = pad.begin(400)
        self.assertEqual(len(r), hid.TOUCH_REPORT_LEN)
        self.assertEqual(r[0], 0x01)                                        # tip down, contact 0
        self.assertEqual(int.from_bytes(r[1:3], "little"), 2000 - 400)
        self.assertEqual(int.from_bytes(r[3:5], "little"), 1300)
        self.assertEqual(r[5], 0x11)                                        # tip down, contact 1
        self.assertEqual(int.from_bytes(r[6:8], "little"), 2000 + 400)
        self.assertEqual(int.from_bytes(r[8:10], "little"), 1300)
        self.assertEqual(r[10:], bytes([2, 0]))                             # two contacts, no button

    def test_move_changes_only_the_distance(self):
        pad = hid.Touchpad()
        pad.begin(400)
        r = pad.move(800)
        self.assertEqual(int.from_bytes(r[1:3], "little"), 1200)
        self.assertEqual(int.from_bytes(r[6:8], "little"), 2800)

    def test_the_fingers_stay_on_the_pad(self):
        pad = hid.Touchpad()
        r = pad.move(10 ** 6)
        self.assertEqual(int.from_bytes(r[6:8], "little"), 2000 + hid.TOUCH_MAX_HALF)
        r = pad.move(0)
        self.assertEqual(int.from_bytes(r[6:8], "little"), 2000 + hid.TOUCH_MIN_HALF)

    def test_end_lifts_both_fingers_where_they_were(self):
        pad = hid.Touchpad()
        pad.begin(400)
        pad.move(600)
        r = pad.end()
        self.assertEqual((r[0], r[5]), (0x00, 0x10))                        # tips up, same contacts
        self.assertEqual(int.from_bytes(r[1:3], "little"), 1400)
        self.assertEqual(r[10:], bytes([2, 0]))

    def test_end_without_fingers_down_sends_nothing(self):
        pad = hid.Touchpad()
        self.assertIsNone(pad.end())
        pad.begin(400)
        pad.end()
        self.assertIsNone(pad.end())


class PinchTest(unittest.TestCase):
    def run_it(self, **kw):
        out = Recorder()
        hid.run_pinch_test(out, sleep=lambda s: None, log=lambda m: None, **kw)
        return out

    def test_spreads_then_pinches_then_lifts(self):
        reports = self.run_it(countdown=0).reports
        halves = [(int.from_bytes(r[6:8], "little") - 2000) for r in reports]
        self.assertEqual(halves[0], 400)
        self.assertEqual(max(halves), 1200)         # 3x
        self.assertEqual(halves.index(1200) < len(halves) - 3, True)
        self.assertEqual(reports[-1][0], 0x00)      # lifted at the end
        self.assertEqual(reports[-2][0], 0x01)

    def test_lifts_even_if_interrupted(self):
        out = Recorder()
        calls = []

        def sleep(s):
            calls.append(s)
            if len(calls) == 10:
                raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            hid.run_pinch_test(out, countdown=0, sleep=sleep, log=lambda m: None)
        self.assertEqual(out.reports[-1][0], 0x00)


class Descriptors(unittest.TestCase):
    def test_report_lengths_match_the_descriptors(self):
        self.assertEqual(input_bytes(hid.KBD_DESC), hid.KBD_REPORT_LEN)
        self.assertEqual(input_bytes(hid.MOUSE_DESC), hid.MOUSE_REPORT_LEN)
        self.assertEqual(input_bytes(hid.CONSUMER_DESC), hid.CONSUMER_REPORT_LEN)

    def test_descriptors_are_closed(self):
        self.assertEqual(hid.KBD_DESC[-1], 0xC0)
        self.assertEqual(hid.MOUSE_DESC[-2:], bytes([0xC0, 0xC0]))

    def test_keyboard_report_is_the_boot_layout(self):
        # modifiers, reserved, six slots
        self.assertEqual(len(hid.Keyboard().report()), 8)


class KeyMap(unittest.TestCase):
    def test_known_keys(self):
        u = hid.KEY_USAGE
        self.assertEqual(u[30], 0x04)       # A
        self.assertEqual(u[44], 0x1D)       # Z
        self.assertEqual(u[2], 0x1E)        # 1
        self.assertEqual(u[11], 0x27)       # 0
        self.assertEqual(u[28], 0x28)       # Enter
        self.assertEqual(u[1], 0x29)        # Esc
        self.assertEqual(u[57], 0x2C)       # Space
        self.assertEqual(u[59], 0x3A)       # F1
        self.assertEqual(u[88], 0x45)       # F12
        self.assertEqual(u[103], 0x52)      # Up
        self.assertEqual(u[108], 0x51)      # Down

    def test_letters_digits_and_function_keys_are_all_there(self):
        usages = set(hid.KEY_USAGE.values())
        for usage in list(range(0x04, 0x28)) + list(range(0x3A, 0x46)):
            self.assertIn(usage, usages)

    def test_no_two_keys_share_a_usage(self):
        values = list(hid.KEY_USAGE.values())
        self.assertEqual(len(values), len(set(values)))

    def test_modifiers_are_not_key_slots(self):
        self.assertFalse(set(hid.MODIFIER_BITS) & set(hid.KEY_USAGE))
        self.assertEqual(sorted(hid.MODIFIER_BITS.values()), [1 << n for n in range(8)])

    def test_every_typeable_character(self):
        for ch in "abcdefghijklmnopqrstuvwxyz ":
            self.assertIn(ch, hid.CHAR_KEY)


class KeyboardReports(unittest.TestCase):
    def setUp(self):
        self.kb = hid.Keyboard()

    def test_idle_report(self):
        self.assertEqual(self.kb.report(), bytes(8))

    def test_press_and_release(self):
        self.assertTrue(self.kb.event(30, 1))
        self.assertEqual(self.kb.report(), bytes([0, 0, 0x04, 0, 0, 0, 0, 0]))
        self.assertTrue(self.kb.event(30, 0))
        self.assertEqual(self.kb.report(), bytes(8))

    def test_modifiers_go_in_the_first_byte(self):
        self.kb.event(29, 1)    # left ctrl
        self.kb.event(54, 1)    # right shift
        self.kb.event(30, 1)
        self.assertEqual(self.kb.report(), bytes([0x01 | 0x20, 0, 0x04, 0, 0, 0, 0, 0]))
        self.kb.event(29, 0)
        self.assertEqual(self.kb.report()[0], 0x20)

    def test_keys_keep_press_order(self):
        for code in (32, 30, 31):   # D A S
            self.kb.event(code, 1)
        self.assertEqual(self.kb.report()[2:5], bytes([0x07, 0x04, 0x16]))
        self.kb.event(30, 0)
        self.assertEqual(self.kb.report()[2:5], bytes([0x07, 0x16, 0]))

    def test_repeats_and_unknown_keys_change_nothing(self):
        self.kb.event(30, 1)
        self.assertFalse(self.kb.event(30, 2))
        self.assertFalse(self.kb.event(30, 1))
        self.assertFalse(self.kb.event(113, 1))     # KEY_MUTE: not in the boot report
        self.assertEqual(self.kb.report(), bytes([0, 0, 0x04, 0, 0, 0, 0, 0]))

    def test_release_of_a_key_never_pressed(self):
        self.assertFalse(self.kb.event(30, 0))
        self.assertFalse(self.kb.event(29, 0))

    def test_six_keys_fit(self):
        for code in (30, 31, 32, 33, 34, 35):
            self.kb.event(code, 1)
        self.assertEqual(self.kb.report()[2:], bytes([0x04, 0x16, 0x07, 0x09, 0x0A, 0x0B]))

    def test_seventh_key_reports_rollover_and_recovers(self):
        for code in (30, 31, 32, 33, 34, 35, 36):
            self.kb.event(code, 1)
        self.assertEqual(self.kb.report(), bytes([0, 0] + [1] * 6))
        self.kb.event(36, 0)
        self.assertEqual(self.kb.report()[2:], bytes([0x04, 0x16, 0x07, 0x09, 0x0A, 0x0B]))

    def test_modifier_alone_with_many_keys_keeps_modifiers(self):
        self.kb.event(42, 1)
        for code in (30, 31, 32, 33, 34, 35, 36):
            self.kb.event(code, 1)
        self.assertEqual(self.kb.report()[:2], bytes([0x02, 0]))

    def test_release_all(self):
        self.kb.event(29, 1)
        self.kb.event(30, 1)
        self.assertEqual(self.kb.release_all(), bytes(8))
        self.assertEqual(self.kb.report(), bytes(8))


class ConsumerReports(unittest.TestCase):
    def setUp(self):
        self.c = hid.Consumer()

    def test_idle(self):
        self.assertEqual(self.c.report(), bytes(2))

    def test_press_and_release_volume_up(self):
        self.assertTrue(self.c.event(115, 1))
        self.assertEqual(self.c.report(), bytes([0xE9, 0]))
        self.assertTrue(self.c.event(115, 0))
        self.assertEqual(self.c.report(), bytes(2))

    def test_two_byte_usage_is_little_endian(self):
        self.c.event(140, 1)    # calculator, usage 0x0192
        self.assertEqual(self.c.report(), bytes([0x92, 0x01]))

    def test_latest_key_wins_and_the_older_one_comes_back(self):
        self.c.event(114, 1)
        self.c.event(115, 1)
        self.assertEqual(self.c.report(), bytes([0xE9, 0]))
        self.c.event(115, 0)
        self.assertEqual(self.c.report(), bytes([0xEA, 0]))

    def test_repeats_and_other_keys_change_nothing(self):
        self.c.event(115, 1)
        self.assertFalse(self.c.event(115, 2))
        self.assertFalse(self.c.event(30, 1))       # KEY_A is not a media key
        self.assertFalse(self.c.event(113, 0))      # mute was never pressed

    def test_release_all(self):
        self.c.event(113, 1)
        self.assertEqual(self.c.release_all(), bytes(2))

    def test_no_media_key_is_also_a_keyboard_key(self):
        self.assertFalse(set(hid.CONSUMER_USAGE) & set(hid.KEY_USAGE))
        self.assertFalse(set(hid.CONSUMER_USAGE) & set(hid.MODIFIER_BITS))


class VirtualModifiers(unittest.TestCase):
    def test_a_held_virtual_ctrl_shows_in_the_report(self):
        kb = hid.Keyboard()
        kb.virtual_mods = 0x01
        self.assertEqual(kb.report(), bytes([0x01, 0, 0, 0, 0, 0, 0, 0]))

    def test_it_combines_with_real_modifiers(self):
        kb = hid.Keyboard()
        kb.event(42, 1)     # left shift
        kb.virtual_mods = 0x01
        self.assertEqual(kb.report()[0], 0x03)

    def test_release_all_drops_it(self):
        kb = hid.Keyboard()
        kb.virtual_mods = 0x01
        self.assertEqual(kb.release_all(), bytes(8))
        self.assertEqual(kb.virtual_mods, 0)


class MouseReports(unittest.TestCase):
    def setUp(self):
        self.m = hid.Mouse()

    def test_small_move(self):
        self.assertEqual(self.m.moves(5, -3), [bytes([0, 5, 253, 0, 0])])

    def test_no_motion_no_report(self):
        self.assertEqual(self.m.moves(0, 0), [])

    def test_big_move_is_split(self):
        reports = self.m.moves(300, -200)
        self.assertEqual(len(reports), 3)
        total_x = sum(int.from_bytes(r[1:2], "little", signed=True) for r in reports)
        total_y = sum(int.from_bytes(r[2:3], "little", signed=True) for r in reports)
        self.assertEqual((total_x, total_y), (300, -200))
        for r in reports:
            self.assertEqual(len(r), 5)
            self.assertGreater(int.from_bytes(r[1:2], "little", signed=True), -128)

    def test_wheel(self):
        self.assertEqual(self.m.moves(0, 0, -1), [bytes([0, 0, 0, 255, 0])])

    def test_buttons(self):
        self.assertEqual(self.m.button(hid.BTN_LEFT, 1), bytes([1, 0, 0, 0, 0]))
        self.assertEqual(self.m.button(hid.BTN_RIGHT, 1), bytes([3, 0, 0, 0, 0]))
        self.assertEqual(self.m.moves(1, 0), [bytes([3, 1, 0, 0, 0])])     # held while moving
        self.assertEqual(self.m.button(hid.BTN_LEFT, 0), bytes([2, 0, 0, 0, 0]))
        self.assertIsNone(self.m.button(999, 1))

    def test_horizontal_wheel(self):
        self.assertEqual(self.m.moves(0, 0, 0, 2), [bytes([0, 0, 0, 0, 2])])
        self.assertEqual(self.m.moves(0, 0, 0, -1), [bytes([0, 0, 0, 0, 255])])

    def test_wheel_and_pan_together_and_split(self):
        reports = self.m.moves(0, 0, 200, -130)
        self.assertEqual(len(reports), 2)
        self.assertEqual(sum(int.from_bytes(r[3:4], "little", signed=True) for r in reports), 200)
        self.assertEqual(sum(int.from_bytes(r[4:5], "little", signed=True) for r in reports), -130)

    def test_release_all(self):
        self.m.button(hid.BTN_MIDDLE, 1)
        self.assertEqual(self.m.release_all(), bytes(5))
        self.assertEqual(self.m.moves(1, 1), [bytes([0, 1, 1, 0, 0])])


class HidOutTests(unittest.TestCase):
    def test_writes_a_report(self):
        r, w = os.pipe()
        try:
            self.assertTrue(hid.HidOut(w).send(b"12345678"))
            self.assertEqual(os.read(r, 100), b"12345678")
        finally:
            os.close(r)
            os.close(w)

    def test_a_host_that_stopped_reading_does_not_hang_us(self):
        r, w = os.pipe()
        os.set_blocking(w, False)
        try:
            out = hid.HidOut(w)
            while True:
                try:
                    os.write(w, bytes(4096))
                except BlockingIOError:
                    break
            started = hid.time.monotonic()
            self.assertFalse(out.send(b"12345678", timeout=0.1))
            self.assertLess(hid.time.monotonic() - started, 1.0)
        finally:
            os.close(r)
            os.close(w)

    def test_no_host_connected(self):
        out = hid.HidOut(-1)
        for err in (errno.ESHUTDOWN, errno.ENODEV, errno.EPIPE):
            with mock.patch.object(hid.os, "write", side_effect=OSError(err, "x")):
                self.assertFalse(out.send(b"12345678"))

    def test_other_errors_are_raised(self):
        with mock.patch.object(hid.os, "write", side_effect=OSError(errno.EIO, "x")):
            with self.assertRaises(OSError):
                hid.HidOut(-1).send(b"1")

    def test_open_failure_is_a_clear_error(self):
        with self.assertRaisesRegex(hid.HidError, "gadget up"):
            hid.HidOut.open("/nonexistent/hidg0")


class Recorder:
    def __init__(self, ok=True):
        self.reports = []
        self.ok = ok

    def send(self, report, timeout=0.5):
        self.reports.append(report)
        return self.ok


class SelfTest(unittest.TestCase):
    def run_it(self, kbd, mouse, **kw):
        hid.run_test(kbd, mouse, sleep=lambda s: None, log=lambda m: None, **kw)

    def test_types_the_text(self):
        kbd, mouse = Recorder(), Recorder()
        self.run_it(kbd, mouse, text="Ab ", countdown=0)
        r = kbd.reports
        # shift down, A down, A up, shift up, B down, B up, space down, space up, all-released
        self.assertEqual(r[0], bytes([0x02, 0, 0, 0, 0, 0, 0, 0]))
        self.assertEqual(r[1], bytes([0x02, 0, 0x04, 0, 0, 0, 0, 0]))
        self.assertEqual(r[2], bytes([0x02, 0, 0, 0, 0, 0, 0, 0]))
        self.assertEqual(r[3], bytes(8))
        self.assertEqual(r[4], bytes([0, 0, 0x05, 0, 0, 0, 0, 0]))
        self.assertEqual(r[6], bytes([0, 0, 0x2C, 0, 0, 0, 0, 0]))

    def test_always_ends_with_everything_released(self):
        kbd, mouse = Recorder(), Recorder()
        self.run_it(kbd, mouse, countdown=0)
        self.assertEqual(kbd.reports[-1], bytes(8))
        self.assertEqual(mouse.reports[-1], bytes(5))

    def test_the_pointer_comes_back_to_where_it_started(self):
        kbd, mouse = Recorder(), Recorder()
        self.run_it(kbd, mouse, countdown=0)
        x = y = wheel = 0
        for r in mouse.reports:
            dx, dy, dw = (int.from_bytes(r[i:i + 1], "little", signed=True) for i in (1, 2, 3))
            x, y, wheel = x + dx, y + dy, wheel + dw
        self.assertEqual((x, y, wheel), (0, 0, 0))

    def test_releases_even_when_the_host_stops_answering(self):
        kbd, mouse = Recorder(ok=False), Recorder()
        with self.assertRaisesRegex(hid.HidError, "isn't reading"):
            self.run_it(kbd, mouse, countdown=0)
        self.assertEqual(kbd.reports[-1], bytes(8))
        self.assertEqual(mouse.reports[-1], bytes(5))

    def test_rejects_characters_it_cannot_type(self):
        with self.assertRaisesRegex(hid.HidError, "can't type"):
            self.run_it(Recorder(), Recorder(), text="a!", countdown=0)


class FakeGadgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.configfs = os.path.join(self.tmp.name, "config")
        self.udc_dir = os.path.join(self.tmp.name, "udc")
        os.makedirs(os.path.join(self.configfs, "usb_gadget"))
        os.makedirs(os.path.join(self.udc_dir, "b.usb"))
        os.makedirs(os.path.join(self.udc_dir, "a.usb"))
        with open(os.path.join(self.udc_dir, "a.usb", "state"), "w") as f:
            f.write("configured\n")
        self.g = hid.Gadget(self.configfs, self.udc_dir, rmtree=True)

    def read(self, rel, mode="r"):
        with open(os.path.join(self.g.root, rel), mode) as f:
            return f.read()

    def test_up_writes_all_three_functions(self):
        self.g.up()
        self.assertEqual(self.read("functions/hid.usb0/protocol"), "1")
        self.assertEqual(self.read("functions/hid.usb0/subclass"), "1")
        self.assertEqual(self.read("functions/hid.usb0/report_length"), "8")
        self.assertEqual(self.read("functions/hid.usb0/report_desc", "rb"), hid.KBD_DESC)
        self.assertEqual(self.read("functions/hid.usb1/protocol"), "2")
        self.assertEqual(self.read("functions/hid.usb1/subclass"), "1")
        self.assertEqual(self.read("functions/hid.usb1/report_length"), "5")
        self.assertEqual(self.read("functions/hid.usb1/report_desc", "rb"), hid.MOUSE_DESC)
        # media keys: a plain (non-boot) interface
        self.assertEqual(self.read("functions/hid.usb2/protocol"), "0")
        self.assertEqual(self.read("functions/hid.usb2/subclass"), "0")
        self.assertEqual(self.read("functions/hid.usb2/report_length"), "2")
        self.assertEqual(self.read("functions/hid.usb2/report_desc", "rb"), hid.CONSUMER_DESC)

    def test_the_touchpad_is_the_fourth_function(self):
        self.g.up()
        self.assertEqual(self.read("functions/hid.usb3/protocol"), "0")
        self.assertEqual(self.read("functions/hid.usb3/subclass"), "0")
        self.assertEqual(self.read("functions/hid.usb3/report_length"), "12")
        self.assertEqual(self.read("functions/hid.usb3/report_desc", "rb"), hid.TOUCH_DESC)

    def test_only_the_keyboard_keeps_an_out_endpoint(self):
        self.g.up()
        self.assertFalse(os.path.exists(os.path.join(self.g.root, "functions/hid.usb0/no_out_endpoint")))
        for name in ("hid.usb1", "hid.usb2", "hid.usb3"):
            self.assertEqual(self.read(f"functions/{name}/no_out_endpoint"), "1")

    def test_a_kernel_without_no_out_endpoint_is_fine(self):
        real_put = self.g._put

        def put(rel, value):
            if rel.endswith("no_out_endpoint"):
                raise FileNotFoundError(rel)
            return real_put(rel, value)

        self.g._put = put
        self.g.up()
        self.assertEqual(self.read("UDC"), "a.usb")

    def test_without_the_touchpad_when_the_controller_refuses(self):
        real_put = self.g._put
        tries = []

        def put(rel, value):
            if rel == "UDC" and value == "a.usb":
                tries.append(os.path.exists(os.path.join(self.g.root, "functions/hid.usb3")))
                if len(tries) == 1:
                    raise OSError(errno.ENOMEM, "out of endpoints")
            return real_put(rel, value)

        self.g._put = put
        with mock.patch.object(hid.sys, "stderr"):
            self.g.up()
        self.assertEqual(tries, [True, False])
        self.assertEqual(self.read("UDC"), "a.usb")
        self.assertFalse(os.path.exists(os.path.join(self.g.root, "functions/hid.usb3")))
        self.assertTrue(os.path.islink(os.path.join(self.g.root, "configs/c.1/hid.usb2")))

    def test_a_failure_without_the_touchpad_is_reported(self):
        real_put = self.g._put

        def put(rel, value):
            if rel == "UDC" and value == "a.usb":
                raise OSError(errno.EBUSY, "busy")
            return real_put(rel, value)

        self.g._put = put
        with mock.patch.object(hid.sys, "stderr"), self.assertRaises(OSError):
            self.g.up()

    def test_functions_are_linked_into_the_config(self):
        self.g.up()
        for name in ("hid.usb0", "hid.usb1", "hid.usb2", "hid.usb3"):
            link = os.path.join(self.g.root, "configs", "c.1", name)
            self.assertTrue(os.path.islink(link))
            self.assertEqual(os.readlink(link), os.path.join(self.g.root, "functions", name))

    def test_binds_the_first_controller(self):
        self.g.up()
        self.assertEqual(self.read("UDC"), "a.usb")

    def test_ids_and_power(self):
        self.g.up()
        self.assertEqual(self.read("idVendor"), "0x1d6b")
        self.assertEqual(self.read("configs/c.1/MaxPower"), "100")
        self.assertEqual(self.read("configs/c.1/bmAttributes"), "0xA0")

    def test_up_twice_is_fine(self):
        self.g.up()
        self.g.up()
        self.assertEqual(self.read("UDC"), "a.usb")
        links = [n for n in os.listdir(os.path.join(self.g.root, "configs", "c.1"))
                 if n.startswith("hid.")]
        self.assertEqual(sorted(links), ["hid.usb0", "hid.usb1", "hid.usb2", "hid.usb3"])

    def test_down_removes_it(self):
        self.g.up()
        self.g.down()
        self.assertFalse(os.path.exists(self.g.root))
        self.assertEqual(self.g.status(), "down")
        self.g.down()   # and again is fine

    def test_down_unbinds_before_removing(self):
        self.g.up()
        order = []
        real_put = self.g._put
        self.g._put = lambda rel, value: (order.append((rel, value)), real_put(rel, value))
        real_unlink = os.unlink

        def unlink(path, *a, **kw):
            if os.path.basename(path).startswith("hid."):
                order.append(("unlink", path))
            real_unlink(path, *a, **kw)

        with mock.patch.object(hid.os, "unlink", side_effect=unlink):
            self.g.down()
        self.assertEqual(order[0], ("UDC", "\n"))
        self.assertEqual([o[0] for o in order].count("unlink"), 4)

    def test_status(self):
        self.assertEqual(self.g.status(), "down")
        self.g.up()
        self.assertEqual(self.g.status(), "a.usb: configured")

    def test_status_when_not_bound(self):
        self.g.up()
        self.g._put("UDC", "\n")
        self.assertIn("not bound", self.g.status())

    def test_no_controller_is_explained(self):
        os.remove(os.path.join(self.udc_dir, "a.usb", "state"))
        os.rmdir(os.path.join(self.udc_dir, "a.usb"))
        os.rmdir(os.path.join(self.udc_dir, "b.usb"))
        with self.assertRaisesRegex(hid.GadgetError, "dtoverlay=dwc2"):
            self.g.up()

    def test_missing_configfs_is_explained(self):
        os.rmdir(os.path.join(self.configfs, "usb_gadget"))
        with self.assertRaisesRegex(hid.GadgetError, "libcomposite"):
            self.g.up()


if __name__ == "__main__":
    unittest.main()
