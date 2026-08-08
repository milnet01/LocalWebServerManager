# LWSM-1006 — Detect projects, their launchers and their declared ports

**Status:** spec draft (2026-08-08).
**Kind:** implement.
**Source:** ROADMAP LWSM-1006 (in-session-2026-08-03), narrowed by the user
on 2026-08-08 under the size gate (`docs/standards/spec-format.md § 5.4`).
**Blocked by:** LWSM-1005 (shipped 2026-08-07).
**Blocker for:** LWSM-1007 (registry persistence and the rescan merge),
LWSM-1121 (the remaining port sources and conflict reporting).
**Pairs with:** LWSM-1050 — this item lands that bullet's implementation, per
its own text; LWSM-1050 does not ship separately.

**Layman:** Teach the app to look through a folder of projects and work out,
for each one, how it starts and which port it wants — and to say plainly when
it cannot tell, rather than guessing.

## 1. Goal

After this ships, `projects.json` no longer has to be hand-written. Given one
or more scan roots, the app produces a list of candidate projects, each with a
launcher it could actually run and — where the project says so anywhere the
rules can reach — a declared port, labelled with which rule found it and in
which file. Where nothing says, the project comes back honestly *unknown*
rather than carrying a guess. Everything the Scanner reads belongs to somebody
else, so it also ships the bounds that make reading it safe: LWSM-1050's
per-file cap, per-line cap, per-line deadline, symlink refusal, non-regular
refusal and containment check.

## 2. Problem

The registry exists and reads a file that nothing writes.
`src/lwsm/registry.py::load_projects` parses `projects.json` into
`ProjectRecord`s, and `src/lwsm/registry.py::default_projects_path` names
where that file lives — but no code path creates it. A first run therefore
raises `RegistryError` and `src/lwsm/__main__.py::build_window` opens an empty
window with a reason. That is correct behaviour for a missing file and useless
behaviour for a new user.

Three consequences, which the invariants in § 5 trace back to:

1. **Nothing discovers a project.** `docs/discovery.md` success criterion 1 is
   graded on a first run with no config finding all seven known projects with
   the right launcher and port. No code attempts it.
2. **`ProjectRecord.effective_port`'s lower rungs are unreachable.** Its
   docstring already names this item as the owner of rung 4, the framework
   default. Rungs 3 and 4 both arrive from detection, so the precedence chain
   in `docs/design.md § The effective port` is currently a two-rung chain
   pretending to be four.
3. **LWSM-1050's hardening has a contract and no code.** The bounds landed in
   `docs/design.md § Everything the Scanner reads is hostile until proven
   otherwise` on 2026-08-03 and that bullet routes the implementation here. It
   is not deferrable work: the first line of scanner code that opens a
   sibling's file is the line that needs them.

## 3. Scope decisions (agreed with the user)

- **The spec was split before drafting** (user, 2026-08-08). The three
  remaining sources `design.md § Robustness` measure 2 names — `.env` /
  `.env.local`, `docker-compose.yml`, `README.md` — and measure 3's conflict
  reporting moved to **LWSM-1121**. None of the seven known projects is
  detected by them, so they are robustness beyond this item's acceptance test
  rather than part of it. The systemd unit stayed here, because for a
  `systemd` project the unit *is* the launcher.
- **Port rule 3, the framework default, is built rather than deleted** (user,
  2026-08-08). `design.md § Detection rules` invites deleting it if it stays
  unused, and none of the seven needs it. It is built because it is a handful
  of lines already in the contract, and the fixture tree gains one project that
  has a framework and no port anywhere, so the rule is exercised rather than
  carried untested.
- **PROPOSED, and not yet confirmed — the recursive walk is not built.** Every
  launcher rule in `design.md § Detection rules` matches at the project root,
  and the one-hop port-bearing file is *named by the launcher* and opened
  directly, not found by searching. So nothing in this item's rule set reads a
  file that a walk would have to find, and building a three-level walk to feed
  no reader is the scaffolding `coding.md § 1.1` forbids. The depth bound and
  the eight excluded directory names are not dropped: they become constraints
  on the one-hop target (§ 4.5), where they are the only place they can still
  do work. **This diverges from `design.md § Detection rules` § Where it
  looks**, so it is surfaced here per `.claude/workflow.md § 2`'s no-silent-
  drift rule rather than absorbed; § 12 carries the amendment that follows if
  the user confirms it. If the user prefers the walk built as written, § 4.2
  gains it and this decision is struck.

## 4. Design

One new core module, `src/lwsm/scanner.py`. No Qt at all — not even `QtCore`,
matching `src/lwsm/ports.py`, because nothing here emits a signal.

### 4.1 What the Scanner returns

```python
class LauncherKind(enum.Enum):
    SYSTEMD = "systemd"
    SHELL = "shell"
    NODE = "node"
    PYTHON = "python"


class PortRule(enum.Enum):
    """Which rule produced a port. The value is what the UI shows."""

    EXPLICIT = "an explicit port setting"  # port rule 1
    ASSIGNMENT = "a port assignment"  # port rule 2
    FRAMEWORK_DEFAULT = "a framework default"  # port rule 3


@dataclass(frozen=True)
class PortFinding:
    port: int
    rule: PortRule
    file: Path  # the file it was read from, absolute
    line: str  # the matched line, already clipped by § 4.3


@dataclass(frozen=True)
class DetectedProject:
    path: Path  # absolute, the identity (ADR-0005)
    name: str  # the directory's own name
    kind: LauncherKind
    argv: tuple[str, ...]  # empty for SYSTEMD; the unit drives it
    unit: str | None  # set only for SYSTEMD
    port: PortFinding | None  # None means "unknown", never a guess


@dataclass(frozen=True)
class ScanResult:
    projects: tuple[DetectedProject, ...]
    skipped: tuple[str, ...]  # one clipped reason per rejected candidate
    timed_out: bool  # the budget expired; `projects` is partial
```

**`DetectedProject` has no `actions` field and no user-owned field of any
kind.** That is the structural half of `design.md § Custom project actions`'s
rule that detection never authors an executable action, and of ADR-0005's
two-halves split. A merge that wanted to promote scanned content into an
executable one would have to add the field first, which is a visible change
rather than a forgotten one.

**`argv` is a tuple of strings, never a command line** (`coding.md § O4`).
`("./start.sh",)`, `("npm", "run", "dev")`, `("python3", "serve.py")`,
`("node", "serve.mjs")`. For `SYSTEMD` it is empty and `unit` is set, because
ADR-0003's verb table — not this module — builds `systemctl`'s argv.

### 4.2 Choosing candidates

```python
def scan(
    roots: Sequence[Path],
    *,
    units: SupportsUnitLookup | None = None,
    now: Callable[[], float] = time.monotonic,
    budget_seconds: float = SCAN_BUDGET_SECONDS,
) -> ScanResult: ...
```

`roots` is passed in rather than read from settings: settings persistence is
LWSM-1007's, and a Scanner that reads the real config could not satisfy
`testing.md § T1`. `now` is injected for the same reason the budget test needs
to be deterministic rather than slow.

A candidate is an **immediate subdirectory** of a scan root. Four candidates
are rejected before anything is read, each with a reason in `skipped`:

1. **Not a directory.**
2. **A symlink.** Refused rather than resolved. Measured 2026-08-08 on Python
   3.13.14: `os.walk(followlinks=False)` declines to *descend* into a
   symlinked subdirectory but still lists it in `dirnames`, and walking a
   symlinked directory **as the top** follows it — a scan of `<root>/proj_link`
   pointing at `<root>/proj` returned `['proj_link', 'real']`. So
   `followlinks=False` is not the guard at candidate level; refusing the
   candidate is.
3. **This application's own directory.** A candidate is skipped when
   `Path(lwsm.__file__).resolve()` is inside it. Measured 2026-08-08 under the
   editable install: that resolves to
   `…/LocalWebServerManager/src/lwsm/__init__.py`, so the repository's own
   directory is recognised without hard-coding a path. Once P01's launcher
   exists the manager would otherwise list and offer to launch itself.
4. **No launcher matched** (§ 4.4). A candidate with no match is not a server
   project and is not listed.

The **20-second budget** (`SCAN_BUDGET_SECONDS = 20.0`) is checked before each
candidate and, inside a file read, **before each line** — not once per scan. A
wall-clock check between files cannot interrupt work already under way. On
expiry the scan returns what it has with `timed_out=True`, rather than hanging
a first run.

### 4.3 Reading somebody else's file

```python
MAX_SOURCE_FILE_BYTES = 256 * 1024
MAX_SOURCE_LINE_CHARS = 4096


def _read_lines(path: Path, deadline: Deadline) -> list[str]: ...
```

Named `MAX_SOURCE_*` rather than reusing `registry.py`'s `MAX_FILE_BYTES`,
because they are different numbers for different jobs — 1 MiB for a config
file this app owns, 256 KB for a sibling's source — and one name for two
values is the ambiguity `documentation.md § 1.5` bans.

Six bounds, all of them LWSM-1050's:

- Opened `O_RDONLY | O_NONBLOCK`, then `fstat` on the raw descriptor: refused
  unless `stat.S_ISREG`. A FIFO at `start.sh` would otherwise block `open()`
  until a writer appears — the failure `registry.py::_read_bounded` was
  written for, reproduced there on 2026-08-06.
- Refused above `MAX_SOURCE_FILE_BYTES`, checked on the `fstat` size *and*
  again on the bytes actually read, so a file that grows between the two is
  still refused.
- Read with `readline(MAX_SOURCE_LINE_CHARS)`. Measured 2026-08-08: that
  returns at most the cap and leaves the remainder for the next call, so a
  100,000-character single line came back as 25 chunks. **The remainder of an
  over-long line is discarded rather than scanned**, which is what stops a
  pattern being split across a chunk boundary and matching half of itself.
- The deadline is checked before each line.
- Decoded `utf-8` with `errors="replace"`. A sibling's file is not required to
  be text, and a `UnicodeDecodeError` three levels into someone else's repo is
  not a fact worth stopping a scan for.
- Any `OSError` rejects that file with a reason and continues. A permission
  denial on one project is not a failure of the scan.

**Sweep, per `coding.md § 1.6`.** The other bounded-read sites are
`applog.py::_NoFollowRotatingFileHandler` (a *write* path, and stricter — it
demands one link and our own ownership) and `registry.py::_read_bounded` (our
own config, weaker — no line cap, no deadline, 1 MiB). Both were enumerated;
neither changes. § 8 records why this is a third implementation rather than an
extraction.

### 4.4 Launcher rules, first match wins

Numbered as `design.md § Detection rules` numbers them, from 0. These are
*launcher* rules; § 4.6's are *port* rules, and both start at 1 in the
original, which is why each is always named in full.

| # | Match | `kind` | `argv` |
|---|---|---|---|
| 0 | a bound systemd user unit (below) | `SYSTEMD` | empty; `unit` set |
| 1 | executable `start.sh`, else executable `run.sh` | `SHELL` | `("./start.sh",)` |
| 2 | `package.json` with `scripts.dev`, else `scripts.start` | `NODE` | `("npm", "run", "dev")` |
| 3 | `serve.py`, else `server.py`, else `app.py` | `PYTHON` | `("python3", "serve.py")` |
| 4 | `serve.mjs`, else `serve.js` | `NODE` | `("node", "serve.mjs")` |

Every path is at the project root, and every within-rule list is ordered: rule
1 prefers `start.sh`, rule 3 prefers `serve.py`, rule 4 prefers `serve.mjs`.

**Rule 1 requires the execute bit** (`os.access(path, os.X_OK)`) and a regular
file. A `start.sh` without it is not a launcher match, and the reason is
recorded — running it would fail at spawn time with a message about a file the
user never chose.

**Rule 2 parses `package.json` through § 4.3's bounded read.** A malformed or
oversized one is not a match, with a reason. `scripts` must be an object and
the chosen value a non-empty string.

**Rule 0 — the systemd path.** Detection is two steps, because ADR-0003
requires both and `design.md § Detection rules` states only the first:

1. **Propose by name.** `systemctl --user list-unit-files --type=service
   --output=json` lists the units. Measured 2026-08-08 against systemd 261.2:
   it returns `[{"unit_file": "ants-stats.service", "state": "enabled",
   "preset": "disabled"}, …]`. JSON rather than the column layout, because
   parsing columns out of a name that may contain escaped bytes
   (`app-ai\x2dprompts\x2dtray@autostart.service` appears in that output) is a
   guess. A unit is proposed when its stem equals the candidate directory's
   name.
2. **Bind by location, never by name** (ADR-0003, security review
   2026-08-03). `systemctl --user show -- <unit> -p FragmentPath -p
   WorkingDirectory` must return at least one path that resolves **inside** the
   candidate directory. Without this, `mkdir <scan root>/project-a` — an empty
   directory with no code in it — is enough to make the UI present a row whose
   Start and Stop drive somebody else's service.

   Measured 2026-08-08: `systemctl --user show` on a unit that does not exist
   **exits 0** and prints a synthesised record, so the exit code is not the
   signal. An empty `FragmentPath` is.

**A unit name is untrusted input.** It is validated against ADR-0003's
`^[A-Za-z0-9@:_.\-]{1,255}\.(service|socket|target|timer)$`, a leading `-` is
rejected, and `--` is passed before it in every `systemctl` argv this module
builds. A name beginning with `-` is consumed by `systemctl` as an option —
`--host=`, `-M`, `--machine=` all redirect which manager is driven.

`units` is a `SupportsUnitLookup` Protocol, defaulting to a real `systemctl`
caller, exactly as `ports.py` accepts `SupportsSnapshot` so the test fake is
the contract. `testing.md § T1` forbids a test touching the real service
manager, and a machine with no `systemd` at all must scan normally: a
`FileNotFoundError` on `systemctl` disables rule 0 for the whole scan and is
recorded once, not once per candidate.

### 4.5 The one-hop port-bearing file

Only for `kind == SHELL`, because that is the only launcher that runs another
file whose name it names. The script is scanned for the **last** `exec`,
`python3`, `python` or `node` invocation naming a path, and exactly one hop is
followed — `project-e` puts its port two hops out (`run.sh` → `launcher.py` →
`config.py`) and is expected back as *port unknown*, which is an honest limit
rather than a bug.

The target is accepted only when **all five** hold, checked after resolution:

1. `os.path.commonpath` of the resolved target and the resolved project root
   is the project root. This is what stops `exec python3 ../../../.ssh/config`
   being read and its contents surfacing in the UI as a detected value.
2. It is a regular file (§ 4.3's `fstat`, not a `Path.is_file()` race).
3. None of its path components below the project root is one of
   `node_modules`, `.git`, `.venv`, `venv`, `__pycache__`, `dist`, `build`,
   `.cache`.
4. It is at most **3 path components** below the project root.
5. It is not the launcher itself, so a script that `exec`s its own name cannot
   loop.

Constraints 3 and 4 are `design.md`'s exclusion list and depth bound, applied
at the only place this item still reads a file below the root. § 3's proposed
scope decision is what moved them here.

### 4.6 Port rules, first match wins

**Rule 1 — an explicit port setting.** Anywhere in the file:
`PORT=N`, `PORT=${PORT:-N}`, `--port N`, `--port=N`, `localhost:N`,
`127.0.0.1:N`.

**Rule 2 — an assignment whose key is a port.** Implemented as a
non-backtracking two-step: partition the line on `=` and then on `:`, take the
left side, and require the key to match `(?:^|[^A-Za-z0-9])port$`
case-insensitively (or to be exactly `port`) after surrounding quotes are
stripped. Then `re.search(r"\d+")` on the right.

**The key must not merely *end in* the letters `port`, which is what
`design.md` says.** Measured 2026-08-08, the literal rule accepts
`const viewport = 1280` → 1280, `transport = 4` → 4, `report: 7` → 7 and
`export = 5` → 5; `viewport` in particular is ordinary in a web project's
config. Requiring a non-alphanumeric character before `port` keeps every
example `design.md` gives and rejects all four:

| Line | Literal "ends in port" | This rule |
|---|---|---|
| `PORT = 8765` | 8765 | 8765 |
| `DEFAULT_PORT = 4322` | 4322 | 4322 |
| `'server_port': 5000` | 5000 | 5000 |
| `"port": 5173` | 5173 | 5173 |
| `const PORT = Number(process.env.PROJECT_A_PORT) \|\| 4321` | 4321 | 4321 |
| `export PORT=8080` | 8080 | 8080 |
| `const viewport = 1280` | **1280** | none |
| `transport = 4` | **4** | none |
| `report: 7` | **7** | none |
| `export = 5` | **5** | none |

Produced 2026-08-08 by running both rules over those ten lines under
`uv run python3` on 3.13.14; § 7 ships the table as a parametrised test so the
figures are an output rather than a transcription.

**Rule 3 — a framework default**, only when neither rule 1 nor rule 2 found
anything **in either file**. The framework is identified from evidence the
scan has already read, never from a new file:

| Framework | Identified by | Default |
|---|---|---|
| Vite | `vite` in `package.json`'s `dependencies` / `devDependencies`, or in the chosen `scripts` value | 5173 |
| Django | a root-level `manage.py`, or `import django` in the launcher's Python file | 8000 |
| Flask | `import flask` / `from flask import` in the launcher's Python file | 5000 |

**Order is file-major, and `design.md` does not say which.** "Port rules, first
match wins, searched in the launcher and then in the one-hop file" admits two
readings, and they disagree: with `PORT_BASE = 3000` in the launcher and
`--port 8080` in the hop file, rule-major returns 8080 and file-major returns
3000. This spec fixes **file-major** — rules 1 then 2 within the launcher,
then rules 1 then 2 within the one-hop file, then rule 3 across both. The
launcher is the file that actually runs, and rule 3's own wording ("only when
neither port rule 1 nor port rule 2 found anything") already scopes across
both files, which only file-major makes coherent. § 12 carries the amendment.

A port outside 1–65535 is not a match, and the search continues. That is
`registry.py`'s `DECLARED_PORT_RANGE`, deliberately not ADR-0005's
1024–65535 — a project may legitimately declare 80.

### 4.7 The layering list widens

`tests/test_layering.py`'s `CORE_MODULES` gains **`scanner.py` and
`applog.py`** in the commit that creates the module. `coding.md § O1` requires
the first and names the second: the criterion covers `applog.py`, the list
omits it, "the check is the one that runs", and widening it is this item's
job. Without that line a `QtWidgets` import in either module passes every gate.

## 5. Invariants

- **INV-1** — No file outside a candidate's own resolved directory is opened.
  *Test:* `tests/test_scanner.py::test_a_hop_out_of_the_project_is_refused`.
  *Breaks when:* a `run.sh` whose last invocation is
  `exec python3 ../../../.ssh/config`, or a symlink inside the project whose
  target resolves outside it.

- **INV-2** — A candidate directory that is itself a symlink is skipped, with
  a reason, and nothing inside it is read.
  *Test:* `tests/test_scanner.py::test_a_symlinked_candidate_is_not_scanned`.
  *Breaks when:* `<root>/proj` is a symlink to `/etc` — measured 2026-08-08 to
  be walked normally under `followlinks=False`, which is why this is a
  candidate-level guard rather than a walk argument.

- **INV-3** — No file contributes more than `MAX_SOURCE_FILE_BYTES`, and no
  line more than `MAX_SOURCE_LINE_CHARS`; the remainder of an over-long line
  is discarded rather than scanned.
  *Test:* `tests/test_scanner.py::test_an_oversized_file_is_refused` and
  `::test_an_over_long_line_is_clipped_and_its_tail_not_scanned`, the second
  planting `PORT=9999` past the cap and asserting it is not found.
  *Breaks when:* a 2 GB `README.md`, or a single 100 MB line.

- **INV-4** — A non-regular file at a launcher or hop path is refused on the
  descriptor, not opened for reading.
  *Test:* `tests/test_scanner.py::test_a_fifo_launcher_does_not_block`, under
  a `SIGALRM` guard raising a `BaseException` subclass so the guard cannot be
  swallowed by the assertion it protects.
  *Breaks when:* a FIFO at `start.sh` with no writer.

- **INV-5** — A scan returns within its budget and says so, rather than
  running to completion.
  *Test:* `tests/test_scanner.py::test_the_budget_stops_a_scan_mid_candidate`,
  driving the injected `now` past the deadline and asserting `timed_out` is
  true and `projects` is shorter than the candidate list.
  *Breaks when:* the deadline is checked once per scan instead of per line and
  per candidate, and one pathological file consumes the whole budget.

- **INV-6** — Launcher rules match in the stated order, and a candidate with
  no match is not listed.
  *Test:* `tests/test_scanner.py::test_launcher_precedence`, parametrised over
  the five rules with a project carrying every lower-precedence marker as
  well.
  *Breaks when:* a project with both an executable `start.sh` and a
  `package.json` comes back as `NODE`.

- **INV-7** — A systemd unit is bound to a project only when its
  `FragmentPath` or `WorkingDirectory` resolves inside that project.
  *Test:* `tests/test_scanner.py::test_a_name_match_alone_does_not_bind_a_unit`.
  *Breaks when:* an empty directory is created whose name matches a real unit
  belonging to another project.

- **INV-8** — A unit name failing ADR-0003's pattern never reaches an argv,
  and every `systemctl` argv this module builds carries `--` before the name.
  *Test:* `tests/test_scanner.py::test_a_hostile_unit_name_is_rejected`,
  parametrised over a leading `-`, an embedded space, a 300-character name and
  a `.mount` suffix.
  *Breaks when:* a unit named `--host=evil.example.service` is proposed.

- **INV-9** — Port rule 2 matches a key that is `port` or ends with a
  non-alphanumeric character followed by `port`, and no other.
  *Test:* `tests/test_scanner.py::test_port_rule_2_keys`, parametrised over
  § 4.6's ten lines.
  *Breaks when:* `const viewport = 1280` is scanned — measured 2026-08-08 to
  return 1280 under the rule as `design.md` words it.

- **INV-10** — Port rules resolve file-major: rules 1 then 2 in the launcher,
  then rules 1 then 2 in the one-hop file, then rule 3 across both.
  *Test:* `tests/test_scanner.py::test_the_launcher_outranks_the_hop_file`,
  with `PORT_BASE = 3000` in the launcher and `--port 8080` in the hop file.
  *Breaks when:* the implementation iterates rules outermost, which returns
  8080 for that fixture.

- **INV-11** — The `rule` and `file` a finding reports are the ones that
  actually produced it, and a project with no readable port has `port is None`
  rather than a substitute.
  *Test:* `tests/test_scanner.py::test_a_finding_reports_the_rule_that_matched`,
  parametrised over one fixture per rule and asserting the exact
  `(rule, file.name)` pair, and
  `::test_project_e_shape_comes_back_unknown`.
  *Breaks when:* a port read from the one-hop file is labelled as coming from
  the launcher, or the framework default is applied to a project whose
  launcher identifies no framework, turning *unknown* into 5000.
  **Asserting mere presence would be a tautology** — `PortFinding` is a frozen
  dataclass whose `rule` and `file` are required, so they cannot be absent and
  a presence test could never fail. The pair has to be checked against the
  fixture that produced it.

- **INV-12** — `DetectedProject` carries no user-owned field: no `actions`, no
  display-name override, no port override, no hidden flag.
  *Test:* `tests/test_scanner.py::test_a_detected_project_has_no_user_owned_field`,
  asserting the dataclass's field names against an explicit allowed set.
  *Breaks when:* a later change adds `actions` so a merge can carry it, which
  is exactly the promotion `design.md § Custom project actions` forbids.

- **INV-13** — The Scanner writes nothing anywhere: no file created, modified,
  or removed under any scan root.
  *Test:* `tests/test_scanner.py::test_a_scan_leaves_the_tree_byte_identical`,
  comparing a recursive `(path, size, mtime_ns, mode)` snapshot of the fixture
  tree before and after.
  *Breaks when:* a future convenience writes a cache or a marker into a
  project — `coding.md § O3`'s standing prohibition.

- **INV-14** — `scanner.py` imports no `QtWidgets`, and both it and
  `applog.py` are named in `tests/test_layering.py`'s `CORE_MODULES`.
  *Test:* `tests/test_layering.py::test_core_never_imports_qtwidgets`
  (parametrised, so the names being present is what makes it run) and
  `::test_the_core_module_list_matches_the_criterion`, a new source-invariant
  test deriving the expected list from `coding.md § O1`'s criterion — every
  module under `src/lwsm/` that is not `mainwindow.py` or `theme.py`.
  *Breaks when:* a sixth core module lands and is not added to the list, which
  is how `applog.py` came to be missing from it.

- **INV-15** — Scanning a line is linear in its length: a 40,000-character
  line completes in well under a second.
  *Test:* `tests/test_scanner.py::test_a_long_line_does_not_backtrack`,
  asserting a 1-second ceiling on `MAX_SOURCE_LINE_CHARS` × 10 characters.
  *Breaks when:* the two-step is replaced by a single pattern with a nested
  quantifier. Measured 2026-08-08: CPython 3.13.14 still backtracks
  catastrophically — `(a+)+$` against 24 `a`s took **1.10 s**, doubling per
  added character — so the hazard is live in this runtime even though the
  specific pattern `design.md` warns about does not exhibit it (below).

## 6. Failure modes

- **`systemctl` is absent.** Rule 0 is disabled for the whole scan, recorded
  once in `skipped`, and every other rule proceeds. A machine without systemd
  scans normally.
- **`systemctl` hangs.** The subprocess carries a timeout drawn from the same
  deadline as the file reads, and a timeout disables rule 0 exactly as absence
  does. Without this the 20-second budget is a promise the scan cannot keep.
- **A scan root does not exist, or is not readable.** One reason in `skipped`,
  and the other roots are scanned. A missing root is ordinary — an unmounted
  drive — and must not blank the result.
- **A project has a launcher and no readable port source.** `port is None`,
  confidence *unknown*. `design.md` requires Start to be refused until the user
  supplies one; refusing is LWSM-1007's and P05's, and this item's obligation
  is only to not invent a value.
- **Two candidates resolve to the same directory** (two scan roots overlap, or
  one root is inside another). The second is skipped with a reason. ADR-0005
  makes the absolute path the identity, so two records sharing one is
  malformed by construction rather than a merge question.
- **The budget expires with candidates unvisited.** `timed_out=True` and a
  partial list. The caller must present it as partial; a partial list rendered
  as complete would make a rescan look like it had removed projects, which
  ADR-0005's *missing* handling exists to prevent.
- **A file decodes to mojibake.** `errors="replace"` means the rules run over
  replacement characters and simply match nothing. No exception, no reason —
  a binary `app.py` is not an error, it is a non-match.

## 7. Tests

New file `tests/test_scanner.py`, plus two additions to
`tests/test_layering.py`. Every test is headless (`testing.md § T6`); the
module imports no Qt, so none of them needs `pytest-qt`.

**The fixture tree is the deliverable, not scaffolding.** A session-scoped
fixture builds a throwaway tree in `tmp_path` mirroring the seven known
projects — each shape from `docs/discovery.md`'s inventory, including the two
expected back as *unknown* — plus the framework-default project § 3 added.
`design.md § Detection accuracy is a test suite, not an opinion` makes it the
**regression corpus every future mis-detection is added to**, so it lives in
`tests/scanner_fixtures.py` as data, not inline in a test body.

Per `testing.md § T1` no fixture is a real sibling project: every one is
generated. Per `testing.md § T3` no test hard-codes a live port — the ports
here are strings in files, never bound, which is the one case T3's rule about
binding does not reach.

| Invariant | Test |
|---|---|
| INV-1 | `test_a_hop_out_of_the_project_is_refused` |
| INV-2 | `test_a_symlinked_candidate_is_not_scanned` |
| INV-3 | `test_an_oversized_file_is_refused`, `test_an_over_long_line_is_clipped_and_its_tail_not_scanned` |
| INV-4 | `test_a_fifo_launcher_does_not_block` |
| INV-5 | `test_the_budget_stops_a_scan_mid_candidate` |
| INV-6 | `test_launcher_precedence` |
| INV-7 | `test_a_name_match_alone_does_not_bind_a_unit` |
| INV-8 | `test_a_hostile_unit_name_is_rejected` |
| INV-9 | `test_port_rule_2_keys` |
| INV-10 | `test_the_launcher_outranks_the_hop_file` |
| INV-11 | `test_a_finding_reports_the_rule_that_matched`, `test_project_e_shape_comes_back_unknown` |
| INV-12 | `test_a_detected_project_has_no_user_owned_field` |
| INV-13 | `test_a_scan_leaves_the_tree_byte_identical` |
| INV-14 | `test_core_never_imports_qtwidgets`, `test_the_core_module_list_matches_the_criterion` |
| INV-15 | `test_a_long_line_does_not_backtrack` |

Plus the acceptance test the roadmap names:
`test_the_seven_known_shapes_are_detected`, parametrised over the fixture
tree, asserting launcher **and** port — including the *unknown* cases, since a
rule that quietly starts guessing for `project-e` is the regression this
corpus exists to catch.

**Every test is seen failing before the code exists** (`testing.md § 1`), and
the three that guard a *bound* rather than a behaviour are additionally
mutation-checked per `testing.md § T9`: INV-3, INV-4 and INV-15 each have
their guard line removed in place and the named test re-run alone
(`PYTHONDONTWRITEBYTECODE=1 uv run pytest -k <name>`), with the result in the
commit body. Those three are singled out because each can pass for a reason
other than the guard — an oversized file that also fails to parse, a FIFO
whose open fails before the `S_ISREG` check is reached, a fast line that was
never long enough to backtrack. That is `testing.md § T9` item 3: a stub must
be able to express the breach.

## 8. Alternatives considered (and rejected)

- **Extract `registry.py::_read_bounded` into a shared helper rather than
  writing a third bounded reader.** Rejected. The two policies genuinely
  differ — 1 MiB against 256 KB, no line cap against 4096 characters, no
  deadline against a per-line one — so the shared function would take four
  parameters and mean nothing without them. `registry.py` is shipped and
  tested, and refactoring it is scope this item does not own. `coding.md
  § 1.3`'s Rule of Three puts extraction at the third *identical* call site,
  not the third similar one. Revisit if LWSM-1121 needs a fourth.
- **Parse `systemctl --user list-unit-files`'s column output.** Rejected on
  the measurement: that output contains names with escaped bytes
  (`app-ai\x2dprompts\x2dtray@autostart.service`), so column splitting is a
  guess where `--output=json` is a fact. JSON is also the current idiom for
  systemd 261 (`coding.md § 1.5`).
- **Trust `systemctl show`'s exit code to mean the unit exists.** Rejected on
  the measurement: it exits 0 for a unit that does not exist and prints a
  synthesised record. An empty `FragmentPath` is the signal.
- **Treat `design.md`'s "ends in `port`" literally.** Rejected on the
  measurement in § 4.6: it accepts `viewport`, `transport`, `report` and
  `export`, and `const viewport = 1280` is ordinary in the exact kind of
  project this app scans.
- **Bind a systemd unit by directory name alone**, as `design.md § Detection
  rules` launcher rule 0 words it. Rejected because ADR-0003's security review
  already rejected it: an empty directory is then enough to put somebody
  else's service behind a Start button.
- **Emit a `QtCore` signal per candidate so the UI can show progress.**
  Rejected: `scan()` is a pure function of its arguments and stays trivially
  testable without a Qt event loop, matching `ports.py`. Running it off the UI
  thread is the caller's problem, and `controller.py` already owns that shape
  with `QThreadPool`.

## 9. Out of scope

- `.env` / `.env.local`, `docker-compose.yml` and `README.md` as port sources,
  and conflict reporting between disagreeing sources — tracked by LWSM-1121.
- Persisting anything, and the rescan merge — tracked by LWSM-1007.
- `confirmed_port`, rung 2 of the effective-port chain — tracked by LWSM-1038.
- The first-run confirmation flow and the "`~/projects` does not exist, so
  ask" behaviour — tracked by LWSM-1008.
- Refusing Start for a project whose port is *unknown* — tracked by LWSM-1007
  for the registry half and P05 for the launch half.
- Editing a wrong launcher or port on the row (`design.md § Robustness`
  measure 4) — tracked by LWSM-1007.

## 10. Resource cost

No new dependency: `os`, `re`, `json`, `stat`, `enum`, `dataclasses`,
`pathlib`, `subprocess`, `time`. No new build target.

Bounded by construction, and every bound is named: at most
`MAX_SOURCE_FILE_BYTES` (256 KB) resident per file, one file at a time; at
most `MAX_SOURCE_LINE_CHARS` (4096) per line, with the tail discarded rather
than buffered; at most `SCAN_BUDGET_SECONDS` (20) of wall clock. `ScanResult`
holds one `DetectedProject` per candidate and one clipped reason per
rejection, both linear in the number of candidates on disk, which is bounded
by the scan roots the user chose. Reasons are clipped by the same rule
`registry.py::_quoted` applies, for the reason recorded there: an unbounded
one reached both the log and the status bar.

## 11. What checks this

| Rule | What catches a breach |
|------|----------------------|
| INV-1 | `tests/test_scanner.py::test_a_hop_out_of_the_project_is_refused` |
| INV-2 | `tests/test_scanner.py::test_a_symlinked_candidate_is_not_scanned` |
| INV-3 | `tests/test_scanner.py::test_an_oversized_file_is_refused`, `::test_an_over_long_line_is_clipped_and_its_tail_not_scanned` |
| INV-4 | `tests/test_scanner.py::test_a_fifo_launcher_does_not_block` |
| INV-5 | `tests/test_scanner.py::test_the_budget_stops_a_scan_mid_candidate` |
| INV-6 | `tests/test_scanner.py::test_launcher_precedence` |
| INV-7 | `tests/test_scanner.py::test_a_name_match_alone_does_not_bind_a_unit` |
| INV-8 | `tests/test_scanner.py::test_a_hostile_unit_name_is_rejected` |
| INV-9 | `tests/test_scanner.py::test_port_rule_2_keys` |
| INV-10 | `tests/test_scanner.py::test_the_launcher_outranks_the_hop_file` |
| INV-11 | `tests/test_scanner.py::test_a_finding_reports_the_rule_that_matched`, `::test_project_e_shape_comes_back_unknown` |
| INV-12 | `tests/test_scanner.py::test_a_detected_project_has_no_user_owned_field` |
| INV-13 | `tests/test_scanner.py::test_a_scan_leaves_the_tree_byte_identical` |
| INV-14 | `tests/test_layering.py::test_core_never_imports_qtwidgets`, `::test_the_core_module_list_matches_the_criterion` |
| INV-15 | `tests/test_scanner.py::test_a_long_line_does_not_backtrack` |
| § 4.4 rule 0's real `systemctl` calls behave as measured | **nothing** — every test injects `SupportsUnitLookup`, per `testing.md § T1`. The measurements in § 4.4 are dated and reproducible by hand; nothing re-runs them |
| § 4.6's rules detect the *seven real* projects correctly | **nothing** — the fixture tree mirrors them, and a fixture that has drifted from the project it mirrors passes while the real detection fails. `testing.md § T1` forbids reading the real ones, so this is a limit rather than a defect |
| § 4.3's `errors="replace"` decode never raises on any real file | **nothing** — untestable in general; the tests cover UTF-8, Latin-1 bytes and a binary blob |
| § 3's proposed no-walk decision matching what the user wants | **nothing** — a preference, not a contract; § 12 carries the `design.md` amendment it needs |

Nineteen rows, **four** with a bolded `nothing` — this spec's honest error
budget, per `spec-format.md § 0`. Two of the four are the same shape: a test
fake and a fixture tree can only be as true as the day someone last checked
them against reality.

## 12. Cross-doc impact

Four documents change in the same release, across the eight edits below.
Items 1–5 are all amendments to `design.md`, which this spec found
under-specified or wrong in five separate places; each is a `Kind: doc-fix`
edit to the section named, and each rides the same `/cold-eyes` pass as this
spec rather than a separate gate.

1. **`docs/design.md § Detection rules`, port rule 2** — "ends in `port` or
   `PORT`" becomes the non-alphanumeric-boundary form, with the four
   false-positive lines named. § 4.6 has the measurement.
2. **`docs/design.md § Detection rules`, port-rule ordering** — "searched in
   the launcher and then in the one-hop file" gains the word *file-major* and
   the worked example, closing the ambiguity in § 4.6.
3. **`docs/design.md § Detection rules`, launcher rule 0** — gains ADR-0003's
   second step, binding by `FragmentPath` / `WorkingDirectory` rather than by
   directory name. Today the two documents disagree and only the ADR is right.
4. **`docs/design.md § Everything the Scanner reads is hostile`** — its claim
   that the unanchored port pattern "is the classic catastrophic-backtracking
   shape" is corrected. Measured 2026-08-08: CPython 3.13.14 still backtracks
   catastrophically in general (`(a+)+$` at 24 characters, 1.10 s, doubling
   per character), but that *specific* pattern is linear — 0.0006 s over a
   40,001-character line. The two-step stays, on simplicity and immunity
   rather than on a hazard that was not reproduced.
5. **`docs/design.md § Detection rules § Where it looks`** — only if the user
   confirms § 3's proposed scope decision: the recursive walk becomes a
   statement that the rules are root-level and the depth bound and exclusion
   list constrain the one-hop target.
6. **`CLAUDE.md § Module map`** — `scanner.py` added, and the note that
   `CORE_MODULES` now covers `applog.py` too.
7. **`CHANGELOG.md`** — an `Added` entry for detection, and a `Security` entry
   for LWSM-1050's bounds.
8. **`ROADMAP.md`** — LWSM-1006 and LWSM-1050 flipped on the closing commit;
   LWSM-1121 already filed.

## 13. Cold-eyes loop log

| Loop | Date | Lanes | CRIT | HIGH | MED | LOW | Outcome |
|------|------|-------|------|------|-----|-----|---------|
