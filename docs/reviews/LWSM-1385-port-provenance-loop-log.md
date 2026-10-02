# LWSM-1385 port provenance loop log

## Cold-eyes loop log

Review rows for `docs/specs/LWSM-1385-port-provenance.md`, written by `review-contract`.

| Loop | Date | Lanes | Q1 | Q2 | Q3 | Q4 | Outcome |
|------|------|-------|----|----|----|----|---------|
| 1 | 2026-10-02 | 2 (`review-lane` via `neutral-lane`, every lane holding every question, spec genre pinned) | 3 | 1 | 0 | 1 | **5 verified, 0 dismissed, 5 fixed.** Q1: `export_profile` named as the clearer when `merge_imported` clears on import; the generic `getattr` copy in `_detected_half_applied` would raise on `port_from`, not write `None`, so § 4.4 now excludes both fields and INV-4's *Breaks when* names the real failure; `_settle_port` ranks five findings, not six. Q2: INV-3 said one field per refusal while the table and INV-2 drop `port_conflicts` with a refused `port_from`. Q4: INV-8 did not catch a second `PortRule` left in `scanner.py`. Two open questions resolved clean, not in the tally: `MainWindow._should_write` compares record content, so a provenance-only rescan is saved; an older build leaving stale conflicts beside an unchanged port was judged not material. |
