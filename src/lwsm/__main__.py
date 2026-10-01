"""Entry point for the `lwsm` console script and `python -m lwsm`.

Both name `run()`, not `main()`. See `run()` for why the two are separate.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from lwsm import __version__, applog

if TYPE_CHECKING:
    # Type-checking only: the runtime imports stay inside build_window so
    # `--version` and `--help` need no Qt and therefore no display (INV-14).
    from PySide6.QtNetwork import QLocalServer
    from PySide6.QtWidgets import QApplication

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
        ProjectsFile,
        RegistryError,
        default_projects_path,
        load_projects,
    )
    from lwsm.scanroots import default_scan_roots, save_scan_roots, scan_root_fallback
    from lwsm.settings import Settings, SettingsError, default_settings_path
    from lwsm.settings import load as load_settings
    from lwsm.settings import save as save_settings
    from lwsm.supervisor import Supervisor, TrustStore, default_trust_path
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
        # `list(...)`, not the list itself (LWSM-1271). `notices` is appended
        # to below with the SETTINGS reasons, and aliasing meant those were
        # pushed into the registry `LoadResult`'s own record. Harmless today —
        # both write gates key on `rows_refused` and `document_refused`, not on
        # `reasons` — and harmless is not a reason to keep a mutation of
        # somebody else's value.
        records, notices = loaded.records, list(loaded.reasons)
    except RegistryError as exc:
        # Not fatal: a missing projects.json is a first run, not a crash, for
        # the same reason an unwritable log does not stop startup. No other
        # exception is caught here — a bug must not be disguised as a first run.
        records, error, load = [], str(exc), exc
        log.warning("no project list: %s", exc)
    for notice in notices:
        # The message banner gets a summary; the log gets the record.
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
        for note in chosen.notes:
            log.info("settings: %s", note)
            notices.append(note)

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
        the window reports the failure in its message banner, and a change that
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
        # ANY reason at all, not just a whole-document refusal (LWSM-1271).
        # `document_refused` catches a file nobody can parse. A file that parses
        # with one bad FIELD comes back with that field defaulted and a reason,
        # and writing it out destroyed the user's text — a hand-typed
        # `"text_scale": "150"` became `100` on the next window close, which is
        # this docstring's own argument at a smaller scale: "the malformed text
        # the user could have fixed gone with it".
        #
        # The cost is real and accepted: with one bad field, every write refuses
        # until the file is corrected, and `save_geometry` fires on every close.
        # LWSM-1163 already took that trade for the document case. Refusing is
        # recoverable and overwriting is not.
        #
        # LWSM-1289 is the fuller answer — preserving values this build cannot
        # use instead of defaulting them — and is filed separately.
        # `document_refused` is named although `reasons` is never empty with
        # it set: it is the flag `settings.LoadResult` documents as the
        # writer's gate, and a gate nothing reads is not one (L5-L2).
        if current.document_refused or current.reasons:
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
        # `deleteLater`, on BOTH paths (LWSM-1276). The dialog is parented to
        # the window, so without this every Preferences open leaves a dialog and
        # its whole widget tree alive for the rest of the session — and this is
        # the one window a user opens repeatedly while trying a setting out.
        #
        # Not `WA_DeleteOnClose`, which is the usual answer and is wrong here:
        # `values()` is read AFTER `exec()` returns, and that attribute would
        # have destroyed the widgets holding those values first. `deleteLater`
        # is deferred to the event loop, so it is safe to schedule before the
        # read and is scheduled after it anyway.
        try:
            if dialog.exec() != SettingsDialog.DialogCode.Accepted:
                return
            roots, poll_ms, log_mib = dialog.values()
        finally:
            dialog.deleteLater()

        # Applied BEFORE the save, and applied even if the save then fails. A
        # setting the user can watch working is worth more than one that only
        # reached a file they cannot see, and the failure is reported either
        # way. Both take effect on the next tick: the timer honours a new
        # interval while running, and `rotate_if_needed` re-reads the cap.
        controller.set_poll_interval_ms(poll_ms)
        supervisor.max_log_bytes = log_mib * 1024 * 1024
        # `or scan_root_fallback()`, because an empty list is not "scan
        # nowhere" anywhere else: `default_scan_roots` resolves an empty file
        # to the fallback, so applying `()` literally here made this session
        # disagree with the next one (LWSM-1213).
        window.set_scan_roots(roots or scan_root_fallback())

        # Two files, two attempts, ONE message. Sharing the `try` meant a
        # refusal of the first skipped the second entirely — and `save_field`
        # refuses routinely, since any malformed `settings.json` makes the
        # re-read report the document refused (LWSM-1163). The roots were then
        # applied in memory, never written, and gone next launch, while the
        # message spoke only of settings (LWSM-1212).
        #
        # The single message is kept deliberately: the user's question is the
        # same either way — was this remembered? — and which file refused is in
        # the text, since `ConfigFileError` carries the path.
        failures: list[str] = []
        for write in (
            lambda: save_field(poll_interval_ms=poll_ms, log_max_mib=log_mib),
            lambda: save_scan_roots(roots),
        ):
            try:
                write()
            except (ConfigFileError, OSError, RuntimeError) as exc:
                failures.append(str(exc))
        if failures:
            window.set_status_message(
                "Settings could not be saved: " + "; ".join(failures)
            )

    probe = PortProbe()
    # Confirmations persist (LWSM-1046), so ADR-0003's gate asks once per
    # launcher rather than once a session. With no home directory there is no
    # file: memory only, which asks every session — the safe direction.
    try:
        trust = TrustStore(default_trust_path())
    except RegistryError as exc:
        log.warning("no trust file: %s", exc)
        trust = TrustStore()
    notices.extend(trust.reasons)
    # One probe for both jobs: the poll classifies from it, and the supervisor's
    # pre-flight check asks the same socket table rather than opening a second
    # view of it that could disagree.
    supervisor = Supervisor(probe=probe, trust=trust)
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
        # No path, no file and no rescan. `ProjectsFile.path` is typed `Path`
        # and the dataclass checks nothing, so the branch where
        # `default_projects_path()` raised would build one holding `None` —
        # and every writer the window offers ends at `save(path)` (LWSM-1210).
        # A control that cannot work is not offered, which is the same answer
        # this file already gives for the log and the theme.
        projects_file=(None if projects_path is None else ProjectsFile(projects_path)),
        rescan=(
            None if projects_path is None else RescanContext(roots=default_scan_roots())
        ),
        save_theme=save_theme,
        # The stored id as well as the palette it names, because `follow-system`
        # names a rule instead and no palette expresses it (LWSM-1244). The
        # window resolves it — only it can, since Qt reports the desktop's
        # colour scheme after the `QApplication` is up.
        theme_id=theme_id,
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
        window.show_load_error(error)
    # Still polls with zero records: INV-5's zero-record case depends on it.
    controller.start_polling()
    return window, controller


DESKTOP_FILE_NAME = "io.github.milnet01.LocalWebServerManager"
"""The installed `.desktop` entry, without the extension (LWSM-1142).

Not cosmetic. On Wayland the compositor matches a window to a launcher by
`app_id`, and Qt derives that from `argv[0]` unless it is told otherwise — so
without this the pinned entry and the running window are two different things
in the task manager, which is the one job a pin has.
"""


def _identify(app: QApplication) -> None:
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


# The socket the running copy listens on, in the per-user runtime directory
# ($XDG_RUNTIME_DIR): mode 0700, on tmpfs, and emptied at logout. A crash can
# still leave the file behind, which is why `claim_single_instance` treats a
# socket nobody answers on as stale rather than as a running copy.
INSTANCE_SOCKET_NAME = "localwebservermanager.sock"

# How long a second launch waits for the first to answer. A local socket either
# accepts at once or has no listener, so this bounds a wedged first copy rather
# than a slow one.
INSTANCE_CONNECT_MS = 1000


@dataclass(frozen=True)
class InstanceClaim:
    """What `claim_single_instance` found.

    `primary` False means another copy answered and was asked to come to the
    front, so this one should exit. `server` is the listening socket to keep
    alive and close at shutdown; it is None when this copy runs WITHOUT a guard,
    and `problem` then says why — the app still starts, because refusing to run
    over a socket we cannot create would trade a rare hazard for a certain one.
    """

    primary: bool
    server: QLocalServer | None = None
    problem: str | None = None


def instance_socket_path() -> str:
    """Where the running copy listens.

    `QStandardPaths`' runtime location is `$XDG_RUNTIME_DIR` when it is set
    and usable, and a private fallback directory Qt creates when it is not.
    """
    from PySide6.QtCore import QStandardPaths

    runtime = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.RuntimeLocation
    )
    return str(Path(runtime) / INSTANCE_SOCKET_NAME)


@contextmanager
def _claim_lock(path: str) -> Iterator[None]:
    """Serialise stale-socket recovery between copies launched together.

    An advisory lock beside the socket, in the same private directory. It
    remembers nothing — it is held for the few milliseconds of a recovery and
    released with the file descriptor — so it is not ADR-0004's lock file. An
    unopenable lock file degrades to the unlocked recovery rather than refusing
    to start.
    """
    import fcntl

    try:
        handle = open(f"{path}.lock", "a", encoding="utf-8")
    except OSError:
        yield
        return
    with handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def claim_single_instance(path: str, on_activated: Callable[[], None]) -> InstanceClaim:
    """Become the one running copy, or wake the one that already is (LWSM-1065).

    The user's decision (2026-09-28): only one copy runs, and opening the app a
    second time brings the existing window to the front. That also settles the
    shared `app.log`, which `RotatingFileHandler` cannot rotate safely from two
    processes.

    **Listen first, connect second.** Connecting first and listening on a miss
    lets two copies launched together both miss and both listen. Listening
    first leaves exactly one winner; the loser gets `AddressInUseError`, and
    only then asks whether anyone is actually there. A socket file with no
    listener behind it was left by a copy that crashed, and is removed.

    Not the lock file ADR-0004 rules out: that decision is about remembering
    which SERVERS are running, and this remembers nothing — the listening
    socket is the running copy, and it cannot outlive the process it belongs
    to while anyone could mistake it for one.

    Any connection counts as a request to come to the front; nothing is read
    from it. The runtime directory is the user's own and 0700, so only this
    user can make one. **No socket options**: with any set, Qt binds in a
    scratch directory and RENAMES the socket into place, which silently
    replaces a live copy's socket instead of failing with `AddressInUseError`
    — measured 2026-09-28, where it let a second copy run.
    """
    from PySide6.QtNetwork import QAbstractSocket, QLocalServer, QLocalSocket

    if not Path(path).is_absolute():
        # Qt answers "" for the runtime location when it cannot create its
        # private fallback, and a relative name makes `QLocalServer` listen in
        # the shared temporary directory, where another user could claim it
        # first and stop every launch (L6-L2). Run unguarded instead.
        return InstanceClaim(
            primary=True,
            problem="no private runtime directory, so a second copy is not prevented",
        )
    server = QLocalServer()
    if not server.listen(path):
        if server.serverError() != QAbstractSocket.SocketError.AddressInUseError:
            return InstanceClaim(primary=True, problem=server.errorString())
        probe = QLocalSocket()
        probe.connectToServer(path)
        if probe.waitForConnected(INSTANCE_CONNECT_MS):
            probe.disconnectFromServer()
            return InstanceClaim(primary=False)
        # Nobody answered, so the file is a crashed copy's leftover. Removed
        # under a lock and only after asking again: two copies launched
        # together after a crash both miss above, and without this the second
        # removed the first one's fresh socket and both ran (L6-L3).
        with _claim_lock(path):
            probe = QLocalSocket()
            probe.connectToServer(path)
            if probe.waitForConnected(INSTANCE_CONNECT_MS):
                probe.disconnectFromServer()
                return InstanceClaim(primary=False)
            QLocalServer.removeServer(path)
            if not server.listen(path):
                return InstanceClaim(primary=True, problem=server.errorString())

    def answer() -> None:
        while server.hasPendingConnections():
            connection = server.nextPendingConnection()
            connection.disconnected.connect(connection.deleteLater)
            connection.disconnectFromServer()
        on_activated()

    server.newConnection.connect(answer)
    return InstanceClaim(primary=True, server=server)


def _bring_to_front(window: MainWindow) -> None:
    """Show the running copy's window to a user who just tried to open another.

    Under Wayland a client may not take focus unasked, so whether the window
    actually comes forward is the compositor's decision — not yet checked on
    KWin. Either way the user gets the running copy, never a second one.
    """
    if window.isMinimized():
        window.showNormal()
    window.raise_()
    window.activateWindow()


def main(argv: list[str] | None = None) -> int:
    """Configure logging, then open the window — unless a copy already runs."""
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

    # Imported here, not at module scope, so `--version` and `--help` — which
    # argparse handles above — need no Qt and therefore no display (INV-14).
    from PySide6.QtWidgets import QApplication

    # Qt permits one QApplication per process, and a test session already has
    # one, so reuse it rather than raising. Checked by type, because
    # `instance()` is typed as the `QCoreApplication` base (LWSM-1066).
    existing = QApplication.instance()
    app = existing if isinstance(existing, QApplication) else QApplication([])

    # Before logging is configured, so a second copy never opens `app.log` at
    # all: two `RotatingFileHandler`s on one file can discard a generation of
    # it, which is half of why only one copy runs (LWSM-1065).
    shown: list[MainWindow] = []
    claim = claim_single_instance(
        instance_socket_path(),
        lambda: _bring_to_front(shown[0]) if shown else None,
    )
    if not claim.primary:
        print("Local Web Server Manager is already running; showing its window.")
        return 0

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
    # Imported here, like every other import in `main`, so `--version` and
    # `--help` need no more of the package than argparse (INV-14). `configfile`
    # pulls in no Qt, so this costs nothing either way.
    from lwsm.configfile import quoted

    # `quoted`, because this reaches a terminal (LWSM-1271). The path is
    # derived from the environment, so a newline in it could forge a second
    # line of output, and `quoted` is already the project's answer for a value
    # from outside reaching a human.
    #
    # **Covered by no test, and that is a property of where it sits.** This line
    # is in `main()`, past the `build_window` seam and before the blocking
    # `app.exec()`, so an in-process test cannot reach it — which is DS01 /
    # LWSM-1056, `main()` being a shipped entry point with no test. Asserting it
    # via `quoted` directly would test `quoted`, which is already tested, and
    # would say nothing about this call site. Recorded rather than faked.
    print(
        f"Logging to {quoted(str(log_path))}" if log_path else "Not logging to a file."
    )

    if claim.problem is not None:
        applog.get_logger(__name__).warning(
            "no single-instance guard (%s) — a second copy could start",
            claim.problem,
        )

    _identify(app)
    # No argument: resolving the default path is itself fallible, so it happens
    # inside build_window's RegistryError catch rather than out here (LWSM-1116).
    window, controller = build_window()
    shown.append(window)
    try:
        window.show()
        return app.exec()
    finally:
        # In a `finally`, so an exception out of show() or exec() cannot leave a
        # pool thread outliving its controller — the race INV-16 exists to
        # prevent.
        #
        # Guarded INDIVIDUALLY, because three statements in one `finally` buy
        # one statement's worth of cleanup: a raising `stop()` skipped the
        # other two, and the rescan pool then fell to `~QThreadPool`'s
        # unbounded join — the LWSM-1100/1139 hazard this block exists to
        # prevent, reached by the failure that makes it matter most
        # (LWSM-1211).
        #
        # `Exception`, not `BaseException`: a KeyboardInterrupt here is the
        # user asking a second time, and honouring it is right. Every failure
        # is logged with its traceback, so a step that could not run is never
        # indistinguishable from one that did.
        shutdown_steps = (
            # Stops the timer and waits, bounded, for any outstanding probe.
            ("stop the poll loop", controller.stop),
            # ADR-0003: the servers themselves are LEFT RUNNING, deliberately —
            # this releases our descriptors and threads and signals nothing.
            ("close the supervisor", controller.close_supervisor),
            # The rescan worker is a second pool with the same hazard, so it
            # gets the same bounded wait rather than being left to
            # `~QThreadPool`, which joins with no timeout at all.
            ("wait for the rescan pool", window.shutdown),
            # Closing removes the socket file, so the next launch finds no
            # leftover and needs no stale-socket recovery.
            ("release the single-instance socket", _release(claim)),
        )
        for description, step in shutdown_steps:
            try:
                step()
            except Exception:
                applog.get_logger(__name__).exception(
                    "could not %s while shutting down", description
                )


def _release(claim: InstanceClaim) -> Callable[[], None]:
    """The shutdown step closing the instance socket, or a no-op without one."""
    server = claim.server
    return server.close if server is not None else lambda: None


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

    try:
        code = main()
    except SystemExit as exc:
        # argparse ends `--version`, `--help` and a mistyped option this way.
        # Not a crash, so no traceback (L6-M1); the bound still applies.
        status = exc.code
        exit_without_waiting_for_abandoned_probes(
            status if isinstance(status, int) else int(status is not None)
        )
        raise
    except BaseException:
        # The bound applies to an exception too (known-issue-008, LWSM-1323):
        # without it, `main()`'s own `finally` had already abandoned the pool,
        # and the propagating exception reached interpreter shutdown and waited
        # there — measured at 30 s. Logged first, because a bounded exit ends
        # the process before the interpreter would print it; with nothing
        # abandoned the bound returns and the exception propagates as usual.
        applog.get_logger(__name__).exception("the app ended on an exception")
        exit_without_waiting_for_abandoned_probes(1)
        raise
    exit_without_waiting_for_abandoned_probes(code)
    return code


if __name__ == "__main__":
    raise SystemExit(run())
