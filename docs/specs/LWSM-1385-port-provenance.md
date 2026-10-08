<!-- ants-spec-format: 1 -->
# LWSM-1385 — Save where a project's port came from, and show any disagreement on its row

**Status:** accepted (2026-10-02).
**Kind:** feature.
**Source:** ROADMAP LWSM-1385 (in-session-2026-10-02, split from LWSM-1121).
**Blocked by:** LWSM-1121 (shipped 2026-10-02).
**Amends:** [LWSM-1007 § 4.2](LWSM-1007-registry-persistence.md#42-the-file-format)'s
rule that a detected port's provenance is not persisted, and its § 9 deferral of
the same.

When two files in a project disagree about its port, the project's
row says so every time the app opens, not only in the log after a scan.

## 1. Goal

After this ships, `projects.json` remembers which file each project's port was
read from, and which other files named a different port. The main window shows
a plain-text marker in the port cell of any project whose sources disagree, and
the detail — which file won, which disagreed — is in that cell's tooltip and in
the row's accessible description. All of it survives a restart, so a conflict
stays visible until a rescan finds it gone.

## 2. Problem

1. **The conflict is found and then forgotten.** `scanner._settle_port` returns
   the winning `PortFinding` and every differing one, and
   `scanner.DetectedProject.port_conflicts` carries them. But
   `registry._detected_half_applied` stores only `found.port.port`, an `int`,
   and the new-project branch of `registry.merge` does the same. The only
   trace left is the "port sources disagree" line in the scan notes.
2. **The window reads stored records only.** `controller.RowView` is built from
   `ProjectRecord` in `controller.ProjectController.rows`, and the app scans
   only on first run or Rescan. So even an in-memory copy of the provenance
   would vanish on the next start.
3. **LWSM-1007 § 4.2 forbids the fix as written.** It says the format "defines
   no key for `rule` or `source`", and its § 9 lists persisting provenance as
   deferred. This spec is that deferred item.

## 3. Scope decisions (agreed with the user)

- **A conflict is shown on the project's row, not only in the scan notes**
  — the user, 2026-10-02 (LWSM-1121 note).
- **The source and the conflicts are saved in `projects.json`** (option (a) on
  LWSM-1385), rather than kept in memory until restart — the user, 2026-10-02.
- **The following were decided by the author, not the user**, and are recorded
  so they are not re-argued:
  - The marker shows only when no `port_override` is set. An override is the
    user's own answer to which port is right, so warning about files they have
    already overruled is noise.
  - A rescan where only the provenance changed is not counted as *changed* in
    the rescan summary. Otherwise the first rescan after upgrading would report
    every project with a port as changed.
  - The rule is written to the file by its enum **name**, lower-cased, because
    `PortRule`'s value is English display text that may be reworded.

## 4. Design

### 4.1 Where the types live

`PortRule` and `PortFinding` move from `scanner.py` to `registry.py`, and
`scanner.py` imports them from there. This is LWSM-1007 § 4.1's move of
`LauncherKind`, for the same reason: `ProjectRecord` now holds them and the
loader must check a rule against the enum at run time, while `scanner.py`
already imports from `registry.py`. A runtime import the other way closes the
cycle § 4.1 measured. Both names stay importable from `lwsm.scanner`, so
existing tests and `tests/scanner_fixtures.py` are unchanged.

`registry.DetectedPort` (the merge's narrowed view of a finding) widens to the
three fields, `port`, `rule` and `source`, as read-only properties.
`registry.ScannedProject` gains a read-only `port_conflicts` property returning
a sequence of `DetectedPort`.

### 4.2 The record

```python
# registry.py — ProjectRecord gains two fields, both classified DETECTED.
port_from: PortFinding | None = None
port_conflicts: tuple[PortFinding, ...] = ()

DETECTED_FIELDS = frozenset(
    {"path", "port", "port_from", "port_conflicts", "kind", "argv", "unit"}
)
```

`port_from` is the finding the stored `port` came from. **Its `port` always
equals the record's `port`**: it is `None` whenever `port` is `None`, and the
loader and the merge are the only code that build records (`ProjectRecord(` and
`replace(…, port=…)` occur only in `registry.py`). The duplicated number is
deliberate. It is what lets the loader detect provenance gone stale under a
build that predates this item (§ 6).

`port_conflicts` is non-empty only when `port_from` is set, and no element's
`port` equals `port_from.port`. The scanner produces at most four:
`_settle_port` ranks at most five findings (a launcher port or a framework
default, two env files, one compose file, the README), and the winner and the
framework default are never conflicts.

Classified detected, so `merge_imported` clears both on an imported record
through `_detected_half_cleared` with no change there, and LWSM-1007's INV-1
keeps the classification complete. `export_profile` writes them as stored.

### 4.3 The file format

Two optional keys per project object, written after `port`:

```json
{
  "path": "/srv/project-a",
  "name": "Project A",
  "port": 3000,
  "port_from": {"port": 3000, "rule": "env_file", "source": ".env"},
  "port_conflicts": [
    {"port": 4000, "rule": "readme", "source": "README.md"}
  ],
  "port_override": null
}
```

`schema_version` stays `1`, under LWSM-1007 § 4.2's compatibility rule and its
INV-5: both keys are optional, and a file without them loads as before. An
older build keeps them through `ProjectRecord.unknown` (LWSM-1218) and writes
them back untouched.

| Key | Type | Default when absent | Refused when |
|---|---|---|---|
| `port_from` | object `{port, rule, source}` or `null` | `null` | not an object; a key missing or extra; `port` not an int in `DECLARED_PORT_RANGE`; `rule` not a lower-cased `PortRule` name; `source` not a non-empty string of at most `MAX_DISPLAY_NAME_CHARS` characters that `is_writable_text` accepts; **or `port` differs from the record's `port`** |
| `port_conflicts` | array of the same object | `[]` | not an array; more than `MAX_PORT_CONFLICTS = 8` elements; any element refused by `port_from`'s rules (less the last); any element's `port` equal to `port_from.port`; **or non-empty while `port_from` is absent**. A refused `port_from` drops it too, under `port_from`'s reason and with none of its own |

A refusal follows LWSM-1007 § 4.2's blanket rule: the field takes its default
and a reason is reported. Both are detected fields, so a refusal never adds to
`LoadResult.user_fields_refused` and never blocks a profile export; the
next scan re-derives them. `port_conflicts` is refused whole, not element by
element, because a partial list would claim fewer disagreements than the scan
found.

`MAX_PORT_CONFLICTS` is twice the scanner's ceiling, so a later source added to
`_settle_port` does not silently start losing the field.

### 4.4 The merge

`registry._detected_half_applied` sets the two new fields explicitly, beside
`port`, and excludes them from its generic `getattr` copy as it excludes
`path`: `ScannedProject` has no `port_from` attribute, so the generic copy
would raise.

| Scan result | `port` | `port_from` | `port_conflicts` |
|---|---|---|---|
| `found.port` is set | `found.port.port` | `found.port` | `found.port_conflicts` |
| `found.port` is `None`, `read_cleanly` | `None` | `None` | `()` |
| `found.port` is `None`, not `read_cleanly` | kept | kept | kept |

The third row keeps the old provenance with the old port, so the pair still
describes each other. The new-project branch of `registry.merge` takes the
first row's values. Each value stored is a `registry.PortFinding` built from
the scan's three fields, so a fake scan in a test cannot leave a foreign type
in a record.

**A provenance-only difference is not *changed*.** `merge` compares the old and
new record with `port_from` and `port_conflicts` set aside when deciding the
`CHANGED` and `UNCHANGED` outcomes; any other detected field differing still
counts. The record is still replaced, so `MainWindow._apply_merge` saves the
new provenance. The
`OVERRIDE_DIFFERS` and `NOT_REOBSERVED` tests already read `port` alone and do
not change.

### 4.5 The row

`controller.RowView` gains `port_from` and `port_conflicts`, copied from the
record in `ProjectController.rows`, and `port_overridden: bool`
(`record.port_override is not None`).

`mainwindow.ProjectRow`:

- **The port cell.** When `port_conflicts` is non-empty and the port is not
  overridden, the cell reads `port 3000 (sources differ)`, translated, with the
  number substituted by `str.replace` as `port_text` does today. Since
  LWSM-1393 the marker is on a second line under the port. Otherwise it is
  `port_text`'s output, unchanged. The marker is text, so the row's accessible
  name, which is built from the rendered cells, carries it with no extra code.
- **The detail.** The port cell's tooltip and the row's accessible description
  carry one sentence per finding: `From .env (a PORT setting in an env file).`
  then, for each conflict, `README.md says 4000.` When the port is overridden
  the first sentence is `You set this port.` followed by the detected port's
  sentence. Empty when `port_from` is `None` and nothing is overridden. The rule
  words come from a translated mapping in `mainwindow.py`, as `state_word` does
  for statuses, not from `PortRule.value`.
- **Every `source` passes through `configfile.display_text`**, and the tooltip
  through `_plain_tooltip`, at render time, because the file is hand-editable
  and the loader checks only length and encoding.

Nothing important is hover-only (`design-accessibility.md`): the disagreement
is visible text in the cell; the tooltip and description add which files.

## 5. Invariants

- **INV-1** — A record written with `port_from` and `port_conflicts` set loads
  back equal to the record written.
  *Test:* `tests/test_registry.py::test_write_then_load_round_trips`, extended
  with both fields populated.
  *Breaks when:* the writer omits a key, the loader returns a list for
  `port_conflicts`, or `rule` is written by value and read by name.

- **INV-2** — A `port_from` whose `port` differs from the record's `port` is
  dropped and reported, and `port_conflicts` is dropped with it.
  *Test:* `tests/test_registry.py` — a file with `"port": 5000` and
  `"port_from": {"port": 3000, …}` loads with `port_from is None`,
  `port_conflicts == ()`, and a reason naming `port_from`.
  *Breaks when:* the loader checks the object's shape but not its port, which
  is the case an older build produces by updating `port` and carrying the
  provenance through `unknown` unchanged.

- **INV-3** — Each refusal in § 4.3's table drops that field (a refused
  `port_from` also drops `port_conflicts`), adds exactly one reason, and
  leaves `user_fields_refused` empty.
  *Test:* `tests/test_registry.py`, parametrised over one fixture per refusal
  cell, including nine conflicts and a conflict equal to the winning port.
  *Breaks when:* a refusal raises, drops the row, or is recorded as a
  user-field refusal and so blocks a profile export (LWSM-1215).

- **INV-4** — The merge stores provenance per § 4.4's three rows.
  *Test:* `tests/test_registry.py`, one case per row, using the existing fake
  scan; the third asserts the stored `port`, `port_from` and `port_conflicts`
  are all the old values.
  *Breaks when:* `_detected_half_applied` copies `found.port` and
  `found.port_conflicts` without the third row's qualifier, which writes
  `None` provenance beside a kept port.

- **INV-5** — A rescan that changes only `port_from` or `port_conflicts` counts
  the project as unchanged, and one that changes `port` still counts it as
  changed.
  *Test:* `tests/test_registry.py`, two cases, asserting `counts[CHANGED]`
  and `counts[UNCHANGED]`.
  *Breaks when:* `merge` compares whole records for either outcome.

- **INV-6** — The port cell shows the marker exactly when `port_conflicts` is
  non-empty and the port is not overridden.
  *Test:* `tests/test_mainwindow.py`, four cases (conflicts × override),
  asserting the cell text and that the row's accessible name contains it.
  *Breaks when:* the marker tests `port_from` instead of `port_conflicts`, or
  ignores the override.
  *Amended by:* [LWSM-1038 § 4.5](LWSM-1038-confirmed-ports.md#45-the-row).

- **INV-7** — A `source` holding a control character reaches the tooltip and
  the accessible description with it replaced by U+FFFD, and markup in it is
  shown as text.
  *Test:* `tests/test_mainwindow.py`, a record whose `port_from.source` is
  `"<b>x</b>\n.env"`.
  *Breaks when:* the row builds the detail from `source` without
  `display_text`, or sets the tooltip without `_plain_tooltip`. This is the
  trust boundary: `projects.json` is hand-editable, so `source` is untrusted
  text on its way to a widget.

- **INV-8** — `PortRule` and `PortFinding` are defined in `registry.py`, and
  `registry.py` imports nothing from `lwsm.scanner` at run time.
  *Test:* `tests/test_layering.py`, the existing AST check of the import
  direction, plus assertions that `scanner.PortFinding is
  registry.PortFinding` and `scanner.PortRule is registry.PortRule`.
  *Breaks when:* the types stay in `scanner.py` and `registry.py` imports them,
  which closes LWSM-1007 § 4.1's cycle.

## 6. Failure modes

- **An older build edits the file.** It keeps both keys as unknown and writes
  them back, but its merge can change `port` underneath them. INV-2 catches
  that on the next load here: the stale `port_from` and its conflicts are
  dropped and reported, and the row shows no marker until a rescan.
- **A hand edit breaks a key.** § 4.3's refusals apply; the row loses its
  detail until the next rescan. Nothing else is affected.
- **The scanner later reports more than eight conflicts.** The field is refused
  on load, so the marker disappears after a restart. `MAX_PORT_CONFLICTS` is set
  at twice today's ceiling so that this needs a deliberate scanner change.
- **First run after upgrading.** Stored records carry no provenance, so no row
  shows a marker until the user rescans. Accepted: the scan is one click, and
  inventing provenance for a stored port would be a guess.

## 7. Tests

The cases are named with each invariant in § 5, all in existing files:

- `tests/test_registry.py` — INV-1, INV-2, INV-3, INV-4, INV-5.
- `tests/test_mainwindow.py` — INV-6, INV-7.
- `tests/test_layering.py` — INV-8.
 Each new test is seen to fail against the code
before its rule is written, by breaking that rule once in a scratch copy per
`docs/standards/testing-overrides.md` § T9.

## 8. Alternatives considered (and rejected)

- **Keep provenance in memory only** (option (b) on LWSM-1385). Rejected by the
  user: a warning that vanishes on restart is the "only in the log" outcome
  already turned down.
- **Store only `rule` and `source`, not the port again.** Avoids the duplicated
  number, but then a `port` changed by an older build or by hand keeps a source
  that no longer describes it, and nothing can tell. The duplicate is checked
  on every load, so it cannot silently disagree.
- **Store the rule by value**, as `kind` is. `PortRule`'s values are English
  sentences meant for display; rewording one would make every saved file's rule
  unreadable.
- **A coloured or icon marker.** Colour alone tells a screen reader nothing,
  and the row's accessible name is built from rendered text by design.
- **Show the marker even when overridden.** Rejected (author's call, § 3): the
  override already settles which port is used.

## 9. Out of scope

- Showing provenance anywhere but the row: the per-project settings and the
  first-run dialog — deferred; not yet queued.
- Re-scanning automatically at start-up so provenance is fresh — deferred; not
  yet queued.
- The ES-import hop LWSM-1121's evidence suggested — shipped separately as the
  scanner's import walk (`scanner._walk_imports`).

## 10. What checks this

| Rule | What catches a breach |
|------|----------------------|
| INV-1 | `tests/test_registry.py::test_write_then_load_round_trips` |
| INV-2 | `tests/test_registry.py`, the stale-`port_from` case |
| INV-3 | `tests/test_registry.py`, the parametrised refusal cases |
| INV-4 | `tests/test_registry.py`, the three merge cases |
| INV-5 | `tests/test_registry.py`, the two outcome-count cases |
| INV-6 | `tests/test_mainwindow.py`, the four marker cases |
| INV-7 | `tests/test_mainwindow.py`, the hostile-source case |
| INV-8 | `tests/test_layering.py` |
| § 4.2 both new fields are DETECTED | LWSM-1007's `tests/test_registry.py::test_every_record_field_is_classified` checks each field is in one set; **nothing** checks it is the detected one |
| § 4.5 the detail's wording | **nothing** — copy, reviewed by reading |

## 11. Cross-doc impact

- `docs/specs/LWSM-1007-registry-persistence.md` § 4.2, § 9 and § 10: the
  provenance clause, deferral and row point here.
- `docs/specs/LWSM-1006-scanner-detection.md` § 4: `PortRule` and
  `PortFinding` now live in `registry.py`; "the value is what the UI shows" no
  longer holds.
- `docs/claude/module-map.md`: `PortRule` and `PortFinding` move from the
  scanner entry to the registry entry.
- `CHANGELOG.md`: one *Added* entry.

## 12. Cold-eyes loop log

Rows live in `../reviews/LWSM-1385-port-provenance-loop-log.md`.
