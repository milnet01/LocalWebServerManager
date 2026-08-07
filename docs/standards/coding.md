<!-- ants-coding-standards: 1 -->
# Coding Standards — v1

A shareable contract for code in this project. Pairs with the
other standards in this folder — see the [index](README.md) for
the full set.

This standard governs ROADMAP bullets with `Kind: implement`,
`fix`, `refactor`, `audit-fix`, or `review-fix`. The other kinds
(`doc`, `test`, `chore`/`release`) defer to their respective
companion documents.


## 1. Principles

### 1.1 Shortest correct implementation

50 lines beats 250. No scaffolding for hypothetical futures, no
abstractions where a direct call works, no error paths for
scenarios that can't happen at the call site. Every line pays rent
in legibility or function.

### 1.2 No workarounds without a root-cause fix

Silencing warnings, `try/except: pass`, `--no-verify`, commenting
out broken code, disabling checks — last resort, not default.
Applies to build, test, runtime, and lint failures alike. When a
workaround is genuinely the only option, leave a comment naming
the underlying constraint so it reads as deliberate, not neglect.

### 1.3 Reuse before rewriting

Before writing new code, look for existing code that does the same
or similar thing, in order of preference:

1. Call it directly.
2. Refactor it to cover the new case, then call it — existing
   call-sites benefit.
3. Only if neither fits, write new code and justify the
   duplication.

**Rule of Three:** extract a helper on the third call-site, not
the first or second. Premature DRY costs more than duplication.

### 1.4 Six-month test

If someone opens this file six months from now, can they read the
change and understand *why* the code looks this way without the
author? If not, it's too clever or too long.

### 1.5 Use latest stable library + current idioms

**Version policy lives in
[dependencies.md](dependencies.md), which is canonical** — what
counts as pinned, when an older version may be held, and what an
exception must record. Don't restate its rules here; two
standards stating the same rule at different strictness is two
rules that will disagree.

What remains this standard's business is the *code*: when calling
library APIs, use the current idiomatic syntax for the version in
use — not the one current three years ago.

For per-language idiom examples (Qt 6, C++20+, Python 3.10+,
React 18+), see `~/.claude/CLAUDE.md § 5` — that's the
canonical source. When unsure what's current, check the
library docs first. Stale idioms compile but they age the
codebase.

### 1.6 A change names the other call sites of the same mechanism

**Applies to every Kind this standard governs** — `implement`, `fix`,
`refactor`, `audit-fix`, `review-fix`. A new mechanism applied
unevenly on the day it lands is the same defect as a fix applied
unevenly later, and the shutdown bound, the stop flag and the
contrast floor below all arrived that way.

A change closes a **mechanism**, not the one call site it was reported
against. Before it is done, name the other places that mechanism is
used, and take exactly one of three outcomes:

1. **Fix them in the same change.**
2. **Say in the commit why they are out of scope.**
3. **Say the sweep found nothing** — one line naming what you looked
   for and what it returned (`swept for bare {…!r} across src/: no
   other sites`).

Outcome 3 is not optional politeness. Without it a clean sweep and a
skipped one produce byte-identical output, so the one behaviour this
rule exists to ban — "I did not look" — is the one it cannot detect,
and the rule decays into advice.

For a **helper-shaped** mechanism, finding the others is a grep rather
than a memory exercise — search for the *defect's shape*, not the
symptom: the helper that should have been called (`_quoted`), the
guard that should have wrapped it (`Path.home()`), the flag that
should have been checked (`_stopped`).

**A mechanism is not only a function**, and this is the half a grep
cannot reach. Several instances below were a *rule* applied unevenly
rather than a helper called unevenly — a bound placed on one exit
path, a guard on one of two sibling slots, a floor checked against
one of two backgrounds. You cannot search for the *absence* of a
bound. So ask "what did I decide here, and where else does that
decision apply?", and let outcome 3's line name the **enumeration**
instead of a search: the set you walked and the answer for each
(`checked both exit paths in controller.py; bound present on both`).
An enumeration you cannot state is a mechanism you have not yet
defined.

**Where the mechanism is wide or the shape has recurred, make the
sweep a test** — a source-invariant test. **`testing.md § 3.6` is
canonical for when to write one and how**; deliberately not restated
here, because § 1.5 two sections up says what two copies of one rule
do to each other.

**Why this is a standard and not advice.** Three consecutive review
passes — FP03, FP04 and FP05 — each reported this shape as their most
common finding, and FP05 found **six instances at once**: a clipping
helper applied to two fields of three, a home-directory guard present
in one module and absent in its twin, a shutdown bound placed on one
exit path, staleness handled on the exception path but not the hang
path, a stop flag checked in one slot but not its sibling, and a
contrast floor enforced against one background of two. Each was cheap
to find and cheap to fix at the time, and instead cost a review cycle
apiece.

`/apply-fixes` runs a blast-radius sweep, so a change routed through
it has already *done* the search half. It does **not** discharge the
recording: whether a change went through that skill is itself
invisible in the commit, so treating it as an exemption restores the
byte-identical output outcome 3 exists to prevent. Record the line
either way, and say where it came from
(`/apply-fixes blast-radius: no other sites`). The skill is also
local to one machine, and this is a public repository — an outside
contributor has no way to invoke the exemption or to tell whether it
was used.

**Numbering note.** This is § 1.6 rather than § 1.4 beside § 1.3's
reuse rule, where it reads better, because `README.md` and
`dependencies.md` both cite `coding.md § 1.5` and inserting ahead of it
would have silently repointed them — this rule, applied to itself.


## 2. Error handling

- **Validate at boundaries, not internally.** User input, network,
  IPC, deserialisation → validate. Internal calls → trust.
- **Don't write paths that can't happen.** If a function is only
  called with non-null input from internal code, don't add a null
  check.
- **Surface unexpected errors loudly.** Swallowed exceptions are
  loaded guns. Log + propagate, don't `except: pass`.
- **Specific exceptions over generic.** `except FileNotFoundError`
  over `except Exception`.
- **Don't write fallbacks for scenarios that can't occur.** Trust
  framework guarantees; only fall back at real failure points.


## 3. Comments

Default to **no comments**. Only add one when the WHY is
non-obvious:

- A hidden constraint (`// gpg is single-threaded; serialise here`).
- A subtle invariant (`// must run before m_grid is freed`).
- A workaround for a specific bug (`// QTBUG-79126: frameless +
  modal drops clicks on Wayland — fall back to event filter`).
- Behaviour that would surprise a reader.

Don't:

- Explain WHAT the code does — well-named identifiers do that.
- Reference the current task / fix / callers ("used by X", "added
  for Y") — those belong in the commit body.
- Write multi-line block comments or paragraph docstrings.


## 4. Naming

- **Functions** — verb phrases (`parse_rgb_color`, `apply_theme`).
- **Variables** — noun phrases (`current_tab`, `grid_size`).
- **Booleans** — `is_*` / `has_*` / `can_*` (`is_ready`,
  `has_focus`).
- **Constants** — match the file's existing style. Don't mix
  SCREAMING_SNAKE and PascalCase in one file.
- **Avoid abbreviations** except universally-known (`url`, `id`,
  `db`). Prefer `temperature` over `temp` when ambiguous.
- **No Hungarian notation.** Type prefixes (`strName`, `iCount`)
  are not naming, they are a comment that rots. The `m_` member
  prefix is fine in a project that already uses it; **this project
  does not** — plain attribute names, a leading underscore for
  private (`self._rows`).

The examples above are Python because this project is Python, and
examples are the form a reader copies — they were camelCase with
`m_` prefixes until 2026-08-07. The rules themselves are
language-neutral.

**Nothing in the gate enforces this; it is held by review.** `ruff`
selects `E, W, F, I, UP, B, RUF100, S` — **not** `N`
(`pep8-naming`) — so `def parseHeader(strName)` passes clean. That
is deliberate rather than an oversight: enabling `N` flags nine
existing sites and **every one is a Qt override that must be
camelCase** (`changeEvent`, `paintEvent`, `updateAccessibility`,
and `QTranslator.translate`'s `sourceText`). A naming rule that
fights the framework at its own boundary would be suppressed nine
times and then ignored. Measured 2026-08-07 by enabling `N` and
reading all nine.


## 5. Language-specific notes

### 5.1 C++

- C++20 minimum unless project pins higher.
- `auto` for obvious types; explicit type when the type matters
  for the reader.
- RAII for everything that owns a resource.
- `[[nodiscard]]` on factory / parser return types.
- `std::make_unique` / `std::make_shared` over raw `new`.
- Prefer `std::optional<T>` over sentinel values (`-1`, `nullptr`).
- `noexcept` on move constructors, swap, destructors.

### 5.2 Qt

- Modern signal-slot connection syntax only.
- Parent-child ownership; don't manually `delete` a parented child.
- `Q_OBJECT` macro on every QObject subclass.
- Wrap user-visible strings in `tr()` for translator compatibility.
- `QSaveFile` for atomic writes, not raw `QFile::Truncate`.
- `setOwnerOnlyPerms()` on files that contain config / secrets.

### 5.3 Python

- Type hints on every public function signature.
- Use `pathlib.Path` over `os.path`.
- `pyproject.toml` for config; no `setup.py`.
- `subprocess.run([cmd, arg])` not `shell=True` with f-strings.

(Add language sections as the project grows.)


## 6. Performance

- **Profile before optimising.** "Make it work, make it right,
  make it fast" — in that order.
- Avoid premature `O(n²)` patterns where `O(n)` fits.
- For hot paths: pre-allocate, batch I/O, avoid copies.
- Don't write a cache without measuring the hit rate first.
- Don't pessimise — use `std::move` on the return of
  rvalue-returning helpers, reserve capacity on growable
  containers when the size is known.


## 7. Security

- **Never trust user input.** Validate at the boundary.
- **No `shell=True`.** Use argv arrays:
  `subprocess.run([cmd, arg])`, `QProcess::start(cmd, args)`.
- **Atomic file writes.** Temp + rename, or `QSaveFile`. Don't
  truncate-and-write — a crash leaves an empty file.
- **Restrictive perms on secret-bearing files.** 0600 for config,
  tokens, keys.
- **Path traversal** — resolve and check `commonpath` /
  `QDir::canonicalPath` before opening user-supplied paths.
- **Argv injection** — when calling external tools with
  user-supplied filenames, prepend `--` separator and prefix
  paths with `./` if they could start with `-`.
- **Don't log secrets.** Strip Authorization headers, API tokens,
  private-key blocks before any `qDebug` / `print` / log call.


## 8. Anti-patterns

- ❌ Multi-paragraph docstrings on every function.
- ❌ "Just in case" exception handlers that swallow everything.
- ❌ Half-finished implementations behind feature flags.
- ❌ Renaming a variable to `_unused` instead of removing it.
- ❌ `// TODO: fix later` with no roadmap entry tracking it.
- ❌ Hardcoded paths / magic numbers without a named constant.
- ❌ Dead-code branches kept "just in case".
- ❌ Compatibility shims for callers that don't exist any more.
- ❌ `using namespace std;` in headers.
- ❌ `from foo import *` in Python.


## LocalWebServerManager overrides

Added at Phase C (2026-08-03). Everything above still applies;
this section adds what is specific to a Qt desktop app that
supervises other people's processes. The §5.3 Python rules are
the baseline — these are in addition.

### O1. The core never imports `QtWidgets`

`docs/design.md § Architecture` splits core from UI, and the
split is enforced by import. A **core module is every module under
`src/lwsm/` that is not `mainwindow.py` or `theme.py`** — a
criterion rather than a list, because the list was wrong: it named
`scanner`, `supervisor` and `logbuffer`, none of which exist yet
(P03 and P05 build them), while omitting `applog.py`, which does
exist and imports no Qt at all. A `QtWidgets` import in a core
module is a review failure, because import-freedom is what makes
the core headless-testable.

**A new core module is added to `tests/test_layering.py`'s
`CORE_MODULES` in the commit that creates it.** That list is what
actually enforces this, and it does not yet name every module the
criterion above covers — `applog.py` is absent from it. So the rule
and its check disagree, and the check is the one that runs.
Widening it is `LWSM-1006`'s job, since P03 is what next adds a
core module.

### O2. Nothing touches a widget off the UI thread

Reader threads and probe workers communicate **only** via queued
Qt signals. A direct widget call from a worker is a crash, not a
race you can get away with — and it is the single most likely
defect in this codebase (ADR-0003 flags it as a standing review
item). Any new thread gets its signal boundary named in the
review.

### O3. Never write into a sibling project

The Scanner reads; nothing writes. No config file, no lock file,
no marker, no log — a sibling project's directory is read-only to
this app, and that constraint is in `docs/discovery.md § Out of
scope`, not merely a convention. App state goes under
`$XDG_CONFIG_HOME/localwebservermanager/` and
`$XDG_STATE_HOME/localwebservermanager/`, each falling back to
its `~/.config` / `~/.local/state` default when the variable is
unset or not absolute. The state half is
`src/lwsm/applog.py::default_state_dir`; the config half has no
code yet and this is the rule it must follow when P09 writes it.

### O4. Every spawn is an argument vector

`shell=False`, always, with `start_new_session=True`. No
`shell=True`, no f-string command lines, no `os.system`. Paths on
paths on this machine contain spaces, so quoting
bugs are not hypothetical. This is §5.3's `subprocess` rule
promoted to non-negotiable.

### O5. Never report a state you have not observed

The app's whole value is telling the truth about what is running.
A function that returns "running" because it started something,
rather than because it observed a bound port, is wrong even when
it happens to be right (ADR-0004). The same applies to a port
holder whose PID cannot be resolved: report that it cannot be
named rather than guessing.

### O6. Qt for Python, not Qt for C++ transliterated

- New-style signals: `Signal()` / `Slot()` from `PySide6.QtCore`.
- `QSettings` is **not** used — config is JSON at known XDG
  paths, per `docs/design.md § Persistence`, so it stays
  hand-editable.
- Widget parenting owns lifetime; don't hold Python references to
  parented children solely to keep them alive.
- Check an API exists in the installed PySide6 before designing
  around it. Verified 2026-08-03:
  `QProcess.setChildProcessModifier` does **not** exist in
  PySide6 6.11, which is why ADR-0003 exists at all. A C++ Qt
  method appearing in the Qt docs is not evidence that the Python
  binding exposes it.

### O7. No literal colours, sizes or fonts in widget code

A widget names a **theme token** (`window`, `base`, `text`,
`accent`, `state_running`, …), never `#1e1e2e` and never
`QColor(...)`. It asks for the system font, never a family name;
it sizes from the text metric, never a pixel constant. A literal
colour or a pinned font size in widget code is a review failure —
it is invisible in one theme, unreadable in another, and it
breaks at 200 % text size.

### O8. Accessibility is part of "done", not a later pass

**The primary user is partially sighted and uses a screen
magnifier.** Any new interactive widget lands with all four of:

1. `setAccessibleName` and, where the name is not
   self-explanatory, `setAccessibleDescription`.
2. Keyboard reachability, in visual tab order, with a visible
   focus ring.
3. Any state it displays conveyed by **text** — colour and glyphs
   reinforce, never carry.
4. A layout that reflows at 200 % text size without clipping or
   eliding.

A widget missing any of these is incomplete, in the same way an
untested one is. Retrofitting accessibility is how it never
happens.


## Cold-eyes loop log

Rule-14 gate history for this standard. Written by `/cold-eyes` as
each loop happens, never back-filled.

| Loop | Date | Lanes | CRIT | HIGH | MED | LOW | Verified | Outcome |
|---|---|---|---|---|---|---|---|---|
| 1 | 2026-08-07 | 2 (general-purpose, strong model) | 0 | 4 | 4 | 4 | 12 verified, 0 unverified, 12 fixed | Converged. Batched run with `testing.md`; both files gained a clause in FP05 from the same pair of root causes, so gating them separately would have meant a second reviewer re-reading overlapping ground. Dimensions: dim 6×3, dim 7×3, dim 2×2, dim 15×1, dim 8×1, dim 12×1, dim 11×1. **Both lanes independently found the same three primary defects**, which is the signal worth recording: § 1.6 named no `Kind:` trigger while its companion `testing.md § T9` enumerated three; § 1.6's two permitted outcomes produced no artefact in the null case, so a clean sweep and a skipped one were byte-identical — the one behaviour the rule bans was the one it could not detect; and § 1.6's preferred "sweep test" was a shape `testing.md § 2.1` and § 9 both forbid and § 3.1's no-I/O rule excluded, with no test type admitting it. The third is the one a gate earns its cost on: the two clauses were written in the same pass, by the same author, and contradicted each other. Fixed by adding a third mandatory outcome, an explicit Kind list, a bound on when a sweep test is warranted, and `testing.md § 3.6` as a sanctioned type. Also corrected: `§ 4`'s naming examples were camelCase with `m_` prefixes in a `ruff`-enforced snake_case project, and the header said "other three standards" against five. Remaining C++/CMake residue routed to LWSM-1062, which already owns the fork reconciliation. |
| 2 | 2026-08-07 | 2 (general-purpose, strong model) | 0 | 7 | 6 | 2 | 15 verified, 0 unverified, 15 fixed | **Converged by sweep, not by dispatch.** Origin split: **11 fix collateral vs 4 draft defects**, a decisive margin on the first split, which is the documented signal to sweep loop 1's own edits rather than send a third cold read. The sweep is what this row records. Loop 1's fixes had contradicted each other in four places, all in § 1.6: the `/apply-fixes` sentence read as an exemption from the outcome-3 recording that loop 1 had just made mandatory, restoring the byte-identical output the mandate exists to prevent; outcome 3 demanded a *grep line* for a mechanism the same section says is often rule-shaped and therefore ungreppable (you cannot search for the absence of a bound) — now it names an enumeration instead; the sweep-test threshold was stated in full in both standards, which § 1.5 twelve lines above forbids by name, so `testing.md § 3.6` is now canonical and § 1.6 points; and the "where the shape recurs" lead disagreed with the "three or more call sites" qualifier nine lines later. **The most serious finding was a false claim loop 1 introduced**: "`ruff` enforces `snake_case` in the gate" — it does not, `select` omits `pep8-naming`, and `def parseHeader(strName)` passes clean. Verified by enabling `N`, which flags nine sites, **every one a Qt override that must be camelCase**; the rule is held by review and now says so. Draft defects: `§ O1` named `scanner`, `supervisor` and `logbuffer`, none of which exist, while omitting `applog.py`, which does and is core by O1's own criterion — replaced with a criterion plus the instruction to widen `test_layering.py`'s `CORE_MODULES`, which is the thing that actually enforces it. |
