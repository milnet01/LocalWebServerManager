"""Entry point — the `lwsm` console script and `python -m lwsm`.

Contract: `CLAUDE.md § Module map` — `main()` handles `--version`, configures
logging, prints where it is logging to, and (since LWSM-1005) opens the window.

These tests cover the two properties a bare `if "--version" in args` cannot
give: an unrecognised option must be refused rather than ignored, and a log
directory the app cannot use must not stop it starting. Both came out of the
2026-08-06 review. LWSM-1005 adds INV-14: `--version` must work with no
display at all.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

from lwsm import __main__ as entry
from lwsm import __version__, applog
from lwsm.__main__ import main


@pytest.fixture(autouse=True)
def _reset_logging():
    """Same process-global reset as `test_applog.py`.

    `main()` configures the real logger, so without this the first test here
    leaks a handler into every later one.
    """
    logger = logging.getLogger(applog.LOGGER_NAME)
    propagate = logger.propagate
    yield
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
    logger.setLevel(logging.NOTSET)
    logger.propagate = propagate


def test_version_is_reported_and_exits_clean(capsys):
    """`--version` is a documented surface, so it is pinned.

    `argparse`'s `action="version"` raises `SystemExit(0)` rather than
    returning, which is the conventional behaviour and what a shell `&&` chain
    expects.
    """
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_an_unknown_option_is_refused(capsys):
    """A membership test accepted anything it did not recognise.

    Before the fix, `main(["--versoin", "--help", "junk"])` printed the startup
    banner and returned 0 — so a typo'd flag looked like it had been honoured,
    and `--help` did not exist at all. Verified 2026-08-06.
    """
    with pytest.raises(SystemExit) as exit_info:
        main(["--versoin"])

    assert exit_info.value.code == 2, "an unusable argument list must not be a success"
    assert "usage" in capsys.readouterr().err.lower()


@pytest.fixture
def _no_event_loop(monkeypatch):
    """Let `main()` return instead of blocking in `app.exec()`.

    Since LWSM-1005 `main` opens a window and runs the loop. The tests below
    are about what happens *before* that, so the loop is stubbed to exit
    immediately — the alternative is a test that never returns.
    """
    from PySide6.QtWidgets import QApplication

    monkeypatch.setattr(QApplication, "exec", lambda self: 0)


@pytest.mark.gui
@pytest.mark.usefixtures("_no_event_loop")
def test_starts_even_when_the_state_directory_is_unusable(
    monkeypatch, capsys, tmp_path: Path
):
    """A diagnostic log that cannot be written is a reason to warn, not to die.

    `configure_logging` raises `OSError` for a read-only filesystem, a full
    disk, an unwritable `~/.local/state` — and, since the 2026-08-06 hardening,
    for every hostile filesystem state it now refuses. Uncaught, that turned a
    log-integrity attack into a total-outage one: reproduced as an unhandled
    traceback and exit 1. Here the state path's parent is a regular file, so
    `mkdir` cannot succeed.
    """
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory\n")
    monkeypatch.setenv("XDG_STATE_HOME", str(blocker))
    # Keep the run off the real config directory too (§ T1).
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    assert main([]) == 0, "an unusable log directory must not stop the app starting"

    captured = capsys.readouterr()
    assert "log" in captured.err.lower(), (
        f"the failure was not reported to the user: {captured.err!r}"
    )


@pytest.mark.gui
@pytest.mark.usefixtures("_no_event_loop")
def test_starts_even_when_there_is_no_home_directory(monkeypatch, capsys, tmp_path):
    """The same promise as the test above, by the one route that bypassed it.

    Drives the real mechanism rather than monkeypatching `Path.home`: with
    `HOME` unset, `posixpath.expanduser` falls back to the passwd entry, and
    with that gone too it returns `~` unexpanded, which `Path.expanduser` turns
    into `RuntimeError`. Measured on 3.13.14 before the fix — `main([])` died
    with `RuntimeError`, `caught by except OSError? False`.

    This asserts a **window**, not just a return code. `main` returning 0 is
    what the stubbed `exec` gives it either way, so a test that stopped there
    would stay green with the window never built.
    """
    import pwd

    def no_passwd_entry(uid: int) -> object:
        raise KeyError(f"no passwd entry for uid {uid}")

    monkeypatch.delenv("HOME", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    # The config path has had this guard since LWSM-1026, so it raises
    # RegistryError and `build_window` turns it into an empty window (INV-15).
    # Left unset on purpose: the two halves of the XDG rule must both survive
    # having no home, and stubbing one of them out would hide half the path.
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(pwd, "getpwuid", no_passwd_entry)

    from lwsm import mainwindow as mainwindow_module

    # Recorded from inside `main`, not read back afterwards: `main`'s local
    # reference is the only one, so the window is destroyed the moment it
    # returns and `QApplication.topLevelWidgets()` comes back empty either way.
    shown: list[str] = []
    monkeypatch.setattr(
        mainwindow_module.MainWindow,
        "show",
        lambda self: shown.append(self.statusBar().currentMessage()),
    )

    assert main([]) == 0, "a machine with no home directory must not stop the app"

    assert len(shown) == 1, "no window was shown"
    # INV-15's actual promise: the window opens *and says why it is empty*.
    # Asserting only that a window exists would stay green if the reason were
    # dropped, which is the LWSM-1113 shape this pass is closing.
    assert "home directory" in shown[0], shown[0]

    captured = capsys.readouterr()
    assert "log" in captured.err.lower(), (
        f"the failure was not reported to the user: {captured.err!r}"
    )


def test_the_console_script_names_run_not_main() -> None:
    """The process-ending exit lives in `run()`, and this pins it there.

    `run()` calls `exit_without_waiting_for_abandoned_probes`, which is an
    `os._exit` when a probe was abandoned (LWSM-1100). `main()` must stay free
    of it because tests call `main()` in-process: while the exit sat inside
    `main`, one abandoned probe earlier in the session ended the pytest run at
    40 % of the suite — **with exit code 0** and a truncated report that read
    as green. Moving it back is the regression this guards.
    """
    import importlib.metadata as metadata

    entry_points = [
        entry
        for entry in metadata.entry_points(group="console_scripts")
        if entry.dist and entry.dist.name == "localwebservermanager"
    ]
    assert [entry.value for entry in entry_points] == ["lwsm.__main__:run"]


@pytest.mark.integration
def test_version_needs_no_display():
    """INV-14 — `--version` must not need a platform plugin.

    argparse handles it before any Qt import, so this passes only while the
    `QApplication` construction stays inside `main` and after `parse_args`.
    Run in a subprocess with the display variables stripped: an in-process test
    would inherit conftest.py's `QT_QPA_PLATFORM=offscreen` and prove nothing.
    """
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"QT_QPA_PLATFORM", "DISPLAY", "WAYLAND_DISPLAY"}
    }
    env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent / "src")

    result = subprocess.run(
        [sys.executable, "-m", "lwsm", "--version"],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert __version__ in result.stdout


# --- LWSM-1113: the two shutdown promises, wired rather than assumed ----------


def test_run_bounds_the_process_exit(monkeypatch) -> None:
    """`run()` must actually call the bound, not merely be named in the metadata.

    `test_the_console_script_names_run_not_main` asserts the entry-point
    *string*, and `test_the_process_exits_promptly_when_a_probe_is_abandoned`
    calls `exit_without_waiting_for_abandoned_probes` directly in its subprocess
    script — so both pass while `run()` does nothing. Reducing `run()` to
    `code = main(); return code`, which deletes the whole of LWSM-1100, left all
    150 tests green (LWSM-1113).

    That call is the single line bounding process exit for the shipped command,
    because `stop()`'s budget covers only its own wait — see LWSM-1117.
    """
    from lwsm import controller as controller_module

    bounded: list[int] = []
    monkeypatch.setattr(entry, "main", lambda: 7)
    monkeypatch.setattr(
        controller_module,
        "exit_without_waiting_for_abandoned_probes",
        lambda code: bounded.append(code),
    )

    assert entry.run() == 7, "run() must return main()'s exit code unchanged"
    assert bounded == [7], (
        "run() returned without bounding the process exit — an abandoned probe "
        "would hold the process open for as long as it takes"
    )


@pytest.mark.gui
@pytest.mark.usefixtures("_no_event_loop")
def test_main_stops_the_controller_when_the_loop_returns(
    monkeypatch, tmp_path: Path
) -> None:
    """`main`'s `finally: controller.stop()` is INV-16's production call site.

    `§ 6` states it as a contract — "without it a pool thread emits into a
    controller being torn down during interpreter shutdown" — and nothing
    observed it: removing the `finally`, and removing the `stop()` call
    outright, each left all 150 tests green (LWSM-1113).

    Fakes rather than the real window, deliberately: what is under test is that
    `main` calls `stop()` on whatever `build_window` handed it, and a real
    controller would make the assertion depend on a poll completing.
    """
    # `main` still configures the real logger and resolves the real config
    # path; both are redirected into tmp_path (§ T1).
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    stops: list[int] = []

    class SpyController:
        def stop(self) -> None:
            stops.append(1)

    shutdowns: list[int] = []

    class FakeWindow:
        def show(self) -> None:
            return None

        def shutdown(self) -> None:
            # The rescan pool is a second thread pool with the controller's
            # hazard (LWSM-1131 § 4.4), so `main` waits for it in the same
            # `finally` — and this double has to answer for it.
            shutdowns.append(1)

    # `_path=None` matches build_window's signature since LWSM-1116: `main`
    # calls it with no argument so the path resolution happens inside its catch.
    monkeypatch.setattr(
        entry, "build_window", lambda _path=None: (FakeWindow(), SpyController())
    )

    assert main([]) == 0
    assert stops == [1], "main() returned without stopping the controller"
    assert shutdowns == [1], "main() returned without waiting for the rescan pool"
