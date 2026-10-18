"""The real sender code talking to the real receiver code over a pipe."""
import json
import os
import select
import sys
import unittest

from tests.loader import ROOT
from tests.test_send import OfflineSender, e, send, tap

RECEIVER = r"""
import json, sys
sys.path.insert(0, %(root)r)
from tests.loader import Rec, load
recv = load("pc/tpkbd-recv")
cfg = recv.load_config("/nonexistent")
cfg["jitter_ms"] = 0
kbd, ptr, pinch = Rec(), Rec(), Rec()
rp = recv.Replayer(kbd, ptr, pinch, cfg)
print("READY %%d" %% recv.PROTO, flush=True)
recv.serve(rp, 0, 3, 30)
print(json.dumps({"kbd": kbd.events, "ptr": ptr.events, "pinch": len(pinch.events)}), flush=True)
""" % {"root": ROOT}


class SenderToReceiver(unittest.TestCase):
    def test_a_session(self):
        link = send.Link(send.load_config("/nonexistent"),
                         argv=[sys.executable, "-I", "-c", RECEIVER])
        link.start()
        self.addCleanup(link.close)
        link.wait_ready(10, log=print)

        s = OfflineSender(send.load_config("/nonexistent"), link=link)
        s.enter_remote()
        s.heartbeat(100.0)
        tap(s, e.KEY_A, 1)
        # libinput lines through the real parser and timestamping
        r, w = os.pipe()
        s.master = r
        os.write(w, b" event5   POINTER_MOTION    +1.0s\t 4.00/ 0.00 ( 4.00/ 0.00 unaccelerated)\n"
                    b" event5   POINTER_BUTTON    +1.1s\t BTN_LEFT (272) pressed, seat count: 1\n"
                    b" event5   GESTURE_PINCH_BEGIN +1.2s\t 2\n")
        os.close(w)
        s.handle_libinput()
        os.close(r)
        s.master = None
        # the connection ends with A, the button and the pinch still held
        link.close = link.proc.stdin.close   # EOF only: the output is read below
        s.shutdown()

        out = b""
        while True:
            ready, _, _ = select.select([link.fd], [], [], 10)
            self.assertTrue(ready, "receiver never finished")
            chunk = os.read(link.fd, 65536)
            if not chunk:
                break
            out += chunk
        result = json.loads(out.decode().strip().splitlines()[-1])
        kbd = [tuple(x) if x != "SYN" else x for x in result["kbd"]]
        ptr = [tuple(x) if x != "SYN" else x for x in result["ptr"]]
        self.assertEqual(kbd[:2], [(e.EV_KEY, e.KEY_A, 1), "SYN"])
        self.assertIn((e.EV_KEY, e.KEY_A, 0), kbd)             # released at the end
        self.assertIn((e.EV_REL, e.REL_X, 5), ptr)             # 4.0 * 1.25
        self.assertIn((e.EV_KEY, e.BTN_LEFT, 1), ptr)
        self.assertIn((e.EV_KEY, e.BTN_LEFT, 0), ptr)          # released at the end
        self.assertGreater(result["pinch"], 0)


if __name__ == "__main__":
    unittest.main()
