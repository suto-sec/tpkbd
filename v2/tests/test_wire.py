"""The UART link end to end: the sender's SerialLink and the receiver's serve loop,
joined by a pseudo-terminal that stands in for the wire."""
import os
import pty
import threading
import time
import unittest
from unittest import mock

from tests.loader import load

recv = load("pi/tpkbd-recv")
try:
    send = load("../v1/thinkpad/tpkbd-send")
except ImportError:     # python-evdev isn't installed
    send = None

CFG = {"scale": 1.0, "watchdog_s": 0.3, "dead_s": 0}


class FakeOut:
    def __init__(self):
        self.reports = []

    def send(self, report, timeout=0.5):
        self.reports.append(report)
        return True


@unittest.skipIf(send is None, "needs python-evdev")
class Wire(unittest.TestCase):
    def setUp(self):
        self.master, slave = pty.openpty()
        os.set_blocking(self.master, False)
        self.port = os.ttyname(slave)
        self.slave = slave
        self.kbd, self.mouse = FakeOut(), FakeOut()
        self.threads = []
        self.link = None

    def stop_receivers(self):
        for t in self.threads:
            t.join(3)
            assert not t.is_alive()
        self.threads.clear()

    def tearDown(self):
        if self.link is not None:
            self.link.close()
        os.close(self.slave)        # the receiver's next read fails, so serve returns
        self.stop_receivers()       # before the descriptor number can be reused
        os.close(self.master)

    def cfg(self, **kw):
        c = send.load_config("/nonexistent")
        c.update(link="serial", serial_port=self.port, baud=115200, **kw)
        return c

    def start_receiver(self):
        def reply(text):
            os.write(self.master, (text + "\n").encode())

        rp = recv.Replayer(self.kbd, self.mouse, CFG, reply=reply)
        t = threading.Thread(target=recv.serve, args=(rp, self.master, CFG["watchdog_s"], 0),
                             daemon=True)
        t.start()
        self.threads.append(t)

    def connect(self):
        self.link = send.make_link(self.cfg())
        self.link.start()
        self.link.USB_WAIT_S = 0    # the tests' receiver has a short watchdog and says no `usb`
        self.link.wait_ready(5, log=print)

    def wait_for(self, cond, secs=3):
        end = time.monotonic() + secs
        while time.monotonic() < end:
            if cond():
                return True
            time.sleep(0.01)
        return False

    def test_make_link_picks_serial(self):
        self.assertIsInstance(send.make_link(self.cfg()), send.SerialLink)
        self.assertNotIsInstance(send.make_link(send.load_config("/nonexistent")), send.SerialLink)

    def test_handshake_then_keys_arrive(self):
        self.start_receiver()
        self.connect()
        self.assertTrue(self.link.started)
        self.link.send(["k 1 30 1", "k 0 0 1", "k 1 30 0", "k 0 0 2", "b 272 1 3"])
        self.assertTrue(self.wait_for(lambda: len(self.kbd.reports) == 2 and self.mouse.reports))
        self.assertEqual(self.kbd.reports, [bytes([0, 0, 0x04, 0, 0, 0, 0, 0]), bytes(8)])
        self.assertEqual(self.mouse.reports, [bytes([1, 0, 0, 0, 0])])

    def test_receiver_started_late_still_answers(self):
        # the sender keeps saying hello until somebody listens
        self.link = send.make_link(self.cfg())
        self.link.start()
        threading.Timer(0.8, self.start_receiver).start()
        self.link.wait_ready(5, log=print)

    def test_heartbeat_answers_are_swallowed(self):
        self.start_receiver()
        self.connect()
        self.link.send(["h 1", "h 2"])
        self.assertTrue(self.wait_for(lambda: self.link.last_rx > 0 and self._poll_lines()))
        self.assertEqual(self.lines, [])

    def _poll_lines(self):
        time.sleep(0.2)
        self.lines = self.link.read_lines()
        return True

    def test_no_receiver_times_out(self):
        self.link = send.make_link(self.cfg())
        self.link.start()
        with self.assertRaises(send.LinkError):
            self.link.wait_ready(0.6, log=print)

    def test_silent_pi_is_noticed(self):
        self.start_receiver()
        self.connect()
        self.assertIsNone(self.link.poll())
        self.link.DEAD_S = 0.2
        time.sleep(0.4)
        self.assertEqual(self.link.poll(), 1)

    def test_traffic_keeps_the_link_alive(self):
        self.start_receiver()
        self.connect()
        self.link.DEAD_S = 0.5
        for _ in range(6):
            self.link.send(["h 1"])
            time.sleep(0.15)
            self.link.read_lines()
        self.assertIsNone(self.link.poll())

    def test_silence_releases_keys(self):
        self.start_receiver()
        self.connect()
        self.link.send(["k 1 30 1", "k 0 0 1"])
        self.assertTrue(self.wait_for(lambda: len(self.kbd.reports) == 1))
        # no more data: the receiver's watchdog lets go
        self.assertTrue(self.wait_for(lambda: self.kbd.reports[-1] == bytes(8)))

    def test_unplugged_adapter_is_a_dead_link(self):
        self.start_receiver()
        self.connect()
        os.close(self.master)
        self.stop_receivers()
        self.master = os.open(os.devnull, os.O_RDONLY)  # so tearDown can close something
        self.link.read_lines()
        self.assertEqual(self.link.poll(), 1)

    def test_missing_port_is_a_link_error(self):
        c = self.cfg()
        c["serial_port"] = "/dev/does-not-exist"
        with self.assertRaises(send.LinkError):
            send.make_link(c).start()


@unittest.skipIf(send is None, "needs python-evdev")
class Config(unittest.TestCase):
    def conf(self, text):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "tpkbd.conf")
            with open(path, "w") as f:
                f.write("[sender]\n" + text)
            return send.load_config(path)

    def test_defaults_stay_on_ssh(self):
        c = send.load_config("/nonexistent")
        self.assertEqual((c["link"], c["serial_port"], c["baud"]), ("ssh", "/dev/ttyUSB0", 115200))

    def test_serial(self):
        c = self.conf("link = serial\nserial_port = /dev/ttyUSB1\nbaud = 230400\n")
        self.assertEqual((c["link"], c["serial_port"], c["baud"]), ("serial", "/dev/ttyUSB1", 230400))

    def test_bad_link(self):
        with self.assertRaises(ValueError):
            self.conf("link = carrier-pigeon\n")

    def test_bad_baud(self):
        with self.assertRaises(ValueError):
            self.conf("baud = 123\n")


class Hello(unittest.TestCase):
    def test_not_answered_in_ssh_mode(self):
        out = []
        rp = recv.Replayer(FakeOut(), FakeOut(), CFG)
        rp.handle("hello")
        rp.handle("h 5")
        self.assertEqual(out, [])

    def test_answered_in_serial_mode(self):
        out = []
        rp = recv.Replayer(FakeOut(), FakeOut(), CFG, reply=out.append)
        rp.handle("hello")
        rp.handle("h 5")
        self.assertEqual(out, ["READY 2", "ok"])


if __name__ == "__main__":
    unittest.main()


@unittest.skipIf(send is None, "needs python-evdev")
class BadConfig(unittest.TestCase):
    def test_duplicate_section_is_a_clean_exit(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "tpkbd.conf")
            with open(path, "w") as f:
                f.write("[sender]\n# comment\n[sender]\nlink = serial\n")
            with self.assertRaises(SystemExit) as cm:
                send.main(["--config", path])
        self.assertIn("bad config", str(cm.exception))
