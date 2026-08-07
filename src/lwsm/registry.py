"""The project list, read from a hand-editable JSON file.

Core module — may import QtCore, never QtWidgets (`docs/standards/coding.md
§ O1`). Contract: `docs/specs/LWSM-1005-vertical-slice.md § 4.1`.

The file is hand-editable and therefore attacker-editable (ADR-0007's
reasoning about settings.json, applied here), so every field is type-checked
before use rather than trusted.
"""

from __future__ import annotations

import errno
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import TypeGuard

SCHEMA_VERSION = 1

# A cap on the file, not on hope. Reproduced before this existed: a 600 MB
# projects.json peaked at 1214 MB RSS. A thousand projects is roughly 200 KB, so
# 1 MiB is generous for anything a person would hand-write.
MAX_FILE_BYTES = 1 << 20

# A rejection reason reaches both the app log and the status bar, and the name
# in it is hand-edited text. Long enough to identify a project, short enough
# that a hostile file cannot flood either.
MAX_REASON_CHARS = 120

# The declared port is the "detected" half and may legitimately be 80 or 443;
# ADR-0005's 1024-65535 floor governs the *override*, which the user types.
DECLARED_PORT_RANGE = (1, 65535)
OVERRIDE_PORT_RANGE = (1024, 65535)


class RegistryError(Exception):
    """The file itself is unusable, so nothing is returned from it.

    ADR-0005 forbids partially parsing a file whose version we do not know.
    """


@dataclass(frozen=True)
class ProjectRecord:
    path: Path
    name: str
    port: int | None
    port_override: int | None

    @property
    def effective_port(self) -> int | None:
        """Override first, else declared.

        The top and third rungs of `docs/design.md § The effective port`;
        confirmed_port (rung 2) is LWSM-1038 and the framework default
        (rung 4) is LWSM-1006.
        """
        return self.port_override if self.port_override is not None else self.port


def default_projects_path() -> Path:
    """$XDG_CONFIG_HOME/localwebservermanager/projects.json.

    Falls back to ~/.config when the variable is unset or not absolute — the
    config half of `docs/standards/coding.md § O3`'s XDG rule, whose state half
    is already `applog.py::default_state_dir`.
    """
    raw = os.environ.get("XDG_CONFIG_HOME", "")
    if raw and Path(raw).is_absolute():
        base = Path(raw)
    else:
        try:
            base = Path.home() / ".config"
        except RuntimeError as exc:
            # Path.home() raises when neither HOME nor a passwd entry resolves —
            # rare, but real in a stripped container, and it happened before any
            # window or log existed. RegistryError is what the caller already
            # turns into an empty window with a reason (INV-15).
            raise RegistryError(f"cannot locate a home directory ({exc})") from exc
    return base / "localwebservermanager" / "projects.json"


def _quoted(value: object) -> str:
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


def _is_int(value: object) -> TypeGuard[int]:
    """`type(...) is int`, not isinstance: `isinstance(True, int)` is True, so a
    hand-edited `"port": true` would otherwise be accepted as port 1.

    `TypeGuard[int]` rather than `bool` so a checker can narrow the `object` at
    the call site. A plain `bool` left `_port_or_reason`'s range comparison and
    its return both unresolvable — correct at runtime, because the `or`
    short-circuits, and three reported errors (LWSM-1080).
    """
    return type(value) is int


def _port_or_reason(
    value: object, field: str, low: int, high: int, name: str
) -> tuple[int | None, str | None]:
    if value is None:
        return None, None
    if not _is_int(value) or not low <= value <= high:
        # _quoted, not {value!r}: repr escapes but does not clip, and a 200 KB
        # string in `port` produced a 200,038-character reason (LWSM-1102).
        return None, f"{name}: {field} {_quoted(value)} is not an integer {low}-{high}"
    return value, None


def _read_bounded(path: Path) -> bytes:
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


def load_projects(path: Path) -> tuple[list[ProjectRecord], list[str]]:
    """Return (records, rejection reasons).

    Raises RegistryError only when the file itself is unusable — the four
    shapes in the spec's § 4.1. A single bad record never blanks the list.
    """
    try:
        raw = _read_bounded(path)
    except OSError as exc:
        # Any OSError, not just FileNotFoundError: a directory at that path, a
        # permission denial, a FIFO or an oversized file must all arrive as
        # RegistryError, because that is the only exception `build_window`
        # tolerates. `exc.strerror` rather than `exc` keeps the reason readable.
        raise RegistryError(f"{path}: cannot be read ({exc.strerror or exc})") from exc

    try:
        # utf-8-sig, not utf-8: an editor-added BOM is invisible in that
        # editor and would otherwise refuse the whole file with a reason
        # naming byte 0, which sends the user looking at the wrong thing.
        data = json.loads(raw.decode("utf-8-sig"))
    except UnicodeDecodeError as exc:
        # Not a JSONDecodeError, so it has to be caught by name.
        raise RegistryError(f"{path}: not valid UTF-8 ({exc})") from exc
    except json.JSONDecodeError as exc:
        raise RegistryError(f"{path}: not valid JSON ({exc})") from exc
    except (ValueError, RecursionError) as exc:
        # Both reproduced, and neither is a JSONDecodeError, so both escaped as
        # themselves past a caller that tolerates only RegistryError — the app
        # died with a traceback and no window. A 5000-digit `port` hits CPython's
        # 4300-digit integer-parse cap and raises plain ValueError; deeply nested
        # arrays exhaust the stack and raise RecursionError, which is not a
        # ValueError — it is RecursionError -> RuntimeError -> Exception, so it
        # needs naming here whatever `except ValueError` would catch. This
        # comment used to say RecursionError "is not even an Exception", which
        # is false, and dangerously so: a reader who believed it would widen
        # ports.py's `except Exception` to BaseException and start swallowing
        # KeyboardInterrupt (LWSM-1108). JSONDecodeError is matched above
        # because it subclasses ValueError and its message is more useful.
        raise RegistryError(
            f"{path}: cannot be parsed ({type(exc).__name__}: {exc})"
        ) from exc

    # json.loads happily returns a list or a string; nothing raises for these.
    if not isinstance(data, dict):
        raise RegistryError(
            f"{path}: top level is {type(data).__name__}, not an object"
        )

    version = data.get("schema_version")
    if not _is_int(version) or version != SCHEMA_VERSION:
        # _quoted, not {version!r}, for the reason `_port_or_reason` records —
        # and this was the last call site still carrying the defect after
        # LWSM-1078 fixed name/path and LWSM-1102 fixed the port fields. It is
        # the worst of the three: this string is raised, so it reaches both the
        # log and the status bar with no per-reason bound anywhere in its path
        # (LWSM-1114).
        raise RegistryError(
            f"{path}: schema_version {_quoted(version)} is not {SCHEMA_VERSION}; "
            "refusing to guess at its contents"
        )

    projects = data.get("projects")
    if not isinstance(projects, list):
        raise RegistryError(
            f"{path}: 'projects' is {type(projects).__name__}, not a list"
        )

    records: list[ProjectRecord] = []
    reasons: list[str] = []
    seen: set[Path] = set()

    for index, entry in enumerate(projects):
        if not isinstance(entry, dict):
            reasons.append(f"projects[{index}]: not an object, skipped")
            continue

        raw_name = entry.get("name")
        if not isinstance(raw_name, str) or not raw_name:
            reasons.append(f"projects[{index}]: 'name' must be a non-empty string")
            continue

        name = _quoted(raw_name)

        raw_path = entry.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            reasons.append(f"{name}: 'path' must be a non-empty string")
            continue
        if "\x00" in raw_path:
            # It passes is_absolute() and would load, but every later os call on
            # it raises ValueError — and P03 passes this path as a spawn cwd.
            reasons.append(f"{name}: path {_quoted(raw_path)} contains a NUL byte")
            continue

        project_path = Path(raw_path)
        if not project_path.is_absolute():
            reasons.append(f"{name}: path {_quoted(raw_path)} is not absolute")
            continue
        if project_path.parts[:1] == ("//",):
            # POSIX gives EXACTLY two leading slashes an implementation-defined
            # meaning, and PurePosixPath keeps them as a distinct root, while
            # realpath resolves '//srv/a' and '/srv/a' to the same directory —
            # so both loaded, two records under one identity. Three or more
            # slashes collapse; two do not. Refused rather than normalised, for
            # the same reason as '..' below.
            reasons.append(f"{name}: path {_quoted(raw_path)} must not begin with '//'")
            continue
        if ".." in project_path.parts:
            # PurePath keeps '..', so /srv/a and /srv/c/../a are unequal and both
            # would load — two records with one identity, which § 6 calls a
            # malformed file. Refused rather than normalised: collapsing '..'
            # lexically is wrong when a component is a symlink, and this path
            # becomes a spawn cwd in P03.
            reasons.append(f"{name}: path {_quoted(raw_path)} must not contain '..'")
            continue
        if project_path in seen:
            # ADR-0005 makes the absolute path the identity, so two records
            # sharing one is a malformed file, not a merge question.
            reasons.append(f"{name}: path {_quoted(raw_path)} is already registered")
            continue
        seen.add(project_path)

        # A bad port loses the field, not the row: the project still exists and
        # the user still needs to see it.
        port, reason = _port_or_reason(
            entry.get("port"), "port", *DECLARED_PORT_RANGE, name
        )
        if reason:
            reasons.append(reason)
        override, reason = _port_or_reason(
            entry.get("port_override"), "port_override", *OVERRIDE_PORT_RANGE, name
        )
        if reason:
            reasons.append(reason)

        records.append(
            ProjectRecord(
                path=project_path, name=raw_name, port=port, port_override=override
            )
        )

    return records, reasons
