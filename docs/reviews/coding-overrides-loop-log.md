# coding-overrides loop log

Review rows for `docs/standards/coding-overrides`, written by `review-contract` (4d).

| Loop | Date | Lanes | Q1 | Q2 | Q3 | Q4 | Outcome |
|------|------|-------|----|----|----|----|---------|
| 1 | 2026-10-02 | 2 (`review-contract`, genre standard pinned, both lanes holding every question; `neutral-lane`) | 3 | 0 | 0 | — | **Verified 3, fixed 3, dismissed 1.** Gate armed by 51e3e8a (the file is new; no second share). Fixed: O4 said every child starts a new session, false for the scanner's captured `systemctl` query (both lanes); the O1 row claimed full coverage where the test reads `QtWidgets` only; O10's "the only sites `N` flags" was false (`ruff check --select N` also flags argument names and test names quoting constants). Dismissed: `__init__.py` "imports nothing" against its `__future__` import, which changes nothing built. |
| 2 | 2026-10-02 | 2 (`review-contract`, genre standard pinned, both lanes holding every question; `neutral-lane`) | 1 | 1 | 0 | — | **Verified 2, fixed 2, dismissed 0.** Fixed: the O3 row cited a browser data-path test as covering the config path (no test covers the config fallback; now said); O6 said config "is JSON" against `docs/design.md § Persistence`, which keeps `scan-roots` plain text. Measured clean: `ruff --select S` flags a `shell=True` string; `N` flags Qt overrides in `src/`. |
