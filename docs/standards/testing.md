<!-- ants-test-standards: 1 -->
# Testing Standards — v1

A shareable contract for tests in this project. Pairs with the
other standards in this folder — see the [index](README.md) for
the full set.

This standard governs ROADMAP bullets with `Kind: test`; the
feature-conformance test § 7 requires of `Kind: implement` work;
the regression-test follow-through expected for `Kind: fix`,
`audit-fix` and `review-fix`; and the source-invariant test
`coding.md § 1.6` hands to § 3.6, which reaches `Kind: refactor`
too. In short: every Kind that ships code.

The narrower list this used to carry — `test` plus the three fix
kinds — contradicted § 1 (TDD for "every code change that ships
behaviour") and § 7 (a conformance test per `Kind: implement`), so
a developer on a feature bullet could read the header and conclude
this standard did not govern them.


## 1. TDD policy — test first, code second

This project follows **test-driven development** for every code
change that ships behaviour. The cycle is:

1. **Write a failing test** that asserts the desired behaviour
   (or, for a bug fix, asserts the bug doesn't recur).
2. **Run the test** and confirm it fails on the current code.
3. **Write the minimum code** that makes the test pass.
4. **Refactor** if needed; tests stay green.
5. **Commit** code + test together (per
   [commits § 1.1](commits.md)).

This sequence catches the most common test-quality bug: a test
written *after* the fix that accidentally tests the new behaviour
without being sensitive to the old one. A test written first must
fail before the fix; otherwise the test isn't testing what you
think.

**Exceptions to TDD** (rare, must be justified in the commit
body):

- Pure refactors with no behaviour change — keep existing tests
  passing; no new test required.
- Documentation-only changes (`Kind: doc` / `doc-fix`) — no test
  needed.
- Generated code (`moc_*`, `ui_*`, etc.) — not tested directly;
  the consumer is.
- Exploratory spike / proof-of-concept clearly marked as such.

If TDD genuinely doesn't fit a change, write a comment in the
commit body explaining why so a reader understands the deliberate
deviation.


## 2. Principles

### 2.1 Tests test the contract, not the implementation

A test that mirrors the function's source is a regression guard
for the current implementation, not validation of correct
behaviour. Anchor tests to **external signals** wherever possible:
spec sections (RFC, ECMA, WCAG), CVE classes, contract docs,
user-visible behaviour.

Test names broadcast this:

- ✅ `test_RFC_7231_section_3_1_2_5_strips_LF`
- ✅ `test_WCAG_2_3_1_no_flashing_at_3hz`
- ❌ `test_parseHeader_branches_2_3_4`

A reviewer reading just the test names should be able to tell
which tests are validating contract vs. which are merely guarding
the current code path.

**One exception, and it is deliberate: the source-invariant test
(§ 3.6).** A test that scans a module's own source for the *shape
of a past defect* mirrors the implementation on purpose — the
contract it validates is that the shape is absent, so there is
nothing else for it to anchor to. It is exempt from this section
and from § 9's mirror-the-source anti-pattern. `coding.md § 1.6`
is what asks for one, and § 3.6 bounds when.

### 2.2 Verify the test fails on broken code

Even when following TDD strictly, double-check before claiming a
test locks in a fix:

```bash
git checkout <fix-commit>^ -- src/lwsm/foo.py            # revert the fix
PYTHONDONTWRITEBYTECODE=1 uv run pytest -k the_new_test  # must FAIL
git checkout HEAD -- src/lwsm/foo.py                     # restore the fix
PYTHONDONTWRITEBYTECODE=1 uv run pytest -k the_new_test  # must PASS
```

**Name the fix's own commit; do not assume it is the last one.**
Two shorter forms were run against this repo on 2026-08-07 while
writing this block, and **both reported the test passing in the
"must FAIL" position** — which reads exactly like a verified
mutation and is worse than no check:

- `git stash push <file>` reverts *uncommitted* work, so against a
  fix that is already committed it reverts nothing.
- `git checkout HEAD~1 -- <file>` reverts exactly one commit, so with
  six commits landed since the fix it lands on a revision that still
  contains it.

`<fix-commit>^` reddened the test on the first attempt.

**Commit the fix before running this block.** `git checkout <rev> -- <path>`
overwrites the working copy with no stash and no reflog entry, so against a
fix you have not committed yet it does not reveal anything — it destroys it.
That is a live hazard rather than a theoretical one: § 1's TDD cycle has you
holding exactly such an edit at step 3.

`PYTHONDONTWRITEBYTECODE=1` is not decoration. Python invalidates
bytecode on mtime **and size**, so a same-size revert-and-restore
can leave a stale `.pyc` that makes the mutation appear to have no
effect — reproduced on this project 2026-08-06. `local-ci.sh`
exports it; a bare `pytest` does not.

Check the `-k` pattern matched what you meant. A pattern matching
nothing **exits 5** (measured), so a typo fails a `&&` chain rather
than passing one — the "must FAIL" step cannot be satisfied by a
misspelling. The real hazard is a pattern matching the *wrong*
tests: that exits 0 and reports a green run of code you did not
touch.

If the test passes on broken code, it's not testing what you
think. Rewrite it.

### 2.3 Spec first, then test

For feature-conformance tests: write `spec.md` first as a
human-readable contract. Get user sign-off on the spec. Then
write the test that enforces each invariant.

The test references the spec by section: `// INV-3 from
spec.md § 2.1`. Reader can move between spec and test fluidly.


## 3. Test types

### 3.1 Unit tests

Test a single function or class in isolation. Deterministic, no
I/O, no external services — **one exception, the source-invariant
test (§ 3.6), which reads a module's source on purpose.**

**Speed budget is § 6's and stated only there.** This line used to
say "< 10 ms each" against § 6's "< 100 ms", an order of magnitude
apart with neither section naming the other, so the same test
passed one and failed the other depending on which a reviewer
cited.

### 3.2 Feature-conformance tests

End-to-end behaviour matching its spec. Larger than unit tests
but still GUI-free where possible. Pattern:

```
tests/features/<feature_name>/
├── spec.md           # contract — human-readable invariants
└── test_<name>.cpp   # enforcement — INV-1, INV-2, … assertions
```

CMakeLists.txt wiring:

```cmake
add_executable(test_foo
    tests/features/foo/test_foo.cpp
    src/foo.cpp)
target_link_libraries(test_foo PRIVATE Qt6::Core Qt6::Test)
add_test(NAME foo_feature COMMAND test_foo)
set_tests_properties(foo_feature PROPERTIES LABELS "features;fast")
```

### 3.3 Integration tests

Cross-component tests where mocking would lose coverage. Hit a
real database / real filesystem / real subprocess where the
interaction is the thing under test.

### 3.4 Performance tests

Measure throughput / latency / memory. Tag `LABELS perf` so they
can be excluded from CI when noisy. Compare against a baseline,
not absolute thresholds, so machine differences don't fail the
test.

### 3.5 Fixture-based tests

For rule-based tools (linters, audit checks): keep `bad.cpp` and
`good.cpp` files in `tests/audit_fixtures/<rule>/`, run the rule
against them, assert N hits on `bad` and 0 on `good`. Count-based,
not line-number-based — line numbers shift across edits.

### 3.6 Source-invariant tests

A test that reads a module's own source and fails on the *shape of
a past defect* — `coding.md § 1.6`'s "make the sweep a test rather
than a habit". `test_no_file_sourced_value_is_interpolated_without_the_clip`
is the worked example: it reads `registry.py` and fails on any
un-clipped `{…!r}` interpolation, so the fourth instance of a
defect already found three times is caught at the gate instead of
by the next review.

Exempt from § 2.1 and § 9's mirror-the-source rule, and from
§ 3.1's no-I/O rule, because reading the source *is* the assertion.
Both exemptions are deliberate and neither generalises: this is the
only test type in this standard that may do either.

**When to write one, so it does not become scaffolding (`coding.md
§ 1.1`):** the mechanism has three or more call sites, **or** this
is the second time the same shape has been found. A two-site
mechanism found once is served by the grep and the commit line.

**Rules, because this type is the easiest to write badly:**

- **Assert the shape's absence, not a file's contents.** Match a
  pattern, never a line count or a whole-file hash — those fail on
  every unrelated edit, which trains people to update the expected
  value without reading it.
- **Exclude comments.** The comment explaining a past defect
  usually contains the defect's own shape, so a naive match reports
  the documentation as a violation.
- **Name it for the invariant, not for the grep** — what must not
  be true, not what regex you ran.
- **Scope it to one module.** A tree-wide scan fires on unrelated
  code and gets deleted rather than fixed. Where the mechanism's
  sites span modules, that means **one test per module holding a
  site** — a scoped test covers only what it can read, and T9 and
  § 7 are discharged only for those sites.


## 4. spec.md authoring

```markdown
# <feature> spec

**Theme:** one-line summary.

## Invariants

- **INV-1**: <observable behaviour, written as an assertion>.
  Source: RFC X.Y.Z § 4.5.
- **INV-2**: <observable behaviour>. Source: user report
  YYYY-MM-DD.
- **INV-3**: <observable behaviour>. Source: derived from INV-1
  and INV-2.

## Out of scope

What this feature explicitly does *not* do. (An empty section is
fine; the heading itself is a useful question to answer.)
```

INV numbering:

- Top-level: `INV-1`, `INV-2`, `INV-3`, …
- Sub-invariants: `INV-1a`, `INV-1b`, … (when one invariant has
  multiple sub-cases differing only in a parameter).

INVs are **append-only** within a spec. Don't renumber when
inserting — add `INV-1c` for a new sub-case after `INV-1b`. Same
policy as ROADMAP IDs.

When a spec invariant is dropped (the feature decision changed),
mark the INV as `**INV-3** (retired in 0.7.21): <reason>` rather
than deleting it — that preserves the cross-reference from old
test code and commit messages.


## 5. Test failure messages

A failing test must print enough to diagnose without reproducing
locally:

```cpp
QVERIFY2(grid->cellAt(0, 0).fg == QColor(255, 0, 0),
         qPrintable(QString("Cell 0,0 fg = %1, expected #FF0000")
                    .arg(grid->cellAt(0, 0).fg.name())));
```

Not just `QVERIFY(grid->cellAt(0, 0).fg == QColor(255, 0, 0))`,
which only prints "QVERIFY failed at line N".

Same principle for Python (`assert x == y, f"got {x}, want {y}"`)
and any other language: every assertion carries enough context
that the CI log alone is diagnosable.


## 6. Performance / determinism

- **Deterministic.** No `random.random()`, no time-of-day. If
  randomness is genuinely needed, seed it with a fixed value.
- **Fast.** Target < 100 ms each for `LABELS fast`. Move slower
  tests to `LABELS perf` or `LABELS integration`.
- **Isolated.** No shared state between tests; one failing test
  doesn't poison another.
- **No network unless opt-in.** A test that hits the network
  needs `LABELS network` and an env-var gate (e.g.
  `ANTS_TEST_NETWORK=1`).


## 7. Coverage policy

- **Every fix has a regression test** (per `Kind: fix`
  follow-through; TDD makes this automatic — the failing test is
  the start of the fix).
- **Every new feature has at least one feature-conformance test**
  (per `Kind: implement`).
- **Every audit / review finding has a regression test** (per
  `Kind: audit-fix` / `review-fix`).
- **Refactors don't get new tests** — they must keep the existing
  ones passing. If the refactor reveals untested behaviour, that's
  a separate `Kind: test` ROADMAP item.


## 8. Test commits

A test-only change uses `Kind: test` and the corresponding commit
prefix. With the `<ID>: <description>` mandate from
[commits § 1.1](commits.md):

```
ANTS-1234: lock the OSC 8 multi-row span emission

Adds INV-7c to tests/features/osc8_hyperlinks/spec.md and the
corresponding assertion in test_osc8_hyperlinks.cpp.

Co-Authored-By: …
```

When the test ships *with* a fix in the same commit (TDD's normal
case), the commit covers both — the test goes in alongside the
code change, with a single commit referencing the ROADMAP ID.


## 9. Anti-patterns

- ❌ Tests written *after* the fix without verifying they fail on
  pre-fix code (§2.2).
- ❌ Tests that mirror the function's source — regression guards,
  not validation. (One exception: the source-invariant test,
  § 3.6, where the shape's absence *is* the contract.)
- ❌ Mocking what should be a real integration test.
- ❌ `if (...) skip;` branches that hide platform-specific bugs.
- ❌ Tests that print "FAIL" but exit 0.
- ❌ Tests that depend on machine timing / CPU speed / FPU
  determinism.
- ❌ Tests that touch the network without an explicit opt-in flag.
- ❌ Tests with named functions like `test_works_correctly` —
  what's the *contract*?
- ❌ Tests committed in a "WIP" / failing state.
- ❌ Disabling a failing test (`@pytest.mark.skip`) without a
  ROADMAP item tracking the underlying bug.
- ❌ Skipping TDD on a behaviour change because "it's small".


## LocalWebServerManager overrides

Added at Phase C (2026-08-03). This project's tests have to cover
process supervision and port inspection, which are the two things
naive test suites either mock into meaninglessness or turn into
flaky machine-dependent messes. These rules pick the line.

### T1. Never touch the real environment

A test may not read or write the user's real
`~/.config/localwebservermanager/`, and may not read, write, or
launch any **sibling** project — anything inside a configured
**scan root** (`docs/design.md § Detection rules`; this
repository's own parent directory is one) other than this
repository itself. Anchored to the scan root and this
repository's parent rather than to an absolute path, so the rule
reads the same on any checkout — and so the ban's extent is
decidable without asking, which a bare `<scan root>` placeholder
was not. Config paths
are injected, and every fixture builds its own throwaway project
tree in `tmp_path`. A test that starts `project-f` is not a
test, it is a side effect.

### T2. Spawn real processes — of fake projects

Process supervision is tested by spawning **real** child
processes, because the behaviour under test *is* the operating
system's: process groups, signals, exit codes, orphaning. Mocking
`subprocess` would test the mock. So fixtures generate tiny
throwaway launcher scripts in `tmp_path` — one that binds a port
and sleeps, one that spawns a child and execs away (the
`start.sh` wrapper shape that motivated ADR-0003), one that exits
0 without binding, one that exits non-zero, one that ignores
`PORT`. Those five cover the state table in ADR-0004.

### T3. Ports come from the OS, never from a literal

A test that hard-codes port 5005 fails on a machine where
something else holds it, and worse, passes for the wrong reason.
Bind port `0`, ask the socket what it got, use that. The one
exception is a test asserting the *rejection* of an out-of-range
value (`80`, `70000`), where nothing is bound.

### T4. Wait for conditions, never for durations

`time.sleep(2)` to let a server start is the flakiness
anti-pattern §6 warns about, and this codebase is full of
opportunities for it. Poll for the actual condition — port bound,
process exited, signal emitted — with a generous ceiling and a
clear timeout message. `qtbot.waitUntil` and `qtbot.waitSignal`
exist for exactly this.

### T5. Every test kills what it started

A leaked child process holds a port and poisons every later test
in the session. Fixtures tear down with the same
group-signalling path production uses — which has the useful side
effect of testing it constantly. A test that leaks is a failing
test even when its assertions pass.

### T6. Headless is the default

Core tests (scanner, registry, ports, supervisor) import no
widgets and need no display. Widget tests use `pytest-qt` and run
under an offscreen platform (`QT_QPA_PLATFORM=offscreen`) so CI
needs no X server. If a test needs a visible window to pass, the
thing it is testing is in the wrong layer — see coding § O1.

### T7. The state table is a parametrised test, not prose

ADR-0004's seven states are the app's core contract. They get one
parametrised test whose cases are named after the states, so a
new state cannot be added without a case appearing. Test names
anchor to the ADR (`test_running_wrong_port_when_child_binds_elsewhere`),
not to the function that happens to implement it.

### T8. Accessibility has tests, or it is decoration

Four checks, all cheap, all headless:

- **Contrast arithmetic** over every theme — every
  text-on-background pair ≥ 4.5:1, every state indicator ≥ 3:1.
  The two high-contrast palettes clear a stricter **7:1** on text
  pairs, because a theme whose whole purpose is contrast has to be
  held to more than the floor everything else meets; softening
  them is the regression this tier exists to catch.
  Parametrised across themes, so **adding a theme that fails is a
  failing build**, not a discovery months later.
- **Keyboard reachability** — every action in the window is
  reachable by Tab and activatable by keyboard, and tab order
  matches visual order.
- **Accessible names** — every interactive widget has a non-empty
  accessible name, and every state is exposed as text and not
  only as a colour.
- **No clipping at 200 %** — the window lays out at the maximum
  text-size setting with no cell narrower than the string it
  renders. A clipped `QLabel` loses its last characters silently.
  Deliberate elision is a separate matter and is not forbidden
  here; where a project elides, it owes the full string in a
  tooltip and in the accessible name. Corrected 2026-09-02: this
  read "nothing elided or cut off", which described neither the
  check nor any project running it.

These fail loudly rather than warning. An accessibility
regression that only warns is an accessibility regression that
ships.

### T9. A test proves the fix is *reached*, not that its helper works

Added 2026-08-07 after the third review of P02 found **four shipped fixes that
could be deleted with the whole suite still green** — 150 tests at the time.

None of those was an untested *feature*. Each had a test that named it and
asserted the wrong end of the call:

| The fix | The test asserted | What it could not see |
|---|---|---|
| `run()`'s call to the bounded process exit (all of LWSM-1100) | the entry-point **string** `lwsm.__main__:run` | that `run()` does anything |
| `MainWindow.setPalette` | the `QPalette` **object** `to_palette()` returns | that no widget ever receives it |
| `main()`'s `finally: controller.stop()` | the helper, called **directly** in a subprocess script | that the caller calls it |
| all three of the log handler's filesystem checks | that an `OSError` was raised | that it was raised by *this* check and not a later one |

(The `setPalette` row is a historical record and its line is deliberately gone:
LWSM-1118 later moved the palette to the application, which made the window's
own call redundant. A row here names what a past review found, not what is in
the tree today.)

So the rule, for every `Kind: fix`, `audit-fix` and `review-fix` change:

1. **Revert the smallest edit the fix made, and confirm the fix's own test goes
   red** — run it by name (`PYTHONDONTWRITEBYTECODE=1 uv run pytest -k
   the_new_test`), not the whole suite, so an unrelated failure cannot stand in
   for it. Delete the line it added, restore the line it removed, or put back
   the value it changed. If it does not redden, the test you just wrote is
   testing something else and the fix ships unguarded.

   **§ 2.2's whole-file revert is not a substitute here.** It undoes every edit
   the fix made to that file at once, so against a multi-site sweep it produces
   one red run for all of them — and the per-site rule below would then credit
   that one run to every site. Use it for a single-site fix; edit the one line
   in place otherwise.

   **Not "delete the line the fix adds", which is what this step said until the
   gate caught it.** Plenty of fixes add no line: this pass alone changed a
   constant, removed a redundant call, and replaced one expression with another.
   Deleting a *changed* line removes the behaviour rather than restoring the
   defect, so it reddens for the wrong reason and the mutation reads as passed.

   This is § 2.2 applied to the *wiring* rather than to the behaviour, and it is
   the half § 2.2 lets through: a fix can be genuinely absent from the shipping
   path while the behaviour it implements is tested elsewhere.
2. **Assert the consequence only that line produces.** Where two mechanisms
   reach the same outcome, the shared outcome is not evidence. A refusal that
   two different checks can both raise needs the *message*, or the side effect
   the other one leaves behind — the `O_DIRECTORY` case above raised `OSError`
   either way, and the only thing separating them was whether the victim file
   got chmodded.
3. **A stub must be able to express the breach.** A fake that cannot produce
   the failure makes its test green by construction. The reader-less FIFO could
   never reach the `S_ISREG` check, because the open failed first — the test
   read as covering it for months.

**When `coding.md § 1.6`'s sweep fixed several call sites in one change, the
mutation is run per *site*, not per change.** One red run does not discharge the
others — that is the same "a fix is reached" question asked five more times.
Where the sweep is instead expressed as a single source-invariant test
(§ 3.6), one mutation of that test is enough for **every site it can actually
read**, and it satisfies § 7's regression-test requirement for those sites too.
Read literally: a § 3.6 test is scoped to one module, so a mechanism whose
sites span modules needs one such test per module, and the sites outside them
are back to a mutation each.

Record the mutation and its result in the commit body. "Verified red on
deletion" is one line and it is the whole evidence that the guard exists.

**This does not license a spy on every call — and it narrows the assertion
style, not the section.** Steps 1–3 and the commit record apply to every change
of the Kinds named above, whatever the fix looks like. What is reserved is the
*call-happened spy*: reach for one only where the **only** difference between
fixed and unfixed is that a call happens, and § 2.1 would otherwise argue
against writing the test at all. Everywhere else, an assertion on a rendered
pixel, a returned value or an observable state change is strictly better and
stays the default — nine of the eleven mutations that review ran died against
rendered pixels.



## Cold-eyes loop log

Rule-14 gate history for this standard. Written by `/cold-eyes` as
each loop happens, never back-filled.

| Loop | Date | Lanes | CRIT | HIGH | MED | LOW | Verified | Outcome |
|---|---|---|---|---|---|---|---|---|
| 1 | 2026-08-07 | 2 (general-purpose, strong model) | 0 | 4 | 4 | 4 | 12 verified, 0 unverified, 12 fixed | Converged. Batched run with `coding.md` — see that file's log for why. Dimensions: dim 6×3, dim 7×3, dim 2×2, dim 15×1, dim 8×1, dim 12×1, dim 11×1. **Both lanes independently found that `§ T9` step 1 only worked for a fix that ADDS a line** — it read "Name the line the fix adds. Delete it" while a large share of fixes change or remove one, and deleting a *changed* line removes the behaviour rather than restoring the defect, so it reddens for the wrong reason and reads as verified. Generalised to reverting the smallest edit, which `§ 2.2` already did. **`§ 2.2` itself was a CMake/ctest recipe in a Python project**, and `§ T9` explicitly stands on it, so following the new clause led to an unrunnable command; now the project's pytest form, and **executing it before it shipped caught two wrong revert forms**, both of which reported the test passing in the "must FAIL" position. `§ 3.6` added to sanction the source-invariant test `coding.md § 1.6` asks for, with the exemptions stated and bounded. Also fixed: `§ 3.1`'s "< 10 ms" against `§ 6`'s "< 100 ms" for the same tests; `§ T9`'s "150 tests" stated as standing fact when the suite is at 173; T7 restored to sequence after T9 had been inserted between T8 and T7; T1's undefined `<scan root>` placeholder; and the header's "other three standards" against five. Remaining C++/CMake residue routed to LWSM-1062. |
| 2 | 2026-08-07 | 2 (general-purpose, strong model) | 0 | 7 | 6 | 2 | 15 verified, 0 unverified, 15 fixed | **Converged by sweep, not by dispatch** — 11 fix collateral vs 4 draft defects; see `coding.md`'s log for the split and the shared findings. Both lanes independently found that loop 1's own two additions to `§ T9` contradicted each other: step 1 endorsed § 2.2's **whole-file** revert while the paragraph below required the mutation **per site**, and a whole-file revert of a multi-site sweep produces exactly one red run — which the per-site rule would then credit to every site, the precise failure T9 exists to catch. Step 1 also passed on "at least one test goes red", satisfiable by any unrelated failure; it now names the fix's own test and runs it by name. `§ T9`'s closing paragraph read as narrowing the whole section to call-happened-spy cases while its opening applied to every fix of three Kinds — it now narrows the *assertion style* only. Draft defects: the header scoped this standard to `test` plus three fix Kinds while `§ 1` binds "every code change that ships behaviour" and `§ 7` binds `Kind: implement`; and `§ 2.2`'s `git checkout <rev> -- <path>` silently destroys an uncommitted fix, which § 1's TDD cycle has you holding at step 3 — now says commit first. `§ 3.1` and `§ 9` gained the reciprocal pointer to § 3.6's exemption, which loop 1 had declared only at the exempt end, and `§ 3.6` now says a mechanism spanning modules needs one test per module. |
