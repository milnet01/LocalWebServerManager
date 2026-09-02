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
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from lwsm import __main__ as entry
from lwsm import __version__, applog, configfile
from lwsm.__main__ import build_window, main


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


def test_no_home_directory_offers_no_rescan_it_cannot_perform(
    qtbot, monkeypatch
) -> None:
    """With nowhere to save, Rescan and the profile entries must not appear.

    `RescanContext.projects_path` is typed `Path` and the dataclass checks
    nothing, so on the branch where `default_projects_path()` raises the
    context was still built — with `None` — and the window offered Rescan,
    Export and Import because `_rescan is not None`. All three end at
    `self._rescan.save(self._rescan.projects_path, ...)` (LWSM-1210).

    Asserted on what a user can reach as well as on the attribute: the
    window's own rule is that a control it cannot honour is not offered, and
    that is the promise being kept.
    """
    import pwd

    from lwsm.__main__ import build_window

    def no_passwd_entry(uid: int) -> object:
        raise KeyError(f"no passwd entry for uid {uid}")

    monkeypatch.delenv("HOME", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setattr(pwd, "getpwuid", no_passwd_entry)

    window, controller = build_window()
    qtbot.addWidget(window)
    controller.stop()

    assert window._rescan is None, "a rescan context was built with no path to save to"
    assert window._rescan_button is None, "Rescan is offered and cannot work"


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

        def close_supervisor(self) -> None:
            # ADR-0003 leaves the SERVERS running; what this releases is our own
            # descriptors and the stop worker (LWSM-1010).
            supervisor_closes.append(1)

    shutdowns: list[int] = []
    supervisor_closes: list[int] = []

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
    assert supervisor_closes == [1], "main() returned without closing the supervisor"


@pytest.mark.gui
@pytest.mark.usefixtures("_no_event_loop")
def test_one_failed_shutdown_step_does_not_defeat_the_other_two(
    monkeypatch, tmp_path: Path
) -> None:
    """Three statements in one `finally` is one statement's worth of cleanup.

    If `controller.stop()` raises, `close_supervisor()` and `shutdown()` never
    run — and the rescan pool then falls to `~QThreadPool`'s UNBOUNDED join,
    which is the LWSM-1100/1139 hazard the block exists to prevent. The
    failure that skips them is exactly the kind of failure that makes the
    remaining two matter (LWSM-1211).

    Each is guarded now, and each failure is logged: a cleanup that could not
    run must not be indistinguishable from one that did.
    """
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    done: list[str] = []

    class FailingController:
        def stop(self) -> None:
            raise RuntimeError("the pool would not settle")

        def close_supervisor(self) -> None:
            done.append("close_supervisor")

    class FakeWindow:
        def show(self) -> None:
            return None

        def shutdown(self) -> None:
            done.append("shutdown")

    monkeypatch.setattr(
        entry,
        "build_window",
        lambda _path=None: (FakeWindow(), FailingController()),
    )

    assert main([]) == 0
    assert done == ["close_supervisor", "shutdown"], (
        f"a failing stop() skipped the rest of the shutdown: {done}"
    )
    # Read from the real log file, not `caplog`: `main` calls
    # `applog.configure_logging()`, which installs its own handler, so the
    # capture fixture sees nothing and an assertion against it would pass
    # against a swallowed exception.
    log_text = (tmp_path / "state" / "localwebservermanager" / "app.log").read_text(
        encoding="utf-8"
    )
    assert "the pool would not settle" in log_text, (
        "the failure was swallowed without a trace"
    )


# --- LWSM-1144: where to scan is configurable ---------------------------------


def test_scan_roots_fall_back_to_projects_when_no_config_exists(tmp_path) -> None:
    """The documented default, and the only behaviour that existed before."""
    absent = tmp_path / "scan-roots"
    assert entry.default_scan_roots(absent) == (Path.home() / "projects",)


def test_scan_roots_are_read_in_order_ignoring_comments_and_blanks(tmp_path) -> None:
    """One directory per line, so the file can explain itself to whoever edits
    it. Order is kept because it is the order the scan walks."""
    config = tmp_path / "scan-roots"
    config.write_text(
        "# where my projects live\n"
        "\n"
        "/srv/first\n"
        "   /srv/second   \n"
        "   # indented comment\n",
        encoding="utf-8",
    )
    assert entry.default_scan_roots(config) == (Path("/srv/first"), Path("/srv/second"))


def test_a_scan_root_expands_a_leading_tilde(tmp_path) -> None:
    """`~/code` is what someone writes in a config file; `Path` alone treats it
    as a literal directory named `~`, which exists nowhere."""
    config = tmp_path / "scan-roots"
    config.write_text("~/code\n", encoding="utf-8")
    assert entry.default_scan_roots(config) == (Path.home() / "code",)


def test_a_config_with_nothing_in_it_falls_back_rather_than_scanning_nowhere(
    tmp_path,
) -> None:
    """Empty and comments-only mean "nothing was configured", not "scan
    nowhere" — the two are indistinguishable to whoever wrote the file, and
    silently scanning nothing is the failure this feature exists to fix."""
    config = tmp_path / "scan-roots"
    config.write_text("# I meant to fill this in\n\n", encoding="utf-8")
    assert entry.default_scan_roots(config) == (Path.home() / "projects",)


def test_an_unreadable_config_falls_back_instead_of_raising(tmp_path) -> None:
    """This runs before the window exists, so a config the user cannot fix
    without a window is a worse failure than scanning the default."""
    config = tmp_path / "scan-roots"
    config.mkdir()  # a directory where a file is expected: the read raises
    assert entry.default_scan_roots(config) == (Path.home() / "projects",)


# --- LWSM-1173: the scan-roots file gets the hardened reader too ---------------


def test_a_fifo_scan_roots_file_falls_back_rather_than_blocking(tmp_path) -> None:
    """This runs inside `build_window` before any window exists, so blocking
    here is the least debuggable failure the app can have: no window, no error,
    no log line, and the `except` never fires because nothing is raised.

    `_leading_comment_block` reads this same file through `read_bounded` and
    returns. Measured 2026-08-27: this one blocked until killed.

    Same alarm safety net as `test_registry.py`, so a regression fails here
    instead of hanging the suite. `_Blocked` derives from `BaseException`
    deliberately: a `TimeoutError` subclasses `OSError` and would be caught by
    the code under test.
    """
    config = tmp_path / "scan-roots"
    os.mkfifo(config)

    class _Blocked(BaseException):
        pass

    def _too_slow(_signum, _frame):
        raise _Blocked("default_scan_roots blocked on the FIFO")

    previous = signal.signal(signal.SIGALRM, _too_slow)
    signal.alarm(5)
    try:
        assert entry.default_scan_roots(config) == (Path.home() / "projects",)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def test_an_oversized_scan_roots_file_falls_back_rather_than_being_read_whole(
    tmp_path,
) -> None:
    """Every line becomes a directory the scanner then walks, so an unbounded
    read is not just memory: measured 2026-08-27, a 2.4 MB file yielded 349,796
    roots at 145 MB RSS. The cap `configfile` already owns bounds both."""
    config = tmp_path / "scan-roots"
    config.write_bytes(b"/srv/x\n" * ((configfile.MAX_FILE_BYTES // 7) + 1))

    assert entry.default_scan_roots(config) == (Path.home() / "projects",)


def test_a_leading_bom_leaves_the_header_a_comment(tmp_path) -> None:
    """Both readers of this file must agree on the decode, or a BOM makes one
    see a header and the other a path. `U+FEFF` decodes fine and `lstrip()`
    leaves it alone, so under plain `utf-8` the user's own comment line becomes
    a scan root — LWSM-1182's class, on the one reader that sweep did not
    reach because it was scoped to `read_bounded` consumers."""
    config = tmp_path / "scan-roots"
    config.write_bytes("﻿# where my projects live\n/srv/first\n".encode())

    assert entry.default_scan_roots(config) == (Path("/srv/first"),)


# --- LWSM-1031: the theme survives a restart ---------------------------------


@pytest.mark.gui
def test_the_stored_theme_is_the_one_the_window_opens_with(
    qtbot, tmp_path, monkeypatch
) -> None:
    """The whole round trip, through `build_window` rather than around it.

    The picker, the palette layer and the settings file are each tested on
    their own; this is the only test that proves they are CONNECTED. The
    window is built twice: once to choose, once to prove the choice came back
    — which is what "survives a restart" means and what a single build cannot
    show.
    """
    from lwsm.settings import default_settings_path
    from lwsm.theme import DEFAULT_THEME, THEMES

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    projects = tmp_path / "projects.json"

    first, controller = build_window(projects)
    qtbot.addWidget(first)
    try:
        assert first._theme is THEMES[DEFAULT_THEME], "a first run must be dark"
        first._theme_actions["parchment"].trigger()
    finally:
        controller.stop()

    assert default_settings_path().exists(), "the choice was not written anywhere"

    second, controller = build_window(projects)
    qtbot.addWidget(second)
    try:
        assert second._theme is THEMES["parchment"]
    finally:
        controller.stop()


@pytest.mark.gui
def test_a_stored_theme_that_no_longer_exists_opens_the_default(
    qtbot, tmp_path, monkeypatch
) -> None:
    """An id naming nothing must not be a window that will not open.

    `settings.py` stores the id without checking membership — a core module
    may not import the theme layer — so this is the path where `theme_for_id`
    is the only thing standing between a removed palette and a `KeyError`
    during construction.
    """
    from lwsm.theme import DEFAULT_THEME, THEMES

    config = tmp_path / "config" / "localwebservermanager"
    config.mkdir(parents=True)
    (config / "settings.json").write_text(
        '{"schema_version": 1, "theme": "retired-in-a-later-build"}\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    window, controller = build_window(tmp_path / "projects.json")
    qtbot.addWidget(window)
    try:
        assert window._theme is THEMES[DEFAULT_THEME]
    finally:
        controller.stop()


@pytest.mark.gui
def test_a_refused_settings_field_is_reported_and_not_silently_defaulted(
    qtbot, tmp_path, monkeypatch
) -> None:
    """`load` returning the defaults is only half the contract.

    A preference that could not be read must not look the same as one that was
    never set — `controller._flush_repeated_error`'s rule, that silence and
    suppression must be distinguishable. So the reason travels from
    `settings.load` to the window, and this is what proves the wire exists: a
    mutant deleting those three lines survived every other test here.
    """
    config = tmp_path / "config" / "localwebservermanager"
    config.mkdir(parents=True)
    (config / "settings.json").write_text(
        '{"schema_version": 1, "theme": 7}\n', encoding="utf-8"
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    # A VALID project list, deliberately. With none, `build_window` ends by
    # calling `set_status_message(error)` for the missing registry, which
    # overwrites the notice summary — so a test without one asserts nothing
    # about settings and reads as a settings failure.
    projects = tmp_path / "projects.json"
    projects.write_text(
        '{"schema_version": 1, "projects": [{"path": "/srv/ok", "name": "ok"}]}\n',
        encoding="utf-8",
    )

    window, controller = build_window(projects)
    qtbot.addWidget(window)
    try:
        assert "theme" in window.statusBar().currentMessage()
    finally:
        controller.stop()


@pytest.mark.gui
def test_the_stored_text_size_is_the_one_the_window_opens_with(
    qtbot, tmp_path, monkeypatch
) -> None:
    """The theme round trip's twin (LWSM-1032), and built twice for the same
    reason: a single build cannot show that a choice SURVIVED anything.

    The application font is process-wide, so it is restored here rather than
    left at whatever the last assertion needed.
    """
    from PySide6.QtWidgets import QApplication

    from lwsm.settings import default_settings_path
    from lwsm.settings import load as load_settings

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    projects = tmp_path / "projects.json"
    app = QApplication.instance()
    assert app is not None
    original = app.font()

    try:
        first, controller = build_window(projects)
        qtbot.addWidget(first)
        try:
            assert first._text_scale == 100, "a first run is not magnified"
            first._text_size_actions[150].trigger()
        finally:
            controller.stop()

        assert load_settings(default_settings_path()).settings.text_scale == 150

        second, controller = build_window(projects)
        qtbot.addWidget(second)
        try:
            assert second._text_scale == 150
            assert second._text_size_actions[150].isChecked()
        finally:
            controller.stop()
    finally:
        app.setFont(original)


@pytest.mark.gui
def test_saving_one_setting_does_not_reset_the_other(
    qtbot, tmp_path, monkeypatch
) -> None:
    """The defect that arrives the moment a second field exists.

    `save_theme` built a fresh `Settings(theme=...)` and wrote it, which was
    correct while `theme` was the only field and silently reverts every other
    one now. It is the same shape as the merge writing `None` over a stored
    port — the one finding of the LWSM-1007 spec gate that implementation
    would not have produced — and it is invisible in any test that changes one
    setting and reads that setting back.

    So: change BOTH, in either order, and assert both survived.
    """
    from PySide6.QtWidgets import QApplication

    from lwsm.settings import default_settings_path
    from lwsm.settings import load as load_settings

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    app = QApplication.instance()
    assert app is not None
    original = app.font()

    try:
        window, controller = build_window(tmp_path / "projects.json")
        qtbot.addWidget(window)
        try:
            window._text_size_actions[175].trigger()
            window._theme_actions["parchment"].trigger()
        finally:
            controller.stop()
    finally:
        app.setFont(original)

    stored = load_settings(default_settings_path()).settings
    assert (stored.theme, stored.text_scale) == ("parchment", 175)


@pytest.mark.gui
def test_a_settings_file_with_a_typo_is_not_overwritten_with_defaults(
    qtbot, tmp_path, monkeypatch
) -> None:
    """LWSM-1163 — the read-modify-write's read can fail wholesale.

    `save_field` re-reads before writing so a hand edit made while the app is
    open loses only the field being written. But `load()` never raises: a
    trailing comma comes back as `Settings()` plus a reason, and writing that
    "current" value out replaced every stored setting with a default AND
    destroyed the malformed text the user could have fixed.

    `registry.py` states the counter-argument in almost the same words it
    needed here — a gate that writes a fresh file over a hand-edited one that
    had only a JSON typo destroys a fully recoverable file.

    Driving the real writer rather than `save_field` directly, for LWSM-1136's
    reason: this defect is entirely about which caller reads what.
    """
    from lwsm.settings import default_settings_path

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    path = default_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    malformed = (
        "{\n"
        '  "schema_version": 1,\n'
        '  "theme": "parchment",\n'
        '  "text_scale": 150,\n'
        '  "poll_interval_ms": 2500,\n'
        '  "log_max_mib": 42,\n'  # <- the trailing comma is the whole defect
        "}\n"
    )
    path.write_text(malformed, encoding="utf-8")

    window, controller = build_window(tmp_path / "projects.json")
    qtbot.addWidget(window)
    try:
        window._theme_actions["emerald"].trigger()
    finally:
        controller.stop()

    assert path.read_text(encoding="utf-8") == malformed


def test_a_refused_settings_write_still_saves_the_scan_roots(
    qtbot, monkeypatch, tmp_path
) -> None:
    """Two independent files shared one `try`, so one refusal lost both.

    `save_field` raises whenever the re-read refused the whole document, which
    a single trailing comma is enough to cause (LWSM-1163) — and that is not
    exotic, it is the state any hand edit can leave. The scan roots were
    applied in memory, never written, and absent next launch, while the
    message spoke only of settings (LWSM-1212).

    The malformed file is the real trigger rather than a patched writer: what
    is under test is that a routine refusal of ONE file does not take the
    other with it.
    """
    from lwsm import settingsdialog as dialog_module
    from lwsm.__main__ import scan_roots_path
    from lwsm.settings import default_settings_path

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    settings_path = default_settings_path()
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.parent.chmod(0o700)
    # The trailing comma is the whole trigger: `load()` reports the document
    # refused, and `save_field` then refuses to write a default over it.
    settings_path.write_text(
        '{\n  "schema_version": 1,\n  "poll_interval_ms": 2500,\n}\n',
        encoding="utf-8",
    )

    chosen = (Path("/srv/alpha"), Path("/srv/beta"))

    class AcceptingDialog:
        DialogCode = dialog_module.SettingsDialog.DialogCode

        def __init__(self, **_kwargs) -> None:
            pass

        def exec(self):
            return self.DialogCode.Accepted

        def values(self):
            return chosen, 1500, 7

    monkeypatch.setattr(dialog_module, "SettingsDialog", AcceptingDialog)

    window, controller = build_window(tmp_path / "projects.json")
    qtbot.addWidget(window)
    try:
        window._settings_action.trigger()
    finally:
        controller.stop()

    assert scan_roots_path().exists(), (
        "the scan roots were never written: a refused settings write took the "
        "healthy one with it"
    )
    written = scan_roots_path().read_text(encoding="utf-8")
    assert "/srv/alpha" in written and "/srv/beta" in written, written

    # And the refusal is SHOWN. `settings.py` records the shape: a version
    # that logged the reason and never displayed it survived every other test.
    message = window.statusBar().currentMessage()
    assert "could not be saved" in message, message
    assert "settings.json" in message, message


def test_both_write_failures_are_named_not_just_the_first(
    qtbot, monkeypatch, tmp_path
) -> None:
    """The bullet asks for both to be collected, and one message can hide one.

    With only ever one file failing in a test, `"; ".join(failures)` and
    `failures[0]` are indistinguishable — a mutant reducing it to the first
    survived until this existed. Both are made to fail: the settings file by a
    trailing comma, the scan-roots path by being a directory.
    """
    from lwsm import settingsdialog as dialog_module
    from lwsm.__main__ import scan_roots_path
    from lwsm.settings import default_settings_path

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    settings_path = default_settings_path()
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.parent.chmod(0o700)
    settings_path.write_text(
        '{\n  "schema_version": 1,\n  "poll_interval_ms": 2500,\n}\n',
        encoding="utf-8",
    )
    # A directory where the file goes: the write cannot succeed, and nothing
    # about it is exotic — an interrupted sync or a stray mkdir leaves this.
    roots_path = scan_roots_path()
    roots_path.parent.mkdir(parents=True, exist_ok=True)
    roots_path.mkdir()

    class AcceptingDialog:
        DialogCode = dialog_module.SettingsDialog.DialogCode

        def __init__(self, **_kwargs) -> None:
            pass

        def exec(self):
            return self.DialogCode.Accepted

        def values(self):
            return (Path("/srv/alpha"),), 1500, 7

    monkeypatch.setattr(dialog_module, "SettingsDialog", AcceptingDialog)

    window, controller = build_window(tmp_path / "projects.json")
    qtbot.addWidget(window)
    try:
        window._settings_action.trigger()
    finally:
        controller.stop()

    message = window.statusBar().currentMessage()
    assert "settings.json" in message, message
    assert "scan-roots" in message, (
        f"the second failure is not in the message: {message}"
    )


def test_clearing_every_scan_root_means_the_same_thing_after_a_restart(
    qtbot, monkeypatch, tmp_path
) -> None:
    """An empty list must not mean two different things.

    `default_scan_roots` ends in `return roots or fallback`, so a file naming
    nowhere means "scan the default" — but `set_scan_roots(())` set the
    session's roots to nothing at all. So clearing the list scanned nothing
    now and silently went back to `~/projects` on the next launch, re-adding
    the projects the user cleared the list to exclude (LWSM-1213).

    Asserted against what a FRESH READ of the file returns, not against a
    literal path: what is being pinned is that the two agree, and hard-coding
    the fallback here would pass even if both ends changed together.
    """
    from lwsm import settingsdialog as dialog_module
    from lwsm.__main__ import default_scan_roots

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    class ClearingDialog:
        DialogCode = dialog_module.SettingsDialog.DialogCode

        def __init__(self, **_kwargs) -> None:
            pass

        def exec(self):
            return self.DialogCode.Accepted

        def values(self):
            return (), 1500, 7

    monkeypatch.setattr(dialog_module, "SettingsDialog", ClearingDialog)

    window, controller = build_window(tmp_path / "projects.json")
    qtbot.addWidget(window)
    try:
        window._settings_action.trigger()
        after_restart = default_scan_roots()
        assert tuple(window.scan_roots()) == tuple(after_restart), (
            f"this session scans {tuple(window.scan_roots())} and the next one "
            f"will scan {tuple(after_restart)}"
        )
    finally:
        controller.stop()


def test_a_settings_save_that_works_says_nothing(qtbot, monkeypatch, tmp_path) -> None:
    """The other half, and neither holds alone.

    An error banner on a successful save is its own defect, and a test that
    only ever drives the failing path cannot tell "reported when it failed"
    from "reported always" — a mutation making the message unconditional
    survived until this existed.
    """
    from lwsm import settingsdialog as dialog_module

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    chosen = (Path("/srv/only"),)

    class AcceptingDialog:
        DialogCode = dialog_module.SettingsDialog.DialogCode

        def __init__(self, **_kwargs) -> None:
            pass

        def exec(self):
            return self.DialogCode.Accepted

        def values(self):
            return chosen, 1500, 7

    monkeypatch.setattr(dialog_module, "SettingsDialog", AcceptingDialog)

    window, controller = build_window(tmp_path / "projects.json")
    qtbot.addWidget(window)
    try:
        window._settings_action.trigger()
    finally:
        controller.stop()

    assert "could not be saved" not in window.statusBar().currentMessage()


# --- LWSM-1018: the scan-roots file the dialog edits ---------------------------


def test_written_roots_are_read_back_in_order(tmp_path) -> None:
    """The writer and the reader agree, including on order.

    Order is the walk order, so a writer that sorted would silently change
    which of two overlapping roots claims a project.
    """
    from lwsm.__main__ import default_scan_roots, save_scan_roots

    config = tmp_path / "scan-roots"
    roots = (Path("/srv/z-last"), Path("/srv/a-first"))

    save_scan_roots(roots, config)

    assert default_scan_roots(config) == roots


def test_the_users_own_header_survives_a_save(tmp_path) -> None:
    """LWSM-1144 put comments in this file so it can explain itself.

    A dialog that erased them the first time it saved would take that away
    without asking. Dies on dropping `_leading_comment_block`.
    """
    from lwsm.__main__ import default_scan_roots, save_scan_roots

    config = tmp_path / "scan-roots"
    config.write_text(
        "# my machine keeps projects in two places\n\n/srv/one\n",
        encoding="utf-8",
    )

    save_scan_roots((Path("/srv/two"),), config)

    text = config.read_text(encoding="utf-8")
    assert "# my machine keeps projects in two places" in text
    assert default_scan_roots(config) == (Path("/srv/two"),)


def test_the_users_own_header_survives_a_save_through_a_bom(tmp_path) -> None:
    """The same header, behind an invisible character (LWSM-1182).

    A BOM does not fail to decode here — `U+FEFF` is a perfectly good
    character — so it survived into the first line, where `lstrip()` left it
    alone because it is not whitespace. `\ufeff# my header` is therefore not a
    comment, the loop breaks on line one, and the whole header was replaced by
    ours. `utf-8-sig` in the read is the fix, matching `registry` and
    `scanner`.

    The sibling above passes on the unfixed code, which is the point of having
    both: the defect is entirely in a character the assertion cannot show.
    """
    from lwsm.__main__ import default_scan_roots, save_scan_roots

    config = tmp_path / "scan-roots"
    config.write_text(
        "# my machine keeps projects in two places\n\n/srv/one\n",
        encoding="utf-8-sig",
    )

    save_scan_roots((Path("/srv/two"),), config)

    text = config.read_text(encoding="utf-8-sig")
    assert "# my machine keeps projects in two places" in text
    assert default_scan_roots(config) == (Path("/srv/two"),)


@pytest.mark.parametrize("hostile", ["undecodable", "unreadable"])
def test_a_scan_roots_file_that_cannot_be_read_is_not_written_over(
    tmp_path, hostile
) -> None:
    """LWSM-1163's shape on the third config file.

    `default_scan_roots` falls back and says nothing, so the dialog offers the
    DEFAULT as though it were the user's list — and that is the value the OK
    button hands back to `save_scan_roots`. `_leading_comment_block` fell back
    on the same input, so the header went with the roots. Measured before the
    fix: a two-line header and five roots became our header and `~/projects`.

    Both hostile states are driven because they are different arms:
    `UnicodeDecodeError` is not an `OSError`, and a fix that closed one left
    the other writing the file away. Only the first is converted, for that
    reason — the second is already a type the caller handles, so the assertion
    is `build_window`'s own handler tuple rather than one class. What is being
    pinned is that the save REFUSES and the bytes survive; which of the two it
    refuses with is the caller's business and is stated in the docstring.
    """
    from lwsm.__main__ import default_scan_roots, save_scan_roots
    from lwsm.configfile import ConfigFileError

    config = tmp_path / "scan-roots"
    payload = b"# my own header\n# and its second line\n\n/srv/one\n/srv/two\n"
    if hostile == "undecodable":
        payload += b"/srv/three\xff\n"
    config.write_bytes(payload)
    if hostile == "unreadable":
        config.chmod(0o000)

    assert default_scan_roots(config) == (Path.home() / "projects",), (
        "precondition: the reader falls back, and says nothing about it"
    )

    with pytest.raises((ConfigFileError, OSError)):
        save_scan_roots(default_scan_roots(config), config)

    config.chmod(0o600)
    assert config.read_bytes() == payload


@pytest.mark.parametrize("name", ["/srv/trailing ", "/srv/two\nlines", "/srv/tabbed\t"])
def test_a_root_the_file_cannot_represent_is_refused_not_silently_lost(
    tmp_path, name
) -> None:
    """The format is one path per line and the reader strips each line, so a
    name ending in whitespace or holding a newline cannot survive the round
    trip. Measured: `/srv/trailing ` came back stripped and therefore pointing
    at a directory that does not exist, and `/srv/two\\nlines` came back as TWO
    roots — the second of them relative, so the scan would walk it from the
    process's working directory.

    Refused at the writer rather than stripped at the chooser (LWSM-1179): the
    chooser is not the only way a root gets here, and a strip would change the
    directory the user picked without saying so. Nothing is written, so the
    previous list survives the refusal.
    """
    from lwsm.__main__ import save_scan_roots
    from lwsm.configfile import ConfigFileError

    config = tmp_path / "scan-roots"

    with pytest.raises(ConfigFileError):
        save_scan_roots((Path(name),), config)

    assert not config.exists(), "the refusal must come before any write"


def test_a_root_with_an_interior_space_still_saves(tmp_path) -> None:
    """The guard is about what the round trip loses, never about spaces.

    A directory called `my projects` is ordinary and round-trips exactly; a
    check written as "reject spaces" would reject it. Dies on widening the
    refusal above.
    """
    from lwsm.__main__ import default_scan_roots, save_scan_roots

    config = tmp_path / "scan-roots"
    roots = (Path("/srv/my projects"),)

    save_scan_roots(roots, config)

    assert default_scan_roots(config) == roots


def test_a_comment_between_roots_is_not_kept_and_that_is_the_contract(
    tmp_path,
) -> None:
    """The stated loss, pinned so it stays a decision rather than a surprise.

    Keeping an interleaved comment would mean deciding which surviving
    directory it belonged to, and one silently re-attached to the wrong line is
    worse than one that is gone. If this test is ever changed, the docstring on
    `save_scan_roots` has to change with it.
    """
    from lwsm.__main__ import save_scan_roots

    config = tmp_path / "scan-roots"
    config.write_text("/srv/one\n# about the next one\n/srv/two\n", encoding="utf-8")

    save_scan_roots((Path("/srv/one"), Path("/srv/two")), config)

    assert "# about the next one" not in config.read_text(encoding="utf-8")


def test_a_file_we_create_explains_itself(tmp_path) -> None:
    """A config file with no header is one the next reader has to guess at."""
    from lwsm.__main__ import default_scan_roots, save_scan_roots

    config = tmp_path / "scan-roots"

    save_scan_roots((Path("/srv/one"),), config)

    text = config.read_text(encoding="utf-8")
    assert text.startswith("#")
    assert default_scan_roots(config) == (Path("/srv/one"),)


# --- LWSM-1018: the dialog reaches the running app ----------------------------


@pytest.mark.gui
def test_stored_numbers_are_applied_at_startup(qtbot, tmp_path, monkeypatch) -> None:
    """A setting nothing reads is a setting that does not exist.

    LWSM-1136 is this project's record of what that looks like: a log cap that
    was implemented, unit-tested and green, and called by nothing outside its
    own test. So this drives `build_window` — the real caller — rather than
    asserting that the setters work.

    Dies on removing either apply line from `build_window`.
    """
    config = tmp_path / "config" / "localwebservermanager"
    config.mkdir(parents=True)
    (config / "settings.json").write_text(
        '{"schema_version": 1, "poll_interval_ms": 4000, "log_max_mib": 32}\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    window, controller = build_window(tmp_path / "projects.json")
    qtbot.addWidget(window)
    try:
        assert controller._timer.interval() == 4000
        assert controller._supervisor.max_log_bytes == 32 * 1024 * 1024
    finally:
        controller.stop()


@pytest.mark.gui
def test_accepting_the_dialog_applies_and_persists_every_field(
    qtbot, tmp_path, monkeypatch
) -> None:
    """The whole seam, end to end, without a modal that would hang the run.

    `exec` and `values` are patched because a real `exec()` blocks the event
    loop with nothing to click it. What is NOT patched is everything this test
    is about: reading the current values, applying them to the live controller
    and supervisor, and writing both files.

    Dies on dropping `open_settings=` from the `MainWindow` call, on either
    apply line, and on either save.
    """
    from lwsm.__main__ import default_scan_roots
    from lwsm.settings import default_settings_path
    from lwsm.settings import load as load_settings
    from lwsm.settingsdialog import SettingsDialog

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    chosen_root = tmp_path / "elsewhere"
    chosen_root.mkdir()

    monkeypatch.setattr(
        SettingsDialog, "exec", lambda self: SettingsDialog.DialogCode.Accepted
    )
    monkeypatch.setattr(
        SettingsDialog, "values", lambda self: ((chosen_root,), 3000, 32)
    )

    window, controller = build_window(tmp_path / "projects.json")
    qtbot.addWidget(window)
    try:
        window._open_settings()

        # Applied to what is running now.
        assert controller._timer.interval() == 3000
        assert controller._supervisor.max_log_bytes == 32 * 1024 * 1024
        assert window.scan_roots() == (chosen_root,)

        # And remembered, in the two files that own them.
        stored = load_settings(default_settings_path()).settings
        assert stored.poll_interval_ms == 3000
        assert stored.log_max_mib == 32
        assert default_scan_roots() == (chosen_root,)
    finally:
        controller.stop()


@pytest.mark.gui
def test_cancelling_the_dialog_changes_nothing(qtbot, tmp_path, monkeypatch) -> None:
    """Reject must not apply, and must not write.

    Dies on dropping the `!= Accepted` early return.
    """
    from lwsm.settingsdialog import SettingsDialog

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(
        SettingsDialog, "exec", lambda self: SettingsDialog.DialogCode.Rejected
    )
    monkeypatch.setattr(
        SettingsDialog, "values", lambda self: ((Path("/never"),), 9999, 999)
    )

    window, controller = build_window(tmp_path / "projects.json")
    qtbot.addWidget(window)
    try:
        before = controller._timer.interval()

        window._open_settings()

        assert controller._timer.interval() == before
        assert window.scan_roots() != (Path("/never"),)
    finally:
        controller.stop()


@pytest.mark.gui
def test_the_window_reopens_where_it_was_closed(qtbot, tmp_path, monkeypatch) -> None:
    """LWSM-1033's round trip, through `build_window` rather than around it.

    The clamp, the placement, the `Settings` fields and `closeEvent` are each
    tested on their own; this is the only test that proves they are CONNECTED
    — that `build_window` reads the five values out of `settings.json`, hands
    them to the window, and wires the saver that puts them back. Built twice,
    for the same reason the theme round trip is: "survives a restart" is not
    something one build can show.

    Driven off Wayland, so the window really moves and the assertion is on
    where it ENDED UP (ADR-0007). The Wayland branch cannot move a window
    without a compositor, and `test_mainwindow.py` covers what it asks for.
    """
    from lwsm.settings import default_settings_path
    from lwsm.settings import load as load_settings

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    projects = tmp_path / "projects.json"

    first, controller = build_window(projects)
    qtbot.addWidget(first)
    try:
        with qtbot.waitExposed(first):
            first.show()
        first.resize(660, 460)
        first.move(90, 130)
        qtbot.wait(1)
        first.close()
    finally:
        controller.stop()

    stored = load_settings(default_settings_path()).settings
    assert (stored.x, stored.y) == (90, 130), "the position was not written"
    assert (stored.width, stored.height) == (660, 460)
    assert stored.maximized is False

    second, controller = build_window(projects)
    qtbot.addWidget(second)
    try:
        with qtbot.waitExposed(second):
            second.show()
        qtbot.wait(1)
        assert (second.pos().x(), second.pos().y()) == (90, 130)
        assert (second.width(), second.height()) == (660, 460)
    finally:
        controller.stop()


@pytest.mark.gui
def test_remembering_the_geometry_does_not_forget_the_theme(
    qtbot, tmp_path, monkeypatch
) -> None:
    """`save_field` read-modify-writes for exactly this reason.

    Writing geometry with a fresh `Settings` would put the theme back to its
    default on the way past — the data-loss shape LWSM-1032 found the first
    time and the one the merge writing `None` over a stored port is a cousin
    of. Five new fields written on every close is the most frequent writer in
    the app, so it is the one most likely to do it.
    """
    from lwsm.settings import default_settings_path
    from lwsm.settings import load as load_settings

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    projects = tmp_path / "projects.json"

    window, controller = build_window(projects)
    qtbot.addWidget(window)
    try:
        window._theme_actions["parchment"].trigger()
        with qtbot.waitExposed(window):
            window.show()
        window.resize(640, 480)
        qtbot.wait(1)
        window.close()
    finally:
        controller.stop()

    stored = load_settings(default_settings_path()).settings
    assert stored.theme == "parchment"
    assert (stored.width, stored.height) == (640, 480)


@pytest.mark.gui
def test_a_wayland_session_does_not_overwrite_a_stored_position(
    qtbot, tmp_path, monkeypatch
) -> None:
    """The saver's Wayland half, end to end through `build_window`.

    A Wayland client is never told where it is, so Qt answers 0,0 — and 0,0 is
    a real position, which would be written as though the user had put the
    window in the corner. `save_geometry` therefore writes the size and the
    maximised flag and leaves the coordinates exactly as they were, which only
    works because `save_field` is a read-modify-write.

    The position under test was recorded by some earlier X11 session, or typed
    into the file by hand. It has to survive a Wayland run, because a position
    that Wayland silently overwrites is one the file can never usefully hold —
    and ADR-0007's whole KWin path exists to restore it.

    `place_window` is replaced, or this test would ask the developer's own
    compositor to move a window (`§ T6`). Found by a mutation that survived the
    suite on 2026-08-21 — this half was asserted in a comment and by nothing
    else.
    """
    import json

    from lwsm import mainwindow as mw
    from lwsm.settings import default_settings_path
    from lwsm.settings import load as load_settings

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setattr(mw.placement, "place_window", lambda *a, **k: None)

    config = tmp_path / "config" / "localwebservermanager"
    config.mkdir(parents=True)
    (config / "settings.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "theme": "midnight",
                "text_scale": 100,
                "poll_interval_ms": 1000,
                "log_max_mib": 5,
                "x": 305,
                "y": 255,
                "width": 700,
                "height": 500,
                "maximized": False,
            }
        ),
        encoding="utf-8",
    )

    window, controller = build_window(tmp_path / "projects.json")
    qtbot.addWidget(window)
    try:
        with qtbot.waitExposed(window):
            window.show()
        # Wait for the RESTORE before resizing. It is deferred to a tick after
        # the first expose, so a resize issued before it lands is undone by it
        # — and the test then measures the stored size rather than the chosen
        # one, which looks exactly like a saver that does not work.
        qtbot.wait(1)
        assert (window.width(), window.height()) == (700, 500)
        window.resize(820, 600)
        qtbot.wait(1)
        window.close()
    finally:
        controller.stop()

    stored = load_settings(default_settings_path()).settings
    assert (stored.x, stored.y) == (305, 255), "Wayland must not overwrite a position"
    assert (stored.width, stored.height) == (820, 600), "the size IS knowable there"
