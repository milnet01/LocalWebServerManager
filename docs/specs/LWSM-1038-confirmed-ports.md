<!-- ants-spec-format: 1 -->
# LWSM-1038 — Remember the port each project was seen running on

**Status:** accepted (2026-10-07).
**Kind:** implement.
**Source:** ROADMAP LWSM-1038 (user-2026-08-03).
**Blocked by:** LWSM-1011 (shipped 2026-10-02).
**Amends:** [LWSM-1385 INV-6](LWSM-1385-port-provenance.md#5-invariants)'s rule
for when the port cell shows *(sources differ)*.

**Layman:** Once the app has seen a project run, its row says "confirmed" and the
app uses the port it saw, instead of a guess read from the project's files.

## 1. Goal

After this ships, `projects.json` stores a `confirmed_port` for each project the
app has seen listening. The app saw it because its own process group held the
port, or because a server in the project's own systemd unit, or one that looks
like the project, held it. The effective port prefers it over the detected port,
so every launch, probe and stop after the first run uses the measured port. Each
row's port cell says *confirmed*, *detected* or *no port*, so the user can see
which projects are still guesses.

## 2. Problem

1. **The precedence chain has a missing rung.** `docs/design.md § The effective
   port` orders override > `confirmed_port` > declared > framework default.
   `registry.ProjectRecord.effective_port` implements override, then `port`,
   and its docstring names rung 2 as this item.
2. **A port the rules cannot read is never learned.** For a project whose port
   no rule reads, such as `project-e`'s (`design.md § Robustness`, measure 1),
   `effective_port` is `None`. `ProjectController._classify` returns `UNKNOWN`
   for such a project before it reads `our_ports`, so even when our own child
   binds a port, nothing records which.
3. **The row cannot say whether its port is a guess.** `design.md § Robustness`
   measure 2 asks for *confirmed* / *detected* / *unknown* on every project.
   `mainwindow.port_text` renders the number alone.

## 3. Scope decisions (agreed with the user)

- **The confidence word is visible text in the port cell**, not only in the
  tooltip — the user, 2026-10-07.
- **A confirmed port hides *(sources differ)***, as an override already does;
  the disagreement stays in the tooltip — the user, 2026-10-07. This amends
  LWSM-1385 INV-6.
- **Settled earlier in `docs/design.md`**, and cited rather than re-argued: the
  precedence; recording from our own launch or from a plausible holder;
  persisting the value as an observed fact (§ Persistence); an override still
  wins, and a launch on it still updates `confirmed_port`.
- **Decided by the author, not the user**, and recorded so they are not
  re-argued:
  - When our group holds several ports, § 4.3's order picks one, and an
    ambiguous set records nothing. Guessing between a dev server and its
    websocket port would store a wrong fact under a word that claims certainty.
  - `confirmed_port` is classified DETECTED, and a rescan that changes the
    stored `port` clears it (§ 4.4).
  - A change to `port_override` clears it (§ 4.4).
  - Seeing nothing never clears it. A stopped project keeps its confirmed port.

## 4. Design

### 4.1 The record and the effective port

```python
# registry.py — ProjectRecord gains one field, classified DETECTED.
confirmed_port: int | None = None

DETECTED_FIELDS = frozenset(
    {
        "path",
        "port",
        "port_from",
        "port_conflicts",
        "confirmed_port",
        "kind",
        "argv",
        "unit",
    }
)


@property
def effective_port(self) -> int | None:
    if self.port_override is not None:
        return self.port_override
    if self.confirmed_port is not None:
        return self.confirmed_port
    return self.port
```

DETECTED because the machine observes it and the user never types it. That gives
it the import behaviour it needs for free: `merge_imported` clears it on a new
record through `_detected_half_cleared`, and a profile never carries one machine's
observations to another as fact. `export_profile` writes it as stored.

### 4.2 The file format

One optional key per project object, written after `port_conflicts`:

```json
{"path": "/srv/project-e", "name": "Project E", "port": null,
 "confirmed_port": 5002, "port_override": null}
```

`schema_version` stays `1`, under LWSM-1007 § 4.2's compatibility rule: the key is
optional, and a file without it loads as before. An older build keeps it through
`ProjectRecord.unknown` (LWSM-1218, test
`tests/test_registry.py::test_a_key_this_build_does_not_know_survives_a_round_trip`).

| Key | Type | Default when absent | Refused when |
|---|---|---|---|
| `confirmed_port` | int or `null` | `null` | not an int (a `bool` is not one, per `_is_int`), or outside `DECLARED_PORT_RANGE` |

A refusal takes the default and reports a reason, under LWSM-1007 § 4.2's rule.
The field is detected, so it never adds to `LoadResult.user_fields_refused` and
never makes the session read-only.

### 4.3 Observing a port

`ProjectController._on_snapshot` gains two steps, both reading the poll's one
snapshot. Neither adds a system call: step 1 reads `our_ports`, which the poll
already computes, and step 2 reads the status `_classify` just returned.

**Step 1, before `_classify`: our own group.** Where `our_ports` is non-empty,
the port to confirm is the first of these that applies:

1. the record's `effective_port`, if our group holds it;
2. the record's `port`, if our group holds it;
3. the only port, if our group holds exactly one;
4. none, otherwise. The set is ambiguous, and nothing is recorded.

Running before `_classify` is what reaches `project-e`. In the poll where its
group binds 5002, step 1 records 5002, `effective_port` becomes 5002, and the
same poll classifies it `running (managed)`.

Rule 3 also changes what a project without an override reads when its group
binds one port other than its declared one: that port is confirmed, so the row
reads `running (managed)` rather than `running (wrong port)`. `running (wrong
port)` remains for an override the project ignores, ADR-0002's case: the
override outranks the confirmed port, so the bound port is never the effective
one.

**Step 2, after `_classify`: someone else's server.** Where `our_ports` is empty
and the status is `RUNNING` or `RUNNING_FOREIGN`, the port to confirm is the
`effective_port` if `snapshot.answers_localhost` says it is held, otherwise the
record's `port`. Those are the two ports `_classify` probes (ADR-0004's
*declared port is probed as well*). `_classify` returns `UNKNOWN` for a record
with no `effective_port`, so step 2 never meets one.

**Either step**: a port equal to the stored `confirmed_port` changes nothing.
A different one replaces the record (`replace(record, confirmed_port=port)`).
No other status, and no poll that found nothing, ever changes the field.

When a poll replaced any record, the controller emits a new signal,
`confirmed_ports_changed`. `MainWindow` answers it with `_write_records`, the one
writer, which saves only where `_should_write` finds the records differ from
the last load. The window shows no message when the save succeeds. A failed save
is logged, and only by `_write_records`' existing warning, and the value stays in
memory for this session.

### 4.4 When a confirmed port is cleared

| Event | `confirmed_port` |
|---|---|
| A rescan leaves the stored `port` unchanged | kept |
| A rescan changes the stored `port`, including to `None` | cleared |
| A rescan finds a new project | `None` |
| An import changes an existing record's `port_override` | cleared |
| An import leaves `port_override` unchanged | kept |
| An import adds a record | `None` (`_detected_half_cleared`) |
| The project stops, or no poll sees it | kept |

`_detected_half_applied` adds `confirmed_port` to `_NOT_COPIED` and sets it by
the first two rows. A changed `port` means the project's own files now say
something else, and the old observation may be why the app still passes the
old value as `PORT`. The *changed* count needs no change, because a row that
clears the field also changed `port`.

`merge_imported` applies the import rows in its existing-record branch, after
`user_half_applied`. Without them, a project that honours `PORT` and was launched
on an override would keep the override's port as its confirmed port after the
override was removed. LWSM-1014's settings editor is the next writer of
`port_override`, and it owes the same rule.

### 4.5 The row

`controller.RowView` gains `port_confirmed: bool`. It is true when
`record.port_override is None and record.confirmed_port is not None`, so true
exactly when rung 2 supplies the effective port. It also gains
`confirmed_port: int | None`, copied from the record.

`mainwindow.ProjectRow`'s port cell, first match wins, each string translated
and its number substituted by `str.replace` as `port_text` does:

| Condition | Cell |
|---|---|
| `port_overridden` | `port 5999` (unchanged) |
| `port_confirmed` | `port 5002 (confirmed)` |
| `effective_port is None` | `no port` (unchanged) |
| `port_conflicts` non-empty | `port 4000 (sources differ)` (LWSM-1385) |
| otherwise | `port 3000 (detected)` |

The second row is above the fourth, which is the amendment to LWSM-1385 INV-6:
the marker now shows when `port_conflicts` is non-empty and the port is neither
overridden nor confirmed.

`port_detail`, the cell's tooltip and the row's accessible description, gains one
leading sentence. When `port_confirmed` it is `Seen running on this port.`, and
the detected-port sentence then takes LWSM-1385's overridden form, `Detected port
4000 is from .env (…).`, followed by the conflicts. When overridden and
`confirmed_port` is set and differs from the override, `Last seen running on
port 5005.` follows `You set this port.`

## 5. Invariants

- **INV-1** — `effective_port` is `port_override` if set, else `confirmed_port`
  if set, else `port`.
  *Test:* `tests/test_registry.py`, one case per rung, each with every lower
  rung set to a different port.
  *Breaks when:* `confirmed_port` is placed above the override, which makes a
  typed port do nothing on a project seen once (`design.md § The effective
  port`).

- **INV-2** — `confirmed_port` round-trips through save and load. A refused
  value loads as `None` with exactly one reason and leaves
  `user_fields_refused` empty.
  *Test:* `tests/test_registry.py`, `test_write_then_load_round_trips` extended
  with the field, plus one case each for `"5002"`, `true`, `0` and `70000`.
  *Breaks when:* the loader accepts a `bool` as an int, or records the refusal
  as a user-field refusal and so makes the session read-only.

- **INV-3** — A rescan keeps `confirmed_port` when the stored `port` is
  unchanged and clears it when the merge changes `port`.
  *Test:* `tests/test_registry.py`, three merge cases with the existing fake
  scan: same port; a new port; a clean read with no port.
  *Breaks when:* `confirmed_port` is left to `_detected_half_applied`'s generic
  copy, which raises because the scan has no such attribute, or is kept
  unconditionally.

- **INV-4** — An import that changes an existing record's `port_override`
  clears its `confirmed_port`; one that leaves it unchanged keeps it.
  *Test:* `tests/test_registry.py`, two `merge_imported` cases.
  *Breaks when:* `merge_imported` relies on `user_half_applied` alone, which
  never touches a detected field.

- **INV-5** — With our group holding ports, the poll confirms by § 4.3 step 1's
  order, and records nothing for an ambiguous set.
  *Test:* `tests/test_controller.py`, four cases with a fake supervisor and
  snapshot: the effective port among two; the declared port among two when the
  effective is not held; a single unrelated port; two unrelated ports, which
  leave the field `None`.
  *Breaks when:* the step takes `min(our_ports)` or the first port iterated.
  That passes the single-port case and fails the ambiguous one.

- **INV-6** — A project with no port, started by us, reads `running (managed)` in
  the same poll its group binds a single port, and that port is stored.
  *Test:* `tests/test_controller.py`, a record with `port=None`, a fake
  supervisor owning the holder of 5002.
  *Breaks when:* confirmation runs after `_classify`, which returns `UNKNOWN`
  for that poll.

- **INV-7** — A server we did not start confirms its port only when it is in the
  project's own unit or looks like the project. A `port blocked` or `failed`
  holder confirms nothing.
  *Test:* `tests/test_controller.py`, three cases: a looks-like holder on the
  declared port while the effective port is free; an unrelated holder on the
  effective port; our child exited and an unrelated holder.
  *Breaks when:* step 2 confirms from any holder of the effective port.

- **INV-8** — No poll that finds the project stopped, or the table unreadable,
  changes `confirmed_port`.
  *Test:* `tests/test_controller.py`, a record with `confirmed_port=5002` polled
  with an empty snapshot, then through `_on_probe_error`.
  *Breaks when:* the controller writes what the poll saw, including `None`.

- **INV-9** — The window saves once per change of `confirmed_port` and not on a
  poll that changed nothing.
  *Test:* `tests/test_mainwindow.py`, an injected `ProjectsFile.save` counted
  across three polls, the first of which confirms a port.
  *Breaks when:* the window never hears of the confirmation, which leaves the
  port in memory only. A save on a poll that changed nothing is already
  stopped by `_should_write`.

- **INV-10** — The port cell follows § 4.5's table, first match winning.
  *Test:* `tests/test_mainwindow.py`, one case per row of the table, plus a row
  that is both confirmed and in conflict. Each asserts the cell text and that
  the row's accessible name contains it.
  *Breaks when:* the conflict test is placed above the confirmed one, which is
  LWSM-1385's order before this amendment.

- **INV-11** — A confirmed port never makes a server ours. A looks-like holder
  whose port was just confirmed still reads `running (foreign)`, with
  `managed` false.
  *Test:* `tests/test_controller.py`, the INV-7 looks-like case polled twice,
  asserting `RowView.managed` and the status on the second poll.
  *Breaks when:* anything gates on `confirmed_port` the way it gates on
  `owns_pid`. This is the trust boundary: ADR-0004 calls "looks like" a display
  heuristic with no security value, and `chdir()` is free. So a confirmed port
  may decide which port is probed and launched, but never whether a holder is
  ours. The Open, Stop and Restart disclosures stay keyed on `owns_pid`.

## 6. Failure modes

- **A local process imitates the project.** A process that `cd`s into the
  project and binds a port is confirmed by step 2. The effective port then
  points at it. Nothing is skipped because of it (INV-11): its row is
  `running (foreign)`, and Open shows the disclosure naming it. The next launch
  of the real project confirms whatever that project binds.
- **An older build rescans.** It keeps `confirmed_port` as an unknown key but
  cannot clear it when `port` changes, so a stale value can survive until the
  project next runs here.
- **A hand edit removes `port_override`.** The loader cannot tell, so a
  confirmed port recorded under the override stays. For a project that honours
  `PORT`, it then keeps binding that port. The supported route is the settings
  editor (LWSM-1014), which clears it.
- **The save fails, or the session is read-only.** The value holds for this
  session and is retried on the next change. `_write_records` logs each failure.
- **A rescan runs while a port is confirmed.** `merge` folds into the records it
  started from, so the confirmation is dropped from the result. The next poll
  that sees the project running records it again.
- **A project flips between two ports.** Each flip is a change and a save, at
  most one per poll interval. Accepted: it is visible in the row, and a project
  that does this has no single port to record.
- **A project with no port, started by hand.** Nothing probes a port for it, so
  it is never confirmed. Out of scope (§ 9).

## 7. Tests

The cases are named with each invariant in § 5, all in existing files:

- `tests/test_registry.py` — INV-1, INV-2, INV-3, INV-4.
- `tests/test_controller.py` — INV-5, INV-6, INV-7, INV-8, INV-11.
- `tests/test_mainwindow.py` — INV-9, INV-10.

Each new test is seen to fail against the code before its rule is written, by
breaking that rule once in a scratch copy per
`docs/standards/testing-overrides.md` § T9. Existing tests in
`tests/test_mainwindow.py` that assert a bare port cell or announcement gain
the *(detected)* or *(confirmed)* word.

## 8. Alternatives considered (and rejected)

- **Never confirm a port equal to the override.** It would stop an override's
  port outliving the override, without a clearing rule. Rejected because
  `design.md § The effective port` says a launch on an overridden port updates
  `confirmed_port`, and § 4.4's clearing rule reaches the same result without
  contradicting it.
- **A third field class, *observed*, beside detected and user.** Every behaviour
  it would need is either DETECTED's (cleared on import) or written per field in
  `_detected_half_applied`, as `port` already is. A third set would touch every
  reader of the two sets for nothing.
- **Store the port it was confirmed beside, and clear on mismatch at load.** It
  also catches the older-build case in § 6, but at the cost of a second key
  whose only job is to detect staleness. The next run corrects the value anyway.
- **Clear `confirmed_port` on every rescan.** Rescan is how detected values
  refresh, but a rescan learns nothing about a port no rule reads. `project-e`
  would lose its port on every rescan, which is the case this item exists for.
- **Confirm from any holder that answers on the port.** `port blocked` exists
  because an unrelated process on 5000 is not the project (ADR-0004).
- **Show the confidence word only in the tooltip.** Rejected by the user (§ 3).

## 9. Out of scope

- Finding a hand-started project that has no port, by scanning every listener
  for one that looks like it — deferred; not yet queued.
- An action to forget a confirmed port — deferred; not yet queued. A rescan that
  changes the port, or an override change, clears it.
- Learning how long a project takes to bind, which ADR-0004 § Slowness is not
  failure names beside this item — deferred; not yet queued.
- The settings editor's own clearing of `confirmed_port` — LWSM-1014.

## 10. What checks this

| Rule | What catches a breach |
|------|----------------------|
| INV-1 | `tests/test_registry.py`, the three precedence cases |
| INV-2 | `tests/test_registry.py::test_write_then_load_round_trips` and the four refusal cases |
| INV-3 | `tests/test_registry.py`, the three rescan cases |
| INV-4 | `tests/test_registry.py`, the two import cases |
| INV-5 | `tests/test_controller.py`, the four our-group cases |
| INV-6 | `tests/test_controller.py`, the no-port case |
| INV-7 | `tests/test_controller.py`, the three foreign-holder cases |
| INV-8 | `tests/test_controller.py`, the stopped and unreadable cases |
| INV-9 | `tests/test_mainwindow.py`, the save-count case |
| INV-10 | `tests/test_mainwindow.py`, the port-cell cases |
| INV-11 | `tests/test_controller.py`, the second-poll foreign case |
| § 4.1 the new field is DETECTED | `tests/test_registry.py::test_an_imported_project_arrives_with_no_confirmed_port` |
| § 4.4 LWSM-1014 clears on an override change | **nothing** — that item is not built; its spec owes the rule |
| § 4.5 the tooltip's wording | **nothing** — copy, reviewed by reading |

## 11. Cross-doc impact

- `docs/specs/LWSM-1385-port-provenance.md` § 5 INV-6: a pointer to § 4.5 here.
- `docs/specs/LWSM-1007-registry-persistence.md` § 4.2: a pointer to § 4.2
  here for the new key.
- `docs/known-issues.md` known-issue-043 names `confirmed_port` as the case it
  feared; it is resolved already and needs no edit.
- `CHANGELOG.md`: one *Added* entry.

## 12. Cold-eyes loop log

Rows live in `../reviews/LWSM-1038-confirmed-ports-loop-log.md`.

## 13. Resource cost

One integer per record, and no new system call per poll (§ 4.3). A save happens
only when a confirmed port changes.
