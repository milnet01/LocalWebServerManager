"""Execute every pattern, bound and predicate LWSM-1006's spec prescribes.

    PYTHONDONTWRITEBYTECODE=1 uv run python3 docs/specs/LWSM-1006-conformance.py

Transcribed VERBATIM from `LWSM-1006-scanner-detection.md`, then run against
inputs chosen to break them. A row that fails is a defect in the SPEC, not in
this file — fix the spec, then re-transcribe.

**Why this exists.** Three cold-eyes loops read those patterns and passed them;
running them found a rule that fabricated port 23456 out of `PORT = 123456` and
another that read a commented-out `# PORT=9999 (old)` as live. A claim about a
pattern is verified by running the pattern. Reading it is not verifying it.

This is a spec artefact, not a test: it holds the patterns because `scanner.py`
does not exist yet. When LWSM-1006 is implemented, these cases move into
`tests/test_scanner.py` pointed at the real module and this file is deleted —
it is named in the spec's Definition of done for exactly that reason.
"""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
import time
from pathlib import Path

FAILS: list[str] = []


def check(name: str, got: object, want: object, note: str = "") -> None:
    if got != want:
        FAILS.append(f"{name}: got {got!r}, spec says {want!r}  {note}")
        print(f"  FAIL {name}: got {got!r}, want {want!r}  {note}")
    else:
        print(f"  ok   {name}: {got!r}")


# ---------------------------------------------------------------- § 4.6 rule 1
RULE_1 = re.compile(
    r"(?:^|[^A-Za-z0-9_])PORT=\$\{PORT:-(\d{1,5})\}(?![0-9])"
    r"|(?:^|[^A-Za-z0-9_])PORT=(\d{1,5})(?![0-9])"
    r"|--port[= ](\d{1,5})(?![0-9])"
    r"|(?:localhost|127\.0\.0\.1):(\d{1,5})(?![0-9])",
    re.IGNORECASE,
)

PORT_RANGE = (1, 65535)


def rule_1(line: str) -> int | None:
    # finditer, not search: an out-of-range value is not a match and scanning
    # resumes after it, so `localhost:99999 and PORT=8080` yields 8080.
    for m in RULE_1.finditer(strip_comment(line)):
        value = int(next(g for g in m.groups() if g is not None))
        if PORT_RANGE[0] <= value <= PORT_RANGE[1]:
            return value
    return None


# --------------------------------------------------------- § 4.6 comments
COMMENT = re.compile(r"(?:^|\s)(?:#|//)")


def strip_comment(line: str) -> str:
    """The code part of `line`, comment removed.

    A marker counts only at line start or after whitespace. That single
    condition is what keeps `http://localhost:3000` intact — an earlier
    quote-aware character loop cut it at the `//` and lost a documented rule-1
    form, while costing 766 us/call against this one's 64 us on a 4096-char
    line (measured 2026-08-08).
    """
    m = COMMENT.search(line)
    return line if not m else line[: m.start()]


# ---------------------------------------------------------------- § 4.6 rule 2
KEY_IS_PORT = re.compile(r"(?:^|[^A-Za-z0-9])port$", re.IGNORECASE)


def rule_2(line: str) -> int | None:
    line = strip_comment(line)
    for separator in ("=", ":"):
        left, found, right = line.partition(separator)
        if not found:
            continue
        key = left.strip().strip("'\"").rstrip("'\" \t")
        if key.lower() != "port" and not KEY_IS_PORT.search(key):
            continue
        for digits in re.finditer(r"(?<![0-9-])\d{1,5}(?![0-9])", right):
            if PORT_RANGE[0] <= int(digits.group()) <= PORT_RANGE[1]:
                return int(digits.group())
    return None


print("=== § 4.6 rule 1: the six accepted forms ===")
for line, want in [
    ("PORT=8080", 8080),
    ("PORT=${PORT:-8080}", 8080),
    ("export PORT=8080", 8080),
    ("--port 5000", 5000),
    ("--port=5000", 5000),
    ("http://localhost:3000/", 3000),
    ("127.0.0.1:9999", 9999),
]:
    check(f"rule_1({line!r})", rule_1(line), want)

print("=== § 4.6 rule 1: keys it must NOT claim (INV-9) ===")
for line in [
    "TRANSPORT=99",
    "EXPORT=5",
    "APP_PORT=4321",
    "SERVER_PORT = 3000",
    "const viewport = 1280",
    "SUPPORT=80",
    "REPORT=443",
]:
    check(f"rule_1({line!r})", rule_1(line), None)

print("=== § 4.6 rule 1: numbers it must NOT fabricate (loop 3 CRITICAL) ===")
for line in [
    "PORT=123456",
    "--port 999999999",
    "localhost:1234567",
    "PORT=0",
    "PORT=65536",
    "--port 70000",
]:
    check(f"rule_1({line!r})", rule_1(line), None)

print("=== § 4.6 rule 1: boundary values that MUST be accepted ===")
check("rule_1('PORT=1')", rule_1("PORT=1"), 1)
check("rule_1('PORT=65535')", rule_1("PORT=65535"), 65535)
check(
    "rule_1('PORT=80')",
    rule_1("PORT=80"),
    80,
    "declared range is 1-65535, not ADR-0005's 1024+",
)

print("=== § 4.6 rule 1: forms NOT yet exercised anywhere ===")
check("case-insensitive lower", rule_1("port=8080"), 8080)
check("mixed case", rule_1("Port=8080"), 8080)
check(
    "space before =",
    rule_1("PORT =8080"),
    None,
    "<- spec lists PORT=N; is 'PORT = 8080' rule 2's job only?",
)
check("--port with no digits", rule_1("--port "), None)
check("localhost with path", rule_1("localhost:3000/health"), 3000)
check("${PORT:-N} lowercase", rule_1("port=${PORT:-8080}"), 8080)
check(
    "${PORT:-N} inner name differs",
    rule_1("PORT=${APP_PORT:-8080}"),
    None,
    "<- spec writes the form as PORT=${PORT:-N} exactly",
)
check("two matches, first wins", rule_1("PORT=8080 and --port 9090"), 8080)

print()
print("=== § 4.6 rule 2: the ten-line table ===")
for line, want in [
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
]:
    check(f"rule_2({line!r})", rule_2(line), want)

print("=== § 4.6 rule 2: INV-9's underscore claim, both directions ===")
check("rule_2 admits _ (DEFAULT_PORT)", rule_2("DEFAULT_PORT = 4322"), 4322)
check("rule_2 admits _ (server_port)", rule_2("server_port: 5000"), 5000)
check("rule_2 admits _ (APP_PORT)", rule_2("APP_PORT=4321"), 4321)
check("rule_1 excludes _ (APP_PORT)", rule_1("APP_PORT=4321"), None)

print("=== § 4.6 rule 2: numbers it must NOT fabricate ===")
for line in ["PORT = 123456", "port: 999999", "MY_PORT=70000", "PORT = 0"]:
    check(f"rule_2({line!r})", rule_2(line), None)

print("=== § 4.6 / INV-19: comments are stripped, quote-aware ===")
for line, want in [
    ("# PORT=9999 (old)", None),
    ("#  PORT=9999", None),
    ("// PORT = 9999", None),
    ("   # PORT=8080", None),
    ("PORT=8080  # was 9090", 8080),
    ("PORT = 8080  // note with # inside", 8080),
    ("http://localhost:3000/", None),  # rule 1's form; `//` is not a comment
    # `;` is a statement separator, not a comment marker, in every language
    # this module reads. Including it lost the port on all three of these.
    ("cd /app ; exec node serve.mjs --port 8080", None),  # rule 1's job
    ('"dev": "cd app ; vite --port 5173"', None),  # rule 1's job
    ('NAME = "a # b"', None),
    ('opts = {"port": 5173}  # dev', 5173),
]:
    check(f"comment {line!r}", rule_2(line), want)
check("rule_1 also strips", rule_1("# PORT=9999"), None)
check(
    "';' must NOT eat a shell separator",
    rule_1("cd /app ; exec node s.mjs --port 8080"),
    8080,
)
check(
    "';' must NOT eat an npm script", rule_1('"dev": "cd app ; vite --port 5173"'), 5173
)
check("';' must NOT eat a shell assignment", rule_1("export FOO=1 ; PORT=9000"), 9000)

print("=== § 4.6 / INV-19: a negative number is not a port ===")
check("rule_2('PORT = -1')", rule_2("PORT = -1"), None)
check("rule_2('PORT = 80.80')", rule_2("PORT = 80.80"), 80, "first whole number wins")

print("=== § 4.6 rule 2: shapes nothing has tried ===")
check("no digits at all", rule_2("PORT = auto"), None)
check("digits left of separator", rule_2("PORT8080 = x"), None)
check("both separators present", rule_2('opts = {"port": 5173}'), 5173)
check(
    "colon inside a URL value",
    rule_2("PORT=http://localhost:8080"),
    8080,
    "<- '=' branch: right is 'http://localhost:8080', first digits 8080",
)
check("key is exactly port", rule_2("port=1234"), 1234)
check("trailing whitespace key", rule_2("PORT\t= 8080"), 8080)
check("hyphen separated key", rule_2("server-port: 5000"), 5000)

print()
print("=== § 4.6: an out-of-range match must not end the scan (finditer) ===")
check(
    "rule 1: in-range after out-of-range", rule_1("localhost:99999 and PORT=8080"), 8080
)
check("rule 1: out-of-range alone", rule_1("localhost:99999"), None)
check(
    "rule 2: in-range after out-of-range",
    rule_2("'server_port': 70000, 'port': 5000"),
    5000,
)
check("rule 2: two numbers, first out of range", rule_2("PORT = 70000 5000"), 5000)
check("rule 2: out-of-range alone", rule_2("PORT = 70000"), None)

print()
print("=== § 4.4: package.json parse failures that are not JSONDecodeError ===")
for label, doc, want in [
    ("20k nested arrays", "[" * 20000 + "]" * 20000, "RecursionError"),
    ("invalid utf-8", b"\xff\xfe{}", "UnicodeDecodeError"),
    ("non-object root", "[1,2]", "AttributeError"),
]:
    try:
        parsed = json.loads(doc.decode("utf-8-sig") if isinstance(doc, bytes) else doc)
        parsed.get("scripts")
        got = "parsed"
    except Exception as exc:  # classifying the exception IS the check
        got = type(exc).__name__
    check(f"package.json {label}", got, want)
check(
    "RecursionError is a ValueError",
    issubclass(RecursionError, ValueError),
    False,
    "<- why the spec names it separately",
)

print()
print("=== § 4.4: package.json — what the port rules must NEVER see ===")
for pair, note in [
    ('"get-port": "^7.0.0"', "a real npm package"),
    ('"detect-port": "^1.5.1"', "another one"),
]:
    got = rule_2(pair)
    if got is not None:
        print(f"  note  rule_2({pair!r}) -> {got!r} ({note})")
        print("        ^ WHY dependencies are never offered to the port rules")
check(
    "dependency blocks are excluded by SCOPE, not by the rules",
    rule_2('"get-port": "^7.0.0"') is not None,
    True,
    "the rules DO match it; § 4.4 keeps them away from it",
)

print()
print("=== § 4.4 step 3: the Environment= prefix must be removed first ===")
raw = "Environment=STATS_PORT=4321 STATS_REFRESH_HOURS=24"
with_prefix = [rule_1(tok) or rule_2(tok) for tok in raw.split()]
check(
    "split WITH the prefix finds nothing",
    any(with_prefix),
    False,
    "<- this is why properties() strips NAME=",
)
without = [rule_1(tok) or rule_2(tok) for tok in raw.split("=", 1)[1].split()]
check("split WITHOUT the prefix finds 4321", next(p for p in without if p), 4321)

print()
print("=== § 4.4 step 3: ExecStart is exempt from the comment stripper ===")
rec = "{ path=/usr/bin/node ; argv[]=/usr/bin/node serve.mjs --port 5000 ; pid=0 }"
# With `;` dropped from the marker set this record survives stripping. The
# exemption is kept on the scope argument (a property value is not a file
# line), NOT on this measurement — which no longer reproduces, and saying so
# is the point: a rule resting on a stale reason is one someone later deletes.
check(
    "record survives the two-marker stripper",
    bool(re.search(r"argv\[\]=([^;]*)", strip_comment(rec))),
    True,
)
check(
    "a '#' inside a quoted command is still cut",
    strip_comment("argv[]=/bin/sh -c 'x --port 8080 # prod'"),
    "argv[]=/bin/sh -c 'x --port 8080",
)
argv = re.search(r"argv\[\]=([^;]*)", rec)
check(
    "extracting first preserves the port", rule_1(argv.group(1)) if argv else None, 5000
)

print()
print("=== § 4.6: line-major within one source ===")
src = ["SERVER_PORT = 3000", "exec node serve.js --port 8080"]
line_major = next((p for ln in src for p in [rule_1(ln) or rule_2(ln)] if p), None)
whole_file_rule_1_first = next(
    (p for fn in (rule_1, rule_2) for ln in src for p in [fn(ln)] if p), None
)
check("line-major picks the earlier line", line_major, 3000)
check("rule-major would pick the later one", whole_file_rule_1_first, 8080)
check(
    "the two orderings differ, so the choice matters",
    line_major != whole_file_rule_1_first,
    True,
)

print()
print("=== § 4.6: file-major vs rule-major, INV-10's fixture ===")
LAUNCHER, HOP = "SERVER_PORT = 3000", "--port 8080"
file_major = rule_1(LAUNCHER) or rule_2(LAUNCHER) or rule_1(HOP) or rule_2(HOP)
rule_major = rule_1(LAUNCHER) or rule_1(HOP) or rule_2(LAUNCHER) or rule_2(HOP)
check("file-major result", file_major, 3000)
check("rule-major result", rule_major, 8080)
check("the fixture discriminates", file_major != rule_major, True)

print()
print("=== ADR-0003 unit-name validation (INV-8) ===")
UNIT_NAME = re.compile(r"^[A-Za-z0-9@:_.\-]{1,255}\.(service|socket|target|timer)$")


def valid_unit(name: str) -> bool:
    return bool(UNIT_NAME.match(name)) and not name.startswith("-")


for name, want in [
    ("project-a.service", True),
    ("app@autostart.service", True),
    ("x.socket", True),
    ("--host=evil.example.service", False),
    ("-M.service", False),
    ("has space.service", False),
    ("x.mount", False),
    ("a" * 250 + ".service", True),
    ("a" * 300 + ".service", False),
    ("x.service\nevil.service", False),
]:
    check(f"valid_unit({name[:34]!r})", valid_unit(name), want)

print()
print("=== § 4.4 step 3: parsing systemd's Environment= and ExecStart= ===")
env_line = "STATS_PORT=4321 STATS_REFRESH_HOURS=24"
pairs = env_line.split()
found = next((p for pair in pairs for p in [rule_1(pair) or rule_2(pair)] if p), None)
check("Environment split then matched", found, 4321)
check(
    "unsplit misses a port that is not first",
    rule_2("REFRESH=24 STATS_PORT=4321"),
    None,
    "<- confirms the spec's reason for splitting: unsplit yields nothing",
)

exec_start = (
    "{ path=/usr/bin/node ; argv[]=/usr/bin/node serve.mjs --port 8080 ; pid=0 }"
)
argv_field = re.search(r"argv\[\]=([^;]*)", exec_start)
check("argv[] extracted", bool(argv_field), True)
check(
    "port from argv[] only", rule_1(argv_field.group(1)) if argv_field else None, 8080
)
check(
    "rule_2 NOT run over ExecStart",
    rule_2(exec_start),
    None,
    "<- spec says rule 2 is not run over it; confirm it would be harmless anyway",
)

print()
print("=== § 4.4 step 1: undoing systemd's \\xNN escaping ===")


def unescape_unit(name: str) -> str:
    return re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), name)


check(
    "escaped stem",
    unescape_unit("app-ai\\x2dprompts\\x2dtray@autostart.service"),
    "app-ai-prompts-tray@autostart.service",
)
check("unescaped passthrough", unescape_unit("project-a.service"), "project-a.service")

print()
print("=== § 4.3: the bounds, executed ===")
d = Path(tempfile.mkdtemp())

# O_NOFOLLOW refuses a symlinked launcher (INV-1, loop 2's CRITICAL)
secret = d / "outside.txt"
secret.write_text("PORT=1234\n")
proj = d / "proj"
proj.mkdir()
os.symlink(secret, proj / "start.sh")
try:
    os.open(proj / "start.sh", os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    check("O_NOFOLLOW refuses a symlinked launcher", "opened", "refused")
except OSError:
    check("O_NOFOLLOW refuses a symlinked launcher", "refused", "refused")

# S_ISREG alone does NOT (the reason O_NOFOLLOW is needed)
fd = os.open(proj / "start.sh", os.O_RDONLY | os.O_NONBLOCK)
check(
    "S_ISREG alone passes a symlink",
    stat.S_ISREG(os.fstat(fd).st_mode),
    True,
    "<- this is WHY O_NOFOLLOW is required",
)
os.close(fd)

# readline caps a line and the tail is discarded
long_line = d / "long.sh"
long_line.write_text("x" * 5000 + "PORT=9999\n")
with long_line.open() as fh:
    first = fh.readline(4096)
check("over-long line clipped to the cap", len(first), 4096)
check("port past the cap is not found", rule_1(first), None)

# a minified package.json survives _read_bytes and dies under _read_lines
pkg = json.dumps(
    {
        "scripts": {"dev": "vite --port 5173"},
        "devDependencies": {f"p{i}": "^1.0.0" for i in range(300)},
    }
)
check("minified package.json is one line", pkg.count("\n"), 0)
check("minified package.json exceeds the line cap", len(pkg) > 4096, True)
try:
    json.loads(pkg[:4096])
    check("line-capped package.json parses", "parses", "raises")
except json.JSONDecodeError:
    check("line-capped package.json parses", "raises", "raises")
check("whole-file package.json parses", bool(json.loads(pkg)), True)

print()
print("=== INV-15: the matcher's cost at the line cap ===")
for label, line in [
    ("4096-char key", ("a" * 4088 + "port = 1")[:4096]),
    ("102 colon fields", ":".join(["x" * 40] * 102)[:4096]),
    ("the OLD fixture", "a" * 4092 + "port"),
]:
    t = time.perf_counter()
    for _ in range(500):
        rule_2(line)
    per = (time.perf_counter() - t) / 500
    reaches = "=" in line or ":" in line
    print(f"  {label:18s} {per * 1e6:8.2f} us/call   reaches the regex: {reaches}")
    if reaches and per > 1.0:
        FAILS.append(f"INV-15: {label} exceeds the 1 s ceiling")

print()
print("=== § 4.5: commonpath containment ===")
root = (d / "proj").resolve()
for target, want in [
    (root / "launcher.py", True),
    (root / "src" / "app" / "cfg.py", True),
    ((root / ".." / "outside.txt").resolve(), False),
    (Path("/etc/shadow"), False),
]:
    inside = os.path.commonpath([str(root), str(target)]) == str(root)
    check(f"contained({str(target)[-28:]!r})", inside, want)

depth_ok = len((root / "a" / "b" / "c" / "d.py").relative_to(root).parts) <= 3
check("4-deep target exceeds the 3-component bound", depth_ok, False)
excluded = {
    "node_modules",
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "dist",
    "build",
    ".cache",
}
hit = set((root / "node_modules" / "x.py").relative_to(root).parts) & excluded
check("node_modules target is excluded", bool(hit), True)

print()
print("=== § 4.5: a NUL byte in a hop token (registry.py's guard, swept in) ===")
nul_target = root / "laun\x00cher.py"
check(
    "commonpath accepts a NUL happily",
    os.path.commonpath([str(root), str(nul_target)]) == str(root),
    True,
    "<- which is why the guard cannot live there",
)
for label, fn in (
    ("resolve()", lambda: nul_target.resolve()),
    ("os.open()", lambda: os.open(nul_target, os.O_RDONLY)),
):
    try:
        fn()
        got = "no error"
    except ValueError:
        got = "ValueError"
    except OSError:
        got = "OSError"
    check(f"NUL token: {label} raises", got, "ValueError", "<- NOT an OSError")

print()

print()
print("=" * 70)
if FAILS:
    print(f"{len(FAILS)} CONFORMANCE FAILURES — each is a defect in the spec:")
    for f in FAILS:
        print(f"  - {f}")
else:
    print("All conformance checks pass.")
