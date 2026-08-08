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
per-file cap, per-line cap, per-line deadline, symlink refusal at both the
candidate and the file level, non-regular refusal and containment check.

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
- **The recursive walk is not built** (user, 2026-08-08). Every launcher rule
  in `design.md § Detection rules` matches at the project root, and the
  one-hop port-bearing file is *named by the launcher* and opened directly,
  not found by searching. So nothing in this item's rule set reads a file a
  walk would have to find, and building a three-level walk to feed no reader
  is the scaffolding `coding.md § 1.1` forbids — on a scan root whose
  subdirectories hold `node_modules` it would also be the dominant term in the
  20-second budget. The depth bound and the eight excluded directory names are
  **not** dropped: they become constraints on the one-hop target (§ 4.5),
  which is the only place they can still do work. This diverges from
  `design.md § Detection rules § Where it looks`, which § 12 item 6 amends —
  surfaced rather than absorbed, per `.claude/workflow.md § 2`.

  The roadmap's acceptance clause "`node_modules` is never descended" is met
  by construction rather than by a prune list: nothing walks, so nothing
  descends. **This is the one place the decision trades a mechanism for a
  claim, so the claim carries its own invariant** — INV-20, with a fixture
  project holding `node_modules/serve.py`. Without it the acceptance clause
  would ship with nothing behind it while § 3 asserted otherwise.

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


class Confidence(enum.Enum):
    DETECTED = "detected"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PortFinding:
    port: int
    rule: PortRule
    source: str  # sanitised like `name`: a project-relative POSIX path,
    # "the <unit> unit", or one of rule 3's fixed framework names


@dataclass(frozen=True)
class DetectedProject:
    path: Path  # RESOLVED, absolute; the identity (ADR-0005)
    name: str  # the directory's own name, sanitised (below)
    kind: LauncherKind
    argv: tuple[str, ...]  # empty for SYSTEMD; the unit drives it
    unit: str | None  # set only for SYSTEMD
    port: PortFinding | None  # None means "unknown", never a guess

    @property
    def confidence(self) -> Confidence:
        return Confidence.UNKNOWN if self.port is None else Confidence.DETECTED


@dataclass(frozen=True)
class ScanResult:
    projects: tuple[DetectedProject, ...]
    skipped: tuple[str, ...]  # one clipped reason per rejection, capped
    timed_out: bool  # the budget expired; `projects` is partial


class SupportsUnitLookup(Protocol):
    """The systemd surface, injected so `testing.md § T1` holds.

    Both calls are bounded by the scan's own deadline. `OSError` is the ONLY
    exception this Protocol may raise, and the real adapter is responsible
    for making that true — it **translates every other failure mode into
    one**. Measured 2026-08-08, three of them are not `OSError` subclasses
    and each would otherwise escape `scan()` as an unhandled exception:

    - `subprocess.TimeoutExpired` (a `SubprocessError`) — the hang.
    - `subprocess.CalledProcessError` (a `SubprocessError`) — a non-zero
      exit. The common cause is not a missing `systemctl`: with no user
      D-Bus session `systemctl --user` exits **1** with empty stdout and
      "Failed to connect to user scope bus" on stderr.
    - `json.JSONDecodeError` (a `ValueError`) — what `--output=json` parsing
      raises on that empty stdout.

    Absence (`FileNotFoundError`) is already an `OSError` and needs no
    translation. § 6's "a machine without systemd scans normally" is only
    true because of this clause; without it the first run on such a machine
    raises instead of returning a `ScanResult`.
    """

    def unit_names(self, timeout: float) -> list[str]: ...

    def properties(
        self, unit: str, names: Sequence[str], timeout: float
    ) -> dict[str, str]:
        """TOTAL over `names`: every one is a key, absent ones map to "".

        Without that, `props["WorkingDirectory"]` on a unit that sets none
        raises `KeyError` — not an `OSError`, so the clause above does not
        catch it and it escapes `scan()`. Making the adapter total is the
        same obligation as translating the exceptions, and for the same
        reason.
        """
        ...
```

`Deadline`, used throughout § 4.3, is a `dataclass(slots=True)` holding one
`expires_at: float`
and one `now: Callable[[], float]`, with `expired()` and `remaining()`. It is
the object `scan()` builds from its `now` and `budget_seconds` arguments and
threads into every read, so the budget is one value rather than a parameter
each reader re-derives.

**`confidence` is derived, never stored.** The ROADMAP requires each project to
carry *detected* or *unknown*; storing it beside `port` would make two fields
able to disagree, which is the shape `coding.md § O5` exists to prevent. The
third value the UI shows, *confirmed*, is `confirmed_port`'s and belongs to
LWSM-1038 — this item never produces it.

**`PortFinding` does not carry the matched line.** An earlier draft did, and it
was the one string in this design that carried a hostile file's bytes to the
log and the status bar with neither `registry.py::_quoted`'s escape nor its
120-character clip — the defect LWSM-1078, LWSM-1102 and LWSM-1114 each closed
at one call site. `rule` plus `source` is the whole of the provenance
`design.md § Robustness` measure 2 asks for ("port 5000 — from a framework
default"), so the field was deleted rather than defended.

**`source`'s form is fixed, because INV-11 asserts it exactly**: a
**project-relative POSIX path** for a file (`start.sh`, `lib/launcher.py` —
§ 4.5 permits a hop three components down, so the bare basename would be
ambiguous), `the <unit> unit` for either systemd property, or rule 3's
framework name. It takes **`name`'s sanitiser, not `_quoted`** — U+FFFD for
control characters and the same clip — for `name`'s reason: it is a display
string, and `repr` would render a row's provenance as `'lib/launcher.py'`,
quotes included. A filename may still contain a newline, so it is sanitised;
it is just not *escaped*.

**`name` is sanitised, and not by `_quoted`.** It carries the same
attacker-supplied bytes as a skip reason — a Linux directory name may contain a
newline — but it is a *display* string, so `repr`'s escaping would put a row in
the UI literally named `'my project'`, quotes included. Instead every C0 and C1
control character is replaced with U+FFFD and the result is clipped to
`MAX_DISPLAY_NAME_CHARS = 120`, the same bound `registry.py::MAX_REASON_CHARS`
uses and for the same reason. Without this, a directory named
`evil<newline>PORT=1 detected` **that has a valid launcher** reaches the log and
the status bar raw — the forged-log-record defect LWSM-1078 closed, arriving by
the one path that survives detection, while the identical name is escaped and
clipped when the candidate is *rejected* and lands in `skipped`. One mechanism,
two call sites, applied to one of them: `coding.md § 1.6` again.

**`path` is the *resolved* path, not merely an absolute one**, and the
distinction is not academic: § 6 deliberately follows a symlinked scan root, so
a root of `~/projects → /mnt/data/projects` makes `~/projects/foo` and
`/mnt/data/projects/foo` the same directory under two names. ADR-0005 makes
this field the registry identity, so storing the unresolved form would give one
project two identities across scans and the merge would report a remove plus an
add. It is also the value § 4.2 rejection 4 compares, the project root § 4.5
constraint 1 checks against, and the working directory P05 spawns in — one
value, four jobs, and they must be the same value.

**`DetectedProject` has no `actions` field and no user-owned field of any
kind.** That is the structural half of `design.md § Custom project actions`'s
rule that detection never authors an executable action, and of ADR-0005's
two-halves split. A merge that wanted to promote scanned content into an
executable one would have to add the field first, which is a visible change
rather than a forgotten one.

**`argv` is a tuple of strings, never a command line** (`coding.md § O4`), and
**it names the alternate that actually matched, not the preferred one** — a
project with `run.sh` and no `start.sh` gets `("./run.sh",)`, one with only
`scripts.start` gets `("npm", "run", "start")`, one with only `app.py` gets
`("python3", "app.py")`. The § 4.4 table's `argv` column shows the *preferred*
alternate as an example. Every path in `argv` is relative to the project
directory, and **`path` is the working directory a launch must use** — P05
spawns there, so `("./run.sh",)` resolves against `path` and nothing else.
For `SYSTEMD`, `argv` is empty and `unit` is set, because ADR-0003's verb table
— not this module — builds `systemctl`'s argv.

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

A candidate is an **immediate subdirectory** of a scan root. Five rejections,
ordered cheapest first so that **only the last one opens a file**: rejections
1-4 are decided from the path alone, while "no launcher matched" needs rule 2
to parse `package.json` and rule 0 to call `systemctl`. Each records a reason in `skipped`:

1. **Not a directory.**
2. **A symlink.** Refused rather than resolved. Measured 2026-08-08 on Python
   3.13.14: `os.walk(followlinks=False)` declines to *descend* into a
   symlinked subdirectory but still lists it in `dirnames`, and walking a
   symlinked directory **as the top** follows it. Measured with `<root>/proj`
   containing a subdirectory `real`, and `<root>/proj_link` a symlink to
   `proj`: walking `proj_link` returned both `proj_link` and `real`, i.e. it
   descended through the link. So
   `followlinks=False` is not the guard at candidate level; refusing the
   candidate is.
3. **This application's own directory.** A candidate is skipped when
   `Path(lwsm.__file__).resolve()` is inside it. Measured 2026-08-08 under the
   editable install: that resolves to
   `…/LocalWebServerManager/src/lwsm/__init__.py`, so the repository's own
   directory is recognised without hard-coding a path. Once P01's launcher
   exists the manager would otherwise list and offer to launch itself.

   **The guard is exact only for a source checkout, and that is the honest
   limit.** Installed as a wheel, `lwsm` resolves inside `site-packages`, which
   is not under a scan root, so the guard never fires — correctly, because the
   repository is then not a candidate either. It fails only for a user who has
   both a wheel install *and* a source checkout inside a scan root, who sees
   their own checkout listed. § 11 records this rather than pretending the
   guard is universal.
4. **Already seen.** Two scan roots may overlap, or one may sit inside
   another, so the same directory can arrive twice; the second is skipped.
   ADR-0005 makes the absolute path the identity, so two records sharing one is
   a malformed result rather than a merge question — the rule
   `registry.py::load_projects` already applies to its own input. Comparison is
   on the **resolved** path, since rejection 2 has already removed the symlink
   route to the same target.
5. **No launcher matched** (§ 4.4). A candidate with no match is not a server
   project and is not listed.

**Every reason is escaped, then clipped, then counted.** All three, because
`registry.py` shipped the first two and needed LWSM-1115 for the third, and this
list holds strings that are *worse* than the registry's: a scan-root
subdirectory name is attacker-supplied and **a Linux filename may contain a
newline**, which is exactly the forged-log-record defect LWSM-1078 closed with
`repr`. So a reason is built through the same escape-then-clip rule
`registry.py::_quoted` applies — reimplemented rather than imported, per § 8's
reasoning about `_read_bounded` — and the same applies to `PortFinding.source`,
which is a file or unit name from the same untrusted tree and reaches the same
status bar.

Each reason is clipped at `MAX_REASON_CHARS = 120` — the same name and value
`registry.py` uses, since it bounds the same thing for the same reason;
`MAX_DISPLAY_NAME_CHARS` is a separate constant because it bounds a *display*
string under a different sanitiser, and one name for two policies is how they
drift apart. `MAX_SKIP_REASONS = 100`, and whenever anything
was suppressed the count is appended as a final entry, exactly as
`registry.py::load_projects` does — unconditionally *given suppression*, never
conditionally quiet about it. Clipping each reason bounds how *long* they
are and nothing bounds how *many* — the gap LWSM-1115 closed in the registry
after a file at its size cap produced **524,271** reasons totalling 20,859,730
characters, 8.7 s of them logged before the window appeared. A scan root with a
large subdirectory count reaches the same shape by a different road.

**Same value as `registry.py::MAX_REASONS`, and deliberately not shared.** The
two bound different populations — hand-edited records in one file against
subdirectories on disk — so they will move independently, and importing a
private constant across modules to save one line would couple them into moving
together. The `MAX_SOURCE_*` names diverge because the *numbers* differ; this
one diverges because the *reasons* do.

The **20-second budget** (`SCAN_BUDGET_SECONDS = 20.0`) is checked before each
candidate and, inside a file read, **before each line** — not once per scan. A
wall-clock check between files cannot interrupt work already under way. On
expiry the scan returns what it has with `timed_out=True`, rather than hanging
a first run.

### 4.3 Reading somebody else's file

```python
MAX_SOURCE_FILE_BYTES = 256 * 1024
MAX_SOURCE_LINE_CHARS = 4096


def _read_bytes(path: Path) -> bytes: ...  # whole file, under the byte cap
def _read_lines(path: Path, deadline: Deadline) -> list[str]: ...  # line-capped
```

**Two readers, because the line cap is right for scanning and wrong for
parsing.** `_read_lines` is what the port rules consume: capped lines with the
tail of an over-long one discarded, which is safe because a port declaration
past character 4096 of one line is not a declaration anyone wrote on purpose.
`_read_bytes` is what `package.json` needs, because JSON has no line structure
to cap. Measured 2026-08-08: a minified `package.json` with 300
`devDependencies` is **6,252 characters on one line**, and truncating it at
4096 raises `JSONDecodeError: Unterminated string`. Under a single line-capped
reader every minified `package.json` — an ordinary artefact — would be reported
as malformed and its project silently dropped from the list. Both readers share
the same open, the same `O_NOFOLLOW`, the same `S_ISREG` check and the same
`MAX_SOURCE_FILE_BYTES`; only the framing differs.

Named `MAX_SOURCE_*` rather than reusing `registry.py`'s `MAX_FILE_BYTES`,
because they are different numbers for different jobs — 1 MiB for a config
file this app owns, 256 KB for a sibling's source — and one name for two
values is the ambiguity `documentation.md § 1.5` bans.

**Four bounds and two error policies.** § 1 lists LWSM-1050's six bounds as a
whole and is canonical for that set. The **candidate**-level symlink refusal
(§ 4.2) and the containment check (§ 4.5) apply to a path before any file is
opened and live there; the **file**-level symlink refusal is the `O_NOFOLLOW`
bullet below, which is why § 1 says "at both the candidate and the file
level". What follows is this function's
own contract, and the last two bullets are how it behaves on failure, not
limits it enforces:

- Opened `O_RDONLY | O_NONBLOCK | O_NOFOLLOW`, then `fstat` on the raw
  descriptor: refused unless `stat.S_ISREG`. Two different attacks, two
  different flags:

  - A FIFO at `start.sh` would block `open()` until a writer appears — the
    failure `registry.py::_read_bounded` was written for, reproduced there on
    2026-08-06. `O_NONBLOCK` plus the `S_ISREG` check is what stops it.
  - **A symlinked `start.sh` is read straight through, and `S_ISREG` cannot
    see it.** Measured 2026-08-08: a `start.sh` symlinked to a file outside the
    project opened cleanly, `S_ISREG` on the resulting descriptor returned
    `True` — it describes the *target* — `os.access(X_OK)` also returned
    `True`, and the target's contents were read. `O_NOFOLLOW` is the only guard
    that refuses it (`ELOOP`, "Too many levels of symbolic links"). Without
    this flag INV-1's containment promise holds for the one-hop target and not
    for the launcher itself, which is the file this module opens first.

  This is why `applog.py`'s handler uses `O_NOFOLLOW` and why `registry.py`'s
  reader does not: the log is a file we own, the config is one the user may
  reasonably symlink, and a sibling project's launcher is neither.
- Refused above `MAX_SOURCE_FILE_BYTES`, checked on the `fstat` size *and*
  again on the bytes actually read, so a file that grows between the two is
  still refused.
- Read with `readline(MAX_SOURCE_LINE_CHARS)`. Measured 2026-08-08: that
  returns at most the cap and leaves the remainder for the next call, so a
  100,000-character single line came back as 25 chunks. **The remainder of an
  over-long line is discarded rather than scanned**, which is what stops a
  pattern being split across a chunk boundary and matching half of itself.
- The deadline is checked before each line, and **expiry abandons the
  candidate in progress**: it is not listed, no partial port is reported for
  it, and the scan returns immediately with `timed_out=True`. Reporting what
  was read so far would hand the caller an honest-looking *unknown* the project
  never earned — and LWSM-1007 is about to persist that list.
- Decoded `utf-8` with `errors="replace"`. A sibling's file is not required to
  be text, and a `UnicodeDecodeError` three levels into someone else's repo is
  not a fact worth stopping a scan for.
- Any `OSError` rejects that file with a reason and continues. A permission
  denial on one project is not a failure of the scan.

**A refused launcher file is not a match, and the rules continue.** A
symlinked, FIFO or oversized `start.sh` is a file this app has declined to
read, so it cannot be the launcher — but § 4.4's alternation carries on to
`run.sh`, and then to rules 2, 3 and 4. Only when *every* alternate is refused
or absent does rejection 5 fire and the candidate go unlisted, carrying the
read's reason rather than a bare "no match".

**Continuing is the security answer, not the lenient one.** Stopping at the
first refused file would mean anyone able to drop a symlink named `start.sh`
into a project directory could delete that project from the manager — a
denial of service bought with one file, in a directory this app already treats
as hostile. Falling through to a `run.sh` that reads cleanly costs nothing and
removes the lever. An earlier draft said the candidate is dropped outright;
that was reasoning about one file rather than about the project.

A refused *hop target* likewise leaves the project listed: the launcher is
still runnable and only the port is unknown.

**Sweep, per `coding.md § 1.6`** — two mechanisms, both enumerated rather than
grepped, because neither is a helper you can search for the absence of.

*Bounded reading of an untrusted file.* The other sites are
`applog.py::_NoFollowRotatingFileHandler` (a *write* path, and stricter — it
demands one link and our own ownership) and `registry.py::_read_bounded` (our
own config, weaker — no line cap, no deadline, 1 MiB). Both enumerated; neither
changes. § 8 records why this is a third implementation rather than an
extraction.

*Bounding a list of rejection reasons that reaches the log and the UI.* The
other site is `registry.py::load_projects`, which holds **both** halves —
`_quoted`'s escape-then-clip per reason **and** `MAX_REASONS` on the count. An
earlier draft of this spec carried the first half and not the second, which is
this rule's exact failure shape: a mechanism applied unevenly on the day it
lands. § 4.2 now carries both. Enumeration: two sites hold this mechanism
(`registry.py::load_projects`, `scanner.py::scan`); both bound length and
count.

### 4.4 Launcher rules, first match wins

Numbered as `design.md § Detection rules` numbers them: these *launcher* rules
from 0, § 4.6's *port* rules from 1. The two sets overlap at every number from
1 up, which is why each is always named in full.

The last column is the **port-bearing content** § 4.6's rules are run over, and
it is named per rule because it differs per rule — a question the design left
open.

| # | Match | `kind` | `argv` (example) | § 4.6 reads |
|---|---|---|---|---|
| 0 | a bound systemd user unit (below) | `SYSTEMD` | empty; `unit` set | the unit's `Environment=` and `ExecStart=` |
| 1 | executable `start.sh`, else executable `run.sh` | `SHELL` | `("./start.sh",)` | the script, then its one-hop target (§ 4.5) |
| 2 | `package.json` with `scripts.dev`, else `scripts.start` | `NODE` | `("npm", "run", "dev")` | the chosen `scripts` value, and nothing else from that file |
| 3 | `serve.py`, else `server.py`, else `app.py` | `PYTHON` | `("python3", "serve.py")` | the matched `.py` file |
| 4 | `serve.mjs`, else `serve.js` | `NODE` | `("node", "serve.mjs")` | the matched `.js`/`.mjs` file |

Every path is at the project root, and every within-rule list is ordered: rule
1 prefers `start.sh`, rule 3 prefers `serve.py`, rule 4 prefers `serve.mjs`.
The `argv` column shows the **preferred** alternate; § 4.1's rule is that
`argv` names whichever alternate actually matched.

**Only rule 1 has a one-hop *file*.** Rules 2, 3 and 4 name the file they run
directly, so there is nothing to follow; rule 0's unit is read through
`systemctl` rather than opened. But two of the five launcher *rules* still
have **two sources**, and § 4.6's file-major ordering runs them left to right as this
table lists them: rule 0 takes `Environment=` then `ExecStart=`, and rule 1 the
script then its hop target. Rules 2, 3 and 4 have a **single** source — for
rule 2 that is the chosen `scripts` value alone, for the reason below.

**Rule 1 requires the execute bit** (`os.access(path, os.X_OK)`) and a regular
file. A `start.sh` without it is not a launcher match, and the reason is
recorded — running it would fail at spawn time with a message about a file the
user never chose.

**Rule 2 parses `package.json` through § 4.3's `_read_bytes`**, not
`_read_lines`, for the reason § 4.3 measures. A malformed or oversized one is
not a match, with a reason — and "malformed" has to be enumerated, because
three of its shapes are **not** `JSONDecodeError` and each would otherwise
escape `scan()` as an unhandled exception:

| Input | Raises | Is it a `ValueError`? |
|---|---|---|
| 20,000 nested `[…]`, well-formed, **40 KB** | `RecursionError` | **no** — a `RuntimeError` |
| bytes that are not valid UTF-8 | `UnicodeDecodeError` | yes, but not a `JSONDecodeError` |
| a valid document whose root is `5`, `[1,2]` or `null` | `AttributeError` on `.get("scripts")` | no |
| `{"dependencies": 5}`, reached by rule 3's evidence scan | `TypeError` on the membership test | no |

Measured 2026-08-08. The file is decoded `utf-8-sig` before parsing — an
editor-added BOM is invisible in that editor, and `registry.py::load_projects`
records that same reasoning — which is what turns the second row into a
`UnicodeDecodeError` rather than a confusing `JSONDecodeError` about byte 0.

So the parse catches **`ValueError`** (covering `JSONDecodeError` and
`UnicodeDecodeError`) and **`RecursionError`**, and **type-checks every
container before touching it**: the root, `scripts`, and — the arm an earlier
draft missed — `dependencies` and `devDependencies`, which rule 3's evidence
scan reads and which no clause constrained. `"dependencies": 5` makes
`"vite" in deps` raise `TypeError`, and `TypeError` is neither a `ValueError`
nor a `RecursionError`, so it escaped `scan()` and took **every other
project's row with it** — one hostile `package.json` deleting the whole list.
A non-`dict` there is *no evidence*, with a reason. All four are non-matches.

**`registry.py::load_projects` already names every one of these** — its
`except (ValueError, RecursionError)` clause and its `isinstance(data, dict)`
guard, each with a comment explaining which reproduction earned it. This is
`coding.md § 1.6`'s sweep failing in the direction it usually does: a
mechanism solved once in the module next door, and re-implemented here without
it. Enumeration: two JSON parse sites in this app (`registry.py::load_projects`,
`scanner.py`'s rule 2); both now catch the same three.

**The port rules never see `package.json`'s raw text, and they see exactly one
value from it: the `scripts` entry this rule chose.** Not every script, and
**never** `dependencies` or `devDependencies`. That value is clipped to
`MAX_SOURCE_LINE_CHARS` and offered to rules 1 and 2 like any other line.
Splitting the raw bytes on newlines instead would either lose most of a
minified file to the line cap or breach INV-3; parsing first avoids both, and
this is the only source in the spec where structure is available to parse.

**Both exclusions are load-bearing, and each was measured 2026-08-08:**

- **A dependency block fabricates ports.** `"get-port": "^7.0.0"` — a real and
  common npm package — partitions on `:`, and `get-port` satisfies
  `KEY_IS_PORT` through the hyphen, so the digit search returns **7**.
  `"detect-port": "^1.5.1"` returns **1**. Both would be reported as
  `DETECTED` with `PortRule.ASSIGNMENT`, which is the manufactured value
  § 4.1's "`None` means *unknown*, never a guess" exists to forbid. Dependency
  names are rule 3's *framework evidence* (`vite`) and are never offered to
  rules 1 and 2.
- **A script the launcher does not run is not evidence.** With
  `"build": "vite build --port 9000"` above `"dev": "vite --port 3000"`,
  scanning every script in document order returns **9000** — the port of a
  build step — and the chosen script can never correct it, because
  first-match-wins has already fired. Only the chosen entry is read. **The chosen entry is the first of `scripts.dev`, `scripts.start` whose value
is a non-empty string**, and if neither is, rule 2 does not match, with a
reason. Stated because `dev` can be *present and invalid* — `""`, `null`, `{}`
are all trivially plantable — and "`scripts.dev`, else `scripts.start`" alone
admits two readings: `dev` is present so it is chosen and then fails, dropping
rule 2 entirely; or `dev` is not a valid entry so `start` is chosen and the
project launches on `("npm", "run", "start")`. Same file, two different
launchers. This mirrors the alternation § 4.3 already fixes for
`start.sh` / `run.sh`, where a refused alternate lets the rules continue.
`scripts` itself must be an object.

**Rule 0 — the systemd path.** Detection is two steps, because ADR-0003
requires both and `design.md § Detection rules` states only the first:

1. **Propose by name.** `systemctl --user list-unit-files --type=service
   --output=json` lists the units. Measured 2026-08-08 against systemd 261.2:
   it returns `[{"unit_file": "ants-stats.service", "state": "enabled",
   "preset": "disabled"}, …]`. JSON rather than the column layout, because
   parsing columns out of a name that may contain escaped bytes
   (`app-ai\x2dprompts\x2dtray@autostart.service` appears in that output) is a
   guess. A unit is proposed when its stem, **after undoing systemd's `\xNN`
   escaping**, equals the candidate directory's name — escaped forms are what
   that output contains, so comparing them raw would miss any project whose
   directory name systemd had to escape.
2. **Bind by location, never by name** (ADR-0003, security review
   2026-08-03). One call fetches every property both this step and § 4.6 need:

   ```
   systemctl --user show -p LoadState -p FragmentPath -p WorkingDirectory \
                         -p Environment -p ExecStart -- <unit>
   ```

   `FragmentPath` or `WorkingDirectory` must resolve **inside** the candidate
   directory — and **an empty value contributes no evidence and is never
   resolved**. `Path("").resolve()` is the *current working directory*
   (measured 2026-08-08), so resolving an absent `WorkingDirectory` makes any
   name-matched unit bind whenever the manager was launched from inside a
   scan-root project — `cd ~/projects/foo && lwsm` — which is precisely the
   empty-directory-drives-somebody-else's-service outcome this step exists to
   stop, arriving through the check meant to prevent it. The same applies to
   `FragmentPath`.

   **`WorkingDirectory` is not a bare path, and usually is not one at all.**
   systemd prefixes it with `-` (ignore if missing) or `!` (run privileged),
   and both are printed. Measured 2026-08-08 across the real user units on this
   machine: **13 of 14 print a `!`-prefixed path** such as `!/home/ants`; only
   the one hand-written unit prints a bare path. So leading `-` and `!` are
   stripped before resolution, or the containment check compares a path that
   cannot exist and never matches anything. Without this, `mkdir <scan root>/project-a` — an empty directory
   with no code in it — is enough to make the UI present a row whose Start and
   Stop drive somebody else's service.

   **Three things about that command, each measured 2026-08-08 and each
   contradicting an earlier draft of this section:**

   - **Every `-p` goes before the `--`.** With the options after it,
     `systemctl` reads `-p` and `FragmentPath` as further *unit names* and
     dumps all **832** property lines of the real unit. The `--` separator
     `coding.md § 7` requires still applies — it just has to be the last thing
     before the name, not the first thing after the options.
   - **`LoadState=not-found` is the missing-unit signal, not an empty
     `FragmentPath` and not the exit code.** A unit that does not exist exits
     **0** and prints a synthesised record with `FragmentPath=` empty; so does
     a unit that exists but is masked.

     **The two produce the same launcher outcome and different reasons, and
     the reason is the whole difference.** Neither binds — no `FragmentPath`
     means nothing to contain-check — so rule 0 does not match either way and
     the candidate falls through to launcher rule 1. But `masked` records a
     reason in `skipped` (`<name>: unit <unit> is masked`) and `not-found`
     records **none**, because a project simply having no unit is the ordinary
     case and would otherwise put a line in `skipped` for every candidate on
     the machine. A masked unit is a user who *disabled* something this app
     was about to drive, which is worth one line.

     **A third branch: the unit loads, has a real `FragmentPath`, and it
     resolves *outside* the candidate.** That is the `mkdir <scan root>/project-a`
     case the whole step exists for — a real unit belonging to someone else,
     carrying this project's name — so it **records a reason**
     (`<name>: unit <unit> is not bound to this directory`). It is the one
     branch where something surprising happened, and the one an operator will
     want to see; `not-found` stays silent because having no unit is ordinary.

     Without that asymmetry the distinction is unobservable and INV-7's
     `::test_a_not_found_unit_is_not_confused_with_a_masked_one` has nothing to
     assert — it would pass against an implementation that treats them
     identically, which is the behaviour that invariant exists to reject.
   - **A name `systemctl` rejects also exits 0**, printing
     `Invalid unit name "--host=evil.example.service" …` on stderr and an empty
     record on stdout. So the validation below is the guard, not a
     belt-and-braces addition to one `systemctl` performs.

3. **Read the port from the unit** (the systemd half of § 4.5's one hop). A
   `systemd` project runs no script this app can open, so its port lives in the
   two properties just fetched, and § 4.6's rules 1 and 2 run over them in this
   order: `Environment=` first, then `ExecStart=`.

   Measured 2026-08-08 against a real unit, `systemctl` prints
   `Environment=STATS_PORT=4321 STATS_REFRESH_HOURS=24`. **`properties()`
   returns the value with its `NAME=` prefix already removed** — that is what
   its `dict[str, str]` return means — so what the rules receive is
   `STATS_PORT=4321 STATS_REFRESH_HOURS=24`, a single space-separated line of
   `KEY=VALUE` pairs, **split on whitespace** and offered to the port rules one
   pair at a time.

   **The prefix is load-bearing and its removal has to be stated.** Measured:
   split with the prefix left on, the first token is
   `Environment=STATS_PORT=4321`, on which rule 2 partitions at the first `=`
   and gets the key `Environment` (not a port key) while rule 1's `PORT=` is
   preceded by `_` and excluded by its own boundary — so **neither rule
   matches**, and `project-a` comes back *unknown*: exactly the failure this
   step exists to prevent. With the prefix removed, `STATS_PORT=4321` yields
   4321 through rule 2.
   **The reason is that `partition` examines only the FIRST `KEY=` on a line.**
   Measured: unsplit, `STATS_PORT=4321 REFRESH=24` still yields 4321 because
   the port happens to come first, while `REFRESH=24 STATS_PORT=4321` yields
   `None` — the port is invisible whenever another variable precedes it, which
   is ordinary. An earlier draft justified the split by saying rule 2 would
   "partition on the wrong `=`"; that is not what goes wrong, and a wrong
   reason is a reason someone will later decide is obsolete. `ExecStart` is a
   **structured record**, not a command line —
   `ExecStart={ path=/usr/bin/node ; argv[]=/usr/bin/node serve.mjs ; … }` — so
   only the `argv[]=` field is scanned, and rule 2 is not run over it at all,
   because `path=` and `pid=` are `systemctl`'s own keys rather than the
   project's.

   Without this step `project-a` — the one known systemd project — comes back
   *unknown*, and the acceptance test in § 7 cannot pass.

**A unit name is untrusted input.** It is validated against ADR-0003's
`^[A-Za-z0-9@:_.\-]{1,255}\.(service|socket|target|timer)$`, a leading `-` is
rejected, and `--` is passed immediately before it in every `systemctl` argv
this module builds. A name beginning with `-` is consumed by `systemctl` as an
option — `--host=`, `-M`, `--machine=` all redirect which manager is driven.

**The escaped name is what goes into every argv; the unescaped stem is used
only for the name comparison.** Those are two different strings and the spec
has to say which is which: `systemctl` accepts only the escaped form, while the
comparison in step 1 needs the unescaped one. **The validator therefore admits
`\`** — as `^[A-Za-z0-9@:_.\\\-]{1,255}\.(service|socket|target|timer)$` — because
ADR-0003's class as written has no backslash, so `app-ai\x2dprompts\x2dtray@autostart.service`
(a real unit on the author's machine) fails validation and can never reach an
argv. Left unfixed that has one of two shapes, both bad: the unescaping step
becomes dead code and every such project falls through to launcher rule 1 — so
the manager offers to spawn a script for a server systemd already owns, the
double-instance hazard ADR-0003 § Service-managed projects exists to prevent —
or the name is passed unvalidated and the guard is bypassed for exactly the
names that contain escapes. Widening the class costs nothing: a backslash is
inert in an `execve` argv, and the leading-`-` rejection plus the `--`
separator remain the actual defence. § 12 gains the ADR-0003 amendment.

**That pattern is otherwise ADR-0003's general one and is deliberately wider
than what step 1 proposes.** This module lists `--type=service` only, so a `.socket`,
`.target` or `.timer` name can only arrive from a future caller passing one in
— ADR-0003's second binding route, the registry's own recorded unit name, which
§ 9 defers to LWSM-1007. The validator is shared with
ADR-0003's verb table rather than narrowed here, so one pattern governs every
`systemctl` argv in the app; INV-8 therefore parametrises a `.mount` suffix,
which is outside the pattern under either route.

`units` is a `SupportsUnitLookup` (§ 4.1), defaulting to a real `systemctl`
caller, exactly as `ports.py` accepts `SupportsSnapshot` so the test fake is
the contract. `testing.md § T1` forbids a test touching the real service
manager, and a machine with no `systemd` at all must scan normally: a
`OSError` from either call — `systemctl` absent, unreadable, or timed out, the
last translated by the adapter per § 4.1 — disables rule 0 for the whole scan
and is recorded once, not once per candidate.

### 4.5 The one-hop port-bearing file

Only for `kind == SHELL`, because that is the only launcher that runs another
file whose name it names — rules 2, 3 and 4 name the file they run, and rule
0's equivalent hop is § 4.4 step 3, which reaches the unit's properties through
`systemctl` rather than by opening anything.

**Finding the target is a tokenise-and-select rule, not a search for "a
path".** It was prose until loop 5 — the only matching mechanism in § 4 that
was — and prose is what left three implementers free to pick three different
tokens:

1. **Strip comments first** (§ 4.6's `strip_comment`, same two markers). The
   scan is over stripped lines, so a commented-out invocation cannot win. This
   matters because the rule takes the **last** invocation: measured
   2026-08-08, a script ending
   `exec python3 new.py` / `# exec python3 old.py (kept for reference)`
   resolves to **`old.py`** unstripped and `new.py` stripped.
2. Take the **last** line still containing `exec`, `python3`, `python` or
   `node` as a whole word.
3. Split it on whitespace, **drop every token beginning with `-`**, and strip
   surrounding quotes.
4. Take the **last** remaining token that satisfies § 4.5's six constraints.

Steps 3 and 4 are what the prose left open, and each of these lines resolves
differently under "the token after the keyword": `exec python3 -u launcher.py`
gives `python3`, `exec env PORT=1 python3 launcher.py` gives `env`, and
`python3 -m http.server 8080` gives `-m`. Under the rule above the first two
give `launcher.py` and the third gives **no hop at all**, which is correct —
`http.server` runs no file in the project. `exec "$DIR/launcher.py"` also gives
no hop: an unexpanded shell variable cannot resolve, so it fails constraint 1
rather than being guessed at. This module does not expand shell variables and
must not start.

Exactly one hop is followed — `project-e` puts its port two hops out (`run.sh` → `launcher.py` →
`config.py`) and is expected back as *port unknown*, which is an honest limit
rather than a bug.

**A token containing a NUL byte is rejected before anything else touches it.**
`os.path.commonpath` accepts one happily, and then `Path.resolve()` and
`os.open()` both raise **`ValueError`** — not an `OSError`, so § 4.3's
"any `OSError` rejects that file and continues" does not catch it and the scan
raises. Measured 2026-08-08 on `exec python3 laun\x00cher.py`, which a hostile
launcher can write directly. `registry.py::load_projects` already refuses a NUL
in a path, and its comment names the consumer: *"every later os call on it
raises ValueError — and P03 passes this path as a spawn cwd."* P03 is this
item, and the guard did not arrive with it.

The target is accepted only when **all six** hold. Constraints 1-5 are checked
after resolution — which is about the *parent* components, since a project may
reasonably hold a symlinked subdirectory — and constraint 6 is about the final
component, which § 4.3's `O_NOFOLLOW` would otherwise refuse unread after all
five had passed:

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
6. **Its final component is not itself a symlink.** Constraints 1–5 all pass
   for an in-project symlink whose target is also in-project, and § 4.3's
   `O_NOFOLLOW` would then refuse it unread — a rejection with no reason
   attached to the thing that caused it. Checking it here means the row says
   *why*.

Constraints 3 and 4 are `design.md`'s exclusion list and depth bound, applied
at the only place this item still reads a file below the root. § 3's proposed
scope decision is what moved them here.

### 4.6 Port rules, first match wins

**`systemctl` property values are exempt from the comment stripper, and
`argv[]=` is extracted from the record before anything else touches it.** The
stripper is defined over the *lines of a file*; a property value is not one,
and a `#` inside a command it quotes (`argv[]=/bin/sh -c 'x --port 8080 # prod'`)
is part of that command rather than a comment about it. Extraction first is
what makes the ordering unambiguous either way.

**This rule survived the reason that produced it, which is worth recording.**
It was written when the marker set still included `;`, and systemd separates a
record's fields with ` ; ` — stripping first then left
`{ path=/usr/bin/node` and lost the port entirely (measured 2026-08-08).
Dropping `;` from the marker set removed that failure, so the exemption is no
longer load-bearing against it; it is kept because the scope argument above
stands on its own, and stated that way rather than left resting on a
measurement that no longer reproduces.

**Comments are stripped before either rule sees a line of a file.** A line
whose first non-whitespace characters are `#` or `//` is skipped entirely, and
a trailing comment is cut at the first such marker. Without this,
`# PORT=9999 (old)` is detected as port 9999 — measured 2026-08-08 — which is
the commonest shape in a real launcher: the *previous* port, commented out,
sitting above the current one. The app's whole value is telling the truth about
what a project does, and reading a disabled line as live is the sharpest way to
fail at that.

**Two markers, not three — `;` is deliberately absent.** An earlier draft
included it, on the analogy of `.ini` files. In every language this module
actually reads it is a **statement separator**, and the cost is measured:
`cd /app ; exec node serve.mjs --port 8080` loses its port, so does
`"dev": "cd app ; vite --port 5173"`, and so does `export FOO=1 ; PORT=9000`
(2026-08-08). It bought nothing in exchange — `#` already covers every
commented-out port in a shell or Python file, and `//` covers JavaScript.

**A marker counts only at line start or after whitespace, and that single
condition is the whole rule.** There is no quote-awareness, deliberately (see
below), so a `#` inside a string does cut the line.

```python
COMMENT = re.compile(r"(?:^|\s)(?:#|//)")


def strip_comment(line: str) -> str:
    match = COMMENT.search(line)
    return line if not match else line[: match.start()]
```

The condition is not a simplification for its own sake — **without it the
stripper eats `http://localhost:3000` at the `//`**, silently killing one of
rule 1's six documented forms. The first version written here was a
quote-aware character loop, on the theory that `NAME = "a # b"` must not be
truncated; it did exactly that damage, and cost **766 µs** per call against
this one's **64 µs** on a line at the cap (measured 2026-08-08). Truncating a
quoted `#` is harmless — the key left of the separator decides the match, and
`NAME` is not a port key — so the loop was buying nothing and breaking
something.

The stripper is shared by both port rules and by rule 3's evidence scan, so a
framework identified from a commented-out import cannot happen either.

**A negative number is not a port.** Rule 2's digit pattern is
`(?<![0-9-])\d{1,5}(?![0-9])`, excluding a preceding `-` as well as a digit:
without it `PORT = -1` yields **1** (measured), inventing a plausible port from
a line that declares an impossible one. `PORT = 80.80` still yields 80, which
is correct — the first whole number on the right is the declaration, and a
fractional port is not a form anyone writes.

**Within one source the scan is line-major: each line is offered to rule 1
then rule 2 before the next line is read**, and the first line to yield a port
wins. Stated because "anywhere in the file" left it open, and because the two
readings disagree — measured 2026-08-08 on a launcher holding
`SERVER_PORT = 3000` above `exec node serve.js --port 8080`, line-major returns
**3000** and running rule 1 over the whole file first returns **8080**. This is
§ 4.6's between-source ordering asked one level down, and the same answer:
proximity to the top of the file beats rule precedence, because a declaration
near the top is the one a human reads as authoritative.

**Rule 1 — an explicit port setting**, anywhere in the line. Given as code for
the same reason rule 2 is, and because **rule 1 runs first, so its looseness
costs more**:

```python
RULE_1 = re.compile(
    r"(?:^|[^A-Za-z0-9_])PORT=\$\{PORT:-(\d{1,5})\}(?![0-9])"  # PORT=${PORT:-N}
    r"|(?:^|[^A-Za-z0-9_])PORT=(\d{1,5})(?![0-9])"  # PORT=N
    r"|--port[= ](\d{1,5})(?![0-9])"  # --port N / --port=N
    r"|(?:localhost|127\.0\.0\.1):(\d{1,5})(?![0-9])",  # localhost:N
    re.IGNORECASE,
)
```

The port is the **first non-`None` group** of the match; the four alternatives
are mutually exclusive, so exactly one is ever set.

**An out-of-range value is not a match, and scanning resumes after it** — the
rest of the same line, then the next line, then the next source. So rule 1 uses
`finditer` and returns the first in-range value rather than `search` and a
range check on one result: `localhost:99999 and PORT=8080` on one line yields
**8080**, where checking only the first match would yield nothing and hand the
line to rule 2. Rule 2's fenced code carries the same rule inside its loop.

Two things the prose form left open, both of which change what gets built:

- **The `PORT=` alternatives need the same left boundary rule 2 has.** Measured
  2026-08-08, an unanchored `PORT=(\d+)` returns 99 for `TRANSPORT=99`, 5 for
  `EXPORT=5` and 4321 for `APP_PORT=4321` — reintroducing, in the
  higher-priority rule, exactly the false positives § 4.6 corrected rule 2 to
  reject. `[^A-Za-z0-9_]` excludes the underscore as well as letters, because
  `APP_PORT` is the shape INV-17's own fixture uses.
- **`${PORT:-N}` needs its own alternative and must come first.** A plain
  `PORT=(\d+)` does not match `PORT=${PORT:-8080}` at all — the character after
  `=` is `$` — so without this branch the form `design.md` singles out as
  mattering (`project-g` declares 8080 this way) is missed by rule 1 and picked
  up, if at all, by rule 2. Listed first because Python's alternation is
  ordered and the plain branch would otherwise never be reached for that line.

`\d{1,5}(?![0-9])` rather than `\d+`, and **the lookahead is the load-bearing
half**. `\d{1,5}` alone does not *reject* a longer number, it takes the first
five digits of one: measured 2026-08-08, `PORT=123456` returns **12345**,
`--port 999999999` returns **99999** and `localhost:1234567` returns **12345** —
each of which then passes the 1–65535 range check and is reported as a detected
port. That manufactures a value out of a line declaring no usable port, which
is the one thing § 4.1's "`None` means *unknown*, never a guess" forbids. With
the lookahead all three return `None`. The `{1,5}` bound remains, so a
4096-character run of digits is never captured in the first place.

**Rule 2 needs the mirror-image guard as well, and for a reason rule 1 does
not have.** Rule 1's digits are anchored — they must sit immediately after
`PORT=`, `--port ` or `localhost:` — so a failed match at that position ends
the attempt. Rule 2 runs a bare `re.search` over the right-hand side, and a
search that cannot match at the first digit **advances and matches the tail**:
measured 2026-08-08, `PORT = 123456` returned **23456**. So rule 2 carries
`(?<![0-9])` as well as `(?![0-9])`. This is the same fabrication class caught
in rule 1 one loop earlier, surviving in the sibling rule — `coding.md § 1.6`'s
"a mechanism, not the call site it was reported against", and it was found by
running both rules over the same corpus rather than by reading either.

Run 2026-08-08 over twelve lines — the six accepted forms above plus
`TRANSPORT=99`, `EXPORT=5`, `APP_PORT=4321`, `SERVER_PORT = 3000`,
`const viewport = 1280` and `export PORT=8080` — with every result as stated
here. § 7 parametrises the same twelve.

**Rule 2 — an assignment whose key is a port.** A non-backtracking two-step.
The prose form admitted two readings — whether `:` is partitioned out of the
line or out of the left side `=` produced — and they differ on
`PORT=http://localhost:8080`, so it is given as code instead:

```python
KEY_IS_PORT = re.compile(r"(?:^|[^A-Za-z0-9])port$", re.IGNORECASE)


def rule_2(line: str) -> int | None:
    # Each separator is tried against the WHOLE line, `=` first. Not `:`
    # applied to `=`'s left side: `'server_port': 5000` has no `=` at all.
    for separator in ("=", ":"):
        left, found, right = line.partition(separator)
        if not found:
            continue
        key = left.strip().strip("'\"").rstrip("'\" \t")
        if key.lower() != "port" and not KEY_IS_PORT.search(key):
            continue
        # finditer, not search — the range check below must not end the scan
        # at the first out-of-range number: `'server_port': 70000, 'port':
        # 5000` yields None under `search` and 5000 under `finditer`
        # (measured). This is rule 1's resume rule, applied here too.
        #
        # BOTH boundaries, and `-` on the left. A lookahead alone is not
        # enough in a *search*:
        # the engine, unable to match at the first digit, advances and matches
        # the tail — ` 123456` yields `23456`. Rule 1 is immune only because
        # `PORT=` anchors its digits to a fixed position.
        for digits in re.finditer(r"(?<![0-9-])\d{1,5}(?![0-9])", right):
            # The range check lives HERE, not at the call site: an out-of-range
            # value must let the search carry on to the next separator, the next
            # line and the next source, which a returned int cannot express.
            if PORT_RANGE[0] <= int(digits.group()) <= PORT_RANGE[1]:
                return int(digits.group())
    return None
```

`PORT_RANGE` is `registry.py`'s `DECLARED_PORT_RANGE`, `(1, 65535)` —
deliberately not ADR-0005's 1024–65535, which governs the *override* the user
types. A project may legitimately declare 80.

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

Produced 2026-08-08 by running both key rules over those ten lines under
`uv run python3` on 3.13.14. **Both columns**, not just the shipping one:
`test_port_rule_2_keys` parametrises the boundary rule, and
`test_the_literal_ends_in_port_rule_would_accept_four_more` asserts that the
literal variant returns the four values in the left column — so the argument for the change stays an output rather than
becoming a transcription the day someone edits the table.

**Rule 3 — a framework default**, only when neither rule 1 nor rule 2 found
anything in **any** of the sources the § 4.4 table gives this launcher kind.
The framework is identified from evidence the scan has already read, never from
a new file:

**The table order is the precedence**, and it is stated because a project can
satisfy two rows: a `PYTHON` candidate with a root-level `manage.py` *and* an
`import flask` in its launcher matches Django and Flask both, and nothing else
in the spec breaks the tie. First row wins; `PortFinding.source` names the
framework that won, so a wrong guess is diagnosable rather than mysterious.
(`design.md` lists the three in a different order — Vite, Flask, Django — which
is why table order could not be left implicit; § 12 item 6a carries it.)

| # | Framework | Identified by | Default |
|---|---|---|---|
| 1 | Vite | `vite` as an **exact key** of `dependencies` / `devDependencies`, or as a **substring** of the chosen `scripts` value | 5173 |
| 2 | Django | a root-level `manage.py`, or `^\s*(?:import\|from)\s+django\b` in the launcher's Python file | 8000 |
| 3 | Flask | `^\s*(?:import\|from)\s+flask\b` in the launcher's Python file | 5000 |

**Every evidence test is exact or whole-word, never a substring**, and this is
the third time in this spec that a loose match fabricates a port. Measured
2026-08-08: `import flask_login` **contains** `import flask`, so a substring
test reports 5000 for a project with no Flask app; `vitest` and
`@vitejs/plugin-react` both contain `vite`. The `\b` and the exact-key rule are
what stop it. § 7's corpus gains `vitest` and `flask_login` fixtures, both
expecting *unknown*.

**Which kinds can reach which evidence**, because the table above does not say
and "the launcher's Python file" means different things per kind:

| Kind | Vite | Django | Flask |
|---|---|---|---|
| `NODE` via rule 2 | yes — its `package.json` | no | no |
| `PYTHON` | no | `manage.py`, or its launcher file | its launcher file |
| `SHELL` | no | a one-hop target ending `.py`, **and then** `manage.py` or `import django` in it | `import flask` in a one-hop target ending `.py` |
| `NODE` via rule 4, `SYSTEMD` | no | no | no |

**The two Vite tests differ on purpose, and conflating them fabricates ports.**
A dependency block has keys, so the test is exact-key membership; a script value
is a string, so the test there is a substring. Read as a substring in both,
`{"devDependencies": {"vitest": "^2.0.0"}}` — a **test runner**, among the
commonest devDependencies in a modern Node project, and not a server at all —
identifies Vite and reports the project `DETECTED` on 5173. That is the same
fabrication class measured for `"get-port": "^7.0.0"` → 7, arriving through
rule 3 instead of rule 2. § 7's corpus gains a `vitest` fixture expecting
*unknown*.

A `SHELL` project **does** reach Django and Flask evidence, because § 4.5's own
worked hop is `run.sh` → `launcher.py` and a shell launcher legitimately runs
Python — **but only when it actually has a `.py` hop target.** An earlier draft
gated Flask on that and Django on a bare root-level `manage.py`, so a
`start.sh` reading `exec node serve.mjs`, with a stray `manage.py` beside it,
reached Django's 8000: a Python default fabricated for a project that runs no
Python, arriving through the shell wrapper ADR-0003 exists because of. Both
cells now carry the same gate. A `NODE` or `SYSTEMD` project does **not**, even with a `manage.py` at
the root: `design.md` fires rule 3 "only when the launcher **identifies** a
framework", and a `serve.mjs` or a unit identifies none — a stray `manage.py`
beside a Node server would otherwise fabricate 8000 for it. So `manage.py`
counts as evidence only for the two kinds that can run it (§ 12 item 6a).
An earlier draft claimed rule 3 never fires for `SHELL` or `SYSTEMD`, which its
own table contradicted; the correction over-shot the other way and this is
where it lands. A project reaching no evidence at
all comes back *unknown*, and that is the correct answer rather than a gap:
guessing 5000 for a shell script would be the invented value `design.md`
refuses.

**Order is file-major, and `design.md` does not say which.** "Port rules, first
match wins, searched in the launcher and then in the one-hop file" admits two
readings, and they disagree whenever the launcher's match comes from a
*lower-numbered rule than* the hop file's. Worked example, with
`SERVER_PORT = 3000` in the launcher and `--port 8080` in the hop file:
rule-major reaches rule 1 in both sources before trying rule 2 anywhere, so it
returns **8080**; file-major exhausts the launcher first and returns **3000**.

This spec fixes **file-major**: rules 1 then 2 within the first source, rules 1
then 2 within the second, then rule 3 across both. The launcher is the file
that actually runs, and rule 3's own wording ("only when neither port rule 1
nor port rule 2 found anything") already scopes across both sources, which only
file-major makes coherent. "Both sources" means whatever the § 4.4 table gives
that launcher kind, in its listed order — **two for launcher rules 0 and 1,
one for launcher rules 2, 3 and 4**. Rule 2's single source is the chosen
`scripts` value; an implementer who went looking for a second one would find
only the rest of `package.json`, which § 4.4 measures as fabricating 7 from
`"get-port": "^7.0.0"`. § 12 carries the amendment.

**The example has to be a line rule 2 accepts, and the first one written was
not.** An earlier draft used `PORT_BASE = 3000`, whose key ends in `BASE`;
measured 2026-08-08, rule 1 and rule 2 both return `None` for it, so the
launcher yielded nothing and **both orderings returned 8080**. The example
proved nothing, and INV-10's fixture — the same line — was green under either
implementation. `SERVER_PORT = 3000` returns 3000 under rule 2 and `None` under
rule 1, which is exactly the shape that separates the two orderings.

A port outside `PORT_RANGE` is not a match and the search continues; the
constant is named where `rule_2` uses it.

### 4.7 The layering list widens

`tests/test_layering.py`'s `CORE_MODULES` gains **`scanner.py` and
`applog.py`** in the commit that creates the module, giving
`applog, controller, ports, registry, scanner`. `coding.md § O1` requires the
first and names the second: the criterion covers `applog.py`, the list omits
it, "the check is the one that runs", and widening it is this item's job.
Without that line a `QtWidgets` import in either module passes every gate.

**`coding.md § O1`'s criterion is wrong as written, and this item corrects it.**
It says a core module is "every module under `src/lwsm/` that is not
`mainwindow.py` or `theme.py`" — a two-way split with no room for the entry
point. Taken literally it covers `__init__.py` and `__main__.py`, and
`src/lwsm/__main__.py` imports `QApplication` from `QtWidgets` **by design**
(deliberately inside `main()`, after `argparse`, so `--version` needs no
display). So a test that derives its list from the criterion adds `__main__.py`
to `CORE_MODULES` and reddens `test_core_never_imports_qtwidgets` on the day it
lands.

The criterion becomes a four-way split, and § 12 carries the amendment:

| Layer | Modules | Rule |
|---|---|---|
| UI | `mainwindow.py`, `theme.py` | may import `QtWidgets` |
| Entry point | `__main__.py` | may import `QtWidgets`; **is** where the `QApplication` is built |
| Package marker | `__init__.py` | imports nothing |
| Core | everything else | `QtCore` only, never `QtWidgets` |

INV-14's test derives `CORE_MODULES` from *that* table — the complement of
its three non-core layers, four named files in all — so a new core module still cannot be forgotten, which
is the property the derivation exists for.

## 5. Invariants

- **INV-1** — No file outside a candidate's own resolved directory is opened.
  *Test:* `tests/test_scanner.py::test_a_hop_out_of_the_project_is_refused`
  and `::test_a_symlinked_launcher_is_refused`, the second planting a
  `start.sh` symlinked to a readable file outside the project and asserting
  that file's port is not detected.
  *Breaks when:* a `run.sh` whose last invocation is
  `exec python3 ../../../.ssh/config`, one naming a token with an embedded NUL
  (`ValueError` from `resolve()`, which is not an `OSError` and escapes the
  scan), or a `start.sh` that is a symlink out of
  the project — the case § 4.3's `O_NOFOLLOW` bullet measures, and the one this
  invariant promised for two drafts with no rule behind it.

- **INV-2** — A candidate directory that is itself a symlink is skipped, with
  a reason, and nothing inside it is read.
  *Test:* `tests/test_scanner.py::test_a_symlinked_candidate_is_not_scanned`.
  *Breaks when:* `<root>/proj` is a symlink to `/etc` — measured 2026-08-08 to
  be walked normally under `followlinks=False`, which is why this is a
  candidate-level guard rather than a walk argument.

- **INV-3** — No file contributes more than `MAX_SOURCE_FILE_BYTES`, through
  either reader; and no line reaches the port rules longer than
  `MAX_SOURCE_LINE_CHARS`, the remainder being discarded rather than scanned.
  *Test:* `tests/test_scanner.py::test_an_oversized_file_is_refused`,
  parametrised over both readers, and
  `::test_an_over_long_line_is_clipped_and_its_tail_not_scanned`, the second
  planting `PORT=9999` past the cap and asserting it is not found.
  *Breaks when:* a 2 GB `start.sh`, or a single 100 MB line in one. (Not a
  `README.md` — this item never opens one; that is LWSM-1121's source.)
  **The line half is scoped to the port rules on purpose** — `_read_bytes`
  applies no line cap, for the reason § 4.3 gives; the byte cap is what bounds
  it, and it is the half that bounds memory.

- **INV-4** — A non-regular file at a launcher or hop path is refused on the
  descriptor, not opened for reading.
  *Test:* `tests/test_scanner.py::test_a_fifo_launcher_does_not_block`, under
  a `SIGALRM` guard raising a `BaseException` subclass so the guard cannot be
  swallowed by the assertion it protects — **and asserting the recorded
  reason**, not merely that the call returned.
  *Breaks when:* a FIFO at `start.sh` with no writer.
  **The reason is the only observable that separates the two guards.** Measured
  2026-08-08: opened `O_NONBLOCK`, a writer-less FIFO's `readline` returns `''`
  — EOF, not a block. So `O_NONBLOCK` alone satisfies "did not block", and
  deleting the `S_ISREG` check leaves the FIFO reading as an *empty file*: the
  project is listed with no port instead of refused with a reason, and a test
  named for blocking never sees it. This is `testing.md § T9` item 2 — where
  two mechanisms reach the same outcome, the shared outcome is not evidence.

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
  *Test:* `tests/test_scanner.py::test_a_name_match_alone_does_not_bind_a_unit`
  and `::test_a_not_found_unit_is_not_confused_with_a_masked_one`, the second
  giving the fake `LoadState=not-found` and `LoadState=masked` in turn, both
  with an empty `FragmentPath`, and asserting that **only the masked one puts a
  reason in `skipped`** — the single observable that differs, without which the
  test passes against an implementation that never distinguishes them.
  *Breaks when:* an empty directory is created whose name matches a real unit
  belonging to another project; or the implementation reads an empty
  `FragmentPath` as "no such unit", which a masked unit also produces.

- **INV-8** — A unit name failing ADR-0003's pattern never reaches an argv,
  and every `systemctl` argv this module builds places `--` immediately before
  the name. **The second half needs its own seam**: the argv is built inside
  the real adapter, which every test replaces with a fake (§ 11), so under the
  four parametrisations below the clause could never fail — an adapter shipping
  `["systemctl", "--user", "show", "-p", …, unit]` with no separator at all
  keeps them all green. So the builder is a pure function,
  `_show_argv(unit) -> list[str]`, called directly by the test.
  *Test:* `tests/test_scanner.py::test_a_hostile_unit_name_is_rejected`,
  parametrised over a leading `-`, an embedded space and a `.mount` suffix —
  three names a directory can actually carry, so each reaches the validator
  through `scan()`. The **length** bound is asserted against the validator
  directly, in `::test_the_unit_name_validator_bounds_length`, because
  `NAME_MAX` is 255 on this filesystem (measured) and a 300-character
  `.service` name has a 292-character stem: no candidate directory can be given
  it, so step 1 never proposes such a unit and a `scan()`-level case would be
  green with the pattern's `{1,255}` deleted. Plus
  `::test_the_show_argv_separates_options_from_the_name`, asserting
  `_show_argv("x.service")` puts `--` at index -2 and every `-p` before it —
  the half that ships unverified otherwise.
  *Breaks when:* a unit named `--host=evil.example.service` is proposed.

- **INV-19** — Neither port rule reads a commented-out line, and neither
  returns a port from a negative number.
  *Test:* `tests/test_scanner.py::test_a_commented_out_port_is_not_detected`,
  parametrised over `#` and `//` at line start, a trailing `# was 9090`
  that must **not** suppress the live value on the same line, `; PORT=9999`
  which **does** yield 9999 because § 4.6 deliberately carries two markers and
  not three,
  `http://localhost:3000` whose `//` is **not** a comment, and
  `NAME = "a # b"`, which yields **no port** — the stripper does truncate it at
  the quoted `#` and that is harmless, since the key left of the separator is
  `NAME` either way. The case asserts the *outcome*, not that the line survives
  intact: asserting the latter would demand the quote-aware loop § 4.6 rejected
  for eating `http://localhost:3000`. Plus
  `::test_a_negative_number_is_not_a_port`.
  *Breaks when:* a launcher carries its previous port commented out above the
  current one — measured 2026-08-08 to return 9999 for `# PORT=9999 (old)`
  before the stripper existed — or a line reads `PORT = -1`, which returned
  **1**.
  **Found by executing the rules against a corpus, not by reading them**, after
  three review loops had passed over both patterns.

- **INV-9** — Both port rules require a separating character before `port`,
  and **the two classes differ on the underscore, deliberately**: rule 2 uses
  `[^A-Za-z0-9]`, which *admits* `_`; rule 1 uses `[^A-Za-z0-9_]`, which does
  not. Neither matches any other key.
  **The difference is load-bearing in both directions, and getting it backwards
  breaks the acceptance test.** Rule 2 must admit `_` or `DEFAULT_PORT` and
  `server_port` stop matching — two of the seven detections § 7 requires. Rule
  1 must exclude it or `APP_PORT=4321` is claimed by the wrong rule, mislabelling
  INV-17's own fixture as `EXPLICIT`. Measured 2026-08-08 across both classes.
  *Test:* `tests/test_scanner.py::test_port_rule_2_keys`, parametrised over
  § 4.6's ten lines, and `::test_port_rule_1_forms`, parametrised over the
  twelve § 4.6 lists for rule 1.
  *Breaks when:* `const viewport = 1280` is scanned — measured 2026-08-08 to
  return 1280 under the rule as `design.md` words it — or `TRANSPORT=99` is,
  which an unanchored rule 1 returns 99 for. **Rule 1 is the one that matters
  more**, because it runs first: an unanchored `PORT=` reintroduces in the
  higher-priority rule exactly what fixing rule 2 removed, and until loop 2 the
  spec gave rule 1 no pattern at all.

- **INV-10** — Port rules resolve file-major: rules 1 then 2 in the launcher,
  then rules 1 then 2 in the one-hop file, then rule 3 across both.
  *Test:* `tests/test_scanner.py::test_the_launcher_outranks_the_hop_file`,
  with `SERVER_PORT = 3000` in the launcher and `--port 8080` in the hop file,
  asserting 3000.
  *Breaks when:* the implementation iterates rules outermost, which returns
  8080 for that fixture. **The fixture line is load-bearing** — § 4.6 records
  the line that was tried first and could not discriminate.

- **INV-11** — The `rule` and `source` a finding reports are the ones that
  actually produced it, and a project with no readable port has `port is None`
  and `confidence is Confidence.UNKNOWN` rather than a substitute.
  *Test:* `tests/test_scanner.py::test_a_finding_reports_the_rule_that_matched`,
  parametrised over one fixture per rule **and one whose port lives in the
  one-hop target rather than the launcher** — the only case that proves
  `source` names the file actually read, and the only coverage § 4.5's
  tokenise-and-select rule gets outside the conformance corpus — each asserting
  the exact `(rule, source)` pair, and
  `::test_project_e_shape_comes_back_unknown`.
  *Breaks when:* a port read from the one-hop file is labelled as coming from
  the launcher, or the framework default is applied to a project whose
  launcher identifies no framework, turning *unknown* into 5000.
  **Asserting mere presence would be a tautology** — `PortFinding` is a frozen
  dataclass whose `rule` and `source` are required, so they cannot be absent
  and a presence test could never fail. The pair has to be checked against the
  fixture that produced it.

- **INV-12** — `DetectedProject` carries no user-owned field: no `actions`, no
  display-name override, no port override, no hidden flag.
  *Test:* `tests/test_scanner.py::test_a_detected_project_has_no_user_owned_field`,
  asserting the dataclass's field names against an explicit allowed set.
  *Breaks when:* a later change adds `actions` so a merge can carry it, which
  is exactly the promotion `design.md § Custom project actions` forbids.

- **INV-13** — The Scanner writes nothing anywhere: no file created, modified,
  or removed under any scan root.
  *Test:* `tests/test_scanner.py::test_a_scan_leaves_the_tree_untouched`,
  comparing a recursive `(path, sha256, mtime_ns, mode)` snapshot of the
  fixture tree before and after. The hash and not just the size, because a
  same-length overwrite is exactly the mutation a size comparison cannot
  see — the shape that produced this project's stale-`.pyc` incident.
  *Breaks when:* a future convenience writes a cache or a marker into a
  project — `coding.md § O3`'s standing prohibition.

- **INV-14** — `scanner.py` imports no `QtWidgets`, and `CORE_MODULES` equals
  every module under `src/lwsm/` except the three § 4.7 names —
  `mainwindow.py`, `theme.py`, `__main__.py` — and `__init__.py`.
  *Test:* `tests/test_layering.py::test_core_never_imports_qtwidgets`
  (parametrised, so the names being present is what makes it run) and
  `::test_the_core_module_list_matches_the_criterion`, a source-invariant test
  (`testing.md § 3.6`) that globs `src/lwsm/*.py`, subtracts the four
  exclusions and asserts set equality with `CORE_MODULES`.
  *Breaks when:* a sixth core module lands and is not added to the list, which
  is how `applog.py` came to be missing from it. **The exclusion set is named
  explicitly rather than derived from `coding.md § O1` as worded**, because
  that criterion excludes only the two UI modules and so would pull in
  `__main__.py`, which imports `QtWidgets` by design — reddening the sibling
  test on the day this one lands.

- **INV-15** — The rule-2 matcher is linear in line length at its own bound: an
  adversarial 4096-character line completes in well under a second.
  *Test:* `tests/test_scanner.py::test_the_port_matcher_does_not_backtrack`,
  calling `rule_2` **directly** on two synthetic strings at the line cap:
  `"a" * 4088 + "port = 1"` (4096 characters) and 102 colon-separated fields,
  with a 1-second ceiling. Both figures come from
  `docs/specs/LWSM-1006-conformance.py`, which prints them on every run.
  *Breaks when:* the two-step is replaced by a single pattern with a nested
  quantifier. Measured 2026-08-08: CPython 3.13.14 still backtracks
  catastrophically — `(a+)+$` against 24 `a`s took **1.10 s**, doubling per
  added character — so the hazard is live in this runtime even though the
  specific pattern `design.md` warns about does not exhibit it (§ 12 item 4).
  **The fixture must contain a separator, and an earlier one did not.** It was
  `"a" * 4092 + "port"`, which has no `=` and no `:`, so `rule_2` returns after
  two `partition` calls and `KEY_IS_PORT` **never runs** — the test was green by
  construction and survived its own prescribed mutation. Instrumented
  2026-08-08: 0 regex calls against the old fixture, 1 against the new, and the
  cost moved 0.24 µs → **154 µs** per call (comment-stripping included), so the
  old figure was timing the early return rather than the rule. This is `testing.md § T9` item 3 and
  `/write-spec`'s "which rule makes this fixture fail?" — a clause that reads
  as sound and tests nothing.
  **The bound is 4096 rather than 40,000** because INV-3 caps every line at
  `MAX_SOURCE_LINE_CHARS`, so no longer line can reach the matcher through
  `scan()`; an earlier draft asserted 40,000, which INV-3 makes unreachable.

- **INV-16** — A candidate containing this application's own package is never
  listed as a project.
  *Test:* `tests/test_scanner.py::test_the_app_does_not_detect_itself`, with a
  fixture candidate holding a `src/lwsm/__init__.py`, a monkeypatched
  `lwsm.__file__` pointing into it, **and an executable `start.sh`**.
  *Breaks when:* the manager is run from a checkout sitting inside a scan
  root, and offers to launch itself.
  **The launcher in the fixture is what makes this falsifiable.** Without it
  the candidate matches no launcher rule, so rejection 5 already keeps it out
  and the test stays green with the self-exclusion guard deleted — the guard
  ships unreached. With it, rejection 3 is the only thing standing between the
  fixture and a listed row, which is also the real situation rejection 3
  describes: once P01's launcher exists, this repository *does* look like a
  project.

- **INV-17** — A `systemd` project's port comes from its unit's `Environment=`
  and `ExecStart=`, in that order, and not from any file in the project
  directory.
  *Test:* `tests/test_scanner.py::test_a_systemd_project_takes_its_port_from_the_unit`,
  with a fake `SupportsUnitLookup` returning the dict `properties()` really
  returns — `{"LoadState": "loaded", "FragmentPath": "<inside the project>",
  "Environment": "APP_PORT=4321 REFRESH=24"}`, **with no `Environment=`
  prefix on the value** — and a project directory containing a `serve.mjs`
  that declares a *different* port, asserting 4321.
  **The absent prefix is the point.** A fake written as
  `{"Environment": "Environment=APP_PORT=4321 …"}` reproduces the exact shape
  § 4.4 step 3 measures as matching *neither* rule, so a correct
  implementation returns `port is None` and the test goes red — and the
  obvious repair is to stop stripping the prefix in the real adapter, which
  reintroduces the `project-a` *unknown* failure this invariant exists to
  prevent.
  *Breaks when:* the unit is read for binding only, which is what an earlier
  draft specified — `project-a`, the one known systemd project, then comes back
  *unknown* and § 7's acceptance test fails.
  **The decoy port in the directory is what makes this falsifiable:** without
  it the test passes against an implementation that ignores the unit entirely
  and reads `serve.mjs`.

- **INV-18** — `ScanResult.skipped` holds at most `MAX_SKIP_REASONS` entries
  plus one final entry naming the suppressed count, which is present whenever
  anything was suppressed.
  Every reason and every `PortFinding.source` is escaped before it is clipped.
  *Test:* `tests/test_scanner.py::test_the_reason_list_is_capped_and_says_so`,
  over a scan root with `MAX_SKIP_REASONS * 3` unusable candidates, and
  `::test_a_newline_in_a_directory_name_cannot_forge_a_log_record`, whose
  candidate directory is named with an embedded newline and whose reason must
  contain no raw `\n`.
  *Breaks when:* a scan root holds thousands of non-project subdirectories —
  the shape `registry.py` measured at 524,271 reasons and 20,859,730
  characters before `MAX_REASONS` existed.
  **The suppressed-count entry is asserted separately from the cap**, because
  a cap with no tail reads exactly like completeness, and that is the half
  `registry.py::load_projects` calls out as never conditionally quiet.

- **INV-20** — No file beneath an excluded directory name is opened, and a
  launcher-shaped file inside one is never a project's launcher.
  *Test:* `tests/test_scanner.py::test_nothing_inside_node_modules_is_read`,
  over a fixture whose root `start.sh` **declares no port of its own and reads
  `exec python3 node_modules/pkg/serve.py`**, that file declaring one — so the
  hop *is* resolved and constraint 3 is the only thing refusing it — asserting
  the project comes back *unknown* and, via a patched opener recording every
  path, that nothing under `node_modules` was opened. A second fixture hops
  four components down (`exec python3 a/b/c/d.py`) for constraint 4.
  **The obvious fixture cannot see either constraint.** A `start.sh` that
  declares its own port ends the search file-major before the hop is ever
  resolved, so deleting constraints 3 and 4 leaves that test — and every other
  named test — green, and a `run.sh` reading
  `exec python3 node_modules/foo/bin.py` is happily followed. The fixture has
  to force the hop.
  *Breaks when:* a future change reinstates a recursive walk without the prune
  list, or the one-hop resolution stops checking § 4.5 constraint 3. **This is
  the acceptance clause the no-walk decision has to pay for**: with nothing
  walking, "`node_modules` is never descended" is true by construction, and an
  invariant nobody can see is how a construction-time guarantee quietly stops
  being one.

## 6. Failure modes

- **`systemctl` is absent.** Rule 0 is disabled for the whole scan, recorded
  once in `skipped`, and every other rule proceeds. A machine without systemd
  scans normally.
- **`systemctl` hangs.** Each call is bounded by
  `min(SYSTEMCTL_TIMEOUT_SECONDS, deadline.remaining())` with
  `SYSTEMCTL_TIMEOUT_SECONDS = 2.0` — **its own budget, not the scan's** — and
  a timeout disables rule 0 exactly as absence does, leaving the scan to
  continue. Drawing the timeout from the scan deadline alone would make a
  single hung `systemctl` consume the whole 20 seconds and set `timed_out`,
  which contradicts this clause: a scan cannot both carry on normally and be
  out of time. `timed_out` therefore means *the scan deadline expired*, never
  *a subprocess was slow*.
- **A scan root does not exist, or is not readable.** One reason in `skipped`,
  and the other roots are scanned. A missing root is ordinary — an unmounted
  drive — and must not blank the result.
- **A scan root is itself a symlink.** Followed, and deliberately: the user
  typed this path, so it is a choice rather than something planted in a
  directory this app happened to walk into. § 4.2's refusal applies to
  *candidates*, which arrive from the filesystem and not from the user. The
  candidates found beneath it are still each resolved and checked, so a
  symlinked root cannot smuggle a symlinked candidate past rejection 2.
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

Two new files, `tests/test_scanner.py` and `tests/scanner_fixtures.py`.
`tests/test_layering.py` gains one new test and a widened `CORE_MODULES` list. Every test is headless (`testing.md § T6`); the
module imports no Qt, so none of them needs `pytest-qt`.

**The fixture tree is the deliverable, not scaffolding.** A session-scoped
fixture builds a throwaway tree via **`tmp_path_factory.mktemp("scan_root")`**
mirroring the seven known projects — each shape from `docs/discovery.md`'s
inventory — plus the framework-default project § 3 added.

**Each fixture's expected result is derived from what the fixture contains,
never asserted from what the real project does.** That distinction is the
corpus's whole value, and getting it backwards produces a test that disagrees
with the rules it is meant to lock:

| Fixture | What it holds | Expected, by the rules |
|---|---|---|
| `project-a` | a bound unit whose `Environment=` carries the port | detected, rule 0 + port rule 2 |
| `project-b` | `serve.py` with a port assignment | detected, launcher rule 3 + port rule 2 |
| `project-c` | `server.py` with a port assignment | detected, launcher rule 3 + port rule 2 |
| `project-d` | `start.sh` hopping to a `.py` that **imports neither Flask nor Django**, port held in a saved setting | **unknown** |
| `project-e` | `run.sh` → `launcher.py` → `config.py`, port two hops out, no framework import in the hop target | **unknown** |
| `project-f` | `start.sh` declaring its port directly | detected, port rule 1 |
| `project-g` | `run.sh` with `${PORT:-8080}` | detected, port rule 1's first alternative |
| framework fixture (§ 3) | `serve.py` importing Flask, no port anywhere | detected, **port rule 3** |
| exclusion fixture (INV-20) | `start.sh` with **no port**, reading `exec python3 node_modules/pkg/serve.py`, that file declaring one | **unknown**; nothing under `node_modules` opened |
| depth fixture (INV-20) | `start.sh` with no port, hopping four components down | **unknown** — constraint 4 refuses it |
| `vitest` fixture (rule 3) | `package.json` with `devDependencies: {"vitest": …}`, `"dev": "vitest"`, no port | **unknown** — `vite` is an exact key, and `vitest` is not it |
| `flask_login` fixture (rule 3) | `serve.py` containing `import flask_login`, no port | **unknown** — the evidence is whole-word `flask` |

**The `project-d` and `project-e` rows carry an explicit negative, and they
have to.** Both are `SHELL` projects whose hop target is a `.py` file, and
§ 4.6's table lets a `SHELL` project reach Flask and Django evidence exactly
that way. The real `project-d` runs on **5000** — Flask's default — so a
fixture whose hop target imports Flask would make rule 3 return 5000, which is
the *right* port and the *wrong* test result. Either the fixture omits the
import (as specified above) and the expectation is *unknown*, or it includes
one and the expectation becomes `PortRule.FRAMEWORK_DEFAULT`. What it may not
be is a fixture whose content nobody stated and an expectation nobody derived.

`testing.md § T1` forbids reading the real projects, so the corpus is only ever
as true as the day someone last checked it against them — recorded in § 11 as
one of the four `nothing` rows rather than pretended away.

**`tmp_path_factory`, not `tmp_path`.** `tmp_path` is function-scoped, so a
session-scoped fixture requesting it raises `ScopeMismatch` at collection —
reproduced 2026-08-08 against this project's pinned pytest 9.1.1:
`ScopeMismatch: You tried to access the function scoped fixture tmp_path with a
session scoped request object`. Nothing runs, and the failure is a collection
error rather than a test failure, so it does not read as one.
`design.md § Detection accuracy is a test suite, not an opinion` makes it the
**regression corpus every future mis-detection is added to**, so it lives in
`tests/scanner_fixtures.py` as data, not inline in a test body.

Per `testing.md § T1` no fixture is a real sibling project: every one is
generated. Per `testing.md § T3` no test hard-codes a live port — the ports
here are strings in files, never bound, which is the one case T3's rule about
binding does not reach.

Every invariant's test is named in its own bullet in § 5 and tabulated in
§ 11. It is not tabulated a third time here: the same eighteen rows stood
in two places for three loops and had already drifted twice.

**`docs/specs/LWSM-1006-conformance.py` runs every pattern in this document
now**, before any of it is implemented — the regexes, the range check, the line
cap, the containment check, the unit-name validator, the comment stripper and
INV-15's timing bound, each against inputs chosen to break it. It exists
because three cold-eyes loops read those patterns and passed them, and running
them found four false claims in two minutes. Re-run it after **any** edit to a
fenced pattern in § 4:

```
PYTHONDONTWRITEBYTECODE=1 uv run python3 docs/specs/LWSM-1006-conformance.py
```

**Definition of done includes deleting it.** When `scanner.py` exists its cases
move into `tests/test_scanner.py` pointed at the real module, and the script
goes — a second copy of the patterns is a second source of truth, and it is
only tolerable while the first one does not exist yet.

Plus the acceptance test the roadmap names:
`test_every_fixture_project_is_detected_as_expected` — named for the corpus
rather than for seven, since the tree already holds eight and grows with every
mis-detection — parametrised over the fixture tree, asserting launcher **and** port — including the *unknown* cases, since a
rule that quietly starts guessing for `project-e` is the regression this
corpus exists to catch.

**Every test is seen failing before the code exists** (`testing.md § 1`), and
the four that guard a *bound* rather than a behaviour are additionally
mutation-checked in `testing.md § T9`'s manner — **adopted voluntarily here,
since T9 binds `Kind: fix`, `audit-fix` and `review-fix` and this item is
`Kind: implement`**; a bound that ships unreached is the same defect whichever
kind introduced it. INV-3, INV-4, INV-15 and INV-18 each
have their guard line removed in place and the named test re-run alone
(`PYTHONDONTWRITEBYTECODE=1 uv run pytest -k <name>`), with the result in the
commit body. Those four are singled out because each can pass for a reason
other than the guard — an oversized file that also fails to parse, a FIFO
whose open fails before the `S_ISREG` check is reached, a fast line that was
never long enough to backtrack, a reason list that never reached its cap. That
is `testing.md § T9` item 3: a stub must be able to express the breach.

**INV-15's one-second ceiling is a duration, and `testing.md § T4` bans those
for *waits*, not for bounds.** T4's target is `time.sleep` standing in for a
condition, where the condition is the thing to poll for; here the elapsed time
*is* the assertion, and there is nothing to poll. The ceiling is set against a
measurement rather than a guess: **153.53 µs/call** for the 4096-character key
line and **70.25 µs/call** for the 102-field line (2026-08-08, printed by
`docs/specs/LWSM-1006-conformance.py`), so 1 second is a margin of roughly
6,500× and 14,000×. A machine slow enough
to fail it honestly has a problem, and a backtracking replacement fails it by
orders of magnitude rather than by a hair — which is what keeps it off
`testing.md § 3.4`'s flaky-perf-test list.

## 8. Alternatives considered (and rejected)

- **Extract `registry.py::_read_bounded` into a shared helper rather than
  writing a third bounded reader.** Rejected. The two policies genuinely
  differ — 1 MiB against 256 KB, no line cap against 4096 characters, no
  deadline against a per-line one — so the shared function would take four
  parameters and mean nothing without them. `registry.py` is shipped and
  tested, and refactoring it is scope this item does not own. `coding.md
  § 1.3`'s Rule of Three puts extraction at the third *identical* call site,
  not the third similar one. Revisit if LWSM-1121 needs a fourth.
- **Keep the matched line on `PortFinding` for diagnosis, escaped and clipped
  through a `registry.py::_quoted` equivalent.** Rejected in favour of deleting
  the field. It would have been this module's *third* copy of escape-then-clip,
  and the value it carries is not the provenance `design.md` asks for — "port
  5000 — from a framework default" needs the rule and the source, not the
  bytes. A field that has to be defended, in a design whose whole subject is
  untrusted input, is worth less than the same information without the defence.
- **Parse `systemctl --user list-unit-files`'s column output.** Rejected on
  the measurement: that output contains names with escaped bytes
  (`app-ai\x2dprompts\x2dtray@autostart.service`), so column splitting is a
  guess where `--output=json` is a fact. JSON is also the current idiom for
  systemd 261 (`coding.md § 1.5`).
- **Trust `systemctl show`'s exit code to mean the unit exists.** Rejected on
  the measurement: it exits 0 for a unit that does not exist, for a unit whose
  *name* it rejects, and prints a synthesised record either way.
  **`LoadState=not-found` is the signal** (§ 4.4 step 2) — not the exit code,
  and not an empty `FragmentPath`, which a *masked* unit also has.
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
- **ADR-0003's second route to a systemd binding** — "when the registry records
  a unit name for it". There is no registry to record one until LWSM-1007, so
  this item implements only the first route, discovery by name-then-location.
  Tracked by LWSM-1007.

## 10. Resource cost

No new dependency: `os`, `re`, `json`, `stat`, `enum`, `dataclasses`,
`pathlib`, `subprocess`, `time`, `typing` (`Protocol`) and `collections.abc`
(`Sequence`, `Callable`). One new intra-package import, `lwsm.registry`, for
`DECLARED_PORT_RANGE` — a core→core dependency and the only one this module
adds. (`lwsm.__file__` is read for § 4.2 rejection 3, which needs no import
beyond the package itself.) No new build target.

Bounded by construction, and every bound is named: at most
`MAX_SOURCE_FILE_BYTES` (256 KB) resident per file, one file at a time; at
most `MAX_SOURCE_LINE_CHARS` (4096) per line, with the tail discarded rather
than buffered; at most `SCAN_BUDGET_SECONDS` (20) of wall clock.

`ScanResult.skipped` is bounded **twice**: each reason is clipped by the rule
`registry.py::_quoted` applies, and the list itself stops at
`MAX_SKIP_REASONS` (100) plus one suppressed-count entry. Length alone is not a
bound — `registry.py` shipped the clip and not the cap, and a file at its size
limit then produced 524,271 reasons totalling 20,859,730 characters (LWSM-1115).

`ScanResult.projects` holds one `DetectedProject` per *accepted* candidate and
is deliberately uncapped: it is the answer the caller asked for, it is bounded
by the directories the user pointed at, and truncating it would silently hide
projects — the failure mode `skipped`'s cap exists to avoid, applied to the
wrong list. The `PortFinding` on each holds an `int`, an enum member and one
file-or-unit name, having lost the matched line for the reason in § 4.1.

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
| INV-9 | `tests/test_scanner.py::test_port_rule_2_keys`, `::test_port_rule_1_forms`, `::test_the_literal_ends_in_port_rule_would_accept_four_more` |
| INV-10 | `tests/test_scanner.py::test_the_launcher_outranks_the_hop_file` |
| INV-11 | `tests/test_scanner.py::test_a_finding_reports_the_rule_that_matched`, `::test_project_e_shape_comes_back_unknown` |
| INV-12 | `tests/test_scanner.py::test_a_detected_project_has_no_user_owned_field` |
| INV-13 | `tests/test_scanner.py::test_a_scan_leaves_the_tree_untouched` |
| INV-14 | `tests/test_layering.py::test_core_never_imports_qtwidgets`, `::test_the_core_module_list_matches_the_criterion` |
| INV-15 | `tests/test_scanner.py::test_the_port_matcher_does_not_backtrack` |
| INV-16 | `tests/test_scanner.py::test_the_app_does_not_detect_itself` |
| INV-17 | `tests/test_scanner.py::test_a_systemd_project_takes_its_port_from_the_unit` |
| INV-18 | `tests/test_scanner.py::test_the_reason_list_is_capped_and_says_so`, `::test_a_newline_in_a_directory_name_cannot_forge_a_log_record` |
| INV-19 | `tests/test_scanner.py::test_a_commented_out_port_is_not_detected`, `::test_a_negative_number_is_not_a_port` |
| INV-20 | `tests/test_scanner.py::test_nothing_inside_node_modules_is_read` |
| § 4.4 rule 0's real `systemctl` calls behave as measured | **nothing** — every test injects `SupportsUnitLookup`, per `testing.md § T1`. The measurements in § 4.4 are dated and reproducible by hand; nothing re-runs them, and a `systemctl` whose output shape changes breaks detection with every test green |
| § 4.6's rules detect the *seven real* projects correctly | **nothing** — the fixture tree mirrors them, and a fixture that has drifted from the project it mirrors passes while the real detection fails. `testing.md § T1` forbids reading the real ones, so this is a limit rather than a defect |
| § 4.3's `errors="replace"` decode never raises on any real file | **nothing** — untestable in general; the tests cover UTF-8, Latin-1 bytes and a binary blob |
| § 4.2's self-exclusion under a **non-editable** install | **nothing** — INV-16 covers the source-checkout case, which is the one that occurs. A wheel install plus a checkout inside a scan root lists the checkout; judged not worth a second mechanism |

Twenty-four rows, **four** with a bolded `nothing` — this spec's honest error
budget, per `spec-format.md § 0`. Recounted after each review loop rather than
adjusted: 20 invariant rows plus 4. Three of the four are one shape — a test
fake, a fixture tree and a measured command line can only be as true as the day
someone last checked them against reality.

## 12. Cross-doc impact

Six documents change in the same release, across the twelve edits below.
Items 1–6a are all amendments to `design.md`, which this spec found
under-specified or wrong in seven separate places, and item 7 is the same for
`coding.md`. **They are not edited by this spec's gate** — that pass reviews
this document only. They land as one `Kind: doc-fix` commit alongside the
implementation and are gated then, which is also when the code proves each
correction was the right one. Until they land, `design.md` and this spec
disagree in items 1-6, and `coding.md` in item 7 — every one listed here on
purpose rather than silently reconciled (`.claude/workflow.md § 2`).

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
5. **`docs/design.md § Detection rules`, candidate selection** — gains the
   symlinked-candidate refusal. "Each scan root's **immediate subdirectories**
   are candidate projects" sanctions only the self-exclusion, and § 4.2's
   measurement shows `followlinks=False` does not cover a symlinked candidate.
6a. **`docs/design.md § Detection rules`, port rule 3's evidence** — "only
    when the launcher identifies a framework" is kept and made operational: the
    § 4.6 table names which evidence each launcher kind can reach, so a stray
    `manage.py` beside a `serve.mjs` cannot fabricate 8000. Numbered `6a`
    rather than renumbering, since § 4.6 already cites it.
6. **`docs/design.md § Detection rules § Where it looks`** — the recursive
   walk becomes a statement that the launcher rules are root-level, and that
   the depth bound and the eight excluded directory names constrain the
   one-hop target instead. Settled with the user 2026-08-08 (§ 3), so this is
   an amendment to make rather than a question to carry.
6b. **`docs/decisions/0003-launch-via-project-scripts.md`, the unit-name
    pattern** — the character class gains `\\`, so a systemd-escaped name can
    pass validation and reach an argv. Without it the escaping step § 4.4
    step 1 requires is dead code.
7. **`docs/standards/coding.md § O1`** — the core-module criterion becomes the
   four-way split in § 4.7. As worded it is a two-way split that covers
   `__main__.py`, which imports `QtWidgets` by design, so any check derived
   from it fails on landing. This is the amendment that makes INV-14
   implementable, so it ships with the code rather than after it.
8. **`CLAUDE.md § Module map`** — `scanner.py` added, and the note that
   `CORE_MODULES` now covers `applog.py` too.
9. **`CHANGELOG.md`** — an `Added` entry for detection, and a `Security` entry
   for LWSM-1050's bounds.
10. **`ROADMAP.md`** — LWSM-1006 and LWSM-1050 flipped on the closing commit;
    LWSM-1121 already filed.

## 13. Cold-eyes loop log

| Loop | Date | Lanes | CRIT | HIGH | MED | LOW | Outcome |
|------|------|-------|------|------|-----|-----|---------|
| 7 | 2026-08-08 | 2 (general-purpose, strong model) — lanes given **different methods again**: one played the attacker who owns a scanned directory, one *wrote the module on paper* from the document alone | Q2 ×2 · Q3 ×8 · Q4 ×2 | **12 verified, 0 unverified, 12 fixed.** Zero wording findings for the fourth loop running. The write-the-code lane is the method to keep: it found four gaps the adversarial lane did not, because "I cannot write this line without choosing" is a sharper test than "is this wrong". **Two findings would each have let one hostile project directory delete every other project's row:** `{"dependencies": 5}` makes rule 3's membership test raise **`TypeError`**, which is neither `ValueError` nor `RecursionError`, so it escaped `scan()` on the one path into `package.json` § 4.4's failure table did not govern; and `properties()` was never contractually total, so `props["WorkingDirectory"]` on a unit that sets none is a `KeyError` — also not an `OSError`. **The sharpest is the one the containment check was supposed to be:** `Path("").resolve()` **is the current working directory**, so an absent `WorkingDirectory` "resolves inside" whatever directory the manager was launched from — `cd ~/projects/foo && lwsm` and any name-matched unit binds, which is exactly the `mkdir <scan root>/project-a` attack step 2 exists to stop, arriving through the check meant to prevent it. Measuring that also found the value is rarely a bare path: **13 of the 14 real user units on this machine print `!/home/ants`**, and systemd's `-` / `!` prefixes were being resolved literally. Two more fabrication routes closed, both the loose-match shape this spec has now hit three times: `vitest` and `@vitejs/plugin-react` contain `vite`, and `import flask_login` contains `import flask`. And the escaped unit name — the only form `systemctl` accepts — **could not pass ADR-0003's own validator**, whose class has no backslash, so the unescaping step was dead code and every such project fell through to spawning a script systemd already owns. Two invariants added last loop had tests that could not fail: INV-20's fixture declared its port in `start.sh`, so the hop was never resolved and constraints 3 and 4 were unobservable; and a writer-less FIFO **reads as EOF, not a block** (measured), so INV-4's "did not block" stayed green with `S_ISREG` deleted. Doc 1673 → 1781 lines. |
| 6 | 2026-08-08 | 2 (general-purpose, strong model) — lanes given **different methods**: one worked error and boundary paths, one traced a concrete input through the document | Q2 ×3 · Q3 ×4 · Q4 ×1 | **8 verified, 0 unverified, 8 fixed** (10 raw; 2 found twice). **Zero wording findings again.** The count went 14 → 6 → 8 rather than continuing to halve, and the reason is visible in the split: giving the two lanes different *methods* surfaced classes a third identical cold read would not have. That is worth more than a monotone curve. **Three of the eight are the same shape — a mechanism `registry.py` already solved, re-implemented here without it**, which is `coding.md § 1.6` failing in its usual direction: (1) the `package.json` parse caught `JSONDecodeError` only, while 20,000 well-formed nested arrays in **40 KB** raise `RecursionError` (not a `ValueError`), invalid UTF-8 raises `UnicodeDecodeError`, and a root of `5` or `[1,2]` raises `AttributeError` on `.get("scripts")` — `registry.py::load_projects` names all three by hand and the scanner inherited none; (2) `DetectedProject.name` travelled **raw and unbounded** while skip reasons and `PortFinding.source` were both escaped-and-clipped, so a directory named `evil⏎PORT=1 detected` reaches the log and status bar by the one path that survives detection — the LWSM-1078 shape, at the one call site the sweep missed. Also: rule 2's fenced code still used `re.search` where the prose beside it promised `finditer`, so `'server_port': 70000, 'port': 5000` returned `None` against the prose's 5000; INV-17's fixture carried the `Environment=` prefix § 4.4 states `properties()` strips, so a literal fake makes a *correct* implementation fail and invites re-breaking `project-a`; § 3 claimed § 7 tests that nothing under `node_modules` is opened, and **no such test, fixture, invariant or row existed** — the one place the no-walk decision trades a mechanism for a claim, now INV-20; a `SHELL` project running `exec node serve.mjs` with a stray `manage.py` reached Django's 8000; `scripts.dev` present-but-invalid had no defined fall-through; and INV-8's 300-character case was unreachable through `scan()` (`NAME_MAX` is 255) so it survived deleting the bound it tests. Doc 1563 → 1661 lines. |
| 5 | 2026-08-08 | 2 (general-purpose, strong model) | Q2 ×3 · Q3 ×3 | **6 verified, 0 unverified, 6 fixed** (9 raw across the lanes; 4 were the same defect found twice). **Again zero wording, structure or duplication findings from either lane.** Count halved against loop 4 (14 → 6) with the signal still at 100%, which is what convergence looks like when the instrument is only asking about the build — loops 1–3 held flat at ~25 findings a loop because six of their fifteen dimensions could never come back clean. **The pass's best find is the one mechanism § 4 still stated as prose:** the one-hop target was "the **last** `exec`, `python3`, `python` or `node` invocation naming a path", which never said *which token* is the path — measured 2026-08-08, `exec python3 -u launcher.py` gives `python3` under "the token after the keyword", `exec env PORT=1 python3 launcher.py` gives `env`, and `python3 -m http.server 8080` gives `-m`. It is now a four-step tokenise-and-select rule, and it also gained the comment stripper, without which a `# exec python3 old.py` *below* the live invocation is "the last" one and the Scanner hops to the retired launcher. Also: the two markers `;` was dropped from in loop 4 were still parametrised in INV-19, so its test would have gone red against the stripper the same document specifies; rule 3 had three frameworks and no precedence, so `manage.py` beside `import flask` was 8000 or 5000 depending on the implementer; a hung `systemctl` drew its timeout from the *scan* budget, so one hang consumed all 20 s and returned zero projects against § 6's promise that a systemd-less machine "scans normally" — it now has its own 2 s bound; INV-7's masked-vs-not-found test had **no differing observable** to assert, so it passed against exactly the implementation it forbids, and masked now records a reason where not-found records none. One collateral: loop 4 narrowed rule 2 to a single source in § 4.4 and left § 4.6 restating three rules as two-source. Doc 1497 → 1563 lines. |
| 4 | 2026-08-08 | 2 (general-purpose, strong model) — **first loop under the four-question brief** | Q1 ×2 · Q2 ×5 · Q3 ×5 · Q4 ×2 | **14 verified, 0 unverified, 14 fixed**, plus 1 collateral. **Every finding from both lanes changed what gets built; neither returned a single wording, structure or duplication finding.** That is the brief, not luck: it asks four questions and names the rest out of scope. Against loop 3's ~11 build-changing out of 26, the signal went from 42% to 100% and the brief itself from 24 KB to 3.4 KB. The worst three, none reachable by the fifteen-dimension passes that preceded them: **(1)** `package.json`'s dependency block was being fed to the port rules, and `"get-port": "^7.0.0"` — a real, common npm package — yields port **7** through `KEY_IS_PORT`'s hyphen; `"detect-port"` yields **1**. Scope narrowed to the chosen `scripts` value alone. **(2)** `systemctl show -p Environment` prints `Environment=STATS_PORT=4321 …`, and splitting *with* that prefix leaves a first token on which rule 2's key is `Environment` and rule 1's `PORT=` is preceded by `_` — neither matches, so `project-a` comes back *unknown*, the precise failure INV-17 exists to prevent. The `NAME=` prefix removal is now stated. **(3)** The `;` I had added to the comment-marker set is a **statement separator**, not a comment marker, in every language this module reads: `cd /app ; exec node serve.mjs --port 8080` lost its port, so did an npm `"dev"` script and a shell assignment. Dropped. Also: the ordering *inside* one source was left open where the ordering *between* sources had been settled (line-major, 3000 vs 8080 on the same file); `path` was "absolute" where four other clauses need it *resolved*, which under a symlinked scan root gives one project two registry identities; `systemctl` failing with no D-Bus session raises `JSONDecodeError`/`CalledProcessError`, neither an `OSError`, so `scan()` raised instead of degrading; INV-16's fixture had no launcher, so rejection 5 already excluded it and the self-exclusion guard shipped unreached; and a refused launcher dropped the whole candidate, letting anyone who can plant a symlink named `start.sh` delete a project from the manager. The one collateral: dropping `;` retired the measurement that justified the `ExecStart` stripper exemption — the exemption is kept on its scope argument and the stale reason replaced, caught by the conformance script on the next run. Doc 1265 → 1497 lines. |
| 3-conf | 2026-08-08 | **none — no reviewer dispatched.** An execution pass, not a review loop | 1 | 1 | 1 | 1 | **4 verified, 4 fixed.** `docs/specs/LWSM-1006-conformance.py` transcribes every pattern, bound and predicate § 4 prescribes and runs them against inputs chosen to break them. Written after loop 3 on the observation that all three of that loop's CRITICALs were false claims about *patterns* — a class no reader catches and no reviewer is needed for. It found, in one run: **(CRIT)** `re.search(r"\d{1,5}(?![0-9])", " 123456")` returns **23456** — a lookahead alone does not reject a longer number in a *search*, because the engine advances past the unmatchable first digit and matches the tail; rule 1 was immune only because `PORT=` anchors its digits, so the fix applied one loop earlier had been applied to the call site rather than to the mechanism (`coding.md § 1.6` exactly). **(HIGH)** `# PORT=9999 (old)` was detected as port 9999 — no rule anywhere mentioned comments, and a commented-out previous port is the commonest shape in a real launcher. **(MED)** the quote-aware stripper written to fix that cut `http://localhost:3000` at the `//`, killing a documented rule-1 form, at 766 µs/call against the replacement's 64 µs. **(LOW)** `PORT = -1` yielded **1**. Also corrected: § 4.4's stated reason for splitting `Environment=` was wrong — the real failure is that `partition` examines only the first `KEY=`, so a port that is not the first variable is invisible. The run is recorded here rather than as a loop because **no reviewer was dispatched**; it is a deterministic check, and it converges where a judgement review does not. |
| 3 | 2026-08-08 | 2 (general-purpose, strong model) | 3 | 4 | 6 | 13 | **26 verified, 0 unverified, 26 fixed**, plus 2 collateral the 4b sweep caught. Dimensions: dim 5×8, dim 4×6, dim 7×3, dim 10×2, dim 6×2, dim 1×2, dim 2×1, dim 15×1, dim 11×1. **Origin split: 6 draft defects against ~20 fix collateral** — the decisive margin the loop-economics rule names, and the reason this run stops here rather than dispatching a fourth. **All three CRITICALs were defects the previous two loops' own fixes introduced**, which is the shape that margin describes. (1) Loop 2's `\d{1,5}` does not *reject* a longer number, it takes the first five digits of one: measured, `PORT=123456` → **12345**, `--port 999999999` → **99999**, each passing the range check and fabricating a port out of a line that declares none — the one outcome § 4.1 forbids. `(?![0-9])` closes it. (2) Loop 2's INV-9 said both rules exclude the underscore; rule 2's shipped class **admits** it, and must, since that is the only reason `DEFAULT_PORT` and `server_port` match at all — an implementer building from that invariant loses two of the seven detections § 7 requires. (3) Loop 1's INV-15 fixture, `"a" * 4092 + "port"`, contains no separator, so `rule_2` returns before `KEY_IS_PORT` ever runs: instrumented at **0 regex calls**, green by construction, and green under its own prescribed mutation. The corrected fixture costs **74.41 µs** against the 0.24 µs the old one "measured" — so loop 1's figure was timing an early return. Two draft defects worth naming: an unreadable launcher's effect on its *candidate* was never stated (both a listed project with no port and a skip passed INV-1 and INV-4), and `skipped` reasons plus `PortFinding.source` were length-bounded but never **escaped**, while § 4.3's own § 1.6 sweep asserted both halves were present — a filename may contain a newline, which is LWSM-1078 exactly. The duplicated 18-row invariant→test table in § 7 was deleted in favour of § 11's. Doc 1195 → 1265 lines. |
| 2 | 2026-08-08 | 2 (general-purpose, strong model) | 2 | 4 | 7 | 11 | **24 verified, 0 unverified, 24 fixed**, plus 7 collateral the 4b sweep caught. Dimensions: dim 5×6, dim 4×4, dim 2×4, dim 7×3, dim 10×3, dim 15×2, dim 12×1, dim 6×1. **Origin split: 12 draft defects, 12 fix collateral** — no decisive margin either way, so the loop dispatched rather than sweeping. Both lanes led with the same contradiction, and it was collateral: loop 1 changed § 4.4's missing-unit signal to `LoadState=not-found` and left § 8 asserting the empty `FragmentPath` it had just retired. **The loop's most valuable finding was a draft defect neither loop-1 lane reached, and it is a security gap** — INV-1 has promised since the first draft that a symlink resolving out of the project is refused, and no rule implemented that half for the *launcher itself*: `commonpath` guarded only the one-hop target. Measured 2026-08-08, a `start.sh` symlinked outside the project passes `S_ISREG` **and** `os.access(X_OK)` — both describe the target — and its contents are read. `O_NOFOLLOW` is the only guard that sees it, which is precisely the LWSM-1050 containment promise this item is chartered to land. Second: **rule 1 had no pattern at all**, only prose, while running *ahead* of the rule § 4.6 had carefully bounded — measured, an unanchored `PORT=` returns 99 for `TRANSPORT=99` and 4321 for `APP_PORT=4321`, the latter being INV-17's own fixture. It also missed `PORT=${PORT:-N}` entirely, the form `project-g` uses. Third, from executing the new reader: **a minified `package.json` is 6,252 characters on one line**, so the 4096 line cap turned an ordinary artefact into `JSONDecodeError` and silently dropped a legitimate Node project; § 4.3 now has two readers. Doc 1042 → 1201 lines. |
| 1 | 2026-08-08 | 2 (general-purpose, strong model) | 3 | 7 | 7 | 8 | **25 verified, 0 unverified, 25 fixed.** Dimensions: dim 5×10, dim 4×4, dim 7×3, dim 15×3, dim 10×2, dim 6×2, dim 2×1. **Both lanes independently led with the same two defects**, which is the strongest corroboration this gate produces. (1) **A `systemd` project had no port-detection path at all** — § 4.5 restricted the one hop to `SHELL`, rule 0 read the unit only to *bind* it, and § 4.6 named no source, so `project-a` came back *unknown* and the acceptance test could not pass; both roadmap bullets say this item carries the unit's `Environment=` / `ExecStart`. Now § 4.4 step 3. (2) **INV-14 prescribed a test that fails on landing**: it derived `CORE_MODULES` from `coding.md § O1`'s criterion, which is a two-way split covering `__main__.py` — and `__main__.py` imports `QtWidgets` by design, so the derivation would also redden the sibling test. The criterion itself is now amended (§ 12 item 7). Lane B alone found the third: **INV-10's discriminating fixture was rejected by this spec's own rule 2** — `PORT_BASE` ends in `BASE`, so both orderings returned 8080 and the test guarding the file-major decision was green by construction. Also fixed: the reason list had `registry.py`'s per-reason clip and not its `MAX_REASONS` count cap (§ 1.6's exact failure shape, one pass after the spec cited that very site); `PortFinding.line` carried a hostile file's bytes to the log and status bar unescaped, and the field was **deleted** rather than defended; INV-15 asserted a 40,000-character line that INV-3 makes unreachable. **A 26th defect came from Phase 4a's execute-before-it-lands rule, not from a lane:** the prescribed `systemctl --user show -- <unit> -p FragmentPath` puts its options *after* the `--`, so `systemctl` reads them as unit names and dumps all **832** property lines. Three invariants added (INV-16 self-exclusion, INV-17 the systemd port, INV-18 the reason cap). Doc 716 → 1042 lines. |
