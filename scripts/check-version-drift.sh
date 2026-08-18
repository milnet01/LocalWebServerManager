#!/usr/bin/env bash
# Assert every file that states the project's version states the SAME one.
#
# `pyproject.toml` is the source of truth; the other three are checked against
# it. The list here and `.claude/bump.json`'s `files` are the same list, and
# `tests/test_ci_contract.py` asserts they stay that way — a file the recipe
# bumps but this does not check is a file that can be left behind silently,
# which is the whole failure mode `releases.md` § 1 wants a mechanical answer
# to.
#
# Two callers, one implementation: `scripts/local-ci.sh` runs it on every gate,
# and it is the recipe's `post_check`, where a non-zero exit stops the release
# with the bump half-applied rather than committing it.
#
# WHY FOUR LITERALS RATHER THAN ONE DERIVED VALUE (LWSM-1067). The obvious fix
# is `importlib.metadata.version()` in `__init__.py`, and it is wrong here for
# two reasons. An editable install caches its metadata, so between bumping
# `pyproject.toml` and re-running `uv sync` that call still reports the OLD
# version — and `cut-release` Phase 2 tests the bumped tree in exactly that
# window, so the check would read a stale value at the one moment it matters.
# And README.md and ROADMAP.md state the version as PROSE, which nothing can
# derive at run time, so a recipe is needed whatever `__init__.py` does:
# deriving would take four files to three, never to one. A literal is always
# current with the file on disk. This script is what makes four of them safe.
set -Eeuo pipefail

cd "$(dirname "$0")/.."

# Deliberately NOT a grep of the tree for the version string. docs/decisions/
# 0002-port-contract.md contains `0.0.0.0`, a bind address, and a tree-wide
# grep cannot tell a version from an IP or from a historical marker
# ("added in 0.6.29") that becomes false the moment it is bumped.
source_of_truth=$(sed -n 's/^version = "\([0-9]\+\.[0-9]\+\.[0-9]\+\)"$/\1/p' pyproject.toml)
if [[ -z $source_of_truth ]]; then
    printf 'check-version-drift: no version found in pyproject.toml\n' >&2
    exit 1
fi

drift=0
expect() {
    local label=$1 path=$2 found=$3
    if [[ $found != "$source_of_truth" ]]; then
        printf '  %-28s %-14s (pyproject.toml says %s) %s\n' \
            "$label" "${found:-<not found>}" "$source_of_truth" "$path" >&2
        drift=1
    fi
}

# Each capture is the version TRIPLE rather than "everything up to the next
# delimiter". The loose form cost a false failure the first time this ran: the
# ROADMAP capture was anchored to a trailing period and the line continues
# " See", so it matched nothing and reported <not found> against a file that
# was correct.
V='\([0-9]\+\.[0-9]\+\.[0-9]\+\)'
expect "__version__" src/lwsm/__init__.py \
    "$(sed -n "s/^__version__ = \"$V\"\$/\1/p" src/lwsm/__init__.py)"
expect "README current version" README.md \
    "$(sed -n "s/^Current version: \*\*$V\*\*.*\$/\1/p" README.md)"
# Whatever follows the triple, not a period specifically: ROADMAP.md is
# rendered from Ants MCP's roadmap store and the tail of that line is the
# store's to decide, not ours.
expect "ROADMAP current version" ROADMAP.md \
    "$(sed -n "s/^> \*\*Current version:\*\* $V.*\$/\1/p" ROADMAP.md)"

if ((drift)); then
    printf '\ncheck-version-drift: files disagree about the version.\n' >&2
    printf 'Bump them together via .claude/bump.json (cut-release), not by hand.\n' >&2
    exit 1
fi

printf '  version %s, consistent across 4 files\n' "$source_of_truth"
