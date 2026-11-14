# shellcheck shell=bash
# Shared by scripts/local-ci.sh and scripts/local-release.sh. Sourced, never
# run: `source scripts/lib.sh` once the caller has set `set -Eeuo pipefail` and
# changed into the repository root. It defines the colour variables, `step`,
# `fail`, and the ERR trap that names the step that broke.
#
# Each script keeps its own SKIPPED list and `skip`, because the two print a
# skip differently. Nothing here is a check.

# The callers use the colours; linted alone, this file does not.
# shellcheck disable=SC2034
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

# `set -E` in the caller is inert without an ERR trap, which left `fail` with a
# single caller: a ruff or pytest failure exited non-zero with no banner naming
# the step that broke. CURRENT_STEP is what makes the trap able to say.
CURRENT_STEP="startup"
trap 'fail "$CURRENT_STEP"' ERR
