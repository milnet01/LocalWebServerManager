<!-- ants-coding-standards: 1 -->
# Coding Standards — v1

A shareable contract for code in this project. Pairs with the
other three standards in this folder ([documentation](documentation.md),
[testing](testing.md), [commits](commits.md)) — see the
[index](README.md) for the full set.

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

- **Functions** — verb phrases (`parseRGBColor`, `applyTheme`).
- **Variables** — noun phrases (`m_currentTab`, `gridSize`).
- **Booleans** — `is*` / `has*` / `can*` (`isReady`, `hasFocus`).
- **Constants** — match the file's existing style. Don't mix
  SCREAMING_SNAKE and PascalCase in one file.
- **Avoid abbreviations** except universally-known (`url`, `id`,
  `db`). Prefer `temperature` over `temp` when ambiguous.
- **No Hungarian notation.** `m_` prefix for member fields is
  fine where a project uses it; type prefixes (`strName`, `iCount`)
  are not.


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
split is enforced by import. Core modules (`scanner`, `registry`,
`ports`, `supervisor`, `logbuffer`, `controller`) may import
`QtCore` for signals and timers; a `QtWidgets` import in any of
them is a review failure, because it is what makes the core
headless-testable.

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
`~/.config/localwebservermanager/` and
`~/.local/state/localwebservermanager/`.

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
