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
