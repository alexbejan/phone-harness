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


# The field's placeholder as Vision reads it: "iMessage", "¡Message", and on the fast model after a Vision fault
# (TRU-320) "limessage" / "rimessage" / "Imessage" (measured 2026-09-23 on the test phone, 4 reads of one screen).
# Up to two stray characters before "message": a one-character pattern missed "limessage", so a send that went out
# raised "draft still in the compose field" and the next clear-field call raised before any paste.
_MSG_PLACEHOLDER = r"[a-z¡!1|]{0,2}\s?message|text message"


def _msg_placeholder(boxes, w):
    import re
    return [t for t in boxes if re.fullmatch(_MSG_PLACEHOLDER, t["text"].strip().lower()) and t["y"] > w["y"] + 0.3 * w["h"]]


def _placeholder_now(w, tries=3, gap=0.4):
    """The placeholder's OCR boxes, read up to `tries` times: with the field focused, the blinking cursor sits on the
    placeholder and one read in two finds nothing there (measured 2026-09-23: 'after tap' and 'after delete' reads came
    back without it while the screenshot showed an empty field), so one miss is not a draft."""
    import time
    from phone_harness.helpers import ocr
    for i in range(tries):
        hits = _msg_placeholder(ocr(), w)
        if hits:
            return hits
        if i < tries - 1:
            time.sleep(gap)
    return []


def messages_clear_field():
    """iOS Messages, thread open: focus the compose field and empty it (cmd+a, delete, up to 4 rounds) until its placeholder
    shows. Returns the placeholder's OCR box. The field is found by its placeholder, else by the '+' button on its row (a
    leftover draft hides the placeholder), else at 0.94 of the phone height. Raises when the field never comes back empty.
    TRU-231, 2026-09-23: a leftover draft from a send that silently failed took the next paste inside it (the tap put the
    cursor before its last word) and both went out as one garbled message (2026-09-21 22:00)."""
    import time
    from phone_harness.helpers import ocr, tap, press, screen_info
    w = screen_info()["window"]
    boxes = ocr()
    hits = _msg_placeholder(boxes, w)
    if hits:
        f = max(hits, key=lambda t: t["y"])
        fy = f["y"]
    else:
        plus = [t for t in boxes if t["text"].strip() == "+" and t["y"] > w["y"] + 0.5 * w["h"]]
        fy = max(plus, key=lambda t: t["y"])["y"] if plus else w["y"] + 0.94 * w["h"]
    tap(w["x"] + 0.35 * w["w"], fy); time.sleep(0.6)
    for _ in range(4):
        press("cmd+a"); time.sleep(0.2); press("delete"); time.sleep(0.5)
        hits = _placeholder_now(w)
        if hits:
            return max(hits, key=lambda t: t["y"])
    raise RuntimeError("the compose field did not come back empty after 4 rounds of cmd+a, delete; nothing sent")


def _send_arrow_x(w, fy, fallback=0.858):
    """The send arrow's x on the compose row, found by its colour in the native screenshot: the rightmost run of iOS blue
    on the row at fy. The arrow moves with the layout (measured 2026-09-23: 0.857 of the phone width with the keyboard
    layout, 0.882 with the Photos picker open under the field), so a fixed 0.858 tapped beside it and the draft stayed
    (TRU-256 run 1). Falls back to `fallback` of the width when no blue run is found or no screenshot can be read."""
    try:
        from phone_harness.helpers import screenshot
        from AppKit import NSBitmapImageRep
        rep = NSBitmapImageRep.imageRepWithContentsOfFile_(screenshot())
        W, H = rep.pixelsWide(), rep.pixelsHigh()
        py = int((fy - w["y"]) / w["h"] * H)
        blue = []
        for px in range(int(0.97 * W), int(0.6 * W), -2):
            c = rep.colorAtX_y_(px, py)
            r, g, b = c.redComponent(), c.greenComponent(), c.blueComponent()
            if b > 0.85 and r < 0.3 and 0.35 < g < 0.7:
                blue.append(px)
            elif blue and px < blue[-1] - 0.05 * W:   # the white arrow glyph splits the pill; a longer gap ends it
                break
        if len(blue) >= 6:
            return w["x"] + (sum(blue) / len(blue)) / W * w["w"]
    except Exception:
        pass
    return w["x"] + fallback * w["w"]


def messages_send(text, wait=1.0):
    """iOS Messages, thread open: empty the compose field (messages_clear_field), paste the text, tap the blue send arrow.
    Field and arrow are found from the placeholder and the phone window, wherever Device Hub draws the phone and whether or
    not the photo picker pushes the field up (2026-09-19, TRU-114).
    TRU-231 (2026-09-23): the field is emptied before every paste, so a leftover draft never merges with the new text.
    iOS 27 sometimes answers the paste with the 'Paste / Text Effects / AutoFill' callout instead of inserting: the
    callout's Paste is tapped, and a paste that left the field empty is tried once more. The draft is checked before the
    arrow is tapped (never a send of an empty field) and after (placeholder back = sent); a draft still in the field gets
    one more arrow tap and never a second paste, so the helper never sends twice. Arrow at 0.858 of the phone width
    (measured 2026-09-23: centre 0.857/0.941 of the screen). Raises when the text never landed or the draft is still
    there (clear it with messages_clear_field before anything else); returns the OCR after the send."""
    import time
    from phone_harness.helpers import ocr, tap, type_text, screen_info
    w = screen_info()["window"]

    def paste_callout(boxes):
        return next((t for t in boxes if t["text"].strip().lower() == "paste" and t["y"] > w["y"] + 0.3 * w["h"]), None)

    for attempt in range(2):
        f = messages_clear_field()
        type_text(text); time.sleep(wait)
        boxes = ocr()
        callout = paste_callout(boxes)
        if callout:
            tap(callout["x"], callout["y"]); time.sleep(wait)
            boxes = ocr()
        if not _placeholder_now(w):
            break
    else:
        raise RuntimeError("the text never reached the compose field (placeholder still showing after two pastes); nothing sent")
    arrow = (_send_arrow_x(w, f["y"]), f["y"])
    for attempt in range(2):
        tap(*arrow); time.sleep(1.5)
        if _placeholder_now(w):
            return ocr()
    raise RuntimeError("draft still in the compose field after two taps on the send arrow; not sent")


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
