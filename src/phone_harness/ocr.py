"""Text recognition over window captures via Apple's Vision framework.

This is the mirror backend's element tree: OCR gives every visible string a
bounding box, converted here into global screen points ready for tap().
"""
import sys
import time

import Quartz
import Vision
from Foundation import NSURL


def image_size(path):
    src = Quartz.CGImageSourceCreateWithURL(NSURL.fileURLWithPath_(path), None)
    if src is None:
        raise RuntimeError(f"cannot read image {path}")
    props = Quartz.CGImageSourceCopyPropertiesAtIndex(src, 0, None)
    return int(props["PixelWidth"]), int(props["PixelHeight"])


def _vision_request(path, cpu_only=False, fast=False):
    handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(
        NSURL.fileURLWithPath_(path), None)
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelFast if fast
                                 else Vision.VNRequestTextRecognitionLevelAccurate)
    if cpu_only:
        request.setUsesCPUOnly_(True)
    ok, err = handler.performRequests_error_([request], None)
    return request, ok, err


FALLBACK_S = 30.0          # after a fault, the fast model for this long
_fast_until = 0.0


def _perform(path):
    """Run the text request, riding out Vision's transient fault
    CRImageReaderError e5rtError (13) (TRU-320). Measured 2026-09-23 during a
    prove run: once it starts, the ACCURATE model fails on every call for a
    while, on the default path and with usesCPUOnly alike (about 17 calls in
    a row), while the FAST model on the CPU read every one of them and the
    run passed. 300 back-to-back calls outside the harness never hit it.
    So: accurate; on a fault, the fast model at once and for the next
    FALLBACK_S seconds (no retry penalty on every call); one more fast try
    after 2.5 s; a fault there is real and raises. Faults go to stderr."""
    global _fast_until
    if time.monotonic() >= _fast_until:
        request, ok, err = _vision_request(path)
        if ok:
            return request
        print(f"[ocr] Vision fault on the accurate model, fast model for "
              f"{FALLBACK_S:.0f} s: {err}", file=sys.stderr)
        _fast_until = time.monotonic() + FALLBACK_S
    for pause in (0.0, 2.5):
        if pause:
            time.sleep(pause)
        request, ok, err = _vision_request(path, cpu_only=True, fast=True)
        if ok:
            return request
        print(f"[ocr] Vision fault on the fast model: {err}", file=sys.stderr)
    raise RuntimeError(f"Vision OCR failed (accurate and fast models): {err}")


def recognize(path, window):
    """OCR a capture of `window` ({x, y, w, h} screen points).

    Returns [{text, confidence, x, y, w, h}] where (x, y) is the box center in
    screen points — pass straight to tap(). Vision's normalized boxes have a
    bottom-left origin; screen points have a top-left origin, hence the flip.
    """
    request = _perform(path)

    img_w, img_h = image_size(path)
    sx = window["w"] / img_w  # image px -> screen points
    sy = window["h"] / img_h

    out = []
    for obs in request.results() or []:
        cand = obs.topCandidates_(1)
        if not cand:
            continue
        bb = obs.boundingBox()
        px = bb.origin.x * img_w
        py_top = (1.0 - bb.origin.y - bb.size.height) * img_h
        pw = bb.size.width * img_w
        ph = bb.size.height * img_h
        out.append({
            "text": str(cand[0].string()),
            "confidence": round(float(cand[0].confidence()), 3),
            "x": round(window["x"] + (px + pw / 2) * sx, 1),
            "y": round(window["y"] + (py_top + ph / 2) * sy, 1),
            "w": round(pw * sx, 1),
            "h": round(ph * sy, 1),
        })
    return out
