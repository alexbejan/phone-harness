"""A rotated Device Hub view is named and no tap is sent (2026-09-23). Runs on the Mac:
.venv/bin/python -m unittest discover tests

The fixtures are Device Hub window captures taken that night on the test iPhone, cropped to the canvas: the same Apple
Account sheet drawn upright and upside down, and the Home Screen drawn on its side."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from phone_harness import devicehub as dh  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"
CHROME = "com.apple.dt.devicekit.chrome.phone2"


def orientation(name):
    path = str(FIX / name)
    buf, bpr, w, h = dh._load_png(path)
    ring, _ = dh.largest_blob(path, (0, 0, w, h))
    l, t, r, b = dh.CHROME_INSETS[CHROME]
    screen = (ring[0] + ring[2] * l, ring[1] + ring[3] * t, ring[2] * (1 - l - r), ring[3] * (1 - t - b))
    return dh.view_orientation(buf, bpr, screen, ring, dh.CHROME_RING_ASPECT[CHROME])


class RotatedView(unittest.TestCase):
    def test_upright(self):
        self.assertEqual(orientation("rotated-upright.png"), "upright")

    def test_upside_down(self):
        self.assertEqual(orientation("rotated-upside-down.png"), "upside-down")

    def test_sideways(self):
        self.assertEqual(orientation("rotated-sideways.png"), "sideways")

    def test_black_screen_cannot_tell(self):
        # a screen with no notch contrast either way is not called rotated: the upright path stays as it was
        buf = bytes([0, 0, 0, 255]) * (100 * 200)
        self.assertIsNone(dh.view_orientation(buf, 400, (0, 0, 100, 200), (0, 0, 100, 200), 0.508))

    def test_session_names_the_state(self):
        # the refusal is a RuntimeError subclass, so every caller that stops on geometry errors stops on this one too
        self.assertTrue(issubclass(dh.RotatedView, RuntimeError))


if __name__ == "__main__":
    unittest.main()
