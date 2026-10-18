import ipaddress
import unittest

from tests.loader import load

pair = load("thinkpad/tpkbd-pair")


class Pair(unittest.TestCase):
    def test_ssh_g(self):
        out = pair.parse_ssh_g("hostname 192.0.2.10\nport 22\nuser someone\n"
                               "hostkeyalias tpkbd-pc\nuserknownhostsfile /etc/tpkbd/known_hosts\n")
        self.assertEqual(out["hostname"], "192.0.2.10")
        self.assertEqual(out["hostkeyalias"], "tpkbd-pc")

    def test_keyscan(self):
        text = "# 192.0.2.10:22 SSH-2.0-OpenSSH\n192.0.2.10 ssh-ed25519 AAAAC3Nza\n"
        self.assertEqual(pair.parse_keyscan(text), ("ssh-ed25519", "AAAAC3Nza"))
        self.assertIsNone(pair.parse_keyscan("# nothing\n"))
        self.assertIsNone(pair.parse_keyscan(""))

    def test_network_detection(self):
        route = "192.0.2.10 dev wlan0 src 192.0.2.77 uid 0\n    cache\n"
        addrs = ("1: lo    inet 127.0.0.1/8 scope host lo\n"
                 "3: wlan0    inet 192.0.2.77/24 brd 192.0.2.255 scope global wlan0\n")
        src = pair.route_source(route)
        self.assertEqual(src, "192.0.2.77")
        self.assertEqual(pair.network_of(addrs, src), ipaddress.ip_network("192.0.2.0/24"))
        self.assertIsNone(pair.network_of(addrs, "198.51.100.1"))
        self.assertIsNone(pair.route_source("unreachable"))

    def test_authorized_line_is_restricted(self):
        line = pair.authorized_line(ipaddress.ip_network("192.0.2.0/24"), "ssh-ed25519 AAAA tpkbd\n")
        self.assertEqual(
            line,
            'from="192.0.2.0/24",restrict,pty,'
            'command="stty -echo; exec /usr/local/bin/tpkbd-recv" ssh-ed25519 AAAA tpkbd')

    def test_known_hosts_entry_is_replaced_not_duplicated(self):
        import os
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "known_hosts")
            key = subprocess.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-f", os.path.join(d, "k")],
                                 capture_output=True, check=True)
            with open(os.path.join(d, "k.pub")) as f:
                _, blob, *_ = f.read().split()
            pair.write_known_hosts(path, "tpkbd-pc", "ssh-ed25519", "AAAAold")
            pair.write_known_hosts(path, "tpkbd-pc", "ssh-ed25519", blob)
            with open(path) as f:
                lines = f.read().splitlines()
        self.assertEqual(lines, [f"tpkbd-pc ssh-ed25519 {blob}"])

    def test_main_refuses_without_root(self):
        import os
        import sys
        if os.geteuid() == 0:
            self.skipTest("running as root")
        old = sys.argv
        sys.argv = ["tpkbd-pair"]
        try:
            with self.assertRaises(SystemExit) as cm:
                pair.main()
        finally:
            sys.argv = old
        self.assertIn("run as root", str(cm.exception.code))


if __name__ == "__main__":
    unittest.main()
