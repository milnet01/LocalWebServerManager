"""Entry point for the `lwsm` console script and `python -m lwsm`.

Both name `run()`, not `main()`. See `run()` for why the two are separate.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING

from lwsm import __version__, applog

if TYPE_CHECKING:
    # Type-checking only: the runtime imports stay inside build_window so
    # `--version` and `--help` need no Qt and therefore no display (INV-14).
    from lwsm.controller import ProjectController
    from lwsm.mainwindow import MainWindow


def build_window(
    projects_path: Path | None = None,
) -> tuple[MainWindow, ProjectController]:
    """Load, construct and connect. Does not run an event loop.

    Split out of `main` so LWSM-1005 INV-15 can observe the RegistryError
    catch: `main` ends in a blocking `app.exec()`, so a test that called it
    would never return, and a test that built the window itself would be
    testing the window rather than the catch.

    `projects_path` defaults to `None` — meaning "resolve it here" — because
    **resolving it can raise**, and until 2026-08-07 `main` called
    `build_window(default_projects_path())`, which evaluates the argument
    *before* entering the function and therefore outside the only catch written
    for it. On a machine with no home directory the guard `default_projects_path`
    has carried since LWSM-1026 produced a `RegistryError` that nothing caught,
    so the app died with a traceback and no window — the guard was there and
    unreachable (LWSM-1116). Tests still pass a path explicitly.
    """
    from lwsm.controller import ProjectController
    from lwsm.mainwindow import MainWindow, RescanContext
    from lwsm.ports import PortProbe
    from lwsm.registry import (
        LoadResult,
        RegistryError,
        default_projects_path,
        load_projects,
    )
    from lwsm.settings import Settings, SettingsError, default_settings_path
    from lwsm.settings import load as load_settings
    from lwsm.settings import save as save_settings
    from lwsm.supervisor import Supervisor
    from lwsm.theme import theme_for_id

    log = applog.get_logger(__name__)
    notices: list[str] = []
    error: str | None = None
    load: LoadResult | RegistryError
    try:
        if projects_path is None:
            projects_path = default_projects_path()
        loaded = load_projects(projects_path)
        load = loaded
        records, notices = loaded.records, loaded.reasons
    except RegistryError as exc:
        # Not fatal: a missing projects.json is a first run, not a crash, for
        # the same reason an unwritable log does not stop startup. No other
        # exception is caught here — a bug must not be disguised as a first run.
        records, error, load = [], str(exc), exc
        log.warning("no project list: %s", exc)
    for notice in notices:
        # The status bar gets a summary; the log gets the record.
        log.warning("project list: %s", notice)

    # The theme, before the window, because the window is built with it.
    #
    # READING it needs no handler: `settings.load` returns a usable `Settings`
    # on every path — missing, unreadable, hostile — precisely so a preference
    # cannot cost the user a window. RESOLVING THE PATH does, and that is what
    # the try below is for: it derives from `default_projects_path`, which
    # raises on a machine with no home directory. LWSM-1116 is the record of
    # what happens when such a guard sits outside its own catch — it is there
    # and unreachable, and the app dies with a traceback and no window.
    # Caught here, the app opens with the default theme and no persistence,
    # which is the same answer it already gives for the log and the project
    # list on that machine.
    settings_path: Path | None = None
    theme_id = Settings().theme
    try:
        settings_path = default_settings_path()
    except RegistryError as exc:
        log.warning("no settings file: %s", exc)
    else:
        chosen = load_settings(settings_path)
        theme_id = chosen.settings.theme
        for reason in chosen.reasons:
            log.warning("settings: %s", reason)
            notices.append(reason)

    def save_theme(chosen_id: str) -> None:
        """Injected rather than defaulted inside `MainWindow`, so a test that
        exercises the picker cannot write to the developer's own config.

        Raises rather than returning quietly when there is nowhere to write:
        `MainWindow.set_theme` reports the failure in the status bar, and a
        switch that silently will not be remembered is worse than one that
        says so.
        """
        if settings_path is None:
            raise SettingsError("there is no writable configuration directory")
        save_settings(settings_path, Settings(theme=chosen_id))

    probe = PortProbe()
    # One probe for both jobs: the poll classifies from it, and the supervisor's
    # pre-flight check asks the same socket table rather than opening a second
    # view of it that could disagree.
    supervisor = Supervisor(probe=probe)
    controller = ProjectController(records, probe, supervisor)
    window = MainWindow(
        controller,
        # `theme_for_id`, not `THEMES[...]`: settings.json is hand-editable and
        # a theme can be removed by an upgrade, so an id naming nothing must
        # fall back rather than raise. `settings.py` deliberately does not
        # check membership — a core module may not import the theme layer.
        theme_for_id(theme_id),
        notices,
        # The load is carried through so the writer's read-only gate can read
        # it: a session whose registry refused a row must not have that row
        # deleted by a rescan (LWSM-1007 § 4.3).
        load=load,
        rescan=RescanContext(projects_path=projects_path, roots=default_scan_roots()),
        save_theme=save_theme,
    )
    if error is not None:
        window.set_status_message(error)
    # Still polls with zero records: INV-5's zero-record case depends on it.
    controller.start_polling()
    return window, controller


SCAN_ROOTS_FILENAME = "scan-roots"
"""The file that lists the directories to scan, beside `projects.json`."""


def default_scan_roots(config: Path | None = None) -> tuple[Path, ...]:
    """The directories to scan, read from a config file, else `~/projects`.

    A function rather than a module constant so it is not evaluated at import
    time, which is the shape `default_projects_path` already takes and the
    reason `build_window` resolves paths inside its own handler. A home
    directory that cannot be resolved yields no roots rather than raising: a
    machine with nowhere to scan should still open a window.

    **Why a file and not just `~/projects` (LWSM-1144).** The hardcoded default
    is right for nobody but its author: a machine that keeps its projects
    anywhere else scans a directory that does not exist, finds nothing, and
    shows an empty window with no indication that the *location* is the
    problem. That is not a missing feature — every part of the app behind it
    works — so the cheapest thing that makes it usable is a way to say where to
    look. The settings dialog (LWSM-1018) still owns the UI; until it exists,
    THIS FILE IS THE SETTING.

    Format is one directory per line. Blank lines and lines whose first
    non-space character is `#` are ignored, so the file can explain itself.
    `~` is expanded. Order is kept, because it is the order the scan walks.

    A file that cannot be read is treated as absent rather than fatal: this
    runs before the window exists, and a config the user cannot fix without a
    window is a worse failure than scanning the default.
    """
    try:
        fallback = (Path.home() / "projects",)
    except RuntimeError:
        fallback = ()

    if config is None:
        # Imported here rather than at module scope for `build_window`'s
        # reason: the entry point resolves paths inside the handler that can
        # report them, and `--version` must not need any of it.
        from lwsm.registry import RegistryError, default_projects_path

        try:
            config = default_projects_path().parent / SCAN_ROOTS_FILENAME
        except (OSError, RuntimeError, RegistryError):
            # `RegistryError` is the one that actually fires, and it is not an
            # OSError: `default_projects_path` has wrapped "there is no home
            # directory" since LWSM-1026, and a machine with no home must still
            # open a window (INV-15) rather than dying here, before there is
            # anything to report the failure in.
            return fallback

    try:
        text = config.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return fallback

    roots = tuple(
        Path(line.strip()).expanduser()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    # An empty or comments-only file means "nothing was configured", not "scan
    # nowhere" — the second is indistinguishable from the first to whoever
    # wrote it, and silently scanning nothing is the failure this exists to fix.
    return roots or fallback


DESKTOP_FILE_NAME = "io.github.milnet01.LocalWebServerManager"
"""The installed `.desktop` entry, without the extension (LWSM-1142).

Not cosmetic. On Wayland the compositor matches a window to a launcher by
`app_id`, and Qt derives that from `argv[0]` unless it is told otherwise — so
without this the pinned entry and the running window are two different things
in the task manager, which is the one job a pin has.
"""


def _identify(app: object) -> None:
    """Name the application to the desktop, before any window exists.

    Separate from `build_window` because it is about the process rather than
    the window, and separate from module scope because it needs the
    `QApplication` that `main` may have found already built (a test session
    has one). Every call is idempotent.

    The icon is set from the installed theme by name rather than from a bundled
    file: the `.desktop` entry already names it, `packaging/` ships it to
    `hicolor`, and reading it from disk here would be a second source for one
    image. A missing theme icon yields a null `QIcon`, which Qt renders as no
    icon rather than failing — the window still opens.
    """
    from PySide6.QtGui import QIcon

    app.setApplicationName("Local Web Server Manager")
    app.setApplicationVersion(__version__)
    app.setDesktopFileName(DESKTOP_FILE_NAME)
    app.setWindowIcon(QIcon.fromTheme(DESKTOP_FILE_NAME))


def main(argv: list[str] | None = None) -> int:
    """Configure logging, then open the window."""
    parser = argparse.ArgumentParser(
        prog="lwsm",
        description=(
            "Find, start, stop and watch the local web servers your projects run."
        ),
    )
    parser.add_argument("--version", action="version", version=f"lwsm {__version__}")
    # Parses sys.argv[1:] when argv is None. This replaces a `"--version" in
    # args` membership test, which had no --help and silently accepted every
    # option it did not recognise — a typo'd flag looked honoured and returned 0.
    parser.parse_args(argv)

    try:
        log_path = applog.configure_logging()
    except OSError as exc:
        # A log we cannot write is worth a warning, not a crash. The 2026-08-06
        # hardening deliberately refuses several hostile filesystem states, so
        # without this branch each of them would kill the app on startup.
        applog.configure_stderr_logging()
        applog.get_logger(__name__).warning(
            "no application log (%s) — continuing without one", exc
        )
        log_path = None
    else:
        applog.get_logger(__name__).info("lwsm %s started", __version__)

    # Printed before the window so a user who cannot see the window still
    # learns where to look.
    print(f"Logging to {log_path}" if log_path else "Not logging to a file.")

    # Imported here, not at module scope, so `--version` and `--help` — which
    # argparse handles above — need no Qt and therefore no display (INV-14).
    from PySide6.QtWidgets import QApplication

    # Qt permits one QApplication per process, and a test session already has
    # one, so reuse it rather than raising.
    app = QApplication.instance() or QApplication([])
    _identify(app)
    # No argument: resolving the default path is itself fallible, so it happens
    # inside build_window's RegistryError catch rather than out here (LWSM-1116).
    window, controller = build_window()
    try:
        window.show()
        return app.exec()
    finally:
        # In a `finally`, so an exception out of show() or exec() cannot leave a
        # pool thread outliving its controller — the race INV-16 exists to
        # prevent. Stops the timer and waits, bounded, for any outstanding probe.
        controller.stop()
        # ADR-0003: the servers themselves are LEFT RUNNING, deliberately —
        # `close()` releases our descriptors and threads and signals nothing.
        controller.close_supervisor()
        # The rescan worker is a second pool with the same hazard, so it gets
        # the same bounded wait rather than being left to `~QThreadPool`, which
        # joins with no timeout at all.
        window.shutdown()


def run() -> int:
    """The shipped `lwsm` command: `main`, then a process exit that is bounded.

    Deliberately separate from `main`. `stop()` bounds only its own wait — a
    pool it gave up on is destroyed at interpreter shutdown, where
    `~QThreadPool` waits for the stuck probe with no timeout, so the app quit
    when the probe said so rather than when the user did (LWSM-1100).

    Ending the process cannot live inside `main`, because tests call `main()`
    in-process: with the exit there, one abandoned probe earlier in the session
    ended the pytest run at 40 % — with exit code 0 and a report that looked
    green, which is the failure this project keeps finding and is not about to
    ship on purpose.
    """
    from lwsm.controller import exit_without_waiting_for_abandoned_probes

    code = main()
    exit_without_waiting_for_abandoned_probes(code)
    return code


if __name__ == "__main__":
    raise SystemExit(run())
