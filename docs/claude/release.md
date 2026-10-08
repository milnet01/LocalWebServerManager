# Releases

What a release owes before it is cut. Moved verbatim from `CLAUDE.md` on
2026-10-08 to keep the always-loaded file small; `CLAUDE.md` § Releases points
here.

## Standing quality passes

Both added by the user on 2026-08-03, and both run as part of the
pre-release review (see **Before a release: the big review**) rather than
when someone remembers:

- **Look for refactoring opportunities.** Python is interpreted, so
  there is no compiler catching a tangle — structure is held by
  reading alone. Before every release, ask what got duplicated, what
  grew a second responsibility, and what a name now lies about.
  Refactor when there is something to refactor; **say "nothing to
  refactor at this size" when there isn't**, rather than inventing
  churn to look diligent.
- **Run a security pass.** Not just the scanners — this app spawns
  processes, signals process groups, reads other projects' files and
  will eventually run user-authored commands. That is a real attack
  surface, and the scanners only see the code that exists today.

## Before a release: the big review

**Before cutting a release, run `check-code` over the whole tree and
`review-code` over the codebase, then `close-findings` on what they
return** (user, 2026-09-28), plus the two **Standing quality passes** above.
This is in addition to the per-item checks `~/.claude/workflow.md` § 6
requires, not instead of them. This replaces the retired `/close-phase`,
which ran the same pair at every phase close; the roadmap is now grouped
by version, so the release is the checkpoint. Read
`docs/audit-allowlist.md` first, as `CLAUDE.md` § Where state lives says. The findings
`close-findings` queues are filed into the release's roadmap section, and
the release waits on those. `./scripts/local-release.sh` (below) is the
mechanical pre-flight and does not replace this.

## Before releasing

**Run `./scripts/local-release.sh [X.Y.Z]`** (LWSM-1151). It is
`cut-release`'s Phase 0 made runnable, and it reports without changing
anything.

**It mirrors nothing, and that is the difference from `local-ci.sh`.**
That script is the CI — the workflow calls it. CI here fires on `push`
and `pull_request` only, with **no tag trigger and no release trigger**,
so *nothing on GitHub ever checks a release*. This script is the only
automated gate a release gets; the big review above is the other.

Two things to know. **The verdict never reads "ready" while a check was
skipped** — a blocker and a check that could not run are tracked
separately, because "no blockers found" and "the blocker check did not
run" must not print the same way. And **`--dry-bump` refuses on a dirty
tree**: its revert is a `git checkout`, which destroys uncommitted work.
That is the mistake LWSM-1067 made twice in one session, once taking a
`roadmap_log` flip with it and leaving ROADMAP.md saying 📋 while the
store said ✅.

`cut-release` still owns the release itself — this performs no bump, no
commit, no tag and no publish.
