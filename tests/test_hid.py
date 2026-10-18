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


class Descriptors(unittest.TestCase):
    def test_report_lengths_match_the_descriptors(self):
        self.assertEqual(input_bytes(hid.KBD_DESC), hid.KBD_REPORT_LEN)
        self.assertEqual(input_bytes(hid.MOUSE_DESC), hid.MOUSE_REPORT_LEN)

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


class MouseReports(unittest.TestCase):
    def setUp(self):
        self.m = hid.Mouse()

    def test_small_move(self):
        self.assertEqual(self.m.moves(5, -3), [bytes([0, 5, 253, 0])])

    def test_no_motion_no_report(self):
        self.assertEqual(self.m.moves(0, 0), [])

    def test_big_move_is_split(self):
        reports = self.m.moves(300, -200)
        self.assertEqual(len(reports), 3)
        total_x = sum(int.from_bytes(r[1:2], "little", signed=True) for r in reports)
        total_y = sum(int.from_bytes(r[2:3], "little", signed=True) for r in reports)
        self.assertEqual((total_x, total_y), (300, -200))
        for r in reports:
            self.assertEqual(len(r), 4)
            self.assertGreater(int.from_bytes(r[1:2], "little", signed=True), -128)

    def test_wheel(self):
        self.assertEqual(self.m.moves(0, 0, -1), [bytes([0, 0, 0, 255])])

    def test_buttons(self):
        self.assertEqual(self.m.button(hid.BTN_LEFT, 1), bytes([1, 0, 0, 0]))
        self.assertEqual(self.m.button(hid.BTN_RIGHT, 1), bytes([3, 0, 0, 0]))
        self.assertEqual(self.m.moves(1, 0), [bytes([3, 1, 0, 0])])     # held while moving
        self.assertEqual(self.m.button(hid.BTN_LEFT, 0), bytes([2, 0, 0, 0]))
        self.assertIsNone(self.m.button(999, 1))

    def test_release_all(self):
        self.m.button(hid.BTN_MIDDLE, 1)
        self.assertEqual(self.m.release_all(), bytes(4))
        self.assertEqual(self.m.moves(1, 1), [bytes([0, 1, 1, 0])])


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
        self.assertEqual(mouse.reports[-1], bytes(4))

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
        self.assertEqual(mouse.reports[-1], bytes(4))

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

    def test_up_writes_both_functions(self):
        self.g.up()
        self.assertEqual(self.read("functions/hid.usb0/protocol"), "1")
        self.assertEqual(self.read("functions/hid.usb0/subclass"), "1")
        self.assertEqual(self.read("functions/hid.usb0/report_length"), "8")
        self.assertEqual(self.read("functions/hid.usb0/report_desc", "rb"), hid.KBD_DESC)
        self.assertEqual(self.read("functions/hid.usb1/protocol"), "2")
        self.assertEqual(self.read("functions/hid.usb1/subclass"), "1")
        self.assertEqual(self.read("functions/hid.usb1/report_length"), "4")
        self.assertEqual(self.read("functions/hid.usb1/report_desc", "rb"), hid.MOUSE_DESC)

    def test_functions_are_linked_into_the_config(self):
        self.g.up()
        for name in ("hid.usb0", "hid.usb1"):
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
        self.assertEqual(sorted(links), ["hid.usb0", "hid.usb1"])

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
        self.assertEqual([o[0] for o in order].count("unlink"), 2)

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
