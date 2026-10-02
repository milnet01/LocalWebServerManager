<!-- ants-coding-overrides: 1 -->
# Coding overrides — LocalWebServerManager

**Status:** v1 (2026-10-02).

The coding standard for this project is `~/.claude/standards/coding.md`,
with `languages/python.md` and `languages/qt.md` beside it. It is read in
place, not copied. This file holds only the rules where this project
differs or adds, each with one line of why. **Those files are on the
author's machine and not in this repository**: a contributor reads this
file plus `CONTRIBUTING.md`.

## O1. The core never imports `QtWidgets`

The package is split four ways, and a core module imports `QtCore` at most:

| Layer | Modules | Rule |
|---|---|---|
| UI | `mainwindow.py`, `settingsdialog.py`, `theme.py` | may import `QtWidgets` |
| Entry point | `__main__.py` | may import `QtWidgets`; builds the `QApplication`, inside `main()` after `argparse` |
| Package marker | `__init__.py` | imports nothing |
| Core | every other module | `QtCore` only, never `QtWidgets` |

`tests/test_layering.py` holds the split as two lists: `CORE_MODULES` and
`NON_CORE_MODULES`. A new module goes into one of them in the commit that
creates it.

Why: keeping `QtWidgets` out of the core is what makes the core testable
without a display.

## O2. Nothing touches a widget off the UI thread

Reader threads and probe workers talk to the UI only through queued Qt
signals. Any new thread names its signal boundary in review.

Why: a direct widget call from a worker is a crash rather than a benign
race, and ADR-0003 keeps it a standing review item.

## O3. Never write into a sibling project

A scanned project's directory is read-only to this app: no config, lock,
marker or log goes there. App state lives under
`$XDG_CONFIG_HOME/localwebservermanager/` and
`$XDG_STATE_HOME/localwebservermanager/`. Each falls back to its
`~/.config` / `~/.local/state` default when the variable is unset or not
absolute.

Why: `docs/discovery.md § Out of scope` makes sibling directories off
limits, so this is not just a convention.

## O4. Every spawn starts a new session

On top of the shared rule that a command is an argument list, never a shell
string: every child the app supervises or leaves running — a server, a
browser — is started with `start_new_session=True`. A short query whose
output is captured and which runs to completion (the scanner's `systemctl`
call) is not.

Why: stopping a server signals its whole process group, and that group
exists only because the child got its own session (ADR-0003).

## O5. Never report a state you have not observed

"Running" means a bound port was observed, not that something was started.
A port holder whose PID cannot be resolved is reported as unnamed, not
guessed.

Why: the app's whole value is telling the truth about what is running
(ADR-0004).

## O6. Qt for Python, not Qt for C++ transliterated

- Signals and slots are `Signal()` / `Slot()` from `PySide6.QtCore`.
- `QSettings` is not used. Config lives in files at the O3 paths, in the
  formats `docs/design.md § Persistence` gives, so it stays hand-editable.
- Don't keep a Python reference to a parented child just to keep it
  alive; the parent owns its lifetime.
- Check that an API exists in the installed PySide6 before designing
  around it.

Why: a method in the C++ Qt docs is no evidence that the binding exposes
it. `QProcess.setChildProcessModifier` is missing from PySide6, which is
why ADR-0003 exists.

## O7. No literal colours, sizes or fonts in widget code

A widget names a theme token (`window`, `text`, `accent`,
`state_running`, …), never a hex value or `QColor(...)`. It uses the
system font, never a family name. It sizes from the text metric, never
from a pixel constant. `theme.py` defines the tokens and is the one
module allowed to hold colour values.

Why: a literal is invisible in one theme, unreadable in another, and
breaks at 200 % text size.

## O8. Accessibility is part of "done"

The primary user is partially sighted and uses a screen magnifier. Every
new interactive widget lands with all four of these:

1. `setAccessibleName`, plus `setAccessibleDescription` where the name is
   not self-explanatory.
2. It can be reached by keyboard, in visual tab order, with a visible
   focus ring.
3. Any state it shows is conveyed in text. Colour and glyphs reinforce it,
   never carry it.
4. Its layout reflows at 200 % text size without clipping. Deliberate
   elision is allowed; `docs/design-accessibility.md § Accessibility` owns
   that rule.

Why: retrofitting accessibility is how it never happens.

## O9. A change names the other places its mechanism is used

A change closes a mechanism, not the one place it was reported against.
Before it is done, list the other places that mechanism applies, and take
exactly one of three outcomes:

1. Fix them in the same change.
2. Say in the commit why they are out of scope.
3. Say the sweep found nothing, in one line naming what was looked for and
   what came back.

For a helper, the list comes from a search for the defect's shape. For a
rule — a bound, a guard, a check against one of two siblings — it is an
enumeration: name the set you walked and the answer for each. Where the
mechanism is wide or the shape has recurred, make the sweep a test;
`testing-overrides.md` § T10 says when and how.

Why: no shared rule covers it, and without outcome 3 a clean sweep and a
skipped one leave identical commits.

## O10. ruff's `N` family is deliberately not selected

PEP 8 casing (`languages/python.md`) is held by review here, not by the
gate.

Why: `N` flags Qt overrides and their arguments, which must be camelCase
(`changeEvent`, `setText`, `sourceText`), so turning it on would mean
suppressing it at the framework boundary.

## What checks this

| Rule | What checks it |
|---|---|
| O1 core never imports `QtWidgets` | Partial: `tests/test_layering.py::test_core_never_imports_qtwidgets` and `::test_the_core_module_list_matches_the_criterion` (modules on disk minus `NON_CORE_MODULES` must equal `CORE_MODULES`) — a core import of another Qt module, such as `QtGui`, is held by review |
| O2 no widget call off the UI thread | nothing |
| O3 never write into a sibling project | Partial: `tests/test_applog.py::test_default_state_dir_follows_the_xdg_spec` covers the state path and `tests/test_settings.py::test_settings_sits_beside_projects_json` the config path — nothing tests the config path's fallback for an unset or relative variable, and nothing checks that no write lands in a scanned directory |
| O4 new session on every supervised spawn | Partial: `tests/test_browsers.py::test_open_url_spawns_the_expanded_argv_detached_and_never_a_shell` covers the browser spawn, and ruff `S` catches a shell string — nothing asserts `start_new_session=True` on other spawn sites |
| O5 never report an unobserved state | nothing |
| O6 Qt for Python | nothing |
| O7 no literal colours, sizes or fonts | Partial: `tests/test_layering.py::test_no_colour_literals_in_widget_code` and `::test_no_pinned_font_family_in_widget_code` scan the modules in `WIDGET_MODULES` — other UI modules are not scanned, and nothing catches a pixel constant |
| O8 accessibility is part of done | Partial: tests in `tests/test_mainwindow.py` and `tests/test_settingsdialog.py::test_every_control_can_be_reached_from_the_keyboard` cover the existing widgets — nothing requires a new widget to arrive with them |
| O9 name the mechanism's other places | nothing |
| O10 `N` unselected | nothing |
