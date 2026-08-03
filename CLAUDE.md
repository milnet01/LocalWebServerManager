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

(Filled in at P01 — Bootstrap, once tech stack is chosen.)

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

MIT, and **intended to be published as a public repository**
(user, 2026-08-03) under the name `LocalWebServerManager` on
`github.com/milnet01`. The repo does **not exist yet** — it is
created once P01 has something worth showing, and creating it
needs explicit authorisation at the time.

Two consequences to hold on to:

- **Everything in this tree becomes world-readable**, including
  `ROADMAP.md`, `docs/specs/`, and any security finding folded
  into the roadmap while still open. There is no private-item
  mechanism today — the file *is* the record.
- **`LICENSE` names Anthony Schemel** as copyright holder. Keep
  it a legal person, not the project name.

## Push policy

Inherits from the user's global `~/.claude/CLAUDE.md` § 6
(public repos: push freely; private: batch + ask). Once the
repo exists it will be **public**, so the free-CI-minutes rule
applies and pushes need no batching gate — but until it exists
there is nothing to push to, and `git push` will fail with no
remote.

Detect repo visibility once per session via
`gh repo view --json visibility -q .visibility` and cache; the
result is recorded in `.claude/workflow.md` § 1 status header.

## Module map

(Filled in at P01 — Bootstrap, once `src/` is non-empty.)

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
