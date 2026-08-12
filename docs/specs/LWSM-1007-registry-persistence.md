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
result survives a restart. After this ships, a user can rename a project, set
a port override, press **Rescan**, and find both edits still in force with a
visible account of what the scan changed.

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

**Three** entries in `docs/known-issues.md` name LWSM-1007 as their owner —
known-issue-025 (identity), -033 (test weaknesses) and -034 (the unpinned
constants), each closed by a section below.

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

`path` is in the detected half because it *is* the identity and a scan is what
observes it; nothing may rewrite it (§ 4.4). `added` is a user-owned timestamp
because ADR-0005 makes it the duplicate-port tie-break, and a rescan must not
be able to reorder that.

The merge is then "replace the detected half, keep the user half" rather than
a field-by-field copy, and INV-1 makes a field that belongs to neither set a
failing build. This is the same reasoning `scanner.DetectedProject`'s docstring
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
      "added": "2026-08-12T14:03:11Z",
      "detected_missing": false,
      "port_last_detected": 3000
    }
  ]
}
```

Every key except `path` and `name` is optional on read. `port_last_detected`
is what makes § 4.3's rule expressible: it records the last port a scan
actually observed, so "the scan stopped seeing a port it used to see" is a
statement the file can hold across restarts rather than one lost with the
process.

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
known-issue-025. The merge refuses the later record and reports it.

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

**The target is checked before it is replaced.** If `path` exists and is not a
regular file, the write is refused rather than performed — `os.replace` onto a
symlink replaces the *symlink*, silently converting a user's deliberate
indirection into a plain file. This is deliberately narrower than
`applog._require_private_regular_file`, for the reason `_read_bounded` already
records: a config file may reasonably be hard-linked or installed for the user,
so ownership and link count are not demanded.

The serialised output is bounded by the same `MAX_FILE_BYTES` the reader
enforces; a registry that would exceed it is refused with a reason rather than
written and then found unreadable on next start.

### 4.6 Merge outcomes

ADR-0005's four, plus the two this spec adds. Each produces a report entry;
none mutates silently.

| Outcome | Condition | Effect |
|---|---|---|
| **new** | scanned, not stored | added, flagged *new* |
| **unchanged** | detected halves equal | nothing |
| **changed** | detected halves differ, both known | detected half updated, change listed |
| **missing** | stored, absent from a **complete** scan | kept, flagged *missing*, never deleted |
| **not re-observed** | stored known, scan unknown (§ 4.3) | stored value kept, flagged |
| **override differs** | a user override exists for a field that moved | override stays in force, row flagged |

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

`MainWindow` gains a **Rescan** button that runs the scan, calls the merge,
writes the file, and puts a one-line summary in the status bar
(`MainWindow.set_status_message` already exists). The per-row flags render as
part of the existing `RowView`.

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

- **INV-2** — A merge never writes a user-owned field.
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
  both persist.
  *Test:* `tests/test_registry.py::test_two_paths_resolving_to_one_directory_are_one_project`,
  using known-issue-025's fixture — a symlinked root beside the real one.
  *Breaks when:* a user adds a project by a symlinked path having already
  added it by its real one. The existing duplicate check cannot catch this:
  it compares unresolved paths, so both records are distinct to it.

- **INV-7** — A write that fails at any point leaves the previous file intact
  and parseable.
  *Test:* `tests/test_registry.py::test_a_failed_write_leaves_the_old_file_intact`
  — failure injected after the temporary file is written and before
  `os.replace`.
  *Breaks when:* the disk fills, or the process dies mid-write.

- **INV-8** — Anything written reloads to an equal record set.
  *Test:* `tests/test_registry.py::test_write_then_load_round_trips`, over a
  record with every field populated, including a name needing JSON escaping.
  *Breaks when:* a field is serialised in a form `load_projects` rejects — a
  `Path` written as a repr, a `LauncherKind` written as an enum rather than
  its value.

- **INV-9** — The written file is a regular file with mode `0600`, and a
  target that is not a regular file is refused rather than replaced.
  *Test:* `tests/test_registry.py::test_the_written_file_is_private` and
  `::test_a_non_regular_target_is_refused` (a FIFO at the config path).
  *Breaks when:* the process umask is permissive, or a symlink is planted at
  the config path.

- **INV-10** — The merge report is bounded in both entry length and entry
  count, and a suppressed tail is always counted.
  *Test:* `tests/test_registry.py::test_the_merge_report_is_bounded`.
  *Breaks when:* a registry with tens of thousands of malformed records is
  merged — the shape LWSM-1115 already fixed for load reasons, arriving on a
  second surface.

- **INV-11** — Two records with the same effective port are both flagged, the
  earliest `added` wins, and the later claimant names the winner.
  *Test:* `tests/test_registry.py::test_duplicate_ports_are_flagged_with_the_first_registered_winning`.
  *Breaks when:* a user sets an override equal to another project's declared
  port.

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
  every project missing *only* if `timed_out` is false; otherwise INV-4 applies.
  A registry is never blanked by a scan.

## 7. Tests

All of the above live in `tests/test_registry.py` beside the existing loader
tests, which the merge tests reuse the fixtures of (`write`, `one_good`).
Every one is written red first and watched failing before the code that
satisfies it — `testing.md § 1`, and the standing practice of this project's
last six fix-passes.

Three of the thirteen need a real filesystem rather than a fake: INV-6 needs a
symlink, INV-7 needs an injected failure, INV-9 needs a FIFO and a mode check.
They use `tmp_path` and are marked so `--fast` keeps them; the marker goes on
the test, never on the file (`CLAUDE.md`).

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
- **Write the file on every change instead of on rescan and exit.** Rejected as
  premature: the registry changes at human speed, and a write per keystroke
  buys durability nobody asked for at the cost of a debounce nobody has
  specified.
- **Resolve paths at load time rather than merge time.** Rejected: it would
  rewrite what the user's own file says, and `load_projects`'s refusal of `..`
  exists precisely because normalising a path lexically is wrong when a
  component is a symlink.

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
| INV-9 | `test_registry.py::test_the_written_file_is_private`, `::test_a_non_regular_target_is_refused` |
| INV-10 | `test_registry.py::test_the_merge_report_is_bounded` |
| INV-11 | `test_registry.py::test_duplicate_ports_are_flagged_with_the_first_registered_winning` |
| INV-12 | `test_registry.py::test_a_pre_existing_file_still_loads` |
| INV-13 | `test_registry.py::test_no_merge_value_is_interpolated_without_the_clip` |
| § 4.5 step 4 (directory `fsync`) | **nothing** — a durability claim a unit test cannot falsify without power loss; the call site is reviewed, not tested |
| § 6 concurrent writers | **nothing** — out of scope by § 9; last writer wins and no reader sees a half-file |
| § 4.3's stale-port limitation | **nothing** by design — it is the accepted cost of INV-3; removing it is the deferred scanner change in § 8 |

**Sixteen rows, three of which say `nothing`** — the honest error budget
`spec-format.md § 0` asks for. All three are limits rather than defects: a
durability call no unit test can falsify, a scope exclusion, and the accepted
cost of INV-3. None carries a roadmap id, because none is a gap to close.

*Command, run against this file:*

```
awk '/^\| Rule \| What catches/{f=1;next} f&&/^\|---/{next} f&&/^\| /{n++} \
     f&&!/^\| /{exit} END{print n}' docs/specs/LWSM-1007-registry-persistence.md
```

→ `16`, and the same awk filtered on `**nothing**` → `3`. Thirteen `INV-`
rows against thirteen invariants defined in § 5
(`grep -c '^- \*\*INV-'` → `13`), so the table and § 5 enumerate the same set.

## 12. Cross-doc impact

- **`docs/decisions/0005-registry-and-rescan.md`** — gains a clause for § 4.3
  (unknown is not changed) and one for § 4.6 (a timed-out scan marks nothing
  missing). Both are decisions the ADR did not make; recording them in the
  spec alone would leave the ADR contradicting the shipped behaviour.
- **`CLAUDE.md § Module map`** — `registry.py`'s entry gains the writer and the
  merge.
- **`docs/known-issues.md`** — known-issue-010 and -013 re-routed to P04
  (§ 9); known-issue-025, -033 and -034 closed by this item.
- **`CHANGELOG.md`** — an `[Unreleased] ### Added` entry.
- **`docs/design.md § Components`** — the Rescan flow already describes this
  behaviour; check it still matches once § 4.6 ships.

## 13. Cold-eyes loop log

| Loop | Date | Lanes | CRIT | HIGH | MED | LOW | Outcome |
|------|------|-------|------|------|-----|-----|---------|
