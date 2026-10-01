<!-- ants-test-standards: 1 -->
<!-- OWNED-HERE testing.md — forked from the app-workflow template and kept as this project's own standard; tests/test_docs.py asserts against it. Reconciling it with the global testing.md is LWSM-1062's job; decided 2026-09-28 (LWSM-1062) -->
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
  passing; no new test required, except § 7's source-invariant case.
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
nothing **exits 5** (measured) — non-zero, so in the "must FAIL"
position a typo reads as red. That step counts only when pytest
exits 1 and reports the named test failed. A pattern matching the
*wrong* tests is the other hazard: in the "must PASS" position it
exits 0 over code you did not touch.

If the test passes on broken code, it's not testing what you
think. Rewrite it.

### 2.3 The spec is the contract

For feature-conformance tests the contract is the item's spec in
`docs/specs/`, where it has one. Whether it is written before the
code or folded back after is `CLAUDE.md` § Review cadence's call.

The test names the invariant it enforces, in its name or docstring:
`INV-3 of LWSM-1006`. Reader can move between spec and test fluidly.


## 3. Test types

### 3.1 Unit tests

Test a single function or class in isolation. Deterministic, no
I/O outside the test's own `tmp_path`, no external services — **one exception, the source-invariant
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
docs/specs/<ID>-<topic>.md   # contract — INV-1, INV-2, … each naming its test
tests/test_<module>.py        # enforcement — one test per invariant
```

There is no wiring step: `pyproject.toml` sets `testpaths = ["tests"]`,
so pytest collects every `tests/test_*.py`. A test's name or docstring
names the invariant it holds, so a spec's `*Test:*` clause can be
searched for.

### 3.3 Integration tests

Cross-component tests where mocking would lose coverage. Hit a
real database / real filesystem / real subprocess where the
interaction is the thing under test.

Mark one `integration` when it spawns a real child process or binds a
real socket — the marker's registered meaning in `pyproject.toml`, and
what `./scripts/local-ci.sh --fast` skips. A throwaway tree under
`tmp_path` alone needs no marker.

### 3.4 Performance tests

Measure throughput / latency / memory. Mark them `perf`, registering
`perf` under `markers` in `pyproject.toml` with the first such test —
an unregistered marker stops the run: pytest warns about it and
`filterwarnings = ["error"]` makes the warning an error. Nothing
deselects `perf` yet; keeping a noisy one out of a gate means adding
`-m "not perf"` to `local-ci.sh`. `integration` and `perf` go on
tests, never on files, because a run deselects by them; `gui` selects
nothing and may be set by a module's `pytestmark` (T6). Compare against a baseline,
not absolute thresholds, so machine differences don't fail the
test.

### 3.5 Fixture-based tests

For rule-based code (the scanner's detection rules, a linter, an
audit check): keep the inputs that must match and the ones that must
not side by side — here, `tests/scanner_fixtures.py` — run the rule
against them, and assert N hits on the first set and 0 on the second. Count-based,
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
  code and gets deleted rather than fixed. The exception is a
  convention every test file keeps, such as T6's `gui` marker: its
  check reads the test files, since that is where the convention lives. Where the mechanism's
  sites span modules, that means **one test per module holding a
  site** — a scoped test covers only what it can read, and T9 and
  § 7 are discharged only for those sites.


## 4. Writing the invariants

`spec-format.md` §3.7 owns the invariant form: numbering, the
`*Test:*` clause, and how a dead invariant is withdrawn without
renumbering.


## 5. Test failure messages

A failing test must print enough to diagnose without reproducing
locally:

```python
assert row.status is ProjectStatus.RUNNING, (
    f"{row.name}: status {row.status}, want running"
)
```

pytest's assertion rewriting already prints both sides of a bare
`assert a == b`. The message is for what the operands cannot say:
which project, which fixture, what the value means. Every assertion
carries enough context that the CI log alone is diagnosable.


## 6. Performance / determinism

- **Deterministic.** No `random.random()`, no time-of-day. If
  randomness is genuinely needed, seed it with a fixed value.
- **Fast.** Target < 100 ms each. A marker never excuses a slow
  test: `integration` says what a test does (§3.3) and `perf` holds
  tests that measure (§3.4), so a slow correctness test carries
  neither and stays in every gate.
- **Isolated.** No shared state between tests; one failing test
  doesn't poison another.
- **No network unless opt-in.** A test that hits the network
  needs a registered `network` marker and an env-var gate (e.g.
  `LWSM_TEST_NETWORK=1`).


## 7. Coverage policy

- **Every fix has a regression test** (per `Kind: fix`
  follow-through; TDD makes this automatic — the failing test is
  the start of the fix).
- **Every new feature has at least one feature-conformance test**
  (per `Kind: implement`).
- **Every audit / review finding has a regression test** (per
  `Kind: audit-fix` / `review-fix`).
- **Refactors don't get new tests** — they must keep the existing
  ones passing. One exception: a refactor that meets § 3.6's
  when-to-write trigger owes its source-invariant test. If the
  refactor reveals untested behaviour, that's a separate `Kind: test`
  ROADMAP item.


## 8. Test commits

A test-only change uses `Kind: test`. With the `<ID>: <description>`
mandate from
[commits § 1.1](commits.md):

```
LWSM-1234: lock the scanner's refusal of a symlinked launcher

Adds INV-20 to docs/specs/LWSM-1006-scanner-detection.md and the
corresponding test in tests/test_scanner.py.

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
tree in `tmp_path`. Nor may it read any other per-user state the
code consults: `tests/conftest.py` pins each `XDG_*` variable the
code reads to a value the test owns. A test that starts `project-f`
is not a test, it is a side effect.

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

A test that needs a Qt application object — one taking `qtbot` or
`app_font` — carries the `gui` marker, on the test or through the
module's `pytestmark`. No run selects on it; it says which tests need
Qt. `tests/test_layering.py` fails on one without it.

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
   for it. It is red only when pytest reports that test failed: exit 5 means
   the pattern matched nothing (§2.2). Delete the line it added, restore the line it removed, or put back
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
Where § 2.2's block ran after the fix was committed, amend that commit's
body with the result; a commit already pushed takes the record in the next
commit instead, naming the fix commit.

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
| 3 | 2026-09-28 | 2 (`review-contract`, genre standard pinned, both lanes holding every question; `neutral-lane`, no project context) | — | — | — | — | 1 verified, 0 dismissed, 1 fixed | Gate armed by c660263 + e7aee3b (pytest forms for § 3.2/§ 3.4/§ 3.5/§ 5/§ 6/§ 8; § 2.3 and § 4 now point at `docs/specs/` and `spec-format.md` § 3.7). **Q2 1**, both lanes: § 6 told a slow test to take `integration`, whose registered meaning is a real child process or socket and which `--fast` skips; now `perf`, with the marker's meaning stated in § 3.3. Measured and true: `local-ci.sh` exports `PYTHONDONTWRITEBYTECODE`; `-k` matching nothing exits 5. **Filed on LWSM-1330, outside the change:** § 7's no-new-tests-for-refactors against § 3.6; § 3.1's "no I/O" against T1's `tmp_path` trees; § 8's "corresponding commit prefix". |
| 4 | 2026-09-28 | 2 (same brief, cold, rebuilt from disk; `neutral-lane`) | — | — | — | — | 1 verified, 0 dismissed, 1 fixed | **Q3 1**, one lane: § 3.4 said `perf` tests are marked "so they can be excluded from CI", and nothing deselects `perf` (measured: `local-ci.sh`'s only `-m` is `"not integration"`); "once registered" read two ways. Now: register it with the first such test, and say that excluding one needs `-m "not perf"` added to `local-ci.sh`. **Filed on LWSM-1330, outside the change:** § 2.2's claim that a mistyped `-k` cannot satisfy the must-FAIL step (it exits 5, which reads as red; both lanes); T6 never says when to apply the registered `gui` marker. |
| 5 | 2026-09-28 | 2 (same brief, cold, rebuilt from disk; `neutral-lane`) | — | — | — | — | 1 verified, 0 dismissed, 1 fixed | **Capped (loop 3 of 3 for a standard). Q2 1**, one lane: § 6 sent every slow test to `perf` while § 3.4 defines `perf` as measurement tests and names `-m "not perf"` as the way to exclude them, which would drop slow correctness tests from the gate; now no marker excuses a slow test. Both lanes re-raised § 2.2's exit-5 claim and T6's `gui` marker, which the packet listed as facts instead of as surfaced; merged into the filed entries. At the cap § 2.2's exit-5 claim and T9 step 1 were fixed too (out-of-change, the run's last loop): a must-FAIL run counts only on exit 1 with the test reported failed (measured). **Final-loop share on this run's own text: 1 of 1** — the § 6 marker rule, rewritten in loops 3 and 4 and wrong again in 5. Read as a violent cap on that one rule, calm on the rest of the document: this review ends here. **Share inside the gated change (c660263 + e7aee3b): 3 of 3** in-change findings; 7 more pre-existing ones filed on LWSM-1330. **Filed, outside the change:** T1's scope against `tests/conftest.py`. |
| 6 | 2026-10-01 | 2 (`review-contract`, genre standard pinned, both lanes holding every question; `neutral-lane`, no project context) | — | — | — | — | 4 verified, 0 dismissed, 4 fixed | **Q1 1 · Q2 3.** Gate armed by 953f950 (LWSM-1330 items 5, 6, 7, 9, 10). Fixed: T1's new claim that conftest pins every `XDG_*` the code reads was false — `XDG_STATE_HOME`, `XDG_CONFIG_DIRS`, `XDG_CURRENT_DESKTOP` were unpinned, and a sentinel run showed the suite creating `localwebservermanager/` under the real state directory; `tests/conftest.py` now pins all three and the sentinel stays empty (both lanes); § 1's "no new test required" for refactors against § 7's new exception (both lanes); § 3.4's "markers go on tests, never on files" against T6's `pytestmark` allowance (now scoped to the selecting markers); § 3.6's one-module rule against T6's check reading every test file (the convention case now named). |
| 7 | 2026-10-01 | 2 (same brief, cold, rebuilt from disk; `neutral-lane`) | — | — | — | — | 2 verified, 0 dismissed, 1 fixed, 1 filed | **Q2 2.** Fixed: loop 1's § 7 exception named only § 3.6's three-site trigger, so a refactor meeting its second-time trigger owed the test under § 3.6 and not under § 7; § 7 now points at § 3.6's trigger instead of restating half of it (one lane; own collateral from loop 1). Filed LWSM-1351, pre-existing: § 2.2 commits the fix before the must-FAIL block, and T9 wants that block's result in the same commit's body (one lane). Resolved clean: no class-based or async test exists, so the T6 check's module-level walk covers every Qt test today. |
| 8 | 2026-10-01 | 2 (same brief, cold, rebuilt from disk; `neutral-lane`) | — | — | — | — | 0 verified, 0 dismissed | **Converged — Q1 0 · Q2 0 · Q3 0.** Resolved clean: an unregistered marker does stop the run (measured: collection error), as § 3.4 says. Open questions left as reported: T2's five launcher fixtures against T7's seven states; T6's check misses a class-based or indirect-fixture Qt test, none of which exists today. |
