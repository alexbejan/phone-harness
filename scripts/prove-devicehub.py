# task: prove the devicehub backend end to end on the connected test phone
# step: doctor-level proof of eyes, hands, keyboard and navigation; exits non-zero on any failure
#
# Run:  phone-harness < scripts/prove-devicehub.py
# Must pass before merging any change to src/phone_harness/devicehub.py or SKILL.md.
# Safe: navigates, types a draft in Messages and clears it, never sends, never changes a setting.
import sys
fails = []
def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name); ok or fails.append(name)

check("session ready", connection_state() == "ready")
info = screen_info(); check("screen_info has native size", info["img_px"][1] > info["img_px"][0] > 0)
shell("process launch --device " + phone.udid + " --terminate-existing com.apple.Preferences"); wait(1.5)
check("open Settings by bundle id", bool(wait_for_text("Airplane Mode", timeout=5)))
hit = scroll_until(lambda boxes: next((b for b in boxes if b["text"] == "General"), None), max_scrolls=8)
check("scroll_until finds General", bool(hit))
win = info["window"]
if hit and (hit["y"] - win["y"]) / win["h"] < 0.12:
    scroll("down", amount=0.15); wait(1.0)
tap_text("General"); check("tap_text General opens it", bool(wait_for_text("About", timeout=5)))
home(); check("home()", bool(wait_for_text("Search", timeout=5)) or bool(find_text("Settings")))
open_app("com.apple.MobileSMS"); wait(1.0)
row = find_text("125 994")
if row and not find_text("Encrypted"): tap(row[0]["x"], row[0]["y"]); wait(1.0)
field = [o for o in ocr() if "message" in o["text"].lower() and o["y"] > 700]
check("Messages field visible", bool(field))
if field:
    f = field[0]; tap(f["x"], f["y"]); wait(0.8)
    type_text("Draft ăî from phone-harness"); wait(1.0)
    check("type_text paste", any("Draft" in o["text"] for o in ocr() if o["y"] > f["y"] - 40))
    type_text(" keys", keystrokes=True); wait(0.8)
    check("type_text keystrokes", any("keys" in o["text"] for o in ocr() if o["y"] > f["y"] - 40))
    press("cmd+a"); press("delete"); wait(0.8)
    check("draft cleared (cmd+a, delete)", not any("Draft" in o["text"] for o in ocr() if o["y"] > f["y"] - 40))
home()
check("list_apps", "com.apple.Preferences" in list_apps(include_system=True))
check("shell(info lockState)", "passcodeRequired" in shell("info lockState"))
print("\n" + ("ALL PASS" if not fails else "FAILED: " + ", ".join(fails)))
sys.exit(1 if fails else 0)
