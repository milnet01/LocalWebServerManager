# LocalWebServerManager — Project instructions for Claude Code

Scaffolded from the **Ants App-Build** template. Follows the machine-wide
workflow in `~/.claude/workflow.md` (local to the author's machine): its five
states and gates, with no phases. The phase-based `app-workflow` skill this
project started under left it on 2026-09-28 (CFG-0645). Where it is still
installed it fires on phrases this roadmap still uses ("fix-pass", "phase
close", "drift handling"); do not follow it here. Its status file
is kept as history at
[`docs/journal/workflow-state-to-2026-09-28.md`](docs/journal/workflow-state-to-2026-09-28.md).

## Where state lives

Read these in order on every session start:

1. **This file** — stable rules and conventions.
2. **`ROADMAP.md`'s open items** — what is in flight and what is
   next. Ask the store, not the file: `roadmap_query
   status:"in-progress" mode:"headline_only"`, then the release
   section's intro for the order. With nothing in flight, the
   first unreleased section's intro names what is next. After reading, **summarise back
   to the user** before doing any work.
3. **The standard matching the active item's `Kind`** — the shared
   file in `~/.claude/standards/` plus this project's
   `docs/standards/<name>-overrides.md` (see **Resumption flow**).
   `dependencies-overrides.md` is read before touching any pin.
4. **`docs/specs/<active-id>.md`** — the contract for the
   currently-active roadmap item.
5. **`docs/audit-allowlist.md`** — read **additionally** before
   invoking `check-code` or `review-code`. It records past false
   positives and why. `check-code` matches its tool-and-rule entries
   through `tools/audit/audit-config.json` (LWSM-1317); nothing new is
   added to it. A new false positive goes in the two ledgers
   `check-code` also reads — `.audit_cache/learned-fp.jsonl` for tool
   findings and `.ants_review_falsepos.jsonl` for reviewer claims —
   and recording it there is `close-findings`' job.

## Which skill runs which job

Standing instruction (user, 2026-08-03). These are not
suggestions to weigh per task — each job has one entry point,
and the point is the pitfalls the skill already knows about:

| Job | Skill |
|-----|-------|
| Writing a spec or plan | **`/write-spec`** |
| Reviewing a spec, design, ADR or standard | **`review-contract`** |
| Deterministic doc checks alone (links, citations, counts) | **`check-doc-facts`** |
| Applying fixes a review produced | **`close-findings`** |
| Writing or editing source code | **`/write-code`** |

`/write-spec` carries the `review-contract` gate itself, so a spec
written through it does not need the review invoked separately.
`close-findings` is for closing a list someone else produced —
review findings, audit findings, a fix-pass — and it owns the
blast-radius sweep that catches what a fix moved elsewhere.

## Review cadence — build first (user, 2026-08-13; revised 2026-09-25)

**Build first and fold the spec back afterwards; spec-first is the exception,
not the default.** Decided after measuring `review-contract`'s yield across four
loops on `LWSM-1007` + `LWSM-1131`: of ~42 verified findings, **roughly 1 in 10
was a defect implementation would not have caught**, and about a third were the
review's own collateral — loop 2 of each document landed almost entirely in text
loop 1's fixes had added.

Two rules, in force for this project:

1. **Default: build it, then correct the spec to match what was built.**
   `/write-spec` Step 8 already describes this fold-back; it is now the normal
   path rather than the repair path. Most work needs no spec at all
   (`spec-format.md § 1`).
2. **Spec-first only when code creates durable artifacts** — an on-disk format,
   a wire protocol, anything another item binds to. There, coding first means a
   migration rather than an edit.

**Rule 1 is a deliberate local departure from global rule 14's "run before
implementation"** (user, 2026-08-13; kept local 2026-08-15). It cancels no
gate. A spec corrected after the build falls under rule 14's own exception
for a document brought into line with verified code. A spec first written
after the build is put to rule 14's trigger like any other document; where
nothing will be built from it, that is the No branch, recorded in one line in
the commit body. A spec written first under rule 2 is gated before building.

**When the gate runs, it runs as global rule 14 and `review-contract` define
it — this project sets no cap and no finding filter of its own** (user,
2026-09-25, LWSM-1305). Two earlier rules here are withdrawn:

They are recorded, with the rationale for rule 1 and the evidence that
has cut against it since, in [`docs/claude/review-cadence.md`](docs/claude/review-cadence.md).
Read it before arguing for or against rule 1.

**Never silently drift.** When code diverges from its spec, decide which was
wrong: the spec (correct it and re-check what it touches) or the code (fix the
code, leave the spec). Never paper over both. Under rule 2 (spec-first), stop
and say so before continuing. Under rule 1, note the divergence on the item's
bullet and fold it back when the build is done. That is a deliberate local
departure from `~/.claude/workflow.md` § 7's first row, which re-runs the
pick-time gate; it is rule 1 applied to drift.

**A rule-14 gate over `CLAUDE.md` must tell its lanes to read the subject
from disk.** A dispatched lane is briefed with the session-start copy of this
file, not the edited one, so a lane that trusts its context reviews the old
text (found 2026-09-25, logged in `~/.claude` as CFG-0593).

## Before pushing

**Run `./scripts/local-ci.sh` before any push that touches code,
tooling or CI config** (user, 2026-08-03). A **docs-only push runs
`./scripts/local-ci.sh --docs`** — the steps that read prose, not the
whole gate, because a full gate on every typo fix trains people to skip
it. It was a complete skip until 2026-09-28, when `local-gate.md` § 2.1
(user, same day) ruled out dropping checks for speed. `--docs` runs the
steps up to and including the format check, which reads every `.md`
because ruff formats the Python blocks inside markdown; among them, the
version lockstep reads `ROADMAP.md`. It does **not** run the suite, which
is why a file the suite reads takes the full gate (below).

**Every push is also scanned for secrets** by the machine-wide hook's
`--secrets-only` mode, before the gate. `LWSM_SKIP_PREPUSH=1` skips the
gate and not the scan.

**Since 2026-08-18 a `pre-push` hook enforces all of that**, so
it is no longer a rule someone has to remember. Enable it once per
clone — `core.hooksPath` cannot be committed:

```bash
git config core.hooksPath .githooks
```

How the hook decides a push is docs-only, which markdown always takes the
full gate, and why: [`docs/claude/ci-gate.md`](docs/claude/ci-gate.md).
Read it before changing the hook, the gate or `test_docs.ASSERTED`.

**Escaping the hook is the user's call, never yours** (`commits.md`
§ 2.3; LWSM-1318). The two escapes differ: `LWSM_SKIP_PREPUSH=1` skips the
gate and keeps the secrets scan, while `git push --no-verify` skips the
whole hook, scan included. Use one only when the user has said so for that
push — never on your own judgement that the push is safe, and never by
exporting the variable, which skips every later push's gate too.

The hook runs the gate under CI's environment (`LWSM_REQUIRE_ALL_TOOLS=1`),
and tool versions are pinned in `scripts/ci-tools.env`. Detail, and how to
bump a tool: [`docs/claude/ci-gate.md`](docs/claude/ci-gate.md).

The script is the single source of truth for CI: `.github/workflows/ci.yml`
prepares a machine and then calls it. **Never add a check to the
workflow instead of the script** — that produces a check nobody can
run before pushing, which is the whole thing this arrangement
exists to prevent.

## Subagents

Global rule 15 governs, confirmed for this project by the user on
2026-08-03: reviews and broad tree searches run agents without asking.

## Releases

**Before cutting a release, read [`docs/claude/release.md`](docs/claude/release.md)**:
the big review (`check-code`, `review-code`, `close-findings`), the standing
refactoring and security passes, and `./scripts/local-release.sh`.

## Tech stack

Chosen in Phase A (2026-08-03) — full reasoning and runner-ups
in [`docs/discovery.md § Tech stack`](docs/discovery.md).

- **Python 3.13** + **PySide6 6.11** (Qt 6) — a desktop app, not
  a website. Native on KDE; both already installed.
- **`subprocess.Popen`** for launching servers, in
  `supervisor.py`, which imports no Qt so the process boundary is
  testable without a display. Phase A chose `QProcess`; the build
  did not use it. **`psutil`** for "who holds this port".
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

There is no compile step. What the gate runs, in order, and the reasoning
behind `yamllint --strict`, fatal SKIPs and the committed
`.python-version`: [`docs/claude/ci-gate.md`](docs/claude/ci-gate.md).

See **Before pushing** above for when the gate is mandatory.

## Commit conventions

Per `~/.claude/standards/commits.md` § 1.1 and
[`docs/standards/commits-overrides.md`](docs/standards/commits-overrides.md):
every commit subject is `<ID>: <description>`, where `<ID>` is the
roadmap item's `LWSM-NNNN`.

**Phases are retired.** A commit with no item id follows `commits.md`
§ 1.2: `chore:`, `docs:`, a release or a hotfix subject. No new `P##`,
`FP##`, `DS##`, `DOC##` or `R##` is opened, and no new `<ID>-complete` tag is
cut; the existing tags stay. A release is tagged by `cut-release`. The
phase-ID history is in [`docs/claude/claude-md-history.md`](docs/claude/claude-md-history.md).

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

Global rule 6. This repo is **public**, so push freely; `main` tracks
`origin/main`.

## The roadmap store

`ROADMAP.md` is rendered from the Ants roadmap store; edit it through
`roadmap_log`, never by hand. Three standing rules:

- **Do not run `roadmap_migrate` on this project.** It is already in the
  store, so there is nothing to migrate, and a `dry_run` has planned
  dozens of phantom headline updates that no diff explains (re-checked
  2026-08-19). The store has no undo. The full record is in the
  2026-09-28 journal file named at the top of this file.
- **A calibrated-down finding is closed as a finding, not built here**
  (user, 2026-09-03). When a fold-in marks a finding as another item's
  scope, flip it shipped, say in the note that no code changed, and name
  the item that owns the work. First applied to LWSM-1230 → LWSM-1011.
- **Three `roadmap_log` traps** (2026-09-25). `set_intro` does not replace
  a section's table — the old table stays and the text lands above it, so
  delete and recreate the section and rebuild the table with `bundle_row`.
  `amend_field field:"section"` naming the item's current section moves
  nothing; move it away and back. `delete_section` refuses a parent that
  has sub-sections; delete those first.

## Module map

What each module owns, and why: [`docs/claude/module-map.md`](docs/claude/module-map.md).
Read the entry for a module before changing it. The layering rule is
[`docs/standards/coding-overrides.md § O1`](docs/standards/coding-overrides.md): a
core module may import `QtCore` but never `QtWidgets`, so every
one of them is testable without a display. **`tests/test_layering.py`
enforces it by parsing the AST, not by grepping for the string** —
every core module *documents* the rule in its docstring, so a
substring search reports all of them as violations.

**Traps** — measured lessons about Qt, the test suite, mutation testing,
the scanner, KWin and the CI tools — are in
[`docs/claude/traps.md`](docs/claude/traps.md). Read the matching ones
before writing a test, a mutation run, or code that touches Qt, a
subprocess or the compositor. Test docstrings that cite a "`CLAUDE.md`
trap" mean that file.

## Hard rule: never kill by pattern

**Never find or kill a process by a command-line pattern on this machine.**
Several Claude Code sessions run here, and the user runs the real app: a
bracketed `pkill -f 'sleep [3]0'` is a substring match that killed two other
sessions' `sleep 300` loops (2026-09-02), and `pkill -INT -f 'bin/lwsm$'`
meant for a test copy matched the user's own window (2026-09-28). Select by
PID, and confirm the PID is yours before signalling — its cwd, or its
`/proc/<pid>/environ` holding the test's private `XDG_RUNTIME_DIR` (LWSM-1287).

## Resumption flow — MANDATORY summarise-back

1. **Parallel batch:** read this file, the roadmap's in-progress
   items, and the intro of the release section they sit in — or,
   with nothing in flight, of the first unreleased section (one
   tool-call batch). Fetch an active item's body by id.
2. Once `Kind` is known from the active item, read the
   matching `docs/standards/<which>.md` (single read).
3. **Summarise back to the user:** "We're on `<ID>`, last did
   `<X>`, next is `<Y>`."
4. Wait for confirm or redirect.

**Never skip step 3.** Catching state-recovery errors before
working is cheaper than corrective rounds later.

## Standards reference

The standards are the shared set in `~/.claude/standards/`, read in
place. This project's differences from them live in
[`docs/standards/`](docs/standards/) as `<name>-overrides.md` files —
see its [README](docs/standards/README.md) for the index and which
kinds each governs (LWSM-1326).
