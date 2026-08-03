"""Application log: the manager's own diary, distinct from the per-project
server logs (ADR-0003). Contract: `docs/design.md § Observability`."""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER_NAME = "lwsm"
MAX_BYTES = 1024 * 1024
BACKUP_COUNT = 5
_LINE_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


class _NoFollowRotatingFileHandler(RotatingFileHandler):
    """`RotatingFileHandler` that refuses to write through a symlink.

    The stock handler opens the path with `open()`, so a symlink planted at
    `app.log` by another local process redirects the whole log — attacker-
    chosen content appended into any file this user owns. Verified 2026-08-03
    before this class existed. `O_NOFOLLOW` makes that an `OSError` instead.
    """

    def _open(self):
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW
        fd = os.open(self.baseFilename, flags, 0o600)
        return open(fd, self.mode, encoding=self.encoding, errors=self.errors)


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
    # mkdir's mode does not apply to an existing directory, hence the chmod.
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
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
        if Path(existing.baseFilename) == target:
            existing.setLevel(level)
            return log_path
        # Reconfigured to a different directory: drop the old handler rather
        # than accumulating one per call, which would fan every record out to
        # every previous location and make the returned path only half true.
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
