"""Device Hub backend: the op vocabulary over Xcode 27's Device Hub.

Device Hub (Xcode 27, `/Applications/Xcode.app/Contents/Applications/
DeviceHub.app`, bundle id `com.apple.dt.Devices`) shares a paired iPhone's
screen and forwards clicks and keystrokes to it. It works where iPhone
Mirroring is unavailable (Romania, no-Apple-ID test phones, iOS 27 devices
paired only for development), and it exposes a lot more than Mirroring does,
which is why this backend is not a copy of ios.py:

  EYES   `xcrun devicectl device capture screenshot` returns the device's own
         framebuffer as a PNG (1125x2436 on an iPhone 11 Pro) in ~0.7 s,
         regardless of how small Device Hub draws the phone on the Mac. OCR
         runs on that, not on a window capture, so text is read at native
         resolution.

  HANDS  CGEvents posted into the Device Hub window. The shared screen is a
         custom-drawn surface with no accessibility children, like Mirroring's
         video stream, so a tap is a click at the Mac screen point where the
         device pixel is drawn. That mapping is the whole job of this file:
         Device Hub's window size and zoom level vary, so the phone-screen
         rect is re-derived from a window capture on every call.

  SIDE   `devicectl` also launches apps by bundle id (no Spotlight), lists
         apps, sets the device pasteboard (exact Unicode paste), and reports
         lock state and Developer Mode for the doctor. Home, App Switcher,
         Lock and Screenshot are Device Hub menu items, pressed through the
         accessibility API.

Measured 2026-09-17 on a Mac mini (macOS 27.0, Xcode 27.0 27A266a, Device Hub
27.0, devicectl 642.16) driving an iPhone 11 Pro on iOS 27.0:

  - A click at the mapped point taps. A slow touch-drag (0.35 s / 14 steps)
    scrolls a list by the dragged distance; a fast drag (0.12 s / 6 steps)
    flicks with momentum; a 0.3 s horizontal drag flips Home Screen pages; a
    1.2 s press-and-hold enters jiggle mode. The opposite of Mirroring on
    macOS 26, where vertical drags are dropped.
  - Scroll-wheel events do nothing, with or without trackpad phases, pixel or
    line units, pointer over the window or not. `input.scroll` is therefore
    a touch-drag.
  - Keystrokes reach the phone whenever Device Hub is frontmost and the phone
    has a focused field, WITHOUT the toolbar's "Capture Keyboard" toggle.
    Modifier flags are forwarded: cmd+a, cmd+v, delete all work, unlike
    Mirroring which drops the flag mask. Nothing arrives while another Mac
    app is frontmost.
  - cmd+v pastes the device pasteboard, and `devicectl device pasteboard
    copy` sets it from stdin (Unicode verified). The Mac clipboard is also
    synced to the phone, but devicectl is deterministic, so paste uses it.
  - SkyLight event records addressed to the Device Hub window (the trick
    background.py uses to drive Mirroring without focus) do land, but Device
    Hub becomes the frontmost app in the process, so there is no background
    mode here. Every input op activates Device Hub first, like mirror.py.
  - The phone chrome ("com.apple.dt.devicekit.chrome.phone2") is drawn as a
    thin light outline ring, a black bezel, then the screen with rounded
    corners and a notch. The ring's bounding box keeps the same proportions
    at every zoom level (aspect 0.506-0.510 from Zoom Out to Zoom to Fit), so
    the screen rect is that box inset by fixed fractions.
  - The floating Home/Screenshot/Rotate toolbar only exists in the
    accessibility tree while the pointer hovers the canvas, so "toolbar
    present" is not a sharing indicator. "View Screen" (an AXButton whose
    description, not title, carries the text) means the phone is selected but
    not sharing; the static text "Screen Sharing Unavailable" means Device
    Hub has to be relaunched (it stays stale after a phone-side change such as
    enabling Developer Mode).
  - After `Stop Screen Sharing` or a relaunch, pressing View Screen restores
    the session in a few seconds with the same geometry.
  - Device Hub owns the phone's touch HID service while it runs. A direct
    CoreDevice HID client (ipbtools/ipb) could press Home but its taps never
    landed on this phone even with Device Hub quit, so there is no
    window-free input route yet; screenshots are window-free already.

What Device Hub cannot do appears as absence: no `nav.back` (iOS has none),
no `apps.current` (devicectl lists processes but not the foreground app), no
`tree` (the shared screen is pixels).
"""
import json
import os
import shlex
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import ApplicationServices as _AS
import Quartz
from AppKit import NSRunningApplication

from . import mirror as _keys      # keycode tables and key posting only
from . import ocr as _vision
from .transport import Backend, Unsupported

APP_NAME = "Device Hub"
BUNDLE_ID = "com.apple.dt.Devices"
APP_PATH = "/Applications/Xcode.app/Contents/Applications/DeviceHub.app"

TMP = Path(tempfile.gettempdir()) / "phone-harness"
TMP.mkdir(exist_ok=True)

# Screen rect inside the chrome's outline-ring bounding box, as fractions of
# the ring (left, top, right, bottom). Measured at Zoom to Actual Size on a
# 2x display: ring 536x1052 px, screen 451x977 px at offset (42, 38). The
# ratio held at every zoom level tried. Keyed by the chrome id that
# `devicectl device info displays` reports, so other bezels can be added.
CHROME_INSETS = {
    "com.apple.dt.devicekit.chrome.phone2": (42 / 536, 38 / 1052, 43 / 536, 37 / 1052),
}
# Ring aspect (w/h) per chrome, to reject a blob that is not the phone.
CHROME_RING_ASPECT = {"com.apple.dt.devicekit.chrome.phone2": 0.508}
_ASPECT_TOL = 0.04

# Device Hub menu items used for hardware controls: (menu, item).
_MENU = {"home": ("Controls", "Home"), "recents": ("Controls", "App Switcher"),
         "lock": ("Controls", "Lock"), "screenshot": ("Controls", "Screenshot")}


# --- Cua Driver: an optional focus-free route for taps and scrolls ----------
#
# Cua Driver (cua.ai/cua-driver, the daemon behind the superset:computer skill)
# posts input to a target pid+window WITHOUT bringing it to the front. Measured
# 2026-09-17 against Device Hub: a background `click` taps the phone 3/3 with
# Finder staying frontmost the whole time, and a `drag` scrolls a list 0.96:1
# (Cua fronts the window for under a millisecond and restores focus, so no
# window pops up). That is the whole reason to use it: the CGEvent path has to
# bring Device Hub frontmost before every action, and this one does not.
#
# What Cua CANNOT do to the phone, measured and kept on the CGEvent/AX path:
#   - type_text: AX insertion writes garbage into the iOS field.
#   - cmd/ctrl/alt combos and paste (cmd+v): the modifier is not forwarded to
#     the phone, so cmd+v types a bare 'v'.
#   - invoke_menu (Home/App Switcher/Lock): refused on Device Hub's SwiftUI
#     menu.
#   - long press: `click` has no hold.
# So this helper drives only tap, scroll, swipe and drag; the backend keeps
# keys, paste and menus on the CGEvent+accessibility path.

class CuaUnavailable(RuntimeError):
    pass


class _Cua:
    """Thin wrapper over `cua-driver call <tool> <json>` for one Device Hub
    window. Coordinates in take Mac screen points and are converted to Cua's
    window-local screenshot pixels using the window's own screenshot scale."""

    def __init__(self):
        self._session = None
        self._wid = None
        self._win_w = None
        self._scale = None            # Cua screenshot px per window point

    @staticmethod
    def binary():
        return shutil.which("cua-driver")

    @classmethod
    def daemon_up(cls):
        if not cls.binary():
            return False
        r = subprocess.run([cls.binary(), "status"], capture_output=True,
                           text=True, timeout=10)
        return r.returncode == 0 and "running" in (r.stdout + r.stderr).lower()

    def _call(self, tool, timeout=20, **kw):
        if not self.binary():
            raise CuaUnavailable("cua-driver is not on PATH")
        r = subprocess.run([self.binary(), "call", tool, json.dumps(kw)],
                           capture_output=True, text=True, timeout=timeout)
        out = (r.stdout or r.stderr).strip()
        try:
            data = json.loads(out)
        except ValueError:
            if r.returncode != 0:
                raise CuaUnavailable(f"cua {tool}: {out[:200]}")
            return {}
        if isinstance(data, dict) and (data.get("error") or data.get("code")
                                       in ("background_unavailable", "refused")):
            raise CuaUnavailable(f"cua {tool} refused: {data.get('code') or data.get('error')}")
        return data

    def session(self):
        if self._session is None:
            self._session = f"phone-harness-devicehub-{os.getpid()}"
            self._call("start_session", session=self._session)
        return self._session

    def _sync(self, win):
        """Refresh the window id and screenshot scale if the window changed."""
        if self._wid == win["id"] and self._win_w == win["w"] and self._scale:
            return
        st = self._call("get_window_state", pid=_pid(), window_id=win["id"],
                        session=self.session(), max_elements=1)
        sw = st.get("screenshot_width")
        wb = st.get("window_bounds") or {}
        if not sw or not wb.get("width"):
            raise CuaUnavailable("cua get_window_state gave no screenshot scale")
        self._wid = win["id"]
        self._win_w = win["w"]
        self._scale = sw / wb["width"]
        self._win = wb

    def _px(self, win, x, y):
        self._sync(win)
        return (x - self._win["x"]) * self._scale, (y - self._win["y"]) * self._scale

    def tap(self, win, x, y):
        px, py = self._px(win, x, y)
        self._call("click", pid=_pid(), window_id=win["id"], x=px, y=py,
                   delivery_mode="background", session=self.session())

    def drag(self, win, x1, y1, x2, y2, duration_ms=700, steps=40):
        self._sync(win)
        fx, fy = self._px(win, x1, y1)
        tx, ty = self._px(win, x2, y2)
        # Cua refuses drag in background mode; foreground fronts the window for
        # under a millisecond and restores focus, so the user's app stays put.
        self._call("drag", pid=_pid(), window_id=win["id"], from_x=fx, from_y=fy,
                   to_x=tx, to_y=ty, duration_ms=duration_ms, steps=steps,
                   delivery_mode="foreground", session=self.session())

    def window_state(self):
        """(screenshot_png_path, [(role,label), ...]) — an independent read of
        the Mac side for verify_with_cua()."""
        import base64
        win = find_window()
        if win is None:
            raise CuaUnavailable("no Device Hub window")
        st = self._call("get_window_state", pid=_pid(), window_id=win["id"],
                        session=self.session(), max_elements=60)
        path = str(TMP / "devicehub-cua.png")
        b64 = st.get("screenshot_png_b64")
        if b64:
            with open(path, "wb") as f:
                f.write(base64.b64decode(b64))
        labels = [(e.get("role"), e.get("label")) for e in st.get("elements", [])
                  if e.get("label")]
        return path, labels


# --- devicectl --------------------------------------------------------------

def devicectl(*args, udid=None, timeout=60, json_out=True, stdin=None):
    """Run `xcrun devicectl device <args>`; returns the parsed `result` when
    json_out, else the CompletedProcess. Raises RuntimeError on failure."""
    cmd = ["xcrun", "devicectl", "device", *args]
    if udid:
        cmd += ["--device", udid]
    if json_out:
        cmd += ["-q", "--json-output", "-"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                       input=stdin)
    if r.returncode != 0:
        raise RuntimeError(f"devicectl {' '.join(args)} failed: "
                           f"{(r.stderr or r.stdout).strip()[:300]}")
    if not json_out:
        return r
    try:
        return json.loads(r.stdout)["result"]
    except (ValueError, KeyError) as e:
        raise RuntimeError(f"devicectl {' '.join(args)}: unreadable JSON ({e})")


def list_devices():
    """Physical devices CoreDevice knows: [{name, udid, state, model, os}]."""
    r = subprocess.run(["xcrun", "devicectl", "list", "devices", "-q",
                        "--json-output", "-"], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"devicectl list devices failed: {r.stderr.strip()[:300]}")
    out = []
    for d in json.loads(r.stdout)["result"]["devices"]:
        hw, dp, cp = (d.get("hardwareProperties", {}), d.get("deviceProperties", {}),
                      d.get("connectionProperties", {}))
        if hw.get("reality", "physical") != "physical":
            continue
        out.append({"name": dp.get("name"), "udid": hw.get("udid"),
                    "state": cp.get("tunnelState"), "model": hw.get("marketingName"),
                    "os": dp.get("osVersionNumber"),
                    "developer_mode": dp.get("developerModeStatus"),
                    "platform": hw.get("platform")})
    return out


# --- Device Hub process / window -------------------------------------------

def _pid():
    """Device Hub's pid from the process table.

    LaunchServices reports pid -1 for this app (NSWorkspace,
    runningApplicationsWithBundleIdentifier_ and
    runningApplicationWithProcessIdentifier_ all agree on -1 while the process
    is plainly running), so the accessibility and window-list calls, which
    need a real pid, get it from pgrep instead."""
    r = subprocess.run(["pgrep", "-x", "DeviceHub"], capture_output=True, text=True)
    pids = [int(x) for x in r.stdout.split()]
    return pids[0] if pids else None


def running_app():
    """The NSRunningApplication for Device Hub (used only to activate it; its
    processIdentifier() is -1, see _pid), or None when it is not running."""
    if _pid() is None:
        return None
    apps = NSRunningApplication.runningApplicationsWithBundleIdentifier_(BUNDLE_ID)
    return apps[0] if apps else None


def find_window():
    """{x, y, w, h, id, title} of the main Device Hub window, or None."""
    pid = _pid()
    if pid is None:
        return None
    wins = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID) or []
    for w in wins:                       # front-to-back
        if w.get("kCGWindowOwnerPID") == pid and w.get("kCGWindowLayer", 1) == 0 \
                and w.get("kCGWindowBounds", {}).get("Height", 0) > 100:
            b = w["kCGWindowBounds"]
            return {"x": b["X"], "y": b["Y"], "w": b["Width"], "h": b["Height"],
                    "id": int(w["kCGWindowNumber"]), "title": w.get("kCGWindowName", "")}
    return None


# --- accessibility helpers --------------------------------------------------

def _ax(node, attr):
    err, val = _AS.AXUIElementCopyAttributeValue(node, attr, None)
    return None if err else val


def _ax_app():
    pid = _pid()
    return _AS.AXUIElementCreateApplication(pid) if pid else None


def _ax_window():
    app = _ax_app()
    wins = _ax(app, "AXWindows") if app else None
    return wins[0] if wins else None


def _ax_frame(node):
    pos, size = _ax(node, "AXPosition"), _ax(node, "AXSize")
    if pos is None or size is None:
        return None
    ok, p = _AS.AXValueGetValue(pos, _AS.kAXValueCGPointType, None)
    ok2, s = _AS.AXValueGetValue(size, _AS.kAXValueCGSizeType, None)
    return (p.x, p.y, s.width, s.height) if ok and ok2 else None


def _ax_walk(root, pred, limit=1, max_depth=30):
    """Depth-first search for nodes matching pred(node). Stops at `limit`."""
    out = []

    def walk(n, d):
        if d > max_depth or len(out) >= limit:
            return
        if pred(n):
            out.append(n)
        for k in _ax(n, "AXChildren") or []:
            walk(k, d + 1)
    if root is not None:
        walk(root, 0)
    return out


def _label(node):
    return _ax(node, "AXTitle") or _ax(node, "AXDescription") or ""


def ax_control(text, roles=("AXButton", "AXCheckBox", "AXRadioButton", "AXMenuButton")):
    """A toolbar/canvas control by its title or description. Device Hub's
    SwiftUI controls carry the text in AXDescription, not AXTitle."""
    hits = _ax_walk(_ax_window(), lambda n: _ax(n, "AXRole") in roles
                    and _label(n) == text)
    return hits[0] if hits else None


def ax_static_texts():
    """Every static text in the window, for state detection."""
    return [_ax(n, "AXValue") for n in
            _ax_walk(_ax_window(), lambda n: _ax(n, "AXRole") == "AXStaticText",
                     limit=400) if _ax(n, "AXValue")]


def ax_menu_item(menu, item):
    app = _ax_app()
    for m in _ax(_ax(app, "AXMenuBar"), "AXChildren") or []:
        if _ax(m, "AXTitle") != menu:
            continue
        for sub in _ax(m, "AXChildren") or []:
            for it in _ax(sub, "AXChildren") or []:
                if _ax(it, "AXTitle") == item:
                    return it
    return None


def _ax_press(node):
    return _AS.AXUIElementPerformAction(node, "AXPress") == 0


# --- focus ------------------------------------------------------------------

def focus_probe():
    """(app_frontmost, depth): see mirror.focus_probe for why AXFrontmost and
    the window list are read from different sources."""
    pid = _pid()
    if pid is None:
        return None, None
    err, val = _AS.AXUIElementCopyAttributeValue(
        _AS.AXUIElementCreateApplication(pid), "AXFrontmost", None)
    front = None if err else bool(val)
    wins = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID) or []
    layer0 = [w for w in wins if w.get("kCGWindowLayer", 1) == 0]
    depth = next((i for i, w in enumerate(layer0)
                  if w.get("kCGWindowOwnerPID") == pid), None)
    return front, depth


def is_frontmost():
    front, depth = focus_probe()
    return bool(front) and depth == 0


def activate(timeout=2.5):
    """Bring Device Hub frontmost and confirm it. Never launches it."""
    app = running_app()
    if app is None:
        raise RuntimeError(f"{APP_NAME} isn't running — open it (Xcode > Open "
                           "Developer Tool > Device Hub), select the phone and "
                           "click View Screen.")
    if is_frontmost():
        return
    deadline = time.time() + timeout
    win = _ax_window()
    while time.time() < deadline:
        app.activateWithOptions_(1 << 1)  # NSApplicationActivateIgnoringOtherApps
        if win is not None:
            _AS.AXUIElementPerformAction(win, "AXRaise")
        time.sleep(0.08)
        if is_frontmost():
            return
    raise RuntimeError(f"could not bring {APP_NAME} frontmost after {timeout:.1f}s; "
                       "input would land in another app, so nothing was sent.")


# --- geometry: where is the phone screen drawn ------------------------------

def _load_png(path):
    from Foundation import NSURL
    src = Quartz.CGImageSourceCreateWithURL(NSURL.fileURLWithPath_(str(path)), None)
    img = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)
    if img is None:
        raise RuntimeError(f"cannot read {path}")
    data = bytes(Quartz.CGDataProviderCopyData(Quartz.CGImageGetDataProvider(img)))
    return data, Quartz.CGImageGetBytesPerRow(img), Quartz.CGImageGetWidth(img), \
        Quartz.CGImageGetHeight(img)


def largest_blob(path, region, ds=4, tol=10):
    """Bounding box (image px) of the largest 8-connected blob of pixels that
    differ from the region's background colour, on a ds-downsampled grid, or
    None. region = (x, y, w, h) in image pixels.

    The canvas is a flat colour; the phone chrome (outline ring + black bezel
    + screen) is one connected blob on it. Labels under the phone and the
    floating toolbar are separate, smaller blobs, which is why "largest
    blob" and not "everything that is not background"."""
    buf, bpr, W, H = _load_png(path)
    rx, ry, rw, rh = (int(v) for v in region)
    rx, ry = max(rx, 0), max(ry, 0)
    rw, rh = min(rw, W - rx), min(rh, H - ry)
    if rw <= ds * 4 or rh <= ds * 4:
        return None, None

    def px(x, y):
        o = y * bpr + x * 4
        return buf[o], buf[o + 1], buf[o + 2]
    samples = [px(rx + dx, ry + dy) for dx in (4, rw // 2, rw - 5)
               for dy in (4, rh // 2, rh - 5)]
    bg = max(set(samples), key=samples.count)
    gw, gh = rw // ds, rh // ds
    grid = bytearray(gw * gh)
    b0, b1, b2 = bg
    for gy in range(gh):
        base = (ry + gy * ds) * bpr
        for gx in range(gw):
            o = base + (rx + gx * ds) * 4
            if abs(buf[o] - b0) > tol or abs(buf[o + 1] - b1) > tol \
                    or abs(buf[o + 2] - b2) > tol:
                grid[gy * gw + gx] = 1
    seen = bytearray(gw * gh)
    best = None
    for start in range(gw * gh):
        if not grid[start] or seen[start]:
            continue
        stack = [start]
        seen[start] = 1
        x0 = x1 = start % gw
        y0 = y1 = start // gw
        while stack:
            i = stack.pop()
            x, y = i % gw, i // gw
            x0, x1, y0, y1 = min(x0, x), max(x1, x), min(y0, y), max(y1, y)
            for dy in (-1, 0, 1):
                ny = y + dy
                if not 0 <= ny < gh:
                    continue
                for dx in (-1, 0, 1):
                    nx = x + dx
                    if 0 <= nx < gw:
                        j = ny * gw + nx
                        if grid[j] and not seen[j]:
                            seen[j] = 1
                            stack.append(j)
        area = (x1 - x0 + 1) * (y1 - y0 + 1)
        if best is None or area > best[0]:
            best = (area, x0, y0, x1, y1)
    if best is None:
        return None, bg
    _, x0, y0, x1, y1 = best
    L, T = rx + x0 * ds, ry + y0 * ds
    R, B = min(rx + x1 * ds + ds - 1, rx + rw - 1), min(ry + y1 * ds + ds - 1, ry + rh - 1)

    def diff(x, y):
        p = px(x, y)
        return abs(p[0] - b0) > tol or abs(p[1] - b1) > tol or abs(p[2] - b2) > tol
    while L < R and not any(diff(L, y) for y in range(T, B + 1, 2)):
        L += 1
    while R > L and not any(diff(R, y) for y in range(T, B + 1, 2)):
        R -= 1
    while T < B and not any(diff(x, T) for x in range(L, R + 1, 2)):
        T += 1
    while B > T and not any(diff(x, B) for x in range(L, R + 1, 2)):
        B -= 1
    return (L, T, R - L + 1, B - T + 1), bg


def canvas_region(win):
    """The canvas in window-relative points: below the toolbar, between the
    sidebar and inspector splitters (whichever are present)."""
    root = _ax_window()
    top = 52.0                                       # toolbar height, fallback
    tb = _ax_walk(root, lambda n: _ax(n, "AXRole") == "AXToolbar")
    if tb:
        f = _ax_frame(tb[0])
        if f:
            top = f[1] + f[3] - win["y"]
    left, right = 0.0, win["w"]
    for sp in _ax_walk(root, lambda n: _ax(n, "AXRole") == "AXSplitter", limit=4):
        f = _ax_frame(sp)
        if not f:
            continue
        x = f[0] - win["x"]
        if x < win["w"] / 2:
            left = max(left, x + 1)
        else:
            right = min(right, x - 1)
    return left, top, right - left, win["h"] - top


class DeviceHub(Backend):
    name = "devicehub"

    def __init__(self, udid=None, geometry_ttl=0.8):
        from . import config
        self.udid = udid or config.get("devicehub.udid") or self._pick_udid()
        self._display = None
        self._geom = None
        self._geom_at = 0.0
        self._ttl = geometry_ttl
        self._info = None
        # Input route. "cua" and "auto" (when the daemon answers) send taps,
        # scrolls and swipes through Cua Driver, which does not steal focus;
        # everything else stays on the CGEvent+AX path. "cgevents" never uses
        # Cua. See the _Cua helper for what Cua can and cannot do to the phone.
        want = str(config.get("devicehub.input") or "auto").lower()
        self._cua = None
        if want in ("cua", "auto"):
            if _Cua.daemon_up():
                self._cua = _Cua()
            elif want == "cua":
                raise RuntimeError(
                    "devicehub.input=cua but the Cua Driver daemon is not "
                    "running. Start it (`open -n -g -a CuaDriver --args serve`) "
                    "or set `phone-harness config set devicehub.input auto`.")
        self.input_route = "cua" if self._cua else "cgevents"

    @staticmethod
    def _pick_udid():
        phones = [d for d in list_devices() if d["platform"] == "iOS"]
        connected = [d for d in phones if d["state"] == "connected"]
        if len(connected) == 1:
            return connected[0]["udid"]
        names = ", ".join(f"{d['name']} ({d['udid']}, {d['state']})" for d in phones) or "none"
        raise RuntimeError(
            f"{'no' if not connected else 'more than one'} iPhone connected to "
            f"CoreDevice; set one with `phone-harness config set devicehub.udid "
            f"<udid>`. Known: {names}")

    # --- device facts (cached per instance) ---

    def info(self):
        """{name, model, os, developer_mode, tunnel, pairing}"""
        if self._info is None:
            d = devicectl("info", "details", udid=self.udid)
            dp, hw, cp = d["deviceProperties"], d["hardwareProperties"], d["connectionProperties"]
            self._info = {"name": dp.get("name"), "model": hw.get("marketingName"),
                          "os": dp.get("osVersionNumber"),
                          "developer_mode": dp.get("developerModeStatus"),
                          "ddi": dp.get("ddiServicesAvailable"),
                          "tunnel": cp.get("tunnelState"), "pairing": cp.get("pairingState"),
                          "transport": cp.get("transportType")}
        return self._info

    def display(self):
        """{w, h, chrome, orientation} of the primary display, device pixels."""
        if self._display is None:
            d = devicectl("info", "displays", udid=self.udid)["displays"][0]
            (x0, y0), (x1, y1) = d["bounds"]
            self._display = {"w": int(x1 - x0), "h": int(y1 - y0),
                             "chrome": d.get("chromeIdentifier", ""),
                             "orientation": d.get("currentOrientation")}
        return self._display

    # --- geometry ---

    def _screen_geometry(self, force=False):
        """{x, y, w, h, id, ring, scale} — the phone screen in Mac screen
        points, re-derived from a fresh window capture (cached `ttl` s)."""
        if not force and self._geom and time.time() - self._geom_at < self._ttl:
            return self._geom
        win = find_window()
        if win is None:
            raise RuntimeError(f"{APP_NAME} has no window; open it and select the phone.")
        path = TMP / "devicehub-window.png"
        r = subprocess.run(["screencapture", "-x", "-o", "-l", str(win["id"]), str(path)],
                           capture_output=True)
        if r.returncode != 0 or not path.exists() or path.stat().st_size < 1000:
            raise RuntimeError("window capture failed (Screen Recording permission?): "
                               + r.stderr.decode(errors="replace").strip())
        _, _, img_w, img_h = _load_png(path)
        scale = img_w / win["w"]                       # image px per point
        cx, cy, cw, ch = canvas_region(win)
        ring, bg = largest_blob(path, (cx * scale, cy * scale, cw * scale, ch * scale))
        if ring is None:
            raise RuntimeError("no phone image in the Device Hub canvas; is the "
                               "screen being shared? (click View Screen)")
        chrome = self.display()["chrome"]
        from . import config
        inset = config.get("devicehub.inset") or CHROME_INSETS.get(chrome)
        if not inset:
            raise RuntimeError(
                f"unknown device chrome {chrome!r}: no screen inset is known for "
                "it. Measure the screen inside the outline ring once and set "
                "`devicehub.inset` to [left, top, right, bottom] fractions of the ring.")
        want = CHROME_RING_ASPECT.get(chrome)
        got = ring[2] / ring[3]
        if want and abs(got - want) > _ASPECT_TOL:
            raise RuntimeError(
                f"the blob in the canvas ({ring[2]}x{ring[3]} px, aspect {got:.3f}) "
                f"is not the phone (expected ~{want:.3f}); zoom so the whole phone "
                "is visible (View > Zoom to Fit or Zoom to Actual Size) and retry.")
        l, t, rr, b = inset
        sx = ring[0] + ring[2] * l
        sy = ring[1] + ring[3] * t
        sw = ring[2] * (1 - l - rr)
        sh = ring[3] * (1 - t - b)
        self._geom = {"x": win["x"] + sx / scale, "y": win["y"] + sy / scale,
                      "w": sw / scale, "h": sh / scale, "id": win["id"],
                      "ring": ring, "scale": scale, "window": win}
        self._geom_at = time.time()
        return self._geom

    def _bounds(self):
        g = self._screen_geometry()
        return {k: g[k] for k in ("x", "y", "w", "h", "id")}

    def _screen_bounds(self):
        try:
            return self._bounds()
        except RuntimeError:
            return None

    def _screen_require(self):
        return self._bounds()

    # --- eyes ---

    def _screen_capture(self, path=None):
        """Native device screenshot; bounds are the on-screen rect the image
        maps onto, so ocr() yields tap-ready Mac points."""
        path = str(path or TMP / "devicehub.png")
        devicectl("capture", "screenshot", "--destination", path, udid=self.udid,
                  json_out=False, timeout=30)
        return path, self._bounds()

    def _screen_text(self, min_confidence=0.3):
        path, win = self._screen_capture()
        return [dict(o, source="pixels")
                for o in _vision.recognize(path, win)
                if o["confidence"] >= min_confidence]

    _screen_text_pixels = _screen_text

    # --- hands ---

    def _mouse(self, etype, x, y):
        ev = Quartz.CGEventCreateMouseEvent(None, etype, Quartz.CGPointMake(x, y),
                                            Quartz.kCGMouseButtonLeft)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)

    def _inside(self, x, y):
        b = self._bounds()
        if not (b["x"] <= x <= b["x"] + b["w"] and b["y"] <= y <= b["y"] + b["h"]):
            raise RuntimeError(f"({x:.0f}, {y:.0f}) is outside the phone screen "
                               f"{b}; refusing to click Device Hub's own UI.")

    def _input_tap(self, x, y):
        self._inside(x, y)
        if self._cua:
            try:
                self._cua.tap(self._screen_geometry()["window"], x, y)
                return
            except CuaUnavailable:
                self._cua = None      # daemon went away mid-run; fall through
        activate()
        self._mouse(Quartz.kCGEventMouseMoved, x, y)
        time.sleep(0.08)
        self._mouse(Quartz.kCGEventLeftMouseDown, x, y)
        time.sleep(0.06)
        self._mouse(Quartz.kCGEventLeftMouseUp, x, y)

    def _input_press(self, x, y, duration=1.0):
        self._inside(x, y)
        activate()
        self._mouse(Quartz.kCGEventMouseMoved, x, y)
        time.sleep(0.08)
        self._mouse(Quartz.kCGEventLeftMouseDown, x, y)
        time.sleep(duration)
        self._mouse(Quartz.kCGEventLeftMouseUp, x, y)

    def _input_drag(self, x1, y1, x2, y2, duration=0.35, steps=14, ease_out=False):
        """Touch-drag. When the Cua route is active it drives the drag (which
        pans a list 0.96:1 without stealing focus); otherwise CGEvents.

        Linear by default, which is what a swipe wants: iOS
        derives momentum from the finger's speed at release, so a linear
        drag keeps flicking after the finger lifts. `ease_out=True` slows
        the path quadratically into the end point and repeats the end point
        a few times before lifting, so the touch releases at zero speed and
        the content stops where the finger stopped. Measured on Settings, a
        364 px drag: linear 1.82x, linear + a 0.3 s still hold 1.84x (the
        phone keeps the last velocity when no touch updates arrive), ease-out
        0.90x (1:1 minus touch slop)."""
        self._inside(x1, y1)
        self._inside(x2, y2)
        if self._cua:
            try:
                self._cua.drag(self._screen_geometry()["window"], x1, y1, x2, y2,
                               duration_ms=int(max(duration, 0.4) * 1000),
                               steps=max(steps, 30))
                return
            except CuaUnavailable:
                self._cua = None
        activate()
        self._mouse(Quartz.kCGEventMouseMoved, x1, y1)
        time.sleep(0.08)
        self._mouse(Quartz.kCGEventLeftMouseDown, x1, y1)
        time.sleep(0.05)
        for i in range(1, steps + 1):
            t = i / steps
            if ease_out:
                t = 1 - (1 - t) ** 2
            self._mouse(Quartz.kCGEventLeftMouseDragged,
                        x1 + (x2 - x1) * t, y1 + (y2 - y1) * t)
            time.sleep(duration / steps)
        if ease_out:
            for _ in range(10):
                self._mouse(Quartz.kCGEventLeftMouseDragged, x2, y2)
                time.sleep(0.03)
        self._mouse(Quartz.kCGEventLeftMouseUp, x2, y2)

    def _input_scroll(self, x, y, dy, dx=0, steps=14):
        """A touch-drag: Device Hub ignores scroll-wheel events. dy < 0
        reveals content further down (the finger moves up), matching the
        convention helpers.scroll() sends. Clamped to the screen so the
        finger never leaves the phone.

        The path eases out so the touch releases at zero speed and the list
        moves by the dragged distance (0.9x measured) instead of flicking on
        (1.8x for a linear drag), which made scroll_until() skip rows."""
        b = self._bounds()
        m = 12
        x1 = min(max(x - dx / 2, b["x"] + m), b["x"] + b["w"] - m)
        x2 = min(max(x + dx / 2, b["x"] + m), b["x"] + b["w"] - m)
        y1 = min(max(y - dy / 2, b["y"] + m), b["y"] + b["h"] - m)
        y2 = min(max(y + dy / 2, b["y"] + m), b["y"] + b["h"] - m)
        dist = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
        self._input_drag(x1, y1, x2, y2, duration=max(0.4, dist / 400),
                         steps=max(steps, int(dist / 6), 10), ease_out=True)

    def _input_keys(self, combo):
        """press('return'), press('cmd+a'). Modifier flags are forwarded by
        Device Hub, so cmd/shift combos reach iOS. Return in a Messages
        field SENDS; type_text never adds one."""
        activate()
        parts = combo.lower().split("+")
        key, mods = parts[-1], parts[:-1]
        if key not in _keys._KEYCODES:
            raise ValueError(f"unknown key {key!r}")
        for m in mods:
            if m not in _keys._MOD_KEYCODES:
                raise ValueError(f"unknown modifier {m!r}")
        with _keys._holding(mods) as flags:
            for down in (True, False):
                _keys._post_key(_keys._KEYCODES[key], down, flags)
                time.sleep(0.03)

    def _input_text(self, s, delay=0.03, keystrokes=False):
        """Paste by default: the text goes to the device pasteboard through
        devicectl (exact Unicode, no autocorrect), then cmd+v. keystrokes=True
        types US-layout keycodes through iOS autocorrect."""
        if not s:
            return
        activate()
        if keystrokes:
            for i, line in enumerate(s.split("\n")):
                if i:
                    self._input_keys("return")
                for ch in line:
                    code, shifted = _keys._keycode_for(ch)
                    if code is None:
                        raise ValueError(f"cannot type {ch!r} via keycodes; use paste")
                    with _keys._holding(["shift"] if shifted else []) as flags:
                        for down in (True, False):
                            _keys._post_key(code, down, flags)
                            time.sleep(0.01)
                    time.sleep(delay)
            return
        devicectl("pasteboard", "copy", udid=self.udid, json_out=False, stdin=s,
                  timeout=30)
        time.sleep(0.15)
        self._input_keys("cmd+v")

    # --- navigation ---

    def _menu(self, which):
        activate()
        item = ax_menu_item(*_MENU[which])
        if item is None or not _ax_press(item):
            raise RuntimeError(f"Device Hub menu {_MENU[which]} not available; is the "
                               "phone screen being shared?")
        time.sleep(0.9)

    def _nav_home(self):
        self._menu("home")

    def _nav_recents(self):
        self._menu("recents")

    def lock(self):
        """Controls > Lock (raw op 'lock')."""
        self._menu("lock")

    # --- apps ---

    def _apps_list(self, include_system=False):
        args = ["info", "apps"] + (["--include-all-apps"] if include_system else [])
        apps = devicectl(*args, udid=self.udid)["apps"]
        return sorted(a["bundleIdentifier"] for a in apps)

    def _apps_launch(self, name):
        """By bundle id (`com.apple.Preferences`), or by app name looked up in
        the device's app list. Returns the bundle id."""
        bid = name
        if "." not in name:
            apps = devicectl("info", "apps", "--include-all-apps", udid=self.udid)["apps"]
            hit = [a for a in apps if a.get("name", "").lower() == name.lower()]
            if not hit:
                raise RuntimeError(f"no app named {name!r} on the device; pass a bundle id")
            bid = hit[0]["bundleIdentifier"]
        # --device before the bundle id: everything after it is passed to the app.
        devicectl("process", "launch", "--device", self.udid, "--activate", bid, timeout=45)
        time.sleep(0.6)
        return bid

    # --- session ---

    def _session_state(self):
        """'not-running' | 'no-device' | 'no-window' | 'not-selected' |
        'unavailable' | 'not-sharing' | 'locked' | 'ready'."""
        if running_app() is None:
            return "not-running"
        dev = next((d for d in list_devices() if d["udid"] == self.udid), None)
        if dev is None or dev["state"] != "connected":
            return "no-device"
        win = find_window()
        if win is None:
            return "no-window"
        name = self.info()["name"]
        if name and not win["title"].startswith(name):
            return "not-selected"
        texts = ax_static_texts()
        if any("Unavailable" in t for t in texts):
            return "unavailable"
        if ax_control("View Screen") is not None:
            return "not-sharing"
        try:
            self._screen_geometry(force=True)
        except RuntimeError:
            return "not-sharing"
        try:
            if devicectl("info", "lockState", udid=self.udid).get("passcodeRequired"):
                return "locked"
        except RuntimeError:
            pass
        return "ready"

    def _session_detail(self):
        return " ".join(t for t in ax_static_texts() if "Screen" in t or "Unavailable" in t)

    def select_device(self):
        """Select this phone's row in the Device Hub sidebar, by the name
        devicectl reports. Never touches any other row."""
        name = self.info()["name"]
        rows = _ax_walk(_ax_window(), lambda n: _ax(n, "AXRole") == "AXStaticText"
                        and _ax(n, "AXValue") == name)
        if not rows:
            raise RuntimeError(f"{name!r} is not in the Device Hub sidebar")
        node = rows[0]
        for _ in range(6):
            node = _ax(node, "AXParent")
            if node is None or _ax(node, "AXRole") == "AXRow":
                break
        if node is None:
            raise RuntimeError("sidebar row not found")
        _AS.AXUIElementSetAttributeValue(node, "AXSelected", True)
        time.sleep(1.0)

    def _session_require(self, timeout=20.0):
        """Bounds if the shared screen is usable. Selects the phone and
        presses View Screen itself (harmless, reversible); everything else is
        the user's: launching Device Hub, relaunching it when stale, pairing,
        unlocking the phone."""
        state = self._session_state()
        if state == "not-selected":
            self.select_device()
            state = self._session_state()
        if state == "not-sharing":
            btn = ax_control("View Screen")
            if btn is not None:
                _ax_press(btn)
                deadline = time.time() + timeout
                while time.time() < deadline:
                    time.sleep(1.0)
                    state = self._session_state()
                    if state != "not-sharing":
                        break
        if state == "ready":
            activate()
            return self._bounds()
        msgs = {
            "not-running": f"{APP_NAME} isn't running. Open it (Xcode > Open Developer "
                           "Tool > Device Hub), select the phone, click View Screen.",
            "no-device": "the phone is not connected to CoreDevice (cable? paired? "
                         "Developer Mode?) — `xcrun devicectl list devices`.",
            "no-window": f"{APP_NAME} is running but has no window.",
            "not-selected": "the phone is not the selected device in Device Hub.",
            "unavailable": f"{APP_NAME} says Screen Sharing Unavailable. It stays "
                           "stale after phone-side changes: quit and relaunch Device "
                           "Hub, then click View Screen.",
            "not-sharing": "screen sharing did not start after View Screen.",
            "locked": "the phone is locked with a passcode; unlock it (I never type PINs).",
        }
        raise RuntimeError(f"Device Hub is not ready ({state}): {msgs.get(state, state)}")

    def _session_refocus(self):
        activate()

    # --- interruption ---

    def _focus_probe(self):
        return focus_probe()

    def _focus_diff(self, before, after):
        b_front, b_depth = before
        a_front, a_depth = after
        if b_front is None or a_front is None:
            raise RuntimeError("focus_probe() could not read AXFrontmost — grant "
                               "Accessibility permission.")
        raised = a_depth is not None and (b_depth is None or a_depth < b_depth)
        return {"raised": bool(raised), "stole_focus": bool(a_front and not b_front)}

    # --- independent verification via Cua Driver ---

    def verify_with_cua(self):
        """A second, independent read of the Mac side through Cua Driver, for
        when a step silently did nothing and you have the daemon. Returns
        {screenshot, session_labels, agrees}: a Cua screenshot of the Device
        Hub window (the whole Mac window, not the phone framebuffer), the
        accessibility labels Cua sees, and whether Cua's view of the sharing
        state agrees with the backend's. Raises CuaUnavailable without the
        daemon."""
        cua = self._cua or _Cua()
        path, labels = cua.window_state()
        flat = " ".join(l for _, l in labels if l)
        cua_sharing = "View Screen" not in flat and "Unavailable" not in flat
        state = self._session_state()
        return {"screenshot": path, "session_labels": labels,
                "backend_state": state,
                "agrees": cua_sharing == (state == "ready")}

    # --- escape hatch: devicectl ---

    def _raw(self, cmd, binary=False, timeout=60):
        """shell('info lockState') -> devicectl's JSON result for this device;
        shell('lock') presses Controls > Lock."""
        if cmd == "lock":
            return self.lock()
        args = shlex.split(cmd) if isinstance(cmd, str) else list(cmd)
        return devicectl(*args, udid=self.udid, timeout=timeout)
