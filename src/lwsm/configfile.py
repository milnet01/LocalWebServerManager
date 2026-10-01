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
import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path


class ConfigFileError(Exception):
    """A config file could not be read or written, and nothing was returned."""


# A cap on the file, not on hope. Reproduced before this existed: a 600 MB
# projects.json peaked at 1214 MB RSS. A real record is about 450 bytes
# (measured 2026-09-28 on a live registry), so a thousand projects is about
# 450 KB and 1 MiB is generous. It bounds MEMORY, not how many records a file
# holds: a minimal record is 27 bytes, so about 38,000 fit under it — which is
# why `registry.MAX_RECORDS` exists (known-issue-002).
MAX_FILE_BYTES = 1 << 20

# A rejection reason reaches both the app log and the message banner, and the name
# in it is hand-edited text. Long enough to identify a project, short enough
# that a hostile file cannot flood either.
MAX_REASON_CHARS = 120


class BoundedReasons:
    """A list of reasons held to `cap`, counting what it drops.

    `MAX_REASON_CHARS` bounds how long each reason is; this bounds how many.
    `close()` adds `tail`, formatted with `count`, whenever anything was
    dropped, and only then: a cap with no tail reads exactly like
    completeness, and nothing downstream could tell a file with 100 problems
    from one with half a million. Written four times by hand before
    LWSM-1361 (scanner, registry load, merge, import), with three tails.

    `reasons` is the live list, for a caller that reads what it has so far.
    """

    def __init__(self, cap: int, tail: str) -> None:
        self.reasons: list[str] = []
        self._cap = cap
        self._tail = tail
        self._dropped = 0

    def note(self, reason: str) -> None:
        if len(self.reasons) < self._cap:
            self.reasons.append(reason)
        else:
            self._dropped += 1

    def close(self) -> list[str]:
        """The reasons, with the tail when anything was dropped."""
        if self._dropped:
            self.reasons.append(self._tail.format(count=self._dropped))
            self._dropped = 0
        return self.reasons


# A separate constant because it bounds a *display* string under a different
# sanitiser: a name reaches the UI as a row label or a picker entry, so
# `repr`'s escaping would put something on screen literally named
# `'my project'`, quotes included.
MAX_DISPLAY_NAME_CHARS = 120

# C0, DEL and C1, lone surrogates, and U+2028/U+2029 — the two Unicode line
# separators, which forge a second line exactly as a newline does.
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\ud800-\udfff\u2028\u2029]")


def display_text(text: str) -> str:
    """A name or a source, safe to put in a log record and on a widget.

    Sanitised and not escaped: it is a *display* string, so `repr` would render
    a row's provenance as `'lib/launcher.py'`, quotes included. A filename may
    still contain a newline, which is the forged-log-record defect LWSM-1078
    closed — so every C0 and C1 control character becomes U+FFFD, and the
    result is clipped, with an ellipsis so a cut name reads as cut. U+FFFD
    rather than a space or a deletion, so the user can see something was there.
    Format characters stay: emoji sequences and right-to-left names need them.

    **Lives here rather than in `scanner.py`, where it was written.** LWSM-1249
    needed the identical treatment for a `.desktop` file's `Name`, which is
    untrusted in exactly the same way and reaches a combo item, a tooltip and
    an accessible name. A second, weaker copy of a sanitiser written after a
    measured defect is what `coding.md § 1.3` forbids, and it is the reason
    this module exists at all — see the module docstring on LWSM-1031. It is
    also why `controller.displayable_name`, a second copy with a different
    replacement and no surrogate handling, was folded in here (LWSM-1341).
    """
    cleaned = _CONTROL.sub("\ufffd", text)
    if len(cleaned) <= MAX_DISPLAY_NAME_CHARS:
        return cleaned
    return cleaned[: MAX_DISPLAY_NAME_CHARS - 1] + "\u2026"


def quoted(value: object) -> str:
    """Escape and clip a hand-edited value before it reaches a log or the UI.

    The file is attacker-editable, and a rejection reason travels to both
    `log.warning` and the message banner. `repr` is what makes that safe (LWSM-1078):
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


def canonical_json(value: object) -> str:
    """`value` as the canonical text a config file carries opaquely.

    Raises `ValueError` for a value `json.loads` accepted that this project's
    writers then refuse, so the loader can refuse the FIELD rather than every
    later save failing on it (review-code 2026-10-01 L5-M1, L5-M2): a
    non-finite float, which `1e999` decodes to, and a string holding an
    unpaired surrogate, which a `\\ud800` escape decodes to. The writers emit
    `ensure_ascii=False` UTF-8 with `allow_nan=False`, and both of those raise
    on exactly these. `UnicodeEncodeError` is a `ValueError`.
    """
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    json.dumps(value, ensure_ascii=False).encode("utf-8")
    return text


def is_writable_text(text: str) -> bool:
    """Whether `text` survives the writers' UTF-8 encode — no unpaired surrogate."""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


class ConfigFileNotDurable(ConfigFileError):
    """The file WAS replaced; only the directory fsync failed (known-issue-047).

    A subclass, so every `except ConfigFileError` still catches it, and a caller
    that must not report a written file as unwritten can tell the two apart.
    """


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


class JsonFileRefused(ConfigFileError):
    """A config file that exists and cannot be used as a JSON object.

    `stage` names where it failed, so each reader keeps its own wording for
    its own users: `unreadable`, `not_utf8`, `not_json`, `unparseable` or
    `not_object`. `cause` is the exception behind it, and `found` the type
    name of a document that is not an object.
    """

    def __init__(
        self, path: Path, stage: str, cause: BaseException | None, found: str = ""
    ) -> None:
        super().__init__(f"{quoted(str(path))}: {stage}")
        self.stage = stage
        self.cause = cause
        self.found = found


@dataclass(frozen=True)
class JsonObject:
    """A loaded config document and any keys it repeated (last one kept)."""

    data: dict[str, object]
    duplicate_keys: tuple[str, ...]


def _refuse_constant(name: str) -> object:
    """`json.loads`' hook for `NaN`, `Infinity` and `-Infinity`.

    Python accepts them and re-emits them bare, which is not JSON: another
    tool reading the file refuses it (known-issue-056, LWSM-1322).
    """
    raise ValueError(f"{name} is not a JSON value")


def load_json_object(path: Path) -> JsonObject:
    """Read `path` as a JSON object, the one sequence every config file takes.

    `registry.load_projects`, `settings.load` and `TrustStore._load` each
    wrote this by hand, and their guards drifted: only the registry noted
    duplicate keys, and the trust store took `NaN` (LWSM-1357). Each guard
    below has a measured cause recorded at `registry.load_projects`.

    A missing file raises `FileNotFoundError` untouched, because to every
    caller that is first run rather than a broken file. Every other failure
    raises `JsonFileRefused`.
    """
    try:
        raw = read_bounded(path)
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise JsonFileRefused(path, "unreadable", exc) from exc

    repeated: list[str] = []

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        # `json`'s own rule, last wins, with the loss remembered.
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                repeated.append(key)
            result[key] = value
        return result

    try:
        # utf-8-sig: an editor-added BOM is invisible in that editor.
        data = json.loads(
            raw.decode("utf-8-sig"),
            parse_constant=_refuse_constant,
            object_pairs_hook=pairs,
        )
    except UnicodeDecodeError as exc:
        raise JsonFileRefused(path, "not_utf8", exc) from exc
    except json.JSONDecodeError as exc:
        raise JsonFileRefused(path, "not_json", exc) from exc
    except (ValueError, RecursionError) as exc:
        # A NaN, a 4300-digit-plus integer, or nesting deep enough to exhaust
        # the stack. `RecursionError` is not a `ValueError`, so it is named.
        raise JsonFileRefused(path, "unparseable", exc) from exc
    if not isinstance(data, dict):
        raise JsonFileRefused(path, "not_object", None, type(data).__name__)
    return JsonObject(data, tuple(repeated))


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
        # exist_ok: the check above and this create are not atomic, and a
        # directory another process made in between is the one we wanted
        # (known-issue-056, LWSM-1322). A FILE there still raises.
        path.mkdir(mode=0o700, exist_ok=True)


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

    `data` is bytes rather than an object to serialise, so a caller that wants
    a domain-specific message can bound the encoded length itself before
    calling — `registry._encoded` does, and keeps its own wording.

    The cap is enforced HERE as well, and that is the point: it was stated as a
    caller obligation in this docstring and two of the four callers did not
    meet it (LWSM-1236). A file written over the cap cannot be read back by
    `read_bounded`, and a caller that refuses to overwrite a file it cannot
    read then cannot rewrite it either. Enforced where the data is, so a fifth
    caller inherits it.

    The check comes before the directory is created and before any temporary
    exists, so a refusal leaves the previous file and the filesystem untouched
    (INV-2), like every other refusal here.
    """
    if len(data) > MAX_FILE_BYTES:
        raise ConfigFileError(
            f"{quoted(str(path))}: too large to write: {len(data)} bytes, "
            f"limit {MAX_FILE_BYTES}; not written"
        )

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
        raise ConfigFileNotDurable(
            f"{quoted(str(path))}: written, but the directory entry could not be "
            f"made durable ({exc.strerror or exc})"
        ) from exc
