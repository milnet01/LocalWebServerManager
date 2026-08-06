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

usage() {
    printf 'usage: %s [--fast]\n' "$0"
    printf '  --fast   skip the slowest stage (still lints and tests)\n'
}

# Every argument is examined, not just $1: an unrecognised one used to be
# ignored silently, so `--fst` or `--help` ran the full gate and looked like it
# had been honoured.
FAST=0
for arg in "$@"; do
    case $arg in
        --fast) FAST=1 ;;
        -h | --help)
            usage
            exit 0
            ;;
        *)
            printf 'unknown argument: %s\n' "$arg" >&2
            usage >&2
            exit 2
            ;;
    esac
done

# Qt needs no display: every test is headless by contract
# (docs/standards/testing.md § T6), and CI runners have no X server. Setting
# this here rather than in the workflow means the local run and the CI run
# share it, like everything else in this file.
export QT_QPA_PLATFORM=offscreen
# Keep the run reproducible: a stray PORT in the developer's shell would be
# inherited by anything the tests spawn (ADR-0002 sets it per child, but a
# leaked one could still confuse a fixture).
# No `|| true`: the only way `unset` fails is a readonly variable, which is
# exactly the case worth hearing about rather than hiding.
unset PORT LWSM_MANAGED

# Colour only when stdout is a terminal, and never when NO_COLOR is set
# (no-color.org). Escape codes in a CI log or a pipe are noise.
if [[ -t 1 && -z ${NO_COLOR:-} ]]; then
    BOLD=$'\033[1m'; RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'
    RESET=$'\033[0m'
else
    BOLD=''; RED=''; GREEN=''; YELLOW=''; RESET=''
fi

step() { CURRENT_STEP="$1"; printf '\n%s==> %s%s\n' "$BOLD" "$1" "$RESET"; }
fail() { printf '\n%sFAILED: %s%s\n' "$RED" "$1" "$RESET" >&2; exit 1; }

# `set -E` above is inert without an ERR trap, which left `fail` with a single
# caller: a ruff or pytest failure exited non-zero with no banner naming the
# step that broke. CURRENT_STEP is what makes the trap able to say.
CURRENT_STEP="startup"
trap 'fail "$CURRENT_STEP"' ERR

# Checks that could not run because a tool is absent. Tracked, because a
# skipped check followed by a green "passed" is indistinguishable from a full
# clean run — and the local developer is exactly who that misleads.
SKIPPED=()
skip() { SKIPPED+=("$1"); printf '%s NOT CHECKED — this is a SKIP, not a pass\n' "$1"; }

if ! command -v uv >/dev/null 2>&1; then
    fail "uv is not installed — see https://docs.astral.sh/uv/"
fi

step "Sync dependencies (locked)"
# --locked, NOT --frozen. Re-measured on uv 0.12.2, 2026-08-06:
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
# The two tools check DIFFERENT things and are tracked separately. They used to
# share one YAML_CHECKED flag, and the consequence was the exact failure the
# SKIPPED machinery exists to prevent: with actionlint absent and yamllint
# present, yamllint set the flag, which suppressed the actionlint skip as well,
# and the run reported "Local CI passed." with zero SKIPs and exit 0.
# Reproduced 2026-08-06 with stub executables on PATH. actionlint is the one
# most likely to be missing, since it has no distro package.
#
# actionlint owns workflow semantics — an invalid `uses:`, a bad expression, a
# typo'd `runs-on`, and shellcheck over every `run:` block. `yamllint -d
# relaxed` validates none of that; what it adds is .github/dependabot.yml,
# which actionlint does not read at all, so a malformed package-ecosystem
# would otherwise reach GitHub and be reported on its dashboard rather than in
# the build.
if command -v actionlint >/dev/null 2>&1; then
    actionlint
else
    skip "actionlint (workflow semantics and run-block shell unchecked)"
fi
if command -v yamllint >/dev/null 2>&1; then
    yamllint -d relaxed .github/
else
    # Deliberately no Python fallback: PyYAML is not a dependency, so
    # `import yaml` would crash on a clean machine — a gate that fails because
    # the gate is broken is worse than one that admits it did not run.
    skip "yamllint (.github/dependabot.yml unchecked)"
    printf 'install yamllint (your package manager, or: pipx install yamllint)\n'
fi

if ((${#SKIPPED[@]})); then
    # On a developer's machine a skip is a warning: a missing linter should not
    # stop someone testing their own change. On the machine that is SUPPOSED to
    # hold every tool it is a failure, because a green tick is what a reader
    # trusts and it cannot distinguish a full run from a degraded one. CI sets
    # LWSM_REQUIRE_ALL_TOOLS=1; the list of checks stays in this one file either
    # way.
    printf '\n%sLocal CI passed, with %d check(s) SKIPPED: %s%s\n' \
        "$YELLOW" "${#SKIPPED[@]}" "${SKIPPED[*]}" "$RESET"
    if [[ ${LWSM_REQUIRE_ALL_TOOLS:-0} == 1 ]]; then
        printf '%sLWSM_REQUIRE_ALL_TOOLS=1 and %d check(s) did not run.%s\n' \
            "$RED" "${#SKIPPED[@]}" "$RESET" >&2
        exit 1
    fi
else
    printf '\n%sLocal CI passed.%s\n' "$GREEN" "$RESET"
fi
