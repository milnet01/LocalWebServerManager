"""Application log: the manager's own diary, distinct from the per-project
server logs (ADR-0003). Contract: `docs/design.md § Observability`."""

from __future__ import annotations

import errno
import logging
import os
import stat
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER_NAME = "lwsm"
MAX_BYTES = 1024 * 1024
BACKUP_COUNT = 5
_LINE_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def _require_private_regular_file(fd: int, path: str) -> None:
    """Raise unless `fd` is a regular file, singly linked, owned by us."""
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode):
        raise OSError(errno.EINVAL, "log path is not a regular file", path)
    if info.st_nlink != 1:
        raise OSError(errno.EMLINK, "log path has another hard link", path)
    if info.st_uid != os.geteuid():
        raise OSError(errno.EPERM, "log path is owned by another user", path)


class _NoFollowRotatingFileHandler(RotatingFileHandler):
    """`RotatingFileHandler` that writes only to a private regular file.

    The stock handler opens the path with `open()`, so a symlink planted at
    `app.log` by another local process redirects the whole log — attacker-
    chosen content appended into any file this user owns. Verified 2026-08-03
    before this class existed. `O_NOFOLLOW` makes that an `OSError` instead.

    `O_NOFOLLOW` closed only part of it. Both gaps below were reproduced
    2026-08-06 against the previous version of this class:

    - a **hard link** is not a symlink, so a link from `app.log` to a file we
      own still received every record — the guarantee stated above was false;
    - `O_NOFOLLOW` does not reject a **FIFO**, and `O_WRONLY` on one blocks
      until a reader appears, so startup hung indefinitely with no error, no
      timeout and no log line.

    So the fd is interrogated rather than trusted. `O_NONBLOCK` is what makes
    that possible at all — without it the FIFO case never reaches the check —
    and it is dropped again once the check passes, because a regular file must
    write blocking or a record can be short-written.
    """

    def _open(self):
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK
        fd = os.open(self.baseFilename, flags, 0o600)
        try:
            _require_private_regular_file(fd, self.baseFilename)
            os.set_blocking(fd, True)
        except BaseException:
            os.close(fd)
            raise
        # `open()` owns the fd from here, including if it raises — so this is
        # outside the try, or a failure there would close the fd twice.
        return open(fd, self.mode, encoding=self.encoding, errors=self.errors)


def _prepare_state_dir(directory: Path) -> None:
    """Create `directory` and every missing component of it as 0700.

    `mkdir(parents=True, mode=0o700)` applies the mode to the LEAF only, so
    every intermediate it created landed at the umask default — measured 0o755
    on 2026-08-06, while the comment at the call site claimed 0700 throughout.
    Creating each component explicitly is what makes that claim true.

    A **symlinked** state directory is supported on purpose, not overlooked: a
    symlinked `~/.local/state` is ordinary with dotfile managers, and
    `test_idempotent_through_a_symlinked_state_dir` pins it. The 2026-08-06
    review proposed refusing one, on the grounds that `O_NOFOLLOW` on the log
    file covers only the final component. That was calibrated down: planting a
    symlink here needs write access to the user's own `~/.local/state`, which
    already implies enough access to edit their shell startup files, so it is
    not an escalation — whereas refusing it breaks a documented configuration.
    The file itself is still guarded, by the handler above.

    `O_DIRECTORY` is deliberate though, and does not conflict with that: it
    rejects a plain file (or a symlink to one) sitting where the state directory
    should be, which is never legitimate, and gives `fchmod` a target that
    cannot change under it between the check and the call.
    """
    missing = []
    probe = directory
    while not probe.exists():
        missing.append(probe)
        if probe.parent == probe:
            break
        probe = probe.parent
    for path in reversed(missing):
        path.mkdir(mode=0o700)

    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        # semgrep's insecure-file-permissions rule calls 0o700 "widely
        # permissive" and suggests 0o644, which is world-READABLE and the
        # opposite of what this directory needs; 0o700 is owner-only, and on a
        # directory the x bit is what makes it traversable at all. Verified
        # false positive — docs/audit-allowlist.md allowlist-005.
        os.fchmod(fd, 0o700)  # nosemgrep
    finally:
        os.close(fd)


def _handler_stream_is_current(handler: RotatingFileHandler, target: Path) -> bool:
    """True when `handler`'s open fd is still the file living at `target`.

    An external delete or replace — logrotate, `systemd-tmpfiles`, or a user
    tidying `~/.local/state` — leaves the handler holding an unlinked inode, and
    every later record goes somewhere no name can reach. Comparing inodes is
    what `logging.handlers.WatchedFileHandler` does, for this exact reason.
    """
    stream = getattr(handler, "stream", None)
    if stream is None or stream.closed:
        return False
    try:
        open_file = os.fstat(stream.fileno())
        on_disk = os.stat(target)
    except OSError:
        return False
    return (open_file.st_dev, open_file.st_ino) == (on_disk.st_dev, on_disk.st_ino)


def configure_stderr_logging(level: int = logging.INFO) -> None:
    """Attach a stderr handler in place of the file one.

    For the entry point to call when `configure_logging` raises: a diagnostic
    log that cannot be written is a reason to warn, not to refuse to start. The
    hardening above deliberately turns several hostile filesystem states into an
    `OSError`, so without this it would have converted a log-integrity attack
    into a total-outage one.
    """
    logger = get_logger()
    logger.setLevel(level)
    logger.propagate = False
    for existing in list(logger.handlers):
        logger.removeHandler(existing)
        existing.close()
    handler = logging.StreamHandler()
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(_LINE_FORMAT))
    logger.addHandler(handler)


def default_state_dir() -> Path:
    """`$XDG_STATE_HOME/localwebservermanager`, else `~/.local/state/...`."""
    xdg = os.environ.get("XDG_STATE_HOME")
    # The XDG spec requires a relative path to be ignored, not resolved against
    # the cwd — honouring one would put the log somewhere different per launch.
    base = (
        Path(xdg)
        if xdg and Path(xdg).is_absolute()
        else Path.home() / ".local" / "state"
    )
    return base / "localwebservermanager"


def get_logger(name: str | None = None) -> logging.Logger:
    """The application logger, or a named child of it."""
    if name is None or name == LOGGER_NAME:
        return logging.getLogger(LOGGER_NAME)
    # Callers pass `__name__`, which inside this package is ALREADY dotted and
    # already carries the `lwsm.` prefix — prefixing again yields
    # `lwsm.lwsm.scanner`, which still logs (the ancestor exists) but names
    # every module wrongly and makes `getLogger("lwsm.scanner").setLevel(...)`
    # target a logger nothing writes to.
    if name.startswith(f"{LOGGER_NAME}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{LOGGER_NAME}.{name}")


def configure_logging(
    state_dir: Path | None = None,
    level: int = logging.INFO,
) -> Path:
    """Attach the rotating file handler; return the path being written to.

    `state_dir` is injected rather than derived so tests never touch the real
    one (testing.md § T1).
    """
    directory = state_dir if state_dir is not None else default_state_dir()
    # 0700/0600 rather than the umask default: this log records every spawn,
    # signal, port probe and config write, i.e. the user's whole project
    # inventory and directory layout. `.gitignore` treats that as private, so
    # writing it world-readable would contradict the project's own posture.
    _prepare_state_dir(directory)
    log_path = directory / "app.log"

    logger = get_logger()
    logger.setLevel(level)
    # Root already has handlers under pytest and Qt; propagating would write
    # every record twice.
    logger.propagate = False

    # `FileHandler.baseFilename` is `os.path.abspath`, which does NOT resolve
    # symlinks — comparing it against `Path.resolve()` makes the two unequal
    # whenever any component is a symlink (a symlinked ~/.local/state is common
    # with dotfile managers), so the guard misses and every line is written
    # twice. Normalise both sides the same way.
    target = Path(os.path.abspath(log_path))

    for existing in list(logger.handlers):
        if not isinstance(existing, RotatingFileHandler):
            continue
        if Path(existing.baseFilename) == target and _handler_stream_is_current(
            existing, target
        ):
            existing.setLevel(level)
            return log_path
        # Two cases land here, and both mean the handler has to go. Reconfigured
        # to a different directory: keeping it would fan every record out to
        # every previous location and make the returned path only half true.
        # Same path but a different inode: the file was deleted or replaced
        # underneath us, so keeping it would append into an unlinked inode
        # forever, silently (reproduced 2026-08-06).
        logger.removeHandler(existing)
        existing.close()

    handler = _NoFollowRotatingFileHandler(
        target,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(_LINE_FORMAT))
    logger.addHandler(handler)
    return log_path
