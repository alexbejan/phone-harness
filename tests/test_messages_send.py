"""messages_send against a fake phone (TRU-231): the iOS 27 paste callout,
an empty paste, and a send that needs a second tap. No device needed:
.venv/bin/python -m unittest discover tests"""
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
WIN = {"x": 800.0, "y": 300.0, "w": 200.0, "h": 400.0}
FIELD = {"text": "iMessage", "x": 870.0, "y": 675.0}
PASTE = {"text": "Paste", "x": 860.0, "y": 640.0}


class FakePhone:
    """paste_modes: per type_text call, 'ok' | 'callout' | 'lost'.
    arrow_ok: per arrow tap, whether it sends."""

    def __init__(self, paste_modes, arrow_ok=(True,), draft=""):
        self.paste_modes, self.arrow_ok = list(paste_modes), list(arrow_ok)
        self.draft, self.callout, self.sent, self.taps = draft, False, [], []
        self.selected = False

    def screen_info(self):
        return {"window": WIN}

    def ocr(self):
        out = [{"text": "older bubble", "x": 850.0, "y": 400.0}, {"text": "+", "x": 826.0, "y": FIELD["y"]}]
        if not self.draft:
            out.append(dict(FIELD))
        if self.callout:
            out.append(dict(PASTE))
        return out

    def press(self, combo):
        if combo == "cmd+a":
            self.selected = True
        elif combo == "delete" and self.selected:
            self.draft, self.selected = "", False

    def type_text(self, text):
        mode = self.paste_modes.pop(0)
        if mode == "ok":
            self.draft = self.draft + text  # a paste into a leftover draft merges
        elif mode == "callout":
            self.callout, self.pending = True, text

    def tap(self, x, y):
        self.taps.append((round(x, 1), round(y, 1)))
        if self.callout and (x, y) == (PASTE["x"], PASTE["y"]):
            self.callout, self.draft = False, self.draft + self.pending
        elif x > WIN["x"] + 0.8 * WIN["w"] and self.draft:
            if self.arrow_ok.pop(0):
                self.sent.append(self.draft)
                self.draft = ""


def load(phone):
    fake = types.ModuleType("phone_harness.helpers")
    for n in ("ocr", "tap", "type_text", "screen_info", "press"):
        setattr(fake, n, getattr(phone, n))
    pkg = types.ModuleType("phone_harness")
    pkg.helpers = fake
    spec = importlib.util.spec_from_file_location("ah_test", ROOT / "agent-workspace" / "agent_helpers.py")
    mod = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {"phone_harness": pkg, "phone_harness.helpers": fake}):
        spec.loader.exec_module(mod)
        with mock.patch("time.sleep"):
            return mod, fake


class MessagesSend(unittest.TestCase):
    def send(self, phone, text="hi"):
        mod, fake = load(phone)
        with mock.patch.dict(sys.modules, {"phone_harness.helpers": fake,
                                           "phone_harness": types.SimpleNamespace(helpers=fake)}), \
                mock.patch("time.sleep"):
            return mod.messages_send(text, wait=0)

    def test_plain_paste_sends_once(self):
        p = FakePhone(["ok"])
        self.send(p)
        self.assertEqual(p.sent, ["hi"])
        self.assertEqual(p.taps[-1], (round(WIN["x"] + 0.858 * WIN["w"], 1), FIELD["y"]))

    def test_leftover_draft_cleared_before_paste(self):
        p = FakePhone(["ok"], draft="by June would be nice")
        self.send(p)
        self.assertEqual(p.sent, ["hi"])

    def test_callout_paste_is_tapped(self):
        p = FakePhone(["callout"])
        self.send(p)
        self.assertIn((PASTE["x"], PASTE["y"]), p.taps)
        self.assertEqual(p.sent, ["hi"])

    def test_lost_paste_retried_once(self):
        p = FakePhone(["lost", "ok"])
        self.send(p)
        self.assertEqual(p.sent, ["hi"])

    def test_twice_lost_raises_and_never_taps_arrow(self):
        p = FakePhone(["lost", "lost"])
        with self.assertRaisesRegex(RuntimeError, "never reached"):
            self.send(p)
        self.assertEqual(p.sent, [])
        self.assertTrue(all(x < WIN["x"] + 0.8 * WIN["w"] for x, _ in p.taps))

    def test_missed_arrow_retried_once_never_twice_sent(self):
        p = FakePhone(["ok"], arrow_ok=[False, True])
        self.send(p)
        self.assertEqual(p.sent, ["hi"])

    def test_arrow_missed_twice_raises(self):
        p = FakePhone(["ok"], arrow_ok=[False, False])
        with self.assertRaisesRegex(RuntimeError, "draft still"):
            self.send(p)
        self.assertEqual(p.sent, [])


if __name__ == "__main__":
    unittest.main()
