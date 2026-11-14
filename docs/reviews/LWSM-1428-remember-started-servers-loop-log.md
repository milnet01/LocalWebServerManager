# LWSM-1428 remember started servers loop log

## Cold-eyes loop log

Review rows for `docs/specs/LWSM-1428-remember-started-servers.md`.

| Loop | Date | Lanes | Q1 | Q2 | Q3 | Q4 | Outcome |
|------|------|-------|----|----|----|----|---------|
| — | 2026-10-29 | none | — | — | — | — | **Not reviewed, by the user's instruction** ("no review is needed, this isn't a complicated task"). Covers the ADR-0004 amendment too. |
| impl | 2026-11-05 | none | — | — | — | — | **Amendment, not a review; no reviewer dispatched.** LWSM-1494: § 4.4 vouches for an adopted group by a member's start time; INV-7 added. |
| impl | 2026-11-05 | none | — | — | — | — | **Amendment, not a review; no reviewer dispatched.** LWSM-1448, written before the code (CLAUDE.md review cadence rule 2): § 4.1 adds `since_boot` and `boot_id`, § 4.3 step 1 compares them; INV-8 added. |
| impl | 2026-11-05 | none | — | — | — | — | **Amendment, not a review; no reviewer dispatched.** LWSM-1447, folded back after the build: INV-2 exempts a stop after a quit froze the record, and § 6 adds the relaunch overlap the user accepted. |
| impl | 2026-11-05 | none | — | — | — | — | **Amendment, not a review; no reviewer dispatched.** LWSM-1513, folded back after the build: § 4.4 lets a live leader vouch, since its cached start time misreads after a clock step. |
| impl | 2026-11-14 | none | — | — | — | — | **Amendment, not a review; no reviewer dispatched.** LWSM-1524, folded back after the build: § 4.1 says an entry whose boot time could not be read at the start carries neither `since_boot` nor `boot_id`. |
