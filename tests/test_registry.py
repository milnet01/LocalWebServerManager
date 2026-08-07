"""LWSM-1005 INV-1, INV-2, INV-10 — the registry refuses what it cannot trust.

No test reads the real ~/.config/localwebservermanager/ (`testing.md § T1`):
every case writes its own file under tmp_path.
"""

from __future__ import annotations

import json
import os
import signal
import stat
from pathlib import Path

import pytest

from lwsm import registry
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
        if os.geteuid() == 0:
            # root ignores the mode bits, so the open SUCCEEDS and this case
            # silently proves nothing. Stated rather than left to pass
            # vacuously (LWSM-1111).
            pytest.skip("mode bits do not deny root")
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


# --- LWSM-1072: the read is bounded and type-checked --------------------------


def test_refuses_a_fifo_rather_than_blocking_on_it(tmp_path: Path) -> None:
    """`Path.read_bytes()` on a FIFO blocks until a writer appears: no window,
    no error, no log line — the least debuggable failure this app can have.

    Same shape `applog.py` already closed for `app.log`, and the same alarm
    safety net, so a regression fails this test instead of hanging the suite.
    `_Blocked` derives from `BaseException` deliberately: a `TimeoutError`
    subclasses `OSError`, and would be caught by code under test.
    """
    path = tmp_path / "projects.json"
    os.mkfifo(path)

    class _Blocked(BaseException):
        pass

    def _too_slow(_signum, _frame):
        raise _Blocked("load_projects blocked on the FIFO")

    previous = signal.signal(signal.SIGALRM, _too_slow)
    signal.alarm(5)
    try:
        with pytest.raises(RegistryError, match="regular file"):
            load_projects(path)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def test_refuses_a_device_node(tmp_path: Path) -> None:
    """A character device: reading it succeeds and returns nothing, so without
    the type check this fails later as 'not valid JSON' — a reason that sends
    the user looking at the wrong thing.

    The node is created under `tmp_path` rather than reading the real
    `/dev/null`, which was the one test outside `tmp_path` that `testing.md
    § T1` otherwise forbids (LWSM-1111). Falls back to `/dev/null` where
    `mknod` needs privileges this run does not have, since the point is the
    character device and not who made it.
    """
    node = tmp_path / "projects.json"
    try:
        os.mknod(node, 0o600 | stat.S_IFCHR, os.makedev(1, 3))
    except (PermissionError, OSError):
        node = Path("/dev/null")

    with pytest.raises(RegistryError, match="regular file"):
        load_projects(node)


def test_refuses_an_oversized_file(tmp_path: Path) -> None:
    """A 600 MB file peaked at 1214 MB RSS. The cap is on the file, not on
    hope."""
    path = tmp_path / "projects.json"
    with path.open("wb") as handle:
        handle.seek(registry.MAX_FILE_BYTES + 1)
        handle.write(b"\0")

    with pytest.raises(RegistryError, match="too large"):
        load_projects(path)


def test_a_file_that_grows_after_the_size_check_is_refused(
    tmp_path: Path, monkeypatch
) -> None:
    """`_read_bounded` reads one byte past the cap and post-checks the length,
    so a file that grew between the `fstat` and the read is still refused
    rather than read whole.

    The mechanism § 4.1 names by name was unguarded: replacing the
    `MAX_FILE_BYTES + 1` read with a plain `read()` and deleting the post-check
    left the suite green, because only the `fstat` path was tested (LWSM-1109).

    The growth is simulated by an `fstat` that under-reports the size, which is
    what a real grow-between-check-and-read looks like from in here. Matched on
    "too large" and not merely `RegistryError`: without the post-check the
    oversized file is read whole and then fails as *invalid JSON*, which is a
    `RegistryError` too and would pass a looser assertion.
    """
    path = tmp_path / "projects.json"
    path.write_bytes(b"x" * (registry.MAX_FILE_BYTES + 10))

    real_fstat = os.fstat

    def under_reporting_fstat(fd):
        values = list(tuple(real_fstat(fd)))
        values[6] = 10  # st_size
        return os.stat_result(values)

    monkeypatch.setattr(registry.os, "fstat", under_reporting_fstat)

    with pytest.raises(RegistryError, match="too large"):
        load_projects(path)


def test_a_file_at_the_size_limit_still_loads(tmp_path: Path) -> None:
    """Guards the cap from being off by one in the direction that refuses
    ordinary files."""
    payload = {"schema_version": 1, "projects": [one_good()]}
    body = json.dumps(payload)
    padding = registry.MAX_FILE_BYTES - len(body) - len('{"pad": "", ')
    payload = {"pad": "x" * padding, **payload}
    path = tmp_path / "projects.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert path.stat().st_size <= registry.MAX_FILE_BYTES

    records, _ = load_projects(path)
    assert len(records) == 1


def test_an_enormous_integer_is_a_registry_error(tmp_path: Path) -> None:
    """CPython caps integer parsing at 4300 digits and raises ValueError — NOT
    a JSONDecodeError, so it escaped as itself and `__main__` died with a
    traceback and no window."""
    path = tmp_path / "projects.json"
    path.write_text(
        '{"schema_version": 1, "projects": [{"path": "/srv/a", "name": "a", '
        '"port": ' + "9" * 5000 + "}]}",
        encoding="utf-8",
    )

    with pytest.raises(RegistryError):
        load_projects(path)


def test_deeply_nested_json_is_a_registry_error(tmp_path: Path) -> None:
    """Nesting exhausts the stack and raises RecursionError, which is not a
    ValueError — `RecursionError -> RuntimeError -> Exception` — so it escapes
    the `except ValueError` that covers the rest of `json.loads`' failures and
    has to be named on its own (LWSM-1108)."""
    path = tmp_path / "projects.json"
    path.write_text("[" * 100_000 + "]" * 100_000, encoding="utf-8")

    with pytest.raises(RegistryError):
        load_projects(path)


# --- LWSM-1078: names are attacker-controlled text -----------------------------


def test_a_newline_in_a_name_cannot_forge_a_log_line(tmp_path: Path) -> None:
    """The reason reaches `log.warning` in `__main__`, so a raw newline lets a
    project name write what looks like a second log record."""
    forged = "evil\nWARNING  lwsm: everything is fine"
    path = write(
        tmp_path,
        {"schema_version": 1, "projects": [{"name": forged, "path": "relative"}]},
    )

    _, reasons = load_projects(path)

    assert len(reasons) == 1
    assert "\n" not in reasons[0], reasons[0]
    assert "\\n" in reasons[0], "the newline must survive, escaped, not vanish"


def test_an_enormous_name_is_clipped(tmp_path: Path) -> None:
    """A 50 MB name produced a 50 MB status string."""
    path = write(
        tmp_path,
        {"schema_version": 1, "projects": [{"name": "A" * 100_000, "path": "nope"}]},
    )

    _, reasons = load_projects(path)

    assert len(reasons) == 1
    # Against the constant, not a loose literal: `< 500` against a 100,000-char
    # input detected removal of the clip and nothing between — `MAX_REASON_CHARS`
    # could be set to 400 and this stayed green (LWSM-1109).
    assert len(reasons[0]) <= 2 * registry.MAX_REASON_CHARS, (
        f"reason is {len(reasons[0])} characters against a "
        f"MAX_REASON_CHARS of {registry.MAX_REASON_CHARS}"
    )


def test_the_clip_bounds_the_escaped_text_not_the_raw_text() -> None:
    """`_quoted` clipped BEFORE the `repr`, so the bound was ~10x the constant.

    Every character here is a non-printable astral code point, which `repr`
    escapes to a 10-character `\\U000e0001` sequence. Clipping first therefore
    bounded the *input* at `MAX_REASON_CHARS` and let the output reach ten
    times that: 400 such characters returned **1203** characters, and a
    rejection reason interpolates two of them (LWSM-1111). An `'A' * 100_000`
    input cannot see this — `repr` adds two quotes to it and nothing more.
    """
    hostile = "\U000e0001" * 400

    quoted = registry._quoted(hostile)

    # +1 for the ellipsis the clip appends.
    assert len(quoted) <= registry.MAX_REASON_CHARS + 1, (
        f"{len(quoted)} characters out of a MAX_REASON_CHARS of "
        f"{registry.MAX_REASON_CHARS}"
    )


def test_a_hostile_port_field_cannot_flood_the_reason(tmp_path: Path) -> None:
    """`_quoted` reached `name` and `path` and never the port fields.

    `_port_or_reason` interpolated `{value!r}`, which escapes but does not
    clip, so a 200 KB string in `port` produced a reason of **200,038**
    characters against a `MAX_REASON_CHARS` of 120 (LWSM-1102). The ceiling is
    the 1 MiB file cap, so a hand-edited file yielded a ~1 MiB status-bar
    string and a ~1 MiB log record into a handler that rotates at 1 MiB
    keeping 5 — scrubbing the very history the user is told to consult.

    LWSM-1078 fixed the name and the path and stopped there because INV-21's
    own *Breaks when* clause said `{value!r}` on the port fields "already did
    the right thing". Half true: escaping yes, bounding no.
    """
    path = write(
        tmp_path,
        {
            "schema_version": 1,
            "projects": [
                {"name": "a", "path": "/srv/a", "port": "X" * 200_000},
                {"name": "b", "path": "/srv/b", "port_override": "Y" * 200_000},
            ],
        },
    )

    records, reasons = load_projects(path)

    # A bad port loses the field, not the row.
    assert len(records) == 2
    assert len(reasons) == 2, reasons
    for reason in reasons:
        # One quoted name plus one quoted value, each bounded by the constant,
        # plus the fixed template text.
        assert len(reason) <= 3 * registry.MAX_REASON_CHARS, (
            f"reason is {len(reason)} characters against a MAX_REASON_CHARS "
            f"of {registry.MAX_REASON_CHARS}"
        )


def test_a_hostile_schema_version_cannot_flood_the_error(tmp_path: Path) -> None:
    """The last field in the module still interpolated as `{version!r}`.

    Same defect as the port fields one call site over (LWSM-1102), and the
    third time this one mechanism has been fixed at a single call site:
    LWSM-1078 did `name` and `path`, LWSM-1102 did the port fields, and
    `schema_version` was left because nobody swept for the others (LWSM-1112).

    This one is worse than the port case in two ways. It raises rather than
    returning a reason, so the whole string reaches `log.warning` **and**
    `set_status_message` with no per-reason bound anywhere in its path; and a
    200 KB value measured **200,093** characters against a `MAX_REASON_CHARS`
    of 120, rising to 1,000,093 at the 1 MiB file cap — a single 1,093,449-byte
    log record into a handler that rotates at 1 MiB keeping 5, which scrubs the
    history the user is told to consult.
    """
    path = write(
        tmp_path,
        {"schema_version": "X" * 200_000, "projects": []},
    )

    with pytest.raises(RegistryError) as caught:
        load_projects(path)

    message = str(caught.value)
    # The path is interpolated too and tmp_path is not hostile input, so the
    # bound is the quoted value plus the fixed template, not the constant alone.
    assert len(message) <= len(str(path)) + 3 * registry.MAX_REASON_CHARS, (
        f"error is {len(message)} characters against a MAX_REASON_CHARS of "
        f"{registry.MAX_REASON_CHARS}"
    )


def test_no_file_sourced_value_is_interpolated_without_the_clip() -> None:
    """`grep '!r}'` over the module must find nothing.

    The acceptance criterion LWSM-1114 was written against, kept as a test so
    the next `{value!r}` is caught at the gate rather than by the next review.
    Three separate passes have now found one of these; a fourth should not have
    to read for it.

    Scoped to `!r}` — an f-string conversion — rather than to `repr(`, which
    `_quoted` itself legitimately calls.
    """
    source = Path(registry.__file__).read_text(encoding="utf-8")

    offenders = [
        f"{number}: {line.strip()}"
        for number, line in enumerate(source.splitlines(), start=1)
        # The comment in `_port_or_reason` cites the defect by name, so match
        # only lines that are not comments.
        if "!r}" in line and not line.strip().startswith("#")
    ]

    assert offenders == [], (
        "file-sourced values must go through _quoted, which escapes AND clips; "
        f"repr alone only escapes: {offenders}"
    )


def test_a_doubled_leading_slash_is_not_a_second_identity(tmp_path: Path) -> None:
    """POSIX gives exactly two leading slashes an implementation-defined
    meaning, and `PurePosixPath` preserves them as a distinct root —
    `Path('//srv/a').parts == ('//', 'srv', 'a')` — while `realpath` resolves
    both to the same directory. Three or more collapse; exactly two do not.

    So `/srv/a` and `//srv/a` both loaded with no reason recorded: two records
    with one identity, which `§ 6` calls a malformed file. `mainwindow` keys
    rows on `Path`, so it drew two rows for one directory, and P03 would spawn
    twice with the same `cwd` (LWSM-1103). Same class as the `..` hole
    LWSM-1078 closed, and refused for the same reason.
    """
    path = write(
        tmp_path,
        {
            "schema_version": 1,
            "projects": [one_good(), one_good(path="//srv/project-a", name="b")],
        },
    )

    records, reasons = load_projects(path)

    assert len(records) == 1, "both records loaded under one identity"
    assert any("//" in reason for reason in reasons), reasons


@pytest.mark.skipif(
    not Path("/proc/self/fd").exists(), reason="descriptor count needs /proc"
)
def test_a_directory_at_the_path_does_not_leak_a_descriptor(tmp_path: Path) -> None:
    """`os.open()` on a directory with `O_RDONLY` **succeeds** on Linux, and
    `os.fdopen()` then raised `IsADirectoryError` before the `with` block was
    entered — so nothing closed the descriptor. 50 calls leaked 50 (LWSM-1104).

    One descriptor today, because `load_projects` runs once from
    `build_window`. It matters because this helper exists *for* resource
    discipline, "a directory at that path" is an enumerated shape in `§ 4.1`
    and in `test_unusable_files_are_refused` — which therefore leaked on every
    test run — and LWSM-1008's rescan makes it unbounded.
    """
    a_directory = tmp_path / "dir.json"
    a_directory.mkdir()

    def open_descriptors() -> int:
        return len(os.listdir("/proc/self/fd"))

    with pytest.raises(RegistryError):
        load_projects(a_directory)
    before = open_descriptors()

    for _ in range(50):
        with pytest.raises(RegistryError):
            load_projects(a_directory)

    assert open_descriptors() <= before, (
        f"{open_descriptors() - before} descriptors leaked over 50 refusals"
    )


def test_a_path_with_a_parent_component_is_refused(tmp_path: Path) -> None:
    """`PurePath` keeps `..`, so `/srv/a` and `/srv/c/../a` are unequal and both
    load — two records with one identity, which `§ 6` calls a malformed file.

    Refused rather than normalised: collapsing `..` lexically is wrong when a
    component is a symlink, and P03 passes this path as a spawn `cwd`.
    """
    path = write(
        tmp_path,
        {
            "schema_version": 1,
            "projects": [one_good(), one_good(path="/srv/c/../project-a", name="b")],
        },
    )

    records, reasons = load_projects(path)

    assert len(records) == 1, "both records loaded under one identity"
    assert any(".." in reason for reason in reasons), reasons


def test_a_path_containing_a_nul_byte_is_refused(tmp_path: Path) -> None:
    """It passes `is_absolute()` and loads, though every later `os` call on it
    raises `ValueError`."""
    path = write(
        tmp_path,
        {
            "schema_version": 1,
            "projects": [{"name": "a", "path": "/srv/a\x00b", "port": 5005}],
        },
    )

    records, reasons = load_projects(path)

    assert records == []
    assert len(reasons) == 1


def test_a_byte_order_mark_does_not_refuse_the_file(tmp_path: Path) -> None:
    """An editor-added BOM is invisible in that editor, and decoding as plain
    utf-8 refused the whole file with a reason naming byte 0."""
    path = tmp_path / "projects.json"
    payload = {"schema_version": 1, "projects": [one_good()]}
    path.write_text(json.dumps(payload), encoding="utf-8-sig")

    records, reasons = load_projects(path)

    assert len(records) == 1
    assert reasons == []


def test_a_missing_home_directory_is_a_registry_error(monkeypatch) -> None:
    """`Path.home()` raises when neither HOME nor a passwd entry resolves, and
    it did so before any window or log existed."""

    def no_home() -> Path:
        raise RuntimeError("Could not determine home directory")

    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(Path, "home", staticmethod(no_home))

    with pytest.raises(RegistryError, match="home directory"):
        registry.default_projects_path()
