"""The project list, read from a hand-editable JSON file.

Core module — may import QtCore, never QtWidgets (`docs/standards/coding.md
§ O1`). Contract: `docs/specs/LWSM-1005-vertical-slice.md § 4.1`.

The file is hand-editable and therefore attacker-editable (ADR-0007's
reasoning about settings.json, applied here), so every field is type-checked
before use rather than trusted.
"""

from __future__ import annotations

import enum
import json
import os
from collections.abc import Callable, Sequence
from dataclasses import MISSING as _NO_DEFAULT
from dataclasses import dataclass, replace
from dataclasses import fields as dataclass_fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, TypeGuard

from lwsm.configfile import (
    MAX_FILE_BYTES,
    ConfigFileError,
    quoted,
    read_bounded,
    write_json_atomically,
)

SCHEMA_VERSION = 1

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


class RegistryError(ConfigFileError):
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
    # The desktop entry id of the browser Open uses for this project
    # (`firefox.desktop`), or None for the desktop default (LWSM-1187). An id
    # rather than a command: `browsers.py` resolves it against the desktop's
    # own registered handlers, so nothing here is ever executed as text.
    browser: str | None = None

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
        "browser",
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
    # Which USER fields were dropped, by name. Carried structurally for the
    # reason `MergeResult.counts` is a field rather than something a caller
    # derives: the only other way to answer "was a user field refused?" is to
    # match words inside `reasons`, which breaks silently the first time an
    # entry is reworded. `export_profile` is the caller (LWSM-1215) — a
    # dropped DETECTED field is harmless in a profile because a rescan
    # re-derives it, and a dropped USER field is the profile's whole point.
    user_fields_refused: frozenset[str] = frozenset()


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
        return None, f"{name}: {field} {quoted(value)} is not an integer {low}-{high}"
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
    """A `str | None` field — `unit`, `launcher_override`, `browser`."""
    if value is None:
        return None, None
    if not isinstance(value, str):
        return None, f"{name}: {field} {quoted(value)} is not a string"
    return value, None


def _text_or_reason(value: object, field: str, name: str) -> tuple[str, str | None]:
    """A `str` field defaulting to `""` — `notes`."""
    if value is None:
        return "", None
    if not isinstance(value, str):
        return "", f"{name}: {field} {quoted(value)} is not a string"
    return value, None


def _bool_or_reason(value: object, field: str, name: str) -> tuple[bool, str | None]:
    """`hidden`, `start_at_login`. `type(...) is bool` for `_is_int`'s reason
    inverted: `isinstance(1, bool)` is False, but a bare `1` is not `true` and
    accepting it would make the file's two spellings of the same flag unequal."""
    if value is None:
        return False, None
    if type(value) is not bool:
        return False, f"{name}: {field} {quoted(value)} is not true or false"
    return value, None


def _kind_or_reason(value: object, name: str) -> tuple[LauncherKind | None, str | None]:
    """`kind` accepts only a `LauncherKind` **value** — never its name."""
    if value is None:
        return None, None
    if not isinstance(value, str):
        return None, f"{name}: kind {quoted(value)} is not a string"
    try:
        return LauncherKind(value), None
    except ValueError:
        known = ", ".join(sorted(member.value for member in LauncherKind))
        return None, f"{name}: kind {quoted(value)} is not one of {known}"


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
        return (), f"{name}: argv {quoted(value)} is not a list of strings"
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
        return (), f"{name}: actions {quoted(value)} is not a list"
    try:
        return tuple(
            json.dumps(element, sort_keys=True, separators=(",", ":"))
            for element in value
        ), None
    except (TypeError, ValueError, RecursionError):
        # `RecursionError` is not a `ValueError` and has to be named, which is
        # the guard `load_projects` carries around its own `json.loads` and
        # this call site did not (LWSM-1217, and LWSM-1164 before it).
        #
        # MEASURED, and the filed reasoning does not hold: there is no depth
        # at which the document clears `json.loads` and this `json.dumps` then
        # fails. At 9,800 levels both succeed; at 10,000 the LOAD raises first
        # and is already converted. That is structural rather than lucky — the
        # actions element is a sub-tree of the document the load just
        # accepted, so it is strictly shallower.
        #
        # Kept anyway, because what makes it right is not a reachable input:
        # two call sites doing the same thing should not disagree about which
        # exceptions that thing raises, and the margin above is a property of
        # CPython's C scanner rather than anything this file guarantees.
        return (), f"{name}: actions {quoted(value)} could not be re-serialised"


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
        return None, f"{name}: added {quoted(value)} is not a string"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None, f"{name}: added {quoted(value)} is not an RFC 3339 instant"
    if parsed.tzinfo is None:
        return (
            None,
            f"{name}: added {quoted(value)} has no time-zone offset, "
            "so it denotes no instant",
        )
    return value, None


def load_projects(path: Path) -> LoadResult:
    """Return the records, every rejection reason, and the ROW-refusal count.

    Raises RegistryError only when the file itself is unusable — the four
    shapes in the spec's § 4.1. A single bad record never blanks the list.
    An absent file raises `RegistryMissing`, which is the one subclass the
    write gate treats as writable (LWSM-1007 § 4.3).
    """
    try:
        raw = read_bounded(path)
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
            f"{path}: schema_version {quoted(version)} is not {SCHEMA_VERSION}; "
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
    user_fields_refused: set[str] = set()
    seen: set[Path] = set()

    def note(reason: str) -> None:
        """Record a reason, or count it once `MAX_REASONS` are already held."""
        nonlocal suppressed
        if len(reasons) < MAX_REASONS:
            reasons.append(reason)
        else:
            suppressed += 1

    def note_field(field: str, reason: str) -> None:
        """A field refusal: the row survives, and the FIELD is named.

        Named rather than inferred from the reason text, so a reworded message
        cannot quietly stop a gate firing (LWSM-1215). Only `USER_FIELDS` are
        recorded — a detected field is re-derived by the next scan, so nothing
        downstream needs to know it was dropped.
        """
        note(reason)
        if field in USER_FIELDS:
            user_fields_refused.add(field)

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

        name = quoted(raw_name)

        raw_path = entry.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            refuse_row(f"{name}: 'path' must be a non-empty string")
            continue
        if "\x00" in raw_path:
            # It passes is_absolute() and would load, but every later os call on
            # it raises ValueError — and P03 passes this path as a spawn cwd.
            refuse_row(f"{name}: path {quoted(raw_path)} contains a NUL byte")
            continue

        project_path = Path(raw_path)
        if not project_path.is_absolute():
            refuse_row(f"{name}: path {quoted(raw_path)} is not absolute")
            continue
        if project_path.parts[:1] == ("//",):
            # POSIX gives EXACTLY two leading slashes an implementation-defined
            # meaning, and PurePosixPath keeps them as a distinct root, while
            # realpath resolves '//srv/a' and '/srv/a' to the same directory —
            # so both loaded, two records under one identity. Three or more
            # slashes collapse; two do not. Refused rather than normalised, for
            # the same reason as '..' below.
            refuse_row(f"{name}: path {quoted(raw_path)} must not begin with '//'")
            continue
        if ".." in project_path.parts:
            # PurePath keeps '..', so /srv/a and /srv/c/../a are unequal and both
            # would load — two records with one identity, which § 6 calls a
            # malformed file. Refused rather than normalised: collapsing '..'
            # lexically is wrong when a component is a symlink, and this path
            # becomes a spawn cwd in P03.
            refuse_row(f"{name}: path {quoted(raw_path)} must not contain '..'")
            continue
        if project_path in seen:
            # ADR-0005 makes the absolute path the identity, so two records
            # sharing one is a malformed file, not a merge question.
            refuse_row(f"{name}: path {quoted(raw_path)} is already registered")
            continue
        seen.add(project_path)

        # A bad port loses the field, not the row: the project still exists and
        # the user still needs to see it.
        port, reason = _port_or_reason(
            entry.get("port"), "port", *DECLARED_PORT_RANGE, name
        )
        if reason:
            note_field("port", reason)
        override, reason = _port_or_reason(
            entry.get("port_override"), "port_override", *OVERRIDE_PORT_RANGE, name
        )
        if reason:
            note_field("port_override", reason)

        # The remaining ten keys, each defaulting when absent and each losing
        # only itself when present at the wrong type. Collected through one list
        # so no field can be parsed and then forgotten on the way to the record —
        # the shape an earlier draft of § 4.2 missed `kind` through.
        # Each pair is TAGGED with its own field name, so a refusal can be
        # attributed without reading the reason text (LWSM-1215).
        fields_and_reasons = [
            ("kind", _kind_or_reason(entry.get("kind"), name)),
            ("argv", _argv_or_reason(entry.get("argv"), name)),
            ("unit", _string_or_reason(entry.get("unit"), "unit", name)),
            ("hidden", _bool_or_reason(entry.get("hidden"), "hidden", name)),
            (
                "launcher_override",
                _string_or_reason(
                    entry.get("launcher_override"), "launcher_override", name
                ),
            ),
            ("notes", _text_or_reason(entry.get("notes"), "notes", name)),
            (
                "start_at_login",
                _bool_or_reason(entry.get("start_at_login"), "start_at_login", name),
            ),
            ("actions", _actions_or_reason(entry.get("actions"), name)),
            ("added", _added_or_reason(entry.get("added"), name)),
            ("browser", _string_or_reason(entry.get("browser"), "browser", name)),
        ]
        for field_name, (_value, reason) in fields_and_reasons:
            if reason:
                note_field(field_name, reason)
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
            browser,
        ) = (value for _field, (value, _reason) in fields_and_reasons)

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
                browser=browser,
            )
        )

    if suppressed:
        # Always, never conditionally quiet: a cap with no tail reads as
        # completeness, and nothing downstream could tell a file with 100
        # problems from one with 524,271.
        reasons.append(f"and {suppressed} more problems in this file, not shown")

    return LoadResult(
        records=records,
        reasons=reasons,
        rows_refused=rows_refused,
        user_fields_refused=frozenset(user_fields_refused),
    )


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
        "browser": record.browser,
    }


def _encoded(path: Path, records: Sequence[ProjectRecord]) -> bytes:
    """The file's bytes, or `RegistryError` naming why they could not be made.

    Extracted from `save_projects` by LWSM-1148, which writes the same format
    to a second, user-chosen path. Serialising and bounding are the half both
    writers share; the gate above them is not, because what a write would
    destroy differs between the registry and a profile.

    `path` is a parameter only so the refusals can name the file. Nothing here
    touches it.
    """
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
            f"{quoted(str(path))}: cannot be serialised "
            f"({type(exc).__name__}: {quoted(str(exc))})"
        ) from exc

    if len(data) > MAX_FILE_BYTES:
        # Refused before anything is written, rather than written and then found
        # unreadable on the next start by the reader's own cap.
        raise RegistryError(
            f"{quoted(str(path))}: would be {len(data)} bytes, over the "
            f"{MAX_FILE_BYTES} limit; not written"
        )
    return data


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
            f"{quoted(str(path))}: not writing over a registry that could not be "
            f"loaded ({quoted(str(load))})"
        )
    if load.rows_refused:
        raise RegistryError(
            f"{quoted(str(path))}: not writing; {load.rows_refused} row(s) were "
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
    data = _encoded(path, records)

    try:
        # The directory, the hostile-target refusal and the durable write, in
        # the order that survives a failure at any step — `configfile.py` owns
        # it now because `settings.json` needs the same sequence and a second
        # copy of it would be a second set of the four defects it records.
        write_json_atomically(path, data, prefix=".projects-")
    except ConfigFileError as exc:
        # Converted rather than propagated: this function's contract, § 6 and
        # four tests all promise `RegistryError`, and `ConfigFileError` is its
        # base, so an `except RegistryError` would not catch it.
        raise RegistryError(str(exc)) from exc


# --------------------------------------------------------------------------
# LWSM-1131 — merging a rescan into the stored registry
# --------------------------------------------------------------------------

# The merge lives here rather than in `scanner.py` because it is about records,
# and it reaches the scan through Protocols rather than an import: `scanner.py`
# imports from this module, so importing it back closes a cycle under which the
# package does not import at all. `tests/test_layering.py` asserts the direction
# by AST. Protocols also make the fakes the contract rather than a duck-typing
# workaround the annotation contradicts, which is `ports.SupportsSnapshot`'s
# reasoning applied to a second seam (`testing.md § T1`).


class DetectedPort(Protocol):
    """`scanner.PortFinding`, narrowed to the one field a merge reads.

    The rest of a finding — the rule and the source — is provenance the UI
    shows, and LWSM-1007 § 4.2 deliberately does not persist it: the format
    defines no key for either, so a merge stores the number and the rest is
    recomputed on the next scan.
    """

    port: int


class ScannedProject(Protocol):
    """`scanner.DetectedProject`, as the merge sees it."""

    path: Path  # RESOLVED, absolute; the identity (ADR-0005)
    name: str
    kind: LauncherKind
    argv: tuple[str, ...]
    unit: str | None
    port: DetectedPort | None  # None means UNKNOWN, never a guess


class ScanLike(Protocol):
    """`scanner.ScanResult`, as the merge sees it."""

    projects: tuple[ScannedProject, ...]
    timed_out: bool  # the budget expired; `projects` is partial
    unlistable_roots: tuple[Path, ...]


NEW = "new"
UNCHANGED = "unchanged"
CHANGED = "changed"
MISSING = "missing"
NOT_REOBSERVED = "not re-observed"
OVERRIDE_DIFFERS = "override differs"
DUPLICATE_IDENTITY = "duplicate identity"
DUPLICATE_PORT = "duplicate port"

# `unchanged` is counted and never rendered — it is the one outcome that is not
# news. The UI owns the wording and the order (`mainwindow.summarise_merge`),
# because these are user-visible strings and this is a core module.
OUTCOMES = (
    NEW,
    UNCHANGED,
    CHANGED,
    MISSING,
    NOT_REOBSERVED,
    OVERRIDE_DIFFERS,
    DUPLICATE_IDENTITY,
    DUPLICATE_PORT,
)

# An `added` that is absent sorts after every present one, and two absent ones
# fall back to file order. Every file in existence today lacks the key, so
# "earliest `added` wins" would otherwise have no meaning on exactly the files
# LWSM-1007's INV-5 requires to load.
_NO_INSTANT = datetime.max.replace(tzinfo=UTC)


@dataclass(frozen=True)
class MergeResult:
    """What one merge did. Deliberately NOT a `LoadResult`.

    Nothing a merge produces is refused at row level, so there is no
    `rows_refused` equivalent and an implementer should not reach for that type.
    `counts` is a field rather than something the caller derives, because the
    only other way to build the summary is to match outcome words inside
    `reasons` — which breaks silently the first time an entry is reworded.
    """

    records: list[ProjectRecord]
    reasons: list[str]
    counts: dict[str, int]


def _instant(added: str | None) -> datetime:
    """`added` as a comparable instant, never as text.

    `"2026-08-12T15:03:11+01:00"` sorts *after* `"2026-08-12T14:03:11Z"`
    lexically while denoting the **same** instant, so a string comparison picks
    the wrong duplicate-port winner. Records this app writes are always
    `Z`-spelled, which is exactly why the bug would not appear until someone
    hand-edited one.
    """
    if added is None:
        return _NO_INSTANT
    try:
        parsed = datetime.fromisoformat(added)
    except ValueError:
        return _NO_INSTANT
    # The loader already drops a naive `added`, so this is defence for a record
    # built in memory rather than loaded from a file.
    return _NO_INSTANT if parsed.tzinfo is None else parsed


def _resolve_or_lexical(path: Path) -> tuple[Path, str | None]:
    """`path.resolve()`, falling back to its lexical absolute form.

    Per record and inside a handler: this project has been bitten four times by
    an exception escaping a per-item loop and taking the whole batch with it. It
    is **not** the same call as the `pathlib`-on-3.13 trap — measured, non-strict
    `resolve()` returns normally where `exists()` raises `PermissionError` — so
    this is defence in depth, and no fixture here is known to make it raise.
    """
    try:
        return path.resolve(), None
    except OSError as exc:
        return (
            Path(os.path.abspath(path)),
            f"{quoted(str(path))}: could not be resolved ({exc.strerror or exc})",
        )


def _detected_half_applied(
    record: ProjectRecord, found: ScannedProject
) -> ProjectRecord:
    """`DETECTED_FIELDS - {"path"}`, with `port` qualified by § 4.1.

    The subtraction is the whole of the never-rewrite-a-path rule: `path` is a
    detected field because a scan is what observes it, but the scan's path is
    *resolved* while the stored one is whatever the user wrote. A merge written
    as a set-driven replacement over the whole set — the natural reading of
    "replace the detected half" — rewrites every stored path to its resolved
    form on the first rescan.

    The `port` qualifier is not a detail either: unqualified, this writes `None`
    over a stored `3000` on the first unreadable launcher. `port` is the **only**
    detected field with an unknown value at all. `unit`'s `None` is a real
    value — it is what every non-systemd project has — and treating it as
    unknown would keep a stale unit name forever on a project that stopped being
    a service, which is this rule's own mirror image.
    """
    return replace(
        record,
        port=record.port if found.port is None else found.port.port,
        kind=found.kind,
        argv=tuple(found.argv),
        unit=found.unit,
    )


def merge(
    stored: Sequence[ProjectRecord],
    scan: ScanLike,
    roots: Sequence[Path],
    now: Callable[[], str],
) -> MergeResult:
    """Fold a rescan into the stored registry without discarding user edits.

    `roots` is a parameter because `ScanResult` does not carry it, and the
    *missing* outcome cannot be evaluated without it: inferring roots from the
    projects returned means a root that legitimately contains zero projects
    silently stops marking its records missing. The roots **requested** are used
    rather than the roots actually walked, because a partial scan does not report
    which it reached.

    `now()` must return RFC 3339 with a `Z` suffix and second precision —
    `datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")`. Pinned because
    `Callable[[], str]` admits anything, and the obvious
    `datetime.now().isoformat()` produces a **naive** stamp that the loader then
    drops on the next load: every record this app created would lose its
    timestamp, leaving the duplicate-port tie-break with nothing to compare on
    exactly the records the app made itself.
    """
    reasons: list[str] = []
    counts = dict.fromkeys(OUTCOMES, 0)
    suppressed = 0

    def note(reason: str) -> None:
        """`load_projects`' bound, on a second surface (INV-6)."""
        nonlocal suppressed
        if len(reasons) < MAX_REASONS:
            reasons.append(reason)
        else:
            suppressed += 1

    def flag(outcome: str, reason: str) -> None:
        counts[outcome] += 1
        note(reason)

    resolved_roots: list[Path] = []
    for root in roots:
        resolved, failure = _resolve_or_lexical(Path(root))
        if failure:
            # Excluded from the containment test and reported, rather than
            # silently included as its lexical form — an unresolvable root
            # cannot answer "is this record under it?".
            note(failure)
            continue
        resolved_roots.append(resolved)

    # Resolved before the containment test for the same reason the roots are: a
    # symlinked root would otherwise contain nothing, and here that lands on the
    # permission-denied run, which is the one branch this field exists for.
    unlistable = [_resolve_or_lexical(Path(root))[0] for root in scan.unlistable_roots]

    # --- identity: first in FILE ORDER owns it ----------------------------
    owner: dict[Path, int] = {}
    resolved_of: list[Path] = []
    for index, record in enumerate(stored):
        resolved, failure = _resolve_or_lexical(record.path)
        if failure:
            note(failure)
        resolved_of.append(resolved)
        if resolved in owner:
            # Kept and written back unchanged, never deleted: the loser holds a
            # user-owned half — notes, an override, an `added` — that no rescan
            # could reconstruct, and ADR-0005 makes removal a user action so an
            # unmounted drive cannot destroy the list.
            flag(
                DUPLICATE_IDENTITY,
                f"{quoted(record.name)}: duplicate identity of "
                f"{quoted(stored[owner[resolved]].name)}",
            )
            continue
        owner[resolved] = index

    scanned = {project.path: project for project in scan.projects}
    merged = list(stored)

    # --- the records that merge -------------------------------------------
    for resolved, index in owner.items():
        record = stored[index]
        found = scanned.get(resolved)
        if found is None:
            _note_if_missing(
                record, resolved, scan, resolved_roots, unlistable, flag, note
            )
            continue

        updated = _detected_half_applied(record, found)
        merged[index] = updated

        not_reobserved = record.port is not None and found.port is None
        if updated != record:
            flag(CHANGED, f"{quoted(record.name)}: detected details changed")
        if not_reobserved:
            flag(
                NOT_REOBSERVED,
                f"{quoted(record.name)}: port no longer detected, "
                f"keeping {record.port}",
            )
        if not (updated != record or not_reobserved):
            counts[UNCHANGED] += 1

        # Only `port_override` participates: `launcher_override` is stored but is
        # mapped to no detected field in this item, so there is nothing for it to
        # differ from.
        if record.port_override is not None and updated.port != record.port:
            flag(
                OVERRIDE_DIFFERS,
                f"{quoted(record.name)}: detected port moved to "
                f"{updated.port}, override {record.port_override} stays in force",
            )

    # --- the projects that are new ----------------------------------------
    for project in scan.projects:
        if project.path in owner:
            continue
        # The one place a merge writes a user-owned field. Reading INV-1 as
        # covering creation too would forbid giving a new project a name, and an
        # implementer obeying it literally would add unnamed rows with no
        # `added` — leaving the port tie-break nothing to compare on any record
        # the app itself created.
        merged.append(
            ProjectRecord(
                path=project.path,
                name=project.name,
                port=None if project.port is None else project.port.port,
                kind=project.kind,
                argv=tuple(project.argv),
                unit=project.unit,
                added=now(),
            )
        )
        flag(NEW, f"{quoted(project.name)}: new")

    _flag_duplicate_ports(merged, flag)

    if suppressed:
        # Always, never conditionally quiet: a cap with no tail reads as
        # completeness, which is `load_projects`' rule on its own surface.
        reasons.append(f"and {suppressed} more merge notes, not shown")

    return MergeResult(records=merged, reasons=reasons, counts=counts)


def _note_if_missing(
    record: ProjectRecord,
    resolved: Path,
    scan: ScanLike,
    resolved_roots: Sequence[Path],
    unlistable: Sequence[Path],
    flag: Callable[[str, str], None],
    note: Callable[[str], None],
) -> None:
    """*missing* means absent from a scan that could have seen it.

    ADR-0005 says "absent from disk", which is not what a scan observes — a scan
    observes absence *from its own roots*. A project the user added by hand
    outside every scan root is present on disk and absent from every scan, so
    the literal reading flags it missing on the first rescan and every one after.

    Two conditions suppress the check, and they are the same distinction § 4.1
    draws between an observation of absence and the absence of an observation,
    applied to roots instead of ports: a **timed-out** scan, whose `projects` is
    partial by definition, and a root that could not be **listed**, which hid an
    unknown number of projects. An ordinary per-entry skip suppresses nothing —
    the scanner looked at that entry and rejected it, which is evidence.
    """
    if scan.timed_out:
        note(
            f"{quoted(record.name)}: the scan timed out, so it was not "
            "checked for being missing"
        )
        return
    if any(resolved.is_relative_to(root) for root in unlistable):
        note(
            f"{quoted(record.name)}: its scan root could not be listed, so it "
            "was not checked for being missing"
        )
        return
    if not any(resolved.is_relative_to(root) for root in resolved_roots):
        # Out of scope for this scan, not missing from it.
        return
    flag(MISSING, f"{quoted(record.name)}: no longer found by a scan")


def port_claims(
    records: Sequence[ProjectRecord],
) -> list[tuple[ProjectRecord, ProjectRecord, int]]:
    """`(loser, winner, port)` for every project whose port was claimed first.

    ADR-0005's tie-break, in ONE place because it now has two callers: the
    merge-time flag below, and the Start-time refusal in `ProjectController`.
    The ADR promises both halves of the same sentence — every later claimant
    is flagged *and* "its Start is refused with that message" — and only the
    flag existed, with no channel to carry it (LWSM-1205).

    Earliest `added` wins, by instant. An absent `added` loses to any record
    that has one, two absent ones are ordered by position in the file, and two
    denoting the **same** instant are ordered by position as well. All three
    fall back to file order for the same reason: position always exists.

    Returned in file order of the port's first claimant, and within a port in
    losing order, so the merge report reads the way it always has.
    """
    claimants: dict[int, list[int]] = {}
    for index, record in enumerate(records):
        port = record.effective_port
        if port is not None:
            claimants.setdefault(port, []).append(index)

    claims: list[tuple[ProjectRecord, ProjectRecord, int]] = []
    for port, indexes in claimants.items():
        if len(indexes) < 2:
            continue
        ordered = sorted(indexes, key=lambda i: (_instant(records[i].added), i))
        winner = records[ordered[0]]
        for loser in ordered[1:]:
            claims.append((records[loser], winner, port))
    return claims


def _flag_duplicate_ports(
    records: Sequence[ProjectRecord], flag: Callable[[str, str], None]
) -> None:
    """ADR-0005's duplicate-port flag. The rule lives in `port_claims`."""
    for loser, winner, port in port_claims(records):
        flag(
            DUPLICATE_PORT,
            f"{quoted(loser.name)}: port {port} is claimed by {quoted(winner.name)}",
        )


# --------------------------------------------------------------------------
# LWSM-1148 — exporting a profile, and merging one back in
# --------------------------------------------------------------------------

# A profile IS a `projects.json`: same `schema_version`, same writer, same
# parser. That is the whole reason this item needed no new on-disk format and
# no migration — `export_profile` encodes with `_encoded` and reads back
# through `load_projects` unchanged. A second format would have bound another
# item to it and made this spec-first work (`CLAUDE.md` § Review cadence).


def export_profile(
    path: Path,
    records: Sequence[ProjectRecord],
    *,
    load: LoadResult | RegistryError,
) -> None:
    """Write `records` to a user-chosen path, or raise `RegistryError`.

    The gate is NOT `save_projects`' gate, and the difference is what each
    write would destroy. There, the risk is overwriting a recoverable registry,
    so the question is whether this load may write at all. Here the target is a
    file the user just named, and the risk runs the other way: a profile whose
    whole purpose is to be a known-good configuration must not silently be
    saved missing the rows the load refused. So a row refusal refuses the
    export by naming the count, rather than quietly exporting the survivors.

    `RegistryMissing` is not special-cased the way it is for the registry:
    first run has nothing to export, and the empty check below already says so
    in the words the user needs.
    """
    if not records:
        raise RegistryError(f"{quoted(str(path))}: there are no projects to export")
    if isinstance(load, RegistryError) and not isinstance(load, RegistryMissing):
        raise RegistryError(
            f"{quoted(str(path))}: not exporting a profile from a registry that "
            f"could not be loaded ({quoted(str(load))})"
        )
    if isinstance(load, LoadResult) and load.user_fields_refused:
        # A dropped ROW is visibly absent from the profile; a nulled FIELD
        # looks intentional. It re-loads cleanly, so the window's
        # refuse-any-refusal gate passes it, and `user_half_applied` then
        # writes the null over a good stored value on every machine the
        # profile reaches (LWSM-1215).
        #
        # USER fields only. A dropped detected field is harmless here because
        # the next scan re-derives it, which is what
        # `test_a_dropped_field_does_not_block_an_export` pins.
        refused = ", ".join(sorted(load.user_fields_refused))
        raise RegistryError(
            f"{quoted(str(path))}: not exporting; the stored value of "
            f"{refused} was refused at load, and a profile carrying it would "
            "erase a good one when imported"
        )
    if isinstance(load, LoadResult) and load.rows_refused:
        raise RegistryError(
            f"{quoted(str(path))}: not exporting; {load.rows_refused} row(s) "
            "were refused at load and the profile would be incomplete"
        )

    data = _encoded(path, records)
    try:
        write_json_atomically(path, data, prefix=".profile-")
    except ConfigFileError as exc:
        # Converted for `save_projects`' reason: this function promises the
        # narrow type, and `except RegistryError` does not catch its base.
        raise RegistryError(str(exc)) from exc


def user_half_applied(record: ProjectRecord, profile: ProjectRecord) -> ProjectRecord:
    """`USER_FIELDS`, taken whole — the mirror of `_detected_half_applied`.

    Driven by the set rather than by a field list, so LWSM-1007's INV-1 keeps
    it complete: a field added to `ProjectRecord` and classified *user* is
    restored here without this function being touched.

    **Taken whole, with no per-field qualifier, and that is the deliberate
    difference from its mirror.** `_detected_half_applied` has to qualify
    `port`, because a scan's `None` means *unknown* and would write over a
    stored number. A profile's `None` is not unknown — the profile is a
    complete snapshot of the user half at the moment it was saved, and the
    caller refuses an import whose load reported ANY refusal, so no field of it
    was dropped on the way in. So `added` comes across with the rest: a profile
    that restored nine of ten user fields would be one nobody could reason
    about.

    Nothing here touches `DETECTED_FIELDS`, `path` included. Those describe the
    machine the profile was exported FROM; this machine's own scan owns them,
    and a rescan re-derives them for free.
    """
    return replace(record, **{name: getattr(profile, name) for name in USER_FIELDS})


def _detected_half_cleared(record: ProjectRecord) -> ProjectRecord:
    """`record` with every detected field back at its default, except `path`.

    The mirror of `user_half_applied`, for the branch that APPENDS. That
    function's own rule — "those describe the machine the profile was exported
    FROM; this machine's own scan owns them, and a rescan re-derives them for
    free" — was stated for the branch with a counterpart and not applied to
    this one, which took the profile's record whole, `argv` included
    (LWSM-1216). `argv` is the launch command, and a profile is a
    configuration rather than a delivery mechanism for something to run.

    `path` is exempt because it is the identity: DETECTED_FIELDS classifies it
    detected while it is the one field no write may resolve.

    Defaults come from the dataclass rather than being written out here, so
    INV-1 keeps this complete: a field added to `ProjectRecord` and classified
    detected is cleared without this function being touched.
    """
    defaults = {
        entry.name: (
            entry.default_factory()
            # `_NO_DEFAULT`, not `MISSING`: this module defines its own
            # module-level `MISSING = "missing"` as a merge outcome, which
            # shadows the dataclasses sentinel and made this comparison
            # always true.
            if entry.default_factory is not _NO_DEFAULT
            else entry.default
        )
        for entry in dataclass_fields(ProjectRecord)
        if entry.name in DETECTED_FIELDS and entry.name != "path"
    }
    return replace(record, **defaults)


def merge_imported(
    stored: Sequence[ProjectRecord],
    imported: Sequence[ProjectRecord],
) -> MergeResult:
    """Fold an imported profile into the stored registry.

    The sibling of `merge()`, and the same three rules: identity is the
    *resolved* path so two spellings of one directory are one project, the
    first record in file order owns that identity, and no stored `path` is ever
    rewritten to its resolved form.

    Where it differs is which half moves. A rescan refreshes the detected half
    and preserves the user half; an import does exactly the reverse, because
    the user half is what a profile exists to carry. `unchanged` is counted and
    not news, and a project stored here but absent from the profile is simply
    kept — an import is a merge, never a replacement.
    """
    reasons: list[str] = []
    counts = dict.fromkeys(OUTCOMES, 0)
    suppressed = 0

    def note(reason: str) -> None:
        """`load_projects`' bound, on a third surface (LWSM-1007 INV-6)."""
        nonlocal suppressed
        if len(reasons) < MAX_REASONS:
            reasons.append(reason)
        else:
            suppressed += 1

    def flag(outcome: str, reason: str) -> None:
        counts[outcome] += 1
        note(reason)

    records = list(stored)

    # First in FILE ORDER owns the identity, exactly as `merge()` decides it.
    owner: dict[Path, int] = {}
    for index, record in enumerate(records):
        resolved, failure = _resolve_or_lexical(record.path)
        if failure:
            note(failure)
        owner.setdefault(resolved, index)

    claimed_by_profile: set[Path] = set()
    for record in imported:
        resolved, failure = _resolve_or_lexical(record.path)
        if failure:
            note(failure)

        if resolved in claimed_by_profile:
            # Two records in the profile naming one directory. The loader keeps
            # both — it refuses a row on its own merits and does not compare
            # rows — so the second is flagged here rather than silently
            # overwriting what the first just restored.
            flag(
                DUPLICATE_IDENTITY,
                f"{quoted(record.name)}: a second profile entry for "
                f"{quoted(str(record.path))}; ignored",
            )
            continue
        claimed_by_profile.add(resolved)

        index = owner.get(resolved)
        if index is None:
            # Not on this machine. Appended with the profile's own `path`, not
            # its resolved form, for the reason a merge never rewrites one.
            owner[resolved] = len(records)
            # The USER half only. The profile's detected fields describe the
            # machine it came from, and this one has never scanned this path
            # (LWSM-1216); a rescan derives them here.
            records.append(_detected_half_cleared(record))
            flag(NEW, f"{quoted(record.name)}: added from the profile")
            continue

        current = records[index]
        restored = user_half_applied(current, record)
        if restored == current:
            counts[UNCHANGED] += 1
            continue
        records[index] = restored
        changed = sorted(
            name
            for name in USER_FIELDS
            if getattr(current, name) != getattr(restored, name)
        )
        flag(
            CHANGED,
            f"{quoted(current.name)}: restored from the profile "
            f"({quoted(', '.join(changed))})",
        )

    if suppressed:
        reasons.append(f"... and {suppressed} more")
    return MergeResult(records=records, reasons=reasons, counts=counts)
