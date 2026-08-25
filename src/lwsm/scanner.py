"""Detect projects, their launchers and their declared ports.

Core module — no Qt at all, not even QtCore (`docs/standards/coding.md § O1`),
matching `ports.py`, because nothing here emits a signal. Contract:
`docs/specs/LWSM-1006-scanner-detection.md`.

Everything this module reads belongs to somebody else, so it ships the bounds
that make reading it safe (LWSM-1050): a per-file byte cap, a per-line cap, a
per-line deadline, symlink refusal at both the candidate and the file level, a
non-regular refusal, and a containment check on the one file a launcher names.

Where a project says nothing about its port, it comes back honestly *unknown*.
`PortFinding` is never a guess.
"""

from __future__ import annotations

import enum
import errno
import json
import os
import re
import stat
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import lwsm
from lwsm.registry import DECLARED_PORT_RANGE, LauncherKind

# Re-exported deliberately. `LauncherKind` moved to `registry.py` with LWSM-1007
# because the loader has to validate against it at run time, and this module
# already imported from there — adding the reverse import would have closed a
# cycle that stops the package importing at all. Every consumer still spells it
# `scanner.LauncherKind`, and `__all__` keeps ruff from calling the import
# unused.
__all__ = ["LauncherKind"]

# 256 KB for a sibling's source, against `registry.py`'s 1 MiB for a config
# file this app owns. Named MAX_SOURCE_* rather than reusing that constant
# because they are different numbers for different jobs, and one name for two
# values is the ambiguity `documentation.md § 1.5` bans.
MAX_SOURCE_FILE_BYTES = 256 * 1024
MAX_SOURCE_LINE_CHARS = 4096

# A rejection reason reaches the app log and the status bar, and the name in it
# is a scan-root subdirectory name — attacker-supplied, and a Linux filename may
# contain a newline. Same name and value as `registry.py::MAX_REASON_CHARS`,
# since it bounds the same thing for the same reason.
MAX_REASON_CHARS = 120

# A separate constant because it bounds a *display* string under a different
# sanitiser: `name` reaches the UI as a row label, so `repr`'s escaping would
# put a project on screen literally named `'my project'`, quotes included.
MAX_DISPLAY_NAME_CHARS = 120

# Clipping each reason bounds how LONG they are and nothing bounds how MANY.
# `registry.py` shipped the first half and needed LWSM-1115 for the second,
# after a file at its size cap produced 524,271 reasons. A scan root with a
# large subdirectory count reaches the same shape by a different road.
#
# The same value as `registry.py::MAX_REASONS` and deliberately not shared: the
# two bound different populations — hand-edited records in one file against
# subdirectories on disk — so they will move independently.
MAX_SKIP_REASONS = 100

# Checked before each candidate and, inside a file read, before each line. A
# wall-clock check between files cannot interrupt work already under way.
SCAN_BUDGET_SECONDS = 20.0

# `systemctl`'s OWN budget, not the scan's. Drawing it from the scan deadline
# would let one hung call consume all 20 seconds and set `timed_out`, which
# contradicts § 6's promise that a systemd-less machine scans normally: a scan
# cannot both carry on normally and be out of time.
SYSTEMCTL_TIMEOUT_SECONDS = 2.0

# `design.md`'s exclusion list and depth bound, applied at the only place this
# item still reads a file below the project root (§ 4.5 constraints 3 and 4).
EXCLUDED_DIR_NAMES = frozenset(
    {"node_modules", ".git", ".venv", "venv", "__pycache__", "dist", "build", ".cache"}
)
MAX_HOP_DEPTH = 3

# How many relative imports of one launcher are followed (§ 4.5, LWSM-1155).
# Measured 2026-08-20 against the project that motivated the rule: its
# `serve.mjs` carries eight imports, of which five are bare (`node:http`,
# `node:fs/promises`, ...) and **three** are relative — and the port is in the
# third. So the bound has to clear 3, and this is a shade under 3x that. The
# `Deadline` bounds the total work either way; this bounds the work ONE hostile
# launcher can demand, which the deadline can only do by spending the whole
# scan's budget on it and degrading every other candidate's row.
MAX_IMPORT_HOPS = 8

# The *declared* range, not ADR-0005's 1024-65535, which governs the override
# the user types. A project may legitimately declare 80.
PORT_RANGE = DECLARED_PORT_RANGE


class PortRule(enum.Enum):
    """Which rule produced a port. The value is what the UI shows."""

    EXPLICIT = "an explicit port setting"  # port rule 1
    ASSIGNMENT = "a port assignment"  # port rule 2
    FRAMEWORK_DEFAULT = "a framework default"  # port rule 3


class Confidence(enum.Enum):
    DETECTED = "detected"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PortFinding:
    """Where a port came from, without the bytes it came from.

    An earlier draft carried the matched line, and it was the one string in this
    design that took a hostile file's bytes to the log and the status bar — the
    defect LWSM-1078, LWSM-1102 and LWSM-1114 each closed at one call site. The
    rule plus the source is the whole of the provenance the UI needs, so the
    field was deleted rather than defended.
    """

    port: int
    rule: PortRule
    source: str


@dataclass(frozen=True)
class DetectedProject:
    """One project the Scanner is willing to list.

    **No `actions` field and no user-owned field of any kind.** That is the
    structural half of `design.md § Custom project actions`'s rule that
    detection never authors an executable action: a merge that wanted to promote
    scanned content into an executable one would have to add the field first,
    which is a visible change rather than a forgotten one.
    """

    path: Path  # RESOLVED, absolute; the identity (ADR-0005)
    name: str
    kind: LauncherKind
    argv: tuple[str, ...]  # empty for SYSTEMD; the unit drives it
    unit: str | None
    port: PortFinding | None  # None means "unknown", never a guess

    @property
    def confidence(self) -> Confidence:
        """Derived, never stored: two fields able to disagree is the shape
        `coding.md § O5` exists to prevent."""
        return Confidence.UNKNOWN if self.port is None else Confidence.DETECTED


@dataclass(frozen=True)
class ScanResult:
    projects: tuple[DetectedProject, ...]
    skipped: tuple[str, ...]
    timed_out: bool  # the budget expired; `projects` is partial

    # Roots `os.scandir` refused. A separate field rather than a reading of
    # `skipped`, because those are two different kinds of thing (LWSM-1131
    # § 4.3): a per-entry skip — "is not a directory", "no launcher matched" —
    # means the scanner LOOKED at something and rejected it, which is evidence.
    # A root that could not be listed means an unknown number of projects were
    # never seen at all, and only that may suppress the merge's *missing* check.
    #
    # `skipped` is `tuple[str, ...]`, so one stray file in a scan root makes it
    # non-empty: a merge reading it as a blanket signal would never flag anything
    # missing on any populated machine, while a clean fixture passed.
    unlistable_roots: tuple[Path, ...] = ()


@dataclass(slots=True)
class Deadline:
    """The scan's budget as one value, threaded into every read.

    `now` is injected so the budget test is deterministic rather than slow.
    """

    expires_at: float
    now: Callable[[], float]

    def expired(self) -> bool:
        return self.now() >= self.expires_at

    def remaining(self) -> float:
        return max(0.0, self.expires_at - self.now())


class SupportsUnitLookup(Protocol):
    """The systemd surface, injected so `testing.md § T1` holds.

    Both calls are bounded by the scan's own deadline. `OSError` is the ONLY
    exception this Protocol may raise, and the real adapter is responsible for
    making that true — it **translates every other failure mode into one**.
    Three of them are not `OSError` subclasses and each would otherwise escape
    `scan()`: `subprocess.TimeoutExpired`, `subprocess.CalledProcessError` (with
    no user D-Bus session `systemctl --user` exits 1 with empty stdout), and the
    `json.JSONDecodeError` that parsing that empty stdout raises.
    """

    def unit_names(self, timeout: float) -> list[str]: ...

    def properties(
        self, unit: str, names: Sequence[str], timeout: float
    ) -> dict[str, str]:
        """TOTAL over `names`: every one is a key, absent ones map to "".

        Without that, `props["WorkingDirectory"]` on a unit that sets none
        raises `KeyError` — not an `OSError`, so the clause above does not catch
        it and it escapes `scan()`, taking every other project's row with it.
        """
        ...


class _BudgetExpired(Exception):
    """The scan deadline expired mid-read. Deliberately not an `OSError`: the
    candidate in progress is abandoned rather than rejected, because reporting
    what was read so far would hand the caller an honest-looking *unknown* the
    project never earned — and LWSM-1007 is about to persist that list."""


# --------------------------------------------------------------------------
# Turning somebody else's bytes into strings we are willing to show
# --------------------------------------------------------------------------

# Surrogates belong in this class as much as C0 and C1 do: `os.scandir` returns
# a name that is not valid UTF-8 as lone surrogates in \udc80-\udcff through
# `surrogateescape`, and a `str` holding one cannot be encoded back to UTF-8.
# `logging` catches its own encode failure and drops the record with a traceback
# on stderr — so the app keeps running and the evidence is gone — while a
# `json.dumps(...).encode()` raises outright, which is what LWSM-1007 will do to
# persist this list.
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\ud800-\udfff]")


def _display(text: str) -> str:
    """A name or a source, safe to put in a log record and on a row.

    Sanitised and not escaped: it is a *display* string, so `repr` would render
    a row's provenance as `'lib/launcher.py'`, quotes included. A filename may
    still contain a newline, which is the forged-log-record defect LWSM-1078
    closed — so every C0 and C1 control character becomes U+FFFD, and the result
    is clipped.
    """
    return _CONTROL.sub("�", text)[:MAX_DISPLAY_NAME_CHARS]


def _quoted(value: object) -> str:
    """Escape and clip a value before it reaches a log or the UI.

    `registry.py::_quoted`'s rule, reimplemented rather than imported for the
    reason § 8 records about `_read_bounded`. Escape first, then clip: clipping
    the input bounds the wrong string, because `repr` expands a non-printable
    astral character to a ten-character sequence (LWSM-1111).
    """
    escaped = repr(value)
    if len(escaped) <= MAX_REASON_CHARS:
        return escaped
    return f"{escaped[:MAX_REASON_CHARS]}…"


# --------------------------------------------------------------------------
# § 4.3 — reading somebody else's file
# --------------------------------------------------------------------------


def _open_source(path: Path) -> int:
    """The one place a sibling project's file is opened.

    `O_NONBLOCK` so a FIFO planted at `start.sh` returns instead of waiting for
    a writer, and `O_NOFOLLOW` because a symlinked `start.sh` is read straight
    through otherwise: `S_ISREG` and `os.access(X_OK)` both describe the
    *target*, so neither can see it. This is also the seam INV-20's test patches
    to record every path the scan touches.
    """
    return os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)


def _checked_descriptor(path: Path) -> int:
    fd = _open_source(path)
    try:
        # Interrogated on the raw descriptor, before anything wraps it —
        # `os.fdopen` on a directory raises before its `with` block is entered,
        # which is how `registry.py` leaked 50 descriptors in 50 calls.
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise OSError(errno.EINVAL, "not a regular file", str(path))
        if info.st_size > MAX_SOURCE_FILE_BYTES:
            raise OSError(
                errno.EFBIG,
                f"too large: {info.st_size} bytes, limit {MAX_SOURCE_FILE_BYTES}",
                str(path),
            )
    except BaseException:
        os.close(fd)
        raise
    return fd


def _wrap(fd: int, mode: str, **kwargs: object) -> object:
    try:
        return os.fdopen(fd, mode, **kwargs)
    except BaseException:
        os.close(fd)
        raise


def _read_bytes(path: Path) -> bytes:
    """The whole file, under the byte cap — what `package.json` needs.

    JSON has no line structure to cap: a minified `package.json` with 300
    devDependencies is 6,252 characters on one line, and truncating it at 4096
    raises `JSONDecodeError`. Under a single line-capped reader every minified
    one — an ordinary artefact — would be reported as malformed.
    """
    handle = _wrap(_checked_descriptor(path), "rb")
    with handle:
        # One byte past the cap, so a file that grew between the fstat and the
        # read is still refused rather than read whole.
        raw = handle.read(MAX_SOURCE_FILE_BYTES + 1)
    if len(raw) > MAX_SOURCE_FILE_BYTES:
        raise OSError(
            errno.EFBIG, f"too large: over {MAX_SOURCE_FILE_BYTES} bytes", str(path)
        )
    return raw


def _read_lines(path: Path, deadline: Deadline) -> list[str]:
    """Capped lines — what the port rules consume.

    A port declaration past character 4096 of one line is not a declaration
    anyone wrote on purpose, so the tail of an over-long line is **discarded
    rather than scanned**: that is what stops a pattern being split across a
    chunk boundary and matching half of itself.

    Decoded `errors="replace"`: a sibling's file is not required to be text, and
    a `UnicodeDecodeError` three levels into someone else's repo is not a fact
    worth stopping a scan for.
    """
    handle = _wrap(_checked_descriptor(path), "r", encoding="utf-8", errors="replace")
    lines: list[str] = []
    total = 0
    with handle:
        discarding = False
        while True:
            if deadline.expired():
                raise _BudgetExpired
            chunk = handle.readline(MAX_SOURCE_LINE_CHARS)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_SOURCE_FILE_BYTES:
                raise OSError(
                    errno.EFBIG,
                    f"too large: over {MAX_SOURCE_FILE_BYTES} bytes",
                    str(path),
                )
            complete = chunk.endswith("\n")
            if discarding:
                discarding = not complete
                continue
            if not complete and len(chunk) >= MAX_SOURCE_LINE_CHARS:
                discarding = True
            lines.append(chunk.rstrip("\n"))
    return lines


# --------------------------------------------------------------------------
# § 4.6 — the port rules
# --------------------------------------------------------------------------

COMMENT = re.compile(r"(?:^|\s)(?:#|//)")


def strip_comment(line: str) -> str:
    """The code part of `line`.

    A marker counts only at line start or after whitespace, and that single
    condition is the whole rule — **without it the stripper eats
    `http://localhost:3000` at the `//`**, silently killing one of rule 1's six
    documented forms. The first version written here was a quote-aware character
    loop that did exactly that damage, at 766 µs per call against this one's
    64 µs. Truncating a quoted `#` is harmless: the key left of the separator
    decides the match, and `NAME` is not a port key.

    Two markers, not three. In every language this module reads `;` is a
    *statement separator*, and including it lost the port on
    `cd /app ; exec node serve.mjs --port 8080`.

    Not applied to `systemctl` property values, which are not lines of a file
    (§ 4.6) — which is why the stripping happens at the call site rather than
    inside the rules.
    """
    match = COMMENT.search(line)
    return line if not match else line[: match.start()]


# LWSM-1190 — a port number in a sentence is advice, not a setting. Measured
# live 2026-08-24 against the real population: RetroDB's help text for moving
# off a busy port ("… Server Port, or PORT=5001 in the …") was read by rule 1,
# and MAME_Curator's validation message ("… expected an integer in 1024-65535")
# by rule 2. Both rows went from blank or right to CONFIDENTLY WRONG, which is
# the worse failure — the app matches status against whoever holds the port, so
# a wrong number reports a running project stopped.
#
# What separates the two is POSITION, the property LWSM-1183 already leans on
# for `$VAR`: a declaration begins at the start of a line, after a separator,
# or after a word that introduces one. Prose ends in an ordinary word, and
# neither `or` nor `"error:` is any of these.
#
# Deliberately narrow in one direction only. A declarator this set does not
# know costs a detection, and an undetected port is `None` — which this module
# already means as *unknown* and never as a guess. A wrong number is not
# recoverable that way, which is why the trade runs this way round.
_SEPARATORS = ";&|({[,"
# A command starts after these; a declaration is named after those. The bare
# `=` is the right-hand side of an assignment, where `opts = {"port": 5173}`
# puts the key rule 2 is looking for.
_COMMAND_WORDS = frozenset({"export", "env", "then", "do", "else", "elif", "="})
_DECLARATORS = frozenset({"const", "let", "var", "local", "declare", "readonly"})


def _declaration_position(before: str) -> bool:
    """Whether `before` leaves a declaration about to start.

    `_ASSIGNMENT` is defined with the hop rules below and is the same shell
    fact read from the other end: `FOO=1 PORT=8080` chains assignments, so a
    token that IS one still leaves the next one in position.
    """
    text = before.rstrip()
    cut = max(text.rfind(char) for char in _SEPARATORS)
    words = text[cut + 1 :].split()
    if not words:
        return True
    last = words[-1]
    return (
        last in _COMMAND_WORDS
        or last in _DECLARATORS
        or last.startswith("-")  # `docker run -e PORT=8080 image`
        or _ASSIGNMENT.match(last) is not None
    )


RULE_1 = re.compile(
    r"(?:^|[^A-Za-z0-9_])PORT=\$\{PORT:-(\d{1,5})\}(?![0-9])"  # PORT=${PORT:-N}
    r"|(?:^|[^A-Za-z0-9_])PORT=(\d{1,5})(?![0-9])"  # PORT=N
    r"|--port[= ](\d{1,5})(?![0-9])"  # --port N / --port=N
    r"|(?:localhost|127\.0\.0\.1):(\d{1,5})(?![0-9])",  # localhost:N
    re.IGNORECASE,
)


def rule_1(line: str) -> int | None:
    """An explicit port setting, anywhere in the line.

    `\\d{1,5}` alone does not *reject* a longer number, it takes the first five
    digits of one — `PORT=123456` returned 12345, which then passed the range
    check and manufactured a port out of a line declaring none. The lookahead is
    the load-bearing half.

    `finditer` and not `search`, because an out-of-range value is not a match and
    scanning resumes after it: `localhost:99999 ; PORT=8080` yields 8080.
    The separator is load-bearing since LWSM-1190 — `and PORT=8080` is a
    sentence, and rule 1 no longer reads an assignment out of one.
    """
    for match in RULE_1.finditer(line):
        form = match.lastindex  # exactly one alternation group can have matched
        value = int(match.group(form))
        if not PORT_RANGE[0] <= value <= PORT_RANGE[1]:
            continue
        # The first two forms are environment assignments and assign only in
        # command position. `--port` and `localhost:` are neither, and stay
        # readable anywhere — including inside a quoted script value, which is
        # the only place a `package.json` port is ever written.
        if form in (1, 2) and not _declaration_position(line[: match.start()]):
            continue
        return value
    return None


KEY_IS_PORT = re.compile(r"(?:^|[^A-Za-z0-9])port$", re.IGNORECASE)


def rule_2(line: str) -> int | None:
    """An assignment whose key *is* a port — not one that merely ends in it.

    The literal "ends in `port`" rule accepts `const viewport = 1280`,
    `transport = 4`, `report: 7` and `export = 5`, and a viewport is ordinary in
    the exact kind of project this app scans.

    The class here admits `_`, deliberately and unlike rule 1's: without it
    `DEFAULT_PORT` and `server_port` stop matching, which is two of the seven
    detections the acceptance test requires.
    """
    # Each separator is tried against the WHOLE line, `=` first. Not `:`
    # applied to `=`'s left side: `'server_port': 5000` has no `=` at all.
    for separator in ("=", ":"):
        left, found, right = line.partition(separator)
        if not found:
            continue
        key = left.strip().strip("'\"").rstrip("'\" \t")
        if key.lower() != "port" and not KEY_IS_PORT.search(key):
            continue
        # `KEY_IS_PORT` accepts any key ENDING in a port word, and a sentence
        # can end in one: `echo "error: PORT` satisfies it through the space.
        # What may precede the name is a declarator, not a verb — the whole
        # key minus its last word has to leave a declaration in position.
        words = key.split()
        if not _declaration_position(" ".join(words[:-1])):
            continue
        # finditer, not search — the range check below must not end the scan at
        # the first out-of-range number: `'server_port': 70000, 'port': 5000`
        # yields None under `search` and 5000 under `finditer`.
        #
        # BOTH boundaries, and `-` on the left. A lookahead alone is not enough
        # in a *search*: the engine, unable to match at the first digit,
        # advances and matches the tail — ` 123456` yields `23456`. Rule 1 is
        # immune only because `PORT=` anchors its digits to a fixed position.
        for digits in re.finditer(r"(?<![0-9-])\d{1,5}(?![0-9])", right):
            # The range check lives HERE, not at the call site: an out-of-range
            # value must let the search carry on to the next separator, the next
            # line and the next source, which a returned int cannot express.
            if PORT_RANGE[0] <= int(digits.group()) <= PORT_RANGE[1]:
                return int(digits.group())
    return None


_BOTH_RULES: tuple[tuple[Callable[[str], int | None], PortRule], ...] = (
    (rule_1, PortRule.EXPLICIT),
    (rule_2, PortRule.ASSIGNMENT),
)
_RULE_1_ONLY: tuple[tuple[Callable[[str], int | None], PortRule], ...] = (
    (rule_1, PortRule.EXPLICIT),
)


def _scan_source(
    name: str,
    lines: Sequence[str],
    *,
    rules: tuple[tuple[Callable[[str], int | None], PortRule], ...] = _BOTH_RULES,
    strip: bool = True,
) -> PortFinding | None:
    """Line-major: each line is offered to rule 1 then rule 2 before the next
    line is read, and the first line to yield a port wins.

    Proximity to the top of the file beats rule precedence, because a
    declaration near the top is the one a human reads as authoritative — on a
    launcher holding `SERVER_PORT = 3000` above `exec node serve.js --port
    8080`, line-major returns 3000 and rule-major returns 8080.
    """
    for line in lines:
        text = strip_comment(line) if strip else line
        for rule, produced_by in rules:
            value = rule(text)
            if value is not None:
                return PortFinding(port=value, rule=produced_by, source=_display(name))
    return None


# --------------------------------------------------------------------------
# § 4.6 rule 3 — a framework default, from evidence already read
# --------------------------------------------------------------------------

_FRAMEWORK_IMPORT = re.compile(r"^\s*(?:import|from)\s+(flask|django)\b", re.IGNORECASE)

# Whole-word, not a bare substring. § 4.6's table says "as a **substring** of
# the chosen `scripts` value" and its own general rule two paragraphs later says
# "every evidence test is exact or whole-word, never a substring" — the two
# contradict, and running them settled it: `{"scripts": {"dev": "vitest"}}` is
# § 7's own fixture, expected *unknown*, and the substring form reports it
# DETECTED on 5173. Every real Vite dev script (`vite`, `vite --host`,
# `./node_modules/.bin/vite`) still matches. Spec amendment surfaced, not
# absorbed (`.claude/workflow.md § 2`).
_VITE_SCRIPT = re.compile(r"\bvite\b")

FRAMEWORK_DEFAULTS = {"Vite": 5173, "Django": 8000, "Flask": 5000}


def _imports(lines: Sequence[str], framework: str) -> bool:
    """Whole-word, never a substring: `import flask_login` **contains**
    `import flask`, so a substring test reports 5000 for a project with no Flask
    app."""
    for line in lines:
        match = _FRAMEWORK_IMPORT.match(strip_comment(line))
        if match and match.group(1).lower() == framework:
            return True
    return False


def _framework_finding(name: str) -> PortFinding:
    return PortFinding(
        port=FRAMEWORK_DEFAULTS[name], rule=PortRule.FRAMEWORK_DEFAULT, source=name
    )


def _python_framework(root: Path, lines: Sequence[str]) -> PortFinding | None:
    """Django before Flask, because the table order is the precedence: a project
    with a root-level `manage.py` *and* an `import flask` matches both, and
    nothing else breaks the tie. `source` names the framework that won, so a
    wrong guess is diagnosable rather than mysterious."""
    if (root / "manage.py").is_file() or _imports(lines, "django"):
        return _framework_finding("Django")
    if _imports(lines, "flask"):
        return _framework_finding("Flask")
    return None


# --------------------------------------------------------------------------
# § 4.5 — the one-hop port-bearing file
# --------------------------------------------------------------------------

# LWSM-1183 — the interpreter is not always spelled out. A launcher that picks
# one at runtime (`PYTHON=python3` … later `$PYTHON app.py`) invokes through a
# VARIABLE, which `\bpython\b` cannot see. Measured live 2026-08-24: the last
# line the keyword did match was the assignment itself, so the walk tried to
# open a file named `PYTHON=python`.
#
# A variable reference therefore counts as a keyword **in command position
# only** — starting a line, or following the `;`, `&`, `|` or `(` that ended the
# previous command. Any `$VAR` anywhere on the line would be far wider: every
# `echo "${MSG}"` would become an invocation, and command position is the
# property that actually makes one. The variable is still never expanded, which
# `_hop_target` below states as a rule; what makes this reach a file is that the
# token beside it, `app.py`, is a literal.
_HOP_KEYWORD = re.compile(
    r"\b(?:exec|python3|python|node)\b" r'|(?:^|[;&|(])\s*!?\s*"?\$\{?[A-Za-z_]'
)

# `NAME=value` is a shell assignment and can never name a file to run. `exec env
# FOO=1 python3 launcher.py` already survived it by having a later token win;
# a line that is ONLY an assignment had nothing later to fall back to.
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _accept_hop(
    token: str, root: Path, launcher: Path
) -> tuple[Path | None, str | None]:
    """§ 4.5's six constraints, on a path.

    A non-`None` reason means the token is a path and is refused; `(None, None)`
    means it is not a path at all. Either way the previous token is tried, since
    step 4 selects the last token that satisfies all six — the caller keeps the
    first refusal for the case where no token is acceptable at all.
    """
    if "\x00" in token:
        # `os.path.commonpath` accepts a NUL happily, and then `Path.resolve()`
        # and `os.open()` both raise ValueError — not an OSError, so the "any
        # OSError rejects that file and continues" rule does not catch it and
        # the whole scan raises. `registry.py` already refuses a NUL in a path,
        # and its comment names P03 as the consumer; the guard did not arrive.
        return None, f"hop target {_quoted(token)} contains a NUL byte"
    try:
        target = (root / token).resolve()
    except (OSError, ValueError):
        return None, f"hop target {_quoted(token)} cannot be resolved"
    try:
        contained = os.path.commonpath([str(root), str(target)]) == str(root)
    except ValueError:
        contained = False
    if not contained:
        # What stops `exec python3 ../../../.ssh/config` being read and its
        # contents surfacing in the UI as a detected value.
        return None, f"hop target {_quoted(token)} is outside the project"
    parts = target.relative_to(root).parts
    if any(part in EXCLUDED_DIR_NAMES for part in parts):
        return None, f"hop target {_quoted(token)} is under an excluded directory"
    if len(parts) > MAX_HOP_DEPTH:
        return None, f"hop target {_quoted(token)} is more than {MAX_HOP_DEPTH} deep"
    if target == launcher:
        return None, f"hop target {_quoted(token)} is the launcher itself"
    if (root / token).is_symlink():
        # Constraints 1-5 all pass for an in-project symlink whose target is
        # also in-project, and `O_NOFOLLOW` would then refuse it unread — a
        # rejection with no reason attached to the thing that caused it.
        return None, f"hop target {_quoted(token)} is a symlink"
    return target, None


# LWSM-1155 — the same one hop, taken along an IMPORT rather than an
# invocation. `_HOP_KEYWORD` above matches `exec`/`python3`/`python`/`node`,
# which is a launcher *running* another file; a launcher that IS the program
# reaches its port by importing it, and nothing here saw that.
#
# Two things follow, and neither is a wider keyword set:
#
# - The tokenise-and-select rule above examines exactly ONE line — the last
#   one holding the keyword, because the rule is "the last invocation". Imports
#   are many lines and the port-bearing one need not be last, so this walks
#   every import line instead.
# - It takes the first specifier whose file yields a PORT, not the first that
#   can be read. Measured 2026-08-20: the launcher that motivated this imports
#   `./stats.mjs`, `./lib/github.mjs` and `./lib/port.mjs` in that order, and
#   only the third declares anything. "First readable" stops at `stats.mjs`.
#
# **Relative specifiers only.** A bare `node:fs/promises`, or a bare package
# name, is not a path and must not become one — or the hop walks into
# `node_modules` on every Node project, which is also the one place § 4.5
# constraint 3 exists to keep it out of.
# The keyword has to be in STATEMENT position, not merely present. Measured
# 2026-08-20 against the real population: `\bimport\b` matches inside
# `console.log("./not-an-import")`, because `-` is a word boundary — so any
# line carrying the word in a string, beside a relative-looking path, hopped.
_JS_IMPORT_LINE = re.compile(
    r"(?:^|[;{}])\s*(?:import|export)\b|\b(?:require|import)\s*\("
)
_JS_RELATIVE = re.compile(r"""['"](\.{1,2}/[^'"]*)['"]""")
_PY_IMPORT_LINE = re.compile(
    r"^\s*(?:from\s+(?P<from>\.*[\w.]*)\s+import\b|import\s+(?P<plain>[\w.]+))"
)


def _import_specifiers(line: str, suffix: str) -> list[str]:
    """The in-project files `line` imports, as paths relative to the project.

    Returns `[]` for a line that imports nothing, and for one that imports only
    things outside the project — which is the common case and the safe default.
    """
    if suffix == ".py":
        match = _PY_IMPORT_LINE.match(line)
        if match is None:
            return []
        # `from .lib.port import X`, `from lib.port import X` and
        # `import lib.port` all name `lib/port.py`. A Python script's own
        # directory is on `sys.path`, so the dotless form IS the local-file
        # form here — unlike JS, where a bare specifier is a package.
        module = match.group("from") or match.group("plain") or ""
        if module.startswith(".."):
            # A parent package is outside the project by construction, so this
            # is constraint 1's case — and `lstrip(".")` would quietly turn
            # `from ..up import x` into a ROOT-level `up.py`, reading a file the
            # import never named rather than refusing one it did.
            return []
        module = module.lstrip(".")
        if not module:
            # `from . import port` names the package, not a module in it.
            return []
        return [module.replace(".", "/") + ".py"]
    if not _JS_IMPORT_LINE.search(line):
        return []
    # The specifier as written, extension included. `./lib/port` (legal under
    # CommonJS, where the extension is optional) is NOT resolved against `.js`
    # and `.mjs` — the same honest limit § 4.5 already takes on two hops.
    return _JS_RELATIVE.findall(line)


def _import_hop_port(
    candidate: Path,
    launcher: Path,
    lines: Sequence[str],
    deadline: Deadline,
    note: Callable[[str], None],
) -> PortFinding | None:
    """§ 4.5's one hop, taken along an import.

    Reached two ways: from launcher rules 3 and 4, where the launcher IS the
    program and there is no `exec` line to read; and from the shell rule's
    invocation hop, where the program is the file that line named (LWSM-1184).

    Every one of § 4.5's six constraints still applies, because the target
    still goes through `_accept_hop`: in-project, not the launcher, not under an
    excluded directory, within `MAX_HOP_DEPTH`, not a symlink, no NUL.

    Still exactly ONE hop. A launcher importing a module that imports another is
    out of scope and comes back *unknown*, which is § 4.5's existing limit for
    `project-e` rather than a new one.
    """
    seen: set[Path] = set()
    hops = 0
    for line in lines:
        for specifier in _import_specifiers(strip_comment(line), launcher.suffix):
            if hops >= MAX_IMPORT_HOPS or deadline.expired():
                # Two different budgets. `MAX_IMPORT_HOPS` bounds the files
                # actually READ, which is the expensive half; the deadline
                # bounds the attempts, which are one failed `open` each and
                # would otherwise be limited only by how many import lines a
                # hostile launcher cares to write.
                return None
            target, reason = _accept_hop(specifier, candidate, launcher)
            if reason is not None:
                note(reason)
                continue
            if target is None or target in seen:
                continue
            seen.add(target)
            try:
                hop_lines = _read_lines(target, deadline)
            except (FileNotFoundError, NotADirectoryError):
                # A specifier naming nothing in the project. The commonest shape
                # by far on the Python side, where `import os` is spelled
                # exactly like `import config`. **It must not count against
                # MAX_IMPORT_HOPS**: measured 2026-08-20, a real Flask launcher
                # yields 95 specifiers whose first eight are all stdlib, so
                # counting the misses spends the whole budget before reaching a
                # single in-project module. It is not worth a reason either.
                continue
            except OSError as exc:
                note(f"{_quoted(specifier)} cannot be read ({exc.strerror or exc})")
                continue
            hops += 1
            found = _scan_source(target.relative_to(candidate).as_posix(), hop_lines)
            if found is not None:
                # INV-11: `source` names the file actually read, never the
                # launcher that pointed at it.
                return found
    return None


def _hop_target(
    lines: Sequence[str], root: Path, launcher: Path, deadline: Deadline
) -> tuple[Path | None, list[str], str | None]:
    """Tokenise and select, in four steps.

    The lines arrive comment-stripped, because the rule takes the **last**
    invocation: a script ending `exec python3 new.py` / `# exec python3 old.py`
    resolves to `old.py` unstripped.

    Steps 3 and 4 are what prose left open. `exec python3 -u launcher.py` gives
    `python3` under "the token after the keyword", `exec env FOO=1 python3
    launcher.py` gives `env`, and `python3 -m http.server 8080` gives `-m`.
    Under this rule the first two give `launcher.py` and the third gives no hop,
    which is correct: `http.server` runs no file in the project. This module
    does not expand shell variables and must not start.
    """
    first_refusal: str | None = None
    for line in reversed(lines):
        if not _HOP_KEYWORD.search(line):
            continue
        stripped = (token.strip("'\"") for token in line.split())
        tokens = [
            token
            for token in stripped
            if not token.startswith("-") and not _ASSIGNMENT.match(token)
        ]
        refusal: str | None = None
        for token in reversed(tokens):
            target, reason = _accept_hop(token, root, launcher)
            if reason is not None:
                # Step 4 takes the last token that satisfies the six
                # constraints, which is not the same as *the last token*: a
                # refused one is one token that failed, and the token before it
                # may still be the target. `exec python3 app.py >>
                # /var/log/app.log` is an ordinary launcher line, and
                # abandoning at the redirect both loses the port and records a
                # reason about a hop the launcher never asked for. The first
                # refusal is kept for the case where no token is acceptable at
                # all, so falling back cannot turn a refusal into silence.
                if refusal is None:
                    refusal = reason
                continue
            if target is None:
                continue
            try:
                return target, _read_lines(target, deadline), None
            except (FileNotFoundError, NotADirectoryError):
                # Not a path at all — an argument, a module name, a bare word.
                continue
            except OSError as exc:
                # A refused hop target leaves the project listed: the launcher
                # is still runnable and only the port is unknown.
                unreadable = f"{_quoted(token)} cannot be read ({exc.strerror or exc})"
                return None, [], unreadable
        # LWSM-1183 — "the last invocation" is the last one that RESOLVES, not
        # the last line carrying the keyword. A line can hold the keyword and
        # name no runnable file at all — a trailing `echo "re-run with python3
        # start.sh"`, or a launcher whose last variable-led line is a `-c`
        # one-liner — and abandoning the walk there loses the port the line
        # above was holding. Widening the keyword to reach `$VAR` widens what
        # can land last, so this is the half that keeps that safe. The first
        # refusal is still what gets reported when NO line yields a hop, so
        # falling through cannot turn a refusal into silence.
        if first_refusal is None:
            first_refusal = refusal
    return None, [], first_refusal


# --------------------------------------------------------------------------
# § 4.4 rule 0 — the systemd path
# --------------------------------------------------------------------------

UNIT_PROPERTIES = (
    "LoadState",
    "FragmentPath",
    "WorkingDirectory",
    "Environment",
    "ExecStart",
)

# ADR-0003's pattern, widened by `\\`. The escaped form is the only one
# `systemctl` accepts, and the class as written has no backslash — so
# `app-ai\x2dprompts\x2dtray@autostart.service`, a real unit, could never pass
# validation and the unescaping step would be dead code. A backslash is inert
# in an `execve` argv; the leading-`-` rejection and the `--` separator remain
# the actual defence.
UNIT_NAME = re.compile(r"^[A-Za-z0-9@:_.\\\-]{1,255}\.(service|socket|target|timer)$")


def _valid_unit_name(name: str) -> bool:
    """A name beginning with `-` is consumed by `systemctl` as an option —
    `--host=`, `-M` and `--machine=` all redirect which manager is driven, and
    such a name exits 0 with an empty record, so this is the guard rather than a
    belt-and-braces addition to one `systemctl` performs."""
    return bool(UNIT_NAME.match(name)) and not name.startswith("-")


def _unescape_unit_name(name: str) -> str:
    """Undo systemd's `\\xNN` escaping, for the name comparison only.

    Two different strings: `systemctl` accepts only the escaped form, while
    matching a unit to a directory needs the unescaped one.
    """
    return re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), name)


def _show_argv(unit: str) -> list[str]:
    """**Every `-p` goes before the `--`.** With the options after it,
    `systemctl` reads `-p` and `FragmentPath` as further unit names and dumps
    all 832 property lines of the real unit. The separator `coding.md § 7`
    requires still applies — it just has to be the last thing before the name.

    A pure function because the argv is built inside the real adapter, which
    every test replaces with a fake: without calling this directly, an adapter
    shipping no separator at all would keep every test green.
    """
    argv = ["systemctl", "--user", "show"]
    for name in UNIT_PROPERTIES:
        argv += ["-p", name]
    argv += ["--", unit]
    return argv


def _exec_start_argv(record: str) -> str | None:
    """`ExecStart` is a structured record, not a command line —
    `ExecStart={ path=/usr/bin/node ; argv[]=/usr/bin/node serve.mjs ; … }` — so
    only the `argv[]=` field is scanned, and rule 2 is not run over it at all,
    because `path=` and `pid=` are `systemctl`'s own keys."""
    match = re.search(r"argv\[\]=([^;]*)", record)
    return match.group(1) if match else None


class SystemctlUnits:
    """The real `systemctl --user` surface.

    Every failure mode becomes an `OSError`, which is the Protocol's contract
    and the only reason § 6's "a machine without systemd scans normally" is
    true. Nothing in the test suite reaches this class (`testing.md § T1`), so
    the measurements behind it are dated and reproducible by hand rather than
    re-run — recorded in the spec's § 11 as one of its `nothing` rows.
    """

    def unit_names(self, timeout: float) -> list[str]:
        raw = self._run(
            [
                "systemctl",
                "--user",
                "list-unit-files",
                "--type=service",
                "--output=json",
            ],
            timeout,
        )
        try:
            listed = json.loads(raw)
        except ValueError as exc:
            # Not a JSONDecodeError from the caller's point of view: with no
            # user D-Bus session the command exits 1 with empty stdout, and a
            # ValueError is not an OSError.
            raise OSError(
                errno.EIO, f"systemctl produced no usable JSON ({exc})"
            ) from exc
        if not isinstance(listed, list):
            raise OSError(errno.EIO, "systemctl's unit list is not a list")
        return [
            entry["unit_file"]
            for entry in listed
            if isinstance(entry, dict) and isinstance(entry.get("unit_file"), str)
        ]

    def properties(
        self, unit: str, names: Sequence[str], timeout: float
    ) -> dict[str, str]:
        raw = self._run(_show_argv(unit), timeout)
        held: dict[str, str] = {}
        for line in raw.splitlines():
            key, found, value = line.partition("=")
            if found:
                held[key] = value
        # TOTAL over `names`, per the Protocol: a missing key would raise
        # KeyError in the caller, which is not an OSError.
        return {name: held.get(name, "") for name in names}

    @staticmethod
    def _run(argv: list[str], timeout: float) -> str:
        try:
            completed = subprocess.run(  # noqa: S603 - argv, never a shell; the
                # unit name is validated against UNIT_NAME and passed after `--`
                argv,
                capture_output=True,
                text=True,
                timeout=max(timeout, 0.0),
                check=True,
            )
        except subprocess.SubprocessError as exc:
            # TimeoutExpired and CalledProcessError are SubprocessError, which
            # is NOT an OSError. Translating them here is what stops a hung or
            # session-less systemctl raising out of `scan()`.
            raise OSError(
                errno.EIO, f"systemctl failed ({type(exc).__name__}: {exc})"
            ) from exc
        return completed.stdout


class _UnitLookup:
    """Rule 0's state for one scan: the unit list, fetched once, and one
    recorded reason if the service manager is unreachable.

    "Recorded once, not once per candidate" is the whole point — a machine with
    no systemd would otherwise put a line in `skipped` for every project on it.
    """

    def __init__(
        self,
        source: SupportsUnitLookup | None,
        deadline: Deadline,
        note: Callable[[str], None],
    ) -> None:
        self._source = source
        self._deadline = deadline
        self._note = note
        self._names: list[str] | None = None
        self._disabled = source is None

    def _timeout(self) -> float:
        return min(SYSTEMCTL_TIMEOUT_SECONDS, self._deadline.remaining())

    def _disable(self, exc: OSError) -> None:
        self._disabled = True
        self._note(
            f"systemctl is unavailable ({exc.strerror or exc}); no unit is bound"
        )

    def names(self) -> list[str]:
        if self._disabled:
            return []
        if self._names is None:
            try:
                self._names = list(self._source.unit_names(self._timeout()))
            except OSError as exc:
                self._names = []
                self._disable(exc)
        return self._names

    def properties(self, unit: str) -> dict[str, str] | None:
        if self._disabled:
            return None
        try:
            return self._source.properties(unit, UNIT_PROPERTIES, self._timeout())
        except OSError as exc:
            self._disable(exc)
            return None


def _bound_inside(value: str, candidate: Path) -> bool:
    """`FragmentPath` / `WorkingDirectory` containment.

    **An empty value contributes no evidence and is never resolved.**
    `Path("").resolve()` is the *current working directory*, so resolving an
    absent `WorkingDirectory` makes any name-matched unit bind whenever the
    manager was launched from inside a scan-root project — which is precisely
    the empty-directory-drives-somebody-else's-service outcome this check exists
    to stop, arriving through the check meant to prevent it.

    systemd prefixes the value with `-` (ignore if missing) or `!` (run
    privileged) and prints both: 13 of the 14 real user units on this machine
    print a `!`-prefixed path, so unstripped this compares a path that cannot
    exist and nothing ever binds.
    """
    cleaned = value.lstrip("-!")
    if not cleaned:
        return False
    try:
        resolved = Path(cleaned).resolve()
    except (OSError, ValueError):
        return False
    return resolved == candidate or candidate in resolved.parents


# --------------------------------------------------------------------------
# § 4.4 — launcher rules, first match wins
# --------------------------------------------------------------------------


@dataclass
class _Launcher:
    kind: LauncherKind
    argv: tuple[str, ...]
    unit: str | None = None
    port: PortFinding | None = None


def _match_systemd(
    candidate: Path,
    raw_name: str,
    quoted: str,
    units: _UnitLookup,
    note: Callable[[str], None],
) -> _Launcher | None:
    for listed in units.names():
        stem = listed.rsplit(".", 1)[0]
        if _unescape_unit_name(stem) != raw_name:
            continue
        if not _valid_unit_name(listed):
            note(f"{quoted}: unit {_quoted(listed)} is not a usable unit name")
            continue
        props = units.properties(listed)
        if props is None:
            return None
        load_state = props["LoadState"]
        if load_state == "not-found":
            # Silent: a project simply having no unit is the ordinary case and
            # would otherwise put a line in `skipped` for every candidate.
            continue
        if load_state == "masked":
            # A user who *disabled* something this app was about to drive is
            # worth one line — and it is the only observable that separates a
            # masked unit from an absent one, both of which exit 0 with an
            # empty FragmentPath.
            note(f"{quoted}: unit {_quoted(listed)} is masked")
            continue
        if not any(
            _bound_inside(props[field], candidate)
            for field in ("FragmentPath", "WorkingDirectory")
        ):
            # A real unit belonging to someone else, carrying this project's
            # name — the `mkdir <scan root>/project-a` case the step exists for,
            # and the one branch an operator will want to see.
            note(f"{quoted}: unit {_quoted(listed)} is not bound to this directory")
            continue
        return _Launcher(
            kind=LauncherKind.SYSTEMD,
            argv=(),
            unit=listed,
            port=_systemd_port(props, listed),
        )
    return None


def _systemd_port(props: dict[str, str], unit: str) -> PortFinding | None:
    """A `systemd` project runs no script this app can open, so its port lives
    in the two properties already fetched: `Environment=` first, then
    `ExecStart=`.

    `properties()` returns the value with its `NAME=` prefix removed, and that
    removal is load-bearing: split with the prefix left on, the first token is
    `Environment=STATS_PORT=4321`, on which rule 2 partitions at the first `=`
    and gets the key `Environment` while rule 1's `PORT=` is preceded by `_` —
    so neither rule matches and the project comes back *unknown*.

    Split on whitespace because `partition` examines only the FIRST `KEY=` on a
    line: unsplit, `REFRESH=24 STATS_PORT=4321` yields None, and a port that is
    not the first variable is invisible.
    """
    source = f"the {unit} unit"
    environment = props["Environment"]
    if environment:
        found = _scan_source(source, environment.split(), strip=False)
        if found is not None:
            return found
    argv_field = _exec_start_argv(props["ExecStart"])
    if argv_field:
        return _scan_source(source, [argv_field], rules=_RULE_1_ONLY, strip=False)
    return None


def _read_alternate(
    candidate: Path,
    filename: str,
    quoted: str,
    deadline: Deadline,
    note: Callable[[str], None],
) -> list[str] | None:
    """One alternate of a launcher rule, or `None` with a reason recorded.

    **A refused launcher file is not a match, and the rules continue.** Stopping
    at the first refused file would mean anyone able to drop a symlink named
    `start.sh` into a project directory could delete that project from the
    manager — a denial of service bought with one file.
    """
    path = candidate / filename
    if not path.is_symlink() and not path.exists():
        return None
    try:
        return _read_lines(path, deadline)
    except OSError as exc:
        note(f"{quoted}: {filename} cannot be read ({exc.strerror or exc})")
        return None


def _match_shell(
    candidate: Path, quoted: str, deadline: Deadline, note: Callable[[str], None]
) -> _Launcher | None:
    for filename in ("start.sh", "run.sh"):
        lines = _read_alternate(candidate, filename, quoted, deadline, note)
        if lines is None:
            continue
        path = candidate / filename
        if not os.access(path, os.X_OK):
            # Running it would fail at spawn time with a message about a file
            # the user never chose.
            note(f"{quoted}: {filename} is not executable")
            continue
        return _Launcher(
            kind=LauncherKind.SHELL,
            argv=(f"./{filename}",),
            port=_shell_port(candidate, path, lines, deadline, note),
        )
    return None


def _shell_port(
    candidate: Path,
    launcher: Path,
    lines: Sequence[str],
    deadline: Deadline,
    note: Callable[[str], None],
) -> PortFinding | None:
    """File-major: rules 1 then 2 in the launcher, then rules 1 then 2 in the
    one-hop file, then rule 3 across both.

    The launcher is the file that actually runs, and rule 3's own scope ("only
    when neither port rule found anything") is coherent only under file-major.
    With `SERVER_PORT = 3000` in the launcher and `--port 8080` in the hop file,
    rule-major returns 8080 and this returns 3000.
    """
    found = _scan_source(launcher.name, lines)
    if found is not None:
        return found

    stripped = [strip_comment(line) for line in lines]
    target, hop_lines, reason = _hop_target(stripped, candidate, launcher, deadline)
    if reason is not None:
        note(reason)
    if target is None:
        return None

    found = _scan_source(target.relative_to(candidate).as_posix(), hop_lines)
    if found is not None:
        return found
    # LWSM-1184 — the wrapper is not the program. Measured live 2026-08-24:
    # Contact_List's `run.sh` builds a venv and runs `launcher.py`, which
    # declares no port and imports one from `config.py`; the scan opened two
    # files and stopped. The invocation hop already grants its target program
    # status for rule 3 below, and this is the same grant for the port rules.
    #
    # It does not deepen the walk. The budget was one hop per launcher shape
    # and still is — one INVOCATION and one IMPORT — so a module the hop file
    # imports that imports another is out of scope exactly as before.
    #
    # Ahead of rule 3, because a port another file DECLARES outranks one a
    # framework merely defaults to. That is § 4.6's own ordering ("only when
    # neither port rule found anything"), and the import walk is those rules
    # read in another file.
    found = _import_hop_port(candidate, target, hop_lines, deadline, note)
    if found is not None:
        return found
    # A shell project reaches Django and Flask evidence only through a `.py`
    # hop: a `start.sh` reading `exec node serve.mjs`, with a stray `manage.py`
    # beside it, would otherwise reach Django's 8000 — a Python default
    # fabricated for a project that runs no Python.
    if target.suffix == ".py":
        return _python_framework(candidate, hop_lines)
    return None


def _match_node_package(
    candidate: Path, quoted: str, note: Callable[[str], None]
) -> _Launcher | None:
    """`package.json` through `_read_bytes`, and every container type-checked
    before it is touched.

    Three of its malformed shapes are **not** `JSONDecodeError` and each would
    otherwise escape `scan()`: 20,000 nested arrays raise `RecursionError` (a
    `RuntimeError`), invalid UTF-8 raises `UnicodeDecodeError`, and a root of
    `5` or `[1,2]` raises `AttributeError` on `.get`. A fourth arrives through
    rule 3's evidence scan: `{"dependencies": 5}` makes `"vite" in deps` raise
    `TypeError`, which is neither — so one hostile file deleted every other
    project's row. `registry.py::load_projects` already names the first three.
    """
    path = candidate / "package.json"
    if not path.is_symlink() and not path.exists():
        return None
    try:
        raw = _read_bytes(path)
    except OSError as exc:
        note(f"{quoted}: package.json cannot be read ({exc.strerror or exc})")
        return None
    try:
        # utf-8-sig: an editor-added BOM is invisible in that editor, and
        # `registry.py::load_projects` records the same reasoning.
        data = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, RecursionError) as exc:
        note(f"{quoted}: package.json cannot be parsed ({type(exc).__name__})")
        return None
    if not isinstance(data, dict):
        note(f"{quoted}: package.json's top level is not an object")
        return None
    scripts = data.get("scripts")
    if not isinstance(scripts, dict):
        note(f"{quoted}: package.json has no 'scripts' object")
        return None

    # `dev` can be present and INVALID — "", null and {} are all trivially
    # plantable — and "dev, else start" alone admits two readings that give the
    # same file two different launchers. The chosen entry is the first whose
    # value is a non-empty string.
    chosen: tuple[str, str] | None = None
    for key in ("dev", "start"):
        value = scripts.get(key)
        if isinstance(value, str) and value:
            chosen = (key, value)
            break
    if chosen is None:
        note(f"{quoted}: package.json has no usable 'dev' or 'start' script")
        return None

    dependencies: set[str] = set()
    for field in ("dependencies", "devDependencies"):
        block = data.get(field)
        if isinstance(block, dict):
            dependencies.update(block)
        elif block is not None:
            note(f"{quoted}: package.json's {field} is not an object")

    return _Launcher(
        kind=LauncherKind.NODE,
        argv=("npm", "run", chosen[0]),
        port=_node_package_port(chosen[1], dependencies),
    )


def _node_package_port(script: str, dependencies: set[str]) -> PortFinding | None:
    """**The port rules see exactly one value from `package.json`: the
    `scripts` entry this rule chose.** Not every script, and never the
    dependency block.

    `"get-port": "^7.0.0"` — a real npm package — partitions on `:` and
    satisfies `KEY_IS_PORT` through the hyphen, so a dependency block returns
    port 7. And with `"build": "vite build --port 9000"` above `"dev": "vite
    --port 3000"`, scanning every script in document order returns the port of
    a build step.

    Vite's two evidence tests differ in *form* and agree in strictness: a
    dependency block has keys, so the test is exact-key membership; a script
    value is a string, so the test there is whole-word. Neither is a bare
    substring — `vitest`, a test runner and among the commonest devDependencies
    there is, contains `vite` and is not a server at all.
    """
    found = _scan_source("package.json", [script[:MAX_SOURCE_LINE_CHARS]])
    if found is not None:
        return found
    # The script value is stripped and clipped exactly as the port rules above
    # see it (§ 4.6: the stripper is shared by both rules **and by rule 3's
    # evidence scan**). `#` is a real comment in an npm script — the value is
    # handed to `sh` — so `node server.js # switch to vite later` is a note
    # about a future migration, not evidence of a Vite server. The dependency
    # test stays exact-key membership and this one stays whole-word: `vitest`,
    # among the commonest devDependencies there is, contains `vite`.
    if "vite" in dependencies or _VITE_SCRIPT.search(
        strip_comment(script[:MAX_SOURCE_LINE_CHARS])
    ):
        return _framework_finding("Vite")
    return None


def _match_named_file(
    candidate: Path,
    quoted: str,
    alternates: Sequence[str],
    kind: LauncherKind,
    argv0: str,
    deadline: Deadline,
    note: Callable[[str], None],
    framework: bool,
) -> _Launcher | None:
    """Launcher rules 3 and 4: the file they run is the file § 4.6 reads — and
    since LWSM-1155 also the file whose *imports* § 4.5 follows.

    That second clause is the correction. The docstring here read "so there is
    nothing to follow", and § 4.5 opened "only for `kind == SHELL`", both on the
    reasoning that a shell launcher names another file while these two ARE the
    file. True of `exec`, and false of `import`: measured 2026-08-20, a real
    `serve.mjs` keeps its port in `./lib/port.mjs` one import away, and came
    back *unknown* because no hop was attempted at all.

    Order is `INV-10`'s, unchanged and extended the way `_shell_port` already
    extends it: the launcher's own lines first, then the one hop, then — for
    rule 3 only — the framework default, which is the weakest evidence of the
    three and so goes last.
    """
    for filename in alternates:
        lines = _read_alternate(candidate, filename, quoted, deadline, note)
        if lines is None:
            continue
        port = _scan_source(filename, lines)
        if port is None:
            port = _import_hop_port(
                candidate, candidate / filename, lines, deadline, note
            )
        if port is None and framework:
            port = _python_framework(candidate, lines)
        return _Launcher(kind=kind, argv=(argv0, filename), port=port)
    return None


def _detect(
    candidate: Path,
    raw_name: str,
    quoted: str,
    units: _UnitLookup,
    deadline: Deadline,
    note: Callable[[str], None],
) -> _Launcher | None:
    """§ 4.4's five rules, first match wins."""
    return (
        _match_systemd(candidate, raw_name, quoted, units, note)
        or _match_shell(candidate, quoted, deadline, note)
        or _match_node_package(candidate, quoted, note)
        or _match_named_file(
            candidate,
            quoted,
            ("serve.py", "server.py", "app.py"),
            LauncherKind.PYTHON,
            "python3",
            deadline,
            note,
            framework=True,
        )
        # A `serve.mjs` identifies no framework, so a stray `manage.py` beside a
        # Node server must not fabricate 8000 for it.
        or _match_named_file(
            candidate,
            quoted,
            ("serve.mjs", "serve.js"),
            LauncherKind.NODE,
            "node",
            deadline,
            note,
            framework=False,
        )
    )


# --------------------------------------------------------------------------
# § 4.2 — choosing candidates
# --------------------------------------------------------------------------


def _own_package_directory() -> Path | None:
    """Where this application's own package lives.

    Exact only for a source checkout, and that is the honest limit: installed as
    a wheel `lwsm` resolves inside `site-packages`, which is not under a scan
    root, so the guard never fires — correctly, because the repository is then
    not a candidate either.
    """
    try:
        return Path(lwsm.__file__).resolve()
    except (AttributeError, OSError, TypeError, ValueError):  # pragma: no cover
        return None


def scan(
    roots: Sequence[Path],
    *,
    units: SupportsUnitLookup | None = None,
    now: Callable[[], float] = time.monotonic,
    budget_seconds: float = SCAN_BUDGET_SECONDS,
) -> ScanResult:
    """Every candidate project under `roots`, with its launcher and its port.

    `roots` is passed in rather than read from settings: settings persistence is
    LWSM-1007's, and a Scanner that read the real config could not satisfy
    `testing.md § T1`.

    A scan root that is itself a symlink is **followed**, deliberately: the user
    typed this path, so it is a choice rather than something planted in a
    directory this app happened to walk into. Candidates arrive from the
    filesystem instead, and are refused.
    """
    deadline = Deadline(expires_at=now() + budget_seconds, now=now)
    reasons: list[str] = []
    suppressed = 0

    def note(reason: str) -> None:
        """Record a reason, or count it once `MAX_SKIP_REASONS` are held."""
        nonlocal suppressed
        if len(reasons) < MAX_SKIP_REASONS:
            reasons.append(reason)
        else:
            suppressed += 1

    lookup = _UnitLookup(
        units if units is not None else SystemctlUnits(), deadline, note
    )
    own = _own_package_directory()
    projects: list[DetectedProject] = []
    seen: set[Path] = set()
    unlistable: list[Path] = []
    timed_out = False

    try:
        for root in roots:
            try:
                with os.scandir(root) as listing:
                    entries = sorted(listing, key=lambda entry: entry.name)
            except OSError as exc:
                # A missing root is ordinary — an unmounted drive — and must not
                # blank the result.
                note(f"{_quoted(str(root))}: cannot be listed ({exc.strerror or exc})")
                # Recorded as a value as well as a reason: LWSM-1131's merge has
                # to distinguish "this root hid an unknown number of projects"
                # from an ordinary per-entry skip, and parsing the reason string
                # back out is the wording-dependence that spec rejects.
                unlistable.append(Path(root))
                continue

            for entry in entries:
                if deadline.expired():
                    raise _BudgetExpired
                raw_name = entry.name
                quoted = _quoted(raw_name)
                try:
                    # Symlink before directory, so the reason names what
                    # actually happened: `is_dir(follow_symlinks=False)` reports
                    # a symlinked directory as "not a directory", which is true
                    # and useless. Both are one lstat.
                    if entry.is_symlink():
                        # Refused rather than resolved. `os.walk(followlinks=
                        # False)` declines to *descend* into a symlinked
                        # subdirectory but still lists it, and walking one as
                        # the top follows it — so that flag is not the guard at
                        # candidate level; this is.
                        note(f"{quoted}: is a symlink, refused")
                        continue
                    if not entry.is_dir(follow_symlinks=False):
                        note(f"{quoted}: is not a directory")
                        continue
                    candidate = Path(entry.path).resolve()
                except OSError as exc:
                    note(f"{quoted}: cannot be examined ({exc.strerror or exc})")
                    continue

                if own is not None and (own == candidate or candidate in own.parents):
                    # Once P01's launcher exists the manager would otherwise
                    # list and offer to launch itself.
                    note(f"{quoted}: is this application's own directory")
                    continue
                if candidate in seen:
                    # Two scan roots may overlap, or one may sit inside another.
                    # ADR-0005 makes the absolute path the identity, so two
                    # records sharing one is a malformed result.
                    note(f"{quoted}: already scanned under another root")
                    continue
                seen.add(candidate)

                try:
                    launcher = _detect(
                        candidate, raw_name, quoted, lookup, deadline, note
                    )
                except OSError as exc:
                    # Contained per candidate, and deliberately at the class
                    # rather than at the metadata calls that raise today:
                    # `Path.exists` / `is_symlink` / `is_file` re-raise EACCES
                    # and ENAMETOOLONG on 3.13 (`pathlib._abc._IGNORED_ERRNOS`
                    # swallows only ENOENT/ENOTDIR/EBADF/ELOOP), and § 4.3
                    # requires one unreadable project to cost that project
                    # only. Four call sites had already been found; patching
                    # those four would leave the fifth. `_BudgetExpired` is not
                    # an `OSError`, so INV-5's abandonment still propagates.
                    note(f"{quoted}: cannot be examined ({exc.strerror or exc})")
                    continue
                if launcher is None:
                    note(f"{quoted}: no launcher matched")
                    continue
                projects.append(
                    DetectedProject(
                        path=candidate,
                        name=_display(raw_name),
                        kind=launcher.kind,
                        argv=launcher.argv,
                        unit=launcher.unit,
                        port=launcher.port,
                    )
                )
    except _BudgetExpired:
        # The candidate in progress is abandoned: not listed, no partial port.
        timed_out = True

    if suppressed:
        # Always, never conditionally quiet: a cap with no tail reads exactly
        # like completeness, and nothing downstream could tell a root with 100
        # unusable subdirectories from one with half a million.
        reasons.append(f"and {suppressed} more problems, not shown")

    return ScanResult(
        projects=tuple(projects),
        skipped=tuple(reasons),
        timed_out=timed_out,
        unlistable_roots=tuple(unlistable),
    )
