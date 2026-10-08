"""Shared test setup.

`scripts/local-ci.sh` exports QT_QPA_PLATFORM=offscreen, but a bare `pytest`
does not — and a widget test that opens a real window on a developer's desktop
is the shape `docs/standards/testing-overrides.md § T6` forbids. So set it here when it
is unset, and leave an explicit choice alone.

`XDG_CONFIG_HOME` is pinned for the same reason and is stricter — unset, not
merely defaulted. Since LWSM-1031 `build_window` reads `settings.json`, so a
test that calls it would otherwise pick up the DEVELOPER'S OWN theme: three
tests in `test_mainwindow.py` call it with only `projects_path` pinned, and
they would pass or fail depending on which palette the author last chose in
the real app. `§ T1` calls that an injected seam's whole purpose; here the
seam is an environment variable, so it is pinned here rather than in each
test. A test that sets it itself still wins — `monkeypatch` is applied after
this fixture and undone before the next.

`XDG_SESSION_TYPE` is pinned for exactly that reason, and it was the third
variable to earn it (LWSM-1033). `placement.py` branches on it: a Wayland
session asks KWin to place the window and cannot read its own position back,
while every other session moves the window itself. This machine RUNS Wayland
and the CI runner has the variable unset, so an unpinned test asserting either
branch passes on one and fails on the other — the same two-machines-one-gate
split `CLAUDE.md` records for shellcheck versions and for the 24x24 target
floor. Pinned to `x11`, so the default is the branch that needs no compositor;
a test that wants the Wayland branch sets it itself.

`XDG_DATA_HOME` and `XDG_DATA_DIRS` are the fourth and fifth, and they are the
same argument a third time (LWSM-1187). `browsers.installed()` reads every
`.desktop` file those two name, and `MainWindow` calls it once per window. So
an unpinned test would build its dropdown from whichever browsers the author
happens to have installed — 3 on this machine, an unknown number on the runner
— and would also walk 381 files per window for an answer it does not use.
Pointed at an empty directory, so the default is a machine with no browsers and
every window gets the "Default" entry alone. A test that wants browsers
injects them through `MainWindow`'s `list_browsers` seam, which is what `§ T1`
asks for.

`XDG_RUNTIME_DIR` is the sixth (LWSM-1065). `main()` claims the single-instance
socket there, so unpinned, a test calling `main()` while the developer has the
real app open would find it, ask it to come to the front, and return early —
and a test run would leave its own socket where the real app looks.

`XDG_STATE_HOME`, `XDG_CONFIG_DIRS` and `XDG_CURRENT_DESKTOP` complete the set:
every `XDG_*` variable `src/` reads is pinned here (LWSM-1330).
"""

from __future__ import annotations

import contextlib
import glob
import os
import sys
import time
from pathlib import Path

import psutil
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# How long a child the test already told to stop gets to finish going before it
# counts as left behind. A killed server is reaped a moment after the kill.
CHILD_EXIT_GRACE_SECONDS = 1.0


def _running(child: psutil.Process) -> bool:
    """Still running, and not a zombie waiting for its parent to collect it."""
    try:
        return child.status() != psutil.STATUS_ZOMBIE
    except psutil.Error:
        return False


# pytest rewrites it at every phase of every test, so it is never a leak.
_PYTEST_OWNED_ENVIRON = frozenset({"PYTEST_CURRENT_TEST"})

_SHARED_STATE = pytest.StashKey[tuple[str, dict[str, str], set[int]]]()


def _environ() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in _PYTEST_OWNED_ENVIRON}


def _child_pids() -> set[int]:
    """This process's DIRECT children, read from `/proc`.

    Not `psutil.Process().children()`: that scans every process on the
    machine, 13 ms each with ~3400 running, which is a minute over a run at
    two calls per test (measured 2026-10-08). The kernel's own list costs
    0.07 ms. Direct children only: a grandchild whose parent died is no longer
    ours, and `_no_orphans_outlive_the_run` finds it by cwd. Where the kernel
    lacks the file (CONFIG_PROC_CHILDREN), psutil answers instead.
    """
    files = glob.glob(f"/proc/{os.getpid()}/task/*/children")
    if not files:
        return {child.pid for child in psutil.Process().children()}
    pids: set[int] = set()
    for name in files:
        with contextlib.suppress(OSError):  # a thread ended since the glob
            pids.update(int(pid) for pid in Path(name).read_text().split())
    return pids


@pytest.hookimpl(wrapper=True)
def pytest_runtest_setup(item):
    """Snapshot the shared state before ANY fixture of this test is set up."""
    item.stash[_SHARED_STATE] = (os.getcwd(), _environ(), _child_pids())
    return (yield)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(item, nextitem):
    """Fail the test that left the process's shared state dirty (LWSM-1374).

    Shared testing.md § 7: where tests share a process, each asserts at
    teardown that it left that state clean, so the test that dirtied it fails
    rather than a later one. `pytest-randomly` shuffles the order on every
    run, so a later victim would be a different test each time.

    Three things every test here shares and no fixture restores:

    - **the working directory** — a stray `os.chdir` moves every relative path;
    - **`os.environ`**, written directly rather than through `monkeypatch`;
    - **child processes** still running, which a later test's port or process
      count then trips over. `_no_orphans_outlive_the_run` catches the same
      leak once per run; this names the test.

    A hook around setup and teardown rather than an autouse fixture: a fixture
    cannot be ordered after `monkeypatch`'s undo, so it reported every
    `monkeypatch.setenv` as a leak (measured while building this). Runs after
    every fixture is torn down. A strayed child is killed as well as reported,
    so one leak fails one test.
    """
    result = yield
    if _SHARED_STATE in item.stash:
        _assert_left_clean(*item.stash[_SHARED_STATE])
    return result


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Name the shuffle's seed after every run, `-q` included (LWSM-1399).

    pytest-randomly prints it in the header, which `-q` drops, and the gate
    runs `-q`: the first order-dependent CI failure could not be replayed.
    """
    seed = getattr(config.option, "randomly_seed", None)
    if isinstance(seed, int):
        terminalreporter.write_line(
            f"test order shuffled with --randomly-seed={seed}; "
            "pass that to replay this order"
        )


def _assert_left_clean(cwd: str, environ: dict[str, str], children_before: set[int]):
    problems = []
    if os.getcwd() != cwd:
        problems.append(f"working directory moved to {os.getcwd()}")
        os.chdir(cwd)
    now = _environ()
    if now != environ:
        changed = sorted(
            key
            for key in environ.keys() | now.keys()
            if environ.get(key) != now.get(key)
        )
        problems.append(f"environment variables changed: {', '.join(changed)}")
        for key in changed:
            if key in environ:
                os.environ[key] = environ[key]
            else:
                os.environ.pop(key, None)
    new = []
    for pid in _child_pids() - children_before:
        with contextlib.suppress(psutil.Error):  # exited since the listing
            new.append(psutil.Process(pid))
    # Polled rather than `psutil.wait_procs`, which REAPS a finished child and
    # so takes its exit status from the `Popen` that owns it. A zombie has
    # exited; whoever started it collects it.
    deadline = time.monotonic() + CHILD_EXIT_GRACE_SECONDS
    alive = [child for child in new if _running(child)]
    while alive and time.monotonic() < deadline:
        time.sleep(0.05)
        alive = [child for child in alive if _running(child)]
    for child in alive:
        with contextlib.suppress(psutil.Error):
            problems.append(f"child process {child.pid} {child.cmdline()} running")
            child.kill()
    if problems:
        pytest.fail("test left shared state dirty: " + "; ".join(problems))


@pytest.fixture(autouse=True)
def _isolated_config_home(tmp_path_factory, monkeypatch):
    """Point XDG_CONFIG_HOME at a directory this test owns.

    A fresh one per test, so a test that WRITES a config cannot be seen by the
    next. Nothing is created here: the point is that the path exists nowhere
    until something makes it, which is what a first run looks like.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path_factory.mktemp("xdg-config")))
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    # Its companion since LWSM-1239: `on_wayland` reads this too, so an
    # unpinned one reintroduces the very split the paragraph above pins the
    # first against. This machine exports it and the runner does not, so a
    # test asserting either branch would pass on one and fail on the other.
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    empty = tmp_path_factory.mktemp("xdg-data")
    monkeypatch.setenv("XDG_DATA_HOME", str(empty))
    monkeypatch.setenv("XDG_DATA_DIRS", str(empty))
    # mktemp makes it 0700, which Qt requires of a runtime directory.
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path_factory.mktemp("xdg-rt")))
    # The rest of what `src/` reads (LWSM-1330). Unpinned, a run created
    # `localwebservermanager/` under the developer's real XDG_STATE_HOME
    # (measured with a sentinel), and `mimeapps_paths` read the host's
    # /etc/xdg and its desktop name.
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path_factory.mktemp("xdg-state")))
    monkeypatch.setenv("XDG_CONFIG_DIRS", str(empty))
    monkeypatch.delenv("XDG_CURRENT_DESKTOP", raising=False)


@pytest.fixture(autouse=True)
def reloads(monkeypatch) -> list[str]:
    """Replace `systemctl --user daemon-reload` for every test (LWSM-1028).

    A Start of a service-managed project writes its drop-in under the pinned
    XDG_CONFIG_HOME and then reloads the user's service manager. The write is
    already contained; the reload would reach the developer's REAL systemd, so
    it is a recorder here. A test asserting the reload reads this list.
    """
    from lwsm import service

    calls: list[str] = []

    def record(**_kwargs: object) -> service.UnitOutcome:
        calls.append("daemon-reload")
        return service.UnitOutcome(ok=True, verb="daemon-reload", unit="")

    monkeypatch.setattr(service, "reload_user_manager", record)
    # And the check after it that systemd read the drop-in (review-code
    # 2026-10-08 L05-L3), which would ask the same real manager.
    monkeypatch.setattr(service, "drop_in_seen", lambda unit, path: True)
    return calls


@pytest.fixture(scope="session", autouse=True)
def _reap_abandoned_pools():
    """Do not let the run end holding an abandoned pool (LWSM-1117).

    `~QThreadPool` joins its thread with **no timeout**, and that join happens
    after pytest has printed its report — so the cost is invisible to pytest's
    own number and shows up only as process wall time. Measured 2026-08-07:
    5.09 s reported against **7.67 s** wall, all 2.6 s of it here.

    2.6 s and not forever only because the fake probe that causes it carries a
    5 s timeout; against a probe that truly never returns the same shape hung
    the interpreter indefinitely. The entry point's escape is an `os._exit`,
    which a test process must never take — it would override pytest's exit code
    with this function's, which is exactly how LWSM-1100 produced a run
    truncated to 40 % and reported green. So the suite reaps instead.
    """
    yield
    from lwsm.controller import wait_for_abandoned_pools

    still_live = wait_for_abandoned_pools(5000)
    if still_live:  # pragma: no cover - a diagnosis, not a behaviour
        print(
            f"\n{still_live} abandoned probe pool(s) survived the run; "
            "the test that abandoned one did not release its fake probe.",
            file=sys.stderr,
        )


# The font every test measures in, on this machine and on CI alike (LWSM-1392).
# Unpinned, offscreen Qt takes fontconfig's default sans: Roboto here, DejaVu
# Sans on the ubuntu-24.04 runner. The lens test's row measured 558 px under one
# and 607 px under the other on 2026-10-07, so a width passed locally and failed
# in CI. DejaVu is the wider of the two, so it is the stricter one to hold.
TEST_FONT_FAMILY = "DejaVu Sans"


@pytest.fixture(scope="session", autouse=True)
def _pinned_test_font(qapp):
    """Create the application once, in `TEST_FONT_FAMILY`, before any test.

    Session-wide rather than per GUI test, so it cannot depend on which test
    happens to create the application first under a shuffled order. A missing
    font stops the run: fontconfig would substitute one silently, which is the
    very split this exists to close.
    """
    from PySide6.QtGui import QFont, QFontInfo

    font = QFont(qapp.font())
    font.setFamily(TEST_FONT_FAMILY)
    qapp.setFont(font)
    resolved = QFontInfo(qapp.font()).family()
    if resolved != TEST_FONT_FAMILY:
        pytest.exit(
            f"tests need the {TEST_FONT_FAMILY} font, but Qt resolved "
            f"{resolved!r}; install it (openSUSE: dejavu-fonts, Debian/Ubuntu: "
            "fonts-dejavu-core)",
            returncode=1,
        )


@pytest.fixture(autouse=True)
def _restore_application_appearance():
    """Undo per-test writes to the application palette and font.

    A `QApplication` is created once per session, so both outlive the window
    that set them:

    - `MainWindow` sets the application **palette** (LWSM-1118), so the one
      test that builds a dark theme would otherwise tint every later test —
      and since most assertions here compare colours *relatively*, that would
      surface somewhere unrelated rather than as an obvious failure.
    - The LWSM-1119 test sets the application **font**, which would leave every
      later render at double size and silently change every text metric the
      suite measures.

    A no-op until a `QApplication` exists, which is the non-GUI tests.
    """
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    before = (app.palette(), app.font()) if app is not None else None
    yield
    app = QApplication.instance()
    if app is not None and before is not None:
        app.setPalette(before[0])
        app.setFont(before[1])


@pytest.fixture
def dense_malformed_file(tmp_path: Path) -> Path:
    """A projects.json at `MAX_FILE_BYTES` holding as many rejectable elements
    as fit — the worst case LWSM-1115 bounds.

    The cheapest malformed element is a bare `1`, two bytes with its comma,
    yielding "not an object, skipped". Not contrived: nothing stops a user
    pointing the app at a JSON file that is not a project list at all.

    Shared rather than duplicated because two files assert against it from
    opposite ends — `test_registry.py` that the reason list is capped, and
    `test_mainwindow.py` that the cap actually reaches `build_window`, which is
    where the 8.7 s of no-window was spent.
    """
    from lwsm.registry import MAX_FILE_BYTES

    head, tail = '{"schema_version":1,"projects":[', "]}"
    count = (MAX_FILE_BYTES - len(head) - len(tail) + 1) // 2
    text = head + ",".join("1" for _ in range(count)) + tail
    while len(text.encode()) > MAX_FILE_BYTES:
        count -= 1
        text = head + ",".join("1" for _ in range(count)) + tail
    path = tmp_path / "projects.json"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture(scope="session", autouse=True)
def _no_orphans_outlive_the_run(tmp_path_factory):
    """Fail the run if a test left a process behind, and say which test.

    `CLAUDE.md` has asked a human to run this by hand since 2026-08-14 -- "the
    count before and after a full suite must be equal" -- and the answer was
    no for over a week (LWSM-1189). A check nobody runs is not a check.

    Matched by CWD under THIS run's own temporary directory, never by command
    line. A `pgrep sleep` cannot tell this project's orphan from another
    program's, and on a shared machine it will find both: matching the cwd
    makes every hit ours by construction, and it is also what makes a stray
    attributable to the test that leaked it, since the directory is named
    after it.

    Killed as well as reported. Leaving them running is the harm being
    guarded against, and the failure below is what stops the kill hiding it.
    """
    yield
    base = str(tmp_path_factory.getbasetemp())
    strays = []
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cwd = proc.cwd()
        except (psutil.Error, OSError):
            # Gone between the listing and the question, or not ours to ask
            # about. Either way it is not evidence.
            continue
        if not cwd.startswith(base):
            continue
        strays.append(f"{proc.pid} {' '.join(proc.info['cmdline'] or [])} in {cwd}")
        with contextlib.suppress(psutil.Error, OSError):
            proc.kill()
    if strays:
        pytest.fail(
            "tests left "
            + str(len(strays))
            + " process(es) running:\n  "
            + "\n  ".join(strays)
        )
