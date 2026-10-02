# ADR-0004 — review-contract loop log

ADR-0004 carried no loop log before this gate, and nothing requires one, so
its review history lives here (`review-contract` Phase 4d). Row numbers are
this document's, oldest first.

| Loop | Date | Trigger | Lanes | Q1 | Q2 | Q3 | Q4 | Verified / fixed / dismissed | Outcome |
|------|------|---------|-------|----|----|----|----|------------------------------|---------|
| 1 | 2026-10-02 | `9cdc1da` (LWSM-1011: service row, wider plausibility test, unknown) | 2, every lane held every question; neutral-lane, no git snapshot | 2 | 4 | 1 | — | 7 / 7 / 0 | Q2, in span (lane B), a code defect: the service row made ANY user unit plus a plausible holder `running (managed)`. Measured for the lane's NEEDS MEASUREMENT: terminals run as user services here (`app-ants\x2dterminal@….service`), so a server started in a terminal read managed, and LWSM-1301's set-stop never fired for it. The classifier now asks for the project's own unit (bound, adopted, or passing ADR-0003's rule, cached), and the window routes Stop by `running (foreign)`; red tests first; the live trays still read `running`. Q1 (lane A): "own child" meant the launcher in the table and the group in the code; defined as the group, with the holder rows first. Q2 (both): row 63 and the `failed` evidence rule disagreed, and row 62 said `stopped` whatever held the port; both now match the code. Q2 (both): two disclosure field lists; now one names the holder's fields and the set dialog is separate. Q3 (both): "expiring" overlay could read as a timer. Q1 (lane B): "listening" vs the localhost-reachable rule (LWSM-1232). In passing: `glossary.md`'s overlay entry carried the same "expiring". Span share so far: 2 of 7. |
