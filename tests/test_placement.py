"""`placement.py` — the arithmetic and the KWin call, with no window at all.

The module imports no Qt, so every test here runs without a display, a
`QApplication` or an event loop. That is the point of the split: what
ADR-0007 calls a security boundary is decided by `clamp_to_screens` and
`kwin_script`, and a boundary is worth testing on its own.

Whether the WINDOW ends up where it was asked to go is a different question and
is `test_mainwindow.py`'s — ADR-0007 requires that one to be behavioural, and
nothing here observes a window.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

from lwsm.placement import (
    DBUS_TIMEOUT_S,
    KWIN_SCRIPT_NAME,
    Rect,
    centre_in,
    clamp_to_screens,
    kwin_script,
    on_wayland,
    pair_or_none,
    place_window,
    placement_available,
    position_is_readable,
    run_kwin_script,
)

WAYLAND = {"XDG_SESSION_TYPE": "wayland"}
X11 = {"XDG_SESSION_TYPE": "x11"}
# A two-monitor desk, the right-hand screen offset by the left one's width.
LEFT = Rect(0, 0, 1920, 1080)
RIGHT = Rect(1920, 0, 1920, 1080)


def have_dbus_send(_name: str) -> str | None:
    return "/usr/bin/dbus-send"


def no_dbus_send(_name: str) -> str | None:
    return None


class FakeRun:
    """Stands in for `subprocess.run`, recording the argument vectors."""

    def __init__(self, fail: Exception | None = None) -> None:
        self.calls: list[list[str]] = []
        self.kwargs: list[dict[str, object]] = []
        self.scripts: list[str] = []
        self._fail = fail

    def __call__(self, argv: list[str], **kwargs: object) -> None:
        self.calls.append(list(argv))
        self.kwargs.append(dict(kwargs))
        # Read the script back while KWin still could — the file is deleted the
        # moment `run_kwin_script` returns, so a test that read it afterwards
        # would be reading nothing.
        for arg in argv:
            if arg.startswith("string:") and arg.endswith(".js"):
                self.scripts.append(Path(arg[len("string:") :]).read_text())
        if self._fail is not None:
            raise self._fail


# --- The arithmetic -------------------------------------------------------


def test_a_rectangle_already_on_a_screen_is_returned_unchanged() -> None:
    """The common case: nothing was unplugged, so nothing moves."""
    target = Rect(100, 200, 800, 600)

    assert clamp_to_screens(target, [LEFT, RIGHT]) == target


def test_a_window_remembered_on_an_unplugged_monitor_comes_back_onto_a_screen() -> None:
    """ADR-0007's reason for clamping at all: restored off-screen, the window
    cannot be reached to be fixed."""
    # `y` chosen to fit as it stands, so this test is about the axis that
    # moves. The other axis has its own case below.
    orphan = Rect(3000, 200, 800, 600)

    landed = clamp_to_screens(orphan, [LEFT])

    assert landed.overlap(LEFT) == landed.width * landed.height
    # Pushed left until it fits, not centred — it keeps as much of the
    # remembered position as the screen allows, and the size is untouched.
    assert landed == Rect(LEFT.width - 800, 200, 800, 600)


def test_a_window_hanging_off_the_bottom_is_lifted_until_it_fits() -> None:
    """The vertical half, which is what a shorter screen produces rather than
    an unplugged one — and the case that caught this file's own first draft."""
    low = Rect(0, 900, 800, 600)

    assert clamp_to_screens(low, [LEFT]) == Rect(0, LEFT.height - 600, 800, 600)


def test_a_window_larger_than_the_screen_is_shrunk_to_it() -> None:
    """The other half of ADR-0007's validation: a size from a bigger display."""
    huge = Rect(0, 0, 4000, 3000)

    assert clamp_to_screens(huge, [LEFT]) == Rect(0, 0, 1920, 1080)


def test_a_window_straddling_two_screens_stays_on_the_one_it_is_mostly_on() -> None:
    """Chosen by overlap area, so a window nudged across the seam does not jump
    to the other monitor."""
    mostly_right = Rect(1800, 100, 800, 600)

    landed = clamp_to_screens(mostly_right, [LEFT, RIGHT])

    assert landed.overlap(RIGHT) > landed.overlap(LEFT)
    assert landed.x >= RIGHT.x


def test_clamping_against_no_screens_changes_nothing() -> None:
    """The headless case. Refusing to place a window because Qt reported no
    screens is a worse answer than trying."""
    target = Rect(10, 20, 30, 40)

    assert clamp_to_screens(target, []) == target


def test_centring_puts_the_window_in_the_middle_of_the_usable_area() -> None:
    """`area` is `availableGeometry`, so the result respects panels."""
    area = Rect(0, 40, 1920, 1040)

    centred = centre_in(area, 800, 600)

    assert centred.x + centred.width // 2 == area.x + area.width // 2
    assert centred.y + centred.height // 2 == area.y + area.height // 2


@pytest.mark.parametrize("values", [(None, 0), (0, None), (None, None)], ids=str)
def test_half_a_pair_is_not_a_pair(values: tuple[int | None, int | None]) -> None:
    """`settings.load` refuses each field on its own, so a hand-edited file can
    arrive with an `x` and no `y`. Inventing the other restores a position the
    window was never at; falling back to the default is not a guess."""
    assert pair_or_none(*values) is None


def test_both_values_make_a_pair() -> None:
    """`0` is deliberately in the fixture above and here: it is a real
    coordinate, and a check written as `if not first` would refuse it."""
    assert pair_or_none(0, 0) == (0, 0)
    assert pair_or_none(3, 4) == (3, 4)


def test_a_position_can_be_set_under_wayland_but_never_read() -> None:
    """The asymmetry the whole item turns on, and the reason position and size
    are separate pairs rather than one rectangle.

    Wayland gives a client no global coordinates, so Qt answers 0,0 forever —
    a plausible position rather than an error, which would be written to
    `settings.json` as though it were true. Measured 2026-08-21: KWin reported
    this app's window at 640,480 while Qt reported 0,0. Setting a position
    still works there, through KWin, which is why `placement_available` says
    yes to the same session this says no to.
    """
    assert placement_available(WAYLAND, have_dbus_send)
    assert not position_is_readable(WAYLAND)
    assert position_is_readable(X11)
    assert position_is_readable({})


# --- Which platform, and whether we can ask -------------------------------


def test_the_session_type_is_the_only_platform_test() -> None:
    """ADR-0007 specifies `XDG_SESSION_TYPE`, matched case-insensitively."""
    assert on_wayland({"XDG_SESSION_TYPE": "Wayland"})
    assert not on_wayland(X11)
    assert not on_wayland({})


def test_placement_is_unavailable_on_wayland_without_dbus_send() -> None:
    """The one case that disables the Centre action: the compositor owns
    placement and there is no way to ask it."""
    assert not placement_available(WAYLAND, no_dbus_send)


def test_placement_is_available_on_wayland_with_dbus_send_and_always_on_x11() -> None:
    """Optimistic off Wayland on purpose — nothing inside the process tells an
    X11 session from a non-KWin Wayland one, and disabling the action on every
    X11 desktop to be honest about GNOME is the worse trade."""
    assert placement_available(WAYLAND, have_dbus_send)
    assert placement_available(X11, no_dbus_send)


# --- The script, which runs inside the compositor -------------------------


def test_the_script_carries_the_target_position_and_our_own_pid() -> None:
    script = kwin_script(Rect(300, 400, 800, 600), pid=4242)

    assert "x: 300," in script
    assert "y: 400," in script
    assert "c.pid !== 4242" in script
    # Transients skipped, so a dialog that happens to come first is never
    # placed instead of the main window.
    assert "c.transientFor" in script
    # Both spellings: `clientList` is Plasma 5's and `windowList` Plasma 6's.
    assert "workspace.windowList" in script
    assert "workspace.clientList" in script


def test_the_script_sends_the_size_and_lets_kwin_add_the_decoration() -> None:
    """KWin's geometry write is authoritative, so a size it is not given is a
    size the window does not keep — and the size it is given is a CLIENT size.

    Both halves were written the other way round first and both were refuted
    by measurement rather than by review (2026-08-21, real KWin, Plasma 6
    Wayland). Sending no size at all left a 700x500 window at its undecorated
    minimum of 239x216. Converting in the caller sent a 28-pixel decoration as
    0, because the window is not decorated yet when placement runs, and each
    launch then lost a title bar's height. `c.clientGeometry` is where the
    answer actually is.
    """
    script = kwin_script(Rect(0, 0, 800, 600), pid=1)

    assert "width: 800 + dw" in script
    assert "height: 600 + dh" in script
    # The fallback matters: a KWin with no `clientGeometry` must still place
    # the window, with the size unconverted rather than with a crash.
    assert "if (c.clientGeometry)" in script
    assert "var dw = 0, dh = 0;" in script


def test_a_coordinate_that_is_not_a_number_cannot_reach_the_compositor() -> None:
    """The security boundary ADR-0007 names. `settings.json` is hand-editable
    by design, `loadScript` runs what we write **inside KWin's scripting
    engine**, and that engine can move and close every window on the desktop,
    read window titles and reach `callDBus`.

    A `Rect` is not validated on construction — it is a plain dataclass — so
    this drives the refusal that actually stands between the file and the
    compositor: every value is put through `int()` on the way into the
    template, and `int()` refuses rather than interpolating.
    """
    attack = Rect(x="0); workspace.slotWindowClose(); //", y=0, width=1, height=1)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="invalid literal"):
        kwin_script(attack, pid=1)


def test_a_float_coordinate_is_truncated_rather_than_interpolated() -> None:
    """JSON has one number type, so a hand-edited `1.5` is plausible. It must
    reach the script as a number, never as the text `1.5` inside a rectangle
    literal that KWin would then have to parse."""
    script = kwin_script(Rect(x=1.9, y=-2.9, width=1, height=1), pid=1)  # type: ignore[arg-type]

    assert "x: 1," in script
    assert "y: -2," in script


# --- The D-Bus call -------------------------------------------------------


def test_the_script_is_written_privately_and_then_deleted(tmp_path: Path) -> None:
    """`mkstemp` in the app's own state directory, at 0600. A predictable path
    is a symlink-replacement target in the window between writing the file and
    KWin reading it — and what would be swapped in is a file the compositor
    executes."""
    seen: list[tuple[Path, int]] = []

    def inspect(argv: list[str], **_kwargs: object) -> None:
        for arg in argv:
            if arg.startswith("string:") and arg.endswith(".js"):
                path = Path(arg[len("string:") :])
                seen.append((path, stat.S_IMODE(path.stat().st_mode)))

    assert run_kwin_script("// script", tmp_path / "state", inspect)

    assert len(seen) == 1
    path, mode = seen[0]
    assert path.parent == tmp_path / "state"
    assert mode == 0o600
    # Deleted on the way out, so a crashed compositor does not leave a trail of
    # scripts in the state directory.
    assert not path.exists()
    assert list((tmp_path / "state").iterdir()) == []


def test_the_three_dbus_calls_are_argument_vectors_with_a_deadline(
    tmp_path: Path,
) -> None:
    """`coding.md § O4` — an argument vector, never a shell string. The timeout
    is what stops a wedged compositor taking the window with it."""
    run = FakeRun()

    assert run_kwin_script("// script", tmp_path, run)

    verbs = [argv[5] for argv in run.calls]
    assert verbs == [
        "org.kde.kwin.Scripting.loadScript",
        "org.kde.kwin.Scripting.start",
        "org.kde.kwin.Scripting.unloadScript",
    ]
    for argv, kwargs in zip(run.calls, run.kwargs, strict=True):
        assert argv[0] == "dbus-send"
        assert kwargs["timeout"] == DBUS_TIMEOUT_S
    assert f"string:{KWIN_SCRIPT_NAME}" in run.calls[0]
    assert f"string:{KWIN_SCRIPT_NAME}" in run.calls[2]


def test_a_failed_dbus_call_is_a_false_and_still_cleans_up(tmp_path: Path) -> None:
    """A window in the wrong place is a nuisance; a traceback out of a startup
    path is not a window."""
    run = FakeRun(fail=subprocess.SubprocessError("no session bus"))

    assert not run_kwin_script("// script", tmp_path, run)
    assert list(tmp_path.iterdir()) == []


def test_an_unwritable_state_directory_is_a_false_not_a_crash(tmp_path: Path) -> None:
    """The same answer for the filesystem half. `applog` already refuses
    several hostile states, and none of them may cost the user a window."""
    blocked = tmp_path / "wall"
    blocked.write_text("not a directory")

    assert not run_kwin_script("// script", blocked / "state", FakeRun())


# --- One path, two targets ------------------------------------------------


def test_on_x11_the_move_is_asked_for_at_the_clamped_position() -> None:
    """The clamp happens inside `place_window` rather than in either caller, so
    neither can forget it — including the Centre action, which computes its own
    target."""
    moved: list[tuple[int, int]] = []

    asked = place_window(
        Rect(5000, 0, 800, 600),
        screens=[LEFT],
        pid=1,
        move=lambda x, y: moved.append((x, y)),
        state_dir=Path("/nonexistent"),
        environ=X11,
        which=no_dbus_send,
    )

    assert asked == Rect(LEFT.width - 800, 0, 800, 600)
    assert moved == [(asked.x, asked.y)]


def test_on_wayland_the_compositor_is_asked_and_move_is_never_called(
    tmp_path: Path,
) -> None:
    """`move()` is accepted and silently ignored there, which is the failure
    ADR-0007 exists to avoid. Asserted as "never called" because a `move()` left
    in the Wayland path looks exactly like working code."""
    run = FakeRun()
    moved: list[tuple[int, int]] = []

    asked = place_window(
        Rect(300, 400, 800, 600),
        screens=[LEFT],
        pid=99,
        move=lambda x, y: moved.append((x, y)),
        state_dir=tmp_path,
        environ=WAYLAND,
        which=have_dbus_send,
        run=run,
    )

    assert asked == Rect(300, 400, 800, 600)
    assert moved == []
    assert "x: 300," in run.scripts[0]
    assert "c.pid !== 99" in run.scripts[0]


def test_placement_that_cannot_be_asked_for_returns_none(tmp_path: Path) -> None:
    """What the Centre action reports to the user rather than appearing to
    work. Both routes to it: the session cannot honour placement at all, and
    the ask itself failed."""
    moved: list[tuple[int, int]] = []
    args = {
        "screens": [LEFT],
        "pid": 1,
        "move": lambda x, y: moved.append((x, y)),
        "state_dir": tmp_path,
        "environ": WAYLAND,
    }

    assert place_window(Rect(0, 0, 800, 600), which=no_dbus_send, **args) is None
    assert (
        place_window(
            Rect(0, 0, 800, 600),
            which=have_dbus_send,
            run=FakeRun(fail=OSError("dbus-send is not executable")),
            **args,
        )
        is None
    )
    assert moved == []


def test_the_real_environment_is_read_when_none_is_injected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`environ=None` is the production path, and every other test here injects
    one — so without this the default argument is never exercised and a
    `place_window` that ignored the real session would pass the file."""
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    assert on_wayland()
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    assert not on_wayland()
    monkeypatch.delenv("XDG_SESSION_TYPE", raising=False)
    assert not on_wayland()
    assert os.environ.get("XDG_SESSION_TYPE") is None
