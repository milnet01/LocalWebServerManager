# ADR-0007: Window geometry, and centring under Wayland

- **Status:** Accepted
- **Date:** 2026-08-03
- **Deciders:** Project lead
- **Related:** [ADR-0005](0005-registry-and-rescan.md),
  [`docs/design-look-and-feel.md § Look and feel`](../design.md)

## Context

The window must remember its size and position between runs, and
offer an explicit **Centre on screen** action.

Under Wayland — which is what this machine runs (KDE Plasma) —
**an application is not permitted to position its own window.**
The compositor owns placement. `QWidget.move()` is accepted
without error and then silently ignored, which is the worst
possible failure shape: the code looks correct, the tests that
assert "we called move()" pass, and the window does not move.

Three sibling projects on this machine have already hit this, and
the user pointed at them rather than letting it be rediscovered:
`SystemManager`, `finbreak` and `OneUp`. **`OneUp` carries the
working solution for centring** — `OneUp/updater.py:1932-1966` —
and it is worth stating why it works rather than merely copying
it: KDE exposes a scripting interface over D-Bus, and a script
running *inside* KWin **is** the compositor, so it may place
windows. The app asks; the compositor acts.

**OneUp also carries the bug this ADR must not inherit.** The
user reports (2026-08-03) that OneUp does not reopen in its last
position. That is the same limitation showing through from the
other side: OneUp persists geometry with
`saveGeometry()`/`restoreGeometry()` (`updater.py:1902`), whose
position component Wayland discards exactly as it discards
`move()`. Size comes back; position does not.

The important observation is that **this is not actually a
platform limit — it is an unused mechanism.** If a KWin script
can centre a window, it can equally place one at remembered
coordinates; centring is just a placement whose target happens to
be the middle. OneUp uses the mechanism for one and not the
other. This project uses it for both.

## Decision

**Size, position and maximised state are all persisted and all
restored — on Wayland as well as X11 — by treating "restore to
remembered coordinates" and "centre" as the same operation with
different targets, both delegated to KWin.**

**Geometry persistence.** `width`, `height`, `x`, `y` and a
`maximized` flag are stored as plain integers and a boolean in
`settings.json`, not as a `QByteArray` blob from
`saveGeometry()`. The blob is opaque and would be the only
unreadable value in a config file whose whole point is being
hand-editable (`docs/design.md § Persistence`). On restore:

- **Size and maximised state** are applied directly on every
  platform — `resize()` is honoured under Wayland; only placement
  is refused.
- A restored geometry is **validated against the current
  screens** before use: a window remembered on a monitor that is
  no longer attached, or sized larger than the current display,
  is clamped to the available area rather than restored
  off-screen.

**Placement — one operation, two targets.** A single
`place_window(target)` helper serves both restore-position and
centre, so there is one code path and one set of failure modes.

- **X11:** `move()` to the target, after clamping the frame
  geometry to `screen.availableGeometry()`. Direct and reliable.
- **Wayland:** run a one-shot KWin script over D-Bus
  (`org.kde.KWin` `/Scripting`: `loadScript` → `start` →
  `unloadScript`) that finds this process's own window by PID,
  skips transients so it never places a dialog instead of the
  main window, and sets `frameGeometry`. The target is either the
  remembered `x`/`y` or the centre of
  `workspace.clientArea(workspace.PlacementArea, c)` — the usable
  area, so it respects panels either way.
- **Every value reaching the KWin script is parsed as a number
  first** (security review, 2026-08-03). `loadScript` takes a file
  path, so the app writes JavaScript with the target coordinates
  interpolated into it — and those coordinates come from a
  deliberately hand-editable `settings.json`. String-formatted, an
  `x` of `0); <arbitrary JS> //` executes **inside KWin's scripting
  engine**, which can move and close every window, read window
  titles, and reach `callDBus`. So `x`, `y`, `width`, `height` go
  through `int()` and `maximized` through `bool()` **before**
  reaching the template, and the clamp to screen geometry that this
  ADR already requires for correctness is the same step. It is a
  security boundary, not only a usability one.
- **The script file is written safely**: `tempfile.mkstemp` in the
  app's own state directory at 0600, loaded, unloaded, deleted. A
  predictable path is a symlink-replacement target in the window
  between writing it and KWin reading it.
- Platform is detected by `XDG_SESSION_TYPE == "wayland"`, the
  same test OneUp uses (`updater.py:541`).
- The KWin call is **deferred by one event-loop tick** after the
  window is shown, because KWin can only move a window it already
  knows about. This is why the restore happens after `show()`
  rather than before it.
- If `dbus-send` is missing, or the session is neither X11 nor
  KWin-based Wayland, placement **degrades honestly**: the window
  opens wherever the compositor puts it at the remembered *size*,
  and the Centre action is disabled with a tooltip saying why —
  rather than being offered and doing nothing.

**Verification is behavioural, not structural.** The test that
matters asserts the window *ends up* at the requested
coordinates, never that `move()` or `dbus-send` was called. A
test asserting the call is exactly the test that passes while
OneUp's window opens in the wrong place — the failure this ADR
exists to avoid. OneUp's own suite shows the shape to follow:
`OneUp/tests/gui-smoke.py:282-305` drives both session types by
setting `XDG_SESSION_TYPE` and asserts the resulting geometry.

## Consequences

**Positive:**

- Reuses a solution already proven on this exact desktop, rather
  than rediscovering a silent failure. The reasoning travels with
  it, so the next person does not "simplify" it back to `move()`.
- Plain integers in the config mean a user can fix a
  wrongly-placed window by editing a file, which an opaque
  base64 blob would not allow.
- **The window actually reopens where it was left**, which the
  `saveGeometry()`/`restoreGeometry()` idiom does not achieve
  under Wayland. This is the one behaviour the user named, and
  the reason this ADR goes further than the code it borrows from.
- The remaining limitation is stated in the UI rather than
  hidden: where placement is genuinely unavailable, the action is
  disabled and explains itself.

**Negative:**

- KDE-specific. The KWin script path works on Plasma 5 and 6 and
  does nothing on GNOME/wlroots Wayland, where centring will be
  unavailable. Acceptable — this is a KDE-targeted app
  (`docs/discovery.md`) — but it is a real limit on the
  "useful to other people" ambition, and the honest degradation
  above is what keeps it from being a bug report.
- Restoring position under Wayland happens **after** the window
  is mapped, so there may be a brief visible jump from the
  compositor's chosen position to the remembered one. That is the
  price of the compositor owning placement; a window that appears
  in the right place a frame late beats one that never gets
  there. If it proves distracting, the mitigation is to open
  hidden and show after placement — not to abandon the restore.

**Neutral:**

- Shelling out to `dbus-send` rather than binding a D-Bus library
  keeps the dependency list at PySide6 + psutil. It is an
  argument vector, never a shell string
  (`docs/standards/coding.md § O4`).

## Amendment (2026-08-21, LWSM-1033) — what the compositor said

This ADR was written from reasoning about Wayland and from reading a
sibling app. Implementing it produced four measurements against the
real KWin on this machine's Plasma 6 Wayland session, and three of
them contradict the decision above. **The decision stands; these are
its corrections.** No `review-contract` gate: the code exists, and
per `CLAUDE.md § Review cadence` an amendment recording what was
actually built does not re-arm one.

**1. "Deferred by one event-loop tick after the window is shown" is
too early.** A window shown with a remembered position of 305,255
opened at 1570,793 — the script ran, matched our PID and set
`frameGeometry`, and the compositor ignored it. Measured: a 0 ms
delay after `show` fails; 50, 150 and 400 ms all work; the first
`Expose` **alone** still fails; `Expose` plus one tick worked 5 times
out of 5. The trigger is now that condition rather than a chosen
number — the surface has been presented, and the compositor has had
one turn of our loop to finish with it.

**2. KWin's geometry write is authoritative, so the script must carry
the size too.** The first implementation preserved the window's
current size by reading `c.frameGeometry.width` back, reasoning from
this ADR's own division of labour — `resize()` is honoured under
Wayland, so only the position needed sending. A 700x500 window then
came back at 239x216, its undecorated minimum: once the script has
told KWin the window is that size, the client's own later `resize` is
configured straight back to it. Order does not help; it is not a
race.

**3. The decoration must be added inside the script, not by the
caller.** Converting a client size to a frame size in the app sends 0
for the margins, because the window is not decorated yet at the
moment placement runs — leaving a 472-pixel client area that the next
close stores and shrinks again on every launch. `c.clientGeometry` is
where the answer is (measured: frame 700x500, client 700x472), so the
script computes the difference itself and falls back to sending the
size unconverted on a KWin too old to expose it.

**4. The position cannot be READ under Wayland at all, and this is
the one place the decision changes.** This ADR says the position
component is discarded on *restore*, and treats the KWin path as
closing that. Restoring works — measured exact, across three
consecutive launches, with no drift. **Capturing does not.** Wayland
gives a client no global coordinates, so Qt answers 0,0 forever:
measured, KWin reported the window at 640,480 while Qt reported 0,0,
and 0,0 is a plausible position rather than an error, so it would be
written to `settings.json` as though the user had put the window in
the corner.

So a Wayland session **records size and maximised state and leaves
the stored coordinates alone**. That is what KDE's own applications
do, and it is the deeper reason
`saveGeometry()`/`restoreGeometry()` loses position there — the
sibling app's bug this ADR set out to avoid is half a platform limit
and not only an unused mechanism. A position recorded under X11, or
typed into the hand-editable file, is still restored on Wayland,
because placement and reading are different problems and only one of
them is refused.

**Consequence for the "Positive" list above.** *"The window actually
reopens where it was left"* holds under X11 and holds under Wayland
only for a position something else recorded. Closing that gap needs
the app to own a D-Bus service for a KWin script to call back into,
which was put to the user on 2026-08-21 and declined in favour of the
honest limit; if it is ever wanted, that is the shape.

**One citation note.** The four `OneUp/updater.py` line references
above no longer resolve — that file is 21 lines now and the working
code is at `OneUp/oneup/gui/placement.py`. Already filed as roadmap
debt (DS01, scheduled with P10) and left for it rather than fixed
here.
