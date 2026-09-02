"""LWSM-1005 INV-1, INV-2, INV-10 — the registry refuses what it cannot trust.

No test reads the real ~/.config/localwebservermanager/ (`testing.md § T1`):
every case writes its own file under tmp_path.
"""

from __future__ import annotations

import dataclasses
import errno
import json
import os
import signal
import stat
from pathlib import Path

import pytest

from lwsm import configfile, registry, scanner
from lwsm.registry import (
    LauncherKind,
    ProjectRecord,
    RegistryError,
    RegistryMissing,
    load_projects,
    save_projects,
)


def load(path: Path) -> tuple[list[ProjectRecord], list[str]]:
    """`load_projects`' records and reasons, for the tests written before it
    returned a `LoadResult`.

    LWSM-1007 widened the return; the third value, `rows_refused`, is what the
    write gate reads and it has its own tests below rather than being threaded
    through every existing one that does not care about it.
    """
    result = load_projects(path)
    return result.records, result.reasons


def write(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "projects.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def one_good(path: str = "/srv/project-a", name: str = "project-a") -> dict:
    return {"path": path, "name": name, "port": 5005}


# --- INV-1: the four unusable-file shapes ------------------------------------


def test_unusable_files_are_refused(tmp_path: Path) -> None:
    absent = tmp_path / "nothing" / "projects.json"
    # `RegistryMissing` since LWSM-1007, and matched by name here rather than
    # left to the base class: it is a subclass, so `pytest.raises(RegistryError)`
    # would keep passing if the distinction were lost — and that distinction is
    # what stops a clean machine being permanently read-only.
    with pytest.raises(RegistryMissing, match="does not exist yet"):
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
    records, reasons = load(path)

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
    records, reasons = load(path)

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
    records, reasons = load(path)
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
    records, _ = load(path)
    assert records[0].effective_port == 5106


def test_a_file_with_no_projects_loads_empty(tmp_path: Path) -> None:
    records, reasons = load(write(tmp_path, {"schema_version": 1, "projects": []}))
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
        handle.seek(configfile.MAX_FILE_BYTES + 1)
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
    path.write_bytes(b"x" * (configfile.MAX_FILE_BYTES + 10))

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
    padding = configfile.MAX_FILE_BYTES - len(body) - len('{"pad": "", ')
    payload = {"pad": "x" * padding, **payload}
    path = tmp_path / "projects.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert path.stat().st_size <= configfile.MAX_FILE_BYTES

    records, _ = load(path)
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

    _, reasons = load(path)

    assert len(reasons) == 1
    assert "\n" not in reasons[0], reasons[0]
    assert "\\n" in reasons[0], "the newline must survive, escaped, not vanish"


def test_an_enormous_name_is_clipped(tmp_path: Path) -> None:
    """A 50 MB name produced a 50 MB status string."""
    path = write(
        tmp_path,
        {"schema_version": 1, "projects": [{"name": "A" * 100_000, "path": "nope"}]},
    )

    _, reasons = load(path)

    assert len(reasons) == 1
    # Against the constant, not a loose literal: `< 500` against a 100,000-char
    # input detected removal of the clip and nothing between — `MAX_REASON_CHARS`
    # could be set to 400 and this stayed green (LWSM-1109).
    assert len(reasons[0]) <= 2 * configfile.MAX_REASON_CHARS, (
        f"reason is {len(reasons[0])} characters against a "
        f"MAX_REASON_CHARS of {configfile.MAX_REASON_CHARS}"
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

    quoted = configfile.quoted(hostile)

    # +1 for the ellipsis the clip appends.
    assert len(quoted) <= configfile.MAX_REASON_CHARS + 1, (
        f"{len(quoted)} characters out of a MAX_REASON_CHARS of "
        f"{configfile.MAX_REASON_CHARS}"
    )


def test_a_hostile_port_field_cannot_flood_the_reason(tmp_path: Path) -> None:
    """`configfile.quoted` reached `name` and `path` and never the port fields.

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

    records, reasons = load(path)

    # A bad port loses the field, not the row.
    assert len(records) == 2
    assert len(reasons) == 2, reasons
    for reason in reasons:
        # One quoted name plus one quoted value, each bounded by the constant,
        # plus the fixed template text.
        assert len(reason) <= 3 * configfile.MAX_REASON_CHARS, (
            f"reason is {len(reason)} characters against a MAX_REASON_CHARS "
            f"of {configfile.MAX_REASON_CHARS}"
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
    assert len(message) <= len(str(path)) + 3 * configfile.MAX_REASON_CHARS, (
        f"error is {len(message)} characters against a MAX_REASON_CHARS of "
        f"{configfile.MAX_REASON_CHARS}"
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


def test_the_shipped_bounds_are_pinned() -> None:
    """Every clip assertion is relative to the constant, so none pins its value.

    After LWSM-1109 the assertions read `<= configfile.MAX_REASON_CHARS`, which
    detects *removal* of the clip and not *loosening* of it: 120 → 100000 left
    the suite green (known-issue-005). Spec § 4.1 states the number as part of
    the contract, so it gets an assertion of its own.

    `MAX_REASONS` is pinned here for the same reason and it is the more
    pointed one — it was added by LWSM-1115 with **exactly this defect**, in
    the same pass whose whole subject is fixes that miss their siblings
    (`coding.md § 1.6`). Its tests assert `<= MAX_REASONS + 1`, so 100 →
    100000 would have passed and restored the flood the cap exists to stop.
    """
    assert configfile.MAX_REASON_CHARS == 120
    assert registry.MAX_REASONS == 100
    # Not independent numbers: the pair is what bounds the total, and the
    # product is what a status bar and a log line actually have to absorb.
    assert configfile.MAX_REASON_CHARS * registry.MAX_REASONS < 20_000, (
        "the worst-case reason volume is what LWSM-1115 bounded; raising "
        "either constant has to be justified against that product"
    )
    # LWSM-1007 INV-7 adds the scanner's two, and adds them **beside** the three
    # above rather than replacing them. Every scanner assertion about a clipped
    # string is expressed relative to its constant — `<= MAX_REASON_CHARS + 50`,
    # `== MAX_DISPLAY_NAME_CHARS` — so raising the bound raises the assertion
    # with it and the suite stays green: measured 2026-08-12, setting
    # `scanner.MAX_REASON_CHARS = 400` reddened nothing. Closes known-issue-034.
    assert scanner.MAX_REASON_CHARS == 120
    assert scanner.MAX_DISPLAY_NAME_CHARS == 120


def test_the_number_of_reasons_is_bounded(dense_malformed_file: Path) -> None:
    """`_quoted` bounds how LONG each reason is; nothing bounded how MANY.

    Measured on 2026-08-07 against the file this builds: **524,271** reasons
    totalling **20,859,730** characters, which `build_window` then wrote out as
    one `log.warning` each — 28.7 MB through a handler that rotates at 1 MiB
    keeping 5, so the whole history the user is told to consult is gone, and
    8.7 s of it happens *before* `window.show()`, with no window to interrupt.

    `docs/specs/LWSM-1005-vertical-slice.md § 6` identifies this exact
    amplification for the probe path and answers it with per-message
    suppression (LWSM-1079). The registry path has the same amplification, a
    worse constant, and had no suppression at all.
    """
    records, reasons = load(dense_malformed_file)

    assert records == []
    assert len(reasons) <= registry.MAX_REASONS + 1, (
        f"{len(reasons):,} reasons against a MAX_REASONS of "
        f"{registry.MAX_REASONS} (+1 for the suppressed-count tail)"
    )


def test_the_suppressed_reasons_are_counted_not_silently_dropped(
    dense_malformed_file: Path,
) -> None:
    """A cap with no tail reads as completeness.

    `controller._flush_repeated_error` already holds this rule — "silence and
    suppression are never indistinguishable in the log" — and a truncated
    reason list owes the same. Without the tail, a file with 524,271 problems
    and a file with exactly `MAX_REASONS` problems produce identical output.
    """
    _, reasons = load(dense_malformed_file)

    assert "more" in reasons[-1], f"no suppressed-count tail: {reasons[-1]!r}"
    # The real number, not a vague "many": 524,271 minus what was kept.
    suppressed = 524_271 - registry.MAX_REASONS
    assert str(suppressed) in reasons[-1], (
        f"the tail must name how many were dropped: {reasons[-1]!r}"
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

    records, reasons = load(path)

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

    records, reasons = load(path)

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

    records, reasons = load(path)

    assert records == []
    assert len(reasons) == 1


def test_a_byte_order_mark_does_not_refuse_the_file(tmp_path: Path) -> None:
    """An editor-added BOM is invisible in that editor, and decoding as plain
    utf-8 refused the whole file with a reason naming byte 0."""
    path = tmp_path / "projects.json"
    payload = {"schema_version": 1, "projects": [one_good()]}
    path.write_text(json.dumps(payload), encoding="utf-8-sig")

    records, reasons = load(path)

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


# --- LWSM-1007: the file format and the writer -------------------------------


def test_every_record_field_is_classified() -> None:
    """INV-1. Derived from the dataclass, never from a written list.

    A field belonging to neither set is one LWSM-1131's merge would neither
    refresh nor preserve — it would simply be forgotten on the first rescan,
    silently, with the record still looking complete.
    """
    declared = {field.name for field in dataclasses.fields(ProjectRecord)}
    classified = registry.DETECTED_FIELDS | registry.USER_FIELDS

    assert declared == classified, (
        "every ProjectRecord field belongs to exactly one half; "
        f"unclassified: {sorted(declared - classified)}, "
        f"classified but absent: {sorted(classified - declared)}"
    )
    assert not (registry.DETECTED_FIELDS & registry.USER_FIELDS)


def every_field_record() -> ProjectRecord:
    """One record with every field populated, including a name needing JSON
    escaping — a default-valued field round-trips through a writer that never
    emitted it at all."""
    return ProjectRecord(
        path=Path("/srv/project-a"),
        name='he said "hi"\n\ttab \\ back — ünïcode',
        port=3000,
        port_override=8080,
        kind=LauncherKind.NODE,
        argv=("npm", "run", "dev"),
        unit="project-a.service",
        hidden=True,
        launcher_override="./other.sh",
        notes="a note",
        start_at_login=True,
        actions=('{"kind":"open_url","label":"Docs"}',),
        added="2026-08-12T14:03:11Z",
        browser="firefox.desktop",
    )


def test_write_then_load_round_trips(tmp_path: Path) -> None:
    """INV-3. Equal records, in the same ORDER.

    A set-equality assertion would pass a writer that sorted by name, and file
    order is load-bearing twice over in LWSM-1131 — which of two duplicate
    identities owns it, and its tie-break between two records with no `added`.
    Each write becomes the next load's file order, so a sorting writer would
    flip both on every run.
    """
    path = tmp_path / "projects.json"
    # The second record sorts BEFORE the first by name and by path, so written
    # order and sorted order genuinely differ. Measured 2026-08-14: the first
    # version of this fixture named them "he said…" and "zzz-sorts-last", which
    # are already in sorted order — a writer mutated to `sorted(records, ...)`
    # passed it. A fixture that cannot express the hazard tests nothing.
    written = [
        every_field_record(),  # name starts "he said", path /srv/project-a
        ProjectRecord(path=Path("/srv/aaa-written-second"), name="aaa-written-second"),
    ]

    save_projects(path, written, load=RegistryMissing("first run"))
    result = load_projects(path)

    assert result.records == written
    assert [record.path for record in result.records] == [
        record.path for record in written
    ]
    assert result.reasons == []
    assert result.rows_refused == 0


def test_argv_and_actions_load_back_as_tuples(tmp_path: Path) -> None:
    """The half of INV-3 a value-by-value comparison would miss.

    JSON has only arrays, so a loader returning a `list` produces a record that
    is unequal to the one written while every field *looks* right. `actions`
    additionally has to stay a tuple of strings or `ProjectRecord` becomes
    unhashable — the dataclass is frozen, so its generated `__hash__` raises
    `TypeError` the moment anything hashes a record carrying one.
    """
    path = tmp_path / "projects.json"
    save_projects(path, [every_field_record()], load=RegistryMissing("first run"))

    record = load_projects(path).records[0]

    assert isinstance(record.argv, tuple)
    assert isinstance(record.actions, tuple)
    assert all(isinstance(action, str) for action in record.actions)
    hash(record)


def test_the_written_file_is_private(tmp_path: Path) -> None:
    """INV-4. 0600, and created that way rather than chmodded afterwards.

    A permissive umask is deliberately NOT tested as a breaker, though it reads
    like the obvious one: umask can only clear permission bits, never add them,
    so a fixture varying it against an explicit-mode create can never fail.
    """
    path = tmp_path / "projects.json"
    save_projects(path, [every_field_record()], load=RegistryMissing("first run"))

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_ISREG(path.lstat().st_mode)
    assert not list(tmp_path.glob(".projects-*.tmp")), "a temporary file was left"


def test_a_non_regular_target_is_refused(tmp_path: Path) -> None:
    """INV-4. A FIFO at the config path."""
    path = tmp_path / "projects.json"
    os.mkfifo(path)

    with pytest.raises(RegistryError, match="not a regular file"):
        save_projects(path, [], load=RegistryMissing("first run"))


def test_a_symlinked_target_is_refused_not_followed(tmp_path: Path) -> None:
    """INV-4, and the case the FIFO fixture cannot reach.

    A symlink pointing at a **regular** file passes `os.stat` and
    `Path.is_file()` — both follow the link — and `os.replace` then destroys the
    symlink rather than writing through it. The FIFO test stays green under that
    bug, which is why this one is named separately.
    """
    real = tmp_path / "real.json"
    real.write_text("keep me", encoding="utf-8")
    path = tmp_path / "projects.json"
    path.symlink_to(real)

    with pytest.raises(RegistryError, match="symlink"):
        save_projects(path, [every_field_record()], load=RegistryMissing("first run"))

    assert path.is_symlink(), "the deliberate indirection was destroyed"
    assert real.read_text(encoding="utf-8") == "keep me"


def test_a_failed_write_leaves_the_old_file_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """INV-2. The boundary is `os.replace`, injected just before it.

    "At any point" would be false: § 4.3 step 4's directory fsync runs *after*
    the replace, so a failure there leaves the new file correctly in place with
    nothing to roll back. That case is reported, not reversed.
    """
    path = tmp_path / "projects.json"
    save_projects(path, [every_field_record()], load=RegistryMissing("first run"))
    before = path.read_bytes()

    def explode(source: object, target: object) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(registry.os, "replace", explode)
    with pytest.raises(RegistryError, match="could not be written"):
        save_projects(
            path,
            [ProjectRecord(path=Path("/srv/new"), name="new")],
            load=load_projects(path),
        )

    assert path.read_bytes() == before
    assert load_projects(path).records == [every_field_record()]
    assert not list(tmp_path.glob(".projects-*.tmp")), (
        "the temporary file survived a failure before os.replace"
    )


def test_a_pre_existing_file_still_loads(tmp_path: Path) -> None:
    """INV-5. The four fields the loader read before LWSM-1007, with defaults.

    `schema_version` deliberately does not move: the reader's check is exact, so
    bumping it would refuse every existing file to buy nothing.
    """
    path = write(tmp_path, {"schema_version": 1, "projects": [one_good()]})

    result = load_projects(path)

    assert registry.SCHEMA_VERSION == 1
    assert result.reasons == []
    assert result.records == [
        ProjectRecord(path=Path("/srv/project-a"), name="project-a", port=5005)
    ]
    only = result.records[0]
    assert (only.kind, only.argv, only.unit, only.actions) == (None, (), None, ())
    assert (only.hidden, only.start_at_login, only.notes, only.added) == (
        False,
        False,
        "",
        None,
    )


def test_a_file_with_a_rejected_row_is_never_written_back(tmp_path: Path) -> None:
    """INV-6. A refused row exists only as a reason STRING.

    Serialising `records` back would delete it permanently and silently, turning
    a recoverable hand-edit into data loss.
    """
    path = write(
        tmp_path,
        {"schema_version": 1, "projects": [one_good(), {"path": "/srv/b", "name": ""}]},
    )
    result = load_projects(path)
    assert result.rows_refused == 1
    before = path.read_bytes()

    with pytest.raises(RegistryError, match="refused at load"):
        save_projects(path, result.records, load=result)

    assert path.read_bytes() == before


def test_an_unparseable_file_is_never_written_over(tmp_path: Path) -> None:
    """INV-6, and the state a `reasons`-only gate misses entirely.

    A raised `RegistryError` produces no reasons at all, so such a gate would
    write a fresh file over a hand-edited registry that had only a JSON typo —
    destroying a fully recoverable file through the check written to prevent it.
    """
    path = tmp_path / "projects.json"
    path.write_text('{"schema_version": 1, "projects": [', encoding="utf-8")
    try:
        load_projects(path)
    except RegistryError as exc:
        failure: RegistryError = exc
    before = path.read_bytes()

    with pytest.raises(RegistryError, match="could not be loaded"):
        save_projects(path, [every_field_record()], load=failure)

    assert path.read_bytes() == before


def test_a_dropped_field_does_not_block_the_write(tmp_path: Path) -> None:
    """INV-6's first discriminating case, and the one that keeps the rule honest.

    Keyed on `reasons` being non-empty rather than on a row count, one hand-typed
    `"port": "3000"` would disable persistence for the whole session on a file
    with nothing at risk — and the two fixtures above pass either way.
    """
    path = write(
        tmp_path,
        {
            "schema_version": 1,
            "projects": [{"path": "/srv/project-a", "name": "a", "port": "3000"}],
        },
    )
    result = load_projects(path)

    assert result.reasons, "the bad port should have been reported"
    assert result.rows_refused == 0
    assert result.records[0].port is None

    save_projects(path, result.records, load=result)
    assert load_projects(path).records == result.records


def test_a_missing_file_is_first_run_and_writes(tmp_path: Path) -> None:
    """INV-6's second discriminating case, plus § 4.3 step 0.

    The path is inside a subdirectory that does not exist either. `tmp_path` is
    always created by pytest, so a fixture placing the missing file directly in
    it would pass against a writer that never creates its parent — which is the
    whole of step 0.
    """
    directory = tmp_path / "config" / "localwebservermanager"
    path = directory / "projects.json"
    with pytest.raises(RegistryMissing) as caught:
        load_projects(path)

    save_projects(path, [every_field_record()], load=caught.value)

    assert path.is_file()
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert load_projects(path).records == [every_field_record()]


def test_a_writer_refusal_reason_is_clipped_and_escaped(tmp_path: Path) -> None:
    """INV-8. A runtime assertion, not a source grep.

    The bound is the quoted value plus the fixed template, not the constant
    alone: `_quoted` clips the *value* to `MAX_REASON_CHARS` and appends an
    ellipsis, so a single quoted value is already 121 characters before any
    template text. The no-newline half is the absolute clause and carries the
    actual security property.
    """
    # Long by nesting, not by one long component: NAME_MAX is 255 bytes, so a
    # 500-character directory name is ENAMETOOLONG and the fixture fails before
    # it can measure anything.
    hostile = tmp_path / "bad\nname"
    hostile.mkdir()
    for _ in range(4):
        hostile = hostile / ("x" * 200)
        hostile.mkdir()
    path = hostile / "projects.json"
    os.mkfifo(path)

    with pytest.raises(RegistryError) as caught:
        save_projects(path, [], load=RegistryMissing("first run"))

    message = str(caught.value)
    assert "\n" not in message
    assert len(message) <= len(str(path)) + 3 * configfile.MAX_REASON_CHARS


def test_a_registry_over_the_size_limit_is_refused_before_anything_is_written(
    tmp_path: Path,
) -> None:
    """§ 6. Refused with a reason rather than written and then found unreadable
    by the reader's own cap on the next start."""
    path = tmp_path / "projects.json"
    huge = [
        ProjectRecord(path=Path(f"/srv/{index}"), name="x" * 2000)
        for index in range(1000)
    ]

    with pytest.raises(RegistryError, match="over the"):
        save_projects(path, huge, load=RegistryMissing("first run"))

    assert not path.exists()
    assert not list(tmp_path.glob(".projects-*.tmp"))


# --- LWSM-1007 § 4.2: the blanket wrong-type rule, key by key ----------------


@pytest.mark.parametrize(
    ("key", "bad", "attribute", "default"),
    [
        ("kind", "rust", "kind", None),
        ("kind", 7, "kind", None),
        ("argv", "npm run dev", "argv", ()),
        ("argv", ["npm", 3], "argv", ()),
        ("unit", 7, "unit", None),
        ("launcher_override", [], "launcher_override", None),
        ("hidden", "yes", "hidden", False),
        ("hidden", 1, "hidden", False),
        ("start_at_login", "no", "start_at_login", False),
        ("notes", 7, "notes", ""),
        ("actions", {}, "actions", ()),
        ("added", "2026-08-12", "added", None),
        ("added", "2026-08-12T14:03:11", "added", None),
        ("added", "yesterday", "added", None),
        ("added", 17, "added", None),
        ("browser", 7, "browser", None),
        ("browser", [], "browser", None),
    ],
)
def test_a_wrong_typed_field_loses_the_field_and_keeps_the_row(
    tmp_path: Path, key: str, bad: object, attribute: str, default: object
) -> None:
    """§ 4.2's fourth column, which is one blanket rule for every key.

    The two `added` date-shaped cases are the pointed ones: both parse cleanly
    through `fromisoformat` and denote **no instant**, and "must carry a time"
    would not catch either, because a date-only value parses to midnight and
    has one. A value with no offset cannot be ordered against one that has an
    offset, and LWSM-1131's INV-7 tie-breaks on exactly that ordering.
    """
    entry = one_good() | {key: bad}
    path = write(tmp_path, {"schema_version": 1, "projects": [entry]})

    result = load_projects(path)

    assert len(result.records) == 1, "a field refusal must never drop the row"
    assert result.rows_refused == 0
    assert getattr(result.records[0], attribute) == default
    assert any(key in reason for reason in result.reasons)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("2026-08-12T14:03:11Z", True), ("2026-08-12T15:03:11+01:00", True)],
)
def test_an_added_stamp_carrying_an_offset_is_kept_verbatim(
    tmp_path: Path, value: str, expected: bool
) -> None:
    """The value is not reformatted on the way in or out.

    This app stamps new values as `Z` with second precision, but a hand-edited
    `+01:00` already in the file is written back as it was: "never rewritten
    once set" and "written with a Z suffix" cannot both hold for a stamp the
    reader accepts in any RFC 3339 spelling.
    """
    path = write(
        tmp_path, {"schema_version": 1, "projects": [one_good() | {"added": value}]}
    )
    result = load_projects(path)

    assert result.records[0].added == value
    assert result.reasons == []

    save_projects(path, result.records, load=result)
    assert json.loads(path.read_text(encoding="utf-8"))["projects"][0]["added"] == value


def test_kind_is_serialised_as_its_value_never_its_name(tmp_path: Path) -> None:
    """`"node"`, not `"NODE"` — and the loader accepts only the value.

    A writer emitting the enum's name produces a file its own loader refuses,
    which INV-3's round-trip would catch as an unequal record but not explain.
    """
    path = tmp_path / "projects.json"
    save_projects(path, [every_field_record()], load=RegistryMissing("first run"))

    on_disk = json.loads(path.read_text(encoding="utf-8"))["projects"][0]
    assert on_disk["kind"] == "node"

    refused = write(
        tmp_path, {"schema_version": 1, "projects": [one_good() | {"kind": "NODE"}]}
    )
    assert load_projects(refused).records[0].kind is None


def test_an_action_is_persisted_opaquely_with_its_keys_normalised(
    tmp_path: Path,
) -> None:
    """§ 4.2: the per-action schema is NOT defined by this item.

    An unknown action shape round-trips rather than being refused, because the
    validation `design.md § Custom project actions` requires lands with the item
    that builds the action surface — the only place it has a failure surface to
    report to. The stated cost is that key order inside an action is normalised.
    """
    path = write(
        tmp_path,
        {
            "schema_version": 1,
            "projects": [
                one_good() | {"actions": [{"zzz": 1, "aaa": 2, "nested": {"b": 1}}]}
            ],
        },
    )

    result = load_projects(path)

    assert result.reasons == []
    assert result.records[0].actions == ('{"aaa":2,"nested":{"b":1},"zzz":1}',)
    save_projects(path, result.records, load=result)
    assert load_projects(path).records == result.records


# --- LWSM-1131: the rescan merge ---------------------------------------------


def stamp() -> str:
    """`now()` in the spelling § 4.3 pins.

    `datetime.now().isoformat()` — the obvious choice — produces a **naive**
    stamp, which the loader drops on the next load. Every record the app created
    would lose its timestamp, leaving the duplicate-port tie-break nothing to
    compare on exactly the records the app made itself.
    """
    return "2026-08-14T09:00:00Z"


@dataclasses.dataclass(frozen=True)
class FakeFinding:
    port: int


@dataclasses.dataclass(frozen=True)
class FakeProject:
    path: Path
    name: str
    kind: LauncherKind = LauncherKind.SHELL
    argv: tuple[str, ...] = ("./start.sh",)
    unit: str | None = None
    port: FakeFinding | None = None


@dataclasses.dataclass(frozen=True)
class FakeScan:
    projects: tuple[FakeProject, ...] = ()
    timed_out: bool = False
    unlistable_roots: tuple[Path, ...] = ()


def a_root(tmp_path: Path, name: str = "projects") -> Path:
    root = tmp_path / name
    root.mkdir()
    return root


def test_a_rescan_never_writes_a_user_field(tmp_path: Path) -> None:
    """INV-1. `name` is the discriminating field precisely because BOTH sides
    carry it — a fixture using `notes`, which the scanner has no equivalent of,
    would pass against a merge that copied everything."""
    root = a_root(tmp_path)
    project = root / "web"
    project.mkdir()
    stored = ProjectRecord(
        path=project,
        name="My Renamed Project",
        port_override=8080,
        hidden=True,
        launcher_override="./mine.sh",
        notes="hand-written",
        start_at_login=True,
        actions=('{"kind":"open_url"}',),
        added="2026-08-01T00:00:00Z",
    )

    result = registry.merge(
        [stored], FakeScan((FakeProject(project, "web"),)), (root,), stamp
    )

    after = result.records[0]
    for field in registry.USER_FIELDS:
        assert getattr(after, field) == getattr(stored, field), field


def test_unknown_does_not_erase_a_known_port(tmp_path: Path) -> None:
    """INV-2. The rule this spec exists to add.

    `port` is the only detected field with an unknown value at all. A stored
    3000 with the scan reporting `None` is the absence of an observation, not an
    observation of absence.
    """
    root = a_root(tmp_path)
    project = root / "web"
    project.mkdir()
    stored = ProjectRecord(path=project, name="web", port=3000)

    result = registry.merge(
        [stored],
        FakeScan((FakeProject(project, "web", port=None),)),
        (root,),
        stamp,
    )

    assert result.records[0].port == 3000
    assert result.counts[registry.NOT_REOBSERVED] == 1
    assert any("no longer detected" in reason for reason in result.reasons)


def test_a_units_none_is_a_real_value_and_does_overwrite(tmp_path: Path) -> None:
    """The mirror image of INV-2, and the reason the rule names `port` alone.

    Treating `unit=None` as *unknown* would keep a stale unit name forever on a
    project that stopped being a systemd service — the same defect produced by
    applying the rule too widely rather than too narrowly.
    """
    root = a_root(tmp_path)
    project = root / "web"
    project.mkdir()
    stored = ProjectRecord(
        path=project, name="web", unit="web.service", kind=LauncherKind.SYSTEMD
    )

    result = registry.merge(
        [stored],
        FakeScan((FakeProject(project, "web", kind=LauncherKind.SHELL, unit=None),)),
        (root,),
        stamp,
    )

    assert result.records[0].unit is None
    assert result.records[0].kind is LauncherKind.SHELL
    assert result.counts[registry.CHANGED] == 1


def test_a_first_detection_is_changed_not_silent(tmp_path: Path) -> None:
    """ "the scan value is known", not "both known".

    Requiring both sides to be known would leave a stored `None` meeting a
    detected 3000 matching no row at all — the port would be updated and nothing
    reported.
    """
    root = a_root(tmp_path)
    project = root / "web"
    project.mkdir()
    stored = ProjectRecord(path=project, name="web", port=None)

    result = registry.merge(
        [stored],
        FakeScan((FakeProject(project, "web", port=FakeFinding(3000)),)),
        (root,),
        stamp,
    )

    assert result.records[0].port == 3000
    assert result.counts[registry.CHANGED] == 1


def test_a_missing_project_is_kept_and_flagged(tmp_path: Path) -> None:
    """INV-4. Never deleted — ADR-0005 makes removal a user action, so an
    unmounted drive cannot destroy the list."""
    root = a_root(tmp_path)
    stored = ProjectRecord(path=root / "gone", name="gone", port=3000)

    result = registry.merge([stored], FakeScan(()), (root,), stamp)

    assert result.records == [stored]
    assert result.counts[registry.MISSING] == 1


def test_a_project_outside_every_scan_root_is_not_missing(tmp_path: Path) -> None:
    """ "In scope for this scan" is what makes *missing* mean anything.

    ADR-0005 says "absent from disk", which is not what a scan observes. A
    project added by hand outside every root is present on disk and absent from
    every scan, so the literal reading flags it on every rescan for ever.
    """
    root = a_root(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    stored = ProjectRecord(path=elsewhere, name="hand-added")

    result = registry.merge([stored], FakeScan(()), (root,), stamp)

    assert result.counts[registry.MISSING] == 0


def test_a_timed_out_scan_marks_nothing_missing(tmp_path: Path) -> None:
    """INV-3, first condition. `projects` is partial by definition, so absence
    carries no information."""
    root = a_root(tmp_path)
    stored = ProjectRecord(path=root / "web", name="web")

    result = registry.merge([stored], FakeScan((), timed_out=True), (root,), stamp)

    assert result.counts[registry.MISSING] == 0
    assert any("timed out" in reason for reason in result.reasons)


def test_an_unlistable_root_marks_nothing_missing_under_it(tmp_path: Path) -> None:
    """INV-3, second condition — separate from the first, and a fixture for one
    passes under a merge that implements only the other.

    Deliberately NOT named for `skipped`: an ordinary per-entry skip means the
    scanner looked at an entry and rejected it, which is evidence and must
    suppress nothing. `skipped` is non-empty on any populated machine, so a
    blanket reading would make *missing* unreachable in production.
    """
    root = a_root(tmp_path)
    other = a_root(tmp_path, "other")
    under_refused = ProjectRecord(path=root / "web", name="web")
    under_ok = ProjectRecord(path=other / "api", name="api")

    result = registry.merge(
        [under_refused, under_ok],
        FakeScan((), unlistable_roots=(root,)),
        (root, other),
        stamp,
    )

    assert result.counts[registry.MISSING] == 1, "only the readable root's record"
    assert any("could not be listed" in reason for reason in result.reasons)


def test_an_ordinary_skip_does_not_suppress_the_missing_check(tmp_path: Path) -> None:
    """The other half of the same distinction, asserted rather than assumed."""
    root = a_root(tmp_path)
    stored = ProjectRecord(path=root / "web", name="web")

    result = registry.merge([stored], FakeScan(()), (root,), stamp)

    assert result.counts[registry.MISSING] == 1


def test_two_paths_resolving_to_one_directory_are_one_project(
    tmp_path: Path,
) -> None:
    """INV-5, on known-issue-025's fixture: a symlinked root beside the real one.

    It constrains what MERGES, not what survives. Read as a rule about survival
    it would contradict INV-4, and an implementer would delete the loser along
    with the user-owned half no rescan can reconstruct.
    """
    real = a_root(tmp_path, "real")
    project = real / "web"
    project.mkdir()
    link = tmp_path / "linked"
    link.symlink_to(real)

    first = ProjectRecord(path=project, name="first", notes="keep me")
    second = ProjectRecord(path=link / "web", name="second", notes="keep me too")

    result = registry.merge(
        [first, second],
        FakeScan((FakeProject(project, "web", port=FakeFinding(3000)),)),
        (real,),
        stamp,
    )

    assert len(result.records) == 2, "neither record may be deleted (INV-4)"
    assert result.records[0].port == 3000, "the first in file order owns the identity"
    assert result.records[1] == second, "the loser is written back unchanged"
    assert result.counts[registry.DUPLICATE_IDENTITY] == 1


def test_a_merge_does_not_rewrite_the_stored_path(tmp_path: Path) -> None:
    """INV-8. The `- {"path"}` subtraction, made testable rather than decorative.

    The changed port is load-bearing: without a detected change the merge is
    all-*unchanged*, and an assertion about a written file would read one the
    merge was never permitted to create.
    """
    real = a_root(tmp_path, "real")
    project = real / "web"
    project.mkdir()
    link = tmp_path / "linked"
    link.symlink_to(real)
    stored = ProjectRecord(path=link / "web", name="web", port=None)

    result = registry.merge(
        [stored],
        FakeScan((FakeProject(project, "web", port=FakeFinding(3000)),)),
        (real,),
        stamp,
    )

    assert result.records[0].path == link / "web", "the user's spelling was rewritten"
    assert result.records[0].port == 3000


def test_duplicate_ports_are_flagged_with_the_first_registered_winning(
    tmp_path: Path,
) -> None:
    """INV-7. Earliest `added` wins and the later claimant names the winner."""
    root = a_root(tmp_path)
    older = ProjectRecord(
        path=root / "a", name="older", port=3000, added="2026-08-01T00:00:00Z"
    )
    newer = ProjectRecord(
        path=root / "b", name="newer", port=3000, added="2026-08-05T00:00:00Z"
    )

    result = registry.merge(
        [newer, older], FakeScan((), timed_out=True), (root,), stamp
    )

    assert result.counts[registry.DUPLICATE_PORT] == 1
    assert any("claimed by 'older'" in reason for reason in result.reasons)


def test_a_record_without_added_loses_the_port_tie_break(tmp_path: Path) -> None:
    """INV-7's absent-`added` half — which breaks on EVERY file that exists
    today, since none carries the key."""
    root = a_root(tmp_path)
    without = ProjectRecord(path=root / "a", name="without", port=3000)
    with_stamp = ProjectRecord(
        path=root / "b", name="with", port=3000, added="2026-08-05T00:00:00Z"
    )

    result = registry.merge(
        [without, with_stamp], FakeScan((), timed_out=True), (root,), stamp
    )

    assert any("claimed by 'with'" in reason for reason in result.reasons)


def test_the_added_tie_break_compares_instants_not_text(tmp_path: Path) -> None:
    """INV-9, and the fixture only discriminates because of the ORDERING.

    The two values are an equal instant, so the winner comes from the tie-break.
    Putting the lexically-larger `+01:00` value FIRST is what makes a text
    comparison pick the other record and go red; placed the other way round, a
    text comparison and the correct rule agree and the test proves nothing.
    """
    root = a_root(tmp_path)
    offset = ProjectRecord(
        path=root / "a", name="offset", port=3000, added="2026-08-12T15:03:11+01:00"
    )
    zulu = ProjectRecord(
        path=root / "b", name="zulu", port=3000, added="2026-08-12T14:03:11Z"
    )

    result = registry.merge(
        [offset, zulu], FakeScan((), timed_out=True), (root,), stamp
    )

    assert any("claimed by 'offset'" in reason for reason in result.reasons), (
        "an equal instant must fall back to file order, not to string order"
    )


def test_a_new_project_is_seeded_with_a_name_and_a_stamp(tmp_path: Path) -> None:
    """The one place a merge writes a user-owned field.

    INV-1 is scoped to records already in the registry for exactly this reason:
    read as covering creation, it would forbid giving a new project a name, and
    an implementer obeying it literally would add unnamed rows with no `added` —
    leaving the tie-break nothing to compare on any record the app made itself.
    """
    root = a_root(tmp_path)
    project = root / "web"
    project.mkdir()

    result = registry.merge(
        [],
        FakeScan((FakeProject(project, "web", port=FakeFinding(3000)),)),
        (root,),
        stamp,
    )

    added = result.records[0]
    assert added.name == "web"
    assert added.added == stamp()
    assert added.port == 3000
    assert added.kind is LauncherKind.SHELL
    assert result.counts[registry.NEW] == 1
    # The stamp must survive a round trip, which a naive one would not.
    path = tmp_path / "projects.json"
    save_projects(path, result.records, load=RegistryMissing("first run"))
    assert load_projects(path).records[0].added == stamp()


def test_the_merge_report_is_bounded(tmp_path: Path) -> None:
    """INV-6. LWSM-1115's shape, arriving on a second surface."""
    root = a_root(tmp_path)
    stored = [
        ProjectRecord(path=root / f"p{index}", name="x" * 500)
        for index in range(registry.MAX_REASONS + 50)
    ]

    result = registry.merge(stored, FakeScan(()), (root,), stamp)

    assert len(result.reasons) == registry.MAX_REASONS + 1
    assert "not shown" in result.reasons[-1]
    assert all(
        len(reason) <= 3 * configfile.MAX_REASON_CHARS for reason in result.reasons
    )


def test_no_merge_value_is_interpolated_without_the_clip(tmp_path: Path) -> None:
    """INV-10, as a runtime assertion rather than a second source grep.

    The existing grep already covers `registry.__file__`, so a mirrored one
    could never fail while the old one passed. This asserts the property the
    grep cannot: that a reason a caller actually receives is escaped.
    """
    root = a_root(tmp_path)
    hostile = "evil\nname " + "y" * 500
    stored = ProjectRecord(path=root / "gone", name=hostile)

    result = registry.merge([stored], FakeScan(()), (root,), stamp)

    assert result.reasons
    assert all("\n" not in reason for reason in result.reasons)
    assert all("y" * 200 not in reason for reason in result.reasons)


def test_a_writer_that_cannot_create_its_temporary_raises_registry_error(
    tmp_path: Path,
) -> None:
    """`tempfile.mkstemp` was the only syscall in the writer outside a handler,
    so a full or read-only disk escaped as a raw `OSError` (LWSM-1135).

    Three contracts promise `RegistryError` here: this function's docstring,
    LWSM-1007 § 4.3 step 5, and § 6's *disk is full* row. The consequence was
    not the exception type — `mainwindow` catches only `RegistryError`, so the
    merge was silently discarded AND Rescan stayed disabled for the session.

    Mode `0500` is the reproducible stand-in the review used; ENOSPC, EDQUOT
    and EROFS reach the same line.
    """
    directory = tmp_path / "cfg"
    directory.mkdir(mode=0o700)
    path = directory / "projects.json"
    directory.chmod(0o500)
    try:
        if os.geteuid() == 0:
            pytest.skip("mode bits do not deny root")
        with pytest.raises(RegistryError, match="could not be written"):
            save_projects(
                path, [every_field_record()], load=RegistryMissing("first run")
            )
    finally:
        directory.chmod(0o700)


# --- LWSM-1148: exporting a profile, and merging one back in -----------------


def clean_load(records: list[ProjectRecord] | None = None) -> registry.LoadResult:
    """A `LoadResult` that permits a write: no reasons, no refused rows."""
    return registry.LoadResult(records=records or [], reasons=[], rows_refused=0)


def test_a_profile_round_trips_through_the_registry_loader(tmp_path: Path) -> None:
    """A profile IS a `projects.json`, and this is the whole claim.

    It is what let this item ship with no new on-disk format, no second parser
    and no migration. If it ever stops holding, the format question the build
    skipped comes back — so this asserts the equality directly rather than
    asserting that `export_profile` wrote *something*.
    """
    profile = tmp_path / "saved.json"
    records = [every_field_record(), ProjectRecord(path=Path("/srv/b"), name="b")]

    registry.export_profile(profile, records, load=clean_load(records))

    reloaded = load_projects(profile)
    assert reloaded.records == records
    assert reloaded.reasons == []
    assert reloaded.rows_refused == 0


def test_an_export_is_refused_when_a_row_was_refused_at_load(tmp_path: Path) -> None:
    """The gate, and it is NOT `save_projects`' gate.

    A profile exists to be a known-good configuration. Exporting the survivors
    of a load that dropped a row writes a file that looks complete and is not,
    and the user finds out when they restore it onto another machine.
    """
    profile = tmp_path / "saved.json"
    records = [every_field_record()]
    refused = registry.LoadResult(
        records=records, reasons=["'name' must be a non-empty string"], rows_refused=1
    )

    with pytest.raises(RegistryError) as caught:
        registry.export_profile(profile, records, load=refused)

    assert "1 row(s)" in str(caught.value)
    assert "incomplete" in str(caught.value)
    assert not profile.exists()


def test_a_dropped_field_does_not_block_an_export(tmp_path: Path) -> None:
    """The discriminating case, and the reason the gate reads `rows_refused`.

    A field refusal keeps the row, so nothing is missing from the profile — and
    keying the gate on `reasons` instead would make one hand-typed
    `"port": "3000"` refuse every export for the session.
    """
    profile = tmp_path / "saved.json"
    records = [every_field_record()]
    dropped_field = registry.LoadResult(
        records=records,
        reasons=["port 70000 is not an integer 1-65535"],
        rows_refused=0,
    )

    registry.export_profile(profile, records, load=dropped_field)

    assert load_projects(profile).records == records


def test_the_loader_names_the_user_field_it_dropped(tmp_path: Path) -> None:
    """The wiring, not the gate — and they fail differently.

    The gate test beside this one builds a `LoadResult` by hand, so it passes
    whether or not `load_projects` ever populates the set. That is the shape
    LWSM-1136 recorded: a mechanism with a unit test and no caller looks
    exactly like a working one.

    `port_override` is a USER field, so it is named; `port` is DETECTED, so it
    is not — asserted together, because "names everything" and "names the
    right things" are different claims.
    """
    path = tmp_path / "projects.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "projects": [
                    {
                        "name": "web",
                        "path": "/srv/web",
                        "port": "3000",
                        "port_override": "8080",
                        "unit": 123,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    loaded = load_projects(path)

    assert loaded.rows_refused == 0, "both are field refusals, not row refusals"
    assert "port_override" in loaded.user_fields_refused
    # `unit`, not `port`: both are detected, but `unit` is one of the fields
    # routed through `note_field`, so it is what can actually distinguish
    # "records the right fields" from "records every field". Asserting `port`
    # here proved nothing — it reaches `note` by another path, and a mutant
    # deleting the USER_FIELDS filter survived because of it.
    assert "unit" not in loaded.user_fields_refused, (
        "`unit` is detected — a rescan re-derives it, so a profile missing it "
        "is not a profile that erases anything"
    )


def test_a_refused_user_field_blocks_an_export(tmp_path: Path) -> None:
    """The other half of the test above, and the difference is WHOSE field.

    A dropped DETECTED field is harmless in a profile: a rescan re-derives it.
    A dropped USER field is the opposite — the user half is the entire point
    of a profile, so a hand-typed `"port_override": "8080"` exports as null,
    re-loads cleanly, passes the window's refuse-any-refusal gate, and
    `user_half_applied` then writes that null over a good stored override on
    every machine the profile reaches (LWSM-1215).

    A dropped ROW is visibly absent. A nulled FIELD looks intentional, which
    is what makes this worth refusing rather than reporting.
    """
    profile = tmp_path / "saved.json"
    records = [every_field_record()]
    refused_override = registry.LoadResult(
        records=records,
        reasons=["port_override '8080' is not an integer"],
        rows_refused=0,
        user_fields_refused=frozenset({"port_override"}),
    )

    with pytest.raises(RegistryError) as caught:
        registry.export_profile(profile, records, load=refused_override)

    assert "port_override" in str(caught.value)
    assert not profile.exists(), "a refused export must leave no file behind"


def test_an_export_from_an_unloadable_registry_is_refused(tmp_path: Path) -> None:
    """The state a `reasons`-only gate misses entirely: a raised
    `RegistryError` produces no reasons at all, and the records in hand are
    then not the file's contents."""
    profile = tmp_path / "saved.json"
    with pytest.raises(RegistryError) as caught:
        registry.export_profile(
            profile,
            [every_field_record()],
            load=RegistryError("projects.json: invalid JSON at line 4"),
        )

    assert "could not be loaded" in str(caught.value)
    assert not profile.exists()


def test_an_export_of_nothing_is_refused(tmp_path: Path) -> None:
    """First run has nothing to save, and a zero-project profile is a file
    whose restore silently does nothing."""
    profile = tmp_path / "saved.json"
    with pytest.raises(RegistryError) as caught:
        registry.export_profile(profile, [], load=RegistryMissing("no file"))

    assert "no projects to export" in str(caught.value)
    assert not profile.exists()


def test_an_exported_profile_is_private(tmp_path: Path) -> None:
    """LWSM-1007 INV-4 reaches the second writer too — it records local paths
    and a start-at-login flag wherever it is written."""
    profile = tmp_path / "saved.json"
    records = [every_field_record()]
    registry.export_profile(profile, records, load=clean_load(records))

    assert stat.S_IMODE(profile.stat().st_mode) == 0o600


def test_a_symlinked_export_target_is_refused_not_followed(tmp_path: Path) -> None:
    """`write_json_atomically`'s refusal reaches the profile writer, so a
    deliberate indirection the user set up is not silently flattened."""
    real = tmp_path / "real.json"
    real.write_text("{}", encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(real)
    records = [every_field_record()]

    with pytest.raises(RegistryError):
        registry.export_profile(link, records, load=clean_load(records))

    assert link.is_symlink()
    assert real.read_text(encoding="utf-8") == "{}"


def test_an_export_refusal_reason_is_clipped_and_escaped(tmp_path: Path) -> None:
    """LWSM-1007 INV-8 on the second writer. The refusals interpolate a path
    and a loader message, both of which can carry a hand-edited newline."""
    hostile = RegistryError("x" * 5000 + "\nforged log line")
    with pytest.raises(RegistryError) as caught:
        registry.export_profile(
            tmp_path / "saved.json", [every_field_record()], load=hostile
        )

    text = str(caught.value)
    assert "\n" not in text
    assert len(text) < 5000


def test_an_import_restores_every_user_field_and_no_detected_one() -> None:
    """The central rule, derived from the two sets rather than from a list.

    LWSM-1007 INV-1 makes every `ProjectRecord` field a member of exactly one
    half, so a field added later is checked here without this test being
    touched — which is the whole reason the merge is written against the sets.

    A rescan refreshes the detected half and preserves the user half; an import
    does exactly the reverse.
    """
    stored = ProjectRecord(
        path=Path("/srv/project-a/"),
        name="renamed-locally",
        port=3000,
        port_override=None,
        kind=LauncherKind.PYTHON,
        argv=("python3", "serve.py"),
        unit=None,
        hidden=False,
        launcher_override=None,
        notes="",
        start_at_login=False,
        actions=(),
        added=None,
    )
    profile = every_field_record()

    merged = registry.merge_imported([stored], [profile])
    assert len(merged.records) == 1
    restored = merged.records[0]

    for name in registry.USER_FIELDS:
        assert getattr(restored, name) == getattr(profile, name), (
            f"user field {name!r} was not restored from the profile"
        )
    for name in registry.DETECTED_FIELDS:
        assert getattr(restored, name) == getattr(stored, name), (
            f"detected field {name!r} was taken from the profile and must not be"
        )
    assert merged.counts[registry.CHANGED] == 1


def test_an_imported_project_this_machine_has_never_seen_brings_no_launcher() -> None:
    """The rule `user_half_applied` states, applied to the OTHER branch.

    "Nothing here touches DETECTED_FIELDS, `path` included. Those describe the
    machine the profile was exported FROM; this machine's own scan owns them,
    and a rescan re-derives them for free." That holds where a counterpart
    exists — and the branch that APPENDS a project absent from this machine
    took the profile's record whole, `argv` and all (LWSM-1216).

    `argv` is the launch command. A profile is a configuration, not a
    delivery mechanism for something to run, and a path that was never
    scanned here has no launcher this machine has looked at.

    `path` and the user half survive: the path is the identity a merge may
    never rewrite, and the user half is what a profile is for.
    """
    profile = dataclasses.replace(
        every_field_record(),
        path=Path("/srv/elsewhere"),
        argv=("./start.sh",),
        kind=registry.LauncherKind.SHELL,
        port=4321,
        unit="elsewhere.service",
        notes="mine",
    )

    merged = registry.merge_imported([], [profile])

    (added,) = merged.records
    assert added.path == Path("/srv/elsewhere"), "the identity is kept"
    assert added.notes == "mine", "the user half is what a profile carries"
    assert added.argv == (), "a launch command arrived from another machine"
    assert added.kind is None
    assert added.port is None
    assert added.unit is None


def test_a_recursion_error_while_re_serialising_actions_is_a_reason(
    monkeypatch, tmp_path: Path
) -> None:
    """`RecursionError` is not a `ValueError`, so it has to be named.

    `load_projects` carries that guard around its own `json.loads` with a
    comment saying exactly this; the `json.dumps` in `_actions_or_reason` did
    not (LWSM-1217). Anything escaping here reaches a caller that tolerates
    only `RegistryError` — LWSM-1108's shape at a new call site.

    Injected rather than provoked by a deep document, and the reason is a
    measurement: there is NO depth at which the document clears `json.loads`
    and this `json.dumps` then fails. At 9,800 levels both succeed; at 10,000
    the load raises first and is already converted. The actions element is a
    sub-tree of the document the load just accepted, so it is always
    shallower. The guard is right because two call sites doing the same thing
    must not disagree about what it raises, and that is what this pins.
    """
    real_dumps = json.dumps

    def dumps_too_deep(obj, **kwargs):
        if obj == {"deep": True}:
            raise RecursionError("maximum recursion depth exceeded")
        return real_dumps(obj, **kwargs)

    monkeypatch.setattr(json, "dumps", dumps_too_deep)

    path = tmp_path / "projects.json"
    path.write_text(
        real_dumps(
            {
                "schema_version": 1,
                "projects": [
                    {
                        "name": "web",
                        "path": "/srv/web",
                        "actions": [{"deep": True}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    loaded = load_projects(path)

    (record,) = loaded.records
    assert record.actions == (), "the row survives and loses only the field"
    assert any("could not be re-serialised" in reason for reason in loaded.reasons)


def test_an_interrupt_while_parsing_actions_is_not_turned_into_a_reason(
    monkeypatch, tmp_path: Path
) -> None:
    """The other side of the guard above: catch the right exceptions, not all.

    Widening it to `BaseException` also passes every test beside this one, and
    it would turn a Ctrl-C during a load into a field refusal — the file would
    come back looking merely malformed, and the user's interrupt would be
    reported as a problem with their data.
    """
    real_dumps = json.dumps

    def dumps_interrupted(obj, **kwargs):
        if obj == {"deep": True}:
            raise KeyboardInterrupt
        return real_dumps(obj, **kwargs)

    monkeypatch.setattr(json, "dumps", dumps_interrupted)

    path = tmp_path / "projects.json"
    path.write_text(
        real_dumps(
            {
                "schema_version": 1,
                "projects": [
                    {"name": "web", "path": "/srv/web", "actions": [{"deep": True}]}
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(KeyboardInterrupt):
        load_projects(path)


def test_an_import_clears_a_user_field_the_profile_left_unset() -> None:
    """The stated loss, and the deliberate one.

    An import is a RESTORE, so the user half moves whole — including a value
    the profile does not carry. The alternative, skipping default-valued
    fields, makes export-then-import stop being the identity and leaves a
    profile nobody can reason about. This is the assertion to read first if
    that decision is ever revisited.
    """
    stored = ProjectRecord(
        path=Path("/srv/a"), name="a", port_override=8080, notes="local note"
    )
    profile = ProjectRecord(path=Path("/srv/a"), name="a")

    restored = registry.merge_imported([stored], [profile]).records[0]

    assert restored.port_override is None
    assert restored.notes == ""


def test_an_import_never_rewrites_a_stored_path() -> None:
    """LWSM-1131 INV-8's rule on the second merge. `path` is a detected field,
    and the stored spelling is whatever the user wrote."""
    stored = ProjectRecord(path=Path("/srv/./project-a/"), name="a")
    profile = ProjectRecord(path=Path("/srv/project-a"), name="renamed")

    restored = registry.merge_imported([stored], [profile]).records[0]

    assert restored.path == Path("/srv/./project-a/")
    assert restored.name == "renamed"


def test_two_spellings_of_one_directory_are_one_project_on_import(
    tmp_path: Path,
) -> None:
    """LWSM-1131 INV-5's rule on the second merge: identity is the RESOLVED
    path, so a symlinked spelling in the profile matches the stored record
    rather than arriving as a second project."""
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)

    stored = ProjectRecord(path=real, name="local")
    profile = ProjectRecord(path=link, name="from-profile")

    merged = registry.merge_imported([stored], [profile])

    assert len(merged.records) == 1
    assert merged.records[0].name == "from-profile"
    assert merged.counts[registry.NEW] == 0


def test_a_project_absent_from_the_profile_is_kept() -> None:
    """An import is a merge, never a replacement."""
    kept = ProjectRecord(path=Path("/srv/kept"), name="kept", notes="mine")
    profile = ProjectRecord(path=Path("/srv/other"), name="other")

    merged = registry.merge_imported([kept], [profile])

    assert merged.records[0] == kept
    assert merged.counts[registry.NEW] == 1
    assert [record.name for record in merged.records] == ["kept", "other"]


def test_an_unchanged_project_is_counted_and_not_reported() -> None:
    """`unchanged` is the one outcome that is not news — the same rule the
    rescan merge follows, so `summarise_merge` needs no import-specific case."""
    same = ProjectRecord(path=Path("/srv/a"), name="a", notes="n")

    merged = registry.merge_imported([same], [same])

    assert merged.counts[registry.UNCHANGED] == 1
    assert merged.counts[registry.CHANGED] == 0
    assert merged.reasons == []


def test_a_second_profile_entry_for_one_directory_is_ignored() -> None:
    """The loader refuses a row on its own merits and never compares rows, so
    two profile entries naming one directory both arrive here. Taking the
    second would silently overwrite what the first just restored."""
    stored = ProjectRecord(path=Path("/srv/a"), name="a")
    first = ProjectRecord(path=Path("/srv/a"), name="first", notes="kept")
    second = ProjectRecord(path=Path("/srv/a"), name="second", notes="discarded")

    merged = registry.merge_imported([stored], [first, second])

    assert len(merged.records) == 1
    assert merged.records[0].notes == "kept"
    assert merged.counts[registry.DUPLICATE_IDENTITY] == 1


def test_the_import_report_is_bounded() -> None:
    """LWSM-1007 INV-6's bound on a third surface. A hand-written profile can
    hold as many entries as the byte cap allows, and every one of them reaches
    `log.info` at the call site."""
    stored: list[ProjectRecord] = []
    profile = [
        ProjectRecord(path=Path(f"/srv/p{index}"), name=f"p{index}")
        for index in range(registry.MAX_REASONS * 3)
    ]

    merged = registry.merge_imported(stored, profile)

    assert len(merged.records) == len(profile)
    assert len(merged.reasons) == registry.MAX_REASONS + 1
    assert merged.reasons[-1].startswith("... and ")
    assert str(len(profile) - registry.MAX_REASONS) in merged.reasons[-1]


def test_no_imported_value_is_interpolated_without_the_clip() -> None:
    """LWSM-1131 INV-10 on the second merge. Every value reaching a reason is
    file-sourced, so a hand-edited newline in a profile must not forge a log
    line at the call site."""
    stored = ProjectRecord(path=Path("/srv/a"), name="a")
    hostile = ProjectRecord(
        path=Path("/srv/a"), name="x" * 5000 + "\nforged", notes="changed"
    )

    merged = registry.merge_imported([stored], [hostile])

    assert merged.reasons
    for reason in merged.reasons:
        assert "\n" not in reason
        assert len(reason) < 5000
