# dependencies-overrides loop log

Review rows for `docs/standards/dependencies-overrides`, written by `review-contract` (4d).

| Loop | Date | Lanes | Q1 | Q2 | Q3 | Q4 | Outcome |
|------|------|-------|----|----|----|----|---------|
| 1 | 2026-10-02 | 2 (`review-contract`, genre standard pinned, both lanes holding every question; `neutral-lane`) | 0 | 1 | 3 | — | **Verified 4, fixed 4, dismissed 1.** Gate armed by 51e3e8a (new file). Fixed: D1 and D2 omitted the `scripts/ci-tools.env` pins (both lanes); D2's "checks the other pins" read as bump or report (both lanes, now bump, one per commit); D2 bumped a pin D7 holds; D5's "every ecosystem" left the interpreter, runner and CI tools undecided. The D7 row's claim about `check-dependencies` was unverified and deleted. Collateral in `.github/dependabot.yml` (a stale `§ 2.2`) corrected. Dismissed: `ci.yml`'s `dependencies.md § 9` (the shared file has a § 9). |
| 2 | 2026-10-02 | 2 (`review-contract`, genre standard pinned, both lanes holding every question; `neutral-lane`) | 1 | 1 | 2 | — | **Verified 4, fixed 4, dismissed 0.** Fixed: D3 read as making every untouched lagging pin a breach (now scoped to a D7 hold); D3 did not separate an upstream break from a migration; D2 left `uv.lock`'s transitive versions undecided; D5 claimed `check-dependencies` covers the CI tools, which its skill never names (measured). |
