# LWSM-1005 history

Pedigree moved out of `docs/specs/LWSM-1005-vertical-slice.md` § 10 on
2026-10-08 (LWSM-1379), verbatim. Nothing here is a rule.

## From § 10, the paragraph under the table

The count was **eight**, and stayed eight after INV-17 and INV-18 landed
(LWSM-1108). Two rows claimed "nothing" against checks that existed: focus-ring
contrast is `test_theme.py::test_the_focus_ring_clears_the_indicator_floor`,
and the three state tokens' contrast is
`test_every_text_token_clears_the_text_floor`, which parametrises over
`state_running`, `state_stopped` and `state_unknown`. § 7's table *was* updated
when they landed and this section was not — so the number was wrong by two, and
a count re-asserted rather than re-derived is how it stayed wrong. Recomputed
from the rows above, not carried forward.
