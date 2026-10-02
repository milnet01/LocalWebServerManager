<!-- ants-testing-overrides: 1 -->
# Testing overrides — LocalWebServerManager

**Status:** v1 (2026-10-02).

Testing for this project is the machine-global `~/.claude/standards/testing.md`
plus `~/.claude/standards/languages/python.md`, read in place rather than
copied. This file holds only where this project differs, each with one line of
why. **Those files are on the author's machine and not in this repository**, so
a contributor reads this file plus `CONTRIBUTING.md`.

## T1 — Never touch the real environment

A test may not read or write the user's real `~/.config/localwebservermanager/`,
nor read, write or launch any project in a configured scan root other than this
repository. Config paths are injected, every fixture builds its project tree in
its own `tmp_path`, and `tests/conftest.py` pins every `XDG_*` variable the code
reads to a directory the test owns. Reading and writing inside its own
`tmp_path` is not the I/O the global unit-test row forbids.

Why: this app supervises the user's real servers. A test that starts one is a
side effect, not a test.

## T2 — Spawn real processes, of fake projects

Process supervision is tested by spawning real children from throwaway
launcher scripts generated in `tmp_path` (`write_launcher` in
`tests/test_supervisor.py`), never by mocking `subprocess`.

Why: the behaviour under test is the operating system's — process groups,
signals, exit codes, orphaning — and a mock would test the mock.

## T3 — Ports come from the OS, never from a literal

A test that binds a port binds `0` and asks the socket what it got
(`free_port` in `tests/test_supervisor.py`, the `listening_socket` fixture in
`tests/test_ports.py`). A literal port is allowed only where nothing is bound:
fake probe data, or a value whose rejection is the assertion.

Why: a hard-coded port fails on a machine where something holds it, and can
pass for the wrong reason.

## T4 — Wait for conditions, never for durations

Poll for the actual condition — port bound, process exited, signal emitted —
with a generous ceiling and a clear timeout message: `qtbot.waitUntil`,
`qtbot.waitSignal`, or `wait_until` in `tests/test_supervisor.py`. Do not
`time.sleep` for a fixed time and then assert.

Why: process start-up time is the flakiness this codebase is most exposed to.

## T5 — Every test kills what it started

Fixtures tear down with the same process-group signalling path production
uses. A test that leaks a process fails even when its assertions pass.

Why: a leaked child holds a port and poisons every later test in the session.

## T6 — Headless is the default

Core modules (scanner, registry, ports, supervisor) import no widgets and need
no display. Widget tests use `pytest-qt` under `QT_QPA_PLATFORM=offscreen`,
set by `tests/conftest.py` and `scripts/local-ci.sh`. A test that takes `qtbot`
or `app_font` carries the `gui` marker, on the test or through the module's
`pytestmark`. If a test needs a visible window to pass, the code it tests is in
the wrong layer.

Why: CI has no X server, and the layering keeps the core testable without Qt.

## T7 — The state table is a parametrised test

The derived states of ADR-0004 get one parametrised test whose cases are named
after the states, so a new state cannot be added without a case appearing. Not
met yet: the classifier that derives them is LWSM-1011, and the test lands with
it.

Why: ADR-0004's state table is the app's core contract.

## T8 — Accessibility has tests, or it is decoration

Four headless checks, each failing rather than warning:

- **Contrast** over every theme: text pairs at least 4.5:1, state indicators at
  least 3:1, and text pairs in the high-contrast palettes at least 7:1.
  Parametrised across themes, so adding a theme that fails fails the build.
- **Keyboard reachability**: every action is reachable by Tab and activatable
  by keyboard, in visual order.
- **Accessible names**: every interactive widget has a non-empty accessible
  name, and every state is exposed as text, not only as a colour.
- **No clipping at 200 %**: no cell is narrower than the string it renders.
  Deliberate elision is allowed if the full string is in the tooltip and the
  accessible name.

Why: the app is keyboard-first and themeable, and a palette regression that
only warns ships.

## T9 — Every fix proves its test red by breaking the fix

For every `fix`, `audit-fix` and `review-fix` change — whether or not the test
was written first — break each part of the fix on purpose and confirm a test
goes red:

1. Copy the file to `build/`.
2. Break one part with an exact-count replace, so a pattern that matches
   nothing, or matches twice, is caught rather than silently skipped.
3. Delete the module's stale `.pyc`, or run with `PYTHONDONTWRITEBYTECODE=1`,
   and run the covering tests by name. Red is exit 1 with a named test failed;
   exit 5 means the name matched nothing.
4. Copy the backup back, confirm with `cmp` that it is byte-identical, and
   delete the backup.

Never restore with `git checkout`: it destroys uncommitted work. Where one
change fixed several sites, break each site separately. A source-invariant test
(T10) counts once for every site it reads. Record the breaks and their results
in the commit body.

Why: stricter than the global § 2, which asks for this proof only for a test
that arrived late and records nothing. Here a test can name a fix and still
assert the wrong end of the call.

## T10 — Source-invariant tests

A test may read a module's own source and fail on the shape of a past defect
(`tests/test_registry.py::test_no_file_sourced_value_is_interpolated_without_the_clip`,
`tests/test_layering.py`, `tests/test_docs.py`). This kind is exempt from the
global § 3 and from § 10's ban on mirroring the implementation.

Write one when the mechanism has three or more call sites, or when the same
shape is found a second time. A refactor that meets that trigger owes one,
despite the global § 8.

Its rules:

- Match the shape, never a line count or a file hash.
- Exclude comments.
- Name the test for the invariant, not the regex.
- Scope it to one module, with one test per module holding a site. The
  exception is a convention every test file keeps, such as T6's `gui` marker,
  which the check reads from the test files.

Why: it turns a sweep found by review into a gate.

## T11 — Markers and speed

Registered markers live in `pyproject.toml`:

- `integration` means the test spawns a real child process or binds a real
  socket. It goes on tests, and it is what `./scripts/local-ci.sh --fast`
  deselects.
- `gui` selects nothing and may be set by a module's `pytestmark`.

An unregistered marker fails the run through `filterwarnings = ["error"]`, not
through `--strict-markers`. There is no `fast` label. A marker never excuses a
slow test, so a slow correctness test stays in every gate.

Why: overrides the global § 5 and `python.md`'s labelling, which would let a
slow correctness test drop out of the quick run.

## T12 — Invariants and tests cite each other

A feature's contract is its spec in `docs/specs/`. Each invariant names its
test in a `*Test:*` clause, and each test names its invariant (`INV-3 of
LWSM-1006`) in its name or docstring.

Why: overrides the global § 4, which links one way only. Here the specs are
the contracts, and the global `spec-format.md` § 3.7 binds them in full.

## What checks this

| Rule | What checks it |
|---|---|
| T1 | Partial: the autouse fixtures in `tests/conftest.py` pin every `XDG_*` — nothing catches a test that walks a sibling project by path |
| T2 | nothing — a reviewer |
| T3 | nothing — a reviewer |
| T4 | Partial: the polling helpers exist — nothing flags a duration sleep, and some tests still use one |
| T5 | Partial: `tests/conftest.py::_no_orphans_outlive_the_run` fails the run on a process left under its temp directory — nothing catches a leaked socket or a stray elsewhere |
| T6 | Partial: `tests/test_layering.py::test_every_test_needing_a_qt_application_carries_the_gui_marker` and `::test_core_never_imports_qtwidgets` — they miss a class-based or indirect-fixture Qt test |
| T7 | nothing — the test does not exist yet |
| T8 | `tests/test_theme.py` (contrast, per theme); `tests/test_mainwindow.py::test_every_action_is_reachable_by_tab_in_the_order_it_is_read`, `::test_every_interactive_widget_has_a_name_a_screen_reader_can_read`, `::test_nothing_is_clipped_at_two_hundred_percent` |
| T9 | nothing — the commit-body record is the only trace, read in review |
| T10 | nothing mechanical — the tests are the checks; whether the trigger was met is a reviewer's call |
| T11 | Partial: `filterwarnings = ["error"]` makes an unregistered marker a collection error; `tests/test_ci_contract.py::test_the_hook_runs_the_same_gate_and_does_not_shortcut_it` keeps `--fast` out of the push gate — nothing catches a misapplied marker or a slow test |
| T12 | Partial: `spec_lint` (an Ants MCP verb) reports an invariant with no test clause — nothing checks that the test cites the invariant |
