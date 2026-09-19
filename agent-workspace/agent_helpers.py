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
    """iOS Messages, thread open: tap the compose field (its placeholder OCRs as 'iMessage'/'¡Message'/'Text Message'), type, tap
    the blue send arrow at the field's right end. Both are found from the placeholder and the phone window, wherever Device Hub
    draws the phone and whether or not the photo picker pushes the field up (2026-09-19, TRU-114: a fixed y > 800 and a fixed
    arrow point missed both). Returns the OCR after the send. Proven 2026-09-18 (TRU-61 run), reworked 2026-09-19."""
    import re, time
    from phone_harness.helpers import ocr, tap, type_text, screen_info
    w = screen_info()["window"]
    hits = [t for t in ocr() if re.fullmatch(r"[i¡l1!]?\s?message|text message", t["text"].strip().lower()) and t["y"] > w["y"] + 0.3 * w["h"]]
    if not hits:
        raise RuntimeError("no compose field on screen: " + ", ".join(t["text"] for t in ocr())[:300])
    f = max(hits, key=lambda t: t["y"])
    tap(f["x"], f["y"]); time.sleep(0.6)
    type_text(text); time.sleep(wait)
    tap(w["x"] + 0.87 * w["w"], f["y"]); time.sleep(1.5)
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
