"""OCR retries once on a transient Vision fault (TRU-320). Runs on the Mac:
.venv/bin/python -m unittest discover tests"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from phone_harness import ocr  # noqa: E402

FAULT = "TextRecognition.CRImageReaderError.e5rtError (13)"


class OcrRetry(unittest.TestCase):
    def run_with(self, results):
        calls = iter(results)
        with mock.patch.object(ocr, "_vision_request",
                               side_effect=lambda p, cpu_only=False: next(calls)) as vr, \
                mock.patch.object(ocr.time, "sleep") as sl:
            try:
                return ocr._perform("x.png"), vr.call_count, sl.call_count
            except RuntimeError as e:
                return e, vr.call_count, sl.call_count

    def test_first_try_ok_no_retry(self):
        out, n, sleeps = self.run_with([("req", True, None)])
        self.assertEqual((out, n, sleeps), ("req", 1, 0))

    def test_transient_fault_then_ok(self):
        out, n, sleeps = self.run_with([(None, False, FAULT), ("req", True, None)])
        self.assertEqual((out, n, sleeps), ("req", 2, 1))

    def test_retry_runs_on_cpu_only(self):
        seen = []
        results = iter([(None, False, FAULT), ("req", True, None)])
        def fake(p, cpu_only=False):
            seen.append(cpu_only)
            return next(results)
        with mock.patch.object(ocr, "_vision_request", side_effect=fake), \
                mock.patch.object(ocr.time, "sleep"):
            ocr._perform("x.png")
        self.assertEqual(seen, [False, True])

    def test_two_faults_raise(self):
        out, n, sleeps = self.run_with([(None, False, FAULT), (None, False, FAULT)])
        self.assertIsInstance(out, RuntimeError)
        self.assertIn("2 attempts", str(out))
        self.assertIn("e5rtError", str(out))
        self.assertEqual((n, sleeps), (2, 1))


if __name__ == "__main__":
    unittest.main()
