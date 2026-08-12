# LWSM-1007 — Persist the registry, and merge a rescan without discarding user edits

**Status:** spec draft (2026-08-12).
**Kind:** implement.
**Source:** ROADMAP LWSM-1007 (in-session-2026-08-03). Policy settled by
[ADR-0005](../decisions/0005-registry-and-rescan.md); this is its mechanism.
**Blocked by:** LWSM-1006 (shipped 2026-08-12).
**Blocker for:** LWSM-1039 (keep one backup of the registry), LWSM-1008
(first-run confirmation flow).
**Pairs with:** nothing.

**Layman:** Remember the project list between runs, and let a rescan pick up
new projects without undoing anything you have changed by hand — and when the
scan cannot tell something it knew before, say so instead of forgetting it.

## 1. Goal

`projects.json` becomes a file the app **writes** as well as reads. A rescan
merges detected facts into the stored list under ADR-0005's rule — user intent
wins, nothing is auto-deleted, and every disagreement is reported — and the
result survives a restart.

The acceptance criterion, stated against what this item actually builds: a
`projects.json` carrying a hand-edited `name` and a hand-edited `port_override`
survives a **Rescan** with both edits in force, plus a visible account of what
the scan changed.

**Editing those fields from inside the app is not part of this item** and no
section below specifies a surface for it. The registry has to be writable
before an editor can have anything to write to, so persistence lands first;
`renaming, hiding and overriding from the UI` is P07's LWSM-1014 for the port
override, and there is no roadmap item for renaming yet. Saying "a user can
rename a project" here would have promised an implementer a dialog this spec
never describes.

## 2. Problem

`src/lwsm/registry.py` is a reader with no writer. `load_projects()` returns
`(records, reasons)` and nothing anywhere in `src/` produces the file it
parses, so today the file is hand-authored and every edit the app might make
is lost the moment the process exits. Four consequences, each grounded in a
symbol read for this spec rather than recalled.

1. **The record cannot hold what ADR-0005 says it holds.**
   `registry.ProjectRecord` is a frozen dataclass of four fields — `path`,
   `name`, `port`, `port_override`.
   *Command:* `awk '/^class ProjectRecord:/,/^    @property/' src/lwsm/registry.py | grep -cE '^    [a-z_]+: '` → `4`.
   ADR-0005 § Decision names seven user-owned fields (display name, hidden
   flag, port override, launcher override, notes, start-at-login flag, and the
   `actions` list) and four detected ones (launcher command, declared port,
   runtime kind, systemd unit name). Exactly three of those eleven have a home
   today — `name` is the display name, `port` the declared port,
   `port_override` the port override — so **eight have nowhere to live**.
   (`path` is the fourth field and is neither: it is the identity ADR-0005
   keys on, which is why § 4.1 classifies it separately.)

2. **Unknown and changed are the same value, so a rescan can silently erase a
   known port.** `scanner.DetectedProject.port` is `PortFinding | None`, and
   its own comment fixes the meaning: `None` means "unknown", never a guess.
   ADR-0005 says a *changed* detected field means "detected fields differ →
   detected half updated". A scan that cannot read a launcher this run —
   a permission change, a budget expiry — yields `port=None`, which differs
   from a stored `3000`, so the literal rule updates the detected half to
   `None` and a known port is gone. **ADR-0005 has no clause distinguishing an
   observation of absence from the absence of an observation**, and neither
   does anything else in the tree. This is the single most consequential gap
   this spec closes.

3. **The two sides disagree about what a project's identity is.**
   `scanner.DetectedProject.path` is documented as `RESOLVED, absolute; the
   identity (ADR-0005)`. `registry.load_projects()` builds `Path(raw_path)`
   and never resolves it — it refuses `..` and a doubled leading slash, and
   dedups through a `seen: set[Path]` of unresolved paths. So a stored
   `/home/me/projects/foo` that is a symlink to `/srv/foo` compares unequal to
   the `/srv/foo` a scan reports, and the merge sees one project as
   simultaneously *new* and *missing*. `docs/known-issues.md`
   known-issue-025 demonstrates the scanner half of this — `scan([symlinked_root,
   real_root])` returns **2 projects for 1 directory** — and routes it here on
   the grounds that identity only becomes durable once it is written to disk.

4. **A partial scan is indistinguishable from a shrunken one.**
   `scanner.ScanResult` carries `timed_out: bool` with the comment `the budget
   expired; projects is partial`. Nothing consumes it. A merge that ignores it
   marks every unreached project *missing* on a slow run.

**Three** entries in `docs/known-issues.md` name LWSM-1007 as their owner, and
**this item closes two of them**: known-issue-025 (identity — § 4.4, INV-6) and
known-issue-034 (the unpinned scanner constants — INV-14).

**known-issue-033 stays open.** It was routed here as "the next item to add
source files and so the first that could add a subpackage", and its one item
with reach is that `test_layering.py` globs `SRC.glob("*.py")` non-recursively,
so a core module under `src/lwsm/<subpackage>/` would be invisible to the
derivation test. **This item adds no subpackage** — every change lands in the
existing `registry.py` — so the premise that routed it here does not fire, and
fixing a latent glob while nothing can trigger it is work without a test that
would fail first. It stays routed and its owner is re-decided when something
actually adds a subpackage.

*Command:* `awk '/^## known-issue-/{h=$0} /^- \*\*Will be addressed in:\*\* LWSM-1007/{print h}' docs/known-issues.md`
→ those three headings.

It was **five** when this spec was drafted. Two of the five — known-issue-010
(contrast on `alt_base`) and -013 (the row's AT-SPI role) — named LWSM-1007 on
the reading that it was "the list view", which it is not; both were re-routed
to P04 on 2026-08-12 as part of writing this spec. § 9 records why.

## 3. Scope decisions (agreed with the user)

- **Phase.** This item opens `P03b`, the continuation phase carrying the four
  items P03 planned and did not deliver (user, 2026-08-12). Commits read
  `P03b: …`.
- **A spec is written for this item**, against `docs/standards/spec-format.md
  § 1`'s bias toward building. All five triggers fire — an on-disk contract
  LWSM-1039 binds to, three subsystems, hard to reverse once records are
  hand-tuned, a real design choice ADR-0005 left open (§ 2 item 2), and the
  merge outcomes crossed with override-presence.
- **`schema_version` stays `1`.** Every new field is optional with a
  documented default, so the hand-written files that exist today keep loading.
  § 8 records the rejected alternative.
- **Deliberately shorter than its predecessor.** LWSM-1006's spec is 1804
  lines and took seven review loops; `spec-format.md § 5.4` and the P03 close
  both read that as a document past the review's design point. This one
  targets the design seams and pushes detail into the tests.

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

The merge replaces **`DETECTED_FIELDS - {"path"}`** and keeps the user half,
rather than copying field by field, and INV-1 makes a field belonging to
neither set a failing build.

**`path` is classified detected but is never written**, and the subtraction is
the whole of that rule. It is in the detected half because a scan is what
observes it, but `DetectedProject.path` is *resolved* while the stored path is
whatever the user wrote (§ 4.4) — so a merge implemented as a plain
set-driven replacement over `DETECTED_FIELDS` would rewrite every stored path
to its resolved form on the first rescan, which is exactly what § 4.4 promises
against. INV-15 tests it, because prose saying "nothing may rewrite it" is not
a contract. This is the same reasoning `scanner.DetectedProject`'s docstring
already gives for having no user-owned field at all: a change that would let
scanned content reach a user-owned field has to be visible.

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

`argv` is a JSON array of strings and loads back as `tuple[str, ...]`, matching
`DetectedProject.argv`; INV-8's "equal record set" is defined over that
conversion, so a loader returning a `list` fails it.

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
| `added` | `str \| None`, RFC 3339 UTC | `null` (see below) |

**`kind` accepts only a value of `LauncherKind` — `"systemd"`, `"shell"`,
`"node"`, `"python"`.** An unrecognised string loses the field and is reported,
the rule `_port_or_reason` already applies to a bad port: the project still
exists and the user still needs to see it.

**`argv` and `actions` load back as tuples, not lists.** JSON has only arrays,
so a loader returning a `list` produces a record unequal to the one written
while every value looks right — INV-8's failure mode exactly.

**`added` is stamped by the merge when it creates a record** (§ 4.6) and is
never rewritten afterwards. **An absent value sorts *after* every present one**
in INV-11's tie-break, with file order breaking a tie between two absent ones —
a rule that exists because every file in existence today lacks the key, so
"earliest `added` wins" would otherwise have no meaning on exactly the files
INV-12 requires to load. **A present value that does not parse as RFC 3339 is
treated as absent and reported**, rather than compared: the file is
hand-editable, so `"yesterday"` is a shape that occurs, and comparing it
lexically against a real timestamp silently produces a wrong winner.

**No merge outcome is persisted.** The flags § 4.6 produces — *new*, *missing*,
*not re-observed*, *override differs*, *duplicate identity* — are report entries
about one merge, not record state, and they are recomputed on the next one.
Nothing in the file records them, so a restart shows no flags until the next
rescan.

**Compatibility with the hand-written files that exist.** A v1 file carrying
only the four fields `load_projects` reads today loads unchanged, with every
new field taking its default. This is why `schema_version` does not move: the
reader's version check is exact (`version != SCHEMA_VERSION` raises), so
bumping it would refuse every existing file to buy nothing. INV-12 locks it.

### 4.3 Unknown is not changed

The rule this spec exists to add:

> A detected field whose rescan value is **unknown** does not overwrite a
> stored known value. It is the absence of an observation, not an observation
> of absence.

**`port` is the only detected field that has an unknown value at all**, and
saying so is half the rule. The others carry no sentinel, so a completed scan's
value for them is always an observation and always wins:

| Field | Is there an "unknown"? | On a completed scan |
|---|---|---|
| `port` | **yes** — `DetectedProject.port is None` means *could not tell* | the rule below |
| `kind` | no — a detected project always has a launcher kind | overwrite |
| `argv` | no — `()` is a real value, and is what every `SYSTEMD` project has | overwrite |
| `unit` | no — `None` is a real value, and is what every non-systemd project has | overwrite |

The distinction matters most for `unit`. Treating its `None` as *unknown* would
keep a stale unit name forever on a project that stopped being a systemd
service — the mirror of the defect this rule exists to prevent, produced by
applying the rule too widely rather than too narrowly.

Concretely, for `port`:

| stored `port` | scan reports | result | reported as |
|---|---|---|---|
| `None` | `None` | `None` | nothing |
| `None` | `3000` | `3000` | changed |
| `3000` | `3000` | `3000` | nothing |
| `3000` | `4000` | `4000` | changed |
| `3000` | `None` | **`3000` kept** | *port no longer detected* |

The last row is the whole point. The stored value survives, and the row is
flagged so the user can see that detection has stopped agreeing with it — which
is ADR-0005's "no silent mutation" applied to a case ADR-0005 did not name.

**The known limitation, stated rather than hidden.** `DetectedProject.port is
None` conflates *"I read the launcher and it declares no port"* with *"I could
not read the launcher"*. Under the rule above, a project whose port was
genuinely removed keeps a stale value until the user clears it. That is the
safe direction of the two — a stale port is visible and correctable, an erased
one is neither — but it is a real cost, and § 8 records the alternative that
removes it.

### 4.4 Identity is the resolved path, compared at merge time

The merge keys both sides on `Path.resolve()`. It does **not** rewrite what is
stored: the user's file keeps the path they wrote, so the file stays
recognisable to the person who hand-edits it.

Two records whose stored paths resolve to one directory are a malformed
registry, exactly as two identical paths already are (`load_projects` refuses
the second with *already registered*). The existing `seen` check cannot see
this case, because it compares unresolved paths — which is precisely
known-issue-025.

**Neither record is deleted.** The one appearing **first in file order** owns
the identity: it alone is merged into and polled. The second is kept, written
back unchanged, and flagged *duplicate identity of `<first project>`*. File
order decides rather than `added`, because `added` is optional (§ 4.2) while
position always exists, and because it is the rule `load_projects` already
applies to exact duplicates — the second occurrence is the one refused.

Keeping the loser is not a nicety: it holds a user-owned half (notes, an
override, an `added`) that no rescan could reconstruct, and ADR-0005 makes
removal a user action so that an unmounted drive cannot destroy the list. INV-5
therefore holds without a carve-out, and INV-6 is about what *merges*, not
about what survives.

**Resolution can fail**, and this project has been bitten four times by an
exception escaping a per-item loop and taking the batch with it (`CLAUDE.md`,
the `pathlib`-on-3.13 trap). So resolution is per record, inside a handler, and
a path that cannot be resolved falls back to its lexical absolute form and is
reported — never dropped, and never allowed to abort the merge.

### 4.5 Writing the file

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
silently converted to a plain file — which is precisely what the refusal
exists to prevent, and what a following stat would have permitted.

This stays deliberately narrower than `applog._require_private_regular_file`,
for the reason `_read_bounded` already records: a config file may reasonably be
hard-linked or installed for the user, so ownership and link count are not
demanded. A **symlink** is refused rather than followed because replacing one
destroys it; a **hard link** is not, because replacing the path leaves the
other name intact.

The serialised output is bounded by the same `MAX_FILE_BYTES` the reader
enforces; a registry that would exceed it is refused with a reason rather than
written and then found unreadable on next start.

**Nothing is written while the load that produced the records had rejections.**
`load_projects` returns `(records, reasons)` and the rejected rows exist only as
reason *strings* — they are not in `records`, and there is no path from a reason
back to the JSON object it came from. So serialising `records` over the file
**permanently deletes every row the loader refused**: a project whose `name` was
blank, whose `path` was relative or contained `..`, or that duplicated an
earlier path. Those are hand-written rows with a hand-written intent, and losing
them silently is the one data loss this app is capable of — the thing LWSM-1039
exists to insure against, arriving through the writer rather than through
corruption.

So: **a non-empty `reasons` list from the load makes the whole session
read-only.** The merge still runs and still reports, the UI still shows what a
rescan would change, and the write is refused with a reason naming the count.
The user fixes the file, or deletes the bad rows deliberately, and the next
start writes normally. § 8 records the alternative that was rejected.

### 4.6 Merge outcomes

The merge is one core function, and its signature is what makes the outcomes
below evaluable:

```python
def merge(
    stored: list[ProjectRecord],
    scan: ScanResult,
    roots: tuple[Path, ...],  # the roots PASSED TO scan(), not inferred
    now: Callable[
        [], str
    ],  # stamps `added` on a new record; injected per testing.md § T1
) -> tuple[list[ProjectRecord], list[str]]:
    """Return (merged records, report entries)."""
```

**`roots` is a parameter because `ScanResult` does not carry it** — its three
fields are `projects`, `skipped` and `timed_out`. Without it the *missing*
outcome below cannot be evaluated at all, and an implementer would fall back to
inferring roots from the projects returned, under which a root that legitimately
contains zero projects silently stops marking its records missing. The **roots
requested** are used rather than "the roots actually walked", because a partial
scan does not report which it reached.

The return shape mirrors `load_projects` — `(records, reasons)` — so both
producers of a record list report their problems the same way.

Seven outcomes: ADR-0005's four (*new*, *unchanged*, *changed*, *missing*), its
*override differs* flag tabulated as a row of its own, and **two this spec
adds** — *not re-observed* (§ 4.3) and *duplicate identity* (§ 4.4). Each
produces a report entry; none mutates silently.

| Outcome | Condition | Effect |
|---|---|---|
| **new** | scanned, not stored | added, flagged *new*; seeded per below |
| **unchanged** | detected halves equal | nothing |
| **changed** | detected halves differ **and the scan value is known** | detected half updated, change listed |
| **missing** | stored, in scope for this scan (below), absent from a complete one | kept, flagged *missing*, never deleted |
| **not re-observed** | stored known, scan unknown (§ 4.3) | stored value kept, flagged |
| **override differs** | a user override exists for a field that moved | override stays in force, row flagged |
| **duplicate identity** | resolves to the same directory as an earlier record (§ 4.4) | kept and written back, excluded from merge and polling, flagged |

**A *new* record is seeded, and that is the one place a merge writes a
user-owned field.** `name` takes `DetectedProject.name`, `added` takes `now()`,
and every other user field takes its § 4.2 default. INV-2 is scoped to records
already in the registry for exactly this reason: read as covering creation too,
it would forbid the merge from giving a new project a name, and an implementer
obeying it literally would add unnamed rows with no `added` — which would in
turn leave INV-11's tie-break with nothing to compare on any record the app
itself created.

**"the scan value is known", not "both known".** A stored `None` with a scan
reporting `3000` is a *changed* row — the port has just been discovered, and
the user is told. Requiring both sides to be known would have left that case
matching no row at all, so a first successful detection would update the record
and report nothing.

**"In scope for this scan" is what makes *missing* mean anything.** A stored
record is a candidate for *missing* only when its resolved path lies under one
of the roots the scan actually walked. ADR-0005 says "absent from disk", which
is not what a scan observes — a scan observes absence *from its own roots*. A
project the user added by hand outside every scan root is present on disk and
absent from every scan, so the literal reading would flag it missing on the
first rescan and every one after.

**A non-empty `ScanResult.skipped` suppresses the missing check for that scan.**
`skipped` is a tuple of reason strings that cannot be keyed back to a project
(it is `tuple[str, ...]`), so there is no way to tell which project a skip
concerned. The merge reports that it could not check for missing projects,
exactly as it does when the scan timed out.

**A timed-out scan marks nothing missing.** When `ScanResult.timed_out` is
true, `projects` is partial by its own definition, so absence carries no
information. The merge reports that it could not check for missing projects.
This rule leans directly on LWSM-1125's guarantee that `_BudgetExpired` does
not subclass `OSError` — without it a timed-out scan reports `timed_out=False`
and this rule would never fire on the runs that need it.

**Duplicate effective ports** are flagged at merge time per ADR-0005, naming
both projects, with the earliest `added` winning and every later claimant
marked *port claimed by `<other project>`*.

### 4.7 The Rescan seam

`MainWindow` gains a **Rescan** button. The report is presented **only** as a
one-line summary through `MainWindow.set_status_message`, which already exists.

**Per-row flags are deliberately not rendered in this item.** `RowView` carries
four fields — `path`, `name`, `effective_port`, `status` — and
`ProjectController.rows()` rebuilds every one of them from the records on each
1000 ms poll. A merge flag is not record state (§ 4.2 persists no outcome), so
it has nowhere to live across a rebuild and would vanish within a second of
being set. Rendering it properly means either persisting outcomes or giving the
controller a second source of row state, and both are larger decisions than
this item needs. The summary is durable enough to satisfy ADR-0005's
requirement that a rescan "produce a visible answer rather than a silent
mutation"; per-row presentation belongs with the first-run flow (LWSM-1008),
which is already designing a surface for showing detected results.

**The scan and the merge run on a `QThreadPool` worker, not on the GUI thread.**
`scan()` is budgeted precisely because it is slow — it walks roots, opens other
people's files and may shell out to `systemctl` — so running it inline would
freeze the window for the length of the scan. This is the arrangement
`ProjectController` already uses for its 1000 ms poll, and `design.md § State
management` requires it. The worker returns the merged records and the report
through a signal; **the file write and every UI update happen on the GUI
thread**, in the slot. Rescan is disabled while one is in flight, so two
overlapping merges cannot both write.

**Exactly one trigger writes the file: a merge that changed something.** If
every outcome is *unchanged*, no write happens — a no-op rewrite would churn
the file's mtime and widen the only window in which § 6's concurrent-writer
loss can occur, for no gain. There is **no write on exit**: nothing this item
builds mutates the registry outside a merge, so an exit hook would have nothing
to flush. (§ 8 rejects a write-per-change alternative; that rejection is about
a *future* editing surface, not about an exit path this item has.)

Deliberately **not** a dialog: presenting a detected list for confirmation is
LWSM-1008's job, and building a lesser version here would be the thing it then
has to replace.

## 5. Invariants

- **INV-1** — Every field of `ProjectRecord` belongs to exactly one of
  `DETECTED_FIELDS` or `USER_FIELDS`.
  *Test:* `tests/test_registry.py::test_every_record_field_is_classified`,
  derived from `dataclasses.fields(ProjectRecord)` rather than a written list.
  *Breaks when:* a field is added to the dataclass and to neither set — after
  which the merge neither refreshes nor preserves it.

- **INV-2** — A merge never writes a user-owned field of a record **already in
  the registry**. Seeding a *new* record is the sole exception and is specified
  in § 4.6.
  *Test:* `tests/test_registry.py::test_a_rescan_never_writes_a_user_field` —
  a stored record with every user field set, merged against a scan whose
  `name` differs, asserting the user half is byte-identical afterwards.
  *Breaks when:* the merge copies `DetectedProject.name` over a user-renamed
  record. `name` is the discriminating fixture precisely because both sides
  carry that field; a fixture using `notes`, which the scanner has no
  equivalent of, would pass against a merge that copied everything.

- **INV-3** — A detected field whose rescan value is unknown never overwrites
  a stored known value.
  *Test:* `tests/test_registry.py::test_unknown_does_not_erase_a_known_port` —
  stored `port=3000`, scan yields `port=None`, assert `3000` survives and the
  row is flagged.
  *Breaks when:* the scan cannot read a launcher it read last time.

- **INV-4** — A timed-out scan marks nothing missing.
  *Test:* `tests/test_registry.py::test_a_timed_out_scan_marks_nothing_missing`
  — `ScanResult(timed_out=True)` omitting a stored project, asserting it is
  not flagged missing and that the report says the check was skipped.
  *Breaks when:* the scan budget expires with projects still unreached.

- **INV-5** — A stored record is never deleted by a merge.
  *Test:* `tests/test_registry.py::test_a_missing_project_is_kept_and_flagged`.
  *Breaks when:* a project's drive is unmounted and a complete scan reports it
  absent.

- **INV-6** — Two stored records whose paths resolve to one directory never
  both **merge**: the first in file order owns the identity, the second is
  flagged *duplicate identity* and excluded from the merge and from polling.
  Both are still written back (INV-5).
  *Test:* `tests/test_registry.py::test_two_paths_resolving_to_one_directory_are_one_project`,
  using known-issue-025's fixture — a symlinked root beside the real one —
  asserting one merged project, two records in the written file, and the
  second flagged.
  *Breaks when:* a user adds a project by a symlinked path having already
  added it by its real one. The existing duplicate check cannot catch this:
  it compares unresolved paths, so both records are distinct to it.
  **It constrains what merges, not what survives.** Read as a rule about
  survival it would contradict INV-5, and an implementer would delete the
  loser along with the user-owned half no rescan can reconstruct.

- **INV-7** — A write that fails at any point leaves the previous file intact
  and parseable.
  *Test:* `tests/test_registry.py::test_a_failed_write_leaves_the_old_file_intact`
  — failure injected after the temporary file is written and before
  `os.replace`.
  *Breaks when:* the disk fills, or the process dies mid-write.

- **INV-8** — Anything written reloads to an equal record set, `==` on the
  dataclass.
  *Test:* `tests/test_registry.py::test_write_then_load_round_trips`, over a
  record with every field populated, including a name needing JSON escaping.
  *Breaks when:* a field is serialised in a form `load_projects` rejects — a
  `Path` written as a repr, a `LauncherKind` written as an enum rather than
  its value — or **loaded back at the wrong type**: `argv` is
  `tuple[str, ...]` and JSON has only arrays, so a loader returning a `list`
  produces a record that is unequal to the one written while every field
  *looks* right (§ 4.2).

- **INV-9** — The written file is a regular file with mode `0600`, and a target
  that is a symlink or a non-regular file is refused rather than replaced.
  *Test:* `tests/test_registry.py::test_the_written_file_is_private`,
  `::test_a_non_regular_target_is_refused` (a FIFO at the config path), and
  `::test_a_symlinked_target_is_refused_not_followed` — a symlink pointing at a
  **regular** file, which is the case a FIFO fixture cannot reach.
  *Breaks when:* the process umask is permissive, or the implementation checks
  with `os.stat` / `Path.is_file()` instead of `os.lstat` — both follow the
  link, so the symlink passes as a regular file and `os.replace` then destroys
  it (§ 4.5 records the measured run). The FIFO test stays green under that
  bug, which is why the symlink case is named separately.

- **INV-10** — The merge report is bounded in both entry length and entry
  count, and a suppressed tail is always counted.
  *Test:* `tests/test_registry.py::test_the_merge_report_is_bounded`.
  *Breaks when:* a registry with tens of thousands of malformed records is
  merged — the shape LWSM-1115 already fixed for load reasons, arriving on a
  second surface.

- **INV-11** — Two records with the same effective port are both flagged, the
  earliest `added` wins, and the later claimant names the winner. **A record
  with no `added` loses to any record that has one**, and two without are
  ordered by position in the file (§ 4.2).
  *Test:* `tests/test_registry.py::test_duplicate_ports_are_flagged_with_the_first_registered_winning`,
  plus `::test_a_record_without_added_loses_the_port_tie_break`.
  *Breaks when:* a user sets an override equal to another project's declared
  port. The absent-`added` half breaks on **every file that exists today**,
  since none carries the key — without a stated default the comparison has no
  meaning on exactly the files INV-12 requires to load.

- **INV-12** — A file carrying only the fields `load_projects` reads today
  loads under the new reader, with defaults, and `SCHEMA_VERSION` is still 1.
  *Test:* `tests/test_registry.py::test_a_pre_existing_file_still_loads`.
  *Breaks when:* a new field is made required, or the version is bumped.

- **INV-13** — No value read from the file or from a scan reaches a report
  entry without passing `_quoted`.
  *Test:* `tests/test_registry.py::test_no_merge_value_is_interpolated_without_the_clip`,
  mirroring the existing `test_no_file_sourced_value_is_interpolated_without_the_clip`.
  *Breaks when:* a hand-edited name containing a newline reaches the status
  bar or the log through the merge report — the defect LWSM-1078, LWSM-1102
  and LWSM-1114 each closed at one call site, arriving on a new one.

- **INV-14** — `registry.MAX_REASON_CHARS`, `scanner.MAX_REASON_CHARS` and
  `scanner.MAX_DISPLAY_NAME_CHARS` are each asserted at their **literal**
  shipped values in one place.
  *Test:* `tests/test_registry.py::test_the_shipped_bounds_are_pinned`, widened
  from the existing test of that name, which today pins `registry`'s copy only.
  *Breaks when:* a bound is loosened. **Every scanner assertion about a clipped
  string is expressed *relative* to the constant** — `<= scanner.MAX_REASON_CHARS
  + 50`, `== scanner.MAX_DISPLAY_NAME_CHARS` — so raising the bound raises the
  assertion with it and the suite stays green; measured 2026-08-12, setting
  `scanner.MAX_REASON_CHARS = 400` reddened nothing. This closes
  known-issue-034, which routed itself here on the grounds that this item gives
  the constants a second consumer.

- **INV-15** — A merge never rewrites a record's stored `path` string, even
  when it resolves to something different.
  *Test:* `tests/test_registry.py::test_a_merge_does_not_rewrite_the_stored_path`
  — a record stored under a symlinked path, merged against a scan reporting its
  resolved form, asserting the written file still carries the path the user
  wrote.
  *Breaks when:* the merge is implemented as a set-driven replacement over the
  whole of `DETECTED_FIELDS`, which contains `path`. That is the natural
  reading of § 4.1's "replace the detected half", and it rewrites every stored
  path to its resolved form on the first rescan — so the invariant exists to
  make § 4.1's `- {"path"}` subtraction testable rather than decorative.

- **INV-16** — A load that produced any rejection reason makes the session
  read-only: no write is attempted, and the refusal names the count.
  *Test:* `tests/test_registry.py::test_a_file_with_a_rejected_row_is_never_written_back`
  — a file with one good project and one whose `name` is empty, asserting the
  file is byte-identical after a merge that would otherwise have changed it.
  *Breaks when:* any hand-written row is refused by the loader. `load_projects`
  returns rejected rows only as reason *strings*, so serialising `records` back
  would delete them permanently and silently — the write turning a recoverable
  hand-edit into data loss.

## 6. Failure modes

- **The config directory does not exist.** Created with mode `0700` before the
  first write; a failure to create it is a `RegistryError` with the reason,
  and the app keeps running against the in-memory list.
- **The file is unreadable at start.** Unchanged from today: `RegistryError`,
  empty window, reason in the status bar. LWSM-1039 adds the restore-from-backup
  offer; this item deliberately does not.
- **The disk is full.** The temporary write fails, the temporary file is
  unlinked, the previous file is untouched (INV-7), and the user is told the
  write failed rather than being left believing it succeeded.
- **A path cannot be resolved.** Falls back to lexical absolute, reported,
  merge continues (§ 4.4).
- **Two app instances write concurrently.** Last writer wins; `os.replace` makes
  each write atomic, so no reader ever sees a half-file, but one instance's
  edits can be lost. Not defended against — § 9.
- **The scan returns nothing at all.** Treated as a complete scan reporting
  every in-scope project missing *only* if `timed_out` is false **and `skipped`
  is empty**. Either one non-empty suppresses the missing check entirely
  (§ 4.6), which is the case that matters: a run where every root was refused
  for permissions returns zero projects with `timed_out` false, and the
  `timed_out` test alone would flag the whole registry missing. A registry is
  never blanked by a scan.

## 7. Tests

All of the above live in `tests/test_registry.py` beside the existing loader
tests, which the merge tests reuse the fixtures of (`write`, `one_good`).
Every one is written red first and watched failing before the code that
satisfies it — `testing.md § 1`, and the standing practice of this project's
last six fix-passes.

**Most of these need a real file, because the subject is a file** — the
existing `write(tmp_path, payload)` helper is how the loader tests already do
it, and INV-8, INV-12 and INV-16 all use it. Three need more than a file's
*contents*: INV-6 needs a symlink, INV-7 an injected mid-write failure, INV-9 a
FIFO, a symlink and a mode check. Every one of them uses `tmp_path` and
**carries no marker**, which is what
makes `--fast` run them: `scripts/local-ci.sh` runs `uv run pytest -q -m "not
integration"` under `--fast`, so a marker can only ever *exclude* a test. The
project declares exactly two markers, `gui` and `integration` (`pyproject.toml`),
and none of these three spawns a process or binds a socket, so `integration`
would be the wrong label as well as the excluding one. Where a marker is
warranted it goes on the test and never on the file (`CLAUDE.md`).

**What these tests do not prove**, said plainly: none of them exercises a real
concurrent write (the § 6 case), and INV-7's failure is injected rather than a
real power loss. Both are honest limits of a unit suite, not gaps to be closed
by asserting harder.

## 8. Alternatives considered (and rejected)

- **Bump `schema_version` to 2.** Rejected: the reader's check is exact, so
  every hand-written file in existence would be refused, and the new fields are
  all optional with defaults — there is nothing a version bump would protect.
  It becomes right the moment a field changes *meaning* rather than being added.
- **Split `ProjectRecord` into nested detected/user dataclasses.** Structurally
  stronger than § 4.1's membership sets, and rejected on blast radius: every
  consumer in `controller.py` and `mainwindow.py` reads the flat attributes
  today, and INV-1 buys the same guarantee — a new field must be classified or
  the build fails — for none of the churn.
- **Teach the scanner to distinguish "no port declared" from "could not
  read".** This is the better fix for § 4.3's limitation and it is not
  rejected, only deferred: it changes `DetectedProject`'s contract, and
  LWSM-1121 is already reopening the port sources. Recorded here so the next
  reader knows § 4.3's rule is a containment, not a conclusion.
- **Write the file on every change rather than only on a merge that changed
  something.** Rejected as premature: the only writer this item builds is the
  merge (§ 4.7), so there is no other change to write. It becomes the right
  question when an editing surface exists, and then it needs a debounce nobody
  has specified.
- **Resolve paths at load time rather than merge time.** Rejected: it would
  rewrite what the user's own file says, and `load_projects`'s refusal of `..`
  exists precisely because normalising a path lexically is wrong when a
  component is a symlink.
- **Carry loader-rejected rows through the write instead of refusing to write
  (INV-16).** This is the better end state and it is rejected *here* on scope:
  it means changing `load_projects` to return the raw JSON of every row it
  refused, which widens the reader's contract, its return type and every one of
  its existing tests — for a case the read-only rule already makes safe. The
  cost of the chosen rule is real and worth stating: one bad hand-edited row
  blocks persistence until the user fixes it. That is visible, reversible, and
  strictly better than the alternative it replaces, which was silent deletion.

## 9. Out of scope

- **Keeping a backup of the registry** — LWSM-1039. § 6 deliberately leaves
  the restore offer to it.
- **The first-run confirmation flow** — LWSM-1008. § 4.7 leaves the dialog to
  it.
- **`.env` / `docker-compose.yml` / `README.md` port sources and conflict
  reporting** — LWSM-1121.
- **Concurrent-writer safety** (a lock file, or an mtime precondition) —
  untracked, because two instances of a single-user desktop app is not a shape
  anyone has asked for. Recorded in § 6 so the omission is visible.
- **known-issue-010** (contrast computed only against `window`; `state_running`
  is 4.29:1 on `alt_base`) and **known-issue-013** (the row's accessible role
  is `Border`) both *named* LWSM-1007 as their owner, describing it as "the
  list view". Neither is registry work — one is a palette contrast check, the
  other an AT-SPI role — and their two siblings from the same review batch,
  known-issue-011 and -012, were already routed to **P04**. Both were
  **re-routed on 2026-08-12** while writing this spec: -010 to LWSM-1030
  (appearance and accessibility foundation), -013 to LWSM-1032 (the
  accessibility pass). The re-routing is done, not proposed; each entry
  records the reason in place.

## 10. Resource cost

- **Memory.** The registry is already bounded by `MAX_FILE_BYTES` (1 MiB) on
  read, and § 4.5 applies the same bound on write. The merge holds two
  dictionaries keyed by resolved path plus the report — O(n) in the number of
  projects, against a file whose size is capped.
- **Named cap on the report.** The merge report reuses the loader's
  `MAX_REASONS` (100) discipline with its always-reported suppressed tail
  (INV-10). Without it a hostile registry turns one rescan into tens of
  thousands of log records — the exact shape LWSM-1115 measured at 28.7 MB
  through a handler that rotates at 1 MiB.
- **Disk.** One file, plus a transient temporary file in the same directory
  that is unlinked on any failure path.
- **New external dependencies: none.** `json`, `os`, `tempfile` and `pathlib`
  are all already imported by `registry.py` or the standard library it uses.

## 11. What checks this

| Rule | What catches a breach |
|------|----------------------|
| INV-1 | `test_registry.py::test_every_record_field_is_classified` |
| INV-2 | `test_registry.py::test_a_rescan_never_writes_a_user_field` |
| INV-3 | `test_registry.py::test_unknown_does_not_erase_a_known_port` |
| INV-4 | `test_registry.py::test_a_timed_out_scan_marks_nothing_missing` |
| INV-5 | `test_registry.py::test_a_missing_project_is_kept_and_flagged` |
| INV-6 | `test_registry.py::test_two_paths_resolving_to_one_directory_are_one_project` |
| INV-7 | `test_registry.py::test_a_failed_write_leaves_the_old_file_intact` |
| INV-8 | `test_registry.py::test_write_then_load_round_trips` |
| INV-9 | `test_registry.py::test_the_written_file_is_private`, `::test_a_non_regular_target_is_refused`, `::test_a_symlinked_target_is_refused_not_followed` |
| INV-10 | `test_registry.py::test_the_merge_report_is_bounded` |
| INV-11 | `test_registry.py::test_duplicate_ports_are_flagged_with_the_first_registered_winning`, `::test_a_record_without_added_loses_the_port_tie_break` |
| INV-12 | `test_registry.py::test_a_pre_existing_file_still_loads` |
| INV-13 | `test_registry.py::test_no_merge_value_is_interpolated_without_the_clip` |
| INV-14 | `test_registry.py::test_the_shipped_bounds_are_pinned` (widened to the two `scanner` constants) |
| INV-15 | `test_registry.py::test_a_merge_does_not_rewrite_the_stored_path` |
| INV-16 | `test_registry.py::test_a_file_with_a_rejected_row_is_never_written_back` |
| § 4.7 write trigger | `test_registry.py::test_an_all_unchanged_merge_does_not_write` |
| § 4.6 scope of *missing* | `test_registry.py::test_a_project_outside_every_scan_root_is_not_missing` |
| § 4.6 *new*-record seeding | `test_registry.py::test_a_new_record_takes_its_name_from_the_scan_and_a_stamped_added` |
| § 4.2 `kind` / tuple round-trip | covered by INV-8's round-trip over a fully-populated record |
| § 4.3 per-field unknown table | **nothing** — only `port` has an unknown sentinel, so the other three rows assert an absence; INV-3 covers the one field that can break |
| § 4.7 per-row flags not rendered | **nothing** — a deliberate omission, not a rule; LWSM-1008 owns the surface |
| § 4.5 step 4 (directory `fsync`) | **nothing** — a durability claim a unit test cannot falsify without power loss; the call site is reviewed, not tested |
| § 6 concurrent writers | **nothing** — out of scope by § 9; last writer wins and no reader sees a half-file |
| § 4.3's stale-port limitation | **nothing** by design — it is the accepted cost of INV-3; removing it is the deferred scanner change in § 8 |

**Twenty-five rows, five of which say `nothing`** — the honest error budget
`spec-format.md § 0` asks for. All five are limits or deliberate omissions
rather than defects: the directory `fsync`, which no unit test can falsify
without power loss; concurrent writers, excluded by § 9; § 4.3's stale-port
cost, accepted as INV-3's price; § 4.3's per-field unknown table, three rows of
which assert an *absence* of a sentinel and so have nothing to break; and
§ 4.7's un-rendered per-row flags, which are a decision not to build rather
than a rule. **None carries a roadmap id, because none is a gap to close.**

*Command, run against this file:*

```
awk '/^\| Rule \| What catches/{f=1;next} f&&/^\|---/{next} \
     f&&/^\| /{n++; if(/^\| INV-/)i++; if(/\*\*nothing\*\*/)z++} \
     f&&!/^\| /{exit} END{print "rows="n" inv="i" nothing="z}' \
  docs/specs/LWSM-1007-registry-persistence.md
```

→ `rows=25 inv=16 nothing=5`, against `grep -c '^- \*\*INV-'` → `16`. So the
table and § 5 enumerate the same sixteen invariants, and the nine non-`INV`
rows are the five `nothing` limits plus four § 4 rules that carry a test
without carrying an invariant of their own.

## 12. Cross-doc impact

- **`docs/decisions/0005-registry-and-rescan.md`** — gains a clause for § 4.3
  (unknown is not changed) and one for § 4.6 (a timed-out scan marks nothing
  missing). Both are decisions the ADR did not make; recording them in the
  spec alone would leave the ADR contradicting the shipped behaviour.
- **`CLAUDE.md § Module map`** — `registry.py`'s entry gains the writer and the
  merge.
- **`docs/known-issues.md`** — known-issue-010 and -013 re-routed to P04
  (§ 9); known-issue-025 and -034 closed by this item; **known-issue-033 stays
  open** and keeps its routing, for the reason § 2 gives.
- **`CHANGELOG.md`** — an `[Unreleased] ### Added` entry.
- **`docs/design.md § Components`** — the Rescan flow already describes this
  behaviour; check it still matches once § 4.6 ships.

## 13. Cold-eyes loop log

| Loop | Date | Lanes | CRIT | HIGH | MED | LOW | Outcome |
|------|------|-------|------|------|-----|-----|---------|
| 1 | 2026-08-12 | 3 (general-purpose, strong model), identical brief, four-question form | Q1 ×3 · Q2 ×3 · Q3 ×6 · Q4 ×0 | **17 raw across 3 lanes → 12 distinct, 12 verified, 0 dismissed, 12 fixed.** Zero wording findings. Convergence on defects was unusually high — all three lanes independently found the same three, which is what makes them worth naming. **The sharpest is a check that did not do what its own paragraph said**: § 4.5 refused a non-regular target to stop `os.replace` destroying a user's symlink, but the natural implementation of "is not a regular file" *follows* the link. Measured here on 3.13 — `link.is_file()` → `True`, `S_ISREG(os.stat)` → `True`, `S_ISREG(os.lstat)` → `False` — and `os.replace` onto it left `is_symlink()` → `False` with the real file untouched. The FIFO test named in INV-9 stays green through that bug, so the fix is `os.lstat` plus a symlink-to-**regular**-file case. **Two contradictions between sections that each read fine alone:** INV-5 "never deleted" against § 4.4 "refuses the later record" and INV-6 "never both persist" — resolved so that a duplicate identity is kept and excluded rather than dropped, since the loser holds a user-owned half no rescan can reconstruct; and § 4.3's table calling a stored-`None`/scan-`3000` row *changed* while § 4.6 required "both known", which left a first successful detection matching no outcome row. **Two fields were deleted rather than specified** — `detected_missing` and `port_last_detected` were in the § 4.2 format, in neither field set (so INV-1 would have failed on the first run), and read by nothing in § 4.3 or § 4.6. **Three claims about this project's own tooling were false or unstated:** `--fast` is `pytest -m "not integration"`, so a marker can only *exclude* — "marked so `--fast` keeps them" was backwards; `added` had no default while INV-11 tie-breaks on it and INV-12 requires today's key-less files to load; and `argv` had no fixed type, so INV-8's "equal record set" was undefined for tuple-vs-list. § 1 also promised a rename/override the item builds no surface for — narrowed to a hand-edited file. Threading and the write trigger were unspecified and are now pinned (worker thread, write only when a merge changed something). One open question resolved **clean**, so it is not in the tally: consumers read only `record.path`, `record.name` and `record.effective_port`, exactly as § 4.1 claims. INV-14 added, closing known-issue-034; known-issue-033 explicitly left open, because this item adds no subpackage and its routing premise does not fire. Loop 2 dispatched. |
| 2 | 2026-08-12 | 3 (general-purpose, strong model), brief byte-identical to loop 1, no prior-loop findings disclosed | Q1 ×1 · Q2 ×3 · Q3 ×6 · Q4 ×0 | **10 verified, 0 dismissed, 10 fixed.** **Nothing from loop 1 resurfaced, so those twelve fixes held.** Roughly half of these are loop 1's own collateral, which is the honest reading: § 4.2's new default list omitted `kind`; § 4.6's new "roots the scan actually walked" condition could not be evaluated at all, because `ScanResult` carries only `projects`/`skipped`/`timed_out` and no merge signature existed anywhere — so the merge's signature is now written down, taking `roots` as a parameter; § 6's "scan returns nothing" sentence contradicted the `skipped` rule loop 1 had just added; and `added` gained an ordering rule without a type or a stamper. **The two genuine draft defects are the ones worth keeping:** `path` is in `DETECTED_FIELDS` while § 4.4 promises the stored path is never rewritten, so a merge built as a plain set-driven replacement — the natural reading of "replace the detected half" — would rewrite every stored path to its resolved form on the first rescan (now `DETECTED_FIELDS - {"path"}`, tested by INV-15); and **the writer would have destroyed data**, since `load_projects` returns rejected rows only as reason *strings*, so serialising `records` back over the file permanently deletes every hand-written row the loader refused. That is the one data loss this app is capable of, arriving through the feature meant to preserve state — closed by INV-16, which makes a load with any rejection read-only. Also: INV-2 forbade writing a user-owned field while § 4.6's *new* row must write `name` and `added`, so INV-2 is now scoped to existing records and seeding is specified; § 4.3's unknown rule was stated over "a detected field" but defined only for `port`, which would have kept a stale `unit` forever on a project that stopped being a systemd service; and § 4.7's per-row flags had nowhere to live, since `rows()` rebuilds every `RowView` from four record fields each 1000 ms poll — the flags are now summary-only and the per-row surface is left to LWSM-1008. Loop 3 dispatched. |
