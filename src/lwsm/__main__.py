"""Entry point for the `lwsm` console script and `python -m lwsm`."""

from __future__ import annotations

import argparse
from pathlib import Path

from lwsm import __version__, applog


def build_window(projects_path: Path):
    """Load, construct and connect. Does not run an event loop.

    Split out of `main` so LWSM-1005 INV-15 can observe the RegistryError
    catch: `main` ends in a blocking `app.exec()`, so a test that called it
    would never return, and a test that built the window itself would be
    testing the window rather than the catch.
    """
    from lwsm.controller import ProjectController
    from lwsm.mainwindow import MainWindow
    from lwsm.ports import PortProbe
    from lwsm.registry import RegistryError, load_projects
    from lwsm.theme import Theme

    log = applog.get_logger(__name__)
    notices: list[str] = []
    error: str | None = None
    try:
        records, notices = load_projects(projects_path)
    except RegistryError as exc:
        # Not fatal: a missing projects.json is a first run, not a crash, for
        # the same reason an unwritable log does not stop startup. No other
        # exception is caught here — a bug must not be disguised as a first run.
        records, error = [], str(exc)
        log.warning("no project list: %s", exc)
    for notice in notices:
        # The status bar gets a summary; the log gets the record.
        log.warning("project list: %s", notice)

    controller = ProjectController(records, PortProbe())
    window = MainWindow(controller, Theme.default(), notices)
    if error is not None:
        window.set_status_message(error)
    # Still polls with zero records: INV-5's zero-record case depends on it.
    controller.start_polling()
    return window, controller


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

    from lwsm.registry import default_projects_path

    # Qt permits one QApplication per process, and a test session already has
    # one, so reuse it rather than raising.
    app = QApplication.instance() or QApplication([])
    window, controller = build_window(default_projects_path())
    window.show()
    status = app.exec()
    # Stops the timer and waits for any outstanding probe, so a pool thread
    # cannot emit into a controller being torn down.
    controller.stop()
    return status


if __name__ == "__main__":
    raise SystemExit(main())
