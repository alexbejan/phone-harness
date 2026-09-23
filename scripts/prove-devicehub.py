# task: prove the devicehub backend end to end on the connected test phone
# step: doctor-level proof of eyes, hands, keyboard and navigation; exits non-zero on any failure
#
# Run:  phone-harness < scripts/prove-devicehub.py
# Must pass before merging any change to src/phone_harness/devicehub.py or SKILL.md.
# With the Cua Driver daemon running, also run it once with
# PHONE_HARNESS_DEVICEHUB_INPUT=cgevents (the two routes differ).
# The route in use is printed below.
# Safe: navigates, types a draft in Messages and clears it, never sends, never changes a setting.
import sys
fails = []
def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name); ok or fails.append(name)

check("session ready", connection_state() == "ready")
print("input route:", input_route())
info = screen_info(); check("screen_info has native size", info["img_px"][1] > info["img_px"][0] > 0)
shell("process launch --device " + phone.udid + " --terminate-existing com.apple.Preferences"); wait(1.5)
check("open Settings by bundle id", bool(wait_for_text("Airplane Mode", timeout=5)))
hit = scroll_until(lambda boxes: next((b for b in boxes if b["text"] == "General"), None), max_scrolls=8)
check("scroll_until finds General", bool(hit))
win = info["window"]
if hit and (hit["y"] - win["y"]) / win["h"] < 0.12:
    scroll("down", amount=0.15); wait(1.0)
before = ocr()
tap_text("General"); check("tap_text General opens it", bool(wait_for_text("About", timeout=5)))
# Optional Jev judgements (jev.enabled). Skipped, not failed, when off.
avail, why = jev_available()
print("jev:", "on" if avail else f"off ({why})")
if avail:
    v = judge_verify("the General settings page is open (About, Software Update rows visible)", before)
    check(f"judge_verify sees General open (p={v.get('p_landed')}, gate={v.get('gate')})",
          v.get("landed") is True and not v.get("unavailable"))
    k = classify_screen()
    check(f"classify_screen kind={k.get('kind')} consequential={k.get('consequential')}",
          k.get("kind") in ("normal", "empty") and not k.get("unavailable"))
    pk = pick_text("the row that shows the phone's software version and model")
    check(f"pick_text -> {pk['box'] and pk['box']['text']!r} (gate={pk['gate']})",
          bool(pk["box"]) and pk["box"]["text"] == "About")
    pn = pick_text("a Send Message button")
    check(f"pick_text absent target -> none (gate={pn['gate']})", pn["box"] is None and pn["gate"] == "stop")
home(); check("home()", bool(wait_for_text("Search", timeout=5)) or bool(find_text("Settings")))
# Messages opens into the last thread; the compose field is the bottom row of
# the phone screen (the placeholder "Message" is hidden whenever a draft is in
# it), so aim by position, not by the word.
open_app("com.apple.MobileSMS"); wait(1.2)
win = screen_info()["window"]
draft_line = lambda: [o["text"] for o in ocr()
                      if (o["y"] - win["y"]) / win["h"] > 0.9 and o["text"] != "+"]
fx = win["x"] + win["w"] * 0.35; fy = win["y"] + win["h"] * 0.94
tap(fx, fy); wait(0.7)                 # focus the compose field (raises keyboard)
type_text("Draft ph"); wait(1.0)       # typing proves the field is reachable+focused
line = draft_line()
check("Messages compose field reachable (paste typed)", any("Draft" in t for t in line))
type_text(" keys", keystrokes=True); wait(0.8)
check("type_text keystrokes", any("keys" in t for t in draft_line()))
for _ in range(4):                     # clear fully, tolerating any pre-existing text
    press("cmd+a"); press("delete"); wait(0.5)
    if not draft_line(): break
check("draft cleared (cmd+a, delete)", not any("Draft" in t or "keys" in t for t in draft_line()))
# messages_clear_field (TRU-231): a leftover draft hides the placeholder; the helper must still find the field and empty it.
type_text("Leftover ph"); wait(1.0)
f = messages_clear_field()
check("messages_clear_field empties a leftover draft", bool(f) and not any("Leftover" in t for t in draft_line()))
home()
check("list_apps", "com.apple.Preferences" in list_apps(include_system=True))
check("shell(info lockState)", "passcodeRequired" in shell("info lockState"))
print("\n" + ("ALL PASS" if not fails else "FAILED: " + ", ".join(fails)))
sys.exit(1 if fails else 0)
