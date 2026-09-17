"""Jev judgements over what the phone shows. Optional, off by default.

The harness reports; the agent decides. These helpers add a cheap, typed
second opinion from TypeSafe Jev (via jevkit) on three questions the agent
otherwise answers by reading OCR by hand:

    judge_verify(expect, before, after)   did the action land?
    pick_text(target)                      which visible string is the one meant?
    classify_screen()                      what kind of screen is this? anything consequential?

Every helper returns a plain dict with `gate` in {"act", "caution", "stop"}
and `unavailable=True` when Jev is off, unconfigured, or unreachable, so a
script can branch without try/except and fall back to find_text/tap_text.

Privacy: when enabled, the visible text of the phone screen (OCR strings or
tree labels, never screenshots or coordinates) is sent to TypeSafe for each
judgement. This fork promises screen text stays on the machine by default,
so `jev.enabled` defaults to false. Turn it on deliberately:

    phone-harness config set jev.enabled true

and give jevkit a key (Keychain item TYPESAFE_API_KEY or the env var).
PHONE_HARNESS_JEV=0 overrides to off for one call.
"""
from . import config


def _enabled():
    return bool(config.get("jev.enabled"))


def _judge():
    """A jevkit Judge, or None with a reason."""
    if not _enabled():
        return None, "jev.enabled is false (phone-harness config set jev.enabled true)"
    try:
        from jevkit import Judge
    except ImportError:
        return None, "jevkit is not installed in this venv (pip install -e ~/Documents/jevkit)"
    return Judge(), None


def _boxes(boxes):
    from . import helpers
    if boxes is not None:
        return boxes
    if helpers.supports("tree"):
        try:
            return helpers.ui()
        except Exception:      # noqa: BLE001 - fall through to OCR
            pass
    return helpers.ocr()


def _cands(boxes):
    from jevkit import compact
    return compact.phone_boxes(_boxes(boxes))


def jev_available():
    """(True, None) or (False, reason). Cheap; does not call the network."""
    j, why = _judge()
    return (j is not None), why


def judge_verify(expect, before, after=None):
    """Did `expect` happen between `before` and `after` (ocr()/ui() lists)?
    `after` defaults to a fresh read. -> {landed, p_landed, dialog, error,
    auth, gate, diff, note, unavailable}."""
    j, why = _judge()
    if j is None:
        return {"unavailable": True, "gate": "caution", "error_text": why}
    return j.verify(expect, _cands(before), _cands(after))


def pick_text(target, boxes=None, tap=False):
    """The visible string best matching a description, as an ocr()-style box
    with tap-ready x/y, or None when nothing matches. With tap=True, taps it
    when gate is "act" and returns the box; never taps on caution/stop."""
    j, why = _judge()
    if j is None:
        return {"unavailable": True, "gate": "caution", "error_text": why, "box": None}
    r = j.pick(target, _cands(boxes), interactive_only=False)
    c = r.get("candidate")
    box = {"text": c["text"], "x": c["x"], "y": c["y"], "w": c["w"], "h": c["h"]} if c else None
    out = {"box": box, "gate": r["gate"], "confidence": r.get("confidence"),
           "ambiguous": r.get("ambiguous"), "unavailable": r.get("unavailable", False),
           "probabilities": r.get("probabilities")}
    if tap and box and r["gate"] == "act":
        from . import helpers
        helpers.tap(box["x"], box["y"])
        out["tapped"] = True
    return out


def classify_screen(boxes=None):
    """-> {kind, confidence, consequential, dialog_kind, keyboard, modal, gate, unavailable}.
    `consequential` true means a Send / Pay / Delete / Sign in / Allow style
    control is visible: the consent rules apply before touching it."""
    j, why = _judge()
    if j is None:
        return {"unavailable": True, "gate": "caution", "error_text": why}
    r = j.classify(_cands(boxes))
    r.pop("raw", None)
    return r
