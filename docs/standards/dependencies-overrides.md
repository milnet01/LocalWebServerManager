<!-- ants-dependencies-overrides: 1 -->
# Dependencies overrides — LocalWebServerManager

**Status:** v1 (2026-10-02).

The dependency standard for this project is
`~/.claude/standards/dependencies.md`, read in place, not copied. This file
holds only the rules where this project differs or adds, each with one line
of why, plus the project's hold register. **That file is on the author's
machine and not in this repository**: a contributor reads this file plus
`CONTRIBUTING.md`.

## D1. The pin unit per ecosystem

| What | Pinned as |
|---|---|
| Python runtime and dev dependencies (`pyproject.toml`) | exact `==` |
| `[build-system] requires` and `[tool.uv] build-constraint-dependencies` | exact `==` |
| GitHub Actions | a full commit SHA, with the release as a trailing comment |
| Runner images | an explicit label, never `-latest` |
| Python interpreter | the version in the committed `.python-version` |
| CI tools (`scripts/ci-tools.env`) | an exact version |
| OS packages a workflow installs with `apt-get` | not pinned; they move with the pinned runner image |

`requires-python` is a floor, not a pin.

Why: exact pins plus the committed `uv.lock` make `scripts/local-ci.sh` and
GitHub CI resolve the same versions. A pin that resolves differently on the
two produces a failure that will not reproduce locally.

## D2. Bump on contact

A pin that is written or touched is set to the latest stable release at
that moment, checked against the registry rather than recalled, unless D7
holds it. Any edit to `pyproject.toml`, a workflow, `uv.lock` or
`scripts/ci-tools.env` checks the other pins in that file too, and bumps
each one that is behind in its own commit (shared § 6). The pins are the
direct ones D1 lists; the transitive versions in `uv.lock` follow from a
re-lock. This overrides the
shared standard's surface-then-ask (§ 5) for pins this project touches.

Why: if bumps wait for a scheduled sweep, the sweep is the only thing that
ever bumps anything.

## D3. Hold only on a demonstrated break

A pin may be held below latest — a D7 row — only if someone tried the
newer version and saw it fail in a way upstream has not fixed. A break in
this project's own code that a migration would fix is migrated, not held.
This is stricter than the shared § 1: a migration nobody has time for is not
a reason here.

Why: an anticipated break, or a deferred migration, is how a pin ends up on
a version nobody has tested against.

## D4. The gate installs with `uv sync --locked`

`scripts/local-ci.sh` installs with `--locked`, never `--frozen`.

Why: `--frozen` passes when `uv.lock` disagrees with `pyproject.toml` and
tests the old version. `--locked` fails, which catches a pin edited without
a re-lock.

## D5. Every ecosystem dependabot supports is registered in `.github/dependabot.yml`

Here that is GitHub Actions and uv. The interpreter, the runner label and
the CI tools have no dependabot ecosystem; D2's contact rule stands in for
it.

Why: an unregistered ecosystem gets no update pull requests, which looks
exactly like having nothing outdated.

## D6. A bump re-verifies the design premise beside the pin

Where a design decision rests on a dependency's behaviour, the check is
recorded as a comment beside the pin in `pyproject.toml`, and every bump
re-runs it. For PySide6, ADR-0003 rests on
`QProcess.setChildProcessModifier` being absent.

Why: a bump can quietly turn an architectural constraint into a free
choice, or bring back one that was designed around.

## D7. The hold register

This project's hold ledger, in the shared standard's columns. Each held
pin also carries a comment beside it pointing here.

| What | Held at | Broke at | What breaks | What would release it | Decided | Last retested |
|---|---|---|---|---|---|---|
| *(none)* | | | | | | |

An empty register means no pin is held on purpose. It does not mean every
pin is current.

## D8. Where the versions live

Shared `dependencies.md` § 7's list for this project: every file carrying a
dependency, tool or interpreter version. The project's own version is
`.claude/bump.json`'s list, not this one.

| What | Where | Moves with |
|---|---|---|
| Runtime and dev dependencies | `pyproject.toml` `[project]` | `uv.lock`, re-locked |
| Build backend | `pyproject.toml` `[build-system] requires` | `[tool.uv] build-constraint-dependencies` in the same file, and `uv.lock`'s `build-constraints` |
| Python interpreter | `.python-version` | `requires-python` in `pyproject.toml` (a floor), and README's "Python 3.13+" |
| CI tools | `scripts/ci-tools.env` | uv also in `.github/workflows/ci.yml`'s setup-uv `version:` |
| GitHub Actions | `.github/workflows/ci.yml` `uses:` SHAs, release in a trailing comment | — |
| Runner image | `.github/workflows/ci.yml` `runs-on:` | — |
| Design premises tied to a version (D6) | the comment above PySide6 in `pyproject.toml`; psutil's `_send_signal` behaviour in `src/lwsm/foreign.py` and ADR-0003 | re-checked on that dependency's bump |

Dated mentions in `ROADMAP.md`, `CHANGELOG.md`, `docs/journal/`,
`docs/reviews/` and the traps records are history and do not move.

Why: a version that lives somewhere nobody listed is the one a bump misses.

## What checks this

| Rule | What checks it |
|---|---|
| D1 pin unit per ecosystem | nothing |
| D2 bump on contact | Partial: `check-dependencies` reports what is behind when run — nothing runs it when a pin is touched |
| D3 hold only on a demonstrated break | nothing |
| D4 `uv sync --locked` | Partial: the `uv sync --locked` step in `scripts/local-ci.sh` fails on a lock that disagrees with `pyproject.toml` — nothing asserts the flag stays `--locked` |
| D5 every ecosystem in dependabot | nothing |
| D6 re-verify the design premise | nothing |
| D7 hold register | nothing checks that a hold has a row |
| D8 where the versions live | Partial: `tests/test_ci_contract.py::test_the_workflow_installs_the_pinned_uv` holds the workflow's uv to `ci-tools.env`, and the gate's `uv sync --locked` holds `uv.lock` to `pyproject.toml` — nothing ties the Python version's three homes together, or finds a new version-bearing file the table lacks |
