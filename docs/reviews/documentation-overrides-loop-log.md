# documentation-overrides loop log

Review rows for `docs/standards/documentation-overrides`, written by `review-contract` (4d).

| Loop | Date | Lanes | Q1 | Q2 | Q3 | Q4 | Outcome |
|------|------|-------|----|----|----|----|---------|
| 1 | 2026-10-02 | 2 (`review-contract`, genre standard pinned, both lanes holding every question; `neutral-lane`) | 1 | 2 | 0 | — | **Verified 3, fixed 3, dismissed 0.** Gate armed by 51e3e8a (new file). Fixed: DOC1 claimed the test catches any growing-set count, where it matches one-to-twelve before a `COUNTED_NOUNS` word (both lanes); DOC2 stretched build-first to every contract document, where `CLAUDE.md` § Review cadence says it of specs (both lanes); DOC2's "reviewed after" against the rule-14 exception for a spec brought into line with verified code. Resolved clean: the hook routes these files to the full gate; `.gitignore` excludes `docs/private/`. |
