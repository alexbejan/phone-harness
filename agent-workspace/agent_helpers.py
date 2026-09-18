"""Agent-editable phone helpers.

Add task-specific primitives here. Core helpers from phone_harness.helpers
load this file at import time; anything defined here is available in
phone-harness scripts alongside the core helpers.
"""


def tap_icon(label, index=0):
    """Tap a Home-Screen app icon by its label.

    Learned: tapping the label text itself does NOT launch the app on the
    Home Screen — the tappable icon sits above the label, about 4% of the
    phone screen's height (~35 points in a Mirroring window, ~19 points at
    Device Hub's Physical Size). Verified against Weather on Mirroring and
    Settings on Device Hub (label tap: no-op; icon tap: launches).
    """
    from phone_harness.helpers import find_text, tap, screen_info
    hits = find_text(label)
    if not hits:
        raise RuntimeError(f"no Home-Screen label matching {label!r}")
    h = hits[index]
    tap(h["x"], h["y"] - 0.04 * screen_info()["window"]["h"])
    return h


def messages_send(text, wait=1.0):
    """iOS Messages, thread open: tap the compose field (OCRs as 'iMessage'/'¡Message', bottom of the screen), type, tap the
    blue send arrow at the field's right end (no label: image point 966,2296 of a 1125x2436 native screenshot on the iPhone 11 Pro
    test phone). Returns the OCR after the send. Proven 2026-09-18 (TRU-61 run)."""
    import time
    from phone_harness.helpers import ocr, tap, type_text, tap_image_point
    f = None
    for t in ocr():
        if "message" in t["text"].lower() and t["y"] > 800:
            f = t; break
    if f is None:
        raise RuntimeError("no compose field on screen: " + ", ".join(t["text"] for t in ocr())[:300])
    tap(f["x"], f["y"]); time.sleep(0.6)
    type_text(text); time.sleep(wait)
    tap_image_point(966, 2296, image_size=(1125, 2436)); time.sleep(1.5)
    return ocr()


def messages_tail(n=12):
    """The last n OCR strings of the open thread (the screen tail), for polling a reply without matching old bubbles."""
    from phone_harness.helpers import ocr
    return [t["text"] for t in ocr() if t["y"] > 120][-n:]


def messages_wait(predicate, timeout=90, every=4):
    """Poll the screen tail until predicate(tail) is true; returns the tail (or None on timeout)."""
    import time
    end = time.time() + timeout
    while time.time() < end:
        tail = messages_tail()
        if predicate(tail):
            return tail
        time.sleep(every)
    return None
