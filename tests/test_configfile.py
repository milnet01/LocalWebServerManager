"""LWSM-1357 — `configfile.load_json_object`, the one JSON config reader.

Three readers (`registry.load_projects`, `settings.load`, `TrustStore._load`)
each repeated the same load sequence and their guards drifted: only the
registry noted duplicate keys and the trust store refused no `NaN`. These
pin the sequence once; each caller's own tests pin its wording.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lwsm.configfile import (
    MAX_FILE_BYTES,
    ConfigFileError,
    JsonFileRefused,
    load_json_object,
)


def write(tmp_path: Path, text: str | bytes) -> Path:
    path = tmp_path / "file.json"
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8")
    return path


def refusal(path: Path) -> JsonFileRefused:
    with pytest.raises(JsonFileRefused) as caught:
        load_json_object(path)
    return caught.value


def test_an_object_loads_and_a_byte_order_mark_is_tolerated(tmp_path: Path) -> None:
    path = write(tmp_path, '﻿{"a": 1}'.encode())
    loaded = load_json_object(path)
    assert loaded.data == {"a": 1}
    assert loaded.duplicate_keys == ()


def test_a_missing_file_is_not_a_refusal(tmp_path: Path) -> None:
    """First run: each caller treats it as no file, not as a broken one."""
    with pytest.raises(FileNotFoundError):
        load_json_object(tmp_path / "absent.json")


def test_an_unreadable_file_is_refused_with_its_cause(tmp_path: Path) -> None:
    path = write(tmp_path, b"x" * (MAX_FILE_BYTES + 1))
    refused = refusal(path)
    assert refused.stage == "unreadable"
    assert isinstance(refused.cause, OSError)


@pytest.mark.parametrize(
    ("text", "stage"),
    [
        (b"\xff\xfe{}", "not_utf8"),
        ("{not json", "not_json"),
        ('{"a": NaN}', "unparseable"),
        ('{"a": Infinity}', "unparseable"),
        ('{"a": -Infinity}', "unparseable"),
        ("[" * 100_000 + "]" * 100_000, "unparseable"),
        ('{"port": ' + "9" * 5000 + "}", "unparseable"),
        ("[1, 2]", "not_object"),
    ],
    ids=[
        "bytes",
        "syntax",
        "nan",
        "infinity",
        "minus-infinity",
        "nesting",
        "huge-int",
        "array",
    ],
)
def test_each_way_a_file_fails_is_named(tmp_path: Path, text, stage: str) -> None:
    """The stage, so each caller can keep its own wording for it. `NaN` and
    `Infinity` are Python's, not JSON's: accepted, they are written back
    bare and no other tool can read the file (known-issue-056)."""
    refused = refusal(write(tmp_path, text))
    assert refused.stage == stage
    assert isinstance(refused, ConfigFileError), "callers catch the base class"


def test_a_non_object_names_what_it_found(tmp_path: Path) -> None:
    assert refusal(write(tmp_path, '"text"')).found == "str"


def test_duplicate_keys_keep_the_last_and_are_reported(tmp_path: Path) -> None:
    """`json`'s own rule is last-wins, silently; the loss is reported so a
    caller can say a hand-edit lost a value."""
    loaded = load_json_object(
        write(tmp_path, '{"a": 1, "a": 2, "b": {"c": 1, "c": 3}}')
    )
    assert loaded.data == {"a": 2, "b": {"c": 3}}
    assert loaded.duplicate_keys == ("c", "a")


# --- LWSM-1361: one capped reason list ----------------------------------------


def test_bounded_reasons_keeps_the_first_cap_and_counts_the_rest() -> None:
    """Hand-written four times before (scanner, registry load, merge, import).
    A cap with no tail reads exactly like completeness, so the count of what
    was dropped is always said once anything was."""
    from lwsm.configfile import BoundedReasons

    bounded = BoundedReasons(cap=2, tail="and {count} more, not shown")
    for n in range(5):
        bounded.note(f"r{n}")

    assert bounded.close() == ["r0", "r1", "and 3 more, not shown"]


def test_bounded_reasons_says_nothing_extra_when_nothing_was_dropped() -> None:
    from lwsm.configfile import BoundedReasons

    bounded = BoundedReasons(cap=2, tail="and {count} more, not shown")
    bounded.note("only")

    assert bounded.close() == ["only"]


# --- review-code 2026-10-08 L03-L4: what a crash or a first run leaves ---------


def test_a_temporary_a_crash_left_behind_is_removed_by_the_next_write(
    tmp_path: Path,
) -> None:
    """A crash between `mkstemp` and `os.replace` leaves `.projects-*.tmp` in
    the config directory, and nothing ever removed it. The next write of the
    same file removes its own prefix's leftovers -- only old ones, so a
    temporary another write is filling right now is never touched.

    Dies on removing nothing, and on removing a fresh temporary.
    """
    import os
    import time

    from lwsm.configfile import write_atomically

    stale = tmp_path / ".projects-crashed.tmp"
    stale.write_bytes(b"half a file")
    an_hour_ago = time.time() - 2 * 3600
    os.utime(stale, (an_hour_ago, an_hour_ago))
    fresh = tmp_path / ".projects-in-flight.tmp"
    fresh.write_bytes(b"being written")
    other = tmp_path / ".settings-crashed.tmp"
    other.write_bytes(b"not this writer's")
    os.utime(other, (an_hour_ago, an_hour_ago))

    write_atomically(tmp_path / "projects.json", b"{}", prefix=".projects-")

    assert not stale.exists()
    assert fresh.exists()
    assert other.exists(), "another writer's leftover is its own to remove"


def test_a_first_write_makes_the_directories_it_created_durable(
    tmp_path: Path, monkeypatch
) -> None:
    """On a first run `prepare_config_dir` creates the config directory, and
    only the file's own directory was synced: the new directory's entry in its
    parent could be lost to a crash, taking the file with it. Each parent of a
    directory created here is synced too.

    Dies on syncing the file's directory alone.
    """
    import os

    from lwsm.configfile import write_atomically

    synced: list[str] = []
    real_fsync = os.fsync

    def recording(fd: int) -> None:
        synced.append(os.readlink(f"/proc/self/fd/{fd}"))
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", recording)
    target = tmp_path / "a" / "b" / "projects.json"

    write_atomically(target, b"{}", prefix=".projects-")

    for directory in (tmp_path, tmp_path / "a", tmp_path / "a" / "b"):
        assert str(directory) in synced, f"{directory} was not synced"
