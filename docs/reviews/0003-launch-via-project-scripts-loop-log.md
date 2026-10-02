# ADR-0003 — review-contract loop log

ADR-0003 carried no loop log before its first gate, and nothing requires one,
so its review history lives here (`review-contract` Phase 4d). Row numbers are
this document's, oldest first.

| Loop | Date | Trigger | Lanes | Q1 | Q2 | Q3 | Q4 | Verified / fixed / dismissed | Outcome |
|------|------|---------|-------|----|----|----|----|------------------------------|---------|
| 1 | 2026-10-02 | `e092a10` (LWSM-1012, adopted-unit binding) | 2, every lane held every question; neutral-lane, neither arrived holding a git snapshot | 1 | 2 | 1 | — | 4 / 4 / 0 | Both lanes confirmed the armed bullet against `unit_belongs_to`. Q3, in span (lane A, raised as an open question): an absolute-path anchor admitted an autostarted editor handed the project's directory; the anchor is now a file the unit runs, code and ADR together, red test first. Q2 (both lanes): § Detection let a name match bind a unit, against the location rule; now a candidate only, and it names adoption. Q2 (lane A): the group paragraph prescribed `os.killpg` while § Stop prescribes `psutil` handles; narrowed to what the code does. Q1 + Q3 (both lanes): the drop-in example omitted `LWSM_MANAGED` and the ADR never said when the drop-in is removed; both recorded from the existing code. The three out-of-span fixes record verified code (rule 14's first exception), so were fixed in-run. In passing: ADR-0004 cited ADR-0003's `os.killpg`; corrected to "group-wide stop". Both NEEDS MEASUREMENT claims (psutil 7.2.2 reuse guard; PySide6 6.11.1 lacks `setChildProcessModifier`) ran true. Span share so far: 1 of 4. |
