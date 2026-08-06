"""LWSM-1005 INV-1, INV-2, INV-10 — the registry refuses what it cannot trust.

No test reads the real ~/.config/localwebservermanager/ (`testing.md § T1`):
every case writes its own file under tmp_path.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lwsm.registry import RegistryError, load_projects


def write(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "projects.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def one_good(path: str = "/srv/project-a", name: str = "project-a") -> dict:
    return {"path": path, "name": name, "port": 5005}


# --- INV-1: the four unusable-file shapes ------------------------------------


def test_unusable_files_are_refused(tmp_path: Path) -> None:
    absent = tmp_path / "nothing" / "projects.json"
    with pytest.raises(RegistryError, match="cannot be read"):
        load_projects(absent)

    a_directory = tmp_path / "dir.json"
    a_directory.mkdir()
    with pytest.raises(RegistryError, match="cannot be read"):
        load_projects(a_directory)

    unreadable = tmp_path / "locked.json"
    unreadable.write_text("{}", encoding="utf-8")
    unreadable.chmod(0o000)
    try:
        with pytest.raises(RegistryError, match="cannot be read"):
            load_projects(unreadable)
    finally:
        unreadable.chmod(0o600)

    not_utf8 = tmp_path / "bytes.json"
    not_utf8.write_bytes(b"\xff\xfe{}")
    with pytest.raises(RegistryError, match="not valid UTF-8"):
        load_projects(not_utf8)

    not_json = tmp_path / "broken.json"
    not_json.write_text("{oh dear", encoding="utf-8")
    with pytest.raises(RegistryError, match="not valid JSON"):
        load_projects(not_json)

    # json.loads succeeds here; only an explicit isinstance check catches it.
    with pytest.raises(RegistryError, match="not an object"):
        load_projects(write(tmp_path, [1, 2, 3]))

    with pytest.raises(RegistryError, match="schema_version"):
        load_projects(write(tmp_path, {"projects": []}))
    with pytest.raises(RegistryError, match="schema_version"):
        load_projects(write(tmp_path, {"schema_version": 2, "projects": []}))
    # True == 1, so only `type(v) is int` rejects this.
    with pytest.raises(RegistryError, match="schema_version"):
        load_projects(write(tmp_path, {"schema_version": True, "projects": []}))

    with pytest.raises(RegistryError, match="'projects'"):
        load_projects(write(tmp_path, {"schema_version": 1}))
    with pytest.raises(RegistryError, match="'projects'"):
        load_projects(write(tmp_path, {"schema_version": 1, "projects": {}}))


# --- INV-2: a bad record is skipped; the rest still load ----------------------


@pytest.mark.parametrize(
    ("bad", "reason"),
    [
        (1, "not an object"),
        ({"path": "/srv/x"}, "'name'"),
        ({"path": "/srv/x", "name": ""}, "'name'"),
        ({"path": "/srv/x", "name": 5}, "'name'"),
        ({"name": "x"}, "'path'"),
        ({"path": "", "name": "x"}, "'path'"),
        ({"path": 5, "name": "x"}, "'path'"),
        ({"path": "relative/x", "name": "x"}, "not absolute"),
    ],
)
def test_bad_record_skipped_others_load(
    tmp_path: Path, bad: object, reason: str
) -> None:
    path = write(tmp_path, {"schema_version": 1, "projects": [bad, one_good()]})
    records, reasons = load_projects(path)

    assert [r.name for r in records] == ["project-a"], "the good record must survive"
    assert any(reason in r for r in reasons), reasons


def test_duplicate_path_is_skipped(tmp_path: Path) -> None:
    # ADR-0005 makes the absolute path the identity, so two records sharing one
    # is a malformed file — and silently collapsing them would drop a row.
    path = write(
        tmp_path,
        {
            "schema_version": 1,
            "projects": [one_good(name="first"), one_good(name="second")],
        },
    )
    records, reasons = load_projects(path)

    assert [r.name for r in records] == ["first"]
    assert any("already registered" in r for r in reasons), reasons


# --- INV-10: the two port fields have different ranges ------------------------


def test_port_ranges_differ_by_field(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        {
            "schema_version": 1,
            "projects": [
                {"path": "/srv/declares-80", "name": "declares-80", "port": 80},
                {
                    "path": "/srv/overrides-80",
                    "name": "overrides-80",
                    "port": 5006,
                    "port_override": 80,
                },
                {"path": "/srv/bool-port", "name": "bool-port", "port": True},
            ],
        },
    )
    records, reasons = load_projects(path)
    by_name = {r.name: r for r in records}

    # A project may legitimately declare 80; ADR-0005's 1024 floor is about the
    # override the user types, not the port the project already uses.
    assert by_name["declares-80"].port == 80
    assert by_name["declares-80"].effective_port == 80

    # An out-of-range override loses the field, not the row.
    assert by_name["overrides-80"].port_override is None
    assert by_name["overrides-80"].effective_port == 5006
    assert any("port_override" in r for r in reasons), reasons

    # isinstance(True, int) is True, so a naive check would make this port 1.
    assert by_name["bool-port"].port is None
    assert len(records) == 3, "a bad port must not delete the project"


def test_override_outranks_declared(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        {
            "schema_version": 1,
            "projects": [
                {
                    "path": "/srv/a",
                    "name": "a",
                    "port": 5005,
                    "port_override": 5106,
                }
            ],
        },
    )
    records, _ = load_projects(path)
    assert records[0].effective_port == 5106


def test_a_file_with_no_projects_loads_empty(tmp_path: Path) -> None:
    records, reasons = load_projects(
        write(tmp_path, {"schema_version": 1, "projects": []})
    )
    assert records == []
    assert reasons == []
