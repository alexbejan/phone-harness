"""Diagnostics: `phone-harness --doctor` walks the ladder for the phone the
helpers would drive — the config default, or `--doctor ios|android`."""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _check(label, ok, hint="", fatal=True):
    """Print a check; a fatal failure is remembered for the verdict."""
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label}" + (f" — {hint}" if not ok and hint else ""))
    if not ok and fatal:
        _failures.append(label)
    return ok


_failures = []


def run_doctor(platform=None):
    from . import config
    platform = (platform or config.get("platform")).lower()
    print(f"phone-harness doctor — {platform}"
          f"{'' if platform == config.get('platform') else '  (default is ' + config.get('platform') + ')'}\n")
    _failures.clear()
    if platform == "android":
        _doctor_android()
    elif platform == "devicehub":
        _doctor_devicehub()
    else:
        _doctor_ios()
    _doctor_jev()
    ok = not _failures
    print("\nall clear" if ok else "\nfix the FAILs above, then re-run")
    return 0 if ok else 1


# --- iPhone: pyobjc -> permissions -> Mirroring -> capture -> OCR -----------

def _doctor_jev():
    from . import config
    if not config.get("jev.enabled"):
        _check("Jev judgements: off (phone-harness config set jev.enabled true to opt in; "
               "screen text then leaves the machine)", True, fatal=False)
        return
    try:
        from jevkit import keys, config as jc
    except ImportError:
        _check("Jev judgements: jev.enabled but jevkit not installed", False,
               "uv pip install -e ~/Documents/jevkit into this venv", fatal=False)
        return
    src = keys.source()
    _check(f"Jev judgements: on, model {jc.MODEL}, key from {src or 'nowhere'}", bool(src),
           "add Keychain item TYPESAFE_API_KEY or set the env var", fatal=False)


def _doctor_ios():
    try:
        import Quartz, Vision, AppKit  # noqa: F401
        _check("pyobjc frameworks (Quartz, Vision, AppKit)", True)
    except ImportError as e:
        _check("pyobjc frameworks", False,
               f"pip install pyobjc-framework-Quartz pyobjc-framework-Vision "
               f"pyobjc-framework-Cocoa ({e})")
        return

    from ApplicationServices import AXIsProcessTrusted
    _check("Accessibility permission (taps & keystrokes)", AXIsProcessTrusted(),
           "System Settings > Privacy & Security > Accessibility: enable your terminal")

    import Quartz as Q
    _check("Screen Recording permission (seeing the phone)",
           bool(Q.CGPreflightScreenCaptureAccess()),
           "System Settings > Privacy & Security > Screen Recording: enable your terminal")

    from . import mirror
    _check(f"{mirror.APP_NAME} installed", Path(mirror.APP_PATH).exists(),
           "requires macOS Sequoia+ with a paired iPhone")

    running = mirror.running_app() is not None
    _check(f"{mirror.APP_NAME} running", running,
           "will auto-launch on first use — not fatal", fatal=False)

    win = mirror.find_window()
    _check("mirroring window found", win is not None,
           "open iPhone Mirroring once manually to pair the phone")
    if not win:
        return

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        path = f.name
    try:
        # Never crash here: a missing Screen Recording grant is exactly what
        # this check exists to report.
        r = subprocess.run(["screencapture", "-x", "-o", "-l", str(win["id"]), path],
                           capture_output=True)
        size = os.path.getsize(path) if os.path.exists(path) else 0
        good = r.returncode == 0 and size > 20_000
        _check(f"window capture works ({size} bytes)", good,
               "capture failed or is blank — Screen Recording permission "
               "needs a terminal restart to take effect")
        if good:
            from . import ocr
            n = len(ocr.recognize(path, win))
            _check(f"Vision OCR works ({n} text boxes)", True)
    finally:
        if os.path.exists(path):
            os.unlink(path)

    from . import ios
    state = ios.IPhone().send("session.state")
    _check(f"session state: {state}", state == "ready",
           "an interstitial is up (iPhone in Use / Connect / Mac Locked) — "
           "clear it on the Mac; lock the iPhone if it says in use", fatal=False)


# --- Device Hub: pyobjc -> permissions -> Xcode 27 -> devicectl -> phone ->
# --- Device Hub window -> sharing -> geometry -> native screenshot -> OCR ----

def _doctor_devicehub():
    try:
        import Quartz, Vision, AppKit  # noqa: F401
        _check("pyobjc frameworks (Quartz, Vision, AppKit)", True)
    except ImportError as e:
        _check("pyobjc frameworks", False,
               f"pip install pyobjc-framework-Quartz pyobjc-framework-Vision "
               f"pyobjc-framework-Cocoa ({e})")
        return
    from ApplicationServices import AXIsProcessTrusted
    _check("Accessibility permission (taps, keystrokes, menus)", AXIsProcessTrusted(),
           "System Settings > Privacy & Security > Accessibility: enable your terminal")
    import Quartz as Q
    _check("Screen Recording permission (locating the phone in the window)",
           bool(Q.CGPreflightScreenCaptureAccess()),
           "System Settings > Privacy & Security > Screen Recording: enable your terminal")

    from . import devicehub as dh
    _check(f"{dh.APP_NAME} installed ({dh.APP_PATH})", Path(dh.APP_PATH).exists(),
           "needs Xcode 27; `xcode-select -p` must point at it")
    try:
        ver = subprocess.run(["xcrun", "devicectl", "--version"], capture_output=True,
                             text=True, timeout=20).stdout.strip()
        _check(f"devicectl works ({ver})", bool(ver), "xcrun devicectl --version failed")
    except Exception as e:  # noqa: BLE001
        _check("devicectl works", False, str(e)[:120])
        return
    try:
        phone = dh.DeviceHub()
    except RuntimeError as e:
        _check("a phone is connected to CoreDevice", False, str(e)[:200])
        return
    info = phone.info()
    _check(f"phone: {info['name']} ({info['model']}, iOS {info['os']}, "
           f"{info['transport']}, tunnel {info['tunnel']}) {phone.udid}",
           info["tunnel"] == "connected", "plug the cable in / pair it in Device Hub")
    _check(f"Developer Mode: {info['developer_mode']}", info["developer_mode"] == "enabled",
           "Settings > Privacy & Security > Developer Mode on the phone, then relaunch Device Hub")
    _check(f"developer disk image services: {info['ddi']}", bool(info["ddi"]),
           "wait for Xcode to prepare the device", fatal=False)
    disp = phone.display()
    _check(f"display {disp['w']}x{disp['h']} px, chrome {disp['chrome']!r}", True)
    if disp["chrome"] not in dh.CHROME_INSETS:
        from . import config
        _check("screen inset known for this chrome", bool(config.get("devicehub.inset")),
               "measure the screen inside the outline ring once and `config set "
               "devicehub.inset '[l,t,r,b]'`")

    _check(f"{dh.APP_NAME} running", dh.running_app() is not None,
           "open it: Xcode > Open Developer Tool > Device Hub")
    if dh.running_app() is None:
        return
    win = dh.find_window()
    _check(f"window found: {win['title']!r}" if win else "window found", win is not None,
           "Device Hub has no window")
    if not win:
        return
    state = phone.send("session.state")
    hints = {"not-selected": "select the phone in the sidebar (the harness does this itself on first use)",
             "not-sharing": "click View Screen (the harness does this itself on first use)",
             "unavailable": "Screen Sharing Unavailable: quit and relaunch Device Hub, then View Screen",
             "locked": "unlock the phone", "no-device": "cable / pairing"}
    _check(f"session state: {state}", state == "ready", hints.get(state, ""))
    if state != "ready":
        return
    g = phone._screen_geometry(force=True)
    _check(f"phone screen located at ({g['x']:.0f}, {g['y']:.0f}) {g['w']:.0f}x{g['h']:.0f} pt "
           f"(ring {g['ring'][2]}x{g['ring'][3]} px, aspect {g['ring'][2]/g['ring'][3]:.3f})", True)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        path = f.name
    try:
        p, b = phone.send("screen.capture", path=path)
        size = os.path.getsize(p)
        _check(f"native device screenshot works ({size} bytes)", size > 20_000,
               "devicectl capture screenshot failed")
        from . import ocr
        n = len(ocr.recognize(p, b))
        _check(f"Vision OCR works ({n} text boxes, mapped to Mac screen points)", n > 0,
               "no text recognised; is the phone screen on?", fatal=False)
    finally:
        if os.path.exists(path):
            os.unlink(path)
    front = dh.is_frontmost()
    _check(f"Device Hub frontmost: {front}", True)

    # Cua Driver route (optional): focus-free taps and scrolls. Only checked
    # when the route resolved to it, so a machine without Cua is not failed.
    if phone.input_route == "cua":
        try:
            v = phone.verify_with_cua()
            _check(f"Cua Driver route active; its window read agrees with the "
                   f"backend ({phone._session_state()})", v["agrees"],
                   "Cua sees a different sharing state than devicectl", fatal=False)
        except dh.CuaUnavailable as e:
            _check("Cua Driver route active but verify_with_cua works", False,
                   str(e)[:160], fatal=False)
    else:
        from . import config
        want = str(config.get("devicehub.input") or "auto").lower()
        _check(f"input route: cgevents (devicehub.input={want}; Cua daemon "
               f"{'off' if want != 'cgevents' else 'not requested'})", True)


# --- Android: adb -> a phone -> authorised -> awake -> tree ------------------

_ADB_INSTALL = {"darwin": "brew install android-platform-tools",
                "win32": "winget install Google.PlatformTools"}.get(sys.platform, "apt install adb (or your distro's android-tools)")
_SCRCPY_INSTALL = {"darwin": "brew install scrcpy", "win32": "winget install Genymobile.scrcpy"}.get(sys.platform, "apt install scrcpy")


def _doctor_android():
    from . import config
    adb = str(config.get("android.adb"))
    if not shutil.which(adb):
        _check(f"adb found ({adb})", False,
               _ADB_INSTALL + ", or set android.adb to the binary")
        return
    _check(f"adb found ({shutil.which(adb)})", True)
    _check("scrcpy found (optional: live mirror during `android awake`)",
           bool(shutil.which("scrcpy")), _SCRCPY_INSTALL + " — not required", fatal=False)

    from . import android
    phone = android.Android()
    state = phone.send("session.state")
    hints = {
        "no-device": "plug in with USB debugging on and tap Allow, or "
                     "Wireless debugging + `phone-harness android pair CODE`",
        "unauthorized": "tap Allow on the phone's 'Allow USB debugging?' prompt",
        "offline": "unplug/replug, or toggle Wireless debugging off and on",
        "locked": "unlock the phone (`phone-harness android awake` keeps it so)",
        "no-adb": "adb did not answer",
    }
    _check(f"a phone is reachable and ready (state: {state})",
           state in ("ready", "locked"), hints.get(state, ""))
    if state == "locked":
        _check("phone unlocked", False, hints["locked"], fatal=False)
    if state not in ("ready",):
        return

    b = phone.send("screen.bounds")
    label = android._phone_label(b["id"]) if b else "?"
    _check(f"talking to {label} ({b['id']}), screen {b['w']}x{b['h']}", bool(b))
    try:
        n = len(phone.send("tree"))
        _check(f"accessibility tree readable ({n} nodes)", n > 0)
    except RuntimeError as e:
        _check("accessibility tree readable", False, str(e)[:120], fatal=False)
    reg = config.devices_of("android")
    _check(f"remembered phones: {', '.join(reg['phones']) or 'none'}; primary: "
           f"{reg['primary'] or 'none'}", True)
