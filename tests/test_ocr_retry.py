"""OCR rides out a transient Vision fault (TRU-320). Runs on the Mac:
.venv/bin/python -m unittest discover tests"""
import io
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from phone_harness import ocr  # noqa: E402

FAULT = "TextRecognition.CRImageReaderError.e5rtError (13)"
OK = ("req", True, None)
BAD = (None, False, FAULT)
ACC, FAST = (False, False), (True, True)


class OcrFallback(unittest.TestCase):
    def setUp(self):
        ocr._fast_until = 0.0
        self.now = 1000.0

    def run_with(self, results):
        calls, seen = iter(results), []

        def fake(p, cpu_only=False, fast=False):
            seen.append((cpu_only, fast))
            return next(calls)
        with mock.patch.object(ocr, "_vision_request", side_effect=fake), \
                mock.patch.object(ocr.time, "monotonic", side_effect=lambda: self.now), \
                mock.patch.object(ocr.time, "sleep") as sl, redirect_stderr(io.StringIO()) as log:
            try:
                out = ocr._perform("x.png")
            except RuntimeError as e:
                out = e
        return out, seen, [c.args[0] for c in sl.call_args_list], log.getvalue()

    def test_accurate_ok_no_fallback(self):
        self.assertEqual(self.run_with([OK])[:3], ("req", [ACC], []))

    def test_fault_goes_fast_at_once(self):
        out, seen, sleeps, log = self.run_with([BAD, OK])
        self.assertEqual((out, seen, sleeps), ("req", [ACC, FAST], []))
        self.assertIn("fast model for 30 s", log)

    def test_fast_window_skips_accurate_then_ends(self):
        self.run_with([BAD, OK])
        self.now += 10
        self.assertEqual(self.run_with([OK])[1], [FAST])
        self.now += 25
        self.assertEqual(self.run_with([OK])[1], [ACC])

    def test_fast_fault_retried_after_pause(self):
        out, seen, sleeps, _ = self.run_with([BAD, BAD, OK])
        self.assertEqual((out, seen, sleeps), ("req", [ACC, FAST, FAST], [2.5]))

    def test_all_fail_raises(self):
        out, _, _, log = self.run_with([BAD, BAD, BAD])
        self.assertIsInstance(out, RuntimeError)
        self.assertIn("e5rtError", str(out))
        self.assertEqual(log.count("[ocr] Vision fault"), 3)


if __name__ == "__main__":
    unittest.main()
