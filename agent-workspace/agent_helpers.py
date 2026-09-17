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
