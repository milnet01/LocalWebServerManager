"""Reading and writing this application's JSON config files, safely.

Core module — may import QtCore, never QtWidgets (`docs/standards/coding.md
§ O1`). No Qt at all in practice, like `ports.py` and `scanner.py`.

**Extracted from `registry.py` by LWSM-1031, which needed a second config
file.** Every function below was written for `projects.json` and each one
records a defect it was written *after* — a FIFO that made the read block
forever with no window and no log line, a symlink destroyed by `os.replace`, a
`mkdir(parents=True, mode=0o700)` that left every parent at the umask default,
a 600 MB file that peaked at 1214 MB RSS. `settings.json` is hand-editable and
therefore attacker-editable in exactly the same way, and lives in the same
directory. Writing a second, weaker copy of this for it is the failure
`docs/standards/coding.md § 1.3` names; there is one copy and both files use
it.

The error type is the base of `registry.RegistryError` rather than that class
itself, so a caller may still catch the narrow one. `registry.save_projects`
converts, which is what keeps `RegistryError` the type its own contract and
tests promise.
"""

from __future__ import annotations

import errno
import os
import stat
import tempfile
from pathlib import Path


class ConfigFileError(Exception):
    """A config file could not be read or written, and nothing was returned."""


# A cap on the file, not on hope. Reproduced before this existed: a 600 MB
# projects.json peaked at 1214 MB RSS. A thousand projects is roughly 200 KB, so
# 1 MiB is generous for anything a person would hand-write.
MAX_FILE_BYTES = 1 << 20

# A rejection reason reaches both the app log and the status bar, and the name
# in it is hand-edited text. Long enough to identify a project, short enough
# that a hostile file cannot flood either.
MAX_REASON_CHARS = 120


def quoted(value: object) -> str:
    """Escape and clip a hand-edited value before it reaches a log or the UI.

    The file is attacker-editable, and a rejection reason travels to both
    `log.warning` and the status bar. `repr` is what makes that safe (LWSM-1078):
    it escapes a newline, so a name cannot forge what looks like a second log
    record, and the clip bounds it — a 50 MB name produced a 50 MB status string.

    **Escape first, then clip.** Clipping the input instead bounded the wrong
    string: `repr` expands a non-printable astral character to a 10-character
    `\\U000e0001` sequence, so 400 of them returned 1203 characters against a
    constant of 120, and a reason interpolates two such values (LWSM-1111).
    Truncating an escaped string can leave an unterminated quote, which is
    cosmetic; it cannot reintroduce a raw newline, which is the property that
    matters.

    Takes `object`, not `str`, because the port fields carry whatever JSON
    held and they need the same bound (LWSM-1102).
    """
    escaped = repr(value)
    if len(escaped) <= MAX_REASON_CHARS:
        return escaped
    return f"{escaped[:MAX_REASON_CHARS]}…"


def read_bounded(path: Path) -> bytes:
    """Read `path`, refusing anything that is not a regular file of sane size.

    `applog.py` already solved this class for `app.log`; `registry.py` did not
    get it. Two failures this closes, both reproduced:

    - A **FIFO** at the config path made `Path.read_bytes()` block forever — no
      window, no error, no log line. `O_NONBLOCK` makes the open return, and the
      `fstat` then refuses it.
    - An oversized file was read whole into memory.

    Deliberately weaker than `applog._require_private_regular_file`, and not a
    call to it: that one also demands a single link and our own ownership, which
    is right for a log we write and wrong for a config file the user may
    reasonably hard-link or have installed for them.
    """
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    try:
        # Interrogated on the raw descriptor, before anything wraps it.
        # `os.fdopen` on a directory raises `IsADirectoryError` *before* its
        # `with` block is entered, so wrapping first left nothing owning the
        # descriptor and nothing closing it: 50 calls leaked 50 (LWSM-1104).
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise OSError(errno.EINVAL, "not a regular file", str(path))
        if info.st_size > MAX_FILE_BYTES:
            raise OSError(
                errno.EFBIG,
                f"too large: {info.st_size} bytes, limit {MAX_FILE_BYTES}",
                str(path),
            )
        handle = os.fdopen(fd, "rb")
    except BaseException:
        # Nothing else owns the descriptor yet, on any path out of here.
        os.close(fd)
        raise

    with handle:
        # One byte past the cap, so a file that grew between the fstat and the
        # read is still refused rather than read whole.
        raw = handle.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise OSError(errno.EFBIG, f"too large: over {MAX_FILE_BYTES} bytes", str(path))
    return raw


def prepare_config_dir(directory: Path) -> None:
    """Create `directory` and every missing component of it at mode 0700.

    Each component explicitly, because `mkdir(parents=True, mode=0o700)` applies
    the mode to the **leaf only** and leaves everything it created at the umask
    default — the defect `applog._prepare_state_dir` records having measured at
    0o755. Unlike that function this one does **not** re-chmod a directory that
    already exists: § 4.3 step 0 says create it if absent, and silently
    tightening a directory the user already made is a change nobody asked for.
    """
    missing: list[Path] = []
    probe = directory
    while not probe.exists():
        missing.append(probe)
        if probe.parent == probe:
            break
        probe = probe.parent
    for path in reversed(missing):
        path.mkdir(mode=0o700)


def refuse_existing_target(path: Path) -> None:
    """Refuse to replace a symlink or a non-regular file.

    **`os.lstat`, never `os.stat` or `Path.is_file()`** — both follow the link,
    so a symlink pointing at a regular file reports `S_ISREG` true, passes, and
    is then destroyed by `os.replace`, which replaces the *symlink* rather than
    its target. Measured on Python 3.13: the real file was left untouched and
    the user's deliberate indirection became a plain file.

    **The `lstat`-then-`replace` race is accepted and not closed.** Both
    `read_bounded` and `applog._require_private_regular_file` interrogate a
    *descriptor*; this interrogates a *path*, and `os.replace` takes paths, so
    there is no descriptor to hold across the swap. The only real fix is a
    directory fd plus `renameat`, which buys nothing against an attacker who can
    already write to a 0700 directory owned by the user. Do **not** add a retry
    loop — there is no state to re-check into.

    Deliberately narrower than `applog._require_private_regular_file`, for the
    reason `read_bounded` already records: a config file may reasonably be
    hard-linked or installed for the user. A symlink is refused because
    replacing one destroys it; a hard link is not, because replacing the path
    leaves the other name intact.
    """
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise ConfigFileError(
            f"{quoted(str(path))}: cannot be examined ({exc.strerror or exc})"
        ) from exc
    if stat.S_ISLNK(info.st_mode):
        raise ConfigFileError(
            f"{quoted(str(path))}: is a symlink; refusing to replace it"
        )
    if not stat.S_ISREG(info.st_mode):
        raise ConfigFileError(
            f"{quoted(str(path))}: is not a regular file; refusing to replace it"
        )


def write_json_atomically(path: Path, data: bytes, *, prefix: str) -> None:
    """Create the directory, refuse a hostile target, and write `data` durably.

    The order is the one that survives a failure at any step, and it is the
    order `save_projects` has always used — this function IS that tail, moved
    so a second config file cannot grow a second, subtly different copy of it.

    `data` is bytes rather than an object to serialise: the caller has to bound
    the encoded length against its own cap *before* anything is created, and it
    cannot do that if the encoding happens in here.
    """
    directory = path.parent
    try:
        prepare_config_dir(directory)
    except OSError as exc:
        raise ConfigFileError(
            f"{quoted(str(directory))}: cannot be created ({exc.strerror or exc})"
        ) from exc

    refuse_existing_target(path)

    # mkstemp creates at 0600 and in the target's own directory, so the rename
    # cannot cross a filesystem. `Path.write_text` would create at
    # `0666 & ~umask`, which is how this file gets a mode nobody chose.
    try:
        handle_fd, temporary_name = tempfile.mkstemp(
            dir=directory, prefix=prefix, suffix=".tmp"
        )
    except OSError as exc:
        # The last syscall in this writer that was outside a handler
        # (LWSM-1135). ENOSPC, EDQUOT, EROFS and EACCES all land here, and this
        # function's docstring, LWSM-1007 § 4.3 step 5 and § 6's *disk is full*
        # row all promise a `ConfigFileError`. Nothing has been created yet, so
        # there is no temporary to unlink and the previous file is untouched.
        raise ConfigFileError(
            f"{quoted(str(path))}: could not be written ({exc.strerror or exc})"
        ) from exc
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle_fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException as exc:
        # Everything up to and including the replace: the previous file is
        # untouched and the temporary is ours to remove (INV-2).
        try:
            temporary.unlink()
        except OSError:
            pass
        if isinstance(exc, OSError):
            raise ConfigFileError(
                f"{quoted(str(path))}: could not be written ({exc.strerror or exc})"
            ) from exc
        raise

    # Step 4, and deliberately outside the block above: the new file is already
    # in place, there is no temporary left to unlink, and rolling back would mean
    # having kept a copy of the old one — which is LWSM-1039. A failure here is
    # REPORTED and not reversed, or § 6 would tell the user a durable write
    # failed.
    try:
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError as exc:
        raise ConfigFileError(
            f"{quoted(str(path))}: written, but the directory entry could not be "
            f"made durable ({exc.strerror or exc})"
        ) from exc
