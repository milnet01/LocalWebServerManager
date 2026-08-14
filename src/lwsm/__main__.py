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
    from lwsm.supervisor import Supervisor
    from lwsm.theme import Theme

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

    probe = PortProbe()
    # One probe for both jobs: the poll classifies from it, and the supervisor's
    # pre-flight check asks the same socket table rather than opening a second
    # view of it that could disagree.
    supervisor = Supervisor(probe=probe)
    controller = ProjectController(records, probe, supervisor)
    window = MainWindow(
        controller,
        Theme.default(),
        notices,
        # The load is carried through so the writer's read-only gate can read
        # it: a session whose registry refused a row must not have that row
        # deleted by a rescan (LWSM-1007 § 4.3).
        load=load,
        rescan=RescanContext(projects_path=projects_path, roots=default_scan_roots()),
    )
    if error is not None:
        window.set_status_message(error)
    # Still polls with zero records: INV-5's zero-record case depends on it.
    controller.start_polling()
    return window, controller


def default_scan_roots() -> tuple[Path, ...]:
    """`~/projects`, until the settings dialog (LWSM-1018) owns this.

    A function rather than a module constant so it is not evaluated at import
    time, which is the shape `default_projects_path` already takes and the
    reason `build_window` resolves paths inside its own handler. A home
    directory that cannot be resolved yields no roots rather than raising: a
    machine with nowhere to scan should still open a window.
    """
    try:
        return (Path.home() / "projects",)
    except RuntimeError:
        return ()


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
