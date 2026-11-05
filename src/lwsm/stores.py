"""The two small files the supervisor keeps: `trust.json` and `started.json`.

Core module — no Qt at all (`docs/standards/coding-overrides.md § O1`).
`TrustStore` remembers which launchers the user confirmed (LWSM-1046);
`StartedStore` remembers which servers this manager started, so a relaunch can
adopt them back (LWSM-1428). Moved out of `supervisor.py` by LWSM-1492, which
also gave the two one reader and one writer: the read, the duplicate-key and
`schema_version` refusals, and the whole-file save were the same steps twice.

**Their failure handling stays different on purpose.** Both err safe — an
unreadable file trusts nothing, or adopts nothing — but `TrustStore` keeps each
reason in `reasons` for the window to show, while `StartedStore` only logs.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lwsm.applog import default_state_dir, get_logger
from lwsm.configfile import (
    ConfigFileError,
    ConfigFileNotDurable,
    JsonFileRefused,
    load_json_object,
    quoted,
    write_atomically,
)
from lwsm.settings import default_settings_path

log = get_logger(__name__)


def _read_document(
    path: Path, schema_version: int, refusing: str
) -> tuple[dict[str, Any] | None, str | None]:
    """The file's top-level object, or why it was refused.

    `(document, None)` when usable; `(None, None)` when there is no file, which
    is a first run and nothing wrong; `(None, reason)` otherwise. `refusing`
    ends the reasons that refuse a file that did parse: what the store does
    instead ("trusting nothing in it").
    """
    # The shared reader (LWSM-1357), which also refuses `NaN` and `Infinity`.
    where = quoted(str(path))
    try:
        loaded = load_json_object(path)
    except FileNotFoundError:
        return None, None
    except JsonFileRefused as exc:
        cause = exc.cause
        if exc.stage == "unreadable" and isinstance(cause, OSError):
            return None, f"{where}: cannot be read ({cause.strerror or cause})"
        if exc.stage == "not_object":
            return None, f"{where}: not a JSON object"
        return None, f"{where}: not valid JSON ({type(cause).__name__})"
    if loaded.duplicate_keys:
        # Which of two values was meant is unknowable, and last-wins would let
        # a hand edit choose (LWSM-1436). Nothing in the file is used.
        return None, (
            f"{where}: repeats the key {quoted(loaded.duplicate_keys[0])}; {refusing}"
        )
    document = loaded.data
    version = document.get("schema_version")
    if type(version) is not int or version != schema_version:
        return None, (
            f"{where}: schema_version {quoted(version)} is not {schema_version}; "
            f"{refusing}"
        )
    return document, None


def _write_document(path: Path, payload: dict[str, Any], *, prefix: str) -> str | None:
    """Write the whole file. Returns why nothing was written, or None.

    Written but not made durable is a success that is logged: the file lasts,
    and only a crash could lose it (LWSM-1415).
    """
    data = (json.dumps(payload, indent=2) + "\n").encode("utf-8", "surrogateescape")
    try:
        write_atomically(path, data, prefix=prefix)
    except ConfigFileNotDurable as exc:
        log.warning("%s: %s", path.name, exc)
    except (ConfigFileError, OSError) as exc:
        return str(exc)
    return None


# --------------------------------------------------------------------------
# trust.json — the launchers the user confirmed (LWSM-1046)
# --------------------------------------------------------------------------

TRUST_SCHEMA_VERSION = 1

# A `launcher_fingerprint` is a SHA-256 hex digest, so anything else in the file
# was not written by this module and names nothing a confirmation can match.
_FINGERPRINT = re.compile(r"\A[0-9a-f]{64}\Z")


def default_trust_path() -> Path:
    """`trust.json` beside `settings.json`, for that function's reason: one XDG
    rule, so the config files cannot drift into different directories."""
    return default_settings_path().with_name("trust.json")


class TrustStore:
    """Which launchers the user has confirmed, keyed by resolved project path.

    ADR-0003's gate is "one-time per-project", so with a `path` a confirmation
    is written to `trust.json` and read back on the next launch (LWSM-1046).
    Asking every session trained the user to click through the one dialog that
    exists to make them read what will run. With no `path` the store is memory
    only, which is what every test's `Supervisor` gets.

    **Every failure here errs towards asking again.** An unreadable file, a
    repeated key, a malformed entry or a newer schema trusts nothing it cannot
    read, and a save
    that fails keeps the confirmation for this session only. Each says why in
    `reasons` and the log. Nothing is gated on a refused read, unlike
    `projects.json`: rewriting over a refused file loses confirmations, and a
    lost confirmation is one more question, never a launcher run unasked. The
    same holds across two running instances, where the last writer wins.

    The fingerprint already covers the argv and the launcher's bytes, so a
    stored entry re-arms on its own when either changes. Entries for projects
    that have since gone are kept, not pruned: they match nothing.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._confirmed: dict[Path, str] = {}
        self._lock = threading.Lock()
        self._path = path
        self.reasons: list[str] = []
        if path is not None:
            self._load(path)

    def _refuse(self, reason: str) -> None:
        self.reasons.append(reason)
        log.warning("trust store: %s", reason)

    def _load(self, path: Path) -> None:
        document, refused = _read_document(
            path, TRUST_SCHEMA_VERSION, "trusting nothing in it"
        )
        if refused is not None:
            self._refuse(refused)
        if document is None:
            return
        confirmed = document.get("confirmed")
        if not isinstance(confirmed, dict):
            self._refuse(f'{quoted(str(path))}: no "confirmed" object')
            return
        for key, fingerprint in confirmed.items():
            project = Path(key)
            if not project.is_absolute():
                self._refuse(f"{quoted(key)}: not an absolute path; dropped")
            elif not isinstance(fingerprint, str) or not _FINGERPRINT.match(
                fingerprint
            ):
                self._refuse(f"{quoted(key)}: not a launcher fingerprint; dropped")
            else:
                self._confirmed[project] = fingerprint

    def _save(self) -> str | None:
        """Write the whole set. Called with `_lock` held, so writes keep order.

        Returns the failure when nothing was written, so `revoke` can say so;
        None when the file was written, or when this store keeps no file.
        """
        if self._path is None:
            return None
        payload = {
            "schema_version": TRUST_SCHEMA_VERSION,
            "confirmed": {
                str(project): fingerprint
                for project, fingerprint in sorted(self._confirmed.items())
            },
        }
        failed = _write_document(self._path, payload, prefix=".trust-")
        if failed is not None:
            self._refuse(f"not saved, so this lasts until the app closes: {failed}")
        return failed

    def confirm(self, project: Path, fingerprint: str) -> None:
        with self._lock:
            self._confirmed[Path(project).resolve()] = fingerprint
            self._save()

    def is_confirmed(self, project: Path, fingerprint: str) -> bool:
        with self._lock:
            return self._confirmed.get(Path(project).resolve()) == fingerprint

    def revoke(self, project: Path) -> str | None:
        """Forget that this project's launcher was confirmed.

        Called from the row's "Ask before starting again" (LWSM-1319), through
        `ProjectController.forget_trust`.

        Not `start()`'s path. A launcher whose CONTENT changes is re-refused on
        its own, because `launcher_fingerprint` hashes it and the stored
        confirmation names the old digest. This is the other question — the
        user withdrawing trust from a project whose launcher has not changed —
        and nothing but a person can answer it, which is why its only caller is
        a menu entry.

        Idempotent: revoking a project that was never confirmed is not an
        error, so a UI need not ask first.

        Returns why the withdrawal was not saved, or None. Unsaved, it holds
        until the app closes and the old confirmation in the file comes back
        at the next launch, so the window must not promise more (LWSM-1474).
        """
        with self._lock:
            self._confirmed.pop(Path(project).resolve(), None)
            return self._save()


# --------------------------------------------------------------------------
# started.json — the servers a relaunch adopts back (LWSM-1428)
# --------------------------------------------------------------------------

STARTED_SCHEMA_VERSION = 1


def default_started_path() -> Path:
    """`started.json` in the state directory: a record of what happened, not
    a setting (`coding-overrides.md` § O3; LWSM-1428 § 4.1)."""
    return default_state_dir() / "started.json"


@dataclass(frozen=True)
class StartedEntry:
    """One server this manager started: enough to know it again (LWSM-1428).

    ADR-0004's identity for a managed server — the launcher's PID plus its
    `create_time`. `name` only rebuilds the log path; no path is read back.
    `since_boot` and `boot_id` carry the same identity off the wall clock
    (LWSM-1448); an entry written before them has neither.
    """

    project: Path
    name: str
    pid: int
    create_time: float
    port: int | None
    since_boot: float | None = None
    boot_id: str | None = None


class StartedStore:
    """The servers this manager started, kept across a relaunch (LWSM-1428).

    Every failure errs safe, as `TrustStore`'s does: a file that cannot be read
    adopts nothing, so those servers read `running (foreign)`, which is what
    every session showed before this record existed. Unlike `TrustStore` it
    keeps no reasons; a failure is logged only. With no `path` it is memory
    only, which is what every test's `Supervisor` gets.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._entries: dict[Path, StartedEntry] = {}
        self._lock = threading.Lock()
        self._path = path
        if path is not None:
            self._load(path)

    def _load(self, path: Path) -> None:
        # A repeated key leaves which of two PIDs, or two projects, is the
        # server's unknowable, so it adopts nothing (LWSM-1436).
        document, refused = _read_document(
            path, STARTED_SCHEMA_VERSION, "adopting nothing"
        )
        if refused is not None:
            log.warning("started record: %s", refused)
        if document is None:
            return
        started = document.get("started")
        if not isinstance(started, list):
            log.warning('started record: no "started" list; adopting nothing')
            return
        for raw in started:
            entry = _started_entry(raw)
            if entry is None:
                log.warning("started record: dropped a malformed entry")
            else:
                self._entries[entry.project] = entry

    def _save(self) -> None:
        """Write the whole set. Called with `_lock` held, so writes keep order."""
        if self._path is None:
            return
        payload = {
            "schema_version": STARTED_SCHEMA_VERSION,
            "started": [
                {
                    "project": str(entry.project),
                    "name": entry.name,
                    "pid": entry.pid,
                    "create_time": entry.create_time,
                    "port": entry.port,
                    **(
                        {"since_boot": entry.since_boot, "boot_id": entry.boot_id}
                        if entry.since_boot is not None
                        else {}
                    ),
                }
                for _project, entry in sorted(self._entries.items())
            ],
        }
        failed = _write_document(self._path, payload, prefix=".started-")
        if failed is not None:
            # The session runs as before; a stale entry left on disk is refused
            # by `adopt` once its process is gone (LWSM-1428 § 6).
            log.warning("started record not saved: %s", failed)

    def entries(self) -> list[StartedEntry]:
        with self._lock:
            return list(self._entries.values())

    def add(self, entry: StartedEntry) -> None:
        with self._lock:
            self._entries[entry.project] = entry
            self._save()

    def remove(self, *projects: Path) -> None:
        with self._lock:
            gone = [p for p in projects if self._entries.pop(p, None) is not None]
            if gone:
                self._save()


def _started_entry(raw: object) -> StartedEntry | None:
    """One stored entry, or None if any field is not what `_save` writes.

    `bool` is refused where an int is meant: it is an `int` subclass, and
    `"pid": true` would otherwise name PID 1.
    """
    if not isinstance(raw, dict):
        return None
    project, name = raw.get("project"), raw.get("name")
    pid, created, port = raw.get("pid"), raw.get("create_time"), raw.get("port")
    if not (isinstance(project, str) and Path(project).is_absolute()):
        return None
    if not isinstance(name, str) or type(pid) is not int or pid <= 1:
        return None
    if isinstance(created, bool) or not isinstance(created, (int, float)):
        return None
    if port is not None and type(port) is not int:
        return None
    # Both or neither (LWSM-1448). Neither is a file from before them, and
    # adoption then falls back to `create_time`.
    since_boot, boot_id = raw.get("since_boot"), raw.get("boot_id")
    if since_boot is None and boot_id is None:
        return StartedEntry(Path(project), name, pid, float(created), port)
    if isinstance(since_boot, bool) or not isinstance(since_boot, (int, float)):
        return None
    if not isinstance(boot_id, str) or not boot_id:
        return None
    return StartedEntry(
        Path(project), name, pid, float(created), port, float(since_boot), boot_id
    )
