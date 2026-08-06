"""The project list, read from a hand-editable JSON file.

Core module — may import QtCore, never QtWidgets (`docs/standards/coding.md
§ O1`). Contract: `docs/specs/LWSM-1005-vertical-slice.md § 4.1`.

The file is hand-editable and therefore attacker-editable (ADR-0007's
reasoning about settings.json, applied here), so every field is type-checked
before use rather than trusted.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

SCHEMA_VERSION = 1

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
    base = Path(raw) if raw and Path(raw).is_absolute() else Path.home() / ".config"
    return base / "localwebservermanager" / "projects.json"


def _is_int(value: object) -> bool:
    """`type(...) is int`, not isinstance: `isinstance(True, int)` is True, so a
    hand-edited `"port": true` would otherwise be accepted as port 1."""
    return type(value) is int


def _port_or_reason(
    value: object, field: str, low: int, high: int, name: str
) -> tuple[int | None, str | None]:
    if value is None:
        return None, None
    if not _is_int(value) or not low <= value <= high:
        return None, f"{name}: {field} {value!r} is not an integer {low}-{high}"
    return value, None


def load_projects(path: Path) -> tuple[list[ProjectRecord], list[str]]:
    """Return (records, rejection reasons).

    Raises RegistryError only when the file itself is unusable — the four
    shapes in the spec's § 4.1. A single bad record never blanks the list.
    """
    try:
        raw = path.read_bytes()
    except OSError as exc:
        # Any OSError, not just FileNotFoundError: a directory at that path or
        # a permission denial must also arrive as RegistryError, because that
        # is the only exception `build_window` tolerates.
        raise RegistryError(f"{path}: cannot be read ({exc})") from exc

    try:
        data = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        # Not a JSONDecodeError, so it has to be caught by name.
        raise RegistryError(f"{path}: not valid UTF-8 ({exc})") from exc
    except json.JSONDecodeError as exc:
        raise RegistryError(f"{path}: not valid JSON ({exc})") from exc

    # json.loads happily returns a list or a string; nothing raises for these.
    if not isinstance(data, dict):
        raise RegistryError(
            f"{path}: top level is {type(data).__name__}, not an object"
        )

    version = data.get("schema_version")
    if not _is_int(version) or version != SCHEMA_VERSION:
        raise RegistryError(
            f"{path}: schema_version {version!r} is not {SCHEMA_VERSION}; "
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

        raw_path = entry.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            reasons.append(f"{raw_name}: 'path' must be a non-empty string")
            continue

        project_path = Path(raw_path)
        if not project_path.is_absolute():
            reasons.append(f"{raw_name}: path {raw_path!r} is not absolute")
            continue
        if project_path in seen:
            # ADR-0005 makes the absolute path the identity, so two records
            # sharing one is a malformed file, not a merge question.
            reasons.append(f"{raw_name}: path {raw_path!r} is already registered")
            continue
        seen.add(project_path)

        # A bad port loses the field, not the row: the project still exists and
        # the user still needs to see it.
        port, reason = _port_or_reason(
            entry.get("port"), "port", *DECLARED_PORT_RANGE, raw_name
        )
        if reason:
            reasons.append(reason)
        override, reason = _port_or_reason(
            entry.get("port_override"), "port_override", *OVERRIDE_PORT_RANGE, raw_name
        )
        if reason:
            reasons.append(reason)

        records.append(
            ProjectRecord(
                path=project_path, name=raw_name, port=port, port_override=override
            )
        )

    return records, reasons
