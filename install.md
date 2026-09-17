# phone-harness install

phone-harness drives a real phone from a Mac (first-run flow for agents:
`onboarding.md`; day-to-day usage: `SKILL.md`). It works with an **iPhone**
through the macOS iPhone Mirroring app or through **Xcode 27's Device Hub**
(`devicehub`), or an **Android** over adb (USB or Wi‑Fi). Same helpers either
way; you choose a default and can switch per call.

## Common

```bash
git clone https://github.com/alexbejan/phone-harness ~/Documents/phone-harness   # this fork
ln -s ~/Documents/phone-harness ~/.phone-harness                                # canonical home
cd ~/.phone-harness
# Python 3.10+ with pyobjc. A Mac's default python3 is often Xcode's 3.9, so
# give the checkout its own interpreter (uv or Homebrew python3.12):
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e .
ln -sf ~/.phone-harness/.venv/bin/phone-harness ~/.local/bin/phone-harness  # on PATH

# register as an agent skill so Claude Code / Codex reach for it automatically
mkdir -p ~/.claude/skills/phone-harness
phone-harness skill > ~/.claude/skills/phone-harness/SKILL.md
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills/phone-harness"
phone-harness skill > "${CODEX_HOME:-$HOME/.codex}/skills/phone-harness/SKILL.md"
```

- Python 3.10+, any OS. **iPhone needs a Mac** (it drives iPhone Mirroring);
  **Android works on macOS, Linux and Windows** and is the default off a Mac.
  Only the CLI? `pip install phone-harness` works too; the
  checkout is what makes the harness editable (`agent-workspace/agent_helpers.py`).
- The default phone is `phone-harness config set platform ios|devicehub|android`;
  `phone-harness config` shows every setting and where it came from;
  `PHONE_HARNESS_PLATFORM=android phone-harness …` overrides for one call.
- `phone-harness --doctor` checks the default phone; `--doctor ios`,
  `--doctor devicehub` or `--doctor android` checks another.
- Telemetry is **off by default in this fork** (`telemetry: false` in
  `config.py`); `phone-harness config set telemetry false` pins it in the
  config file too. Scripts, screen text and phone names never leave the
  machine.

Re-run the `phone-harness skill > …/SKILL.md` lines after pulling updates so
the agent's copy matches the code.

## iPhone

- macOS Sequoia+ with **iPhone Mirroring** paired to the phone (open the app
  once and finish its pairing prompts — this needs the physical phone).
- Two permissions for your **terminal**, in System Settings → Privacy & Security:
  - **Accessibility** — taps and keystrokes. Takes effect immediately.
  - **Screen Recording** — seeing the phone. Takes effect after the terminal
    restarts.
  ```bash
  open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
  open "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"
  ```
- Then `phone-harness --doctor ios`.

> You may need to grant more than these two. They are the permissions we
> *know* are required and all `--doctor` checks; a fresh machine may prompt for
> more the first time an action runs. If `--doctor` passes but taps, typing, or
> capture silently do nothing, look for a macOS permission prompt.

## iPhone via Device Hub (Xcode 27)

For a phone that iPhone Mirroring cannot reach: no Apple ID, a region where
Mirroring is unavailable, or a device paired only for development.

- **Xcode 27** installed and selected (`xcode-select -p` inside Xcode.app);
  `xcrun devicectl list devices` must work.
- The phone on **iOS 27 or later**, **Developer Mode** on (Settings → Privacy &
  Security → Developer Mode; the toggle may only appear once pairing starts),
  paired with the Mac by cable (Device Hub → Add Device (+) or just plug it in
  and tap Trust). Wi‑Fi pairing exists but is untested here.
- Device Hub open (Xcode → Open Developer Tool → Device Hub), the phone
  selected in the sidebar, **View Screen** clicked once. The harness re-selects
  the phone and presses View Screen itself later; it never launches Device Hub.
- The same two terminal permissions as Mirroring: **Accessibility** (taps,
  keystrokes, menu items) and **Screen Recording** (finding the phone inside
  the Device Hub window). The Xcode Command Line Tools are not needed.
- `phone-harness config set platform devicehub`. With one iPhone connected
  the harness picks it; with several, `phone-harness config set
  devicehub.udid <udid>` (from `xcrun devicectl list devices`).
- Then `phone-harness --doctor devicehub`: it walks pyobjc → permissions →
  Device Hub app → devicectl → phone (tunnel, Developer Mode, DDI, display
  chrome) → Device Hub running → window → session state → phone screen located
  → native screenshot → OCR.
- Keep the full Device Hub window (not the compact one) visible on the main
  display at any zoom.
- **Optional, recommended: Cua Driver** (cua.ai/cua-driver, the daemon behind
  the `superset:computer` skill). When its daemon is running the backend sends
  taps, scrolls and swipes through it, which does not bring Device Hub to the
  front — no window popping while an agent works. It needs the same
  Accessibility + Screen Recording grants. Nothing to configure:
  `devicehub.input` defaults to `auto` (use Cua when present, else CGEvents);
  pin it with `phone-harness config set devicehub.input cua|cgevents`. Typing,
  paste and the Home/Lock menu still use the direct path and briefly front
  Device Hub.

## Android

- adb: `brew install android-platform-tools` (macOS), `apt install adb` (Debian/Ubuntu),
  `winget install Google.PlatformTools` (Windows). Optional: `scrcpy` (`brew` /
  `apt` / `winget install Genymobile.scrcpy`) for a live mirror window during
  `phone-harness android awake`.
- On the phone, once: Settings → About phone → tap **Build number** 7× →
  Settings → System → **Developer options**.
- **USB**: Developer options → **USB debugging** on → plug in → tap **Allow**
  (tick "Always allow from this computer"). Done.
- **Wi‑Fi** (Android 11+, same network as the Mac): Developer options →
  **Wireless debugging** on → tap the row → **Pair device with pairing code** →
  `phone-harness android pair 123456` with the code shown. The phone is
  remembered by name; from then on the harness finds and connects it itself.
- `phone-harness config set platform android` to make it the default, then
  `phone-harness --doctor android`.
- `phone-harness android` shows known phones and what is attached; a plugged-in
  phone always wins over Wi‑Fi. Long task? `phone-harness android awake --bg`
  keeps the phone unlocked for the session without changing any setting;
  `phone-harness android rest` ends it.

## Both

Set up each as above; `phone-harness config set platform …` picks the default,
`PHONE_HARNESS_PLATFORM=…` picks per call. They never interfere — the
iPhone is driven through the mirroring or Device Hub window, the Android over
adb.

`phone-harness config set telemetry false` turns off anonymous usage telemetry.

## If It Fails

`--doctor` walks the ladder in order and names the missing step. Common ones:

- **iPhone — capture is blank/black**: Screen Recording granted but the
  terminal wasn't restarted; or Mirroring shows an interstitial (iPhone in Use /
  Connect / Mac Locked) — clear it on the Mac, lock the iPhone if it says in use.
- **iPhone — taps do nothing**: Accessibility missing, or another window stole
  focus (helpers re-activate the window; check for a macOS prompt).
- **iPhone — `--doctor` says pyobjc missing on an install that works**: it is
  running a different Python than the one that has pyobjc; use the interpreter
  `pip install -e .` used, or `pip install pyobjc-framework-Quartz
  pyobjc-framework-Vision pyobjc-framework-Cocoa` for that one.
- **Device Hub — `not-running` / `no-window`**: open Device Hub (Xcode → Open
  Developer Tool → Device Hub); the harness never launches it.
- **Device Hub — `no-device`**: the phone is not connected to CoreDevice:
  cable, Trust prompt, Developer Mode, or `xcrun devicectl list devices` shows
  it as `available (paired)` rather than `connected`.
- **Device Hub — `unavailable`** ("Screen Sharing Unavailable"): Device Hub
  went stale after a phone-side change (Developer Mode enabled, reboot). Quit
  and relaunch it, select the phone, View Screen.
- **Device Hub — the blob "is not the phone"**: zoom so the whole phone is
  visible (View → Zoom to Fit / Physical Size) and keep the full window; a
  new bezel needs its insets in `CHROME_INSETS` or `devicehub.inset`.
- **Device Hub — taps do nothing**: Accessibility missing, or a modal on the
  Mac keeps Device Hub from coming frontmost; on the Home Screen, labels are
  not tap targets (use `open_app("com.apple.Preferences")` or tap the icon
  ~20 pt above the label at Physical Size).
- **Device Hub — `locked`**: unlock the phone. The harness never types a PIN.
- **Android — `unauthorized`**: unlock the phone and tap Allow on the "Allow
  USB debugging?" prompt (replug if it does not appear).
- **Android — `no-device`**: USB debugging off, cable/port, or for Wi‑Fi:
  Wireless debugging turned itself off (it does after a reboot) or a different
  network than the Mac. `adb devices` shows what adb sees.
- **Android — `locked`**: unlock the phone; `phone-harness android awake` keeps
  it awake for the session. The harness never types a PIN.
- **Android — the tree is unavailable on some screen**: that screen never goes
  idle (something animates), so `uiautomator` refuses; read `screenshot()`
  instead or move to a screen that settles.
