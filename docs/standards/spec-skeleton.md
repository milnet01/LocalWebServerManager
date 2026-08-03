# <PREFIX>-NNNN — <short imperative title>

**Status:** spec draft (YYYY-MM-DD).
**Kind:** implement.
**Source:** ROADMAP <PREFIX>-NNNN (<where the ask came from>).

<!-- Relationship lines, only if they apply. Delete otherwise:
**Blocked by:** <ID>.  **Blocker for:** <ID>.  **Pairs with:** <ID>.
**Supersedes:** <ID>.  **Superseded by:** <ID>. -->

<!-- Layman: one plain-English sentence, required if this changes anything a
     user sees. Delete if the work is entirely internal. -->

## 1. Goal

<One paragraph. What is true after this ships that is not true now.>

## 2. Problem

<What is broken or missing, and why it matters now.
 Ground every claim in a symbol — `src/foo.py::bar()` — that you have
 actually opened. Never a line number. Number the consequences if there
 is more than one.>

## 3. Scope decisions (agreed with the user)

<The choices that were preference, not deduction, and who made them.
 This is what stops the same argument being had twice. If there were
 none, say "none — every choice below follows from §2".>

## 4. Design

### 4.1 <concern>

<The mechanism. Types, signatures, schemas and file layouts as fenced
 blocks — never prose narrating them. Name the exact files, functions,
 libraries and config keys you will add or touch.>

## 5. Invariants

<One per contract. Every one needs all three clauses.
 "Breaks when" is the important one: if nothing can break it, it is a
 tautology, not a contract — delete it and find the real one.

 Where the test is a command, write what it should output after the arrow,
 then RUN IT — now, not at review. A clause with no expected result can
 only be read, and a clause that is only read is one nobody has run.
 Where it is a manual recipe or a test-file path there is nothing to run:
 drop the arrow rather than inventing an output for it.>

- **INV-1** — <one testable claim, stated so it can fail>.
  *Test:* <a command> → <the exact output you just saw>.
  *Breaks when:* <the concrete input or state that makes it fail>.

- **INV-2** — <a claim whose test cannot be executed>.
  *Test:* <the manual recipe or test-file path that locks it — no arrow>.
  *Breaks when:* <the concrete input or state that makes it fail>.

<!-- If this work crosses a trust boundary — network, filesystem, user input,
     model output, IPC — state the boundary and the defence as an invariant
     here, including the existing defences the design must preserve. -->

## 6. Failure modes

<What happens when each assumption in §4 breaks. A design with only a
 happy path has not been designed.>

## 7. Tests

<Which test locks which invariant, where it lives, its label.
 Claim only what the test actually exercises.
 Note the requirement to see each test fail against pre-fix code.>

## 8. Alternatives considered (and rejected)

<Each with the reason it lost. A rejected option with no reason gets
 re-proposed in six months.>

## 9. Out of scope

- <deferred item> — tracked by <PREFIX>-NNNN.

## 10. Resource cost

<Required if this holds state or adds a build target: memory budget and
 eviction policy. No unbounded growth without a named cap. New external
 dependencies (prefer none). Otherwise: "none — no new state, no new
 build target, no new dependency".>

## 11. What checks this

<One row per rule or contract above. The right cell says exactly one of
 two things: a named catcher, or **nothing** in bold plus why (and a
 roadmap id if the gap is a defect rather than a limit).
 A row that is wrong is worse than a row that is missing.>

| Rule | What catches a breach |
|------|----------------------|
| INV-1 | <test file::test name> |
| INV-2 | **nothing** — <why>; tracked by <PREFIX>-NNNN |

## 12. Cross-doc impact

<Which other docs change in the same release: CLAUDE.md, CHANGELOG,
 README, sibling specs. "none" is a valid answer.>

## 13. Cold-eyes loop log

<Written as the loops happen — never back-filled. The tally must
 balance: findings recorded must equal outcomes recorded.>

| Loop | Date | Lanes | CRIT | HIGH | MED | LOW | Outcome |
|------|------|-------|------|------|-----|-----|---------|
