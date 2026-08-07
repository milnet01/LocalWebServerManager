# LocalWebServerManager — Project instructions for Claude Code

Scaffolded from the **Ants App-Build** template; follows the
`app-workflow` (`~/.claude/skills/app-workflow/SKILL.md`, local to the author's machine)
skill.

## Where state lives

Read these in order on every session start:

1. **This file** — stable rules and conventions.
2. **`.claude/workflow.md`** — live status header (current
   phase, active item, step number, blockers, last-update
   timestamp). After reading, **summarise back to the user**
   before doing any work.
3. **`docs/standards/{coding,documentation,testing,commits,dependencies}.md`**
   — the five v1 standards. `dependencies.md` is canonical for
   version policy and is read before touching any pin.
4. **`docs/specs/<active-id>.md`** — the contract for the
   currently-active roadmap item.
5. **`docs/audit-allowlist.md`** — read **additionally** before
   invoking `/audit` or `/code-quality-review` so already-confirmed
   project-specific false positives aren't re-flagged. The
   allowlist is the closed-loop memory for this project — see
   the app-workflow skill (`~/.claude/skills/app-workflow/SKILL.md`, local to the author's machine)
   "False-positive learning" section.

## Which skill runs which job

Standing instruction (user, 2026-08-03). These are not
suggestions to weigh per task — each job has one entry point,
and the point is the pitfalls the skill already knows about:

| Job | Skill |
|-----|-------|
| Writing a spec or plan | **`/write-spec`** |
| Reviewing a spec, design, ADR or standard | **`/cold-eyes`** |
| Applying fixes a review produced | **`/apply-fixes`** |
| Writing or editing source code | **`/write-code`** |

`/write-spec` carries the `/cold-eyes` gate itself, so a spec
written through it does not need the review invoked separately.
`/apply-fixes` is for closing a list someone else produced —
review findings, audit findings, a fix-pass — and it owns the
blast-radius sweep that catches what a fix moved elsewhere.

## Before pushing

**Run `./scripts/local-ci.sh` before any push that touches code,
tooling or CI config** (user, 2026-08-03). A **docs-only push is
exempt** — the gate has nothing to say about prose, and making it
mandatory there just trains people to skip it.

The script is the single source of truth for CI: `.github/workflows/ci.yml`
prepares a machine and then calls it. **Never add a check to the
workflow instead of the script** — that produces a check nobody can
run before pushing, which is the whole thing this arrangement
exists to prevent.

## Standing quality passes

Both added by the user on 2026-08-03, and both run as part of closing a
phase rather than when someone remembers:

- **Look for refactoring opportunities.** Python is interpreted, so
  there is no compiler catching a tangle — structure is held by
  reading alone. On every phase close, ask what got duplicated, what
  grew a second responsibility, and what a name now lies about.
  Refactor when there is something to refactor; **say "nothing to
  refactor at this size" when there isn't**, rather than inventing
  churn to look diligent.
- **Run a security pass.** Not just the scanners — this app spawns
  processes, signals process groups, reads other projects' files and
  will eventually run user-authored commands. That is a real attack
  surface, and the scanners only see the code that exists today.

## Subagents

**Agents are permitted where they genuinely help and are token-
efficient** (user, 2026-08-03). Reviews are the clearest case —
`/cold-eyes`, `/audit` and `/code-quality-review` all depend on a
fresh pair of eyes that has not been reading along, so the rule-14
gate runs its reviewers here without asking first. Broad
"where is X used across the tree" searches are the other case.

This overrides any session-level default that says not to spawn
agents unless asked. It is not a licence to fan out on work one
context can already do.

## Closing a phase

Run **`/close-phase`** once steps 1–4 of the per-phase loop
are done — see SKILL.md for the full description.

## Tech stack

Chosen in Phase A (2026-08-03) — full reasoning and runner-ups
in [`docs/discovery.md § Tech stack`](docs/discovery.md).

- **Python 3.13** + **PySide6 6.11** (Qt 6) — a desktop app, not
  a website. Native on KDE; both already installed.
- **`QProcess`** for launching and supervising servers, so
  status, live log output and exit signals share one source of
  truth. **`psutil`** for "who holds this port".
- **`uv`** + `pyproject.toml` for dependencies; **`pytest`** +
  **`pytest-qt`** for tests; **`ruff`** for lint and format.

The app **runs each sibling project's own launcher** (`start.sh`,
`run.sh`, `serve.py`, `serve.mjs`, `npm run dev`) and never
edits sibling source. Ports become reassignable via a port
contract the siblings adopt — see `docs/discovery.md §
Feature set`, formalised as an ADR in Phase B.

## Build and test

```bash
uv sync --extra dev     # resolves from the committed uv.lock
./scripts/local-ci.sh   # the whole gate
./scripts/local-ci.sh --fast   # same, minus the integration tests
```

There is no compile step. `scripts/local-ci.sh` runs, in order:
`uv sync --locked`, `ruff check`, `ruff format --check`,
`python -m compileall src tests` (the syntax gate), an
entry-point resolution check, `pytest`, `shellcheck`, and
`actionlint` + `yamllint`. A check whose tool is missing is
reported as an explicit **SKIP**, never folded into the pass —
**each tool is tracked separately**, because sharing one flag
between `actionlint` and `yamllint` made a missing `actionlint`
report a clean pass (reproduced and fixed 2026-08-06).

In CI, a SKIP is **fatal**: the workflow sets
`LWSM_REQUIRE_ALL_TOOLS=1`, so the machine that is supposed to
hold every tool cannot report green on a degraded run. Locally it
stays a warning — a missing linter should not stop you testing
your own change.

`.python-version` is committed, so a developer's machine and the
runner resolve the **same** interpreter. `requires-python` is only
a floor, and `filterwarnings = ["error"]` would turn any
divergence into a red build that does not reproduce locally.

See **Before pushing** above for when the gate is mandatory.

## Commit conventions

Per [`docs/standards/commits.md § 1.1`](docs/standards/commits.md):
every commit subject is `<ID>: <description>`, where `<ID>` is
either a phase ID (`P##`, `FP##`, `DS##`, `DOC##`, `R##`) or a
stable per-bullet ID for ROADMAP_FORMAT v1 projects
(`LWSM-NNNN`).

Every implementation phase ends with `git tag -a <ID>-complete`
on the closing commit. Tags are local until the user explicitly
authorises a push.

## Licence and visibility

MIT, and **published as a public repository** at
`github.com/milnet01/LocalWebServerManager` (LWSM-1004, created
2026-08-03 from a squashed orphan commit — the pre-publication
history named author-private services and is kept locally under
the `pre-public-history` tag).

Two consequences to hold on to:

- **Everything in this tree is world-readable**, including
  `ROADMAP.md`, `docs/specs/`, and any security finding folded
  into the roadmap while still open. `docs/private/` is
  gitignored and is the only place author-private facts go.
- **`LICENSE` names Anthony Schemel** as copyright holder. Keep
  it a legal person, not the project name.

## Push policy

Inherits from the user's global `~/.claude/CLAUDE.md` § 6
(public repos: push freely; private: batch + ask). This repo is
**public**, so the free-CI-minutes rule applies: push freely, no
batching gate. `main` tracks `origin/main`.

Detect repo visibility once per session via
`gh repo view --json visibility -q .visibility` and cache; the
result is recorded in `.claude/workflow.md` § 1 status header.

## Module map

Eight modules at P02. The layering rule is
[`docs/standards/coding.md § O1`](docs/standards/coding.md): a
core module may import `QtCore` but never `QtWidgets`, so every
one of them is testable without a display. **`tests/test_layering.py`
enforces it by parsing the AST, not by grepping for the string** —
every core module *documents* the rule in its docstring, so a
substring search reports all of them as violations.

- **`src/lwsm/__init__.py`** — the package docstring stating that
  rule, and `__version__`.
- **`src/lwsm/__main__.py`** — `main()`, plus the thin **`run()`**
  the `lwsm` console script and `python -m lwsm` actually name.
  `run()` is `main()` followed by
  `exit_without_waiting_for_abandoned_probes`, and the split is
  load-bearing: that call is an `os._exit` when a probe was
  abandoned, and while it sat inside `main()` **one abandoned probe
  ended the pytest run at 40 % of the suite with exit code 0** and
  a report that read as green (LWSM-1100). Anything that ends the
  process belongs behind `run()`, never in `main()`, which tests
  call in-process. An `argparse` parser, so
  `--version` and `--help` work and an unrecognised option exits
  2 rather than being ignored. Prints where it is logging to, and
  starts anyway — with a warning on stderr — when the log
  directory cannot be used. Since P02 it also opens the window,
  via **`build_window()`** — a deliberate seam: `main()` ends in a
  blocking `app.exec()`, so anything inside it is unreachable from
  an in-process test. `QApplication` is imported and constructed
  *inside* `main`, after `argparse`, so `--version` needs no
  display.
- **`src/lwsm/applog.py`** — the application log.
  `default_state_dir()`, `get_logger()`, `configure_logging()`,
  `configure_stderr_logging()` (the fallback the entry point uses
  when the file log is unavailable), and a
  `_NoFollowRotatingFileHandler` that writes only to a private
  regular file: `O_NOFOLLOW` 0600 inside a 0700 directory, and
  then an `fstat` requiring one link and our own ownership, so
  neither a symlink nor a **hard link** nor a **FIFO** planted at
  `app.log` can redirect or block the log. The last two were
  reproduced against the `O_NOFOLLOW`-only version on 2026-08-06.

Added at P02 (LWSM-1005), contract in
[`docs/specs/LWSM-1005-vertical-slice.md`](docs/specs/LWSM-1005-vertical-slice.md):

- **`src/lwsm/registry.py`** — core. `ProjectRecord`,
  `RegistryError`, `default_projects_path()`, `load_projects()`.
  Returns `(records, rejection reasons)`: the file being unusable
  raises, one bad *record* never does. A bad **port** loses the
  field, not the row. **Port ranges differ by field** — declared
  `port` is 1–65535 (a project may legitimately declare 80),
  `port_override` is ADR-0005's 1024–65535. Type checks use
  `type(v) is int`, because `isinstance(True, int)` is `True` and
  the file is hand-editable.
- **`src/lwsm/ports.py`** — core, no Qt at all. `PortProbe`,
  `PortSnapshot`, `ProbeError`, and the `SupportsSnapshot`
  Protocol the controller accepts so test fakes are the contract.
  One `psutil.net_connections` call per snapshot.
- **`src/lwsm/controller.py`** — core, `QtCore` only.
  `ProjectController`, `ProjectStatus`, `RowView`. Polls every
  1000 ms **on a `QThreadPool` worker** (design.md § State
  management requires it). **`QRunnable` is not a `QObject`**, so
  the task holds a composed `_SnapshotSignals(QObject)` — a
  `Signal` declared on a bare `QRunnable` has no `emit`.
  `stop()` waits for the pool, and every test fixture calls it.
- **`src/lwsm/theme.py`** — UI layer, and the **only** module
  allowed a colour literal; `test_layering.py` exempts it by an
  explicit allowlist and asserts it still holds the palette.
- **`src/lwsm/mainwindow.py`** — UI layer. Rows are created once
  and **updated in place**; rebuilding would drop keyboard focus
  and re-announce every unchanged row. The state glyph is
  decorative and excluded from the accessible name, which is
  built from the rendered cell strings.

Tests: `test_applog.py`, `test_main.py`, `test_registry.py`,
`test_ports.py`, `test_controller.py`, `test_mainwindow.py`,
`test_layering.py`, plus `conftest.py` (sets
`QT_QPA_PLATFORM=offscreen` when unset, so a bare `pytest` cannot
open a real window). **Markers go on tests, not files** — marking
a whole file by its heaviest test makes `--fast` silently skip
every light test beside it.

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

**Trap: `setAccessibleName("")` does not hide a widget from the
accessibility tree.** `QAccessibleDisplay` falls back to
`QLabel::text()` when the accessible name is empty, so a decorative
label is still announced — verified by querying the live interface,
which exposes the glyph as a named child (LWSM-1071). To exclude
something from a screen reader, paint it or merge it into a labelled
sibling; do not blank its name. **Assert against the AT tree's
children**, not only the parent's accessible name, or the test cannot
see this.

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

**Trap: run analysis tools inside the project venv (`uv run`, or
`uv run --with <tool>`).** Bare `deptry` / `pip-audit` resolve the
*system* Python and report the project's own declared dependencies as
missing — 21 bogus findings on 2026-08-06 against a `pyproject.toml`
that declares them. Same family as `python` not being on PATH: the
output looks authoritative and is about the wrong interpreter.

## Resumption flow — MANDATORY summarise-back

Per the app-workflow skill:

1. **Parallel batch:** read this file + `.claude/workflow.md`
   status header + active-item details (one tool-call batch).
2. Once `Kind` is known from the active item, read the
   matching `docs/standards/<which>.md` (single read).
3. **Summarise back to the user:** "We're on `<ID>` step
   `<N>`, last did `<X>`, next is `<Y>`."
4. Wait for confirm or redirect.

**Never skip step 3.** Catching state-recovery errors before
working is cheaper than corrective rounds later.

## Standards reference

The five standards (`coding`, `documentation`, `testing`,
`commits`, `dependencies`) plus `roadmap-format` live in
[`docs/standards/`](docs/standards/) — see its
[README](docs/standards/README.md) for the index, the
closed-loop diagram, and which kinds each governs.
