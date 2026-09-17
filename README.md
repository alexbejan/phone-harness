# Phone Harness 📱

**[phone-harness](https://phone-harness.com?utm_source=github&utm_medium=readme&utm_campaign=header)** · let your agent control your phone.

Connect Claude Code, Codex, or any agent to your real phone. **iPhone** through
the Mac's iPhone Mirroring window or through **Xcode 27's Device Hub** (this
fork), **Android** over adb from macOS, Linux or Windows. No jailbreak, nothing
installed on the phone. The agent sees the screen, taps, types, and reads the
result.

> **This fork** (`alexbejan/phone-harness`, branch `devicehub`) adds the
> `devicehub` platform: the same helpers drive a paired iPhone through Xcode
> 27's Device Hub where iPhone Mirroring is unavailable (Romania, a test phone
> with no Apple ID). Telemetry is off by default here. See
> [How Device Hub works](#how-device-hub-works).

```
  ● agent: wants to open Weather
  │
  ● find_text("Weather") → (400, 468)
  │
  ● tap(400, 468) → reads the screen → forecast is up
  ✓ done
```

Try [Phone Harness Cloud](https://phone-harness.com/cloud?utm_source=github&utm_medium=readme&utm_campaign=cloud) → Hosted iPhones and Androids with stealth, real numbers, 2FA, and unlimited devices

Get started by sending the [setup prompt](https://phone-harness.com?utm_source=github&utm_medium=readme&utm_campaign=setup-prompt) to your
coding agent.

## Demo

**Task:** "Buy me a Waymo to Delah Coffee from my current location."

https://github.com/user-attachments/assets/80b6d38e-0222-481c-93db-9de60d79247a

## Setup

Paste into Claude Code or Codex:

```text
Set up phone-harness for me. Clone https://github.com/ShawnPana/phone-harness into ~/.phone-harness, read `install.md` first, install it so `phone-harness` is a command on my PATH, and register it as an agent skill named phone-harness using `phone-harness skill` as the body. Then read `onboarding.md` and walk me through it.
```

The agent asks which phone is your default and walks you through the parts
that need your hands: pairing iPhone Mirroring and granting Accessibility and
Screen Recording, or turning on Android developer options and approving adb.
`phone-harness --doctor` checks the chain. Details in [install.md](install.md).

## Usage

```bash
phone-harness <<'PY'
open_app("Notes")
tap_text("New Note")
type_text("hello from the harness")
print([o["text"] for o in ocr()][:10])
PY
```

Helpers are pre-imported. [SKILL.md](SKILL.md) is the agent's day-to-day
guide; [helpers.py](src/phone_harness/helpers.py) is the full list.

## How it works

**iPhone.** iPhone Mirroring renders the phone as a Mac window and forwards
mouse and keyboard as touches. The harness captures that window, OCRs it with
Apple's Vision framework for text with tap-ready coordinates, and posts
HID-level events for taps, swipes, and typing.

**Android.** adb is the transport. `screencap` is the capture, the phone's
accessibility tree is the text source, `input` is the hands. Works over USB or
Wi‑Fi, no window needed.

**iPhone via Device Hub.** Xcode 27's Device Hub shares a paired phone's
screen and forwards clicks and keystrokes to it. The harness reads the screen
with `xcrun devicectl device capture screenshot` (the device's own framebuffer,
native resolution, no window needed), OCRs that, maps device pixels onto the
Mac points where Device Hub draws them, and posts CGEvents there. `devicectl`
also launches apps by bundle id and sets the device pasteboard for exact
pastes.

Same helpers on all three. `phone-harness config set platform
ios|devicehub|android` picks the default.

## How Device Hub works

Due diligence and measurements behind the `devicehub` backend
(`src/phone_harness/devicehub.py`), done 2026-09-17 on a Mac mini (macOS 27.0,
Xcode 27.0 27A266a, Device Hub 27.0, devicectl 642.16) with an iPhone 11 Pro on
iOS 27.0 paired by cable, Developer Mode on, no Apple ID. Sources: Apple's
"Device Hub", "Managing your simulated and physical devices in Device Hub",
"Interacting with your app in Device Hub" and "Capturing screenshots and
videos from devices" pages, the WWDC26 sessions 258 and 260, the Device Hub
bundle and menus, community reports (tddworks/baguette#77, JaviSoto/
device-hub-ios, ipbtools/ipb).

**What Device Hub is.** `/Applications/Xcode.app/Contents/Applications/
DeviceHub.app`, bundle id `com.apple.dt.Devices`, process name `DeviceHub`
(LaunchServices reports its pid as -1, so the backend reads the pid from
`pgrep`). It replaces Simulator.app and manages paired physical devices. The
window title is the selected device's name; the canvas shows the shared
screen inside a bezel ("chrome"), the sidebar lists devices, the inspector is
on the right. Screen sharing of physical devices needs iOS 27+, Developer Mode
and pairing; "you can interact with the view in Device Hub and the physical
device simultaneously". Camera/microphone apps on the phone stop the sharing.
There is no AppleScript dictionary, the only URL scheme is `devices:`, and
there are no scripting hooks; `devicectl` is Apple's stated automation route
("a command line tool based on the same underlying technology as Device Hub").

**Phone side.** With sharing on, the developer disk image runs
`dtremotedisplayd` (screen stream), `dtuhidd` ("DT Remote service for
receiving and posting UniversalHID events": it posts the touches Device Hub
sends), `dtscreencaptured` (screenshots), `dtpasteboardd` (clipboard sync). The
community reports about `dtuhidd` ignoring another tool's touches once Device
Hub has attached ("whichever client connects first wins") are about
simulators; on this physical phone a direct CoreDevice HID client
(`ipbtools/ipb`, built from source) could press Home but its taps never
landed, with Device Hub sharing, with sharing stopped, and with Device Hub
quit. So there is no window-free input route today; the backend does not use
ipb.

**Eyes: native screenshots.** `xcrun devicectl device capture screenshot
--device <udid> --destination x.png` returns the framebuffer (1125x2436 px on
the 11 Pro) in 0.7-1.0 s, regardless of how small the phone is drawn on the
Mac, so OCR reads at native resolution. Device Hub's own Screenshot button
saves to the Desktop and was not needed. `devicectl device info displays`
reports the display size and the chrome id (`com.apple.dt.devicekit.chrome.
phone2`), `info lockState` the passcode state, `info details` Developer Mode
and the tunnel state, `info apps --include-all-apps` the app list.

**Geometry: where the phone is drawn.** The shared screen is a custom-drawn
surface with no accessibility children, and the window size and zoom vary
(Zoom In/Out, Zoom to Fit, Actual Size, Resize mode, compact window). The
backend re-derives the screen rect on every call (cached 0.8 s): it captures
the window (`screencapture -l <id>`), takes the canvas region from the
accessibility tree (below the toolbar, between the sidebar and inspector
splitters), finds the largest connected blob of non-background pixels (the
chrome: a thin light outline ring, a black bezel, the screen), checks the
blob's aspect against the chrome's known ring aspect (0.506-0.510 measured
from Zoom Out to Zoom to Fit) and insets it by fixed fractions (screen =
ring inset by 42/536, 38/1052, 43/536, 37/1052). Verified by OCR-ing the Mac
window and the native screenshot independently: the two agree within 2 pt.
Labels under the phone ("AI Agent Phone / iOS 27.0 / View Screen") and the
floating Home/Screenshot/Rotate toolbar are separate, smaller blobs. Another
chrome needs its insets added to `CHROME_INSETS` or set as
`devicehub.inset`.

**Hands: CGEvents at the mapped point, Device Hub frontmost.** Measured:

| Gesture | Result |
|---|---|
| click | tap (Home Screen labels are not targets; the icon above them is) |
| linear touch-drag (any speed tried, with or without a still hold before release) | scrolls, then keeps going: 1.8x the dragged distance (iOS keeps the release velocity) |
| touch-drag with an ease-out path and the end point repeated before release | pans 0.9x the dragged distance (1:1 minus touch slop); this is what `scroll()` sends |
| touch-drag, 0.12 s / 6 steps | flick with momentum (`swipe()`) |
| horizontal drag, 0.3 s / 12 steps | flips Home Screen pages |
| press and hold 1.2 s | long press (jiggle mode on the Home Screen) |
| scroll-wheel events (pixel or line units, with or without trackpad phases, pointer over the window) | nothing, so `scroll()` is a touch-drag |
| keystrokes with Device Hub frontmost and a field focused | typed; **the "Capture Keyboard" toggle is not needed** |
| keystrokes with another Mac app frontmost | nothing |
| modifier combos (cmd+a, cmd+v, delete) | forwarded, unlike Mirroring which drops the flag mask |
| cmd+v after `devicectl device pasteboard copy` (stdin) | pastes the exact Unicode text |
| cmd+v after `pbcopy` on the Mac | also pastes (clipboard is synced), but devicectl is deterministic |
| SkyLight event records to the Device Hub window (the no-focus trick from background.py) | land, but Device Hub becomes frontmost anyway, so there is no background mode |

Home, App Switcher, Lock and Screenshot are `Controls` menu items (shift+cmd+H,
cmd+L, shift+cmd+S); the backend presses the menu items through accessibility
after activating Device Hub.

**Cua Driver route (optional, focus-free).** Cua Driver (cua.ai/cua-driver, the
daemon behind the `superset:computer` skill) posts input to a pid+window
without bringing it to the front. When its daemon is running the backend routes
**taps, scrolls and swipes** through it, so Device Hub no longer pops to the
front on every action; the phone-screen rect the backend already computes is
converted to Cua's window-local screenshot pixels. Measured 2026-09-17:

| via Cua | result |
|---|---|
| `click` background | taps 3/3, Finder stays frontmost throughout |
| `drag` (foreground; fronts the window for <1 ms then restores) | scrolls a list 0.96:1, focus stays put |
| `press_key` background (single keys, shift) | reaches the phone, no focus steal |
| `type_text` | AX insertion writes garbage — unused |
| `hotkey` cmd+v / cmd+a | modifier not forwarded to the phone — unused |
| `invoke_menu` Controls > Home | refused on Device Hub's SwiftUI menu — unused |

So Cua drives only tap/scroll/swipe; typing, paste, cmd combos, the Controls
menu and long press stay on the CGEvent + accessibility path (which fronts
Device Hub). `devicehub.input` selects the route: `auto` (default: prefer Cua
when the daemon answers), `cua` (require it), `cgevents` (never). The backend's
`verify_with_cua()` is a second, independent read of the Mac side for when a
step silently did nothing. The toolbar also has Capture Keyboard, Resize
mode, Zoom Out/Fit/Actual/In, Open in New Window and More Actions (Stop
Screen Sharing, Restart, Show in Finder, Rename, CarPlay Simulator, Collect
sysdiagnose, Unpair). The Home/Screenshot/Rotate buttons under the phone are
only in the accessibility tree while the pointer hovers the canvas.

**Session states** (`connection_state()`): `not-running`, `no-device` (not
connected to CoreDevice), `no-window`, `not-selected` (window title is another
device), `unavailable` ("Screen Sharing Unavailable": Device Hub is stale, for
example after Developer Mode was enabled while it ran; quit and relaunch it),
`not-sharing` (the "View Screen" button is up; an AXButton whose *description*
carries the text), `locked`, `ready`. `ensure_device()` selects the phone's
sidebar row and presses View Screen itself (sharing came back in a few seconds
after Stop Screen Sharing and after a relaunch); launching, relaunching,
pairing and unlocking stay with the user.

**Keyboard shortcuts** (from the app's menus): File: New Tab cmd+T, New Window
shift+cmd+N, Close cmd+W. View: Hide Sidebar shift+cmd+L, Inspectors
alt+cmd+1/2/3, Zoom In cmd++, Zoom Out cmd+-, Zoom to Fit cmd+0, Physical Size
cmd+1. Device: Toggle Appearance shift+cmd+A, Toggle Software Keyboard
alt+cmd+K, Increase/Decrease Text Size alt+cmd+plus/minus. Controls: Home
shift+cmd+H, Lock cmd+L, Siri alt+shift+cmd+H, Screenshot shift+cmd+S, Record
Screen shift+cmd+R. Most Device menu items (appearance, battery, Face ID,
location) are simulator-only and disabled for a physical device. The backend
uses menu items via accessibility rather than shortcuts, because with a field
focused on the phone the keystrokes would go to the phone.

**Not measured / open**: whether a longer Cua `press_key`/paste route could
replace the CGEvent path for typing (today it cannot); Resize mode and the
compact window (the backend
expects the full window; the doctor reports the state), a second phone chrome,
Wi-Fi pairing (the test phone is on a cable), whether sharing survives the
phone locking (Device Hub's own docs say interaction stops when a camera or
microphone app comes up on the phone).

## Limits

- Unlocking the iPhone pauses mirroring; a PIN-locked Android needs the user.
- Device Hub: input needs Device Hub frontmost (no background mode); one
  phone chrome is calibrated (`phone2`, the notch iPhones); Home Screen labels
  are not tap targets (launch by bundle id instead).
- OCR sees text, not icons. Unlabeled controls need a screenshot and a
  vision-capable model.
- No multi-touch, no camera or Face ID flows. DRM video renders black.
- Connecting the phone is always the user's job.

## Sponsor

phone-harness is free and maintained in my own time.
[Sponsoring](https://github.com/sponsors/ShawnPana) keeps it that way.
