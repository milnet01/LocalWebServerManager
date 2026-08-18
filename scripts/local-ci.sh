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

# The gate must never read a .pyc it cannot prove is current. Python's default
# bytecode invalidation compares only the source's mtime and SIZE, so a
# same-second edit whose replacement text is the same byte length leaves the
# stale bytecode looking valid. Observed live on 2026-08-06: a constant read
# 400 from an import while the file on disk, `git status` and `git show HEAD`
# all said 120 — and the test run was green. This is the "green test over a
# stale binary" false pass in a language with no build step, and it is
# invisible: clean tree, empty diff, passing suite (LWSM-1110).
#
# Writing none is better than trusting one. The cost is recompiling each run,
# which is milliseconds at this size.
export PYTHONDONTWRITEBYTECODE=1

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

# Tools that ran at a version CI does not use. Tracked separately from SKIPPED
# because they are a different failure: a SKIP says a check did not run, a
# DRIFT says it ran and its answer does not predict GitHub's.
#
# This is the bug the whole ci-tools.env arrangement exists for. On 2026-08-18
# every push went red on two SC2015 findings in install-desktop-entry.sh while
# `./scripts/local-ci.sh` was green: local shellcheck was 0.11.0, the runner's
# apt shipped 0.9, and 0.11 relaxed SC2015 for `command -v` guards. The steps
# matched perfectly. The tools did not, and nothing looked at them.
DRIFTED=()

# The pins CI installs. `.` rather than `source` for POSIX spelling; the file
# is plain KEY=value by design (see its header).
if [[ -f scripts/ci-tools.env ]]; then
    # The `source=` path is resolved from shellcheck's WORKING DIRECTORY, not
    # from this file's directory — so it is spelled repo-root-relative, the
    # same as the runtime path above it. The gate always invokes shellcheck
    # from the repo root (the `cd` at the top of this file), so the two agree.
    # shellcheck source=scripts/ci-tools.env
    . scripts/ci-tools.env
else
    fail "scripts/ci-tools.env is missing — it is what makes this run and CI comparable"
fi

# Compare a tool's reported version against its pin.
#   $1 tool name  $2 pinned version  $3 version as found
#
# A mismatch is a WARNING locally and fatal under LWSM_REQUIRE_ALL_TOOLS — the
# same asymmetry as a SKIP, for the same reason. A developer whose distro moved
# ahead should still be able to test their own change; the machine that is
# supposed to install exact versions must prove it did, or the pin is decorative.
check_version() {
    local tool=$1 pinned=$2 found=$3
    # Normalise a leading `v` on BOTH sides before comparing. A tool does not
    # get to decide whether its own version has one, and two builds of the same
    # release disagree: actionlint installed by `go install …@v1.7.12` reports
    # "v1.7.12" because the tag is what gets compiled in, while the release
    # binary reports "1.7.12". That cost a red build on 2026-08-18 — the first
    # thing this check found was a difference in spelling rather than version,
    # which is the one kind of drift it must not report.
    pinned=${pinned#v}
    found=${found#v}
    if [[ $found == "$pinned" ]]; then
        printf '  %s %s (matches CI)\n' "$tool" "$found"
        return
    fi
    DRIFTED+=("$tool $found vs CI $pinned")
    printf '%s  %s %s — CI runs %s. This check does NOT predict GitHub.%s\n' \
        "$YELLOW" "$tool" "$found" "$pinned" "$RESET"
}

if ! command -v uv >/dev/null 2>&1; then
    fail "uv is not installed — see https://docs.astral.sh/uv/"
fi

step "Tool versions match CI"
# Checked FIRST, before anything is run. A drift report that arrives after the
# suite has passed is read as a footnote to a green run; arriving before it,
# it is a statement about everything that follows.
check_version uv "$UV_VERSION" "$(uv --version | awk '{print $2}')"

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

step "Version lockstep"
# Four files state the version and nothing checked they agreed until LWSM-1067.
# Run here rather than only as the release recipe's post_check: a drift
# introduced today should fail today's push, not surface weeks later as a
# stopped release. Same script both places, so the two cannot disagree.
bash scripts/check-version-drift.sh

step "Lint (ruff check)"
uv run ruff check .

step "Format check (ruff format --check)"
uv run ruff format --check .

step "Syntax gate (compileall)"
# The "build" for a pure-Python project. `import lwsm` would miss any submodule
# that nothing imports yet, which at this stage is most of them.
#
# -f and checked-hash, not the defaults, and PYTHONDONTWRITEBYTECODE above does
# not cover this step: compileall's whole job is to WRITE bytecode, so it
# ignores that variable, and by default it skips a file whose .pyc looks
# current by the same mtime-and-size test that produced LWSM-1110. So the
# stale .pyc survived the syntax gate and the tests then imported it.
#   -f                          recompile regardless of timestamps
#   --invalidation-mode checked-hash   record the source's hash in the .pyc, so
#                               every later import verifies CONTENT rather than
#                               a timestamp, and cannot go stale at all
uv run python -m compileall -q -f --invalidation-mode checked-hash src tests

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
    check_version shellcheck "$SHELLCHECK_VERSION" \
        "$(shellcheck --version | awk '/^version:/ {print $2}')"
    # -x so it FOLLOWS the sourced ci-tools.env rather than reporting SC1091
    # and treating every pin as an unassigned variable. Following the source is
    # also the stronger check: without it the three pins are opaque to it.
    # The hook is shell this project ships and a broken one fails a push at
    # the worst moment, so it is linted with everything else. Named
    # explicitly rather than by glob: .githooks/ may hold a sample or a
    # non-shell file later, and a glob would lint whatever appeared.
    shellcheck -x scripts/*.sh .githooks/pre-push
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
    # actionlint bundles a shellcheck of its own, chosen when IT was built, and
    # runs it over every `run:` block. So SHELLCHECK_VERSION governs
    # scripts/*.sh and this one governs the workflow's inline shell; pinning
    # actionlint is what keeps the second reproducible, since there is no way
    # to point it at ours.
    check_version actionlint "$ACTIONLINT_VERSION" \
        "$(actionlint --version | head -n 1)"
    actionlint
else
    skip "actionlint (workflow semantics and run-block shell unchecked)"
fi
if command -v yamllint >/dev/null 2>&1; then
    check_version yamllint "$YAMLLINT_VERSION" \
        "$(yamllint --version | awk '{print $NF}')"
    # -c, not `-d relaxed`: the two are mutually exclusive, and `-d` would
    # silently discard .yamllint.yml along with the one rule this project
    # overrides. The config file also lints ITSELF here, which `-d` could not
    # express — .yamllint.yml is checked alongside .github/ below.
    # --strict makes a WARNING exit non-zero. yamllint's default is to report
    # one and exit 0, which is how an 82-character line sat in ci.yml's CI
    # annotations for weeks while every run was "green" — and this is the same
    # week four pushes went out after a red build because nobody read the
    # notification. A warning nobody has to act on is noise, and noise is what
    # a real finding hides in. Safe to turn on precisely because the count is
    # zero right now; the config sets a limit these files can actually meet.
    yamllint --strict -c .yamllint.yml .yamllint.yml .github/
else
    # Deliberately no Python fallback: PyYAML is not a dependency, so
    # `import yaml` would crash on a clean machine — a gate that fails because
    # the gate is broken is worse than one that admits it did not run.
    skip "yamllint (.github/dependabot.yml unchecked)"
    printf 'install yamllint (your package manager, or: pipx install yamllint)\n'
fi

# Reported BEFORE the pass/skip line and in its own block, because the whole
# point is that it must not read as a detail inside a green run. A drifted tool
# does not make this run wrong; it makes it non-predictive, which is worse to
# discover from a red push than from four lines here.
if ((${#DRIFTED[@]})); then
    printf '\n%sTOOL DRIFT — %d tool(s) differ from what CI installs:%s\n' \
        "$YELLOW" "${#DRIFTED[@]}" "$RESET"
    for drift in "${DRIFTED[@]}"; do
        printf '  %s\n' "$drift"
    done
    printf 'Pins live in scripts/ci-tools.env. Install the pinned version, or\n'
    printf 'bump the pin there and re-run — GitHub will follow it.\n'
    if [[ ${LWSM_REQUIRE_ALL_TOOLS:-0} == 1 ]]; then
        # On the runner this is never a warning: the install step names exact
        # versions, so a mismatch means it did not do what it says and the pin
        # is decorative.
        printf '%sLWSM_REQUIRE_ALL_TOOLS=1: CI installed a version it did not promise.%s\n' \
            "$RED" "$RESET" >&2
        exit 1
    fi
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
elif ((${#DRIFTED[@]})); then
    # A distinct final line, not the plain green one. "Local CI passed." is
    # what a reader takes as "GitHub will pass too", and with a drifted tool
    # that inference is exactly what is unavailable.
    printf '\n%sLocal CI passed, but %d tool(s) DRIFTED from CI — see above.%s\n' \
        "$YELLOW" "${#DRIFTED[@]}" "$RESET"
else
    printf '\n%sLocal CI passed.%s\n' "$GREEN" "$RESET"
fi
