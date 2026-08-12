# LWSM-1007 — Persist the registry: the file format and the writer

**Status:** spec draft (2026-08-12).
**Kind:** implement.
**Source:** ROADMAP LWSM-1007 (in-session-2026-08-03). Policy settled by
[ADR-0005](../decisions/0005-registry-and-rescan.md); this is half of its
mechanism. **Narrowed from an umbrella spec on 2026-08-12** — see § 3.
**Blocked by:** LWSM-1006 (shipped 2026-08-12).
**Blocker for:** LWSM-1131 (merge a rescan into the stored registry),
LWSM-1039 (keep one backup of the registry), LWSM-1008 (first-run
confirmation flow).
**Pairs with:** [LWSM-1131](LWSM-1131-rescan-merge.md), the other half of the
split. This spec owns what a record *is* and how it reaches the disk;
LWSM-1131 owns what a rescan does to it.

**Layman:** Remember the project list between runs — and never lose a
hand-edited file to a bad save.

## 1. Goal

`projects.json` becomes a file the app **writes** as well as reads. The record
grows the fields [ADR-0005](../decisions/0005-registry-and-rescan.md) says it
holds, each one classified as user-owned or detected, and the write is atomic,
durable, private, and refused outright in the two cases where performing it
would destroy a hand-edited file.

Two acceptance criteria, stated against what this item actually builds:

1. A record with **every** field populated survives a write and a reload as an
   equal record *sequence* — same records, same order (INV-3).
2. A `projects.json` with one hand-written row the loader refuses is **not**
   written over, and the refusal says why (INV-6).

**Nothing in this item calls the writer.** The only caller is LWSM-1131's
merge; until it lands, the writer is reachable from tests alone. That is
deliberate and is the point of the split — a record format and an atomic write
are a contract several items bind to, and they are settled before anything
depends on them. **Editing fields from inside the app is not part of this item
either**, and no section below specifies a surface for it: `renaming, hiding
and overriding from the UI` is P07's LWSM-1014 for the port override, and there
is no roadmap item for renaming yet.

## 2. Problem

`src/lwsm/registry.py` is a reader with no writer. `load_projects()` returns
`(records, reasons)` and nothing anywhere in `src/` produces the file it parses,
so today the file is hand-authored and every edit the app might make is lost the
moment the process exits. Three consequences, each grounded in a symbol read for
this spec rather than recalled.

1. **The record cannot hold what ADR-0005 says it holds.**
   `registry.ProjectRecord` is a frozen dataclass of four fields — `path`,
   `name`, `port`, `port_override`.
   *Command:* `awk '/^class ProjectRecord:/,/^    @property/' src/lwsm/registry.py | grep -cE '^    [a-z_]+: '` → `4`.
   ADR-0005 § Decision names seven user-owned fields (display name, hidden flag,
   port override, launcher override, notes, start-at-login flag, and the
   `actions` list) and four detected ones (launcher command, declared port,
   runtime kind, systemd unit name). Exactly three of those eleven have a home
   today — `name` is the display name, `port` the declared port, `port_override`
   the port override — so **eight have nowhere to live**. (`path` is the fourth
   field and is neither: it is the identity ADR-0005 keys on, which is why § 4.1
   classifies it separately.)

2. **The obvious writer destroys data, and it does so silently.**
   `load_projects` returns rejected rows only as reason *strings* — they are not
   in `records`, and there is no path from a reason back to the JSON object it
   came from. So the natural implementation, serialising `records` back over the
   file, **permanently deletes every row the loader refused**: a project whose
   `name` was blank, whose `path` was relative or contained `..`, or that
   duplicated an earlier path. Those are hand-written rows with a hand-written
   intent. This is the one data loss this app is capable of — the thing
   LWSM-1039 exists to insure against, arriving through the writer rather than
   through corruption, and with LWSM-1039 not yet built to catch it. § 4.3
   closes it and INV-6 tests it.

3. **A "is this a regular file?" check does not mean what it reads as.** The
   write must not destroy a user's deliberate symlink, and the natural
   implementation of the refusal *follows* the link and permits exactly the case
   it was written to refuse. Measured on this machine, Python 3.13 — § 4.3
   carries the run. This is not a hypothetical: it survived the umbrella spec's
   own FIFO test, which stays green through the bug.

**Two** entries in `docs/known-issues.md` name LWSM-1007 as their owner after
the split, and **this item closes one of them**: known-issue-034 (the unpinned
`scanner` constants — INV-7). known-issue-025 (identity) moved to LWSM-1131
with the merge, which is where identity is compared.

*Command:* `awk '/^## known-issue-/{h=$0} /^- \*\*Will be addressed in:\*\* LWSM-1007/{print h}' docs/known-issues.md`

**known-issue-033 stays open.** It was routed here as "the next item to add
source files and so the first that could add a subpackage", and its one item
with reach is that `test_layering.py` globs `SRC.glob("*.py")` non-recursively,
so a core module under `src/lwsm/<subpackage>/` would be invisible to the
derivation test. **This item adds no subpackage** — every change lands in the
existing `registry.py` — so the premise that routed it here does not fire, and
fixing a latent glob while nothing can trigger it is work without a test that
would fail first. It stays routed and its owner is re-decided when something
actually adds a subpackage.

## 3. Scope decisions (agreed with the user)

- **Phase.** This item opens `P03b`, the continuation phase carrying the four
  items P03 planned and did not deliver (user, 2026-08-12). Commits read
  `P03b: …`.
- **This spec is one half of a split, and the split is why it exists in this
  shape** (user, 2026-08-12). The umbrella spec — *Persist the registry, and
  merge a rescan without discarding user edits* — reached `review-contract`'s
  3-loop cap without converging. Every one of its 34 findings was verified and
  fixed and none ever resurfaced, so the fixes held; what kept arriving was new
  surface. The document went **540 → 692 → 852 → 979 lines** while the finding
  count held flat at **12 / 10 / 12**, and each loop's findings clustered in a
  *different* region. That is the "two cold reads never reached parts of it"
  shape, so `spec-format.md § 5.4` and global rule 14's *past loop 3, split
  rather than loop* both apply. The seam is § 4 of the umbrella: this part takes
  the record format and the writer, [LWSM-1131](LWSM-1131-rescan-merge.md) takes
  the merge. **Neither part inherits the umbrella's review** — the loops ran
  against a document that no longer exists, so each runs the gate from loop 1 on
  its own bytes.
- **The id and the path are kept, not reallocated.** Inbound citations —
  `docs/known-issues.md`, `.claude/workflow.md`, LWSM-1039's and LWSM-1008's
  dependency lines — all name LWSM-1007, and a new slug would orphan every one
  of them.
- **Invariants are renumbered from 1**, per `/write-spec`'s splitting rule: a
  part is a new contract at a narrower scope, and carrying the umbrella's sparse
  numbering into an eight-invariant document would read as nine missing
  invariants. **The mapping, so the umbrella's citations stay findable:**

  | Umbrella INV | Here | Subject |
  |---|---|---|
  | INV-1 | **INV-1** | every record field is classified |
  | INV-7 | **INV-2** | a write failing before `os.replace` rolls back |
  | INV-8 | **INV-3** | round-trip to an equal record sequence |
  | INV-9 | **INV-4** | private regular file; a symlinked target is refused |
  | INV-12 | **INV-5** | a pre-existing file still loads; `SCHEMA_VERSION` is 1 |
  | INV-16 | **INV-6** | a row refusal or a `RegistryError` makes the session read-only |
  | INV-14 | **INV-7** | the shipped bounds are pinned at their literal values |
  | INV-13 (writer half) | **INV-8** | no writer-refusal reason skips `_quoted` |

  Umbrella INV-13 is the one finding that genuinely splits. It covered "no value
  reaches **a report entry**" across both halves, and the halves are two
  different surfaces — this part's writer-refusal reasons, and LWSM-1131's merge
  report. Each part states its own rather than one part citing an invariant it
  does not own. Umbrella INV-2, -3, -4, -5, -6, -10, -11, -15 and -17 are all
  merge rules and moved wholesale to LWSM-1131 § 3's mirror of this table.
- **Section numbering follows the global standard, and the siblings differ.**
  `~/.claude/standards/spec-format.md § 4` requires recommended sections
  "appended after § 3's twelve, numbered from 13 … never interleaved", so
  *Resource cost* is § 13 here. `LWSM-1005` and `LWSM-1006` interleave it at
  § 10 and push the last three one higher. They are the ones that are wrong;
  `docs/known-issues.md` known-issue-036 owns the sweep that renumbers them, and
  records why the fix could not be taken mid-split.
- **`schema_version` stays `1`.** Every new field is optional with a documented
  default, so the hand-written files that exist today keep loading. § 8 records
  the rejected alternative.

## 4. Design

### 4.1 The record grows two halves, and every field is classified

`ProjectRecord` stays one flat frozen dataclass — `controller.ProjectController`
and `mainwindow.ProjectRow` read `record.path`, `record.name` and
`record.effective_port` today, and splitting the type would rewrite consumers
for no gain (`coding.md § 1.3`, reuse before rewriting). The two halves become
**explicit membership** instead:

```python
# registry.py
DETECTED_FIELDS: frozenset[str] = frozenset({"path", "port", "kind", "argv", "unit"})
USER_FIELDS: frozenset[str] = frozenset(
    {
        "name",
        "port_override",
        "hidden",
        "launcher_override",
        "notes",
        "start_at_login",
        "actions",
        "added",
    }
)
```

`added` is a user-owned timestamp because ADR-0005 makes it the duplicate-port
tie-break, and a rescan must not be able to reorder that.

INV-1 makes a field belonging to neither set a failing build. **The sets are
declared here and consumed by LWSM-1131**, whose merge replaces
`DETECTED_FIELDS - {"path"}` and keeps the user half. The subtraction is stated
in that spec because it is a rule about merging; what this spec owns is that
`path` is *classified* detected — a scan is what observes it — while being a
field no write may resolve (§ 4.2).

**`LauncherKind` moves from `scanner.py` to `registry.py`, and `scanner.py`
imports it from there.** Typing `kind` needs the enum in `registry`, and
`scanner.py` **already** imports `from lwsm.registry import DECLARED_PORT_RANGE`
(its module-level import block) — so an implementer adding `from lwsm.scanner import
LauncherKind` to `registry.py` closes a cycle and **the application stops
importing at all**. Measured on this tree, both entry orders, with that import
added and nothing else changed:

```
python3 -c "import lwsm.registry"
  ImportError: cannot import name 'DECLARED_PORT_RANGE' from partially
  initialized module 'lwsm.registry' (most likely due to a circular import)

python3 -c "import lwsm.scanner"
  ImportError: cannot import name 'LauncherKind' from partially initialized
  module 'lwsm.scanner' (most likely due to a circular import)
```

Moving the enum down keeps the **existing** dependency direction (`scanner` →
`registry`) rather than adding a second one, and costs one import line in
`scanner.py`. The rejected alternative — storing `kind` as a `str` validated
against a hard-coded tuple of the four values — is in § 8: it duplicates the
enum in the module least likely to be updated when a fifth kind is added.
`LauncherKind` is cited by name in `docs/specs/LWSM-1006-scanner-detection.md`
and in `CLAUDE.md § Module map`; both name it as a `scanner` symbol and are
listed in § 11.

### 4.2 The file format

```json
{
  "schema_version": 1,
  "projects": [
    {
      "path": "/srv/project-a",
      "name": "Project A",
      "port": 3000,
      "port_override": null,
      "kind": "node",
      "argv": ["npm", "run", "dev"],
      "unit": null,
      "hidden": false,
      "launcher_override": null,
      "notes": "",
      "start_at_login": false,
      "actions": [],
      "added": "2026-08-12T14:03:11Z"
    }
  ]
}
```

Every key except `path` and `name` is optional on read. The default for each,
covering all eleven — an unlisted key would be one an implementer has to invent
a default for, which is how `kind` was missed in an earlier draft:

| Key | Type | Default when absent | Present and the wrong type |
|---|---|---|---|
| `port`, `port_override` | `int \| None` | `null` | field dropped, reported |
| `unit`, `launcher_override` | `str \| None` | `null` | field dropped, reported |
| `kind` | `LauncherKind \| None` | `null` — an unknown launcher kind | field dropped, reported |
| `hidden`, `start_at_login` | `bool` | `false` | field dropped, reported |
| `notes` | `str` | `""` | field dropped, reported |
| `argv` | `tuple[str, ...]` | `()` | field dropped, reported |
| `actions` | `tuple[str, ...]` of canonical JSON, see below | `()` | field dropped, reported |
| `added` | `str \| None`, any RFC 3339 instant | `null` | field dropped, reported |

**The fourth column is one blanket rule, and it is stated because the file is
hand-editable and most of these keys had no answer.** A present value of the
wrong type **loses the field and is reported** — exactly what `_port_or_reason`
already does for a bad port. It is a *field* refusal, so it never makes the
session read-only (§ 4.3, INV-6). The two required keys are the exception and
are **row** refusals: a non-string `name` or `path` drops the whole object, as
`load_projects` does today.

**A dropped field's original text is lost on the next write, and that is
accepted rather than defended.** The record holds the parsed value, so the
writer emits the default and the hand-typed `"port": "3000"` is gone. The
asymmetry with a refused *row* (§ 4.3, which refuses to write at all) is
deliberate and rests on one distinction: **a refused field's text is by
definition not a valid value of that field, while a refused row may be entirely
valid apart from one typo.** The user is told at load either way. § 8 records it
beside the carry-through alternative.

**`kind` accepts only a value of `LauncherKind` — `"systemd"`, `"shell"`,
`"node"`, `"python"` — serialised as the enum's `value`, never its name.** An
unrecognised string is the fourth column's case. The enum lives in `registry.py`
per § 4.1.

**`argv` loads back as a tuple, not a list.** JSON has only arrays, so a loader
returning a `list` produces a record unequal to the one written while every
value looks right — INV-3's failure mode exactly. `argv`'s tuple form also
matches `scanner.DetectedProject.argv`, so the merge compares like with like.

**`actions` is persisted opaquely and its schema is NOT defined here.**
`docs/design.md § Custom project actions` makes an action *a label plus one of
three kinds* — `open_file`, `open_url`, `run_command` — each with a payload, and
attaches four security rules to them (`open_url` parsed not concatenated,
`open_file` `commonpath`-checked and refusing the execute bit, `run_command` an
argv validated **on load** and owned by the `Supervisor`). None of that is built
by this item or by LWSM-1131, so **the per-action schema and design.md's
load-time validation land with the item that builds the action surface** — the
only place that validation has a failure surface to report to.

**The stored form is one canonical-JSON string per element**, not the decoded
objects: `load_projects` type-checks only that the value is an array, then
stores `tuple(json.dumps(e, sort_keys=True, separators=(",", ":")) for e in
value)`, and the writer `json.loads` each back. Three reasons this shape and not
the obvious one. A `tuple[dict, ...]` makes `ProjectRecord` **unhashable** — the
dataclass is `frozen=True`, so it generates a `__hash__` that raises `TypeError`
the moment anything hashes a record with actions. A `list` fails INV-3's `==`
round-trip for the same reason `argv` does. And leaving the type unstated makes
an implementer pick one of those two. **The cost, stated: key order inside an
action is normalised**, so a hand-written action's key order is not preserved
byte-for-byte, though its value is.

**`added` is written by this app as RFC 3339 with a `Z` suffix and second
precision.** That spelling governs **only values the app stamps**; a value
already in the file is written back **verbatim**, so a hand-edited `+01:00` is
preserved rather than rewritten. The two rules have to be separated, because
"never rewritten once set" and "written with a `Z` suffix" cannot both hold for
a stamp the reader is required to accept in any RFC 3339 spelling.
**LWSM-1131 owns who stamps it and how it is compared** (its INV-9 requires a
parsed instant rather than text). **This item parses it too** — the fourth
column's rule needs to decide whether a present `added` is well-formed, and
that decision is a parse, which is why § 13 lists `datetime` as arriving here
and not with the sibling.

**Well-formed means: `datetime.fromisoformat` succeeds AND the result's `tzinfo`
is not `None`.** The `tzinfo` clause is the whole of the rule and the other
obvious ones are redundant, which is worth stating because a longer rule reads
safer and is not. Measured here:

```
'2026-08-12'                -> ok, tzinfo=None      # NOT an instant
'2026-08-12T14:03:11'       -> ok, tzinfo=None      # NOT an instant
'2026-08-12T14:03:11Z'      -> ok, tzinfo=UTC
'2026-08-12T15:03:11+01:00' -> ok, tzinfo=UTC+01:00
'yesterday'                 -> ValueError
```

So `fromisoformat` is far broader than RFC 3339 and admits two spellings that
denote no instant — and **"must carry a time" would not catch them**, because a
date-only value parses to midnight and has one. A value with no offset cannot be
ordered against one that has an offset, and LWSM-1131's INV-7 tie-breaks on
exactly that ordering. Anything failing either clause is the fourth column's
case: **dropped and reported**, never compared.

**`path` is written back as the loader's `Path`, not as the user's raw text.**
No writer *resolves* a path or follows a symlink, and that is the rule LWSM-1131's
INV-8 tests the merge side of. But it is not byte-verbatim, because
`load_projects` discards `raw_path` and stores `Path(raw_path)`
(`load_projects` builds `Path(raw_path)`, stores that, and discards `raw_path`), and `Path` normalises on construction. Measured on
this tree:

```
'/srv/a/'   -> '/srv/a'      # trailing slash dropped
'/srv///a'  -> '/srv/a'      # three or more slashes collapse
'/srv/./a'  -> '/srv/a'      # single-dot component dropped
'//srv/a'   -> '//srv/a'     # exactly two are preserved, and are refused anyway
```

So a hand-written `/srv/a/` comes back as `/srv/a`. That is a real change to the
user's file and is stated rather than promised against; carrying the raw string
would mean a second field in `ProjectRecord` holding text no consumer reads.

**The stored `port` is a bare `int`, and a detected port's provenance is
deliberately not persisted.** This is the one detected field where the format
and `DetectedProject` are not the same type: `scanner.DetectedProject.port` is
`PortFinding | None`, and `PortFinding` carries `port`, `rule` and `source` —
which its own docstring calls "the whole of the provenance the UI needs". The
format defines no key for `rule` or `source`, so a merge stores
`finding.port` and the rest is recomputed on the next scan rather than
round-tripped. Said explicitly because the alternative — an implementer
inventing `port_rule` and `port_source` keys, or silently dropping provenance
and not knowing whether that was intended — is exactly the invention this
section exists to prevent. The cost is that provenance survives a scan but not a
restart, so a rescan is what re-establishes it; § 9 records it.

**No merge outcome is persisted.** The flags LWSM-1131 produces — *new*,
*missing*, *not re-observed*, *override differs*, *duplicate identity* — are
report entries about one merge, not record state. Nothing in this format records
them, which is a constraint on that spec and the reason its per-row flags are
summary-only.

**Compatibility with the hand-written files that exist.** A v1 file carrying
only the four fields `load_projects` reads today loads unchanged, with every new
field taking its default. This is why `schema_version` does not move: the
reader's version check is exact (`version != SCHEMA_VERSION` raises), so bumping
it would refuse every existing file to buy nothing. INV-5 locks it.

### 4.3 Writing the file

**The two signatures, because the outcomes below cannot be evaluated without
them and LWSM-1131 § 9 binds to the second:**

```python
# registry.py


@dataclass(frozen=True)
class LoadResult:
    """What `load_projects` returns. Replaces the `(records, reasons)` tuple."""

    records: list[ProjectRecord]
    reasons: list[str]  # every refusal, row-level and field-level alike
    rows_refused: int  # ROW refusals only; `reasons` is not a proxy for it


class RegistryMissing(RegistryError):
    """Raised when the file is absent. A subclass, so existing
    `except RegistryError` handlers keep working unchanged."""


def load_projects(path: Path) -> LoadResult: ...


def save_projects(
    path: Path,
    records: Sequence[ProjectRecord],
    *,
    load: LoadResult | RegistryError,  # the load these records came from
) -> None:
    """Write atomically, or raise `RegistryError` naming why it refused."""
```

**`load_projects` returns a dataclass, not a widened tuple.** `rows_refused`
cannot be derived from `reasons` — a field refusal appends a reason and keeps
the row (§ 4.2), which is the whole of INV-6's discriminating case. A third
tuple element would break every two-value unpacking just as visibly while
reading worse. **This is a breaking change to one production caller,
`__main__.build_window`, plus the loader's existing tests**; § 11 lists both.

**The gate lives inside `save_projects`, not in its caller**, and `load` is how
it gets there. This item builds no caller at all, so a gate in the caller would
be a gate nothing implements — and LWSM-1131 § 4.4 says "the merge does not
re-implement that check; it calls a writer that enforces it."

Atomic replace, in the target's own directory so the rename cannot cross a
filesystem:

0. **Create `path.parent` at mode `0700` if it is absent**, and this step is
   `save_projects`' own — nothing else in this item runs. § 6 requires the
   directory to exist "before the first write", and § 1 says nothing here calls
   the writer, so a caller-side `mkdir` would be a step no code performs and
   first run would raise on the exact path § 4.3 exists to enable.
1. Create a temporary file in `path.parent`, mode `0600`.
2. Write the serialised JSON; `flush()`; `os.fsync()` the file descriptor.
3. `os.replace(tmp, path)` — atomic for any concurrent reader.
4. `os.fsync()` the **directory** descriptor, so the rename itself is durable
   rather than only the bytes.
5. On any failure **before step 3 completes**, unlink the temporary file and
   raise `RegistryError`.
6. A failure at step 4 is **reported and not reversed**: the new file is
   already in place, there is no temporary file left to unlink, and rolling
   back would mean having kept a copy of the old one — which is LWSM-1039.

Steps 5 and 6 are split because "on any failure" covered step 4 and contradicted
INV-2: it would have an implementer unlink a path that no longer exists and
raise `RegistryError` for a write that actually succeeded, so § 6 would tell the
user the write failed about a durable file.

Step 4 is the one usually omitted, and omitting it means a crash can leave the
directory entry pointing at neither version. Step 1's mode matters because the
file records local paths and a start-at-login flag.

**The target is checked with `os.lstat`, before it is replaced.** The write is
refused when `path` exists and is either a symlink or a non-regular file.

**`os.stat` is the wrong call here and `Path.is_file()` is the same mistake**,
because both follow the link: a symlink pointing at a regular file reports
`S_ISREG` true, passes the check, and is then destroyed by `os.replace`, which
replaces the *symlink* rather than its target. Measured on this machine, Python
3.13:

```
link.is_file()                 -> True
S_ISREG(os.stat(link).st_mode) -> True      # follows — the trap
S_ISREG(os.lstat(link).st_mode)-> False
S_ISLNK(os.lstat(link).st_mode)-> True
os.replace(tmp, link); link.is_symlink() -> False   # indirection gone
```

The real file was left untouched and the user's deliberate indirection was
silently converted to a plain file — which is precisely what the refusal exists
to prevent, and what a following stat would have permitted.

**The `lstat`-then-`replace` race is accepted, and saying so is the point.**
Both `_read_bounded` and `applog._require_private_regular_file` interrogate a
*descriptor*; this check interrogates a *path*, so a symlink planted between the
`lstat` and the `os.replace` is destroyed anyway. It is accepted rather than
closed because the fd-based form is not available: `os.replace` takes paths, so
there is no descriptor to hold across the swap, and the only real fix is a
directory fd plus `renameat`, which buys nothing against an attacker who can
already write to a `0700` directory owned by the user. An implementer should
**not** add a retry loop; there is no state to re-check into.

This stays deliberately narrower than `applog._require_private_regular_file`,
for the reason `_read_bounded` already records: a config file may reasonably be
hard-linked or installed for the user, so ownership and link count are not
demanded. A **symlink** is refused rather than followed because replacing one
destroys it; a **hard link** is not, because replacing the path leaves the other
name intact.

The serialised output is bounded by the same `MAX_FILE_BYTES` the reader
enforces; a registry that would exceed it is refused with a reason rather than
written and then found unreadable on next start.

**Nothing is written while the load that produced the records had a ROW
refusal.** § 2 item 2 is why. So: **a load that refused a whole row makes the
session read-only.** Whatever produced the records still runs and still reports,
the UI still shows what would have changed, and the write is refused with a
reason naming the count. The user fixes the file, or deletes the bad rows
deliberately, and the next start writes normally. § 8 records the alternative
that was rejected.

**Row-level, not any reason — the distinction is the whole rule.**
`load_projects` writes to `reasons` for two different things. A **row** refusal
(`'name' must be a non-empty string`, a relative path, `..`, a duplicate) drops
the object, and that is the data the writer would destroy. A **field** refusal
(`port 70000 is not an integer 1-65535`, and now an unrecognised `kind`) keeps
the row and only drops the field — `_port_or_reason` returns a reason and the
record is still appended. Keying the gate on `reasons` being non-empty would
therefore let one hand-typed `"port": "3000"` disable persistence for the whole
session, on a file with nothing at risk. **So `LoadResult` carries
`rows_refused` separately from `reasons`**, and that count is what the gate
reads.

**Four states, and only the first two may write:**

| At load | May write? |
|---|---|
| `RegistryMissing` — the file is absent | **yes** — this is first run, and a fresh `projects.json` is created |
| `LoadResult` with `rows_refused == 0` | **yes** — including when fields were dropped |
| `LoadResult` with `rows_refused > 0` | no — read-only, reported |
| any other `RegistryError` (unparseable, wrong `schema_version`, unreadable, a directory, a FIFO) | no — read-only, reported |

**The absent file is a `RegistryError` today, and that is why `RegistryMissing`
exists.** `_read_bounded` opens with `os.open`, so a missing
file raises `FileNotFoundError`; `load_projects` converts **any** `OSError` into
`RegistryError` in its `except OSError` handler, whose own comment says so — "Any
OSError, not just FileNotFoundError". An earlier draft of this table listed "no
file at all" and "`RegistryError` raised" as separate states, which are the same
state: an implementer gating on "no `RegistryError`" would ship an app that is
**permanently read-only on a clean machine**, where `projects.json` is never
created and the persistence this whole item exists to add never happens. § 1's
acceptance criteria and § 6's "created with mode `0700` before the first write"
both describe a write that could never occur. All three review lanes found it
independently.

`RegistryMissing` is a **subclass** of `RegistryError` so that every existing
`except RegistryError` handler — `__main__.build_window` is the only one — keeps
its current behaviour without being touched. Only the write gate discriminates,
and INV-6 tests the discrimination.

The last row is the one a `reasons`-only gate misses entirely: a raised
`RegistryError` produces **no reasons at all**, and § 6 already sends that case
to an empty window. Without this clause a caller would write a fresh file over a
hand-edited registry that had only a JSON typo or a stale `schema_version` —
destroying a fully recoverable file through the very gate written to prevent
destruction.

**Records are written in the order given**, and nothing may sort them. Two rules
in LWSM-1131 depend on file order — which of two duplicate identities owns it,
and its tie-break between two records with no `added` — and each write becomes
the next load's file order, so a writer that sorted by name would silently flip
both on every run. INV-3 asserts a sequence rather than a set for this reason.

**Every value that reaches a refusal reason passes `_quoted` first** (INV-8).
The writer's reasons interpolate file-sourced text — a path that could not be
replaced, a name in a row-refusal count — and `_quoted` is the existing clip
that stops a hand-edited newline reaching the status bar or the log.

## 5. Invariants

- **INV-1** — Every field of `ProjectRecord` belongs to exactly one of
  `DETECTED_FIELDS` or `USER_FIELDS`.
  *Test:* `tests/test_registry.py::test_every_record_field_is_classified`,
  derived from `dataclasses.fields(ProjectRecord)` rather than a written list.
  *Breaks when:* a field is added to the dataclass and to neither set — after
  which LWSM-1131's merge neither refreshes nor preserves it.

- **INV-2** — A write that fails **before `os.replace` completes** leaves the
  previous file intact and parseable, and unlinks the temporary file.
  *Test:* `tests/test_registry.py::test_a_failed_write_leaves_the_old_file_intact`
  — failure injected after the temporary file is written and before
  `os.replace`.
  *Breaks when:* the disk fills, or the process dies mid-write.
  **"At any point" would be false**, and the boundary is `os.replace` because
  that is where the swap becomes visible. § 4.3's step 4 — the directory
  `fsync` — runs *after* it, so a failure there leaves the new file correctly in
  place with no temporary file left to unlink and nothing to roll back; it is
  reported, not reversed. Reverting it would mean keeping a copy of the old
  file, which is LWSM-1039.

- **INV-3** — Anything written reloads to an equal record **sequence** — same
  records, `==` on the dataclass, **in the same order**.
  *Test:* `tests/test_registry.py::test_write_then_load_round_trips`, over a
  record with every field populated, including a name needing JSON escaping.
  *Breaks when:* a field is serialised in a form `load_projects` rejects — a
  `Path` written as a repr, a `LauncherKind` written as an enum rather than its
  value — or **loaded back at the wrong type**: `argv` is `tuple[str, ...]` and
  JSON has only arrays, so a loader returning a `list` produces a record that is
  unequal to the one written while every field *looks* right (§ 4.2) — **or when
  the writer reorders**. Order is load-bearing twice over in LWSM-1131 and each
  write becomes the next load's file order, so a set-equality test would pass a
  writer that sorted by name and flipped both on every run.

- **INV-4** — The written file is a regular file with mode `0600`, and a target
  that is a symlink or a non-regular file is refused rather than replaced.
  *Test:* `tests/test_registry.py::test_the_written_file_is_private`,
  `::test_a_non_regular_target_is_refused` (a FIFO at the config path), and
  `::test_a_symlinked_target_is_refused_not_followed` — a symlink pointing at a
  **regular** file, which is the case a FIFO fixture cannot reach.
  *Breaks when:* the file is created before its mode is set, or written through
  a helper that never passes `0o600` — `tempfile.NamedTemporaryFile` and
  `mkstemp` both create at `0600`, but `Path.write_text` creates at
  `0666 & ~umask`. Also when the target check uses `os.stat` / `Path.is_file()`
  instead of `os.lstat` — both follow the link, so a symlink passes as a regular
  file and `os.replace` then destroys it (§ 4.3 records the measured run); the
  FIFO test stays green under that bug, which is why the symlink case is named
  separately.
  **A permissive umask is NOT a breaker**, though it reads like the obvious one:
  umask can only clear permission bits, never add them. Measured on this
  machine — creating with an explicit `0o600` under `umask 0000`, `0077` and
  `0777` gives modes `0600`, `0600` and `0000`. A fixture that varies the umask
  against an explicit-mode create can therefore never fail, which is the
  unfalsifiable-clause shape this project has been bitten by before.

- **INV-5** — A file carrying only the fields `load_projects` reads today loads
  under the new reader, with defaults, and `SCHEMA_VERSION` is still 1.
  *Test:* `tests/test_registry.py::test_a_pre_existing_file_still_loads`.
  *Breaks when:* a new field is made required, or the version is bumped.

- **INV-6** — A load that refused a **row**, or that raised any `RegistryError`
  **other than `RegistryMissing`**, makes the session read-only: no write is
  attempted, and the refusal says why. A load that only dropped a **field**
  still writes, and so does `RegistryMissing`.
  *Test:* `tests/test_registry.py::test_a_file_with_a_rejected_row_is_never_written_back`
  (one good project, one with an empty `name`),
  `::test_an_unparseable_file_is_never_written_over` (the `RegistryError` path),
  and **two** discriminating cases, neither of which the first two can stand in
  for: `::test_a_dropped_field_does_not_block_the_write` — one good project whose
  `port` is `"3000"`, which drops the field, keeps the row, and must **not** make
  the session read-only — and
  `::test_a_missing_file_is_first_run_and_writes` — asserting `RegistryMissing`
  is raised, that a `projects.json` **is** created, and that it round-trips.
  **Its fixture points at a path inside a subdirectory of `tmp_path` that does
  not exist either**, so it exercises § 4.3's step 0. `tmp_path` itself is always
  created by pytest, so a fixture placing the missing file directly in it would
  pass against a writer that never creates its parent — the gap step 0 closes.
  *Breaks when:* any hand-written row is refused by the loader. `load_projects`
  returns rejected rows only as reason *strings*, so serialising `records` back
  would delete them permanently and silently — the write turning a recoverable
  hand-edit into data loss. **The third test is the one that keeps the rule
  honest**: keyed on `reasons` being non-empty rather than on a row count, a
  single mistyped port would disable persistence for the whole session, and the
  first two fixtures pass either way.

- **INV-7** — `registry.MAX_REASON_CHARS`, `registry.MAX_REASONS`,
  `scanner.MAX_REASON_CHARS` and `scanner.MAX_DISPLAY_NAME_CHARS` are each
  asserted at their **literal** shipped values in one place, and the existing
  product bound is kept.
  *Test:* `tests/test_registry.py::test_the_shipped_bounds_are_pinned`. **The
  widening is strictly additive** — the test today asserts
  `registry.MAX_REASON_CHARS == 120`, `registry.MAX_REASONS == 100` and
  `MAX_REASON_CHARS * MAX_REASONS < 20_000`, and all three stay. This item adds
  the **two** `scanner` constants and no more. Naming only those two would have
  had an implementer rewrite the test to that list and **delete the
  `MAX_REASONS` assertion**, which is
  known-issue-005's exact shape on the one constant whose own test docstring
  records that it "was added by LWSM-1115 with **exactly this defect**".
  *Breaks when:* a bound is loosened. **Every scanner assertion about a clipped
  string is expressed *relative* to the constant** — `<= scanner.MAX_REASON_CHARS
  + 50`, `== scanner.MAX_DISPLAY_NAME_CHARS` — so raising the bound raises the
  assertion with it and the suite stays green; measured 2026-08-12, setting
  `scanner.MAX_REASON_CHARS = 400` reddened nothing. This closes
  known-issue-034.

- **INV-8** — Every refusal reason `save_projects` emits is clipped and escaped:
  no file-sourced value reaches one at full length or with control characters
  intact.
  *Test:* `tests/test_registry.py::test_a_writer_refusal_reason_is_clipped_and_escaped`
  — a **runtime** assertion, not a source grep: refuse a write whose target path
  carries a newline and 500 characters, then assert the raised `RegistryError`'s
  message **contains no raw newline** and is bounded the way the loader's
  existing test bounds one — `<= len(str(path)) + 3 * MAX_REASON_CHARS`, not
  `<= MAX_REASON_CHARS`. **The tighter form is unachievable and would fail
  against a correct writer:** `_quoted` clips the *value* to `MAX_REASON_CHARS`
  and appends an ellipsis, so a single quoted value is already 121 characters
  before any template text, and a reason interpolates the value into a
  sentence. The loader test states the same bound with the same reasoning in a
  comment — "the bound is the quoted value plus the fixed template, not the
  constant alone". The no-newline half is the absolute clause and carries the
  actual security property.
  *Breaks when:* a hand-edited path containing a newline reaches the status bar
  or the log through a refused write — the defect LWSM-1078, LWSM-1102 and
  LWSM-1114 each closed at one call site, arriving on a new one.
  **A second source grep would have been untestable.** The existing
  `test_no_file_sourced_value_is_interpolated_without_the_clip`
  (`tests/test_registry.py`) greps the whole of `registry.__file__` for a
  non-comment `!r}` — and `save_projects` lives in that same module, so it is
  *already* covered by that test and a mirrored grep could never fail while the
  old one passed. The runtime form asserts something the grep cannot: that the
  reason a caller actually receives is bounded. LWSM-1131's INV-10 is the merge
  report's surface and keeps the grep form, its report being built elsewhere.

## 6. Failure modes

- **The config directory does not exist.** Created by `save_projects` itself
  (§ 4.3 step 0) with mode `0700` before the
  first write; a failure to create it is a `RegistryError` with the reason, and
  the app keeps running against the in-memory list.
- **There is no file at all — first run.** `RegistryMissing`, an empty window,
  and the session is **writable**: the directory is created `0700`, and the
  first `save_projects` creates `projects.json`. This is the one `RegistryError`
  subclass that does not make the session read-only (§ 4.3), and separating it
  is what stops a clean machine being permanently unable to persist anything.
- **The file is unreadable at start** — a directory, a FIFO, a permission
  denial, bad UTF-8, bad JSON, or the wrong `schema_version`. Unchanged from
  today: `RegistryError`, empty window, reason in the status bar — and now also
  read-only for the session (§ 4.3). LWSM-1039 adds the restore-from-backup
  offer; this item deliberately does not.
- **The disk is full.** The temporary write fails, the temporary file is
  unlinked, the previous file is untouched (INV-2), and the user is told the
  write failed rather than being left believing it succeeded.
- **The serialised registry exceeds `MAX_FILE_BYTES`.** Refused with a reason
  before anything is written, rather than written and then found unreadable on
  the next start.
- **Two app instances write concurrently.** Last writer wins; `os.replace` makes
  each write atomic, so no reader ever sees a half-file, but one instance's
  edits can be lost. Not defended against — § 9.

## 7. Tests

All of the above live in `tests/test_registry.py` beside the existing loader
tests, which they reuse the fixtures of (`write`, `one_good`) — **except the
import-cycle check, which belongs in `tests/test_layering.py`** with the other
AST-derived structural rules. The registry file holds **28** tests today
(*command:* `grep -c "def test_" tests/test_registry.py`). Every new one is
written red first and watched failing before the code that satisfies it —
`testing.md § 1`, and the standing practice of this project's last six
fix-passes.

**Most of these need a real file, because the subject is a file** — the existing
`write(tmp_path, payload)` helper is how the loader tests already do it, and
INV-3, INV-5 and INV-6 all use it. Two need more than a file's *contents*: INV-2
an injected mid-write failure, INV-4 a FIFO, a symlink and a mode check. INV-6's
first-run case needs the *absence* of one, which `tmp_path` gives for free.

**Every one of them carries no marker, and that is what makes `--fast` run
them.** `scripts/local-ci.sh` runs `uv run pytest -q -m "not integration"`
under `--fast`, so a marker can only ever *exclude* a test. The project declares
exactly two, `gui` and `integration` (`pyproject.toml`), and nothing here
spawns a process or binds a socket. **That constraint decided where the
import-cycle check goes**: the obvious form — import each module first in a
fresh interpreter — spawns one, so it would be `integration`-marked and skipped
by exactly the run a developer is most likely to be doing. An AST assertion that
`registry.py` does not import `lwsm.scanner` is in-process, is the invariant the
cycle actually violates, and sits beside the layering rules that are already
enforced by parsing rather than grepping (`CLAUDE.md`). Where a marker is
warranted it goes on the test and never on the file.

**What these tests do not prove**, said plainly: none of them exercises a real
concurrent write (the § 6 case), and INV-2's failure is injected rather than a
real power loss. Both are honest limits of a unit suite, not gaps to be closed
by asserting harder.

## 8. Alternatives considered (and rejected)

- **Bump `schema_version` to 2.** Rejected: the reader's check is exact, so
  every hand-written file in existence would be refused, and the new fields are
  all optional with defaults — there is nothing a version bump would protect. It
  becomes right the moment a field changes *meaning* rather than being added.
- **Split `ProjectRecord` into nested detected/user dataclasses.** Structurally
  stronger than § 4.1's membership sets, and rejected on blast radius: every
  consumer in `controller.py` and `mainwindow.py` reads the flat attributes
  today, and INV-1 buys the same guarantee — a new field must be classified or
  the build fails — for none of the churn.
- **Carry loader-rejected rows through the write instead of refusing to write
  (INV-6).** This is the better end state and it is rejected *here* on scope: it
  means changing `load_projects` to return the raw JSON of every row it refused,
  which widens the reader's contract, its return type and every one of its
  existing tests — for a case the read-only rule already makes safe. The cost of
  the chosen rule is real and worth stating: one bad hand-edited row blocks
  persistence until the user fixes it. That is visible, reversible, and strictly
  better than the alternative it replaces, which was silent deletion.
- **Write the file on every change rather than on demand.** Rejected as
  premature: this item builds no caller at all, and the only one coming is
  LWSM-1131's merge. It becomes the right question when an editing surface
  exists, and then it needs a debounce nobody has specified.
- **Store `kind` as a validated `str` instead of moving `LauncherKind` into
  `registry.py`.** Avoids touching `scanner.py`, and rejected because it
  duplicates the enum's four values in the module least likely to be updated
  when a fifth is added — a silent rejection of a valid `kind` at load, in a
  reader whose whole job is to be forgiving about fields. The move costs one
  import line and keeps the dependency direction `scanner.py`'s existing
  `DECLARED_PORT_RANGE` import already establishes. § 4.1 carries the measured
  ImportError that rules out the naive third option, importing the enum upward.
- **Preserve the original text of a field the loader dropped**, so a mistyped
  `"port": "3000"` survives the next write. Rejected on the same scope grounds
  as the row case above, and on a narrower one: a refused *field's* text is by
  definition not a valid value of that field, so preserving it means carrying
  text that can never be used for anything except being written back. § 4.2
  states the loss instead.
- **Ship the writer and the merge as one item** — which is what the umbrella
  spec was. Rejected by measurement, not by taste: § 3 carries the numbers.

## 9. Out of scope

- **The rescan merge, and everything that reads these fields** — LWSM-1131.
  That includes who stamps `added`, how it is compared, how two paths resolving
  to one directory are reconciled, and every merge outcome. This spec defines
  the fields; it acts on none of them.
- **Keeping a backup of the registry** — LWSM-1039. § 6 deliberately leaves the
  restore offer to it.
- **The first-run confirmation flow** — LWSM-1008.
- **Concurrent-writer safety** (a lock file, or an mtime precondition) —
  untracked, because two instances of a single-user desktop app is not a shape
  anyone has asked for. Recorded in § 6 so the omission is visible.
- **Acting on `hidden`, `launcher_override`, `notes`, `start_at_login` or
  `actions`.** All five round-trip through the file and **nothing reads them**,
  in this item or in LWSM-1131. Stated because the file is hand-editable, so
  every one of these keys is reachable today and an implementer would otherwise
  have to guess. A hand-set `"hidden": true` does nothing yet; that is better
  than one that silently removes a row with no way to bring it back.
- **The `actions` schema, and `design.md`'s load-time validation of a
  `run_command` argv.** § 4.2 persists the array opaquely; the per-action shape,
  the `open_url` / `open_file` / `run_command` rules and the `Supervisor`
  ownership all land with the item that builds the action surface. Untracked —
  no roadmap item claims it yet, and it is named here so the omission is visible
  rather than discovered by whoever builds it.
- **Persisting a detected port's provenance** (`PortFinding.rule` and
  `.source`). § 4.2 stores the bare `int`; provenance is recomputed by the next
  scan. Untracked, and cheap to add later — two optional keys, both defaulting
  to absent, under the same `schema_version`.
- **known-issue-010** (contrast computed only against `window`) and
  **known-issue-013** (the row's accessible role is `Border`) both *named*
  LWSM-1007 as their owner, describing it as "the list view". Neither is
  registry work. Both were **re-routed on 2026-08-12** — -010 to LWSM-1030,
  -013 to LWSM-1032 — and each entry records the reason in place.

## 10. What checks this

| Rule | What catches a breach |
|------|----------------------|
| INV-1 | `test_registry.py::test_every_record_field_is_classified` |
| INV-2 | `test_registry.py::test_a_failed_write_leaves_the_old_file_intact` |
| INV-3 | `test_registry.py::test_write_then_load_round_trips` |
| INV-4 | `test_registry.py::test_the_written_file_is_private`, `::test_a_non_regular_target_is_refused`, `::test_a_symlinked_target_is_refused_not_followed` |
| INV-5 | `test_registry.py::test_a_pre_existing_file_still_loads` |
| INV-6 | `test_registry.py::test_a_file_with_a_rejected_row_is_never_written_back`, `::test_an_unparseable_file_is_never_written_over`, `::test_a_dropped_field_does_not_block_the_write`, `::test_a_missing_file_is_first_run_and_writes` |
| INV-7 | `test_registry.py::test_the_shipped_bounds_are_pinned` (widened additively; the existing `MAX_REASONS` and product assertions stay) |
| INV-8 | `test_registry.py::test_a_writer_refusal_reason_is_clipped_and_escaped` |
| § 4.1 `LauncherKind` moves without closing an import cycle | `tests/test_layering.py::test_registry_does_not_import_scanner` — an AST check, not a subprocess: a fresh-interpreter import test would spawn a process, earn the `integration` marker and be skipped by `--fast`, which is the run most likely to be the only one anybody does |
| § 4.2 `kind` rejected when not a `LauncherKind` | `test_registry.py::test_an_unrecognised_kind_loses_the_field_and_keeps_the_row` |
| § 4.2 the wrong-type rule, over every optional key | `test_registry.py::test_a_wrong_typed_field_is_dropped_and_reported`, parametrised over all **eleven** optional keys — not the table's eight rows, three of which pair two keys, which would leave `port_override`, `launcher_override` and `start_at_login` with no case |
| § 4.2 a non-string `name` or `path` is a ROW refusal | `test_registry.py::test_a_wrong_typed_required_field_refuses_the_row` |
| § 4.2 `added` verbatim on write, `Z` only when stamped | `test_registry.py::test_a_stored_added_offset_is_written_back_verbatim` |
| § 4.2 `added` unparseable is dropped and reported | `test_registry.py::test_an_unparseable_added_is_dropped_and_reported` |
| § 4.2 `actions` round-trips opaquely, and a record carrying one stays hashable | `test_registry.py::test_an_opaque_actions_array_round_trips_by_value`, which also calls `hash()` on the record — the assertion a `tuple[dict, ...]` would fail |
| § 4.2 `argv` tuple round-trip | covered by INV-3's round-trip over a fully-populated record |
| § 4.2 `path` is not resolved, though `Path` normalises it | `test_registry.py::test_the_writer_does_not_resolve_a_stored_path` |
| § 4.3 the `MAX_FILE_BYTES` write bound | `test_registry.py::test_an_oversized_registry_is_refused_before_writing` |
| § 4.3 the gate lives inside `save_projects` | covered by INV-6, whose fixtures call the writer directly |
| § 4.2 a dropped field's original text is lost | **nothing** — an accepted cost, stated in § 4.2 and § 8, not a rule |
| § 4.2 port provenance not persisted | **nothing** — deliberate (§ 9); `rule` and `source` are recomputed by the next scan |
| § 4.3 steps 4 and 6 (directory `fsync`, and its failure reported not reversed) | **nothing** — a durability claim a unit test cannot falsify without power loss; the call site is reviewed, not tested |
| § 6 concurrent writers | **nothing** — out of scope by § 9; last writer wins and no reader sees a half-file |
| § 9 five fields persisted but inert | **nothing** — deliberate; INV-3's round-trip proves they survive, and nothing reads them |

**Twenty-four rows, five of which say `nothing`.** All five are limits or
deliberate omissions rather than defects: the directory `fsync` and its
failure path, which no unit test can falsify without power loss; concurrent
writers, excluded by § 9; the five persisted-but-inert fields and the unpersisted
port provenance, both § 9 deferrals with their cost stated; and the dropped
field's lost text, accepted in § 8. **None carries a roadmap id, because none is
a gap to close.**

*Command, run against this file:*

```
awk '/^\| Rule \| What catches/{f=1;next} f&&/^\|---/{next} \
     f&&/^\| /{n++; if(/^\| INV-/)i++; if(/\*\*nothing\*\*/)z++} \
     f&&!/^\| /{exit} END{print "rows="n" inv="i" nothing="z}' \
  docs/specs/LWSM-1007-registry-persistence.md
```

→ `rows=24 inv=8 nothing=5`, against `grep -c '^- \*\*INV-'` → `8`. So the table
and § 5 enumerate the same eight invariants, and the sixteen non-`INV` rows are
the five `nothing` limits plus eleven § 4 rules that carry a test without
carrying an invariant of their own.

## 11. Cross-doc impact

- **`ROADMAP.md`** — LWSM-1007's bullet narrowed to the writer and the format;
  **LWSM-1131 added** for the merge. Both done 2026-08-12.
- **`CLAUDE.md § Module map`** — `registry.py`'s entry gains `save_projects`,
  `LoadResult`, `RegistryMissing`, the field-classification sets and
  `LauncherKind`; `scanner.py`'s entry loses `LauncherKind` from its symbol
  list. The entry also states `load_projects` returns "(records, rejection
  reasons)", which `LoadResult` replaces.
- **Two code call sites this item must update, listed because neither is
  optional and both are outside `registry.py`:** `src/lwsm/__main__.py`'s
  `build_window` unpacks `load_projects`' two-tuple, and `src/lwsm/scanner.py`
  **defines** `LauncherKind` today — after § 4.1's move it imports it from
  `lwsm.registry`, beside the `DECLARED_PORT_RANGE` import already in that
  module's import block.
- **`docs/specs/LWSM-1006-scanner-detection.md`** — cites `LauncherKind` as a
  `scanner` symbol. Its statements stay true of the enum's *values*; the owning
  module changes, so its module attribution needs a pass. **That spec is
  accepted and its own gate is behind it**, so the correction is filed rather
  than made here.
- **`docs/specs/LWSM-1131-rescan-merge.md`** — its § 4.3 says the merge's return
  shape "mirrors `load_projects` — `(records, reasons)`", which `LoadResult`
  makes false. Corrected in that document as collateral of this loop.
- **`docs/known-issues.md`** — known-issue-034 closed by INV-7; known-issue-025
  **re-pointed to LWSM-1131**, since identity is compared at merge time;
  known-issue-033 stays open and keeps its routing, for the reason § 2 gives;
  known-issue-036 gains the section-numbering finding this split produced (§ 3).
- **`docs/decisions/0005-registry-and-rescan.md`** — unchanged by this part. The
  two clauses ADR-0005 is missing are both merge rules and are LWSM-1131's
  cross-doc impact.
- **`CHANGELOG.md`** — an `[Unreleased] ### Added` entry.
- **`.claude/workflow.md`** — the split, and LWSM-1131 joining P03b's item list.

## 12. Cold-eyes loop log

| Loop | Date | Lanes | CRIT | HIGH | MED | LOW | Outcome |
|------|------|-------|------|------|-----|-----|---------|
| 0-split | 2026-08-12 | **none — no reviewer was dispatched** | — | — | — | — | **Provenance row, not a review.** This document is the format-and-writer half of *LWSM-1007 — Persist the registry, and merge a rescan without discarding user edits*, narrowed in place on 2026-08-12 after that spec reached `review-contract`'s `--max-loops 3` cap without converging. The merge half is [LWSM-1131](LWSM-1131-rescan-merge.md). The umbrella's three loops produced 34 findings, all verified, all fixed, none ever resurfacing — and its own loop-3 row diagnosed the cap as **size and scope** rather than an unsettled contract: 540 → 979 lines with the count flat at 12 / 10 / 12 and each loop clustering in a different region. The user chose the split on 2026-08-12 over accepting at the cap or running a fourth loop. **No review is inherited.** Those loops ran against a 979-line document that no longer exists; this part runs the gate from loop 1 on its own bytes, and so does LWSM-1131. Invariants renumbered from 1 with the mapping in § 3. |
| 1 | 2026-08-12 | 3 (general-purpose, strong model), identical brief, four-question form | Q1 ×4 · Q2 ×4 · Q3 ×5 · Q4 ×1 | **14 verified, 0 dismissed, 14 fixed.** First cold read of this document on its own bytes; no review inherited from the umbrella. **Two findings would have stopped the application, and neither was reachable from the umbrella's three loops.** (1) **`kind: LauncherKind` closes an import cycle.** `scanner.py` already imports `DECLARED_PORT_RANGE` from `lwsm.registry`, so typing `kind` with the scanner's enum makes `registry` import `scanner` — measured here, **both** entry orders raise `ImportError` and nothing in the package imports at all. Fixed by moving `LauncherKind` down into `registry.py`, keeping the direction that already exists; the rejected string-validation alternative is in § 8, and § 10 checks it with an AST assertion in `test_layering.py` rather than a subprocess, which would have earned the `integration` marker and been skipped by `--fast`. (2) **First run was permanently read-only.** `_read_bounded` opens with `os.open` and `load_projects` converts *any* `OSError` to `RegistryError`, so "no file at all" and "`RegistryError` raised" were the same state listed as two rows of one table with opposite answers — a clean machine could never create `projects.json`, falsifying both § 1 acceptance criteria. **All three lanes found this independently**, and it was present verbatim in the umbrella's § 4.5, where three loops did not reach it. Fixed with a `RegistryMissing(RegistryError)` subclass and a four-state table. **Three contracts were named and never given a shape:** `load_projects`' new return (now a `LoadResult` dataclass — `rows_refused` cannot be derived from `reasons`, which is INV-6's whole discriminating case), `save_projects` itself (no signature anywhere, while LWSM-1131 § 9 binds to it), and the wrong-type behaviour of eight of eleven optional keys (now one blanket rule as a fourth table column). **Three type claims were false:** `actions` was `tuple[str, ...]` where `design.md § Custom project actions` makes an action a label plus one of three kinds with a payload — INV-3's round-trip would have passed over a shape the design forbids, so the array is now persisted opaquely with its schema deferred to the item that builds the surface; `path` was promised "written back exactly as the user wrote it" when `load_projects` discards `raw_path` and `Path` normalises on construction (measured: `/srv/a/` → `/srv/a`, `/srv///a` → `/srv/a`); and the stored `port` is a bare `int` where `DetectedProject.port` is a `PortFinding` carrying `rule` and `source`, so provenance is now explicitly not persisted rather than silently dropped. **Two of my own fixes-in-waiting were self-contradictory:** `added` could not be both "never rewritten once set" and "written with a `Z` suffix" while the reader must accept any RFC 3339 spelling (now: `Z` governs only what the app stamps, stored text is verbatim), and § 4.3 step 5's "on any failure" covered step 4, contradicting INV-2 by unlinking a file that no longer exists and reporting failure for a write that succeeded. **INV-7 was one edit from reinstating a known defect** — it enumerated three constants and said "widened from the existing test", which would have had an implementer delete that test's `registry.MAX_REASONS == 100` assertion; `MAX_REASONS` is the one constant whose own docstring records that it shipped with exactly the defect known-issue-005 describes. **INV-8's test could not have failed:** it mirrored a source grep over the whole of `registry.__file__`, and `save_projects` lives in that module, so the new test was already covered by the old one — replaced with a runtime assertion on the emitted reason. **Two open questions resolved clean and are not in the tally** (`scanner.MAX_REASON_CHARS` / `MAX_DISPLAY_NAME_CHARS` exist as named; § 7's `--fast` and marker claims hold). **4c found one of its own:** six `path:line` citations did not resolve and `drafting-rules.md` forbids line numbers outright, so all are now symbol references. **Collateral, swept once after every fix:** LWSM-1131 § 4.3's "mirrors `load_projects` — `(records, reasons)`", its § 4.4 read-only gate (which said any `RegistryError` blocks the write — false for first run, the path that item actually runs on), and its § 13 `datetime` attribution. **Honest cost: the document went 642 → 888 lines.** Five Q3 findings add where nothing stood, and two fixes carry measured evidence, but that is the growth 4a-min warns produces the next loop's findings — loop 2 should be read hardest against the new text in § 4.1, § 4.2 and § 4.3. Loop 2 dispatched. |
| 2 | 2026-08-13 | 3 (general-purpose, strong model), brief byte-identical to loop 1, no prior-loop findings disclosed | Q1 ×1 · Q2 ×3 · Q3 ×4 · Q4 ×1 | **9 verified, 0 dismissed, 9 fixed. Nothing from loop 1 resurfaced, so all fourteen of those fixes held.** **The finding about this loop is that every one of its nine landed in text loop 1 ADDED** — which is exactly what loop 1's own row predicted, and it is the measured shape `4a-min` describes rather than a fresh reading of the draft. **Two would have produced a test that fails against correct code.** INV-8 asked for a refusal message "within `MAX_REASON_CHARS`", which is unachievable: `_quoted` clips the *value* to 120 and appends an ellipsis, so one quoted value is already 121 characters before any template — and the loader's existing test states the right bound with the reasoning in a comment (`<= len(str(path)) + 3 * MAX_REASON_CHARS`). All three lanes found it. And INV-6's first-run fixture would have passed against a writer that never creates its parent directory, because `tmp_path` always exists. **That second one exposed a genuine hole rather than a test defect:** § 6 required the config directory "created `0700` before the first write" while § 1 says nothing in this item calls the writer, so the `mkdir` was assigned to nobody — now § 4.3 step 0, inside `save_projects`. **Three counts and types contradicted their own section.** The § 10 row parametrised the wrong-type rule "over all eight", the table's *row* count, where there are **eleven** optional keys — three rows pair two — which would have left `port_override`, `launcher_override` and `start_at_login` untested by the very case the row exists to force. INV-7 named four constants then called them "the three this item adds"; it adds two. And `added`'s type cell still read "RFC 3339 **UTC**" four lines above prose requiring a `+01:00` value to be preserved, so a loader following the table would drop the tie-break stamp LWSM-1131 depends on. **`actions` was fixed in loop 1 and still under-specified:** "opaque" gave no Python type, and both available readings are wrong — a `list` fails INV-3's `==` round-trip, and a `tuple[dict, ...]` makes the `frozen=True` `ProjectRecord` raise `TypeError` on `hash()`. Now one canonical-JSON string per element, with the normalised key order named as the cost. **Loop 1's `added` parse rule was unfalsifiable in the other direction** — "well-formed" was never defined, and `datetime.fromisoformat` is far broader than RFC 3339. Pinned by measurement, and **the refuting run corrected my own first wording**: I wrote "must carry a date, a time and a `tzinfo`", but `'2026-08-12'` parses to midnight and *has* a time, so the `tzinfo` clause alone does all the work and the longer rule merely read safer. One finding was mine: the `lstat`-then-`replace` race was unstated, and is now accepted explicitly with the reason a retry loop is wrong. **Two open questions resolved clean, not in the tally** (`scanner.MAX_DISPLAY_NAME_CHARS` exists; known-issue-034 names exactly the two constants INV-7 pins). **Phase 5's collateral rule applies and gates the next dispatch:** with nine of nine landing on last loop's additions, 4b was re-run over the whole seed-pair list instead — it found two more staleness items of my own (the `actions` § 10 row still claiming a byte-unchanged round-trip, and § 6 still implying a caller creates the directory), both fixed here. 888 → 946 lines. |

## 13. Resource cost

- **Memory.** The registry is already bounded by `MAX_FILE_BYTES` (1 MiB) on
  read, and § 4.3 applies the same bound on write. The writer holds the
  serialised document once — O(n) in the number of projects, against a file
  whose size is capped.
- **Named cap on refusal reasons.** The writer's reasons reuse the loader's
  existing `MAX_REASONS` (100) and `MAX_REASON_CHARS` (120) discipline, pinned
  by INV-7 and clipped by INV-8. LWSM-1131's merge report is a separate surface
  and carries its own bound.
- **Disk.** One file, plus a transient temporary file in the same directory that
  is unlinked on any failure path.
- **New external dependencies: none.** `registry.py` imports `errno`, `json`,
  `os`, `stat`, `dataclasses`, `pathlib` and `typing` today; this item adds
  **`tempfile`** for the writer and **`datetime`** for § 4.2's `added` parse.
  `datetime` is needed **here**, not with LWSM-1131: deciding whether a present
  `added` is well-formed is a parse, and § 4.2's fourth-column rule makes that
  decision at load. LWSM-1131 *compares* the parsed instants and adds no import
  of its own. `collections.abc` arrives with `save_projects`' `Sequence`. All
  standard library, so `pyproject.toml` does not change.
  *Command:* `grep -nE "^(import|from) " src/lwsm/registry.py`.
