"""LWSM-1006 — the Scanner's twenty invariants, and the conformance corpus.

Contract: `docs/specs/LWSM-1006-scanner-detection.md`. Every test here is named
in that spec's § 5 bullet or its § 11 table, except the cases moved in from
`docs/specs/LWSM-1006-conformance.py` — which the spec's Definition of done
requires, since two copies of the patterns would be two sources of truth.

Every test is headless (`testing.md § T6`) and none of them touches a real
service manager, a real project directory or a real port (`testing.md § T1`,
`§ T3`): the ports here are strings inside generated files, never bound.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
import signal
import stat
import time
from collections.abc import Callable
from pathlib import Path

import pytest

import lwsm
from lwsm import scanner
from lwsm.scanner import (
    Confidence,
    DetectedProject,
    LauncherKind,
    PortRule,
    ScanResult,
    rule_1,
    rule_2,
    strip_comment,
)
from scanner_fixtures import CORPUS, FakeUnits, build_tree, corpus_units

# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------


def line_port(line: str) -> int | None:
    """One line of a *file*, through the rules in their real order.

    The comment stripper lives here rather than inside the rules because
    `systemctl` property values are exempt from it (§ 4.6), so a rule that
    stripped its own input could not serve both callers.
    """
    text = strip_comment(line)
    found = rule_1(text)
    return found if found is not None else rule_2(text)


def scan_root(root: Path, units: object | None = None, **kwargs: object) -> ScanResult:
    """`scan()` over one root, with a unit lookup that reaches no systemd.

    Never `units=None`: that builds the real adapter, and a test that forgot to
    inject would shell out to the machine's own service manager (`testing.md
    § T1`).
    """
    return scanner.scan(
        [root], units=units if units is not None else FakeUnits(), **kwargs
    )


def by_name(result: ScanResult) -> dict[str, DetectedProject]:
    return {project.name: project for project in result.projects}


def make_project(
    root: Path, name: str, files: dict[str, str], *executable: str
) -> Path:
    base = root / name
    base.mkdir(parents=True)
    for relative, content in files.items():
        target = base / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    for relative in executable:
        (base / relative).chmod(0o755)
    return base


class Clock:
    """A monotonic clock that advances by a fixed step on every reading.

    Injected so INV-5 is deterministic rather than slow: nothing sleeps, and
    the budget expires after a known number of deadline checks.
    """

    def __init__(self, step: float) -> None:
        self.now = 0.0
        self.step = step

    def __call__(self) -> float:
        value = self.now
        self.now += self.step
        return value


@pytest.fixture(scope="session")
def corpus_tree(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The regression corpus, built once.

    `tmp_path_factory` and not `tmp_path`: the latter is function-scoped, so a
    session-scoped fixture requesting it raises `ScopeMismatch` at *collection*,
    which reads as a collection error rather than as a test failure.
    """
    return build_tree(tmp_path_factory.mktemp("scan_root"))


@pytest.fixture
def opened_paths(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Every path the scanner opens, recorded at its single opener."""
    seen: list[Path] = []
    real = scanner._open_source

    def spy(path: Path) -> int:
        seen.append(Path(path))
        return real(path)

    monkeypatch.setattr(scanner, "_open_source", spy)
    return seen


# --------------------------------------------------------------------------
# INV-9, INV-19 — the port rules, as pure functions
# --------------------------------------------------------------------------

RULE_1_FORMS: tuple[tuple[str, int | None], ...] = (
    ("PORT=8080", 8080),
    ("PORT=${PORT:-8080}", 8080),
    ("--port 5000", 5000),
    ("--port=5000", 5000),
    ("http://localhost:3000/", 3000),
    ("127.0.0.1:9999", 9999),
    ("export PORT=8080", 8080),
    ("TRANSPORT=99", None),
    ("EXPORT=5", None),
    ("APP_PORT=4321", None),
    ("SERVER_PORT = 3000", None),
    ("const viewport = 1280", None),
)

RULE_2_LINES: tuple[tuple[str, int | None], ...] = (
    ("PORT = 8765", 8765),
    ("DEFAULT_PORT = 4322", 4322),
    ("  'server_port': 5000", 5000),
    ('  "port": 5173', 5173),
    ("const PORT = Number(process.env.PROJECT_A_PORT) || 4321", 4321),
    ("export PORT=8080", 8080),
    ("const viewport = 1280", None),
    ("transport = 4", None),
    ("report: 7", None),
    ("export = 5", None),
)


@pytest.mark.parametrize(("line", "expected"), RULE_1_FORMS)
def test_port_rule_1_forms(line: str, expected: int | None) -> None:
    """§ 4.6's twelve lines. Rule 1 runs first, so its looseness costs more:
    an unanchored `PORT=` returns 99 for `TRANSPORT=99` and 4321 for
    `APP_PORT=4321`, which is INV-17's own fixture."""
    assert rule_1(line) == expected


@pytest.mark.parametrize(("line", "expected"), RULE_2_LINES)
def test_port_rule_2_keys(line: str, expected: int | None) -> None:
    """§ 4.6's ten-line table: a key must not merely *end in* `port`."""
    assert rule_2(line) == expected


def _literal_rule_2(line: str) -> int | None:
    """`design.md`'s wording — a key that merely **ends in** `port`.

    Kept as a second implementation on purpose (§ 4.6): the argument for the
    boundary rule stays an *output* of this suite rather than a transcription
    of a table someone may later edit.
    """
    for separator in ("=", ":"):
        left, found, right = line.partition(separator)
        if not found:
            continue
        key = left.strip().strip("'\"").rstrip("'\" \t")
        if not key.lower().endswith("port"):
            continue
        for digits in re.finditer(r"(?<![0-9-])\d{1,5}(?![0-9])", right):
            if scanner.PORT_RANGE[0] <= int(digits.group()) <= scanner.PORT_RANGE[1]:
                return int(digits.group())
    return None


@pytest.mark.parametrize(
    ("line", "literal"),
    [
        ("const viewport = 1280", 1280),
        ("transport = 4", 4),
        ("report: 7", 7),
        ("export = 5", 5),
    ],
)
def test_the_literal_ends_in_port_rule_would_accept_four_more(
    line: str, literal: int
) -> None:
    assert _literal_rule_2(line) == literal
    assert rule_2(line) is None


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("PORT=1", 1),
        ("PORT=65535", 65535),
        # 1-65535, not ADR-0005's 1024 floor: a project may declare 80.
        ("PORT=80", 80),
        ("port=8080", 8080),
        ("Port=8080", 8080),
        ("localhost:3000/health", 3000),
        ("port=${PORT:-8080}", 8080),
        ("--port ", None),
        ("PORT =8080", None),
        ("PORT=${APP_PORT:-8080}", None),
        ("PORT=8080 and --port 9090", 8080),
    ],
)
def test_port_rule_1_shapes_outside_the_table(line: str, expected: int | None) -> None:
    assert rule_1(line) == expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("PORT = auto", None),
        ("PORT8080 = x", None),
        ('opts = {"port": 5173}', 5173),
        # The `=` branch wins: `right` is the whole URL, whose first digits are
        # 8080. Partitioning `:` out of `=`'s left side would answer differently.
        ("PORT=http://localhost:8080", 8080),
        ("port=1234", 1234),
        ("PORT\t= 8080", 8080),
        ("server-port: 5000", 5000),
        ("APP_PORT=4321", 4321),
        ("server_port: 5000", 5000),
    ],
)
def test_port_rule_2_shapes_outside_the_table(line: str, expected: int | None) -> None:
    assert rule_2(line) == expected


@pytest.mark.parametrize(
    "line",
    [
        "PORT=123456",
        "--port 999999999",
        "localhost:1234567",
        "PORT=0",
        "PORT=65536",
        "--port 70000",
    ],
)
def test_rule_1_never_fabricates_a_port_from_a_longer_number(line: str) -> None:
    """`\\d{1,5}` alone does not *reject* a longer number, it takes the first
    five digits of one — `PORT=123456` returned 12345, which then passed the
    range check. The lookahead is the load-bearing half."""
    assert rule_1(line) is None


@pytest.mark.parametrize(
    "line", ["PORT = 123456", "port: 999999", "MY_PORT=70000", "PORT = 0"]
)
def test_rule_2_never_fabricates_a_port_from_a_longer_number(line: str) -> None:
    """Rule 2 needs the mirror-image guard for a reason rule 1 does not have:
    it *searches*, so an engine that cannot match at the first digit advances
    and matches the tail — ` 123456` returned 23456."""
    assert rule_2(line) is None


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("# PORT=9999 (old)", None),
        ("#  PORT=9999", None),
        ("// PORT = 9999", None),
        ("   # PORT=8080", None),
        ("PORT=8080  # was 9090", 8080),
        # `//` inside a URL is not a comment marker: a marker counts only at
        # line start or after whitespace, and without that single condition the
        # stripper eats `http://localhost:3000` and kills a rule-1 form.
        ("http://localhost:3000/", 3000),
        # `;` is a statement separator in every language this module reads, so
        # it is deliberately NOT a marker — all three of these keep their port.
        ("cd /app ; exec node serve.mjs --port 8080", 8080),
        ('"dev": "cd app ; vite --port 5173"', 5173),
        ("export FOO=1 ; PORT=9000", 9000),
        # Truncated at the quoted `#`, and harmlessly: the key left of the
        # separator is `NAME` either way. Asserting the line survives intact
        # would demand the quote-aware loop § 4.6 rejected.
        ('NAME = "a # b"', None),
        ('opts = {"port": 5173}  # dev', 5173),
    ],
)
def test_a_commented_out_port_is_not_detected(line: str, expected: int | None) -> None:
    assert line_port(line) == expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [("PORT = -1", None), ("PORT = 80.80", 80)],
)
def test_a_negative_number_is_not_a_port(line: str, expected: int | None) -> None:
    """`PORT = -1` returned 1, inventing a plausible port from a line that
    declares an impossible one. `PORT = 80.80` still yields 80, which is
    correct — the first whole number on the right is the declaration."""
    assert rule_2(line) == expected


@pytest.mark.parametrize(
    ("rule", "line", "expected"),
    [
        (rule_1, "localhost:99999 and PORT=8080", 8080),
        (rule_1, "localhost:99999", None),
        (rule_2, "'server_port': 70000, 'port': 5000", 5000),
        (rule_2, "PORT = 70000 5000", 5000),
        (rule_2, "PORT = 70000", None),
    ],
)
def test_an_out_of_range_match_does_not_end_the_scan(
    rule: Callable[[str], int | None], line: str, expected: int | None
) -> None:
    """`finditer`, not `search`: an out-of-range value is not a match and
    scanning resumes after it."""
    assert rule(line) == expected


def test_a_dependency_pair_is_kept_away_from_the_rules_by_scope_not_by_them() -> None:
    """`"get-port": "^7.0.0"` is a real npm package, and rule 2 reads port 7
    out of it. Nothing in the *rules* stops that — § 4.4 is what keeps the
    dependency block from ever being offered to them."""
    assert rule_2('"get-port": "^7.0.0"') == 7
    assert rule_2('"detect-port": "^1.5.1"') == 1


# --------------------------------------------------------------------------
# INV-15 — the matcher's cost at its own bound
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "line"),
    [
        (
            "key at the line cap",
            ("a" * 4088 + "port = 1")[: scanner.MAX_SOURCE_LINE_CHARS],
        ),
        (
            "102 colon fields",
            ":".join(["x" * 40] * 102)[: scanner.MAX_SOURCE_LINE_CHARS],
        ),
    ],
)
def test_the_port_matcher_does_not_backtrack(label: str, line: str) -> None:
    """A 1-second ceiling against measurements of 153 µs and 70 µs — a margin
    of thousands, so a machine slow enough to fail it honestly has a problem
    and a backtracking replacement fails by orders of magnitude.

    **The fixture must contain a separator.** An earlier one was
    `"a" * 4092 + "port"`, which has no `=` and no `:`, so `rule_2` returned
    after two `partition` calls and the regex never ran at all.
    """
    assert "=" in line or ":" in line, "without a separator the regex never runs"
    started = time.perf_counter()
    rule_2(line)
    assert time.perf_counter() - started < 1.0


# --------------------------------------------------------------------------
# § 4.4 step 3 — reading a port out of a unit's properties
# --------------------------------------------------------------------------


def test_the_environment_prefix_must_be_removed_before_the_rules_see_it() -> None:
    """Split with the prefix left on, the first token is
    `Environment=STATS_PORT=4321`: rule 2 partitions at the first `=` and gets
    the key `Environment`, while rule 1's `PORT=` is preceded by `_`. Neither
    matches, and `project-a` comes back *unknown*."""
    raw = "Environment=STATS_PORT=4321 STATS_REFRESH_HOURS=24"
    assert not any(line_port(token) for token in raw.split())
    value = raw.split("=", 1)[1]
    assert next(p for p in (line_port(t) for t in value.split()) if p) == 4321


def test_an_unsplit_environment_value_hides_a_port_that_is_not_first() -> None:
    """`partition` examines only the FIRST `KEY=` on a line, so a port is
    invisible whenever another variable precedes it — which is ordinary."""
    assert rule_2("STATS_PORT=4321 REFRESH=24") == 4321
    assert rule_2("REFRESH=24 STATS_PORT=4321") is None


def test_exec_start_is_a_record_and_only_its_argv_field_is_scanned() -> None:
    record = (
        "{ path=/usr/bin/node ; argv[]=/usr/bin/node serve.mjs --port 8080 ; pid=0 }"
    )
    argv = scanner._exec_start_argv(record)
    assert argv is not None
    assert rule_1(argv) == 8080
    # `path=` and `pid=` are systemctl's own keys, not the project's, so rule 2
    # is never run over the record.
    assert rule_2(record) is None


def test_a_property_value_is_exempt_from_the_comment_stripper() -> None:
    """The stripper is defined over the *lines of a file*; a `#` inside a
    command a property quotes is part of that command."""
    quoted = "argv[]=/bin/sh -c 'x --port 8080 # prod'"
    assert strip_comment(quoted) == "argv[]=/bin/sh -c 'x --port 8080"
    assert rule_1(quoted) == 8080


# --------------------------------------------------------------------------
# INV-8 — a unit name is untrusted input
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "valid"),
    [
        ("project-a.service", True),
        ("app@autostart.service", True),
        ("x.socket", True),
        ("app-ai\\x2dprompts\\x2dtray@autostart.service", True),
        ("--host=evil.example.service", False),
        ("-M.service", False),
        ("has space.service", False),
        ("x.mount", False),
        ("x.service\nevil.service", False),
    ],
)
def test_the_unit_name_validator_accepts_only_adr_0003_names(
    name: str, valid: bool
) -> None:
    """The escaped form is the only one `systemctl` accepts, and ADR-0003's
    class as written has no backslash — so a real escaped unit could never
    reach an argv and the unescaping step was dead code."""
    assert scanner._valid_unit_name(name) is valid


def test_the_unit_name_validator_bounds_length() -> None:
    """Asserted against the validator directly: `NAME_MAX` is 255, so no
    candidate directory can carry a 292-character stem and a `scan()`-level
    case would stay green with the `{1,255}` bound deleted."""
    assert scanner._valid_unit_name("a" * 250 + ".service") is True
    assert scanner._valid_unit_name("a" * 300 + ".service") is False


def test_the_show_argv_separates_options_from_the_name() -> None:
    """The argv is built inside the real adapter, which every other test
    replaces with a fake — so without calling the builder directly, an adapter
    shipping no separator at all would keep every parametrisation green."""
    argv = scanner._show_argv("x.service")
    assert argv[-2] == "--"
    assert argv[-1] == "x.service"
    assert all(index < len(argv) - 2 for index, arg in enumerate(argv) if arg == "-p")


@pytest.mark.parametrize(
    ("directory", "unit"),
    [
        ("-M", "-M.service"),
        ("has space", "has space.service"),
        ("mounty", "mounty.mount"),
    ],
    ids=["leading-dash", "embedded-space", "wrong-suffix"],
)
def test_a_hostile_unit_name_is_rejected(
    tmp_path: Path, directory: str, unit: str
) -> None:
    make_project(
        tmp_path, directory, {"start.sh": "#!/bin/sh\nexec true\n"}, "start.sh"
    )
    units = FakeUnits(
        units={
            unit: {
                "LoadState": "loaded",
                "FragmentPath": str(tmp_path / directory / unit),
            }
        }
    )

    result = scan_root(tmp_path, units)

    assert units.property_calls == [], "a rejected name reached an argv"
    assert by_name(result)[directory].kind is LauncherKind.SHELL


@pytest.mark.parametrize(
    ("escaped", "plain"),
    [
        (
            "app-ai\\x2dprompts\\x2dtray@autostart.service",
            "app-ai-prompts-tray@autostart.service",
        ),
        ("project-a.service", "project-a.service"),
    ],
)
def test_a_systemd_escaped_unit_name_is_unescaped_for_the_name_comparison(
    escaped: str, plain: str
) -> None:
    """Two different strings, and the spec has to say which is which:
    `systemctl` accepts only the escaped form, while step 1's comparison needs
    the unescaped one."""
    assert scanner._unescape_unit_name(escaped) == plain


# --------------------------------------------------------------------------
# INV-7 — a unit binds by location, never by name
# --------------------------------------------------------------------------


def test_a_name_match_alone_does_not_bind_a_unit(tmp_path: Path) -> None:
    """`mkdir <scan root>/project-a` — an empty directory with no code in it —
    must not put a row on screen whose Start and Stop drive somebody else's
    service."""
    make_project(
        tmp_path, "project-a", {"start.sh": "#!/bin/sh\nexec true\n"}, "start.sh"
    )
    units = FakeUnits(
        units={
            "project-a.service": {
                "LoadState": "loaded",
                "FragmentPath": "/etc/systemd/user/project-a.service",
                "WorkingDirectory": "",
            }
        }
    )

    result = scan_root(tmp_path, units)

    assert by_name(result)["project-a"].kind is LauncherKind.SHELL
    assert any("not bound to this directory" in reason for reason in result.skipped)


def test_an_absent_working_directory_is_never_resolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`Path("").resolve()` **is** the current working directory, so resolving
    an absent `WorkingDirectory` makes any name-matched unit bind whenever the
    manager was launched from inside a scan-root project — the attack the check
    exists to stop, arriving through the check itself."""
    candidate = make_project(
        tmp_path, "project-a", {"start.sh": "#!/bin/sh\nexec true\n"}, "start.sh"
    )
    monkeypatch.chdir(candidate)
    units = FakeUnits(
        units={
            "project-a.service": {
                "LoadState": "loaded",
                "FragmentPath": "",
                "WorkingDirectory": "",
            }
        }
    )

    result = scan_root(tmp_path, units)

    assert by_name(result)["project-a"].kind is LauncherKind.SHELL


@pytest.mark.parametrize(
    "prefix", ["", "-", "!"], ids=["bare", "ignore-if-missing", "privileged"]
)
def test_a_systemd_prefixed_working_directory_still_binds(
    tmp_path: Path, prefix: str
) -> None:
    """13 of the 14 real user units on this machine print a `!`-prefixed path.
    Unstripped, the containment check compares a path that cannot exist and
    nothing ever binds."""
    candidate = make_project(
        tmp_path, "project-a", {"serve.mjs": "const PORT = 9999\n"}
    )
    units = FakeUnits(
        units={
            "project-a.service": {
                "LoadState": "loaded",
                "FragmentPath": "",
                "WorkingDirectory": f"{prefix}{candidate}",
            }
        }
    )

    result = scan_root(tmp_path, units)

    assert by_name(result)["project-a"].kind is LauncherKind.SYSTEMD


def test_a_not_found_unit_is_not_confused_with_a_masked_one(tmp_path: Path) -> None:
    """Both exit 0, both print an empty `FragmentPath`, and both fall through to
    launcher rule 1 — so the **reason** is the single observable that separates
    them. Without the asymmetry this test passes against exactly the
    implementation it exists to reject."""
    make_project(tmp_path, "proj", {"start.sh": "#!/bin/sh\nexec true\n"}, "start.sh")

    def scan_with(load_state: str) -> ScanResult:
        units = FakeUnits(
            units={"proj.service": {"LoadState": load_state, "FragmentPath": ""}}
        )
        return scan_root(tmp_path, units)

    masked = scan_with("masked")
    not_found = scan_with("not-found")

    assert any("is masked" in reason for reason in masked.skipped)
    assert not any("proj.service" in reason for reason in not_found.skipped)
    for result in (masked, not_found):
        assert by_name(result)["proj"].kind is LauncherKind.SHELL


def test_a_systemd_project_takes_its_port_from_the_unit(corpus_tree: Path) -> None:
    """`project-a` holds a `serve.mjs` declaring 9999. Without that decoy this
    test passes against an implementation that ignores the unit entirely."""
    result = scan_root(corpus_tree, corpus_units(corpus_tree))

    project = by_name(result)["project-a"]
    assert project.kind is LauncherKind.SYSTEMD
    assert project.unit == "project-a.service"
    assert project.argv == ()
    assert project.port is not None
    assert project.port.port == 4321
    assert project.port.source == "the project-a.service unit"


def test_a_machine_with_no_systemd_scans_normally(tmp_path: Path) -> None:
    """§ 6: `OSError` from either call disables rule 0 for the whole scan and is
    recorded **once**, not once per candidate."""

    class Absent:
        def unit_names(self, timeout: float) -> list[str]:
            raise FileNotFoundError("systemctl")

        def properties(self, unit: str, names, timeout: float) -> dict[str, str]:
            raise AssertionError("rule 0 should be disabled")

    for name in ("one", "two"):
        make_project(tmp_path, name, {"serve.py": "PORT = 8000\n"})

    result = scan_root(tmp_path, Absent())

    assert len(by_name(result)) == 2
    assert sum("systemctl" in reason for reason in result.skipped) == 1


# --------------------------------------------------------------------------
# INV-3, INV-4 — reading somebody else's file
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reader", ["_read_bytes", "_read_lines"], ids=["bytes", "lines"]
)
def test_an_oversized_file_is_refused(tmp_path: Path, reader: str) -> None:
    fat = tmp_path / "start.sh"
    fat.write_bytes(b"x" * (scanner.MAX_SOURCE_FILE_BYTES + 1))
    deadline = scanner.Deadline(expires_at=time.monotonic() + 60, now=time.monotonic)

    with pytest.raises(OSError, match="too large"):
        if reader == "_read_bytes":
            scanner._read_bytes(fat)
        else:
            scanner._read_lines(fat, deadline)


def test_an_over_long_line_is_clipped_and_its_tail_not_scanned(tmp_path: Path) -> None:
    """A port declaration past character 4096 of one line is not a declaration
    anyone wrote on purpose — and the discarded remainder is what stops a
    pattern matching half of itself across a chunk boundary."""
    # A SPACE before `PORT`, and it is load-bearing. Without it the tail reads
    # `xxxPORT=9999`, which rule 1's left boundary rejects anyway — so the test
    # was green with the discard logic deleted, proving nothing (verified by
    # mutation, 2026-08-08).
    over = "x" * (scanner.MAX_SOURCE_LINE_CHARS + 100) + " PORT=9999"
    make_project(
        tmp_path, "proj", {"start.sh": f"#!/bin/sh\n{over}\nexec true\n"}, "start.sh"
    )

    result = scan_root(tmp_path)

    project = by_name(result)["proj"]
    assert project.port is None
    assert project.confidence is Confidence.UNKNOWN


def test_a_minified_package_json_is_still_parsed(tmp_path: Path) -> None:
    """A minified `package.json` with 300 devDependencies is 6,252 characters
    on one line. Under a single line-capped reader every one of them would be
    reported as malformed and its project silently dropped."""
    document = json.dumps(
        {
            "scripts": {"dev": "vite --port 5173"},
            "devDependencies": {f"p{index}": "^1.0.0" for index in range(300)},
        }
    )
    assert len(document) > scanner.MAX_SOURCE_LINE_CHARS
    assert "\n" not in document
    make_project(tmp_path, "proj", {"package.json": document})

    project = by_name(scan_root(tmp_path))["proj"]

    assert project.kind is LauncherKind.NODE
    assert project.port is not None
    assert project.port.port == 5173


class _Alarm(BaseException):
    """A `BaseException` so a bare `except Exception` in the code under test
    cannot swallow the guard protecting the assertion."""


def test_a_fifo_launcher_does_not_block(tmp_path: Path) -> None:
    """**The reason is the only observable that separates the two guards.**
    Opened `O_NONBLOCK`, a writer-less FIFO's `readline` returns `''` — EOF,
    not a block — so `O_NONBLOCK` alone satisfies "did not block" while the
    FIFO reads as an *empty file*, and the project is listed with no port
    instead of refused."""
    base = tmp_path / "proj"
    base.mkdir()
    os.mkfifo(base / "start.sh")
    (base / "start.sh").chmod(0o755)

    def fire(signum: int, frame: object) -> None:
        raise _Alarm("the FIFO blocked")

    previous = signal.signal(signal.SIGALRM, fire)
    signal.alarm(10)
    try:
        result = scan_root(tmp_path)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)

    assert "proj" not in by_name(result)
    assert any("not a regular file" in reason for reason in result.skipped)


def test_a_writer_less_fifo_reads_as_eof_not_as_a_block(tmp_path: Path) -> None:
    """The measurement the test above rests on, kept executable: this is why
    "did not block" is not evidence that the `S_ISREG` check exists."""
    fifo = tmp_path / "start.sh"
    os.mkfifo(fifo)
    descriptor = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
    try:
        assert stat.S_ISREG(os.fstat(descriptor).st_mode) is False
        with os.fdopen(descriptor, "r") as handle:
            assert handle.readline(scanner.MAX_SOURCE_LINE_CHARS) == ""
    except BaseException:
        os.close(descriptor)
        raise


@pytest.mark.parametrize(
    ("document", "raised"),
    [
        ("[" * 20000 + "]" * 20000, RecursionError),
        ("[1,2]", AttributeError),
    ],
    ids=["nested-arrays", "non-object-root"],
)
def test_the_package_json_failure_shapes_are_not_all_value_errors(
    document: str, raised: type[BaseException]
) -> None:
    """Three of `package.json`'s malformed shapes are not `JSONDecodeError`,
    and each would otherwise escape `scan()` as an unhandled exception. This
    pins *why* the parse names `RecursionError` separately."""
    with pytest.raises(raised):
        json.loads(document).get("scripts")
    assert not issubclass(RecursionError, ValueError)


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("nested arrays", "[" * 20000 + "]" * 20000),
        ("non-object root", "[1, 2]"),
        ("scripts is not an object", '{"scripts": 5}'),
        # Reached by rule 3's evidence scan, and the arm an earlier draft
        # missed: `"vite" in 5` raises TypeError, which is neither a
        # ValueError nor a RecursionError, so one hostile package.json took
        # every other project's row with it.
        (
            "dependencies is not an object",
            '{"scripts": {"dev": "vite"}, "dependencies": 5}',
        ),
        (
            "dev is present but invalid",
            '{"scripts": {"dev": "", "start": "node x.js"}}',
        ),
    ],
)
def test_a_hostile_package_json_never_escapes_the_scan(
    tmp_path: Path, name: str, content: str
) -> None:
    make_project(tmp_path, "hostile", {"package.json": content})
    make_project(tmp_path, "innocent", {"serve.py": "PORT = 8000\n"})

    result = scan_root(tmp_path)

    assert "innocent" in by_name(result), f"{name} deleted every other row"


def test_scripts_dev_present_but_invalid_falls_through_to_start(tmp_path: Path) -> None:
    """`dev` can be present and invalid — `""`, `null`, `{}` are all trivially
    plantable — and "dev, else start" alone admits two readings that produce
    two different launchers for the same file."""
    make_project(
        tmp_path,
        "proj",
        {"package.json": '{"scripts": {"dev": "", "start": "node x.js --port 4000"}}'},
    )

    project = by_name(scan_root(tmp_path))["proj"]

    assert project.argv == ("npm", "run", "start")
    assert project.port is not None
    assert project.port.port == 4000


def test_a_mojibake_file_is_a_non_match_not_an_error(tmp_path: Path) -> None:
    """§ 6: a binary `app.py` is not an error, it is a non-match."""
    base = tmp_path / "proj"
    base.mkdir()
    (base / "app.py").write_bytes(bytes(range(256)) * 10)

    project = by_name(scan_root(tmp_path))["proj"]

    assert project.kind is LauncherKind.PYTHON
    assert project.port is None


# --------------------------------------------------------------------------
# INV-1, INV-2, INV-20 — nothing outside the candidate is opened
# --------------------------------------------------------------------------


def test_a_hop_out_of_the_project_is_refused(
    tmp_path: Path, opened_paths: list[Path]
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    secret = tmp_path / "secret.py"
    secret.write_text("PORT = 1234\n", encoding="utf-8")
    make_project(
        root,
        "proj",
        {"start.sh": "#!/bin/sh\nexec python3 ../../secret.py\n"},
        "start.sh",
    )

    project = by_name(scan_root(root))["proj"]

    assert project.port is None
    assert secret.resolve() not in [path.resolve() for path in opened_paths]


def test_a_hop_token_holding_a_nul_byte_does_not_raise(tmp_path: Path) -> None:
    """`os.path.commonpath` accepts a NUL happily, and then `Path.resolve()` and
    `os.open()` both raise **`ValueError`** — not an `OSError`, so § 4.3's
    "any OSError rejects that file and continues" does not catch it."""
    make_project(
        tmp_path,
        "proj",
        {"start.sh": "#!/bin/sh\nexec python3 laun\x00cher.py\n"},
        "start.sh",
    )

    project = by_name(scan_root(tmp_path))["proj"]

    assert project.kind is LauncherKind.SHELL
    assert project.port is None


def test_a_symlinked_launcher_is_refused(tmp_path: Path) -> None:
    """A symlinked `start.sh` opens cleanly, `S_ISREG` returns `True` — it
    describes the *target* — and `os.access(X_OK)` does too. `O_NOFOLLOW` is
    the only guard that refuses it.

    The assertion is on the outside file's **port**, not on the opener: the
    recorded path would be `<project>/start.sh`, which resolves to the outside
    file whether or not it was ever read, so a path comparison there proves
    nothing either way.
    """
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.sh"
    outside.write_text("PORT=1234\n", encoding="utf-8")
    outside.chmod(0o755)
    base = root / "proj"
    base.mkdir()
    os.symlink(outside, base / "start.sh")

    result = scan_root(root)

    assert "proj" not in by_name(result)
    assert any("start.sh" in reason for reason in result.skipped)
    assert all(project.port is None for project in result.projects)


def test_a_refused_launcher_lets_the_remaining_rules_continue(tmp_path: Path) -> None:
    """Stopping at the first refused file would let anyone able to drop a
    symlink named `start.sh` into a project directory delete that project from
    the manager — a denial of service bought with one file."""
    outside = tmp_path / "outside.sh"
    outside.write_text("PORT=1234\n", encoding="utf-8")
    root = tmp_path / "root"
    root.mkdir()
    base = make_project(
        root, "proj", {"run.sh": "#!/bin/sh\nPORT=8080\nexec true\n"}, "run.sh"
    )
    os.symlink(outside, base / "start.sh")

    project = by_name(scan_root(root))["proj"]

    assert project.argv == ("./run.sh",)
    assert project.port is not None
    assert project.port.port == 8080


def test_a_symlinked_candidate_is_not_scanned(
    tmp_path: Path, opened_paths: list[Path]
) -> None:
    """`os.walk(followlinks=False)` declines to *descend* into a symlinked
    subdirectory but still lists it, and walking one as the top follows it — so
    `followlinks=False` is not the guard at candidate level."""
    root = tmp_path / "root"
    root.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "start.sh").write_text("PORT=1234\n", encoding="utf-8")
    (elsewhere / "start.sh").chmod(0o755)
    os.symlink(elsewhere, root / "proj")

    result = scan_root(root)

    assert result.projects == ()
    assert any("symlink" in reason for reason in result.skipped)
    assert not [path for path in opened_paths if "start.sh" in str(path)]


def test_nothing_inside_node_modules_is_read(
    tmp_path: Path, opened_paths: list[Path]
) -> None:
    """**The obvious fixture cannot see either constraint.** A `start.sh` that
    declares its own port ends the search file-major before the hop is ever
    resolved, so deleting constraints 3 and 4 leaves such a test green. Both
    fixtures here force the hop."""
    make_project(
        tmp_path,
        "excluded",
        {
            "start.sh": "#!/bin/sh\nexec python3 node_modules/pkg/serve.py\n",
            "node_modules/pkg/serve.py": "PORT = 7777\n",
        },
        "start.sh",
    )
    make_project(
        tmp_path,
        "deep",
        {
            "start.sh": "#!/bin/sh\nexec python3 a/b/c/d.py\n",
            "a/b/c/d.py": "PORT = 7778\n",
        },
        "start.sh",
    )

    found = by_name(scan_root(tmp_path))

    assert found["excluded"].port is None
    assert found["deep"].port is None
    assert not [path for path in opened_paths if "node_modules" in path.parts]


def test_a_hop_target_that_is_itself_a_symlink_is_refused_with_a_reason(
    tmp_path: Path,
) -> None:
    """Constraints 1-5 all pass for an in-project symlink whose target is also
    in-project, and `O_NOFOLLOW` would then refuse it unread — a rejection with
    no reason attached to the thing that caused it."""
    base = make_project(
        tmp_path,
        "proj",
        {
            "start.sh": "#!/bin/sh\nexec python3 launcher.py\n",
            "real.py": "PORT = 6060\n",
        },
        "start.sh",
    )
    os.symlink(base / "real.py", base / "launcher.py")

    result = scan_root(tmp_path)

    assert by_name(result)["proj"].port is None
    assert any("symlink" in reason for reason in result.skipped)


def test_an_unreadable_hop_target_is_escaped_and_clipped_like_its_neighbours(
    tmp_path: Path,
) -> None:
    """INV-18: *"Every reason and every `PortFinding.source` is escaped before it
    is clipped."* This reason was the last one interpolating a raw token, so a
    200-character name carrying `\\x1b` reached the app log and the status bar
    intact.

    A **directory** is the trigger: it passes all six of § 4.5's constraints and
    then fails § 4.3's `fstat`, which is the arm that reaches this line.

    The name is 200 characters, so the assertion reddens for `_quoted` being
    removed — watched failing that way. It does **not** redden for
    `MAX_REASON_CHARS` being raised (measured: 400 stays green), because it is
    expressed relative to that constant, which is known-issue-005's shape.
    `scanner`'s copy of the bound is pinned by nothing, unlike `registry`'s.
    """
    name = "\x1b" + "a" * 198 + "\x7f"
    base = make_project(
        tmp_path, "proj", {"start.sh": f"#!/bin/sh\nexec python3 {name}\n"}, "start.sh"
    )
    (base / name).mkdir()

    result = scan_root(tmp_path)

    assert by_name(result)["proj"].port is None
    reasons = [reason for reason in result.skipped if "cannot be read" in reason]
    assert len(reasons) == 1
    assert "\x1b" not in reasons[0]
    assert "\x7f" not in reasons[0]
    # 50 bounds the fixed text around the token — "cannot be read (…)" — which
    # no input can grow.
    assert len(reasons[0]) <= scanner.MAX_REASON_CHARS + 50


def test_a_script_that_execs_its_own_name_cannot_loop(tmp_path: Path) -> None:
    make_project(
        tmp_path, "proj", {"start.sh": "#!/bin/sh\nexec python3 start.sh\n"}, "start.sh"
    )

    assert by_name(scan_root(tmp_path))["proj"].port is None


@pytest.mark.parametrize(
    ("invocation", "expected"),
    [
        ("exec python3 -u launcher.py", "launcher.py"),
        # FOO, not PORT: `exec env PORT=1 …` is § 4.5's own example, but rule 1
        # would read a port off the launcher's own line and the hop would never
        # be reached — the test would pass without resolving anything.
        ("exec env FOO=1 python3 launcher.py", "launcher.py"),
        ("python3 -m http.server 8080", None),
        ('exec "$DIR/launcher.py"', None),
    ],
)
def test_the_hop_target_is_chosen_by_tokenise_and_select(
    tmp_path: Path, invocation: str, expected: str | None
) -> None:
    """Each of these resolves differently under "the token after the keyword":
    `python3`, `env` and `-m` respectively. This module does not expand shell
    variables and must not start."""
    make_project(
        tmp_path,
        "proj",
        {"start.sh": f"#!/bin/sh\n{invocation}\n", "launcher.py": "PORT = 6161\n"},
        "start.sh",
    )

    project = by_name(scan_root(tmp_path))["proj"]

    assert project.port is None if expected is None else project.port.port == 6161


def test_the_last_invocation_wins_and_a_commented_one_is_not_it(tmp_path: Path) -> None:
    """A script ending `exec python3 new.py` / `# exec python3 old.py (kept for
    reference)` resolves to `old.py` unstripped and `new.py` stripped."""
    make_project(
        tmp_path,
        "proj",
        {
            "start.sh": "#!/bin/sh\nexec python3 new.py\n"
            "# exec python3 old.py (kept)\n",
            "new.py": "PORT = 3131\n",
            "old.py": "PORT = 9191\n",
        },
        "start.sh",
    )

    project = by_name(scan_root(tmp_path))["proj"]

    assert project.port is not None
    assert project.port.port == 3131


@pytest.mark.parametrize(
    "invocation",
    [
        "exec python3 app.py",
        "exec python3 app.py >> /var/log/app.log",
        "exec python3 app.py --cfg ../shared/conf.ini",
        "exec python3 app.py --cfg node_modules/x/c.json",
    ],
    ids=["control", "log redirect", "outside the project", "excluded directory"],
)
def test_a_refused_token_falls_back_to_the_one_before_it(
    tmp_path: Path, invocation: str
) -> None:
    """§ 4.5 step 4 takes the **last** token that satisfies the six constraints,
    which is not the same as *the last token* — a refused one is one token that
    failed, not the end of the search.

    **The control is what isolates the abort as the only difference**: all four
    lines name `app.py`, and three of them ended in silent under-detection
    because the trailing token was refused. A redirect on the `exec` line is
    ordinary in real launchers.

    INV-20's depth fixture (`exec python3 a/b/c/d.py`) is a single token and
    cannot see this, which is how it survived seven review loops.
    """
    make_project(
        tmp_path,
        "proj",
        {"start.sh": f"#!/bin/sh\n{invocation}\n", "app.py": "PORT = 8123\n"},
        "start.sh",
    )

    project = by_name(scan_root(tmp_path))["proj"]

    assert project.port is not None, invocation
    assert project.port.port == 8123


def test_a_line_whose_every_token_is_refused_still_records_a_reason(
    tmp_path: Path,
) -> None:
    """Falling back must not turn a refusal into silence: with no acceptable
    token anywhere on the line the port is unknown **and** the reason names the
    token that was refused."""
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "secret.py").write_text("PORT = 1234\n", encoding="utf-8")
    make_project(
        root,
        "proj",
        {"start.sh": "#!/bin/sh\nexec python3 ../../secret.py\n"},
        "start.sh",
    )

    result = scan_root(root)

    assert by_name(result)["proj"].port is None
    assert any("secret.py" in reason for reason in result.skipped)


# --------------------------------------------------------------------------
# INV-6, INV-10, INV-11, INV-12 — what the Scanner returns
# --------------------------------------------------------------------------

EVERY_MARKER: dict[str, str] = {
    "start.sh": "#!/bin/sh\nexec true\n",
    "package.json": '{"scripts": {"dev": "vite"}}',
    "serve.py": "print('hi')\n",
    "serve.mjs": "console.log('hi')\n",
}


@pytest.mark.parametrize(
    ("drop", "kind", "argv"),
    [
        ((), LauncherKind.SYSTEMD, ()),
        ((), LauncherKind.SHELL, ("./start.sh",)),
        (("start.sh",), LauncherKind.NODE, ("npm", "run", "dev")),
        (("start.sh", "package.json"), LauncherKind.PYTHON, ("python3", "serve.py")),
        (
            ("start.sh", "package.json", "serve.py"),
            LauncherKind.NODE,
            ("node", "serve.mjs"),
        ),
    ],
    ids=["rule-0", "rule-1", "rule-2", "rule-3", "rule-4"],
)
def test_launcher_precedence(
    tmp_path: Path, drop: tuple[str, ...], kind: LauncherKind, argv: tuple[str, ...]
) -> None:
    """Each project carries every lower-precedence marker as well, so a rule
    that fired out of order is visible rather than merely possible."""
    files = {name: body for name, body in EVERY_MARKER.items() if name not in drop}
    candidate = make_project(
        tmp_path, "proj", files, *(["start.sh"] if "start.sh" in files else [])
    )
    units = FakeUnits()
    if kind is LauncherKind.SYSTEMD:
        units = FakeUnits(
            units={
                "proj.service": {
                    "LoadState": "loaded",
                    "FragmentPath": str(candidate / "proj.service"),
                }
            }
        )

    project = by_name(scan_root(tmp_path, units))["proj"]

    assert project.kind is kind
    assert project.argv == argv


def test_a_candidate_with_no_launcher_is_not_listed(tmp_path: Path) -> None:
    make_project(tmp_path, "notes", {"README.md": "PORT=8080\n"})

    result = scan_root(tmp_path)

    assert result.projects == ()
    assert any("no launcher" in reason for reason in result.skipped)


def test_argv_names_the_alternate_that_actually_matched(tmp_path: Path) -> None:
    """`argv` names whichever alternate matched, not the preferred one — the
    § 4.4 table's column shows the preferred alternate as an example."""
    make_project(tmp_path, "shell", {"run.sh": "#!/bin/sh\nexec true\n"}, "run.sh")
    make_project(tmp_path, "node", {"package.json": '{"scripts": {"start": "node x"}}'})
    make_project(tmp_path, "python", {"app.py": "print('hi')\n"})
    make_project(tmp_path, "mjs", {"serve.js": "console.log(1)\n"})

    found = by_name(scan_root(tmp_path))

    assert found["shell"].argv == ("./run.sh",)
    assert found["node"].argv == ("npm", "run", "start")
    assert found["python"].argv == ("python3", "app.py")
    assert found["mjs"].argv == ("node", "serve.js")


def test_the_launcher_outranks_the_hop_file(tmp_path: Path) -> None:
    """**The fixture line is load-bearing.** `PORT_BASE = 3000` was tried first
    and could not discriminate: rule 1 and rule 2 both return `None` for it, so
    both orderings returned 8080. `SERVER_PORT = 3000` returns 3000 under rule
    2 and `None` under rule 1, which is exactly the shape that separates
    file-major from rule-major."""
    make_project(
        tmp_path,
        "proj",
        {
            "start.sh": "#!/bin/sh\nSERVER_PORT = 3000\nexec python3 launcher.py\n",
            "launcher.py": "--port 8080\n",
        },
        "start.sh",
    )

    project = by_name(scan_root(tmp_path))["proj"]

    assert project.port is not None
    assert project.port.port == 3000, "rule-major would return 8080"


def test_within_one_source_the_scan_is_line_major(tmp_path: Path) -> None:
    """Proximity to the top of the file beats rule precedence, because a
    declaration near the top is the one a human reads as authoritative."""
    make_project(
        tmp_path,
        "proj",
        {"start.sh": "#!/bin/sh\nSERVER_PORT = 3000\nexec node serve.js --port 8080\n"},
        "start.sh",
    )

    project = by_name(scan_root(tmp_path))["proj"]

    assert project.port is not None
    assert project.port.port == 3000


@pytest.mark.parametrize(
    ("files", "executable", "rule", "source", "port"),
    [
        (
            {"start.sh": "#!/bin/sh\nPORT=8080\nexec true\n"},
            ("start.sh",),
            PortRule.EXPLICIT,
            "start.sh",
            8080,
        ),
        ({"serve.py": "PORT = 8765\n"}, (), PortRule.ASSIGNMENT, "serve.py", 8765),
        (
            {"serve.py": "import flask\n"},
            (),
            PortRule.FRAMEWORK_DEFAULT,
            "Flask",
            5000,
        ),
        (
            {
                "start.sh": "#!/bin/sh\nexec python3 lib/launcher.py\n",
                "lib/launcher.py": "PORT = 5055\n",
            },
            ("start.sh",),
            PortRule.ASSIGNMENT,
            "lib/launcher.py",
            5055,
        ),
    ],
    ids=["explicit", "assignment", "framework", "one-hop"],
)
def test_a_finding_reports_the_rule_that_matched(
    tmp_path: Path,
    files: dict[str, str],
    executable: tuple[str, ...],
    rule: PortRule,
    source: str,
    port: int,
) -> None:
    """**Asserting mere presence would be a tautology** — `PortFinding` is a
    frozen dataclass whose `rule` and `source` are required. The one-hop case
    is the only one that proves `source` names the file actually read."""
    make_project(tmp_path, "proj", files, *executable)

    found = by_name(scan_root(tmp_path))["proj"].port

    assert found is not None
    assert (found.port, found.rule, found.source) == (port, rule, source)


def test_project_e_shape_comes_back_unknown(corpus_tree: Path) -> None:
    """Exactly one hop is followed. `project-e` puts its port two hops out and
    is expected back as *port unknown*, which is an honest limit rather than a
    bug — and a rule that quietly starts guessing for it is the regression this
    corpus exists to catch."""
    project = by_name(scan_root(corpus_tree, corpus_units(corpus_tree)))["project-e"]

    assert project.port is None
    assert project.confidence is Confidence.UNKNOWN


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        ({"package.json": '{"scripts": {"dev": "vite"}}'}, 5173),
        (
            {
                "package.json": '{"scripts": {"dev": "x"},'
                ' "devDependencies": {"vite": "^5"}}'
            },
            5173,
        ),
        (
            {
                "package.json": '{"scripts": {"dev": "x"},'
                ' "devDependencies": {"vitest": "^2"}}'
            },
            None,
        ),
        # The script-value half is whole-word too, and this is the case that
        # settled it: a bare substring reports a test runner as a Vite server.
        ({"package.json": '{"scripts": {"dev": "vitest"}}'}, None),
        (
            {"package.json": '{"scripts": {"dev": "./node_modules/.bin/vite --host"}}'},
            5173,
        ),
        ({"serve.py": "import django\n"}, 8000),
        ({"serve.py": "print(1)\n", "manage.py": "print(1)\n"}, 8000),
        ({"serve.py": "import flask\n"}, 5000),
        ({"serve.py": "import flask_login\n"}, None),
        # A `serve.mjs` identifies no framework, so a stray `manage.py` beside
        # a Node server must not fabricate 8000 for it.
        ({"serve.mjs": "console.log(1)\n", "manage.py": "print(1)\n"}, None),
    ],
    ids=[
        "vite-script",
        "vite-key",
        "vitest-key",
        "vitest-script",
        "vite-binary-path",
        "django-import",
        "django-manage",
        "flask",
        "flask-login",
        "node-with-manage",
    ],
)
def test_a_framework_default_needs_evidence_the_launcher_can_reach(
    tmp_path: Path, files: dict[str, str], expected: int | None
) -> None:
    """Every evidence test is exact or whole-word, never a substring: `vitest`
    and `@vitejs/plugin-react` both contain `vite`, and `import flask_login`
    contains `import flask`."""
    make_project(tmp_path, "proj", files)

    found = by_name(scan_root(tmp_path))["proj"].port

    assert (found.port if found else None) == expected


def test_a_shell_project_reaches_framework_evidence_only_through_a_py_hop(
    tmp_path: Path,
) -> None:
    """A `start.sh` reading `exec node serve.mjs`, with a stray `manage.py`
    beside it, reached Django's 8000: a Python default fabricated for a project
    that runs no Python."""
    make_project(
        tmp_path,
        "node-wrapper",
        {"start.sh": "#!/bin/sh\nexec node serve.mjs\n", "manage.py": "print(1)\n"},
        "start.sh",
    )
    make_project(
        tmp_path,
        "python-wrapper",
        {
            "start.sh": "#!/bin/sh\nexec python3 launcher.py\n",
            "launcher.py": "import django\n",
        },
        "start.sh",
    )

    found = by_name(scan_root(tmp_path))

    assert found["node-wrapper"].port is None
    assert found["python-wrapper"].port is not None
    assert found["python-wrapper"].port.port == 8000


def test_a_detected_project_has_no_user_owned_field() -> None:
    """A merge that wanted to promote scanned content into an executable action
    would have to add the field first, which is a visible change rather than a
    forgotten one."""
    allowed = {"path", "name", "kind", "argv", "unit", "port"}

    assert {field.name for field in dataclasses.fields(DetectedProject)} == allowed


# --------------------------------------------------------------------------
# INV-2, INV-5, INV-13, INV-16, INV-18 — candidates, budget, and the tree
# --------------------------------------------------------------------------


def test_the_app_does_not_detect_itself(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**The launcher in the fixture is what makes this falsifiable.** Without
    it the candidate matches no launcher rule, so rejection 5 already keeps it
    out and the test stays green with the self-exclusion guard deleted."""
    base = make_project(
        tmp_path,
        "checkout",
        {"start.sh": "#!/bin/sh\nPORT=8080\nexec true\n", "src/lwsm/__init__.py": ""},
        "start.sh",
    )
    monkeypatch.setattr(lwsm, "__file__", str(base / "src" / "lwsm" / "__init__.py"))

    result = scan_root(tmp_path)

    assert result.projects == ()
    assert any("own directory" in reason for reason in result.skipped)


def test_the_same_directory_reached_twice_is_listed_once(tmp_path: Path) -> None:
    """Two scan roots may overlap, or one may sit inside another. ADR-0005
    makes the absolute path the identity, so two records sharing one is a
    malformed result rather than a merge question."""
    root = tmp_path / "root"
    root.mkdir()
    make_project(root, "proj", {"serve.py": "PORT = 8000\n"})

    result = scanner.scan([root, root], units=FakeUnits())

    assert len(result.projects) == 1
    assert any("already" in reason for reason in result.skipped)


def test_a_missing_scan_root_does_not_blank_the_result(tmp_path: Path) -> None:
    """A missing root is ordinary — an unmounted drive — and must not blank the
    result."""
    good = tmp_path / "good"
    good.mkdir()
    make_project(good, "proj", {"serve.py": "PORT = 8000\n"})

    result = scanner.scan([tmp_path / "gone", good], units=FakeUnits())

    assert len(result.projects) == 1
    assert any("gone" in reason for reason in result.skipped)


def _plant_unreadable_directory(root: Path) -> str:
    """A candidate the scanner may list but may not enter.

    Needs no attacker: a root-owned or another user's directory under a scan
    root has this shape. Reaches `Path.exists` / `is_file`, which re-raise
    `EACCES` on 3.13 — `pathlib` swallows only `ENOENT/ENOTDIR/EBADF/ELOOP`.
    """
    if os.geteuid() == 0:
        pytest.skip("root ignores directory permissions, so 0o000 plants nothing")
    base = make_project(root, "aaa-hostile", {"serve.py": "PORT = 8000\n"})
    base.chmod(0o000)
    return "aaa-hostile"


def _plant_long_hop_token(root: Path) -> str:
    """An attacker-authored launcher whose hop token exceeds `NAME_MAX`.

    One line in one file under a scan root: `MAX_SOURCE_LINE_CHARS` is 4096 and
    `NAME_MAX` is 255. Reaches `Path.is_symlink` in `_accept_hop`, a different
    line from the one above, which is why both triggers are carried here.
    """
    make_project(
        root,
        "aaa-hostile",
        {"start.sh": "#!/bin/sh\nexec python3 " + "a" * 3000 + "\n"},
        "start.sh",
    )
    return "aaa-hostile"


@pytest.mark.parametrize(
    "plant",
    [_plant_unreadable_directory, _plant_long_hop_token],
    ids=["unreadable directory", "hop token longer than NAME_MAX"],
)
def test_one_hostile_candidate_does_not_destroy_the_whole_scan(
    tmp_path: Path, plant: Callable[[Path], str]
) -> None:
    """§ 4.3: *"Any `OSError` rejects that file with a reason and continues. A
    permission denial on one project is not a failure of the scan."*

    The hostile candidate sorts **first**, so a scan that gives up on it loses
    every project behind it — which is what shipped: `scan()` caught only
    `_BudgetExpired`, so the caller got no `ScanResult` at all.
    """
    hostile = plant(tmp_path)
    for index in range(3):
        make_project(tmp_path, f"good-{index}", {"serve.py": "PORT = 8000\n"})

    try:
        result = scan_root(tmp_path)
    finally:
        (tmp_path / hostile).chmod(0o700)

    assert sorted(by_name(result)) == ["good-0", "good-1", "good-2"]
    assert any(hostile in reason for reason in result.skipped)


def test_the_budget_stops_a_scan_mid_candidate(corpus_tree: Path) -> None:
    """The deadline is checked before each candidate **and, inside a file read,
    before each line** — a wall-clock check between files cannot interrupt work
    already under way."""
    clock = Clock(step=0.1)

    result = scanner.scan(
        [corpus_tree],
        units=corpus_units(corpus_tree),
        now=clock,
        budget_seconds=0.5,
    )

    assert result.timed_out is True
    assert len(result.projects) < len(CORPUS)


def test_a_scan_within_its_budget_does_not_claim_a_timeout(corpus_tree: Path) -> None:
    """`timed_out` means *the scan deadline expired*, never *a subprocess was
    slow* — so a clean run must not set it."""
    assert scan_root(corpus_tree, corpus_units(corpus_tree)).timed_out is False


def _snapshot(root: Path) -> dict[str, tuple[str, int, int]]:
    """`(sha256, mtime_ns, mode)` per path — the hash and not just the size,
    because a same-length overwrite is exactly the mutation a size comparison
    cannot see."""
    found: dict[str, tuple[str, int, int]] = {}
    for directory, _dirnames, filenames in os.walk(root):
        for name in filenames:
            path = Path(directory) / name
            info = path.lstat()
            digest = (
                hashlib.sha256(path.read_bytes()).hexdigest()
                if stat.S_ISREG(info.st_mode)
                else ""
            )
            found[str(path.relative_to(root))] = (
                digest,
                info.st_mtime_ns,
                info.st_mode,
            )
    return found


def test_a_scan_leaves_the_tree_untouched(corpus_tree: Path) -> None:
    before = _snapshot(corpus_tree)

    scan_root(corpus_tree, corpus_units(corpus_tree))

    assert _snapshot(corpus_tree) == before


def test_the_reason_list_is_capped_and_says_so(tmp_path: Path) -> None:
    """**The suppressed-count entry is asserted separately from the cap**,
    because a cap with no tail reads exactly like completeness."""
    unusable = scanner.MAX_SKIP_REASONS * 3
    for index in range(unusable):
        (tmp_path / f"empty-{index:04d}").mkdir()

    result = scan_root(tmp_path)

    assert len(result.skipped) == scanner.MAX_SKIP_REASONS + 1
    assert result.skipped[-1] == (
        f"and {unusable - scanner.MAX_SKIP_REASONS} more problems, not shown"
    )


def test_the_suppressed_count_is_absent_when_nothing_was_suppressed(
    tmp_path: Path,
) -> None:
    (tmp_path / "empty").mkdir()

    result = scan_root(tmp_path)

    assert len(result.skipped) == 1
    assert "not shown" not in result.skipped[0]


def test_a_newline_in_a_directory_name_cannot_forge_a_log_record(
    tmp_path: Path,
) -> None:
    """A Linux filename may contain a newline, which is the forged-log-record
    defect LWSM-1078 closed — and it arrives by **two** paths: the reason for a
    rejected candidate, and `DetectedProject.name` for one that survives
    detection."""
    forged = "evil\nPORT=1 detected"
    (tmp_path / forged).mkdir()
    make_project(tmp_path, f"{forged}-live", {"serve.py": "PORT = 8000\n"})

    result = scan_root(tmp_path)

    assert result.skipped
    assert not any("\n" in reason for reason in result.skipped)
    assert not any("\n" in project.name for project in result.projects)


def test_a_reason_is_clipped_as_well_as_escaped(tmp_path: Path) -> None:
    """Clipping bounds how *long* each reason is; `MAX_SKIP_REASONS` bounds how
    many. `registry.py` shipped the first and needed LWSM-1115 for the second."""
    (tmp_path / ("n" * 200)).mkdir()

    result = scan_root(tmp_path)

    assert all(len(reason) < scanner.MAX_REASON_CHARS + 60 for reason in result.skipped)


def test_a_display_name_is_clipped(tmp_path: Path) -> None:
    # 200 and not more: `NAME_MAX` is 255 on this filesystem, so a longer
    # directory name cannot be created at all and the test would measure
    # `mkdir` rather than the clip.
    make_project(tmp_path, "n" * 200, {"serve.py": "PORT = 8000\n"})

    result = scan_root(tmp_path)

    assert len(result.projects[0].name) == scanner.MAX_DISPLAY_NAME_CHARS


# --------------------------------------------------------------------------
# The acceptance test the roadmap names
# --------------------------------------------------------------------------


@pytest.mark.parametrize("fixture", CORPUS, ids=[project.name for project in CORPUS])
def test_every_fixture_project_is_detected_as_expected(
    corpus_tree: Path, fixture: object
) -> None:
    """Named for the corpus rather than for seven, since the tree already holds
    more and grows with every mis-detection. Asserts launcher **and** port,
    including the *unknown* cases."""
    result = scan_root(corpus_tree, corpus_units(corpus_tree))

    project = by_name(result).get(fixture.name)
    assert project is not None, f"{fixture.name} was not detected ({fixture.why})"
    assert project.path == (corpus_tree / fixture.name).resolve()
    assert project.kind is fixture.kind
    assert project.argv == fixture.argv
    assert project.unit == fixture.unit
    if fixture.port is None:
        assert project.port is None, fixture.why
        assert project.confidence is Confidence.UNKNOWN
    else:
        assert project.port is not None, fixture.why
        assert (project.port.port, project.port.rule, project.port.source) == (
            fixture.port,
            fixture.rule,
            fixture.source,
        )
        assert project.confidence is Confidence.DETECTED
