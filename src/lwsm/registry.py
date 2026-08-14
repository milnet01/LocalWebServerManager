"""The project list, read from a hand-editable JSON file.

Core module — may import QtCore, never QtWidgets (`docs/standards/coding.md
§ O1`). Contract: `docs/specs/LWSM-1005-vertical-slice.md § 4.1`.

The file is hand-editable and therefore attacker-editable (ADR-0007's
reasoning about settings.json, applied here), so every field is type-checked
before use rather than trusted.
"""

from __future__ import annotations

import enum
import errno
import json
import os
import stat
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
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

# `MAX_REASON_CHARS` bounds how LONG each reason is; this bounds how MANY there
# are, which nothing did until LWSM-1115. The cheapest malformed element is two
# bytes, so a file at `MAX_FILE_BYTES` measured **524,271** reasons totalling
# **20,859,730** characters on 2026-08-07 — which `build_window` then wrote as
# one `log.warning` each: 28.7 MB through a handler that rotates at 1 MiB
# keeping 5, i.e. the whole history the user is told to consult, and 8.7 s of it
# before `window.show()` with no window on screen to interrupt.
#
# 100 is chosen against a legitimate file, not against the attack: a thousand
# projects is roughly 200 KB, and a user who has broken a hundred of them has
# a systematic problem the hundred-and-first line will not clarify. The
# suppressed count is always reported (see `load_projects`), on the rule
# `controller._flush_repeated_error` already follows — silence and suppression
# must never be indistinguishable.
MAX_REASONS = 100

# The declared port is the "detected" half and may legitimately be 80 or 443;
# ADR-0005's 1024-65535 floor governs the *override*, which the user types.
DECLARED_PORT_RANGE = (1, 65535)
OVERRIDE_PORT_RANGE = (1024, 65535)


class LauncherKind(enum.Enum):
    """How a project is started. Serialised as the `value`, never the name.

    **Lives here rather than in `scanner.py`, and the reason is runtime
    validation rather than the annotation** (LWSM-1007 § 4.1). This module
    carries `from __future__ import annotations`, so `kind: LauncherKind | None`
    is never evaluated and a `TYPE_CHECKING`-only import would satisfy typing
    alone — but the loader has to *check* a value against the enum, which needs
    the class at run time. `scanner.py` already imports `DECLARED_PORT_RANGE`
    from here, so a runtime `from lwsm.scanner import LauncherKind` in this file
    closes a cycle and **the package stops importing at all**, both entry orders.
    Moving the enum down keeps the existing direction (`scanner` → `registry`)
    instead of adding a second one.
    """

    SYSTEMD = "systemd"
    SHELL = "shell"
    NODE = "node"
    PYTHON = "python"


class RegistryError(Exception):
    """The file itself is unusable, so nothing is returned from it.

    ADR-0005 forbids partially parsing a file whose version we do not know.
    """


class RegistryMissing(RegistryError):
    """There is no file — first run.

    A **subclass**, so every existing `except RegistryError` handler keeps its
    behaviour untouched and only the write gate discriminates. Separating it is
    what stops a clean machine, where `projects.json` has never existed, being
    permanently unable to persist anything (LWSM-1007 § 4.3).
    """


@dataclass(frozen=True)
class ProjectRecord:
    path: Path
    name: str
    port: int | None = None
    port_override: int | None = None
    kind: LauncherKind | None = None
    argv: tuple[str, ...] = ()
    unit: str | None = None
    hidden: bool = False
    launcher_override: str | None = None
    notes: str = ""
    start_at_login: bool = False
    actions: tuple[str, ...] = ()
    added: str | None = None

    @property
    def effective_port(self) -> int | None:
        """Override first, else declared.

        The top and third rungs of `docs/design.md § The effective port`;
        confirmed_port (rung 2) is LWSM-1038 and the framework default
        (rung 4) is LWSM-1006.
        """
        return self.port_override if self.port_override is not None else self.port


# The record's two halves, as explicit membership rather than two types:
# `ProjectController` and `ProjectRow` read `path`, `name` and `effective_port`
# today, and splitting the dataclass would rewrite them for no gain
# (`coding.md § 1.3`). INV-1 makes a field belonging to neither a failing build,
# because LWSM-1131's merge would then neither refresh nor preserve it.
#
# `path` is classified *detected* — a scan is what observes it — while being the
# one field no write may resolve. `added` is *user*-owned because ADR-0005 makes
# it the duplicate-port tie-break, and a rescan must not reorder that.
DETECTED_FIELDS: frozenset[str] = frozenset({"path", "port", "kind", "argv", "unit"})
USER_FIELDS: frozenset[str] = frozenset(
    {
        "name",
        "port_override",
        "hidden",
        "launcher_override",
        "notes",
        "start_at_login",
        "actions",
        "added",
    }
)


@dataclass(frozen=True)
class LoadResult:
    """What `load_projects` returns. Replaces the `(records, reasons)` tuple.

    `rows_refused` cannot be derived from `reasons`: a **field** refusal appends
    a reason and keeps the row, a **row** refusal drops the object. The write
    gate keys on the count, because keying it on `reasons` being non-empty would
    let one hand-typed `"port": "3000"` disable persistence for a whole session
    on a file with nothing at risk (LWSM-1007 § 4.3, INV-6).
    """

    records: list[ProjectRecord]
    reasons: list[str]  # every refusal, row-level and field-level alike
    rows_refused: int  # ROW refusals only; `reasons` is not a proxy for it


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


# Every helper below implements one blanket rule (LWSM-1007 § 4.2): a key that
# is present with the wrong type **loses the field and is reported**, exactly as
# `_port_or_reason` already does for a bad port. It is a *field* refusal, so it
# never makes the session read-only — only a **row** refusal does, and the two
# required keys `name` and `path` are the only row refusals.
#
# A dropped field's original text is lost on the next write, and that is accepted
# rather than defended: a refused field's text is by definition not a valid value
# of that field, while a refused row may be entirely valid apart from one typo.


def _string_or_reason(
    value: object, field: str, name: str
) -> tuple[str | None, str | None]:
    """A `str | None` field defaulting to `None` — `unit`, `launcher_override`."""
    if value is None:
        return None, None
    if not isinstance(value, str):
        return None, f"{name}: {field} {_quoted(value)} is not a string"
    return value, None


def _text_or_reason(value: object, field: str, name: str) -> tuple[str, str | None]:
    """A `str` field defaulting to `""` — `notes`."""
    if value is None:
        return "", None
    if not isinstance(value, str):
        return "", f"{name}: {field} {_quoted(value)} is not a string"
    return value, None


def _bool_or_reason(value: object, field: str, name: str) -> tuple[bool, str | None]:
    """`hidden`, `start_at_login`. `type(...) is bool` for `_is_int`'s reason
    inverted: `isinstance(1, bool)` is False, but a bare `1` is not `true` and
    accepting it would make the file's two spellings of the same flag unequal."""
    if value is None:
        return False, None
    if type(value) is not bool:
        return False, f"{name}: {field} {_quoted(value)} is not true or false"
    return value, None


def _kind_or_reason(value: object, name: str) -> tuple[LauncherKind | None, str | None]:
    """`kind` accepts only a `LauncherKind` **value** — never its name."""
    if value is None:
        return None, None
    if not isinstance(value, str):
        return None, f"{name}: kind {_quoted(value)} is not a string"
    try:
        return LauncherKind(value), None
    except ValueError:
        known = ", ".join(sorted(member.value for member in LauncherKind))
        return None, f"{name}: kind {_quoted(value)} is not one of {known}"


def _argv_or_reason(value: object, name: str) -> tuple[tuple[str, ...], str | None]:
    """`argv` loads back as a **tuple**, not a list.

    JSON has only arrays, so a loader returning a `list` produces a record
    unequal to the one written while every value looks right — INV-3's failure
    mode exactly. The tuple form also matches `scanner.DetectedProject.argv`, so
    LWSM-1131's merge compares like with like.
    """
    if value is None:
        return (), None
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return (), f"{name}: argv {_quoted(value)} is not a list of strings"
    return tuple(value), None


def _actions_or_reason(value: object, name: str) -> tuple[tuple[str, ...], str | None]:
    """`actions` is persisted **opaquely**, one canonical-JSON string per element.

    Its per-action schema and `design.md § Custom project actions`' load-time
    validation land with the item that builds the action surface — the only place
    that validation has a failure surface to report to. Neither this item nor
    LWSM-1131 builds it.

    Canonical strings rather than the decoded objects for three reasons. A
    `tuple[dict, ...]` makes `ProjectRecord` **unhashable**: the dataclass is
    `frozen=True`, so its generated `__hash__` raises `TypeError` the moment
    anything hashes a record with actions. A `list` fails INV-3's `==` round-trip
    for the same reason `argv` does. And leaving the type unstated makes an
    implementer pick one of those two. The stated cost is that key order inside
    an action is normalised, though its value is not.
    """
    if value is None:
        return (), None
    if not isinstance(value, list):
        return (), f"{name}: actions {_quoted(value)} is not a list"
    try:
        return tuple(
            json.dumps(element, sort_keys=True, separators=(",", ":"))
            for element in value
        ), None
    except (TypeError, ValueError):
        return (), f"{name}: actions {_quoted(value)} could not be re-serialised"


def _added_or_reason(value: object, name: str) -> tuple[str | None, str | None]:
    """`added` must be an RFC 3339 **instant**, and the tz clause is the whole rule.

    `fromisoformat` is far broader than RFC 3339 and admits two spellings that
    denote no instant — `'2026-08-12'` and `'2026-08-12T14:03:11'` both parse
    with `tzinfo=None`. "Must carry a time" would not catch them, because a
    date-only value parses to midnight and has one. A value with no offset cannot
    be ordered against one that has an offset, and LWSM-1131's INV-7 tie-breaks
    on exactly that ordering.

    The value is kept **verbatim**, not reformatted: this app stamps new values
    as `Z` with second precision, but a hand-edited `+01:00` already in the file
    is written back as it was. "Never rewritten once set" and "written with a Z
    suffix" cannot both hold for a stamp the reader accepts in any spelling.
    """
    if value is None:
        return None, None
    if not isinstance(value, str):
        return None, f"{name}: added {_quoted(value)} is not a string"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None, f"{name}: added {_quoted(value)} is not an RFC 3339 instant"
    if parsed.tzinfo is None:
        return (
            None,
            f"{name}: added {_quoted(value)} has no time-zone offset, "
            "so it denotes no instant",
        )
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


def load_projects(path: Path) -> LoadResult:
    """Return the records, every rejection reason, and the ROW-refusal count.

    Raises RegistryError only when the file itself is unusable — the four
    shapes in the spec's § 4.1. A single bad record never blanks the list.
    An absent file raises `RegistryMissing`, which is the one subclass the
    write gate treats as writable (LWSM-1007 § 4.3).
    """
    try:
        raw = _read_bounded(path)
    except FileNotFoundError as exc:
        # Ahead of the OSError clause below, which would otherwise fold first
        # run into "unreadable" and leave a clean machine permanently unable to
        # persist anything — the write gate would refuse to create the very file
        # whose absence it is reading.
        raise RegistryMissing(f"{path}: does not exist yet") from exc
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
    suppressed = 0
    rows_refused = 0
    seen: set[Path] = set()

    def note(reason: str) -> None:
        """Record a reason, or count it once `MAX_REASONS` are already held."""
        nonlocal suppressed
        if len(reasons) < MAX_REASONS:
            reasons.append(reason)
        else:
            suppressed += 1

    def refuse_row(reason: str) -> None:
        """A reason that also DROPS the object.

        Counted separately from `reasons` because that count, and not the reason
        list, is what the write gate reads (INV-6). The count is incremented even
        once `MAX_REASONS` reasons are held and `note` starts suppressing — a
        refusal the user is not shown is still a refusal the writer must not
        write over.
        """
        nonlocal rows_refused
        rows_refused += 1
        note(reason)

    for index, entry in enumerate(projects):
        if not isinstance(entry, dict):
            refuse_row(f"projects[{index}]: not an object, skipped")
            continue

        raw_name = entry.get("name")
        if not isinstance(raw_name, str) or not raw_name:
            refuse_row(f"projects[{index}]: 'name' must be a non-empty string")
            continue

        name = _quoted(raw_name)

        raw_path = entry.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            refuse_row(f"{name}: 'path' must be a non-empty string")
            continue
        if "\x00" in raw_path:
            # It passes is_absolute() and would load, but every later os call on
            # it raises ValueError — and P03 passes this path as a spawn cwd.
            refuse_row(f"{name}: path {_quoted(raw_path)} contains a NUL byte")
            continue

        project_path = Path(raw_path)
        if not project_path.is_absolute():
            refuse_row(f"{name}: path {_quoted(raw_path)} is not absolute")
            continue
        if project_path.parts[:1] == ("//",):
            # POSIX gives EXACTLY two leading slashes an implementation-defined
            # meaning, and PurePosixPath keeps them as a distinct root, while
            # realpath resolves '//srv/a' and '/srv/a' to the same directory —
            # so both loaded, two records under one identity. Three or more
            # slashes collapse; two do not. Refused rather than normalised, for
            # the same reason as '..' below.
            refuse_row(f"{name}: path {_quoted(raw_path)} must not begin with '//'")
            continue
        if ".." in project_path.parts:
            # PurePath keeps '..', so /srv/a and /srv/c/../a are unequal and both
            # would load — two records with one identity, which § 6 calls a
            # malformed file. Refused rather than normalised: collapsing '..'
            # lexically is wrong when a component is a symlink, and this path
            # becomes a spawn cwd in P03.
            refuse_row(f"{name}: path {_quoted(raw_path)} must not contain '..'")
            continue
        if project_path in seen:
            # ADR-0005 makes the absolute path the identity, so two records
            # sharing one is a malformed file, not a merge question.
            refuse_row(f"{name}: path {_quoted(raw_path)} is already registered")
            continue
        seen.add(project_path)

        # A bad port loses the field, not the row: the project still exists and
        # the user still needs to see it.
        port, reason = _port_or_reason(
            entry.get("port"), "port", *DECLARED_PORT_RANGE, name
        )
        if reason:
            note(reason)
        override, reason = _port_or_reason(
            entry.get("port_override"), "port_override", *OVERRIDE_PORT_RANGE, name
        )
        if reason:
            note(reason)

        # The remaining nine keys, each defaulting when absent and each losing
        # only itself when present at the wrong type. Collected through one list
        # so no field can be parsed and then forgotten on the way to the record —
        # the shape an earlier draft of § 4.2 missed `kind` through.
        fields_and_reasons = [
            _kind_or_reason(entry.get("kind"), name),
            _argv_or_reason(entry.get("argv"), name),
            _string_or_reason(entry.get("unit"), "unit", name),
            _bool_or_reason(entry.get("hidden"), "hidden", name),
            _string_or_reason(
                entry.get("launcher_override"), "launcher_override", name
            ),
            _text_or_reason(entry.get("notes"), "notes", name),
            _bool_or_reason(entry.get("start_at_login"), "start_at_login", name),
            _actions_or_reason(entry.get("actions"), name),
            _added_or_reason(entry.get("added"), name),
        ]
        for _value, reason in fields_and_reasons:
            if reason:
                note(reason)
        (
            kind,
            argv,
            unit,
            hidden,
            launcher_override,
            notes,
            start_at_login,
            actions,
            added,
        ) = (value for value, _reason in fields_and_reasons)

        records.append(
            ProjectRecord(
                path=project_path,
                name=raw_name,
                port=port,
                port_override=override,
                kind=kind,
                argv=argv,
                unit=unit,
                hidden=hidden,
                launcher_override=launcher_override,
                notes=notes,
                start_at_login=start_at_login,
                actions=actions,
                added=added,
            )
        )

    if suppressed:
        # Always, never conditionally quiet: a cap with no tail reads as
        # completeness, and nothing downstream could tell a file with 100
        # problems from one with 524,271.
        reasons.append(f"and {suppressed} more problems in this file, not shown")

    return LoadResult(records=records, reasons=reasons, rows_refused=rows_refused)


# --------------------------------------------------------------------------
# § 4.3 — writing the file
# --------------------------------------------------------------------------


def _serialised(record: ProjectRecord) -> dict[str, object]:
    """One record as the file's object.

    `path` is written as the loader's `Path`, not the user's raw text — nothing
    here resolves a path or follows a symlink, but `Path` normalises on
    construction, so a hand-written `/srv/a/` comes back as `/srv/a`. Stated
    rather than promised against; carrying the raw string would put a second
    field in `ProjectRecord` that no consumer reads.
    """
    return {
        "path": str(record.path),
        "name": record.name,
        "port": record.port,
        "port_override": record.port_override,
        "kind": None if record.kind is None else record.kind.value,
        "argv": list(record.argv),
        "unit": record.unit,
        "hidden": record.hidden,
        "launcher_override": record.launcher_override,
        "notes": record.notes,
        "start_at_login": record.start_at_login,
        # Back to objects: the record holds each action as canonical JSON text,
        # and writing the strings would nest a document inside a string field.
        "actions": [json.loads(action) for action in record.actions],
        "added": record.added,
    }


def _prepare_config_dir(directory: Path) -> None:
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


def _refuse_existing_target(path: Path) -> None:
    """Refuse to replace a symlink or a non-regular file.

    **`os.lstat`, never `os.stat` or `Path.is_file()`** — both follow the link,
    so a symlink pointing at a regular file reports `S_ISREG` true, passes, and
    is then destroyed by `os.replace`, which replaces the *symlink* rather than
    its target. Measured on Python 3.13: the real file was left untouched and
    the user's deliberate indirection became a plain file.

    **The `lstat`-then-`replace` race is accepted and not closed.** Both
    `_read_bounded` and `applog._require_private_regular_file` interrogate a
    *descriptor*; this interrogates a *path*, and `os.replace` takes paths, so
    there is no descriptor to hold across the swap. The only real fix is a
    directory fd plus `renameat`, which buys nothing against an attacker who can
    already write to a 0700 directory owned by the user. Do **not** add a retry
    loop — there is no state to re-check into.

    Deliberately narrower than `applog._require_private_regular_file`, for the
    reason `_read_bounded` already records: a config file may reasonably be
    hard-linked or installed for the user. A symlink is refused because
    replacing one destroys it; a hard link is not, because replacing the path
    leaves the other name intact.
    """
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise RegistryError(
            f"{_quoted(str(path))}: cannot be examined ({exc.strerror or exc})"
        ) from exc
    if stat.S_ISLNK(info.st_mode):
        raise RegistryError(
            f"{_quoted(str(path))}: is a symlink; refusing to replace it"
        )
    if not stat.S_ISREG(info.st_mode):
        raise RegistryError(
            f"{_quoted(str(path))}: is not a regular file; refusing to replace it"
        )


def _refuse_unwritable_load(path: Path, load: LoadResult | RegistryError) -> None:
    """The read-only gate, and it lives HERE rather than in a caller.

    This item builds no caller, so a gate in the caller would be a gate nothing
    implements — and LWSM-1131 § 4.4 says the merge "calls a writer that enforces
    it" rather than re-implementing the check.

    Four states, and only the first two may write: `RegistryMissing` (first run,
    so a fresh file is created), a `LoadResult` with no ROW refusal (including
    one that dropped fields), a `LoadResult` that refused a row, and any other
    `RegistryError`.

    The last is the one a `reasons`-only gate misses entirely: a raised
    `RegistryError` produces **no reasons at all**, so such a gate would write a
    fresh file over a hand-edited registry that had only a JSON typo or a stale
    `schema_version` — destroying a fully recoverable file through the very
    check written to prevent destruction.
    """
    if isinstance(load, RegistryMissing):
        return
    if isinstance(load, RegistryError):
        raise RegistryError(
            f"{_quoted(str(path))}: not writing over a registry that could not be "
            f"loaded ({_quoted(str(load))})"
        )
    if load.rows_refused:
        raise RegistryError(
            f"{_quoted(str(path))}: not writing; {load.rows_refused} row(s) were "
            "refused at load and would be deleted by a write"
        )


def save_projects(
    path: Path,
    records: Sequence[ProjectRecord],
    *,
    load: LoadResult | RegistryError,
) -> None:
    """Write atomically, or raise `RegistryError` naming why it refused.

    `load` is the load these records came from, and it is a parameter rather
    than something recomputed here: whether the session may write is a fact
    about that load, and re-reading the file would answer about a different one.

    The order is the one that survives a failure at any step. Records are
    written **in the order given** and nothing may sort them — LWSM-1131 depends
    on file order twice over, and each write becomes the next load's file order,
    so a writer that sorted by name would silently flip both on every run.
    """
    _refuse_unwritable_load(path, load)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "projects": [_serialised(record) for record in records],
    }
    try:
        # ensure_ascii=False so a non-Latin project name stays readable in the
        # file the user is invited to hand-edit; the bound below is on the
        # encoded bytes, which is what the reader's cap measures.
        text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        data = text.encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise RegistryError(
            f"{_quoted(str(path))}: cannot be serialised "
            f"({type(exc).__name__}: {_quoted(str(exc))})"
        ) from exc

    if len(data) > MAX_FILE_BYTES:
        # Refused before anything is written, rather than written and then found
        # unreadable on the next start by the reader's own cap.
        raise RegistryError(
            f"{_quoted(str(path))}: would be {len(data)} bytes, over the "
            f"{MAX_FILE_BYTES} limit; not written"
        )

    directory = path.parent
    try:
        _prepare_config_dir(directory)
    except OSError as exc:
        raise RegistryError(
            f"{_quoted(str(directory))}: cannot be created ({exc.strerror or exc})"
        ) from exc

    _refuse_existing_target(path)

    # mkstemp creates at 0600 and in the target's own directory, so the rename
    # cannot cross a filesystem. `Path.write_text` would create at
    # `0666 & ~umask`, which is how this file gets a mode nobody chose.
    handle_fd, temporary_name = tempfile.mkstemp(
        dir=directory, prefix=".projects-", suffix=".tmp"
    )
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
            raise RegistryError(
                f"{_quoted(str(path))}: could not be written ({exc.strerror or exc})"
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
        raise RegistryError(
            f"{_quoted(str(path))}: written, but the directory entry could not be "
            f"made durable ({exc.strerror or exc})"
        ) from exc
