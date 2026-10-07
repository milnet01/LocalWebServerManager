# LWSM-1034 health check loop log

## Cold-eyes loop log

Review rows for `docs/specs/LWSM-1034-health-check.md`, written by `review-contract`.

| Loop | Date | Lanes | Q1 | Q2 | Q3 | Q4 | Outcome |
|------|------|-------|----|----|----|----|---------|
| 1 | 2026-10-07 | 2 (`review-lane` via `neutral-lane`, every lane holding every question, spec genre pinned) | 1 | 1 | 0 | 0 | **2 verified, 2 fixed, 1 dismissed.** Q2, both lanes: the no-answer tooltip said "did not answer within 2 seconds" while § 4.1 maps a refused connection and a non-HTTP reply to the same `None`; reworded to "gave no HTTP answer", and the `HealthAnswer` comment with it. Q1, both lanes as an open question, verified in `registry._refuse_unwritable_load`: § 6 and INV-11 said a refused user field makes the session read-only; it does not (only a row refusal does), and the real effect is that `export_profile` refuses (LWSM-1215). Dismissed as immaterial, both lanes: INV-12's input cannot come from the file, since `HEALTH_PATH_PATTERN` refuses it; its false trust-boundary sentence was deleted under Phase 3's carve-out. Open questions that resolved clean, not in the tally: `_status_of` does return the overlay; `hello\r\n` raises `BadStatusLine` (an `HTTPException`) and a silent server `TimeoutError` (an `OSError`), both measured. Out of scope, filed as LWSM-1396: the same read-only claim in LWSM-1385 INV-3 and LWSM-1038, and LWSM-1005 INV-16's single-wait bound against `stop()`'s sequential pool waits. |
