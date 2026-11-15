"""LWSM-1562 — the two small stores: `trust.json` and `started.json`.

What each store holds is also exercised through the supervisor in
`test_supervisor.py`; this file holds the bounds and the file-format rules.
"""

from __future__ import annotations

import json
from pathlib import Path

from lwsm import settings
from lwsm.stores import StartedEntry, StartedStore, TrustStore

FINGERPRINT = "a" * 64


def _entry(**changes: object) -> dict[str, object]:
    base: dict[str, object] = {
        "project": "/srv/a",
        "name": "a",
        "pid": 4242,
        "create_time": 1.5,
        "port": 8000,
    }
    base.update(changes)
    return base


def _started_file(tmp_path: Path, *entries: dict[str, object]) -> Path:
    path = tmp_path / "started.json"
    path.write_text(
        json.dumps({"schema_version": 1, "started": list(entries)}), encoding="utf-8"
    )
    return path


# --- 04.1: reasons are bounded -----------------------------------------------


def test_many_bad_trust_entries_leave_a_bounded_list_of_reasons(
    tmp_path: Path,
) -> None:
    """One reason per bad entry was unbounded: a 1 MiB `trust.json` held on the
    order of 10^5 of them, and all reached the window."""
    bad = {f"relative-{n}": FINGERPRINT for n in range(500)}
    path = tmp_path / "trust.json"
    path.write_text(
        json.dumps({"schema_version": 1, "confirmed": bad}), encoding="utf-8"
    )

    store = TrustStore(path)

    assert len(store.reasons) <= settings.MAX_REASONS + 1, (
        f"{len(store.reasons)} reasons held"
    )
    assert "480" in store.reasons[-1], f"no count of the dropped: {store.reasons[-1]!r}"


def test_repeated_failed_saves_add_one_reason(tmp_path: Path) -> None:
    """A directory that cannot be written failed every `confirm`, and each
    failure appended another reason for the whole session."""
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, so nothing can be created beneath it")
    store = TrustStore(blocker / "trust.json")

    for n in range(5):
        store.confirm(tmp_path / f"p{n}", FINGERPRINT)

    unsaved = [r for r in store.reasons if r.startswith("not saved")]
    assert len(unsaved) == 1, f"reasons: {store.reasons!r}"


# --- 04.4: a non-finite number never reaches the file -------------------------


def test_a_non_finite_create_time_is_dropped_on_load(tmp_path: Path) -> None:
    """`1e999` decodes to `inf`; `_save` then wrote a bare `Infinity`, which the
    shared reader refuses, so the next launch dropped the whole file."""
    path = _started_file(
        tmp_path, _entry(create_time=-1), _entry(project="/srv/b", name="b")
    )
    # `json.dumps` would write `Infinity`; the file holds the literal `1e999`.
    path.write_text(
        path.read_text(encoding="utf-8").replace("-1,", "1e999,", 1), encoding="utf-8"
    )

    store = StartedStore(path)

    assert [e.name for e in store.entries()] == ["b"]


def test_a_non_finite_entry_is_never_written(tmp_path: Path) -> None:
    path = tmp_path / "started.json"
    store = StartedStore(path)

    store.add(StartedEntry(Path("/srv/a"), "a", 4242, float("inf"), 8000))

    assert not path.exists() or "Infinity" not in path.read_text(encoding="utf-8")


# --- 04.5: a port is a port --------------------------------------------------


def test_a_port_outside_the_range_drops_the_entry(tmp_path: Path) -> None:
    path = _started_file(
        tmp_path,
        _entry(port=-5),
        _entry(project="/srv/b", name="b", port=70000),
        _entry(project="/srv/c", name="c", port=8000),
    )

    assert [e.name for e in StartedStore(path).entries()] == ["c"]
