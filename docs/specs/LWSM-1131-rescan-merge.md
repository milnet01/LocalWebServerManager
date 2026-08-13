# LWSM-1131 — Merge a rescan into the stored registry without discarding user edits

**Status:** spec draft (2026-08-12).
**Kind:** implement.
**Source:** ROADMAP LWSM-1131 (split-of-LWSM-1007-2026-08-12). Policy settled by
[ADR-0005](../decisions/0005-registry-and-rescan.md); this is half of its
mechanism. **Split out of an umbrella spec on 2026-08-12** — see § 3.
**Blocked by:** [LWSM-1007](LWSM-1007-registry-persistence.md) (the record
format and the writer), which is itself blocked by LWSM-1006 (shipped
2026-08-12).
**Blocker for:** nothing. LWSM-1039 and LWSM-1008 both declare LWSM-1007 and
neither needs the merge.
**Pairs with:** [LWSM-1007](LWSM-1007-registry-persistence.md), the other half
of the split. That spec owns what a record *is* and how it reaches the disk;
this one owns what a rescan does to it.

**Layman:** Let a rescan pick up new projects without undoing anything you have
changed by hand — and when the scan cannot tell something it knew before, say so
instead of forgetting it.

## 1. Goal

A rescan merges detected facts into the stored list under ADR-0005's rule — user
intent wins, nothing is auto-deleted, and every disagreement is reported — and
the result survives a restart, because LWSM-1007's writer puts it on disk.

The acceptance criterion, stated against what this item actually builds: a
`projects.json` carrying a hand-edited `name` and a hand-edited `port_override`
survives a **Rescan** with both edits in force, plus a visible account of what
the scan changed.

**Editing those fields from inside the app is not part of this item** and no
section below specifies a surface for it. `renaming, hiding and overriding from
the UI` is P07's LWSM-1014 for the port override, and there is no roadmap item
for renaming yet. Saying "a user can rename a project" here would promise an
implementer a dialog this spec never describes.

## 2. Problem

Three gaps, each grounded in a symbol read for this spec rather than recalled.
None of them is a gap in the *format* — LWSM-1007 settles that — and all three
are about what a merge does with what a scan reports.

1. **Unknown and changed are the same value, so a rescan can silently erase a
   known port.** `scanner.DetectedProject.port` is `PortFinding | None`, and its
   own comment fixes the meaning: `None` means "unknown", never a guess.
   ADR-0005 says a *changed* detected field means "detected fields differ →
   detected half updated". A scan that cannot read a launcher this run — a
   permission change, a budget expiry — yields `port=None`, which differs from a
   stored `3000`, so the literal rule updates the detected half to `None` and a
   known port is gone. **ADR-0005 has no clause distinguishing an observation of
   absence from the absence of an observation**, and neither does anything else
   in the tree. This is the single most consequential gap this spec closes.

2. **The two sides disagree about what a project's identity is.**
   `scanner.DetectedProject.path` is documented as `RESOLVED, absolute; the
   identity (ADR-0005)`. `registry.load_projects()` builds `Path(raw_path)` and
   never resolves it — it refuses `..` and a doubled leading slash, and dedups
   through a `seen: set[Path]` of unresolved paths. So a stored
   `/home/me/projects/foo` that is a symlink to `/srv/foo` compares unequal to
   the `/srv/foo` a scan reports, and the merge sees one project as
   simultaneously *new* and *missing*. `docs/known-issues.md` known-issue-025
   demonstrates the scanner half of this — `scan([symlinked_root, real_root])`
   returns **2 projects for 1 directory** — and was re-pointed here on
   2026-08-12, from LWSM-1007, because identity is something a *merge* compares.

3. **A partial scan is indistinguishable from a shrunken one.**
   `scanner.ScanResult` carries `timed_out: bool` with the comment `the budget
   expired; projects is partial`. Nothing consumes it. A merge that ignores it
   marks every unreached project *missing* on a slow run.

**One** entry in `docs/known-issues.md` names LWSM-1131 as its owner, and **this
item closes it**: known-issue-025 (identity — § 4.2, INV-5).

*Command:* `awk '/^## known-issue-/{h=$0} /^- \*\*Will be addressed in:\*\* LWSM-1131/{print h}' docs/known-issues.md`

## 3. Scope decisions (agreed with the user)

- **Phase.** This item belongs to `P03b`, the continuation phase carrying the
  four items P03 planned and did not deliver, and it is the fifth — created by
  splitting the first (user, 2026-08-12). Commits read `P03b: …`.
- **This spec is one half of a split.** The umbrella spec — *LWSM-1007 — Persist
  the registry, and merge a rescan without discarding user edits* — reached
  `review-contract`'s 3-loop cap without converging. Every one of its 34 findings
  was verified and fixed and none ever resurfaced, so the fixes held; what kept
  arriving was new surface. The document went **540 → 692 → 852 → 979 lines**
  while the finding count held flat at **12 / 10 / 12**, and each loop's
  findings clustered in a *different* region. That is the "two cold reads never
  reached parts of it" shape, so `spec-format.md § 5.4` and global rule 14's
  *past loop 3, split rather than loop* both apply. The seam is § 4 of the
  umbrella: [LWSM-1007](LWSM-1007-registry-persistence.md) keeps the record
  format and the writer, this part takes the merge. **Neither part inherits the
  umbrella's review** — the loops ran against a document that no longer exists,
  so each runs the gate from loop 1 on its own bytes.
- **A new id rather than a suffix.** `spec-format.md § 5.4` requires each part
  of a split get its own id; LWSM-1007 keeps its own so its inbound citations
  stay valid, and the merge — which nothing cites yet — takes the new one.
- **Invariants are renumbered from 1**, per `/write-spec`'s splitting rule. **The
  mapping, so the umbrella's citations stay findable:**

  | Umbrella INV | Here | Subject |
  |---|---|---|
  | INV-2 | **INV-1** | a merge never writes a user field of an existing record |
  | INV-3 | **INV-2** | unknown never overwrites a stored known value |
  | INV-4 | **INV-3** | a timed-out scan marks nothing missing |
  | INV-5 | **INV-4** | a stored record is never deleted by a merge |
  | INV-6 | **INV-5** | two paths resolving to one directory never both merge |
  | INV-10 | **INV-6** | the merge report is bounded |
  | INV-11 | **INV-7** | duplicate effective ports, earliest `added` winning |
  | INV-15 | **INV-8** | a merge never rewrites a stored `path` |
  | INV-17 | **INV-9** | `added` is compared as a parsed instant |
  | INV-13 (merge half) | **INV-10** | no merge-report value skips `_quoted` |

  Umbrella INV-1, -7, -8, -9, -12, -14, -16 and the writer half of -13 are all
  format-and-writer rules and stayed with LWSM-1007, whose § 3 carries the
  mirror of this table.
- **Section numbering follows the global standard, and the siblings differ.**
  `~/.claude/standards/spec-format.md § 4` requires recommended sections
  "appended after § 3's twelve, numbered from 13 … never interleaved", so
  *Resource cost* is § 13 here. `LWSM-1005` and `LWSM-1006` interleave it at
  § 10; known-issue-036 owns the sweep that renumbers them.

## 4. Design

### 4.1 Unknown is not changed

The rule this spec exists to add:

> A detected field whose rescan value is **unknown** does not overwrite a stored
> known value. It is the absence of an observation, not an observation of
> absence.

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
genuinely removed keeps a stale value until the user clears it. That is the safe
direction of the two — a stale port is visible and correctable, an erased one is
neither — but it is a real cost, and § 8 records the alternative that removes it.

### 4.2 Identity is the resolved path, compared at merge time

The merge keys both sides on `Path.resolve()`. It does **not** rewrite what is
stored: the user's file keeps the path they wrote, so the file stays
recognisable to the person who hand-edits it. LWSM-1007 § 4.2 states the same
rule from the writer's side; INV-8 here tests the merge's.

Two records whose stored paths resolve to one directory are a malformed
registry, exactly as two identical paths already are (`load_projects` refuses
the second with *already registered*). The existing `seen` check cannot see this
case, because it compares unresolved paths — which is precisely
known-issue-025.

**Neither record is deleted.** The one appearing **first in file order** owns the
identity: it alone is merged into. The second is kept, written back unchanged,
and flagged *duplicate identity of `<first project>`*.

**It is still polled, and that is a stated limitation rather than an
oversight.** Excluding it from the status loop would need the excluded set to
reach `ProjectController`, and nothing carries it: `merge()` returns
`(records, reasons)`, no merge outcome is persisted (LWSM-1007 § 4.2), and
`rows()` rebuilds from records alone. The visible cost is two rows for one
directory, both showing the same status. Suppressing the row properly is the
same mechanism as honouring `hidden`, and § 9 defers both together rather than
inventing a channel for one of them here. File order decides rather than
`added`, because `added` is optional while position always exists, and because
it is the rule `load_projects` already applies to exact duplicates — the second
occurrence is the one refused.

Keeping the loser is not a nicety: it holds a user-owned half (notes, an
override, an `added`) that no rescan could reconstruct, and ADR-0005 makes
removal a user action so that an unmounted drive cannot destroy the list. INV-4
therefore holds without a carve-out, and INV-5 is about what *merges*, not about
what survives.

**Resolution can fail**, and this project has been bitten four times by an
exception escaping a per-item loop and taking the batch with it (`CLAUDE.md`,
the same family as the `pathlib`-on-3.13 trap, though **not the same call**:
that trap is `Path.exists` / `is_file` / `is_dir`, and measured here, non-strict
`resolve()` returns normally where `exists()` raises `PermissionError`. No
fixture in this project is known to make `resolve()` raise, so the handler is
defence-in-depth and § 10 files its test as unreachable rather than claiming a
failure mode nobody can produce). So resolution
is per record, inside a handler, and a path that cannot be resolved falls back
to its lexical absolute form and is reported — never dropped, and never allowed
to abort the merge.

### 4.3 Merge outcomes

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
) -> MergeResult: ...


@dataclass(frozen=True)
class MergeResult:
    records: list[ProjectRecord]
    reasons: list[str]  # report entries, bounded by INV-6
    counts: dict[str, int]  # outcome label -> count, for § 4.4's summary
```

**`counts` is a field rather than something the slot derives**, because the
only other way to build § 4.4's summary is to match outcome words inside
`reasons` — the exact wording-dependence § 8 rejects for `skipped`, and it
would break silently the first time an entry is reworded. The merge already
knows each outcome as it assigns it; carrying the tally costs a counter.

**`now()` must return RFC 3339 with a `Z` suffix and second precision** —
`datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")` in production,
matching LWSM-1007 § 4.2's stamped spelling. Pinned because `Callable[[], str]`
admits anything: the obvious `datetime.now().isoformat()` produces a **naive**
stamp, LWSM-1007's reader drops any `added` whose parsed `tzinfo` is `None`, and
every record this app created would lose its timestamp on the next load —
leaving INV-7's tie-break with nothing to compare on exactly the records the app
made itself, which is the failure INV-1's seeding rule exists to prevent.

**`roots` is a parameter because `ScanResult` does not carry it** — its three
fields are `projects`, `skipped` and `timed_out`. Without it the *missing*
outcome below cannot be evaluated at all, and an implementer would fall back to
inferring roots from the projects returned, under which a root that legitimately
contains zero projects silently stops marking its records missing. The **roots
requested** are used rather than "the roots actually walked", because a partial
scan does not report which it reached.

The return shape is a plain `(records, reasons)` tuple. It **used** to be
described as mirroring `load_projects`, and no longer does: LWSM-1007 § 4.3
replaces that loader's two-tuple with a `LoadResult` dataclass carrying a
`rows_refused` count, which the merge has no equivalent of — nothing a merge
produces is refused at row level. The two shapes are deliberately different, so
an implementer should not reach for `LoadResult` here.

**The merge replaces `DETECTED_FIELDS - {"path"}`, except that `port` is
replaced only when the scan value is known (§ 4.1), and keeps the user half**,
rather than copying field by field. The `port` qualifier is not a detail: it is
in `DETECTED_FIELDS`, so the unqualified rule writes `None` over a stored
`3000` on the first unreadable launcher — which is INV-2 and the *not
re-observed* outcome broken by the mechanism sentence that sits above them. The subtraction is the whole of the
never-rewrite-a-path rule: `path` is in `DETECTED_FIELDS` because a scan is what
observes it, but `DetectedProject.path` is *resolved* while the stored path is
whatever the user wrote (§ 4.2) — so a merge implemented as a plain set-driven
replacement over the whole set would rewrite every stored path to its resolved
form on the first rescan, which is exactly what § 4.2 promises against. INV-8
tests it, because prose saying "nothing may rewrite it" is not a contract.

Seven outcomes: ADR-0005's four (*new*, *unchanged*, *changed*, *missing*), its
*override differs* flag tabulated as a row of its own, and **two this spec
adds** — *not re-observed* (§ 4.1) and *duplicate identity* (§ 4.2). Each
produces a report entry; none mutates silently.

| Outcome | Condition | Effect |
|---|---|---|
| **new** | scanned, not stored | added, flagged *new*; seeded per below |
| **unchanged** | detected halves equal | nothing |
| **changed** | detected halves differ **and the scan value is known** | detected half updated, change listed |
| **missing** | stored, in scope for this scan (below), absent from a complete one | kept, flagged *missing*, never deleted |
| **not re-observed** | stored known, scan unknown (§ 4.1) | stored value kept, flagged |
| **override differs** | `port_override` is set and the detected `port` moved | override stays in force, row flagged |
| **duplicate identity** | resolves to the same directory as an earlier record (§ 4.2) | kept and written back unchanged, excluded from the merge, flagged |

**A *new* record is seeded, and that is the one place a merge writes a
user-owned field.** `name` takes `DetectedProject.name`, `added` takes `now()`,
and every other user field takes its LWSM-1007 § 4.2 default. INV-1 is scoped to
records already in the registry for exactly this reason: read as covering
creation too, it would forbid the merge from giving a new project a name, and an
implementer obeying it literally would add unnamed rows with no `added` — which
would in turn leave INV-7's tie-break with nothing to compare on any record the
app itself created.

**"the scan value is known", not "both known".** A stored `None` with a scan
reporting `3000` is a *changed* row — the port has just been discovered, and the
user is told. Requiring both sides to be known would leave that case matching no
row at all, so a first successful detection would update the record and report
nothing.

**Only `port_override` participates in *override differs*.**
`launcher_override` is stored but is not mapped to any detected field in this
item, so there is nothing for it to differ *from*: `ProjectRecord.effective_port`
already fixes the override/detected precedence for ports, and no equivalent
exists for a launcher.

**`hidden` and `launcher_override` are preserved and not acted on.** The merge
carries them through as user-owned, and **nothing in this item reads either.**
ADR-0005 says hidden projects are not polled and drop out of the list; that
behaviour needs a controller change and a UI affordance for un-hiding, neither
of which this item builds, and a hand-set `"hidden": true` that silently removed
a row with no way to bring it back would be worse than one that does nothing
yet. Stated because the file is hand-editable, so both keys are reachable today.

**"In scope for this scan" is what makes *missing* mean anything.** A stored
record is a candidate for *missing* only when its resolved path lies under one
of the `roots` passed to `merge()`. ADR-0005 says "absent from disk", which is
not what a scan observes — a scan observes absence *from its own roots*. A
project the user added by hand outside every scan root is present on disk and
absent from every scan, so the literal reading would flag it missing on the
first rescan and every one after.

**Containment is resolved-against-resolved, and both sides matter.** The stored
path is resolved (§ 4.2) and **the roots must be resolved too**, because
`scan()`'s docstring says "a scan root that is itself a symlink is **followed**,
deliberately". With `roots=(/home/me/projects,)` symlinked to `/srv`, every
stored record resolves to `/srv/…`, lies under no root as written, and *missing*
never fires for anything — the same symlink shape known-issue-025 and INV-5 are
built on, arriving on the containment test instead of on identity. A root that
cannot be resolved is excluded from the containment test and reported, per
§ 4.2's per-record handler rule.

**A skip suppresses the missing check only when it could have CONCEALED a
project, and `ScanResult` gains a field so the merge can tell.** The
distinction is the same one § 4.1 draws between an observation of absence and
the absence of an observation, applied to roots instead of ports.

`scan()` calls `note()` for two different kinds of thing. **Ordinary
per-entry skips** — `"is not a directory"`, `"no launcher matched"`,
`"already scanned under another root"`, `"is this application's own
directory"` — mean the scanner *looked at* the entry and rejected it. That is
evidence, and it must not suppress anything. **A root that could not be
listed** (`"cannot be listed"`) means an unknown number of projects were never
seen at all.

Reading `skipped` as a blanket signal is therefore wrong, and wrong in the
direction that silently disables a feature: `skipped` is `tuple[str, ...]`, so
**one stray file in a scan root makes it non-empty**, and *missing* would never
fire on any populated machine while a clean fixture passed. ADR-0005's
*missing* flag, INV-4 and § 10's out-of-scope row would all be unreachable in
production.

So **`ScanResult` gains `unlistable_roots: tuple[Path, ...]`**, populated where
`scan()` already notes a root it could not list, and the merge suppresses the
missing check **only for stored records resolving under one of those roots,
compared resolved-against-resolved**. The entries are resolved before the
containment test for the same reason `roots` are — a symlinked root would
otherwise contain nothing, and here that failure lands on the permission-denied
run, which is the one branch this field exists for.
Every other root is still checked. A per-entry skip suppresses nothing. This is
a change to `scanner.py`, listed in § 11; the alternative — leaving the merge to
parse reason strings — is rejected in § 8.

**A timed-out scan marks nothing missing.** When `ScanResult.timed_out` is true,
`projects` is partial by its own definition, so absence carries no information.
The merge reports that it could not check for missing projects. This rule leans
directly on LWSM-1125's guarantee that `_BudgetExpired` does not subclass
`OSError` — without it a timed-out scan reports `timed_out=False` and this rule
would never fire on the runs that need it.

**Duplicate effective ports** are flagged at merge time per ADR-0005, naming
both projects, with the earliest `added` winning and every later claimant marked
*port claimed by `<other project>`*. **An absent `added` sorts after every
present one**, with file order breaking a tie between two absent ones — a rule
that exists because every file in existence today lacks the key, so "earliest
`added` wins" would otherwise have no meaning on exactly the files LWSM-1007's
INV-5 requires to load.

### 4.4 The Rescan seam

`MainWindow` gains a **Rescan** button. The report is presented **only** as a
one-line summary through `MainWindow.set_status_message`, which already exists.

**The summary is `MergeResult.counts` rendered in this fixed order, omitting
any whose count is zero:**

| Order | Outcome | Label |
|---|---|---|
| 1 | new | `N new` |
| 2 | changed | `N changed` |
| 3 | not re-observed | `N port no longer detected` |
| 4 | override differs | `N override differs` |
| 5 | duplicate identity | `N duplicate` |
| 6 | missing | `N missing` |

`"Rescan: 2 new, 1 changed, 1 missing"`. That is six of § 4.3's seven outcomes.
**`unchanged` is the seventh and is never rendered** — it is counted, because
`counts` is the merge's own tally, but it is the one outcome that is not news.
When every rendered count is zero the line is `"Rescan: no changes"`. **The full report entries go to the
application log**, one record each, where INV-6's bound already applies.
Pinned because "a one-line summary" admits both `"Rescan complete"`, which
satisfies no acceptance criterion, and `"; ".join(reasons)`, which is
effectively unbounded — INV-6 caps the entry *list*, not a line built by joining
it, and § 1 promises "a visible account of what the scan changed".

**Per-row flags are deliberately not rendered in this item.** `RowView` carries
four fields — `path`, `name`, `effective_port`, `status` — and
`ProjectController.rows()` rebuilds every one of them from the records on each
1000 ms poll. A merge flag is not record state (LWSM-1007 § 4.2 persists no
outcome), so it has nowhere to live across a rebuild and would vanish within a
second of being set. Rendering it properly means either persisting outcomes or
giving the controller a second source of row state, and both are larger
decisions than this item needs. The summary is durable enough to satisfy
ADR-0005's requirement that a rescan "produce a visible answer rather than a
silent mutation"; per-row presentation belongs with the first-run flow
(LWSM-1008), which is already designing a surface for showing detected results.

**The scan and the merge run on a `QThreadPool` worker, not on the GUI thread.**
`scan()` is budgeted precisely because it is slow — it walks roots, opens other
people's files and may shell out to `systemctl` — so running it inline would
freeze the window for the length of the scan. This is the arrangement
`ProjectController` already uses for its 1000 ms poll, and `design.md § State
management` requires it. The worker returns the merged records and the report
through a signal; **the file write and every UI update happen on the GUI
thread**, in the slot. Rescan is disabled while one is in flight, so two
overlapping merges cannot both write.

**An exception escaping the worker must be caught inside `run()`.** PySide6
swallows one — verified against the pinned 6.11.1 on 2026-08-06: the traceback
prints to stderr, the process survives at exit 0, and **no signal is emitted**,
so the in-flight flag that disables Rescan would stay set and the button would
never re-enable. `run()` therefore needs a catch-all that still reports, not
just the exception it expects. This is LWSM-1069's shape arriving on a second
worker.

**First run writes unconditionally, and it is the exception to the trigger
below.** When the load raised `RegistryMissing` there is no file, so "differs
from the loaded one" is vacuous — and on a clean machine whose first scan finds
**zero** projects both sets are empty, the difference test says no, and
`projects.json` would never come into existence. Every subsequent run would
repeat the whole first-run path. So: `RegistryMissing` writes, empty or not.

**Otherwise exactly one trigger writes the file: the merged record set differs
from the loaded one.** Record *content*, not report entries — three outcomes flag a row
while leaving every field identical (*missing*, *not re-observed*, *duplicate
identity*), and none of them writes. A no-op rewrite would churn the file's
mtime and widen the only window in which the concurrent-writer loss LWSM-1007
§ 6 describes can occur, for no gain. "A merge that changed something" would be
ambiguous here in exactly the wrong direction: a *missing*-only merge changes
the report and nothing else, and both readings pass a test that only exercises
an all-*unchanged* merge. There is **no write on exit**: nothing this item
builds mutates the registry outside a merge, so an exit hook would have nothing
to flush.

**The write is still subject to LWSM-1007's read-only gate, and the SLOT owns
it — not `merge()`.** `merge()`'s signature takes `stored`, `scan`, `roots` and
`now`, and returns records and reasons; it is handed no `LoadResult`, calls no
writer, and must not, because it runs on the pool thread while every write
happens on the GUI thread. **The `LoadResult | RegistryError` from the startup
load is held by the window and passed to `save_projects(path, merged,
load=…)` in the slot**, which is the only place both values are in scope. A
merge whose `stored` came from a load that refused a **row**, or that raised any
`RegistryError` **other than `RegistryMissing`**, still runs and still reports;
the writer refuses. Nothing re-implements the check.

**`RegistryMissing` is the exception, and it is the first-run path this item
actually runs on.** No file means `stored` is empty, so every scanned project is
*new*, and the write **must** happen — that is how `projects.json` comes into
existence at all. Reading the gate as "any `RegistryError` blocks the write"
would make a clean machine permanently unable to persist a rescan; LWSM-1007
§ 4.3 carries the measurement showing an absent file raises `RegistryError`
today.

Deliberately **not** a dialog: presenting a detected list for confirmation is
LWSM-1008's job, and building a lesser version here would be the thing it then
has to replace.

## 5. Invariants

- **INV-1** — A merge never writes a user-owned field of a record **already in
  the registry**. Seeding a *new* record is the sole exception and is specified
  in § 4.3.
  *Test:* `tests/test_registry.py::test_a_rescan_never_writes_a_user_field` — a
  stored record with every user field set, merged against a scan whose `name`
  differs, asserting the user half is byte-identical afterwards.
  *Breaks when:* the merge copies `DetectedProject.name` over a user-renamed
  record. `name` is the discriminating fixture precisely because both sides
  carry that field; a fixture using `notes`, which the scanner has no equivalent
  of, would pass against a merge that copied everything.

- **INV-2** — A detected field whose rescan value is unknown never overwrites a
  stored known value.
  *Test:* `tests/test_registry.py::test_unknown_does_not_erase_a_known_port` —
  stored `port=3000`, scan yields `port=None`, assert `3000` survives and the
  row is flagged.
  *Breaks when:* the scan cannot read a launcher it read last time.

- **INV-3** — A timed-out scan marks nothing missing.
  *Test:* `tests/test_registry.py::test_a_timed_out_scan_marks_nothing_missing`
  — `ScanResult(timed_out=True)` omitting a stored project, asserting it is not
  flagged missing and that the report says the check was skipped. A second case,
  `::test_an_unlistable_root_marks_nothing_missing_under_it`, covers the other
  suppressing condition — the two are separate and a fixture for one passes
  under a merge that only implements the other. **Neither is named for
  `skipped`**: an ordinary per-entry skip suppresses nothing (§ 4.3), so a test
  named for the blanket reading would lock in the defect that section rejects.
  *Breaks when:* the scan budget expires with projects still unreached, or every
  root is refused for permissions — which returns zero projects with
  `timed_out` false.

- **INV-4** — A stored record is never deleted by a merge.
  *Test:* `tests/test_registry.py::test_a_missing_project_is_kept_and_flagged`.
  *Breaks when:* a project's drive is unmounted and a complete scan reports it
  absent.

- **INV-5** — Two stored records whose paths resolve to one directory never both
  **merge**: the first in file order owns the identity, the second is flagged
  *duplicate identity* and excluded from the merge. Both are still written back
  (INV-4).
  *Test:* `tests/test_registry.py::test_two_paths_resolving_to_one_directory_are_one_project`,
  using known-issue-025's fixture — a symlinked root beside the real one —
  asserting one merged project, **two records in `merge()`'s returned list**,
  and the second flagged.
  **It asserts on the returned records, not on a written file**, because
  *duplicate identity* is one of the three outcomes § 4.4 says leave every field
  identical and therefore do **not** trigger a write. A fixture reading
  `projects.json` would be reading a file the merge was never permitted to
  create.
  *Breaks when:* a user adds a project by a symlinked path having already added
  it by its real one. The existing duplicate check cannot catch this: it
  compares unresolved paths, so both records are distinct to it.
  **It constrains what merges, not what survives.** Read as a rule about
  survival it would contradict INV-4, and an implementer would delete the loser
  along with the user-owned half no rescan can reconstruct.

- **INV-6** — The merge report is bounded in both entry length and entry count,
  and a suppressed tail is always counted.
  *Test:* `tests/test_registry.py::test_the_merge_report_is_bounded`.
  *Breaks when:* a registry with tens of thousands of malformed records is
  merged — the shape LWSM-1115 already fixed for load reasons, arriving on a
  second surface.

- **INV-7** — Two records with the same effective port are both flagged, the
  earliest `added` wins, and the later claimant names the winner. **A record
  with no `added` loses to any record that has one**, two without are ordered by
  position in the file, and **two whose `added` values denote the SAME instant
  are ordered by position in the file as well**. All three fall back to file
  order for the same reason: position always exists, and § 4.2 makes it the rule
  for a duplicate identity already.
  *Test:* `tests/test_registry.py::test_duplicate_ports_are_flagged_with_the_first_registered_winning`,
  plus `::test_a_record_without_added_loses_the_port_tie_break`.
  *Breaks when:* a user sets an override equal to another project's declared
  port. The absent-`added` half breaks on **every file that exists today**,
  since none carries the key — without a stated default the comparison has no
  meaning on exactly the files LWSM-1007's INV-5 requires to load.

- **INV-8** — A merge never rewrites a record's stored `path` string, even when
  it resolves to something different.
  *Test:* `tests/test_registry.py::test_a_merge_does_not_rewrite_the_stored_path`
  — a record stored under a symlinked path, merged against a scan reporting its
  resolved form **and a changed `port`**, asserting the returned record still
  carries the path the user wrote and that the written file does too. **The
  changed port is load-bearing in the fixture**: without a detected change the
  merge is all-*unchanged*, § 4.4 forbids the write, and the assertion would
  read a file that was never created.
  *Breaks when:* the merge is implemented as a set-driven replacement over the
  whole of `DETECTED_FIELDS`, which contains `path`. That is the natural reading
  of "replace the detected half", and it rewrites every stored path to its
  resolved form on the first rescan — so the invariant exists to make § 4.3's
  `- {"path"}` subtraction testable rather than decorative.

- **INV-9** — `added` is compared as a **parsed instant**, never as a raw
  string.
  *Test:* `tests/test_registry.py::test_the_added_tie_break_compares_instants_not_text`
  — two records whose `added` values denote the same moment written as
  `2026-08-12T14:03:11Z` and `2026-08-12T15:03:11+01:00`, with the `Z` one
  **second** in file order, asserting the **`+01:00` record wins** (file order,
  per INV-7's equal-instant rule).
  **The fixture only discriminates because of the ordering.** "Neither wins on
  text order" named no observable outcome and could not be asserted: the two
  values are an equal instant, so the winner comes from the tie-break, and
  putting the lexically-larger `+01:00` value **first** is what makes a text
  comparison pick the other record and go red. Placed the other way round, a
  text comparison and the correct rule agree and the test proves nothing.
  *Breaks when:* two stamps use different RFC 3339 spellings. The format admits
  numeric offsets and fractional seconds, and `"2026-08-12T15:03:11+01:00"`
  sorts *after* `"2026-08-12T14:03:11Z"` lexically while denoting the **same**
  instant — so a string comparison silently picks the wrong duplicate-port
  winner. Records this item writes are always `Z`-spelled, which is exactly why
  the bug would not show up until a user hand-edited one.

- **INV-10** — No value read from the file or from a scan reaches a **merge
  report entry** without passing `_quoted`.
  *Test:* `tests/test_registry.py::test_no_merge_value_is_interpolated_without_the_clip`,
  mirroring the existing `test_no_file_sourced_value_is_interpolated_without_the_clip`
  at `tests/test_registry.py:463`.
  *Breaks when:* a hand-edited name containing a newline reaches the status bar
  or the log through the merge report — the defect LWSM-1078, LWSM-1102 and
  LWSM-1114 each closed at one call site, arriving on a new one. LWSM-1007's
  INV-8 is the same rule for writer refusals, which is a different surface with
  a different set of interpolated values.

## 6. Failure modes

- **A path cannot be resolved.** Falls back to lexical absolute, reported, merge
  continues (§ 4.2). `EACCES` and `ENAMETOOLONG` are the two that actually
  arrive on 3.13.
- **The scan returns nothing at all.** Treated as a complete scan reporting
  every in-scope project missing *only* if `timed_out` is false **and no
  `unlistable_roots` entry contains the record's resolved path** (§ 4.3). That
  is the case that matters: a run where every root was refused for permissions
  returns zero projects with `timed_out` false, and the `timed_out` test alone
  would flag the whole registry missing. **A per-entry skip suppresses
  nothing** — gating on `skipped` being empty is the reading § 4.3 rejects at
  length. **A registry is never blanked by a scan.**
- **The worker raises.** Caught inside `run()` and reported; without the
  catch-all, PySide6 swallows it, no signal is emitted, and Rescan stays
  disabled forever (§ 4.4).
- **The load that produced `stored` refused a row.** The merge runs and reports;
  the write is refused by LWSM-1007's gate. The user sees what a rescan *would*
  change without the file being touched.
- **The write fails.** LWSM-1007 § 6 owns this. The merged records stay in
  memory for the session and the user is told the write failed.

## 7. Tests

All of the above live in `tests/test_registry.py` beside the loader and writer
tests, whose fixtures they reuse (`write`, `one_good`). Every one is written red
first and watched failing before the code that satisfies it — `testing.md § 1`,
and the standing practice of this project's last six fix-passes.

The merge takes a `ScanResult`, so most of these need a **fake scan** rather
than a real one: `scanner.SupportsUnitLookup` is already the pattern this
project uses for injecting a test double, and `merge()`'s `now` parameter is
injected for the same reason (`testing.md § T1`). Two need a real file — INV-5 a
symlink, INV-8 a record stored under one. Every one uses `tmp_path` and
**carries no marker**, which is what makes `--fast` run them:
`scripts/local-ci.sh` runs `uv run pytest -q -m "not integration"` under
`--fast`, so a marker can only ever *exclude* a test. The project declares
exactly two markers, `gui` and `integration` (`pyproject.toml`), and none of
these spawns a process or binds a socket.

**Four of these are `pytest-qt` tests** rather than unit tests, because their
subject is the window: the button disabled while a merge is in flight and
re-enabled by the slot, the worker's catch-all, the summary's shape, and the
read-only gate blocking the write while the merge still reports. All four carry
the `gui` marker, which the project's other window tests already use, and
`--fast` runs them — `gui` is not `integration`.

**One test crosses into `tests/test_scanner.py`**: `ScanResult.unlistable_roots`
is a `scanner` change (§ 11), so the case asserting an unlistable root lands in
it while an ordinary per-entry skip does not belongs with the scanner's own
suite, not the registry's.

**What these tests do not prove**, said plainly: none exercises a real
concurrent rescan, and the worker's swallowed-exception case is tested by
raising deliberately rather than by reproducing PySide6's behaviour from
scratch. Both are honest limits of a unit suite.

## 8. Alternatives considered (and rejected)

- **Teach the scanner to distinguish "no port declared" from "could not
  read".** This is the better fix for § 4.1's limitation and it is not rejected,
  only deferred: it changes `DetectedProject`'s contract, and LWSM-1121 is
  already reopening the port sources. Recorded here so the next reader knows
  § 4.1's rule is a containment, not a conclusion.
- **Resolve paths at load time rather than merge time.** Rejected: it would
  rewrite what the user's own file says, and `load_projects`'s refusal of `..`
  exists precisely because normalising a path lexically is wrong when a
  component is a symlink.
- **Delete the losing record of a duplicate identity instead of keeping and
  flagging it.** Rejected: the loser holds a user-owned half no rescan can
  reconstruct, and ADR-0005 makes removal a user action. This was a genuine
  contradiction in the umbrella spec — INV-4 said "never deleted" while § 4.2
  said "refuses the later record" — and all three loop-1 lanes found it.
- **Persist the merge outcomes so per-row flags can be rendered.** Rejected on
  scope: it widens the on-disk format LWSM-1007 has just settled, for a
  presentation LWSM-1008 is already designing. § 4.4 records what the summary
  buys instead.
- **Have the merge parse `ScanResult.skipped`'s reason strings to tell a
  root-level skip from a per-entry one, instead of adding
  `unlistable_roots`.** Rejected: it makes the merge depend on the exact wording
  of another module's messages, which nothing pins and which a translation or a
  tidy-up would silently break — and the failure is invisible, because a merge
  that stops recognising `"cannot be listed"` simply stops suppressing and
  starts flagging real projects missing.
- **Infer the scan roots from the projects returned rather than passing
  `roots`.** Rejected because it is silently wrong: a root that legitimately
  contains zero projects would stop marking its records missing, and no test
  built from a populated fixture would ever catch it.

## 9. Out of scope

- **The record format, the writer and the read-only gate** —
  [LWSM-1007](LWSM-1007-registry-persistence.md). This spec calls that writer
  and adds no persistence of its own.
- **Keeping a backup of the registry** — LWSM-1039.
- **The first-run confirmation flow, and any per-row presentation of merge
  outcomes** — LWSM-1008. § 4.4 leaves the dialog to it.
- **`.env` / `docker-compose.yml` / `README.md` port sources and conflict
  reporting** — LWSM-1121.
- **Refusing Start for the later claimant of a duplicate port.** ADR-0005's
  duplicate-port clause is two halves — the row is flagged *port claimed by
  `<other project>`* **and "its Start is refused"** — and this item builds only
  the flag. There is no Start to refuse yet: the supervisor is P05, so the
  refusal has nowhere to live and no surface to report from. Recorded here
  because the ADR states it as one decision, and a reader comparing the two
  documents would otherwise find half of it silently missing rather than
  deferred. **P05 owns it**, and INV-7's flag is the input it will act on.
- **Acting on `hidden`, and suppressing a duplicate-identity row from the
  list** — untracked, and deferred together because they are one mechanism: a
  channel from the merge to `ProjectController` for "do not poll or show this
  record". This item preserves both facts and reads neither (§ 4.2, § 4.3). The
  visible cost is a hand-set `"hidden": true` doing nothing and a symlink
  duplicate showing twice. Deferred rather than invented here because the honest
  version also needs a way to *un*-hide, which is UI this item has no surface
  for.

## 10. What checks this

| Rule | What catches a breach |
|------|----------------------|
| INV-1 | `test_registry.py::test_a_rescan_never_writes_a_user_field` |
| INV-2 | `test_registry.py::test_unknown_does_not_erase_a_known_port` |
| INV-3 | `test_registry.py::test_a_timed_out_scan_marks_nothing_missing`, `::test_an_unlistable_root_marks_nothing_missing_under_it` |
| INV-4 | `test_registry.py::test_a_missing_project_is_kept_and_flagged` |
| INV-5 | `test_registry.py::test_two_paths_resolving_to_one_directory_are_one_project` |
| INV-6 | `test_registry.py::test_the_merge_report_is_bounded` |
| INV-7 | `test_registry.py::test_duplicate_ports_are_flagged_with_the_first_registered_winning`, `::test_a_record_without_added_loses_the_port_tie_break` |
| INV-8 | `test_registry.py::test_a_merge_does_not_rewrite_the_stored_path` |
| INV-9 | `test_registry.py::test_the_added_tie_break_compares_instants_not_text` |
| INV-10 | `test_registry.py::test_no_merge_value_is_interpolated_without_the_clip` |
| § 4.3 write trigger | `test_registry.py::test_an_all_unchanged_merge_does_not_write`, `::test_a_missing_only_merge_does_not_write` |
| § 4.4 first run writes even with zero projects | `test_registry.py::test_a_first_run_finding_nothing_still_creates_the_file` — the case where both sets are empty and the difference trigger says no |
| § 4.4 the slot owns the gate, not `merge()` | `test_mainwindow.py::test_a_row_refusing_load_blocks_the_rescan_write` (`gui`) — asserts the merge still ran and reported |
| § 4.3 `now()` returns a `Z`-suffixed RFC 3339 instant | `test_registry.py::test_the_production_now_stamps_a_value_the_loader_accepts` — round-trips the real callable through `load_projects`, so a naive stamp fails here rather than silently on the next start |
| § 4.4 the summary is counts per outcome | `test_mainwindow.py::test_the_rescan_summary_names_each_outcome_count` (`gui`) |
| § 4.3 scope of *missing* | `test_registry.py::test_a_project_outside_every_scan_root_is_not_missing` |
| § 4.3 containment resolves BOTH sides | `test_registry.py::test_a_symlinked_scan_root_still_scopes_missing` — a root symlinked to the directory the records resolve under; unresolved-vs-resolved makes *missing* unreachable |
| § 4.3 only an unlistable root suppresses *missing* | `test_registry.py::test_an_ordinary_per_entry_skip_does_not_suppress_missing`, `::test_an_unlistable_root_suppresses_missing_only_under_that_root` |
| § 4.3 *new*-record seeding | `test_registry.py::test_a_new_record_takes_its_name_from_the_scan_and_a_stamped_added` |
| § 4.3 *changed* on a first detection | `test_registry.py::test_a_first_detected_port_is_reported_as_changed` |
| § 4.2 an unresolvable path does not abort the merge | **nothing** — measured: non-strict `Path.resolve()` returns normally even where `exists()` raises `PermissionError`, so no fixture here produces the raise. The per-record handler stays as defence-in-depth; the test is not written rather than written green against a branch that never runs |
| § 4.4 Rescan disabled while in flight | `test_mainwindow.py::test_rescan_is_disabled_while_a_merge_is_in_flight` (`gui`) |
| § 4.4 the worker's catch-all | `test_mainwindow.py::test_a_raising_rescan_worker_re_enables_the_button` (`gui`) |
| § 4.1 per-field unknown table | **nothing** — only `port` has an unknown sentinel, so the other three rows assert an absence; INV-2 covers the one field that can break |
| § 4.2 duplicate still polled | **nothing** — a stated limitation (§ 9), not a rule; no channel carries the excluded set to the poller |
| § 4.3 `hidden` / `launcher_override` preserved but inert | **nothing** — deliberate; LWSM-1007's INV-3 round-trip proves they survive, and nothing reads them |
| § 4.1's stale-port limitation | **nothing** by design — it is the accepted cost of INV-2; removing it is the deferred scanner change in § 8 |
| § 9 Start refused for a duplicate-port claimant | **nothing** — ADR-0005's other half, deferred to P05 because no Start exists to refuse; INV-7's flag is the input it will act on |

**Twenty-eight rows, six of which say `nothing`.** All six are limits or
deliberate omissions rather than defects: § 4.1's per-field unknown table, three
rows of which assert an *absence* of a sentinel and so have nothing to break;
§ 4.2's duplicate row still being polled; `hidden` / `launcher_override` being
preserved but inert; § 4.1's stale-port cost, accepted as INV-2's price; and the
Start refusal, which has no Start to refuse until P05. **Only the last carries a
roadmap owner, and it is the only one that is a gap rather than a cost** — the
other four are § 9 deferrals with their price stated.

*Command, run against this file:*

```
awk '/^\| Rule \| What catches/{f=1;next} f&&/^\|---/{next} \
     f&&/^\| /{n++; if(/^\| INV-/)i++; if(/\*\*nothing\*\*/)z++} \
     f&&!/^\| /{exit} END{print "rows="n" inv="i" nothing="z}' \
  docs/specs/LWSM-1131-rescan-merge.md
```

→ `rows=28 inv=10 nothing=6`, against `grep -c '^- \*\*INV-'` → `10`. So the
table and § 5 enumerate the same ten invariants, and the eighteen non-`INV` rows
are the six `nothing` limits plus twelve § 4 rules that carry a test without
carrying an invariant of their own.

## 11. Cross-doc impact

- **`docs/decisions/0005-registry-and-rescan.md`** — gains a clause for § 4.1
  (unknown is not changed) and one for § 4.3 (a timed-out or partially-skipped
  scan marks nothing missing). Both are decisions the ADR did not make;
  recording them in the spec alone would leave the ADR contradicting the shipped
  behaviour.
- **`ROADMAP.md`** — this bullet added 2026-08-12; LWSM-1007's narrowed.
- **`CLAUDE.md § Module map`** — `registry.py`'s entry gains `merge()` and its
  `TYPE_CHECKING`-only `ScanResult` import (§ 13); `scanner.py`'s gains
  `ScanResult.unlistable_roots`; `mainwindow.py`'s gains the Rescan button, its
  worker, and the fact that the window holds the startup `LoadResult` for the
  slot to pass to `save_projects`.
- **`src/lwsm/scanner.py` — this item adds a field.** `ScanResult` gains
  `unlistable_roots: tuple[Path, ...]`, populated where `scan()` already notes a
  root it could not list (§ 4.3). It is the only `scanner` change here, and
  `tests/test_scanner.py` gains a case asserting an unlistable root appears in
  it while an ordinary per-entry skip does not.
- **`docs/specs/LWSM-1006-scanner-detection.md`** — specifies `ScanResult`'s
  three fields. Adding a fourth makes that enumeration incomplete. **That spec is
  accepted with its gate behind it**, so the correction is filed rather than made
  here; it is additive, so nothing it states becomes false.
- **`docs/known-issues.md`** — known-issue-025 closed by INV-5, having been
  re-pointed here from LWSM-1007.
- **`CHANGELOG.md`** — an `[Unreleased] ### Added` entry.
- **`docs/design.md § Components`** — the Rescan flow already describes this
  behaviour; check it still matches once § 4.3 ships.

## 12. Cold-eyes loop log

| Loop | Date | Lanes | CRIT | HIGH | MED | LOW | Outcome |
|------|------|-------|------|------|-----|-----|---------|
| 0-split | 2026-08-12 | **none — no reviewer was dispatched** | — | — | — | — | **Provenance row, not a review.** This document is the merge half of *LWSM-1007 — Persist the registry, and merge a rescan without discarding user edits*, split out on 2026-08-12 after that spec reached `review-contract`'s `--max-loops 3` cap without converging. The format-and-writer half kept the LWSM-1007 id and path. The umbrella's three loops produced 34 findings, all verified, all fixed, none ever resurfacing — and its own loop-3 row diagnosed the cap as **size and scope** rather than an unsettled contract: 540 → 979 lines with the count flat at 12 / 10 / 12 and each loop clustering in a different region. The user chose the split on 2026-08-12 over accepting at the cap or running a fourth loop. **No review is inherited.** Those loops ran against a 979-line document that no longer exists; this part runs the gate from loop 1 on its own bytes, and so does LWSM-1007. Invariants renumbered from 1 with the mapping in § 3. |
| 2 | 2026-08-13 | 3 (general-purpose, strong model), brief byte-identical to loop 1, no prior-loop findings disclosed | Q1 ×2 · Q2 ×3 · Q3 ×3 · Q4 ×1 | **9 verified, 0 dismissed, 9 fixed. Nothing from loop 1 resurfaced.** **Five of the nine were loop 1's own collateral**, the same proportion part LWSM-1007 saw, and the honest headline of this run: § 6 still carried the blanket-`skipped` rule that § 4.3 now spends five paragraphs rejecting *and cited § 4.3 as its authority*; INV-3 still named a test asserting the rejected behaviour, which contradicted its own § 10 row; `unlistable_roots` repeated the unresolved-containment hazard I had just fixed for `roots`, on the branch that only fires under permission denial; and INV-9's *Breaks when* called two literals an "earlier instant" when the same invariant's test correctly calls them the same moment. My 4b sweep found none of these — it swept the subjects I had edited and not the sections that restate them. **One finding is a genuine design defect that predates every fix:** § 4.3 said the merge "replaces `DETECTED_FIELDS - {\"path\"}`" unqualified, and `port` is in that set — so the mechanism sentence, implemented literally, writes `None` over a stored `3000` on the first unreadable launcher, breaking INV-2 and the *not re-observed* outcome stated a few lines above it. That is the class this gate is actually worth running for: correct code, faithful to a wrong contract, tests green. **Two clauses could not be built as written.** The summary was specified as counts per outcome while `merge()` returned only records and free-text reasons, so the only available implementation was substring-matching the report — the exact wording-dependence § 8 rejects for `skipped`; `merge()` now returns a `MergeResult` carrying `counts`, and the seven outcomes have labels and a fixed order. And the write-trigger tests were filed in `test_registry.py` while § 4.4 puts the write in the GUI slot, so they had no write to observe. **One finding was mine, from measurement:** I had cited the `pathlib`-on-3.13 trap as covering `Path.resolve`, and it does not — measured, non-strict `resolve()` returns normally where `exists()` raises `PermissionError`, so § 10's unresolvable-path row is now a `nothing` naming a branch no fixture here reaches, rather than a test written green against dead code. 814 → 855 lines. **No loop 3 —** see the row above and the user's standing decision to cap. |
| 1 | 2026-08-13 | 3 (general-purpose, strong model), identical brief, four-question form | Q1 ×2 · Q2 ×2 · Q3 ×4 · Q4 ×2 | **10 verified, 0 dismissed, 10 fixed.** First cold read of this document ever; no review inherited from the umbrella. **The sharpest finding kills a feature silently.** § 4.3 suppressed the *missing* check whenever `ScanResult.skipped` was non-empty — but `scan()` calls `note()` for entirely ordinary things: `"is not a directory"`, `"no launcher matched"`, `"already scanned under another root"`, `"is this application's own directory"`. **One stray file in a scan root makes `skipped` non-empty**, so ADR-0005's *missing* outcome would never have fired on any populated machine while a clean fixture passed. Two lanes found it; the call sites were then read directly to confirm. `skipped` is `tuple[str, ...]` and gives the merge nothing to discriminate on, and parsing another module's message wording is rejected in § 8 — so **`ScanResult` gains `unlistable_roots`**, and only a root that could not be listed suppresses the check, and only for records under it. That is § 4.1's observation-of-absence rule applied to roots. **A second silent-disable, same shape:** containment compared a *resolved* stored path against an *unresolved* root, and `scan()`'s docstring says a symlinked root is "followed, deliberately" — so a symlinked scan root put every record out of scope and *missing* never fired. Both sides now resolve. **The gate was wired to a function that cannot reach it:** § 4.4 said the merge "passes the `LoadResult | RegistryError` it was given to `save_projects`", but § 4.3's pinned signature has no such parameter and § 4.4 itself puts the write on the GUI thread while the merge runs on the pool — so an implementer would either widen a signature the spec calls load-bearing or write from the worker. The **slot** owns it now. **Three clauses had no observable outcome (Q4 ×2 and one Q3).** INV-9's fixture used two *equal* instants and asked that "neither wins on text order", which names nothing and could not be asserted — the equal-instant tie-break is now defined (file order) and the fixture orders the values so a text comparison goes red, which it would not have done the other way round. INV-5 and INV-8 both asserted on "the written file" while § 4.4 forbids the write in exactly their scenarios — *duplicate identity* changes no field, so INV-5 reads a file that was never created; INV-8's fixture now carries a changed port to make the write fire. And the Rescan summary's *content* was unspecified, admitting both `"Rescan complete"` and an unbounded `"; ".join(reasons)` — now counts per outcome, with entries going to the log. **`now()` was typed `Callable[[], str]` and never pinned**, so the obvious `datetime.now().isoformat()` produces a naive stamp that LWSM-1007's reader drops — every record the app created would lose its `added` on the next load, leaving INV-7's tie-break with nothing to compare on exactly those records. **§ 13 claimed this item "adds no import at all"**, but `merge()` lives in `registry.py` and its signature names `ScanResult` — the cycle LWSM-1007 § 4.1 measured. Resolved by measurement rather than by argument: `registry.py` already carries `from __future__ import annotations` and `merge()` names no `scanner` symbol at runtime, so a `TYPE_CHECKING`-only import imports cleanly where a runtime one raises. **One finding came from reading ADR-0005 rather than from a lane:** its duplicate-port clause is two halves — flag the row **and** refuse its Start — and this document adopted only the flag without deferring the other, so half an ADR decision was silently missing rather than owned. Now deferred to P05 in § 9, with a `nothing` row naming it. **Collateral swept back into LWSM-1007:** its § 4.1 justified the `LauncherKind` move on the *type annotation*, which `from __future__ import annotations` makes false — the real reason is that § 4.2's loader validates against the enum at runtime. 679 → 814 lines. |

## 13. Resource cost

- **Memory.** The merge holds two dictionaries keyed by resolved path plus the
  report — O(n) in the number of projects, against a file whose size
  `MAX_FILE_BYTES` (1 MiB) already caps on read.
- **Named cap on the report.** The merge report reuses the loader's
  `MAX_REASONS` (100) discipline with its always-reported suppressed tail
  (INV-6). Without it a hostile registry turns one rescan into tens of thousands
  of log records — the exact shape LWSM-1115 measured at 28.7 MB through a
  handler that rotates at 1 MiB.
- **Time.** One `scan()` per Rescan, already budgeted by LWSM-1006's deadline,
  plus an O(n) merge. Both run on a `QThreadPool` worker so neither blocks the
  GUI thread (§ 4.4).
- **Disk.** None of its own — the write is LWSM-1007's, and only when the record
  set changed.
- **New external dependencies: none. Two imports, both standard library, and
  one of them must be `TYPE_CHECKING`-only.** `merge()` lives in `registry.py`
  (§ 11) and its signature names `ScanResult`, a `scanner` symbol — so a
  **runtime** `from lwsm.scanner import ScanResult` closes the cycle LWSM-1007
  § 4.1 measured and the application stops importing. Measured here on this
  tree, with nothing else changed:

  ```
  if TYPE_CHECKING: from lwsm.scanner import ScanResult   -> both modules import, exit 0
  from lwsm.scanner import ScanResult                     -> ImportError (circular)
  ```

  The guarded form is safe because `registry.py` already carries
  `from __future__ import annotations`, so the annotation is never evaluated,
  and **`merge()` needs no `scanner` symbol at runtime** — it reads attributes
  off the objects it is handed and never names a class. `datetime` is a runtime
  import and arrives with LWSM-1007's `added` parse; this item reuses it to
  *compare* instants (INV-9) and adds nothing. `pyproject.toml` does not change.
  *Command:* `grep -nE "^(import|from) " src/lwsm/registry.py`.
