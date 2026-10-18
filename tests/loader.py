"""Load the extension-less scripts as modules, with a stand-in for python-evdev.

The scripts talk to /dev/input and /dev/uinput, which tests can't use. The
stand-in has the constants they need, and the scripts only create devices from
main(), so importing them is safe."""
import importlib.machinery
import importlib.util
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONSTS = dict(
    EV_SYN=0, EV_KEY=1, EV_REL=2, EV_ABS=3, SYN_REPORT=0,
    KEY_ESC=1, KEY_A=30, KEY_LEFTCTRL=29, KEY_RIGHTCTRL=97, KEY_SPACE=57,
    KEY_POWER=116, KEY_SLEEP=142, KEY_WAKEUP=143, KEY_SUSPEND=205,
    BTN_LEFT=272, BTN_RIGHT=273, BTN_MIDDLE=274,
    BTN_TOOL_FINGER=325, BTN_TOUCH=330, BTN_TOOL_DOUBLETAP=333,
    REL_X=0, REL_Y=1, REL_HWHEEL=6, REL_WHEEL=8, REL_WHEEL_HI_RES=11,
    REL_HWHEEL_HI_RES=12,
    ABS_X=0, ABS_Y=1, ABS_MT_SLOT=47, ABS_MT_POSITION_X=53,
    ABS_MT_POSITION_Y=54, ABS_MT_TRACKING_ID=57,
    INPUT_PROP_POINTER=0, INPUT_PROP_BUTTONPAD=2,
)


def _stub_evdev():
    mod = types.ModuleType("evdev")
    mod.ecodes = types.SimpleNamespace(**CONSTS, ecodes=dict(CONSTS))
    mod.AbsInfo = lambda *a: a
    mod.UInput = lambda *a, **kw: None
    mod.list_devices = lambda: []
    mod.InputDevice = lambda path: None
    sys.modules["evdev"] = mod


def load(relpath):
    _stub_evdev()
    path = os.path.join(ROOT, relpath)
    name = os.path.basename(relpath).replace("-", "_")
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class Rec:
    """Stands in for a UInput: records what would have been written."""

    def __init__(self):
        self.events = []

    def write(self, t, c, v):
        self.events.append((t, c, v))

    def syn(self):
        self.events.append("SYN")

    def clear(self):
        self.events.clear()
