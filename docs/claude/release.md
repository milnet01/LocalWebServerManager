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
`cut-release`'s Phase 0 made runnable. It changes nothing git tracks; its
AppImage step builds into `dist/` and tags a local container image.

**It mirrors nothing, and that is the difference from `local-ci.sh`.**
That script is the CI — the workflow calls it. The release workflow
(`.github/workflows/release.yml`) attaches the AppImage only **after** a
release is published, so what it finds is found after the tag is public.
Run by hand, it builds and smoke-tests without uploading. This script is the
only automated gate that runs before a release; the big review above is the
other.

**It builds and smoke-tests the AppImage** with
`scripts/build-appimage.sh`, the script the release workflow runs, so a
broken AppImage blocks the release here (LWSM-1052). The smoke test runs on
Debian 13 and Debian 12. On each it launches the app offscreen and runs `ldd`
over the bundle's Qt platform plugins, failing on a missing library
(LWSM-1544). It needs uv and a
podman or docker that can run; without them, the check is skipped and the
verdict cannot read "ready".

Two things to know. **The verdict never reads "ready" while a check was
skipped** — a blocker and a check that could not run are tracked
separately, because "no blockers found" and "the blocker check did not
run" must not print the same way. And **`--dry-bump` works in a scratch worktree at HEAD**, never in your
tree, and refuses on a dirty tree, whose changes HEAD would not hold. It
once reverted with `git checkout` in your tree, which discarded a
`roadmap_log` render made while it ran (LWSM-1067, LWSM-1510).

`cut-release` still owns the release itself — this performs no bump, no
commit, no tag and no publish.

## After publishing: sign the AppImage

**Run `uv run scripts/sign-release.py publish X.Y.Z`** once the release is
published (LWSM-1548, ADR-0008). It waits for the Release workflow, downloads
the AppImage, signs it with the key on this PC, checks the signature against
the committed public key, and uploads the `.sig`. A release with no `.sig` is
offered to no installed AppImage. Run it again after moving a tag.

**Run it again after a re-run of the Release workflow too.** A re-run replaces
the AppImage already attached to the release (`gh release upload --clobber`,
LWSM-1546), so the `.sig` no longer matches it.

**The key is set up once, by the user:** `uv run scripts/sign-release.py
generate` writes it to `~/.config/lwsm-release/signing.key` and prints the
line for `src/lwsm/update_key.py`. **Back the key up.** Lost, every installed
AppImage refuses later updates until its user downloads one by hand. The key
never enters the repository or a Claude session.

`local-release.sh X.Y.Z` blocks when the key is missing or does not match
(its step 0j, through `sign-release.py check-key`). Nothing checks that
`publish` was run.
