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


# --- autonomous runs ---------------------------------------------------------

class PhoneSurface:
    """jevkit.runner Surface over this phone. Menu: tap each visible string,
    type each allowed text into the focused field, scroll down/up, back."""

    def __init__(self, settle_s=1.2):
        from . import helpers
        self.h = helpers
        self.settle_s = settle_s

    def observe(self):
        cands = _cands(None)
        title = self.h.current_app() if self.h.supports("apps.current") else None
        return cands, {"window_title": title}

    def actions(self, cands, texts):
        acts = []
        for c in cands:
            base = c["line"].split("] ", 1)[1]
            acts.append({"id": f"tap_{c['id']}", "kind": "tap", "line": f"[tap_{c['id']}] tap {base}",
                         "call": ("tap", c["x"], c["y"])})
        for i, t in enumerate(texts):
            acts.append({"id": f"type{i}", "kind": "type", "line": f"[type{i}] type {t!r} into the focused field",
                         "call": ("type", t)})
        acts.append({"id": "scroll_down", "kind": "scroll", "line": "[scroll_down] scroll down to see items further down the list",
                     "call": ("scroll", "down")})
        acts.append({"id": "scroll_up", "kind": "scroll", "line": "[scroll_up] scroll up to see items further up the list", "call": ("scroll", "up")})
        if self.h.supports("nav.back"):
            acts.append({"id": "back", "kind": "back", "line": "[back] go back to the previous screen", "call": ("back",)})
        return acts

    def execute(self, action):
        call = action["call"]
        if call[0] == "tap":
            return self._tap_clear_of_bars(call[1], call[2], action)
        if call[0] == "type":
            return self.h.type_text(call[1])
        if call[0] == "scroll":
            return self.h.scroll(call[1], amount=0.35)
        if call[0] == "back":
            return self.h.back()
        raise RuntimeError(f"unknown action {call}")

    def _tap_clear_of_bars(self, x, y, action):
        """Rows under the translucent navigation bar (top ~12%) or the tab and
        search bars (bottom ~20%; measured 2026-09-17: a tap at 86% height on
        the Settings root did nothing) read fine but do not take a tap. Nudge
        the list in small steps until the row sits inside the band, re-find it
        by its text each time, then tap. Bounded: three nudges, then tap anyway."""
        import time
        win = self.h.screen_info()["window"]
        lo, hi = 0.12, 0.80
        text = action["line"].split("tap ", 1)[1].strip("'\"") if "tap " in action["line"] else None
        frac = (y - win["y"]) / win["h"]
        for _ in range(3):
            if lo <= frac <= hi or not text:
                break
            # scroll() takes the content direction: "down" shows what is further
            # down, so the list moves up and a bottom row rises (0.86 -> 0.80 per 0.15).
            self.h.scroll("down" if frac > hi else "up", amount=0.12)
            time.sleep(0.9)
            hits = self.h.find_text(text, exact=True) or self.h.find_text(text)
            if not hits:
                break
            x, y = hits[0]["x"], hits[0]["y"]
            frac = (y - win["y"]) / win["h"]
        return self.h.tap(x, y)

    def settle(self):
        import time
        time.sleep(self.settle_s)


def jev_run(goal, texts=(), max_steps=12, max_seconds=180):
    """Let Jev drive a bounded task on the phone toward `goal`. Jev only
    picks from moves code built from the visible screen; labels on the
    consent list (send, pay, delete, sign in, allow, call, ...) are never
    offered. Text it may type comes only from `texts`. Stops on done, unsure,
    an auth/error/consequential screen, a stuck screen, or the limits.
    Returns {status, reason, steps, final_screen, trace, trace_path}."""
    j, why = _judge()
    if j is None:
        return {"status": "unavailable", "reason": why}
    from jevkit.runner import Runner
    return Runner(PhoneSurface(), judge=j, max_steps=max_steps, max_seconds=max_seconds).run(goal, texts=texts)
