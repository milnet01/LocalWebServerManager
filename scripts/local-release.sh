#!/usr/bin/env bash
# The RELEASE preflight. Run this before cutting a version; it answers
# "would a release stop, and where?" without changing anything.
#
# HOW THIS DIFFERS FROM scripts/local-ci.sh. That script IS the CI — the
# GitHub workflow calls it, so running it locally runs the same checks the
# same way. There is no release workflow to mirror: this project's CI fires
# on push and pull_request only, with no tag or release trigger, so nothing
# on GitHub ever checks a release. That makes this script the ONLY gate a
# release gets, rather than a local copy of a remote one.
#
# WHAT IT IS. `cut-release`'s Phase 0 made runnable. That skill is the release
# procedure and this is not a replacement for it: it performs no bump, no
# commit, no tag and no publish, and knows nothing about Phases 1-7. What it
# gives you is Phase 0's verdict in a terminal, before you have decided to
# start, and a real test of the recipe — which is where two defects came from
# the day the recipe was written (LWSM-1067): a pattern that matched twice
# because the roadmap quoted its own version line, and a bind address
# (0.0.0.0) that a grep-built file list would have bumped as a version.
#
# Usage:
#   ./scripts/local-release.sh              # everything that needs no target
#   ./scripts/local-release.sh 0.1.0        # the full preflight for 0.1.0
#   ./scripts/local-release.sh 0.1.0 --dry-bump
#                                           # also apply the bump, run
#                                           # post_check, and revert
set -Eeuo pipefail

cd "$(dirname "$0")/.."

RECIPE=.claude/bump.json

usage() {
    printf 'usage: %s [X.Y.Z] [--dry-bump]\n' "$0"
    printf '  X.Y.Z       the version you intend to cut; omitted, the checks\n'
    printf '              that need one are reported as SKIPPED\n'
    printf '  --dry-bump  apply the recipe, run post_check, then revert.\n'
    printf '              Refuses on a dirty tree — the revert is a git\n'
    printf '              checkout and would destroy uncommitted work\n'
}

TARGET=""
DRY_BUMP=0
for arg in "$@"; do
    case $arg in
        --dry-bump) DRY_BUMP=1 ;;
        -h | --help)
            usage
            exit 0
            ;;
        [0-9]*.[0-9]*.[0-9]*) TARGET=$arg ;;
        *)
            printf 'unknown argument: %s\n' "$arg" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ -t 1 && -z ${NO_COLOR:-} ]]; then
    BOLD=$'\033[1m'; RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'
    RESET=$'\033[0m'
else
    BOLD=''; RED=''; GREEN=''; YELLOW=''; RESET=''
fi

step() { CURRENT_STEP="$1"; printf '\n%s==> %s%s\n' "$BOLD" "$1" "$RESET"; }
fail() { printf '\n%sFAILED: %s%s\n' "$RED" "$1" "$RESET" >&2; exit 1; }
CURRENT_STEP="startup"
trap 'fail "$CURRENT_STEP"' ERR

# A release STOP, and a check that could not run, are different answers and
# are tracked separately — the same split scripts/local-ci.sh draws between a
# failure and a SKIP, and for the same reason: "no blockers found" and "the
# blocker check did not run" must not print the same way.
BLOCKERS=()
SKIPPED=()
block() { BLOCKERS+=("$1"); printf '%s  BLOCKED: %s%s\n' "$RED" "$1" "$RESET"; }
skip() { SKIPPED+=("$1"); printf '%s  SKIPPED: %s%s\n' "$YELLOW" "$1" "$RESET"; }
ok() { printf '  %s\n' "$1"; }

# --- 0a: the recipe exists and is in the dialect cut-release reads -----------

step "0a  Release recipe"
[[ -f $RECIPE ]] || fail "$RECIPE is missing — cut-release stops at Phase 0a"

# `pattern` is a LITERAL in files[] and a REGEX in version_pattern. A recipe
# written on the wrong side of that fails in the worst available way: the edit
# searches for the regex source text, finds nothing, and leaves the file at the
# old version. bump-recipe.md § Validating names three tells; all three are
# checked here rather than trusted.
python3 - "$RECIPE" <<'PY' || fail "recipe is not in the dialect cut-release reads"
import json, re, sys

recipe = json.loads(open(sys.argv[1]).read())
problems = []
for key in ("version_source", "version_pattern", "files"):
    if key not in recipe:
        problems.append(f"missing required key {key!r}")
for entry in recipe.get("files", []):
    path = entry.get("path", "<no path>")
    if "format" in entry:
        problems.append(f"{path}: has 'format' where 'replace' belongs")
    if "replace" not in entry:
        problems.append(f"{path}: no 'replace'")
    pattern = entry.get("pattern", "")
    if "(?P<" in pattern:
        problems.append(f"{path}: named capture group — pattern is a LITERAL here")
    if pattern.startswith("^") or pattern.endswith("$"):
        problems.append(f"{path}: regex anchors — pattern is a LITERAL here")
    if "{OLD}" not in pattern:
        problems.append(f"{path}: pattern does not contain {{OLD}}")
if "post_bump" in recipe:
    problems.append("'post_bump' object in place of tag/post_check")
try:
    re.compile(recipe.get("version_pattern", ""))
except re.error as exc:
    problems.append(f"version_pattern is not a valid regex: {exc}")
for problem in problems:
    print(f"  {problem}", file=sys.stderr)
sys.exit(1 if problems else 0)
PY
ok "$RECIPE is well-formed"

# --- 0b: OLD is extractable --------------------------------------------------

step "0b  Current version"
OLD=$(python3 - "$RECIPE" <<'PY'
import json, re, sys
recipe = json.loads(open(sys.argv[1]).read())
text = open(recipe["version_source"]).read()
match = re.search(recipe["version_pattern"], text, re.M)
print(match.group(1) if match else "")
PY
)
[[ -n $OLD ]] || fail "version_pattern matched nothing in the version_source"
ok "current version $OLD"
[[ -n $TARGET ]] && ok "target version  $TARGET"

step "0b  Version lockstep"
# Same script the recipe uses as post_check and the gate runs every push, so
# all three answers come from one implementation.
bash scripts/check-version-drift.sh

# --- the recipe actually applies ---------------------------------------------

step "0b  Recipe patterns resolve"
# Read-only: counts occurrences, writes nothing. This is the check that caught
# the roadmap quoting its own version line — the pattern matched twice, and a
# real bump would have stopped mid-release with the tree half-edited.
python3 - "$RECIPE" "$OLD" <<'PY' || fail "a recipe pattern does not match exactly once"
import json, sys

recipe = json.loads(open(sys.argv[1]).read())
old = sys.argv[2]
bad = False
for entry in recipe["files"]:
    pattern = entry["pattern"].replace("{OLD}", old)
    count = open(entry["path"]).read().count(pattern)
    verdict = "1 match" if count == 1 else f"{count} MATCHES"
    print(f"  {entry['path']:26} {verdict}")
    bad |= count != 1
sys.exit(1 if bad else 0)
PY

# --- 0c: tree state ----------------------------------------------------------

step "0c  Tree state"
if [[ -n $(git status --porcelain) ]]; then
    block "uncommitted changes — cut-release Phase 0c stops, or asks to stash"
    git status --short | sed 's/^/    /'
    TREE_CLEAN=0
else
    ok "clean"
    TREE_CLEAN=1
fi

# --- 0d: what is already published -------------------------------------------

step "0d  Already published"
if [[ -z $TARGET ]]; then
    skip "tag and release existence (needs a target version)"
else
    TAG=$(python3 -c "
import json,sys
recipe=json.loads(open('$RECIPE').read())
print(recipe.get('tag','').replace('{NEW}','$TARGET'))")
    if [[ -z $TAG ]]; then
        ok "recipe has no tag template — nothing to check"
    else
        if [[ -n $(git tag -l "$TAG") ]]; then
            block "local tag $TAG already exists"
        elif [[ -n $(git ls-remote --tags origin "$TAG" 2>/dev/null) ]]; then
            block "tag $TAG is already on the remote — people may have fetched it"
        elif gh release view "$TAG" >/dev/null 2>&1; then
            block "release $TAG is already published"
        else
            ok "$TAG is free — no local tag, no remote tag, no release"
        fi
    fi
fi

# --- 0e: the changelog section -----------------------------------------------

step "0e  Changelog section"
if [[ -z $TARGET ]]; then
    skip "dated changelog section (needs a target version)"
    SECTION_FOUND=0
else
    # Match either dash: changelog-format.md § 4.3 spells the heading with an
    # em dash, and `changelog_log op:release` closes one with an ASCII hyphen.
    # The DATE is what decides, not the dash — an undated `## [X.Y.Z]` is an
    # RC-flow placeholder and publishing from it puts "unreleased" in the notes.
    if grep -qE "^## \[$TARGET\] [—-] [0-9]{4}-[0-9]{2}-[0-9]{2}" CHANGELOG.md; then
        LINES=$(awk -v v="$TARGET" '
            $0 ~ "^## \\[" v "\\] [—-] [0-9]" {f=1; next}
            /^## \[/ {f=0}
            f && NF' CHANGELOG.md | wc -l)
        if ((LINES == 0)); then
            block "the [$TARGET] section is dated but empty"
            SECTION_FOUND=0
        else
            ok "dated section present, $LINES non-blank lines"
            SECTION_FOUND=1
        fi
    else
        block "no dated '## [$TARGET] — YYYY-MM-DD' section; move [Unreleased] into one"
        SECTION_FOUND=0
    fi
fi

# --- 0f: does the roadmap agree the cited work shipped? ----------------------

step "0f  Roadmap agrees with the changelog"
if ((SECTION_FOUND == 0)); then
    skip "roadmap cross-check (needs the changelog section)"
else
    # Only an ID that STARTS a bullet is a claim that it shipped. One in
    # continuation prose is a cross-reference, and firing on those turns one
    # real finding into a list nobody reads.
    ids=$(awk -v v="$TARGET" '
        $0 ~ "^## \\[" v "\\] [—-] [0-9]" {f=1; next}
        /^## \[/ {f=0}
        f && /^- /' CHANGELOG.md | grep -oE '[A-Z][A-Z0-9]*-[0-9]+' | sort -u)
    if [[ -z $ids ]]; then
        ok "the section cites no roadmap IDs — an observation, not a stop"
    else
        unshipped=0
        for id in $ids; do
            # The archives too: a release routinely cites work closed in an
            # earlier minor, which roadmap-format.md § 3.9 rotated out of
            # ROADMAP.md. Looking only at the current file cannot tell an
            # archived ID from one that never existed.
            line=$(grep -m1 -F "[$id]" ROADMAP.md docs/roadmap/*.md 2>/dev/null || true)
            if [[ -z $line ]]; then
                block "$id is cited as shipped but appears in no roadmap"
                unshipped=$((unshipped + 1))
            elif [[ $line != *"✅"* ]]; then
                block "$id is cited as shipped but is not ✅"
                unshipped=$((unshipped + 1))
            fi
        done
        ((unshipped == 0)) && ok "all $(echo "$ids" | wc -l) cited IDs are ✅"
        # Stated limit, so the report is not read as exhaustive: a claim made
        # in continuation prose — "(also closes X)" — sits in a position
        # nothing can distinguish from a cross-reference, and is missed.
        printf '  note: a shipping claim written in continuation prose is not detected\n'
    fi
fi

# --- 0g: what a release would cost -------------------------------------------

step "0g  Visibility and CI cost"
VISIBILITY=$(gh repo view --json visibility -q .visibility 2>/dev/null || true)
if [[ -z $VISIBILITY ]]; then
    skip "visibility (no gh, no remote, or not authenticated)"
else
    ok "$VISIBILITY"
    runs=0
    grep -qE '^\s+branches:' .github/workflows/*.yml && runs=$((runs + 1))
    grep -qE '^\s+tags:' .github/workflows/*.yml && runs=$((runs + 1))
    grep -qE '^\s+release:' .github/workflows/*.yml && runs=$((runs + 1))
    ok "$runs workflow run(s) would fire: no tag trigger and no release trigger means"
    ok "the release commit's push is the only one"
fi

# --- optional: prove the bump applies and post_check passes ------------------

if ((DRY_BUMP)); then
    step "Dry bump (writes, then reverts)"
    if ((TREE_CLEAN == 0)); then
        fail "--dry-bump refuses on a dirty tree: the revert is a git checkout, and it would destroy the uncommitted work listed above"
    fi
    [[ -n $TARGET ]] || fail "--dry-bump needs a target version"
    python3 - "$RECIPE" "$OLD" "$TARGET" <<'PY'
import json, sys
recipe = json.loads(open(sys.argv[1]).read())
old, new = sys.argv[2], sys.argv[3]
for entry in recipe["files"]:
    path = entry["path"]
    text = open(path).read()
    pattern = entry["pattern"].replace("{OLD}", old)
    replace = entry["replace"].replace("{OLD}", old).replace("{NEW}", new)
    open(path, "w").write(text.replace(pattern, replace, 1))
    print(f"  bumped {path}")
PY
    post_check=$(python3 -c "
import json
print(json.loads(open('$RECIPE').read()).get('post_check',''))")
    bump_failed=0
    if [[ -n $post_check ]]; then
        # Not under the ERR trap: the revert below MUST run even when this
        # fails, or the preflight leaves the tree bumped — the exact
        # half-applied state the whole exercise exists to avoid.
        if eval "$post_check"; then
            ok "post_check passed on the bumped tree"
        else
            bump_failed=1
        fi
    else
        skip "post_check (the recipe defines none)"
    fi
    # Revert only the recipe's own paths, never `git checkout -- .`.
    mapfile -t paths < <(python3 -c "
import json
for e in json.loads(open('$RECIPE').read())['files']: print(e['path'])")
    git checkout -- "${paths[@]}"
    ok "reverted ${#paths[@]} file(s) to $OLD"
    ((bump_failed == 0)) || block "post_check failed on the bumped tree"
fi

# --- verdict -----------------------------------------------------------------

printf '\n'
if ((${#BLOCKERS[@]})); then
    printf '%sNOT READY — %d blocker(s):%s\n' "$RED" "${#BLOCKERS[@]}" "$RESET"
    for item in "${BLOCKERS[@]}"; do printf '  - %s\n' "$item"; done
    ((${#SKIPPED[@]})) && printf '%s%d check(s) skipped.%s\n' \
        "$YELLOW" "${#SKIPPED[@]}" "$RESET"
    exit 1
fi
if ((${#SKIPPED[@]})); then
    # Deliberately NOT "ready". A skipped check has no answer, and the one
    # thing this script must never do is let "not checked" read as "clear".
    printf '%sNo blockers found, but %d check(s) did not run:%s\n' \
        "$YELLOW" "${#SKIPPED[@]}" "$RESET"
    for item in "${SKIPPED[@]}"; do printf '  - %s\n' "$item"; done
    [[ -z $TARGET ]] && printf 'Pass a target version to run all of them.\n'
    exit 0
fi
printf '%sREADY to cut %s. Run the release with: cut-release %s%s\n' \
    "$GREEN" "$TARGET" "$TARGET" "$RESET"
