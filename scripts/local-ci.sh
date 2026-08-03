#!/usr/bin/env bash
# The CI gate. Run this before any push that touches code, tooling or CI
# config; a docs-only push does not need it.
#
# THIS FILE IS THE SINGLE SOURCE OF TRUTH FOR CI.
# `.github/workflows/ci.yml` sets up a machine and then calls this script —
# it does not restate the steps. That is deliberate and is the only way
# "the local run matches GitHub exactly" can stay true: two lists of steps
# drift the first time someone edits one of them, and the drift is discovered
# by a red build on a push, which is exactly what running locally was meant to
# avoid.
#
# So: to change what CI does, change THIS FILE.
#
# Usage:
#   ./scripts/local-ci.sh          # the full gate
#   ./scripts/local-ci.sh --fast   # skip the slowest stage (still lints+tests)
set -Eeuo pipefail

cd "$(dirname "$0")/.."

FAST=0
[[ ${1:-} == "--fast" ]] && FAST=1

# Qt needs no display: every test is headless by contract
# (docs/standards/testing.md § T6), and CI runners have no X server. Setting
# this here rather than in the workflow means the local run and the CI run
# share it, like everything else in this file.
export QT_QPA_PLATFORM=offscreen
# Keep the run reproducible: a stray PORT in the developer's shell would be
# inherited by anything the tests spawn (ADR-0002 sets it per child, but a
# leaked one could still confuse a fixture).
unset PORT LWSM_MANAGED || true

step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
fail() { printf '\n\033[31mFAILED: %s\033[0m\n' "$1" >&2; exit 1; }

# Checks that could not run because a tool is absent. Tracked, because a
# skipped check followed by a green "passed" is indistinguishable from a full
# clean run — and the local developer is exactly who that misleads.
SKIPPED=()
skip() { SKIPPED+=("$1"); printf '%s NOT CHECKED — this is a SKIP, not a pass\n' "$1"; }

if ! command -v uv >/dev/null 2>&1; then
    fail "uv is not installed — see https://docs.astral.sh/uv/"
fi

step "Sync dependencies (locked)"
# --locked, NOT --frozen. Measured on uv 0.11.7, 2026-08-03:
#   pyproject says psutil==7.1.0, uv.lock still says 7.2.2
#     uv sync --frozen  -> exit 0, lock untouched, TESTED AGAINST 7.2.2
#     uv sync --locked  -> exit 1
# --frozen means "don't update the lock", which silently tolerates a lock that
# disagrees with pyproject.toml — so a commit that edits a pin and forgets to
# re-lock gets a green CI run against the OLD version. --locked asserts the two
# agree, which is the property this step is actually here to guarantee.
uv sync --extra dev --locked

step "Lint (ruff check)"
uv run ruff check .

step "Format check (ruff format --check)"
uv run ruff format --check .

step "Syntax gate (compileall)"
# The "build" for a pure-Python project. `import lwsm` would miss any submodule
# that nothing imports yet, which at this stage is most of them.
uv run python -m compileall -q src tests

step "Entry points resolve"
# compileall proves every file that EXISTS parses; it cannot know that
# [project.scripts] names a module that does not. Without this, the shipped
# `lwsm` command can be dead while CI stays green — which it was, until the
# P01 review caught it.
uv run python -c "
import importlib.metadata as m
eps = [e for e in m.entry_points(group='console_scripts')
       if e.dist and e.dist.name == 'localwebservermanager']
assert eps, 'no console_scripts entry point found for localwebservermanager'
for e in eps:
    e.load()
    print(f'  {e.name} -> {e.value} OK')
"

step "Tests"
if [[ $FAST -eq 1 ]]; then
    uv run pytest -q -m "not integration"
else
    uv run pytest -q
fi

step "Shell scripts (shellcheck)"
if command -v shellcheck >/dev/null 2>&1; then
    shellcheck scripts/*.sh
else
    skip "shellcheck"
fi

step "Workflow and config YAML"
# actionlint covers .github/workflows/ only, so dependabot.yml needs yamllint
# regardless — otherwise the better-equipped machine checks LESS, and a
# malformed package-ecosystem reaches GitHub, which reports config errors on
# its own dashboard rather than in the build.
YAML_CHECKED=0
if command -v actionlint >/dev/null 2>&1; then
    actionlint
    YAML_CHECKED=1
fi
if command -v yamllint >/dev/null 2>&1; then
    yamllint -d relaxed .github/
    YAML_CHECKED=1
elif [[ $YAML_CHECKED -eq 1 ]]; then
    skip "yamllint (.github/dependabot.yml unchecked)"
fi
if [[ $YAML_CHECKED -eq 0 ]]; then
    # Deliberately no Python fallback: PyYAML is not a dependency, so
    # `import yaml` would crash on a clean machine — a gate that fails because
    # the gate is broken is worse than one that admits it did not run.
    skip "workflow YAML"
    printf 'install yamllint (your package manager, or: pipx install yamllint)\n'
fi

if ((${#SKIPPED[@]})); then
    printf '\n\033[33mLocal CI passed, with %d check(s) SKIPPED: %s\033[0m\n' \
        "${#SKIPPED[@]}" "${SKIPPED[*]}"
else
    printf '\n\033[32mLocal CI passed.\033[0m\n'
fi
