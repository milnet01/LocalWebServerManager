"""Putting the window where the user left it, and back in the middle on ask.

Core, and — unlike every other core module — it imports no Qt at all, not even
`QtCore`. That is not tidiness: the arithmetic below is the security boundary
ADR-0007 describes, and a boundary worth testing is worth testing without a
display, a `QApplication` or an event loop.

**Under Wayland an application may not place its own window.** The compositor
owns placement, so `QWidget.move()` is accepted and then silently ignored —
the worst failure shape there is, because the code looks right and a test
asserting "we called `move()`" passes while the window does not move. KDE
exposes a scripting interface over D-Bus, and a script running *inside* KWin
**is** the compositor, so it may place windows. The app asks; KWin acts.

ADR-0007's observation is the one worth keeping: restoring to remembered
coordinates and centring are **the same operation with different targets**, so
there is one code path here and one set of failure modes. `place_window` is
that path.

The technique is transcribed from `OneUp/oneup/gui/placement.py` on this
machine — the working solution the ADR points at, which has since moved out of
the `updater.py` lines the ADR cites. Two things are deliberately not copied:
that app writes its script into the shared temp directory, and it looks for
`workspace.windowList()` alone, which is Plasma 6's spelling.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from lwsm import applog

log = applog.get_logger(__name__)


# Every D-Bus call is given a deadline. KWin is normally instant, but this runs
# on the GUI thread during startup, and a compositor that has wedged must not
# take the window with it — the app opening in the wrong place beats the app
# not opening.
DBUS_TIMEOUT_S = 3.0

# The name the script is loaded under. Constant rather than generated: it is
# unloaded in the same call, and a stale entry from a crashed run is then
# replaced rather than accumulating.
KWIN_SCRIPT_NAME = "lwsm_place"


@dataclass(frozen=True)
class Rect:
    """A window rectangle in screen coordinates, as plain integers.

    Plain integers, not a `QRect`, for the same reason `settings.json` stores
    them rather than a `saveGeometry()` blob (ADR-0007): they are the values
    that go on disk, they are hand-editable there, and every one of them is
    interpolated into a script that runs inside the compositor. A type that
    can only hold integers is the cheapest half of that guarantee.
    """

    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def overlap(self, other: Rect) -> int:
        """Area shared with `other`. Zero when they do not touch."""
        wide = min(self.right, other.right) - max(self.x, other.x)
        tall = min(self.bottom, other.bottom) - max(self.y, other.y)
        return wide * tall if wide > 0 and tall > 0 else 0


def pair_or_none(first: int | None, second: int | None) -> tuple[int, int] | None:
    """Both, or nothing — half a position is not a position.

    `settings.load` reads each field on its own and refuses each on its own, so
    a hand-edited file can arrive with an `x` and no `y`. There is no safe way
    to invent the other: defaulting a coordinate to 0 puts the window in the
    corner, and substituting the current width restores a size the window was
    never at. Falling back to the default is the one answer that is not a
    guess.

    **Position and size are separate pairs and not one rectangle**, because
    they are separately knowable. Under Wayland a client is never told where
    it is — measured 2026-08-21, KWin reported this app's window at 640,480
    while Qt reported 0,0 — so a session there can record a size and cannot
    record a position. Joined into one rectangle, the missing half would take
    the size down with it and the window would forget a size it knew.
    """
    if first is None or second is None:
        return None
    return (first, second)


def position_is_readable(environ: dict[str, str] | None = None) -> bool:
    """Whether this session can tell us where our own window is.

    The mirror of `placement_available`, and the asymmetry is the point:
    **setting** a position under Wayland works, through KWin, and **reading**
    one is not possible at all. Wayland gives a client no global coordinates,
    so Qt answers 0,0 forever — which is a plausible position, not an error,
    and would be saved as though it were true.

    So a Wayland session remembers size and maximised state and leaves the
    stored position alone. That is what KDE's own applications do, and it is
    why `saveGeometry()`/`restoreGeometry()` loses position there. A position
    that IS in the file — recorded under X11, or typed in by hand — is still
    restored on Wayland, because placement and reading are different problems.
    """
    return not on_wayland(environ)


def centre_in(area: Rect, width: int, height: int) -> Rect:
    """A `width` x `height` rectangle in the middle of `area`.

    Not clamped here — `clamp_to_screens` is what does that, and doing it twice
    would mean two answers to the same question.
    """
    return Rect(
        x=area.x + (area.width - width) // 2,
        y=area.y + (area.height - height) // 2,
        width=width,
        height=height,
    )


def clamp_to_screens(target: Rect, screens: Sequence[Rect]) -> Rect:
    """`target` moved and shrunk until it lies inside one of `screens`.

    ADR-0007 requires this for correctness — a window remembered on a monitor
    that is no longer attached must not be restored off-screen, where the user
    cannot reach it to fix it. It is also half the security boundary: whatever
    a hand-edited `settings.json` claims, what reaches the KWin script is a
    rectangle inside a real screen.

    The screen chosen is the one the remembered rectangle **overlaps most**,
    which keeps a window that straddles two monitors on the one it was mostly
    on. Overlapping none at all — the unplugged-monitor case — falls back to
    the first screen, since there is no better claim to make and any attached
    screen beats none.

    With no screens at all there is nothing to clamp against, so the target is
    returned unchanged. That is the headless case, and refusing to place a
    window because Qt reported no screens would be a worse answer than trying.
    """
    if not screens:
        return target
    home = max(screens, key=target.overlap)
    if target.overlap(home) == 0:
        home = screens[0]

    width = min(target.width, home.width)
    height = min(target.height, home.height)
    # `max` after `min`, so a window as wide as the screen lands at the screen's
    # own left edge rather than at a negative coordinate.
    x = max(home.x, min(target.x, home.right - width))
    y = max(home.y, min(target.y, home.bottom - height))
    return Rect(x=x, y=y, width=width, height=height)


def on_wayland(environ: dict[str, str] | None = None) -> bool:
    """The one platform test, `XDG_SESSION_TYPE`, as ADR-0007 specifies.

    `environ` is injected so a test can drive both session types without
    mutating the process it runs in — which is what ADR-0007 asks the
    verification to do.
    """
    env = os.environ if environ is None else environ
    return env.get("XDG_SESSION_TYPE", "").lower() == "wayland"


def placement_available(
    environ: dict[str, str] | None = None,
    which: Callable[[str], str | None] | None = None,
) -> bool:
    """Whether asking for a position can do anything at all.

    `which=None` rather than `which=shutil.which`, and the difference is not
    cosmetic: a default argument is bound when the function is DEFINED, so a
    `monkeypatch.setattr(shutil, "which", ...)` never reaches one and the test
    silently measures the developer's own machine. Resolving it in the body is
    what makes the real environment patchable — which a test of the
    disabled-action branch has no other way to reach, since that branch
    depends on a tool being absent. Cost one cycle on 2026-08-21.

    False only where the session is Wayland and `dbus-send` is missing: there
    the compositor owns placement and we have no way to ask it, so the Centre
    action is disabled and says why rather than being offered and doing
    nothing (ADR-0007).

    Off Wayland this is optimistic on purpose. `move()` works under X11, and
    under a Wayland compositor that is not KWin it does not — but nothing
    distinguishes those two from inside the process, and refusing to try would
    disable the action on every X11 session to be honest about GNOME.
    """
    if not on_wayland(environ):
        return True
    return bool((shutil.which if which is None else which)("dbus-send"))


def kwin_script(target: Rect, pid: int) -> str:
    """The one-shot script KWin runs, with `target` interpolated as numbers.

    **Every value reaching this template is an `int` before it arrives**, which
    is what `Rect` and `clamp_to_screens` are for. `loadScript` takes a path,
    so the app writes JavaScript for KWin to execute; string-formatted, an `x`
    of ``0); <arbitrary JS> //`` would run **inside KWin's scripting engine**,
    which can move and close every window on the desktop, read window titles,
    and reach `callDBus`. `settings.json` is deliberately hand-editable, so
    that string is a plausible thing to find in it.

    **`target.width` and `target.height` are a CLIENT size; the decoration is
    added inside the script.** Three measurements got to that, all against
    real KWin on this machine's Plasma 6 Wayland session on 2026-08-21, and
    each refuted the reasoning before it.

    First this preserved the window's current size by reading
    `c.frameGeometry.width` back, on the reasoning that ADR-0007 hands the
    size to `resize()` on every platform and only placement is refused. A
    window whose remembered size was 700x500 came back at 239x216 — its
    undecorated minimum — with the position exact: **KWin's geometry write is
    authoritative**, so once this script says the window is 239x216 the
    client's own later `resize` is configured straight back to it. Swapping
    the order does not help; it is not a race.

    Then the caller converted, adding the decoration it measured off its own
    window. At the moment placement runs the window is not decorated yet, so
    that margin is zero and the frame came back 700x500 — leaving a 472-pixel
    client area, which `closeEvent` would then store and shrink again by 28
    pixels on every launch.

    So the conversion happens **here**, where the decoration is known:
    `c.clientGeometry` is the client area and `c.frameGeometry` the frame, and
    KWin has both correct at the moment the script runs (measured: frame
    700x500, client 700x472). A KWin too old to expose `clientGeometry` falls
    back to sending the size unconverted, which is what an undecorated window
    wants anyway.

    Windows are matched by our own PID, and transients are skipped so a dialog
    that happens to come first is never placed instead of the main window.
    `clientList` is Plasma 5's spelling and `windowList` Plasma 6's; OneUp
    claims both and calls only the second.
    """
    return f"""\
var wins = (workspace.windowList ? workspace.windowList()
                                 : workspace.clientList());
for (var i = 0; i < wins.length; i++) {{
    var c = wins[i];
    if (c.pid !== {int(pid)} || c.transientFor) continue;
    var dw = 0, dh = 0;
    if (c.clientGeometry) {{
        dw = c.frameGeometry.width - c.clientGeometry.width;
        dh = c.frameGeometry.height - c.clientGeometry.height;
    }}
    c.frameGeometry = {{
        x: {int(target.x)},
        y: {int(target.y)},
        width: {int(target.width)} + dw,
        height: {int(target.height)} + dh
    }};
    break;
}}
"""


def run_kwin_script(
    js: str,
    state_dir: Path,
    run: Callable[..., subprocess.CompletedProcess[bytes]] | None = None,
) -> bool:
    """Load, start and unload a one-shot KWin script. True if it was asked.

    True means the three D-Bus calls were made and each was accepted, **never
    that the window moved** — KWin reports nothing back about what the script
    did, and this module has no way to observe the result. The caller reads the
    window's own geometry if it wants to know, which is what ADR-0007's
    behavioural verification does.

    A nonzero exit status is the only failure `dbus-send` reports, and it means
    the CALL did not land: off KWin the session bus answers `ServiceUnknown`,
    and discarding that left the Centre action offered and doing nothing, which
    ADR-0007 forbids in as many words (LWSM-1170). Measured against real KWin on
    2026-08-25, the status says nothing about the script itself — a `loadScript`
    naming a file that does not exist still exits 0, as does an `unloadScript`
    for a name never registered. So every call is checked, because a failure
    that reaches one reaches all three, and none can tell us more than that.

    The script goes to a private temporary file in an owner-only state
    directory at 0600 (`mkstemp`'s mode), not to a predictable path: between
    writing it and KWin reading it, a predictable path is a symlink-replacement
    target, and what would be swapped in is a file the compositor executes.

    `run` is injected so a test can drive the Wayland branch without a
    compositor. Failure is a warning and a `False`, never an exception: a
    window in the wrong place is a nuisance, and a traceback out of a startup
    path is not.
    """
    # Resolved here, not in the signature, for `placement_available`'s reason:
    # a default argument is bound at definition time and no monkeypatch of the
    # module reaches it.
    runner = subprocess.run if run is None else run
    handle, name = None, None
    try:
        # `applog`'s, not a third copy: `mkdir(parents=True, mode=0o700)` sets
        # the mode on the leaf alone and leaves every parent it created at the
        # umask default (measured 0o755 again on 2026-08-25), and `exist_ok`
        # accepts a directory already left loose. That function creates each
        # component explicitly and re-chmods the leaf. `supervisor.py` reaches
        # for the same private name for the same tree.
        applog._prepare_state_dir(state_dir)
        handle, name = tempfile.mkstemp(suffix=".js", prefix="place-", dir=state_dir)
        with os.fdopen(handle, "w", encoding="utf-8") as script:
            # The descriptor is now owned by the file object, so the `finally`
            # below must not close it a second time.
            handle = None
            script.write(js)

        base = [
            "dbus-send",
            "--session",
            "--dest=org.kde.KWin",
            "--print-reply",
            "/Scripting",
        ]
        for call in (
            [
                *base,
                "org.kde.kwin.Scripting.loadScript",
                f"string:{name}",
                f"string:{KWIN_SCRIPT_NAME}",
            ],
            [*base, "org.kde.kwin.Scripting.start"],
            [
                *base,
                "org.kde.kwin.Scripting.unloadScript",
                f"string:{KWIN_SCRIPT_NAME}",
            ],
        ):
            # An argument vector, never a shell string (`coding.md § O4`).
            result = runner(call, capture_output=True, timeout=DBUS_TIMEOUT_S)
            if result.returncode != 0:
                # `dbus-send` puts the reason on stderr, which is why the calls
                # capture output they otherwise never read.
                log.warning(
                    "KWin would not accept %s: %s",
                    call[len(base)],
                    result.stderr.decode("utf-8", "replace").strip()
                    or f"exit status {result.returncode}",
                )
                return False
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        log.warning("could not ask KWin to place the window: %s", exc)
        return False
    finally:
        if handle is not None:
            os.close(handle)
        if name is not None:
            try:
                os.unlink(name)
            except OSError:
                pass
    return True


def place_window(
    target: Rect,
    *,
    screens: Sequence[Rect],
    pid: int,
    move: Callable[[int, int], None],
    state_dir: Path,
    environ: dict[str, str] | None = None,
    which: Callable[[str], str | None] | None = None,
    run: Callable[..., subprocess.CompletedProcess[bytes]] | None = None,
) -> Rect | None:
    """Ask for `target`, and return the rectangle actually asked for.

    One path for both jobs ADR-0007 names — restoring a remembered position and
    centring — because they differ only in how the target was computed. The
    clamp happens here rather than in either caller, so neither can forget it.

    `None` means placement was not attempted: either the session cannot honour
    it (`placement_available`), or the ask itself failed. The caller reports
    that rather than leaving the user with an action that appears to work.

    `move` is the X11 half, injected because performing it needs `QtWidgets`
    and this module may not import it (`coding.md § O1`). It is a seam in the
    testing sense too — `place_window` is then drivable with no window at all.
    """
    if not placement_available(environ, which):
        return None
    asked = clamp_to_screens(target, screens)
    if on_wayland(environ):
        runner = subprocess.run if run is None else run
        if not run_kwin_script(kwin_script(asked, pid), state_dir, runner):
            return None
    else:
        move(asked.x, asked.y)
    return asked
