# testing-overrides loop log

Review rows for `docs/standards/testing-overrides`, written by `review-contract` (4d).

| Loop | Date | Lanes | Q1 | Q2 | Q3 | Q4 | Outcome |
|------|------|-------|----|----|----|----|---------|
| 1 | 2026-10-02 | 2 (`review-contract`, genre standard pinned, both lanes holding every question; `neutral-lane`) | 0 | 2 | 4 | — | **Verified 6, fixed 6, dismissed 0.** Gate armed by 51e3e8a (new file). Fixed: T6 omitted `qapp`, which pyproject's `gui` definition covers (the checker reads `qtbot` and `app_font` only, now Partial); T11's Why said "quick run" where `--fast` drops integration tests (push gate meant); T7 said neither one case per state nor per table row, nor that cases come from the enumeration (both lanes, two findings); T9/T10 "counts once" read two ways (both lanes); T12 left a spec-less feature with no contract. Open question resolved clean: an unregistered marker stops the run (measured, exit 2). |
| 2 | 2026-10-02 | 2 (`review-contract`, genre standard pinned, both lanes holding every question; `neutral-lane`) | 1 | 2 | 0 | — | **Verified 3, fixed 3, dismissed 0.** Fixed: T7 asserted every enumeration member, which includes overlay labels ADR-0004 gives no row (both lanes; text this run wrote); T9's red admitted an import or name error, looser than global § 1; T9's "exit 5" omitted exit 4 for a missing node id (measured). |
