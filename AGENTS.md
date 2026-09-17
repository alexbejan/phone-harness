# For agents working in this repo

This is Alex's fork of ShawnPana/phone-harness. Branch `devicehub` is the
working branch and what is installed on this Mac (`~/.phone-harness` ->
`~/Documents/phone-harness`, venv `.venv`, `phone-harness` on PATH, skill at
`~/.claude/skills/phone-harness/SKILL.md`). It drives the Vorti test iPhone
through Xcode 27's Device Hub.

## The loop: the harness improves itself

Whenever an agent using the phone finds something the harness does not cover,
the fix goes into the harness, not into a one-off workaround in the task:

1. **Recognise the trigger.** A helper is missing; a documented fact is
   wrong on the real phone; a gotcha cost you more than one retry and is not
   in `SKILL.md`; the doctor passed but something silently did nothing; a
   Device Hub state the backend does not name.
2. **Reproduce and measure once** on the phone (a native screenshot before
   and after, a number or a yes/no). Facts in this repo carry a date and a
   measurement; guesses do not go in.
3. **Fix in the right place.** Backend behaviour: `src/phone_harness/
   devicehub.py`. Diagnostics: `_doctor_devicehub` in `admin.py`. Agent
   guidance: `SKILL.md` (Device Hub section) and the README table "How
   Device Hub works". Task-specific conveniences that no other task needs:
   `agent-workspace/agent_helpers.py` (no PR needed, just commit).
4. **Prove it.** `phone-harness --doctor devicehub` and
   `phone-harness < scripts/prove-devicehub.py` must both pass, plus a check
   for the thing you changed. When the Cua Driver daemon is present, run the
   proof in **both** input modes, because they take different code paths:
   `phone-harness < scripts/prove-devicehub.py` (auto -> cua) and
   `PHONE_HARNESS_DEVICEHUB_INPUT=cgevents phone-harness <
   scripts/prove-devicehub.py`. Then `phone-harness skill >
   ~/.claude/skills/phone-harness/SKILL.md` so the installed skill matches.
5. **Ship it.** Branch from `devicehub` (`fix/<slug>` or `feat/<slug>`),
   commit with the measurement in the message, push, `gh pr create --base
   devicehub`, and **merge it yourself** when the proof passes and the change
   is backend, doctor or docs. Ask Alex first for: anything that changes the
   consent rules, anything that sends from or changes the phone, and any PR
   to the upstream repo (`ShawnPana/phone-harness`), which waits for his go.
6. **Tell the next agent.** If the fix changes how a task should be written,
   it belongs in `SKILL.md`, because that file is the only thing the next
   agent reads.

Two input routes exist on Device Hub (see the README table): Cua Driver for
focus-free taps/scrolls, CGEvents+AX for everything else. If you extend what
Cua covers, measure it the way the existing rows were measured (a native
screenshot before and after, and confirm focus stayed put), and only move an
op onto Cua once it beats the CGEvent path on the real phone.

Token-frugal: no subagents or workflows for this; read the file you change,
measure on the phone, write, prove, ship.

## Ground rules on the phone

Navigation, typing a draft and reading are fine. Sending anything, calls,
sign-ins and Settings changes need Alex's explicit go for that action. Never
type a PIN. Never select or drive Alex's own iPhone (also paired in Device
Hub); the backend only drives the configured UDID.
