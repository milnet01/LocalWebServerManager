# Traps

Moved word for word out of `CLAUDE.md` on 2026-10-01, to keep the
always-loaded instructions under Claude Code's size limit.
`CLAUDE.md` § Module map points here and still holds the rules.

**Trap: a `testing.md § T9` mutation that removes ONE of several
redundant guards proves nothing.** LWSM-1006's byte cap is checked in
three places — the `fstat`, the bytes `_read_bytes` actually read, and
`_read_lines`' running total — deliberately, so a file that grows
between the fstat and the read is still refused. Deleting any one left
the test green, which reads exactly like "the bound is untested" and is
not what it means. **Mutate the whole mechanism, not one line of it**;
and mutating the *constant* instead is worthless whenever the fixture
derives its own size from that constant. Hit 2026-08-08 — two of the
four prescribed mutations came back green on the first attempt, and one
of them was a genuinely dead assertion (a tail reading `xxxPORT=9999`,
which rule 1's left boundary rejects anyway, so the discard logic it
claimed to test could be deleted).

**And a mutation *prescribed by a review bullet* can be inert — run it and read
the output before trusting the bullet.** LWSM-1126 asked for `*sorted(
dependencies)` to be appended to the scanned lines and stated the result becomes
port 7. `dependencies` is a set of **keys**, so what gets scanned is `get-port`,
which holds no digits: the mutant ran and the suite stayed green. A fold-in
bullet is a reviewer's reading of a mechanism, not a measurement of it — four
times across FP05 and FP06 a bullet has been wrong about its own mechanism, in
both directions. **Also check the fixture can express the hazard at all**: the
same item's dependency pair had to be pretty-printed onto its own line, because
in a minified `package.json` rule 2 stops at the document's first `:` and never
reaches it.

**A mutation YOU write can be inert too, and a shell loop is where it happens.**
LWSM-1155 ran seven mutants through a bash helper driving `python3` string
replacements; **two came back green without having been applied.** One meant to
*move* `hops += 1` and instead *deleted* it, so the counter never incremented
and the test passed for a reason unrelated to the mutation. The other never
applied at all — the pattern held quotes and backslashes the shell mangled
before `python3` saw them. Both read exactly like "the mutant survived", which
is the conclusion *"this code is untested"* — the same false confidence the
mutation was run to remove, arrived at from the opposite side. **Assert the
anchor matched before running the test** (`assert t.count(a) == 1`), and prefer a
heredoc'd `python3` over shell-interpolated arguments for anything holding a
regex. A mutant that reports green without having been applied is worse than no
mutant, because it is counted.

**And an anchored EDIT needs two guards, not one — `t.count(a) == 1` is only
the first.** Two shapes cost a cycle each on 2026-08-21 while shipping
LWSM-1148. **An "already applied" sentinel must name a SYMBOL, never the item
id**: `assert "LWSM-1148" not in t` refused a file whose only mention of the id
was a docstring the same run had written one call earlier — which reads as
"this is already done" and is the opposite of the truth. Guard on
`"def export_profile" not in t`. And **assert the replacement differs from the
anchor** (`assert repl != anchor`) — a mutation that is textually a no-op
applies cleanly, reports green, and is counted as a survivor, which is the
LWSM-1155 failure reached from a third direction. Both are one line, and both
fire before anything runs. **The anchor itself is the third case and it is
self-announcing**: prose here is hard-wrapped at ~70 columns, so an anchor
pasted as one logical sentence matches zero times. That one is safe — a zero
count stops the run — which is exactly why the two above are worth writing
down and it is not.

**A `mutation_probe` that times out has NOT told you the file's state.**
Measured 2026-09-03: the transport gave up with no envelope, a grep a moment
later still showed the mutation applied, and a read seconds after that showed
the file restored — the server finished after the caller stopped waiting, and
`restored_clean` only ever arrives in the envelope the timeout destroyed. **After
a timeout, re-read before concluding anything, and never hand-repair from one
observation**: a repair races the server's own restore, and a gate or commit
inside that window ships the mutant (LWSM-1296).

**Trap: a scanner fixture cannot tell you what a matcher does to files nobody
wrote for it — the author's own sibling projects can.** `/mnt/Games/Scripts/Linux`
holds the real population this app scans: 7 projects across all five launcher
kinds, detected live by `scanner.scan([root], units=FakeUnits({}))` in about a
second. **Diff the verdicts across a change** — dump `name/kind/port/source` per
project before and after, and read every line that moved. On LWSM-1155 exactly
one moved, and that is the evidence the change was surgical; no test count can
say that. Then **read every hit the new matcher produces over those same files**:
that pass found three defects no fixture had asked for, including `\bimport\b`
matching inside `not-an-import` (a `-` is a word boundary, so a presence test
fires on any line carrying the word beside a quoted relative path) and a
`from ..up import x` whose stripped dots became a **root-level `up.py`** — not a
refusal but a *different file*, read and believed.
**`tests/scanner_fixtures.py` is the regression corpus and is a different tool**:
it locks what we already know, and by construction contains only hazards someone
thought of. The live tree is the only thing here that answers *what else did this
match?* — it is also the only source for a magnitude, and it is where
`MAX_IMPORT_HOPS = 8` came from (a real launcher's three relative imports).
**Read-only and someone else's**, so never write to it, and expect its contents
to drift — quote a measured number with its date, as the traps above do.

**Trap: `ruff format` formats fenced ` ```python ` blocks inside
Markdown**, and `local-ci.sh` runs it over `.`. A spec with code
blocks fails the gate until they are ruff-formatted. Run
`uv run ruff format docs/specs/<file>.md` after writing one.

**Trap: an exception escaping `QRunnable.run()` is swallowed by
PySide6.** Verified against the pinned 6.11.1 on 2026-08-06: the
traceback prints to stderr, the process survives at exit 0, and **no
signal is emitted** — so any state the task was meant to clear stays
set. This is what makes an unhandled probe error freeze the poll loop
permanently rather than crash (LWSM-1069). Any `run()` body needs a
catch-all that still reports, not just the exception it expects.

**The same swallowing applies to a SLOT Qt invoked, which changes how a test
must assert.** Measured 2026-08-31 (LWSM-1176): a `KeyError` raised inside a
`QAction.triggered` handler printed "Exceptions caught in Qt event loop" and
the test carried on. So `pytest.raises` sees nothing and a test written as
"this must not raise" passes against the defect. **Assert the observable
instead** — there, the status-bar message the handler exists to show, which
was empty precisely because the handler died. A slot called DIRECTLY from
Python still propagates, so the same defect reaches you two ways depending on
how the test reaches it.

**Trap: `setAccessibleName("")` does not hide a widget from the
accessibility tree.** `QAccessibleDisplay` falls back to
`QLabel::text()` when the accessible name is empty, so a decorative
label is still announced — verified by querying the live interface,
which exposes the glyph as a named child (LWSM-1071). To exclude
something from a screen reader, paint it or merge it into a labelled
sibling; do not blank its name. **Assert against the AT tree's
children**, not only the parent's accessible name, or the test cannot
see this.

**Trap: a `QComboBox` ignores `setAccessibleName` altogether.** Its
accessibility interface reports the CURRENT TEXT as its name, and ignores
the item's `AccessibleTextRole` too; the description is the field it passes
through. Measured 2026-09-25 (LWSM-1315): "Browser for <project>" had never
reached a screen reader, while a test reading `box.accessibleName()` stayed
green. **Assert on `QAccessible.queryAccessibleInterface(widget).text(...)`,
never on the widget property** — the property is what you set, not what is
announced.

**Trap: a stale `.pyc` can make a green run report on code that is not
on disk.** Python's default bytecode invalidation compares only the source's
**mtime and size**, so a same-second edit-and-revert whose replacement text is
the same byte length leaves the stale bytecode looking valid. Observed live on
2026-08-06: a constant read `400` from an import while the file, `git status`
and `git show HEAD` all said `120`; clearing `__pycache__` restored it. Clean
tree, empty diff, passing suite — nothing visible is wrong. `local-ci.sh` now
exports `PYTHONDONTWRITEBYTECODE=1` so the gate can never trust a `.pyc`
(LWSM-1110); **do the same (`PYTHONDONTWRITEBYTECODE=1 uv run pytest`) or clear
`__pycache__` before believing any ad-hoc measurement**, because the gate's
guard does not cover a bare `pytest` you run yourself.

**Trap: monkeypatching a Qt virtual method after the widget exists does
nothing.** PySide6 decides whether a Python override exists when the object is
*constructed*, so `monkeypatch.setattr(ProjectRow, "paintEvent", spy)` on an
already-built row is never called and the test silently measures nothing. Two
routes that do work: substitute a subclass for the *name the code constructs*
(`monkeypatch.setattr(mainwindow, "ProjectRow", CountingRow)`) **before** the
window is built, or — for a method you merely *call* rather than override, like
`update()` — set the spy on the instance, since `ProjectRow` is a Python class
and `self.update()` finds the instance attribute first. Hit on 2026-08-07 while
writing LWSM-1109's repaint test.

**Trap: a Qt CONTAINER does not carry the property its children carry, and
`QDialogButtonBox` is the case that bites.** Its own `focusPolicy()` is
`NoFocus` while the Ok and Cancel buttons inside it are focusable, so an
accessibility test that asks the box reports the two most important controls in
a dialog as keyboard-unreachable. Measured 2026-08-21 on LWSM-1018's first run.
Ask `box.button(QDialogButtonBox.StandardButton.Ok)`, not the box. The general
form is worth more than the instance: **when asserting a property for
accessibility, assert it on the widget that actually receives the
interaction** — the same lesson as the `setAccessibleName("")` trap above,
where the answer was also to read the AT tree's children rather than the
parent.

**Trap: a Qt object held only through an inlined attribute access is deleted
mid-test.** `box = getattr(build(qtbot), "_poll")` drops the last Python
reference to the dialog as the expression ends, PySide destroys the C++ object,
and the next call on `box` raises `RuntimeError: Internal C++ object already
deleted` — which reads as a bug in the code under test rather than in the test.
`qtbot.addWidget` does **not** save you: it registers the widget for cleanup,
not for ownership. Bind the parent to a name and keep it alive for the whole
test. Hit 2026-08-21 on LWSM-1018.

**Trap: `qtbot.waitSignal` must be armed BEFORE anything that emits
synchronously.** Completing a `Future` on the main thread runs its
done-callback inline, so a signal emitted from that callback has already been
and gone by the time a wait armed afterwards starts listening — and the
failure is a timeout, which reads as "the code never emitted" rather than
"the test looked too late". Put the triggering call INSIDE the `with`. Cost a
cycle on 2026-08-31 (LWSM-1191), where the emit being tested was the fix.

**Trap: `QCoreApplication.installTranslator` only broadcasts once the event
loop is running**, because it is gated on `is_app_running`. With no `exec()`,
no `LanguageChange` is posted anywhere and a translator test sees nothing
happen. Worse, and unexplained after four probes on 2026-08-07: with the loop
running and the window the only registered top-level widget, `installTranslator`
returned `True` and Qt still did **not** post the event to `MainWindow`, while a
bare `QMainWindow` in the same shape did receive it. So a language test must
send `QEvent.Type.LanguageChange` by hand and say what it therefore does not
prove — see `test_a_translator_installed_later_reaches_an_existing_row`.

**Trap: `pathlib` metadata calls raise on a directory you cannot enter.**
`Path.exists()`, `is_symlink()`, `is_file()` and `is_dir()` swallow only
`ENOENT / ENOTDIR / EBADF / ELOOP` (`_IGNORED_ERRNOS` in
`/usr/lib64/python3.13/pathlib/_abc.py`). **`EACCES` and `ENAMETOOLONG` are
re-raised** — this is not the older behaviour where `exists()` returned `False`
for anything it could not stat, and code written against that memory is wrong
on 3.13. Found 2026-08-12: four such calls in `scanner.py` sat outside any
handler, and one `chmod 000` directory in a scan root returned **0 of 20**
healthy projects. **This is the fourth shape of the same class** — a
non-`OSError`-shaped, or unguarded-`OSError`, exception escaping a per-item
loop and taking the whole batch with it, after `{"dependencies": 5}` →
`TypeError`, a non-total `properties()` → `KeyError`, and a NUL byte →
`ValueError`. Three earlier fixes each closed one instance and none closed the
class. **When a loop processes untrusted items, contain per item and prove it
with a hostile fixture**; do not add a fifth guard to a fifth call site.

**Trap: a suite can be 370-green and still not hold its own contract.** 81
mutants against `scanner.py` on 2026-08-12: 47 red, **34 green**. Three clauses
the spec calls load-bearing were correct in the code and protected by nothing —
`_BudgetExpired` not subclassing `OSError` (under which a timed-out scan
reports `timed_out=False` and claims completeness), the `package.json`
dependency-block scope, and rule 1's execute-bit precondition, whose line never
executed in any test. **Coverage found what reading did not**: `scanner.py:943`,
`:295`, `:326`, `:904` and `:1213` were all in the miss list, and the last is
the *per-candidate* half of a deadline whose per-line half does all the work.
Before believing an invariant is held, mutate it — and check the line runs at
all.

**Trap: a supervisor test that fails before its own `stop()` leaves a real
process running on the developer's machine.** `Supervisor.close()` deliberately
does **not** signal anything — ADR-0003 leaves servers running on manager exit —
so a fixture that only calls `close()` is correct for the app and wrong for a
test. Found 2026-08-14: five orphans (`/bin/sh ./start.sh`, `child.py`) survived
from two runs where an intermediate version of a test failed mid-way, and they
were still holding their ports **2.5 hours and ~85 test runs later**, reparented
to pid 1 with their pytest tmpdirs already deleted. **A supervisor fixture must
stop everything it started before closing** — `for path in sup.running():
sup.stop(path, grace=0.5)` in a `finally`, which is what `tests/test_supervisor.py`
now does. `conftest.py`'s `_no_orphans_outlive_the_run` fails the run on any
survivor (LWSM-1189), and it matches by the process's **cwd under the run's own
temp directory**, never by command line.

**Trap: stopping a child that has not finished STARTING leaks its grandchild,
and `stop()` reports success.** `killpg` sweeps the group as it stands at that
instant, so a server the launcher forks a microsecond later never joins the
sweep — it is reparented to init and outlives the run, while `StopOutcome`
comes back clean and the test passes. Measured 2026-08-24 on LWSM-1167: one
orphan per run from a test that called `stop()` on the line after `start()`.
**The code is not at fault and changing it would be wrong** — the real app
polls before it offers a Stop button, so it never asks this. **A test must wait
for the launcher to signal that it has spawned**, which means a launcher that
backgrounds the real process FIRST and touches a file second (`await_ready` in
`test_supervisor.py`), so the file existing proves the grandchild exists. A
bare sleep only makes the race less likely, and a *shorter* sleep in the
launcher is worse than useless: the orphan then expires on its own and the
orphan check goes quiet while the defect stands.

**Trap: a one-row fixture cannot see a per-row bug.** Hit on 2026-08-14
mutation-testing LWSM-1016. Every window fixture in `test_mainwindow.py` built
**one** project, so a `lambda` closing over the loop variable — which makes
every row's buttons drive the *last* project in the list — passed the whole
suite. Four of six mutants survived that first pass and each was a genuine gap:
the closure, no test reaching the two overlay states at all, a mutation that
had not applied cleanly, and one that could not be caught because the code was
equivalent. **When a widget is created per item, at least one fixture must have
two of them**, and the assertion must name which one it expects.

**Trap: `psutil.wait_procs` reaps a process that is your own child.**
It calls `Process.wait()`, which for a direct child is `os.waitpid` — so
waiting on the stop set collects the managed child's status mid-sequence,
frees its PID for reuse, and `Popen.wait()` afterwards returns `0` instead
of the real exit code (`Popen._try_wait` swallows the `ChildProcessError`
and reports success). ADR-0003 forbids reaping until the sequence ends
precisely because that PID is in use as a process-group id. `supervisor.py`
polls `is_running() and status() != ZOMBIE` instead — a zombie is unreaped,
which is exactly the state that keeps the PID reserved.

**Trap: a "we did not reap too early" test is vacuous against a child that
ignores SIGTERM.** Hit on 2026-08-14 while mutation-testing LWSM-1009. The
test asserted `Popen.returncode` stayed `None` through the wait loop; with a
launcher holding `trap '' TERM`, a premature `poll()` finds the child still
running and reads `None` anyway, so the assertion held whether or not the rule
did — the mutant survived. **The launcher must die *during* the window the
property covers.** Same family as the § T9 note above: eleven of twelve
mutants died on the first pass and the twelfth was the one that mattered.

**Trap: a method with no production caller looks exactly like a working one,
and its own unit test is what hides it.** `Supervisor.rotate_if_needed`
implemented `design.md § Observability`'s "capped at 5 MB with one rotation"
correctly and was called by **nothing** outside `tests/test_supervisor.py` — so
the cap was green, documented in two places, and absent from the shipped build
(LWSM-1136, found 2026-08-15, fixed 2026-08-19). A chatty server appended to an
`O_APPEND` descriptor until the disk filled. **The test could not have caught
it**, because a test that invokes the mechanism directly asserts the mechanism
and never the wiring — and green is what you were expecting either way. **When
a method's whole value is being CALLED from somewhere, the test must drive that
caller**, not the method: LWSM-1136's replacement drives `poll_once` against a
real `Supervisor` and a real child. And `find_caller` on the symbol is the
cheapest way to ask; one caller, in a test file, is the tell. Same family as
the `semgrep` and stale-`.pyc` notes above — a mechanism that ran nothing looks
exactly like a mechanism that found nothing to do.

**Trap: a green test can be holding the defect in place, and it reads exactly
like coverage.** Two shapes, both measured here. LWSM-1162's escaping-symlink
refusal was unreachable from `start()`, and a test asserted precisely that, by
name, with a docstring explaining why it was right — fixing the code turned a
green test red, which is the only reason anyone looked. LWSM-1184's was
stronger, because nothing was wrong with the test: `project-e` pinned "the port
is two hops out, and exactly one hop is followed" as **an honest limit rather
than a bug**, and that limit was the thing the user filed as the defect.
**When a change reddens a pre-existing test, read what the test CLAIMS before
assuming the change is wrong** — a fixture can encode a limit that has since
stopped being one. Then say so where it is visible: the fixture moves, the
reason moves with it, and something narrower takes its place holding whatever
bound is left (`project-e-deep`). Silently editing a fixture to go green and
silently backing out a correct change are the same mistake from opposite
sides. The inverse of the LWSM-1136 trap above — there a test asserted a
mechanism nothing called, here one asserted a mechanism that was no longer
wanted.

**Trap: a fold-in bullet's LINE NUMBERS go stale while its reasoning stays
exact — search for the expression, never open the cited line.** Every FP09
bullet closed on 2026-09-06 cited lines that had since moved, and every one of
them described its defect correctly, down to the Qt call responsible. Opening
the cited line reads as "the bullet is wrong" and is the fastest way to dismiss
a real finding. Grep for the code it quotes instead. **And count the sites
before fixing one**: two of those bullets named a single location where the
identical expression appeared twice in the same file, and in both cases the
unnamed twin was the one no test covered. The corollary to the trap below —
the bullet is usually right about the mechanism and unreliable about where.

**Trap: a fold-in bullet's stated CAUSE is a reading, not a measurement, and it
has now been wrong six times.** LWSM-1184 was filed as "the launcher uses an
ordinary import rather than the relative form the walk follows" — and
`_import_specifiers` already resolved the dotless form; the walk was simply
never wired into the shell launcher's hop. LWSM-1168's supervisor half
reproduced exactly as filed while its UI half named the wrong branch entirely.
**Reproduce before designing, and prefer an instrument to an argument.** Two
that pay for themselves in one run here: patch `scanner._open_source` to
record every path a live scan opens, which answers "where did it stop?"
outright; and diff live-tree verdicts across the change, which is the only
thing that catches a SECOND project with the same defect (LWSM-1190's
MAME_Curator) or proves a change surgical. Neither is expensive. Both have
overturned a bullet the same session it was read.

**Trap: a concurrency test that issues two calls back to back proves nothing
about a check-then-act.** Python serialises the two threads on the GIL often
enough that the loser arrives after the winner has finished, so the broken code
passes. **The first call has to be HELD OPEN inside the window** — which means
knowing where the window is: for `Supervisor.start` (LWSM-1137) it is between
the lock being released and the registry insert, so the first start is parked
inside the trust gate by patching `trust.is_confirmed`. Assert the outcomes,
not the timing. The same shape applies to `stop()` (LWSM-1138), where the two
overlapping calls come free from the stop pool's own `max_workers=4` and the
assertion belongs on the **descriptor** rather than on the `StopOutcome` — two
plausible-looking outcomes is exactly what the broken version returned.

**Trap: to prove an fd-reuse hazard, make the reuse HAPPEN — a test that only
asserts the fix's shape proves nothing.** LWSM-1169's two tests run a real
`stop()` from inside the rotation's window, then `os.open()` a sentinel-filled
bystander file: lowest-free-fd means it takes the number `stop()` just freed,
and the pre-fix code truncates that bystander to zero. **Assert the steal
happened** (`stolen == managed.log_fd`) or the test passes for a reason
unrelated to the defect. Where the fix holds a lock across the window, the
`stop()` must run on its own thread with a BOUNDED join, or the test deadlocks
instead of failing. Same family as the held-open note above — the window has to
be entered, never raced for.

**Trap: a fixture set that only exercises one branch of a four-way split.**
Every `start()` test in `test_supervisor.py` used `("./start.sh",)`, so the one
launcher kind that works was the only one tested — and `_launcher_path` refusing
`npm`, `python3` and `node` outright survived 494 green tests and shipped as
"success criterion 2 closed end to end" (found 2026-08-15, `FP07`/LWSM-1132).
This is the **one-row-fixture trap one layer up**: there, one row could not see a
per-row bug; here, one launcher kind could not see a per-kind bug. **When code
branches on a closed set — launcher kinds, states, schema versions — at least
one fixture must exist per member, and a test that names the branch must say
which member it drives.** The same pass found no fixture with `port=None`, which
is what hid an overlay that can never settle.

**Trap: `semgrep` silently excludes test directories, and its zero has been read
as whole-tree on five closes.** It ships a default ignore list covering
`tests/`, so `semgrep --config p/security-audit src tests` scanned **11 files,
all under `src/`** (measured 2026-08-15). Nothing in the output says `tests/` was
skipped. Report semgrep's result as a statement about `src/` only, or pass an
explicit file list. Same family as the `actionlint`/`yamllint` shared-flag bug
and the stale `.pyc`: **a tool that analysed nothing looks exactly like a tool
that found nothing.**

**Trap: an exit status can report the TRANSPORT and not the operation.**
Measured against real KWin on 2026-08-25 (LWSM-1170): `dbus-send` exits 1 with
`ServiceUnknown` on stderr when nothing owns the destination — and exits **0**
for a `loadScript` naming a file that does not exist, and for an `unloadScript`
of a name never registered. And a `loadScript` under a name that is still
loaded is REFUSED in the reply (`int32 -1`, measured 2026-10-01) while the
status is still 0. So the status says the call landed and nothing
more, and a check written as "did the load succeed?" asks a question the tool
never answers. **Measure what a nonzero status actually means before building a
check on it**, and say in the code what it does not cover. Third costume of the
family above: a call that did nothing looks exactly like a call that found
nothing to do.

**Trap: `.editorconfig`'s blanket `[*]` section is not a declared shell style**,
so `shfmt` has no config to run against here and must be reported as skipped
rather than run against its own tab default — which would diff every 4-space
shell file in the project as malformed.

**Trap: `subprocess.Popen` resolves a bare `argv[0]` against the PASSED
`env`'s `PATH`, not the parent's.** Verified 2026-08-17. So
`build_child_env`'s allowlist is load-bearing for *launching*, not only for
keeping secrets out of the child: drop `PATH` from `ENV_ALLOWLIST` and every
`npm` / `node` / `python3` launcher stops resolving — while the shell kind,
whose `argv[0]` is `./start.sh`, keeps working. That is the same
one-branch-in-four blind spot LWSM-1132 shipped behind, so a change to the
allowlist must be tested against a fixture per launcher kind and not just
against `./start.sh`.

**Trap: under Wayland a client can SET its window position and can never READ
one — and the two look like one feature.** ADR-0007 treated "Wayland discards
the position" as a *restore* problem that a KWin script closes. It is also a
*capture* problem that nothing closes: Wayland gives a client no global
coordinates, so Qt answers 0,0 forever. Measured 2026-08-21 — KWin reported
the app's window at 640,480 while Qt reported 0,0, and **0,0 is a plausible
position rather than an error**, so it was written to `settings.json` as though
the user had put the window in the corner. This is the deeper reason
`saveGeometry()`/`restoreGeometry()` loses position there, and why KDE's own
apps save size and let KWin place. So a Wayland session records size and
maximised state and **leaves the stored coordinates alone**; a position
recorded under X11 or typed in by hand is still restored there. Position and
size are therefore stored and passed as **separate pairs, never one
rectangle** — joined, the unknowable half takes the knowable half with it.

**Trap: three things about the KWin placement path were settled by measuring,
and each had a plausible wrong answer that reasoning reached first.** All
against real KWin, Plasma 6 Wayland, 2026-08-21, and all invisible to the test
suite because the tests substitute a stand-in for the compositor that honours
whatever it is handed whenever it is handed it. **The delay:** ADR-0007's "one
event-loop tick after the window is shown" fails outright; 50 ms works, the
first `Expose` alone still fails, and `Expose` **plus one tick** worked 5/5 —
so the trigger is that condition, not a number. **The size:** KWin's geometry
write is authoritative, so a script that preserves the current size by reading
`c.frameGeometry.width` back pins the window at whatever KWin currently
believes — a 700x500 window came back at its undecorated minimum of 239x216
with the position exact, and swapping the order does not help because it is
not a race. **The decoration:** converting a client size to a frame size in
the app sends 0 for the margins, because the window is not decorated yet when
placement runs; `c.clientGeometry` inside the script is where the answer is.
**The general lesson is the one ADR-0007 already states and this proved twice
over: for anything the compositor owns, a green suite is not evidence — run
the app and ask KWin where the window went.** A KWin script's `print()` reaches
`journalctl --user -u plasma-kwin_wayland`, which is how all of this was read.

**Trap: `setToolTip("")` does not remove a `QAction`'s tooltip.** Qt falls
back to the action's own **text**, so an entry meant to carry an explanation
only when disabled reports its label the rest of the time — and a test
asserting `toolTip() == ""` fails against correct code. Exactly the
`setAccessibleName("")` trap above in a second costume: **an empty string is
not an absent value in Qt.** Assert what is actually there.

**Trap: a default argument bound to a module function cannot be monkeypatched.**
`def f(which=shutil.which)` captures the function object when `f` is *defined*,
so `monkeypatch.setattr(shutil, "which", ...)` never reaches it and the test
silently measures the developer's real machine. Cost a cycle on LWSM-1033 and
then nearly cost a second one in `MainWindow.__init__`, where the same shape
decided whether a `build_window` test could keep its hands off the live
compositor. **Default the parameter to `None` and resolve it in the body.**

**Trap: `git checkout <file>` on work that is not committed yet destroys it.**
Used to revert a hand-applied mutant mid-session on 2026-08-21, it reverted the
file to HEAD and took every uncommitted LWSM-1033 edit in `mainwindow.py` with
it — about an hour's work, recovered only because it was still in the session's
context. The mutation harness itself was never at risk: it holds the original
text in memory and writes it back in a `finally`. **Restore from a copy you
made, never from git, while the work is uncommitted** — and the cheaper habit
is to commit before starting a mutation run at all.

**Trap: `QIcon.fromTheme` returns a null icon under `QT_QPA_PLATFORM=offscreen`.**
The icon theme search paths are populated by the *platform theme plugin*, so
under `offscreen` `QIcon.themeSearchPaths()` is `[':/icons']` and
`themeName()` is empty — every theme lookup misses, including one whose file
is definitely installed. Measured 2026-08-18 while shipping LWSM-1142: the
same lookup returned a 128px SVG under the real Wayland session and null under
`offscreen`. **`conftest.py` sets `offscreen` when unset, so any test
asserting an icon resolves by theme name fails in the suite and in CI for a
reason that says nothing about the icon.** Assert the file is installed where
the theme expects it, or inject the icon; do not assert `fromTheme`.

**Trap: a hand-built `QStyleOption` does not reproduce the state it names, and
it will tell you a control is unstyled when it is not.** This cost two wrong
diagnoses in one session (2026-09-06). Rendering `CE_PushButton` with
`State_HasFocus` set reported that no palette draws a focus ring — Qt gates
focus indication on **`State_KeyboardFocusChange`**, so a correct style draws
nothing without it, and LWSM-1238 sat blocked for days on that reading. Hours
later, clearing `State_Enabled` reported a disabled button as pixel-identical
to an enabled one, and the fix built on that reading made the two states
*harder* to tell apart. **The correction was wrong too, and that is the more
useful half**: "a real `setEnabled(False)` widget dims plainly" was measured
with no theme applied. Under one it did not dim at all, because `to_palette`'s
two-argument `setColor` wrote every token into the Disabled colour group as
well — the user's own screenshot is what settled it (LWSM-1300). **Render a
real widget in the real state AND the real context — `setEnabled(False)`,
`setDown(True)`, `setFocus()`, with the application palette and the window's
style sheet applied — and grab it.** A hand-built option is for asking a style
a question you have already checked another way; an unthemed widget answers
about an app nobody is running.

**Trap: a changed-pixel count is not visibility, and it reads as rigour.**
LWSM-1298 was filed and closed on "2175 of 2400 pixels change"; measured as
contrast that same rendering is 1.08:1 on `midnight` — invisible, every pixel
having moved by a couple of RGB units. Measure a colour change as a **contrast
ratio between the two states**, never as a population of moved pixels, and
sample the region the change lives in: a fill sample taken from a button's
interior cannot see a ring drawn at its border, which was the second half of
the same wrong answer.

**Trap: `offscreen` cannot show what a screen reader hears, but the bus
can be read directly.** The system `python3` has `gi` with the `Atspi`
typelib; the venv does not. Run a test copy of the window on a private
`Xvfb` display with `QT_QPA_PLATFORM=xcb` and
`QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1`, then walk
`Atspi.get_desktop(0)` for the child whose `get_process_id()` is that copy's
PID, printing `get_role_name()` and `get_name()`. Nothing appears on the
user's screen. Measured 2026-10-01 for LWSM-1348: Qt's `Border` role reads
as `panel` on the bus.

**Trap: "the most common colour" is not a control's fill once it has a
one-colour outline.** Fusion shades a button's fill across many near-equal
colours, so the 1 px outline `OutlineStyle` paints round the perimeter
out-counts every one of them, and a sampler taking the mode as the fill
reads the outline instead (LWSM-1337, measured 2026-10-01). Sample a fill
from inside the edge band. Related: **a child widget paints over its
parent's ring** — a list's viewport and a spin box's text field are
children drawn after the style, so a ring painted on the parent loses its
inner pixels unless the child is moved in.

**Trap: the app never loads Breeze — it resolves to Fusion.** PySide6 ships its
own Qt, so the system `breeze6.so` cannot bind to it: `QStyleFactory.keys()` is
`['Windows', 'Fusion']` on the venv interpreter and the system one alike.
Measured 2026-09-06. Any reasoning about "how this looks on the user's Breeze
desktop" is about a style this app does not use.

**Trap: a green suite, a full set of killed mutants and a passing contrast
floor can all agree on a change that is visibly wrong.** LWSM-1300's `:disabled`
rule had eight-palette coverage, five mutants all killed, and cleared every
floor — and rendering it showed it made the defect worse. It was backed out.
**For anything whose whole value is how it LOOKS, the last step is to render it
and look**; the suite can only hold the properties someone thought to assert.

**Trap: the desktop's light/dark scheme cannot be driven from a test at all —
`QStyleHints.setColorScheme` is ignored under `offscreen`.** Measured 2026-09-02
while shipping LWSM-1244: the setter returns without error, `colorScheme()`
stays `Unknown`, and `colorSchemeChanged` never fires. Nothing says it was
refused. Same family as the `fromTheme` trap above — a platform-owned answer
that the offscreen platform simply does not have — but worse in one way: the
icon case *fails*, where this one leaves a test asserting the wrong branch and
passing. **So anything reading the colour scheme needs an injected seam**
(`MainWindow`'s `read_dark`), or the whole light/dark half is unverifiable.
Set the seam, then verify the real reader against a running desktop, which is
the only place it can be checked.

**Trap: an installer that writes into `~/.local/share/icons/hicolor` can hide
every OTHER application's icons.** That directory is shared by every app that
installs a per-user icon, and it normally has no `index.theme` and no
`icon-theme.cache`. Generating a cache there does not merely speed lookup up —
once a cache exists it is treated as authoritative for that directory, so
anything it fails to list stops resolving. Measured 2026-08-18 (LWSM-1143):
one `gtk-update-icon-cache -f` produced a 1,932-byte cache over a tree of 90
icons and about seventeen of the user's pinned launchers went blank until it
was deleted and plasmashell restarted. **The `|| true` on that line gave false
comfort — it guards against the command *failing*, and the command succeeded;
succeeding was the damage.** Every check passed: `desktop-file-validate`,
`shellcheck`, the icon resolved, the entry launched. **When a step writes into
a directory shared with other software, the verification has to ask what
happened to the other software, not only to us.**

**Trap: two runs executing the same STEPS with different TOOLS is not one
gate.** `local-ci.sh` has said "the single source of truth for CI" since P01
and it was true of the step list and false of everything else. On 2026-08-18
local shellcheck 0.11.0 passed `scripts/*.sh` while the runner's apt shipped
0.9, which reports SC2015 on `command -v` guards that 0.11 accepts — **eight
consecutive red pushes against a green local run**, and four of those were
pushed after the first failure because nobody read the email. Pins now live in
`scripts/ci-tools.env`, both sides read it, and the gate reports TOOL DRIFT.
**The second lesson is smaller and cost its own red build**: the first thing
the new check found was `go install …@v1.7.12` reporting `v1.7.12` against a
release binary's `1.7.12` — the same version, spelled differently. **A version
comparison must normalise before it compares**, or its first live finding is a
false alarm and the whole check stops being believed. And **when the gate
itself changes, the only proof is a push** — both defects were found by GitHub,
not by reasoning about the YAML.

**Trap: a geometry test can pass against a window that never grows.** Three
of LWSM-1149's first-draft tests survived deleting the entire
`_apply_default_geometry` mechanism (2026-08-18): with the scroll area in
place, Qt's own default size happened to satisfy "a short list needs no
scrolling", "a long list does not grow the window" and "the minimum does not
clip a column". The second is the pure vacuous form — a window that ignores
its content passes it by never growing at all. **The fix is to pin the two
cases against each other in ONE test** (3 rows shorter than 8, 8 equal to 48),
so neither half can hold on its own. The third was worse than weak and was
dropped: the columns are fixed-width, so Qt's layout minimum already forbids
clipping one and the assertion could not fail. Same family as the § T9 note
above and the SIGTERM-ignoring launcher — an assertion that holds whether or
not the rule does. **Mutate the mechanism out before believing a geometry
test, and say which mutant each test dies on.**

**Trap: a widget's SIZE depends on the runner's default font, so a pixel-floor
test can pass locally and fail in CI.** `design-accessibility.md § Accessibility` puts a
24x24 floor under every clickable target. Qt's style derives a button's height
from the font, and on this machine that gave **25 px** — clearing the floor by
one pixel — while the GitHub runner's smaller default font gave **22**. So the
floor was breached for every user with a small system font, the suite could not
see it, and CI was the only thing that could (found 2026-08-19, LWSM-1032).
**A floor belongs in the SOURCE, not only in the assertion** —
`setMinimumHeight(MIN_TARGET_PX)`, a minimum so it still grows with the
text-size control. And **parametrise the test over the font** rather than
trusting the ambient one: the 6 pt case fails on a build with no explicit floor
whatever machine it runs on, while the ambient case passes on this one either
way. Same family as the TOOL DRIFT note above — two machines running the same
steps with different inputs is not one gate.

**Trap: a colour solved for CONTRAST alone converges on white.** LWSM-1031
derives each palette's state tokens by walking a fixed hue's lightness until it
clears § T8's floor. The first draft walked from the far end of the range and
stopped at the first pass, which on a dark palette is near-white for *every*
hue — so all eight state tokens came out `#ffffff`, perfectly legible and
carrying no state information at all. **Every contrast check passed**, because
contrast is exactly what it was solving for. Walk *away* from the surfaces and
stop at the first clear, so the token keeps as much of its hue as the floor
allows; and hold the result to a second property the first cannot imply —
`test_the_state_tokens_are_distinguishable_from_the_body_text`. Same family as
the vacuous geometry test: an assertion that holds whether or not the rule
does, here because the rule as stated was not the rule that was wanted.

**Trap: run analysis tools inside the project venv (`uv run`, or
`uv run --with <tool>`).** Bare `deptry` / `pip-audit` resolve the
*system* Python and report the project's own declared dependencies as
missing — 21 bogus findings on 2026-08-06 against a `pyproject.toml`
that declares them. Same family as `python` not being on PATH: the
output looks authoritative and is about the wrong interpreter.
