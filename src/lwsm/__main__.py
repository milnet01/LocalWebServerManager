"""Entry point for the `lwsm` console script and `python -m lwsm`.

Both name `run()`, not `main()`. See `run()` for why the two are separate.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from lwsm import __version__, applog

if TYPE_CHECKING:
    # Type-checking only: the runtime imports stay inside build_window so
    # `--version` and `--help` need no Qt and therefore no display (INV-14).
    from lwsm.controller import ProjectController
    from lwsm.mainwindow import MainWindow
    from lwsm.placement import Rect


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
    from lwsm.configfile import ConfigFileError
    from lwsm.controller import ProjectController
    from lwsm.mainwindow import MainWindow, RescanContext
    from lwsm.placement import pair_or_none
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
    # Both defaulted BEFORE the try, not inside the `else`: the branch that
    # raises must still leave every setting bound, or a machine with no home
    # directory trades a caught RegistryError for a NameError.
    theme_id = Settings().theme
    text_scale = Settings().text_scale
    poll_interval_ms = Settings().poll_interval_ms
    log_max_mib = Settings().log_max_mib
    stored = Settings()
    try:
        settings_path = default_settings_path()
    except RegistryError as exc:
        log.warning("no settings file: %s", exc)
    else:
        chosen = load_settings(settings_path)
        theme_id = chosen.settings.theme
        text_scale = chosen.settings.text_scale
        poll_interval_ms = chosen.settings.poll_interval_ms
        log_max_mib = chosen.settings.log_max_mib
        stored = chosen.settings
        for reason in chosen.reasons:
            log.warning("settings: %s", reason)
            notices.append(reason)

    def save_field(**changes: object) -> None:
        """Write ONE setting without dropping the others.

        Read-modify-write rather than `Settings(theme=...)`, which was correct
        while there was one field and became a data-loss bug the moment
        LWSM-1032 added a second: saving a theme built a fresh `Settings`, so
        every other field went back to its default on the way past. That is the
        same shape as the merge writing `None` over a stored port, which is the
        one defect the LWSM-1007 spec gate caught that implementation would
        not have.

        Re-reading rather than holding the loaded value, so a file edited by
        hand while the app is open loses only the field being written.

        Raises rather than returning quietly when there is nowhere to write:
        the window reports the failure in the status bar, and a change that
        silently will not be remembered is worse than one that says so.

        **And it raises when the re-read refused the whole document**
        (LWSM-1163). `load()` never raises, so a trailing comma comes back as
        `Settings()` plus a reason — and writing that out is not a partial
        loss but a total one: every stored value replaced by a default, and
        the malformed text the user could have fixed gone with it.
        `registry.save_projects` refuses for the same reason in almost the
        same words, and `save_geometry` fires on every window close, so this
        is the ordinary path rather than a corner.
        """
        if settings_path is None:
            raise SettingsError("there is no writable configuration directory")
        current = load_settings(settings_path)
        if current.document_refused:
            raise SettingsError(
                "refusing to overwrite the settings file with defaults: "
                + "; ".join(current.reasons)
            )
        save_settings(settings_path, replace(current.settings, **changes))

    def save_theme(chosen_id: str) -> None:
        save_field(theme=chosen_id)

    def save_text_scale(percent: int) -> None:
        save_field(text_scale=percent)

    def save_geometry(rect: Rect | None, maximized: bool, position_known: bool) -> None:
        """Remember where the window was (LWSM-1033, ADR-0007).

        The values go through `save_field` like every other setting, so a
        geometry write cannot drop the theme the same way a theme write once
        dropped everything else — and this is the most frequent writer in the
        app, since it fires on every close.

        `rect is None` means the window had no valid normal geometry to store
        — it was never shown. The stored values are left alone rather than
        cleared: a run that opened no window has learnt nothing about where the
        user wants it.

        `position_known` is false under Wayland, where the client is never told
        where it is. There the size and the maximised flag are written and the
        stored coordinates are **left untouched** — which is why this is a
        read-modify-write and not a whole-document rewrite. A position
        recorded under X11, or typed into the file by hand, therefore survives
        a Wayland session and is still restored by it.
        """
        if rect is None:
            save_field(maximized=maximized)
            return
        changes: dict[str, object] = {
            "width": rect.width,
            "height": rect.height,
            "maximized": maximized,
        }
        if position_known:
            changes |= {"x": rect.x, "y": rect.y}
        save_field(**changes)

    def open_settings() -> None:
        """Preferences (LWSM-1018), applied without a restart.

        Built here rather than in `MainWindow` because this is the only scope
        where BOTH config files and BOTH live objects are in reach: the window
        holds neither the controller's timer nor the supervisor's log cap, and
        scan roots are not in `settings.json` at all. That is what the
        `open_settings` seam was left for (LWSM-1146).

        `window` is read before it is assigned below, which is deliberate and
        safe: this runs on a menu trigger, long after `build_window` returned.
        """
        from lwsm.settingsdialog import SettingsDialog

        current = (
            Settings()
            if settings_path is None
            else load_settings(settings_path).settings
        )
        dialog = SettingsDialog(
            roots=window.scan_roots(),
            poll_interval_ms=current.poll_interval_ms,
            log_max_mib=current.log_max_mib,
            parent=window,
        )
        if dialog.exec() != SettingsDialog.DialogCode.Accepted:
            return
        roots, poll_ms, log_mib = dialog.values()

        # Applied BEFORE the save, and applied even if the save then fails. A
        # setting the user can watch working is worth more than one that only
        # reached a file they cannot see, and the failure is reported either
        # way. Both take effect on the next tick: the timer honours a new
        # interval while running, and `rotate_if_needed` re-reads the cap.
        controller.set_poll_interval_ms(poll_ms)
        supervisor.max_log_bytes = log_mib * 1024 * 1024
        window.set_scan_roots(roots)

        try:
            save_field(poll_interval_ms=poll_ms, log_max_mib=log_mib)
            save_scan_roots(roots)
        except (ConfigFileError, OSError, RuntimeError) as exc:
            # One handler for both files rather than two, because the user's
            # question is the same either way: was this remembered? Which file
            # refused is in the message, since `ConfigFileError` carries the
            # path.
            window.set_status_message(f"Settings could not be saved: {exc}")

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
        text_scale=text_scale,
        save_text_scale=save_text_scale,
        open_settings=open_settings,
        position=pair_or_none(stored.x, stored.y),
        size=pair_or_none(stored.width, stored.height),
        maximized=stored.maximized,
        save_geometry=save_geometry,
    )
    # The stored choices, applied once at startup. `Supervisor` and
    # `ProjectController` default to the same values `settings.py` does, so a
    # first run with no file is already correct and this only moves anything
    # when the user has chosen something.
    controller.set_poll_interval_ms(poll_interval_ms)
    supervisor.max_log_bytes = log_max_mib * 1024 * 1024
    if error is not None:
        window.set_status_message(error)
    # Still polls with zero records: INV-5's zero-record case depends on it.
    controller.start_polling()
    return window, controller


SCAN_ROOTS_FILENAME = "scan-roots"
"""The file that lists the directories to scan, beside `projects.json`."""


SCAN_ROOTS_HEADER = (
    "# Directories to scan for projects, one per line.\n"
    "# Blank lines and lines starting with # are ignored.\n"
)
"""What a file this app wrote says about itself, when the user wrote nothing."""


def scan_roots_path(config: Path | None = None) -> Path:
    """The one expression for where the scan-roots file lives.

    Extracted so the reader below and `save_scan_roots` cannot end up pointing
    at different files — the rule `settings.default_settings_path` follows for
    the same reason, and the failure it prevents is a dialog that appears to
    save and a scan that keeps using the old list.

    Raises whatever `default_projects_path` raises; both callers handle it,
    differently, which is why it is not caught here.
    """
    if config is not None:
        return config
    # Imported here rather than at module scope for `build_window`'s reason:
    # `--version` must not need any of it.
    from lwsm.registry import default_projects_path

    return default_projects_path().parent / SCAN_ROOTS_FILENAME


def save_scan_roots(roots: Sequence[Path], config: Path | None = None) -> None:
    """Write the scan-roots file, keeping what the user wrote at the top.

    **Only the LEADING comment block survives** — every comment and blank line
    before the first directory. Comments interleaved between directories are
    not kept, and that is a stated loss rather than an oversight: keeping one
    would mean deciding which surviving directory it belonged to, and a comment
    silently re-attached to the wrong line is worse than one that is gone.
    LWSM-1144 put comments in this file so it "can explain itself", and a
    header is what that means in practice.

    Atomic, through the same writer `projects.json` and `settings.json` use, so
    a third config file cannot grow a third and subtly different write path.
    (`write_json_atomically` takes bytes; only its name is about JSON.)

    Raises `ConfigFileError` — or whatever `scan_roots_path` raises — when there
    is nowhere to write, for `save_field`'s reason: a change that silently will
    not be remembered is worse than one that says so.
    """
    from lwsm.configfile import write_json_atomically

    path = scan_roots_path(config)
    body = "".join(f"{root}\n" for root in roots)
    data = (_leading_comment_block(path) + body).encode("utf-8")
    write_json_atomically(path, data, prefix=".scan-roots-")


def _leading_comment_block(path: Path) -> str:
    """The file's own header, or ours if it has none we can read.

    Read through `read_bounded` rather than `Path.read_text`: this runs against
    a path the user controls, and that helper is where the FIFO-blocks-forever
    and the read-600 MB-into-memory cases are already closed.
    """
    from lwsm.configfile import ConfigFileError, read_bounded

    try:
        text = read_bounded(path).decode("utf-8")
    except (OSError, UnicodeDecodeError, ConfigFileError):
        return SCAN_ROOTS_HEADER

    kept: list[str] = []
    for line in text.splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            break
        kept.append(line)
    return "".join(f"{line}\n" for line in kept) or SCAN_ROOTS_HEADER


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
    look. **This file is still the setting now that the dialog exists**
    (LWSM-1018): the dialog edits it through `save_scan_roots` rather than
    copying the roots into `settings.json`, so there is one owner and no
    migration. Settled with the user 2026-08-21.

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
        from lwsm.registry import RegistryError

        try:
            config = scan_roots_path()
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
