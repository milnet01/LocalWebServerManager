<!-- ants-commits-overrides: 1 -->
# Commits overrides — LocalWebServerManager

**Status:** v1 (2026-10-02).

Commits for this project follow the machine-global
`~/.claude/standards/commits.md`, with `~/.claude/standards/local-gate.md`
for the push gate, both read in place rather than copied. This file holds
only where this project differs, each with one line of why. Those files
are on the author's machine and not in this repository, so a contributor
reads this file and `CONTRIBUTING.md`.

## C1. A commit that changes code carries a body

Global § 1.4 makes the body optional; here it is required on every commit
that changes code. It records the mechanism-sweep outcome
(`coding-overrides.md` § O9), the mutation record (`testing-overrides.md`
§ T9) and the result of `./scripts/local-ci.sh`.

A session working under the author's machine-wide configuration, which
defines them, also writes its lines: a `write-code:` line naming what ran, a
`write-doc:` line saying what was checked, and a `CLAUDE.md rule 14:` line
per document that rule's test was asked of — in its scope or one of its
exclusions — recording the decision, a "no gate" included.

Why: the coding and testing overrides owe these records, and the commit
body is the only place they survive.

## C2. The push gate is this repository's own hook

The local gate (global § 4.2) is `.githooks/pre-push`, enabled per clone
with `git config core.hooksPath .githooks`. Where the machine-wide hook is
installed it runs that hook's secrets-only scan first; elsewhere — CI, a
contributor's clone — it prints `NO SECRET SCAN` and there is none. Then it
runs `scripts/local-ci.sh` — with `--docs` when every pushed path is
documentation the suite does not read (the hook's `docs_only()`). Its
bypasses are `LWSM_SKIP_PREPUSH=1`, which skips the gate and keeps any scan,
and `git push --no-verify`, which skips both;
each needs the user, per global § 2.3, and is recorded in the body of the
next commit, naming what was skipped and why. There is no `commit-msg` hook, so
subject shape (global §§ 1.1–1.3) is checked by nothing.

Why: the hook encodes which markdown the suite asserts against, which a
shared hook's path list cannot know; `CLAUDE.md` § Before pushing and
`docs/claude/ci-gate.md` hold the detail.

## C3. Pushes go freely

The repository is public on GitHub, whose runners cost it nothing, so
global § 4.1's free case applies: push per commit or in a batch, without
asking. A session still checks the visibility at its start, as § 4.1 asks.

Why: the free case is the answer this repository has given every time it
was checked.

## What checks this

| Rule | What checks it |
|------|----------------|
| C1 body carries the records | nothing — no hook reads a commit body |
| C2 the gate runs before a push | Partial: `tests/test_ci_contract.py` checks that `.githooks/pre-push` is present and executable, and that `docs_only()` never exempts a file `tests/test_docs.py` asserts against — nothing checks that a clone has set `core.hooksPath`, and nothing records a bypass |
| C2 secret scan | Partial: the machine-wide hook's scan, where it is installed — nothing scans a push from any other machine |
| C2 subject shape | nothing — there is no `commit-msg` hook |
| C3 the repository is public | nothing — `gh repo view --json visibility -q .visibility` answers it, and nothing runs it |
