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
field no write may rewrite (§ 4.2).

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

| Key | Type | Default when absent |
|---|---|---|
| `port`, `port_override` | `int \| None` | `null` |
| `unit`, `launcher_override` | `str \| None` | `null` |
| `kind` | `LauncherKind \| None` | `null` — an unknown launcher kind |
| `hidden`, `start_at_login` | `bool` | `false` |
| `notes` | `str` | `""` |
| `argv`, `actions` | `tuple[str, ...]` | `()` |
| `added` | `str \| None`, RFC 3339 UTC | `null` |

**`kind` accepts only a value of `LauncherKind` — `"systemd"`, `"shell"`,
`"node"`, `"python"`.** An unrecognised string loses the field and is reported,
the rule `_port_or_reason` already applies to a bad port: the project still
exists and the user still needs to see it.

**`argv` and `actions` load back as tuples, not lists.** JSON has only arrays,
so a loader returning a `list` produces a record unequal to the one written
while every value looks right — INV-3's failure mode exactly. `argv`'s tuple
form also matches `scanner.DetectedProject.argv`, so the merge compares like
with like.

**`added` is written as RFC 3339 with a `Z` suffix and second precision, and
never rewritten once set.** This spec owns the field's type, its default and its
spelling; **LWSM-1131 owns who stamps it and how it is compared** (its merge
seeds it on a new record, and its INV-9 requires the comparison be made on a
parsed instant rather than on text, because a hand-edited `+01:00` sorts
lexically against a `Z` in the wrong direction). Stated here because the file is
hand-editable, so a value this spec's reader must accept can arrive in any RFC
3339 spelling: **a present value that does not parse is treated as absent and
reported**, rather than compared.

**`path` is written back exactly as the user wrote it.** No writer normalises,
resolves or rewrites the stored path string. `load_projects` refuses `..` and a
doubled leading slash at read time, and that is the whole of the normalisation
this format performs — resolving a path lexically is wrong when a component is a
symlink, and rewriting the file's own text makes it unrecognisable to the person
who hand-edits it. LWSM-1131's INV-8 tests the merge side of the same rule.

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

Atomic replace, in the target's own directory so the rename cannot cross a
filesystem:

1. Create a temporary file in `path.parent`, mode `0600`.
2. Write the serialised JSON; `flush()`; `os.fsync()` the file descriptor.
3. `os.replace(tmp, path)` — atomic for any concurrent reader.
4. `os.fsync()` the **directory** descriptor, so the rename itself is durable
   rather than only the bytes.
5. On any failure, unlink the temporary file and raise `RegistryError`.

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
session, on a file with nothing at risk. **So `load_projects` gains a
row-refusal count alongside its reasons**, and that count is what the gate
reads.

**Three states, and only the first may write:**

| At load | May write? |
|---|---|
| no file at all, or every row accepted | **yes** — a fresh `projects.json` is created on first run |
| one or more rows refused | no — read-only, reported |
| `RegistryError` raised (unparseable, wrong `schema_version`, unreadable) | no — read-only, reported |

The third row is the one a `reasons`-only gate misses entirely: a raised
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

- **INV-6** — A load that refused a **row**, or that raised `RegistryError`,
  makes the session read-only: no write is attempted, and the refusal says why.
  A load that only dropped a **field** still writes.
  *Test:* `tests/test_registry.py::test_a_file_with_a_rejected_row_is_never_written_back`
  (one good project, one with an empty `name`),
  `::test_an_unparseable_file_is_never_written_over` (the `RegistryError` path),
  and the discriminating case
  `::test_a_dropped_field_does_not_block_the_write` — one good project whose
  `port` is `"3000"`, which drops the field, keeps the row, and must **not** make
  the session read-only.
  *Breaks when:* any hand-written row is refused by the loader. `load_projects`
  returns rejected rows only as reason *strings*, so serialising `records` back
  would delete them permanently and silently — the write turning a recoverable
  hand-edit into data loss. **The third test is the one that keeps the rule
  honest**: keyed on `reasons` being non-empty rather than on a row count, a
  single mistyped port would disable persistence for the whole session, and the
  first two fixtures pass either way.

- **INV-7** — `registry.MAX_REASON_CHARS`, `scanner.MAX_REASON_CHARS` and
  `scanner.MAX_DISPLAY_NAME_CHARS` are each asserted at their **literal**
  shipped values in one place.
  *Test:* `tests/test_registry.py::test_the_shipped_bounds_are_pinned`, widened
  from the existing test of that name, which today pins `registry`'s copy only.
  *Breaks when:* a bound is loosened. **Every scanner assertion about a clipped
  string is expressed *relative* to the constant** — `<= scanner.MAX_REASON_CHARS
  + 50`, `== scanner.MAX_DISPLAY_NAME_CHARS` — so raising the bound raises the
  assertion with it and the suite stays green; measured 2026-08-12, setting
  `scanner.MAX_REASON_CHARS = 400` reddened nothing. This closes
  known-issue-034.

- **INV-8** — No value read from the file reaches a **writer refusal reason**
  without passing `_quoted`.
  *Test:* `tests/test_registry.py::test_no_writer_reason_is_interpolated_without_the_clip`,
  mirroring the existing `test_no_file_sourced_value_is_interpolated_without_the_clip`
  at `tests/test_registry.py:463`.
  *Breaks when:* a hand-edited path containing a newline reaches the status bar
  or the log through a refused write — the defect LWSM-1078, LWSM-1102 and
  LWSM-1114 each closed at one call site, arriving on a new one. LWSM-1131's
  INV-10 is the same rule for the merge report, which is a different surface
  with a different set of interpolated values.

## 6. Failure modes

- **The config directory does not exist.** Created with mode `0700` before the
  first write; a failure to create it is a `RegistryError` with the reason, and
  the app keeps running against the in-memory list.
- **The file is unreadable at start.** Unchanged from today: `RegistryError`,
  empty window, reason in the status bar — and now also read-only for the
  session (§ 4.3). LWSM-1039 adds the restore-from-backup offer; this item
  deliberately does not.
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
tests, which they reuse the fixtures of (`write`, `one_good`). The file holds
**28** tests today (*command:* `grep -c "def test_" tests/test_registry.py`).
Every new one is written red first and watched failing before the code that
satisfies it — `testing.md § 1`, and the standing practice of this project's
last six fix-passes.

**Most of these need a real file, because the subject is a file** — the existing
`write(tmp_path, payload)` helper is how the loader tests already do it, and
INV-3, INV-5 and INV-6 all use it. Two need more than a file's *contents*: INV-2
an injected mid-write failure, INV-4 a FIFO, a symlink and a mode check. Every
one of them uses `tmp_path` and **carries no marker**, which is what makes
`--fast` run them: `scripts/local-ci.sh` runs `uv run pytest -q -m "not
integration"` under `--fast`, so a marker can only ever *exclude* a test. The
project declares exactly two markers, `gui` and `integration`
(`pyproject.toml`), and neither test spawns a process or binds a socket, so
`integration` would be the wrong label as well as the excluding one. Where a
marker is warranted it goes on the test and never on the file (`CLAUDE.md`).

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
| INV-6 | `test_registry.py::test_a_file_with_a_rejected_row_is_never_written_back`, `::test_an_unparseable_file_is_never_written_over`, `::test_a_dropped_field_does_not_block_the_write` |
| INV-7 | `test_registry.py::test_the_shipped_bounds_are_pinned` (widened to the two `scanner` constants) |
| INV-8 | `test_registry.py::test_no_writer_reason_is_interpolated_without_the_clip` |
| § 4.2 `kind` rejected when not a `LauncherKind` | `test_registry.py::test_an_unrecognised_kind_loses_the_field_and_keeps_the_row` |
| § 4.2 `added` unparseable is treated as absent | `test_registry.py::test_an_unparseable_added_is_treated_as_absent_and_reported` |
| § 4.2 tuple round-trip for `argv` / `actions` | covered by INV-3's round-trip over a fully-populated record |
| § 4.2 `path` written back verbatim | `test_registry.py::test_the_writer_does_not_normalise_a_stored_path` |
| § 4.3 the `MAX_FILE_BYTES` write bound | `test_registry.py::test_an_oversized_registry_is_refused_before_writing` |
| § 4.3 step 4 (directory `fsync`) | **nothing** — a durability claim a unit test cannot falsify without power loss; the call site is reviewed, not tested |
| § 6 concurrent writers | **nothing** — out of scope by § 9; last writer wins and no reader sees a half-file |
| § 9 five fields persisted but inert | **nothing** — deliberate; INV-3's round-trip proves they survive, and nothing reads them |

**Sixteen rows, three of which say `nothing`.** All three are limits or
deliberate omissions rather than defects: the directory `fsync`, which no unit
test can falsify without power loss; concurrent writers, excluded by § 9; and
the five persisted-but-inert fields, a § 9 deferral with its cost stated. **None
carries a roadmap id, because none is a gap to close.**

*Command, run against this file:*

```
awk '/^\| Rule \| What catches/{f=1;next} f&&/^\|---/{next} \
     f&&/^\| /{n++; if(/^\| INV-/)i++; if(/\*\*nothing\*\*/)z++} \
     f&&!/^\| /{exit} END{print "rows="n" inv="i" nothing="z}' \
  docs/specs/LWSM-1007-registry-persistence.md
```

→ `rows=16 inv=8 nothing=3`, against `grep -c '^- \*\*INV-'` → `8`. So the table
and § 5 enumerate the same eight invariants, and the eight non-`INV` rows are
the three `nothing` limits plus five § 4 rules that carry a test without
carrying an invariant of their own.

## 11. Cross-doc impact

- **`ROADMAP.md`** — LWSM-1007's bullet narrowed to the writer and the format;
  **LWSM-1131 added** for the merge. Both done 2026-08-12.
- **`CLAUDE.md § Module map`** — `registry.py`'s entry gains the writer, the
  field classification sets and the row-refusal count.
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
  `os`, `stat`, `dataclasses`, `pathlib` and `typing` today; the writer adds
  **`tempfile`**. `datetime` arrives with LWSM-1131, which stamps `added`. Both
  are standard library, so `pyproject.toml` does not change.
  *Command:* `grep -nE "^(import|from) " src/lwsm/registry.py`.
