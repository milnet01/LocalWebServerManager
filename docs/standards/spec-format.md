<!-- ants-spec-format: 1 -->
# Spec- and plan-authoring standard — v1

**Status:** v1 (2026-07-27).
**Applies to:** every file under `docs/specs/` and `docs/plans/`.

A **spec** is the implementation contract for one roadmap item: what must
be true when it ships, and how each claim is proven. A **plan** is the
ordered build steps for that same item. They are separate files because
they answer different questions and go stale at different rates — a
contract outlives the steps that satisfied it.

This standard is the generalised form of the format the mature projects
converged on independently (`Ants_Terminal/docs/standards/specs.md`,
`OneUp/docs/standards/documentation.md` §4–§7). It exists so authors stop
reverse-engineering the format from old specs, and so specs stay parseable
by the `spec_query` MCP verb (§7).

**This is the project's copy** and it wins for work in this repo. The
upstream original is `~/.claude/skills/_shared/spec-format.md`. Keep this a
verbatim copy: project-specific changes go at the bottom under
`## <Project> overrides`, immediately before `## What checks this`, so the
two stay diffable. A silently-forked copy is worse than no copy — it wins,
and it wins with the upstream's fixes missing.

---

## 0. How to use this — you should rarely read past here

This document is a **reference**, not a procedure. Reading 400 lines before
writing a spec is how variance gets in. Three tiers, and most work only
touches the first:

1. **Run `/write-spec`.** It resolves the id, copies the skeleton (§9),
   runs the deterministic gate, and drives the review loop. Nothing to
   remember and nothing to choose.
2. **Before you commit, walk the ten-item checklist below.** These are the
   judgment calls no script can make. Ten lines, not four hundred.
3. **Read a numbered section only when a check fires** and you want to know
   why the rule exists. Every rule below is here because its absence shipped
   a defect; the section says which one.

### Before you commit — the ten

The gate catches everything countable. These are what it cannot:

1. Does every invariant name **what input breaks it** — honestly? (§3.7)
2. Could any invariant pass on **every possible input**? Then it is a
   tautology, not a contract. (§3.7)
3. Does any test claim to prove **more than it exercises**? (§3.9)
4. Is every fact stated in exactly **one** place? (§5.2)
5. Was every cited symbol, constant and behaviour **actually looked at**,
   not recalled? (§5.1)
6. Are the **preference calls** recorded, with who made them? (§3.5)
7. Does each rejected alternative carry **why** it lost? (§3.10)
8. Does the **What checks this** table say `nothing` where that is the
   truth, rather than naming a catcher that does not really catch it?
   (§3.12)
9. `/doc-lint` `size` reports the line count — given it, **is the split worth
   it**? (§5.4)
10. Does every plan step have an **observable** verification? (§8)

### The one number that matters

Count the rows in your **What checks this** table (§3.12) that say
`nothing`. That is the size of the surface where mistakes can still get
through — this process's honest error budget. When a reviewer or a human
catches the same class twice, convert that row into a mechanical check
(§5.7) and the number drops. A process getting genuinely more reproducible
is a process where that count falls over time; nothing else is evidence.

---

## 1. When a spec is required

Write a spec when the work has a **non-obvious contract** — invariants a
future change could silently break, a data shape other code depends on, a
security boundary, or a design spanning several files.

Skip the formal spec when the work is mechanical: a typo, a one-line fix, a
menu entry, a dependency bump. A regression test is more useful than a
document. A `spec.md` beside a feature test (`tests/features/<name>/`) is
the right home for a single-invariant behaviour; `docs/specs/` is for
designs whose contract spans files.

When unsure, write the spec. It is cheaper than the rewrite that follows an
unstated assumption.

## 2. Files and naming

```
docs/specs/<ID>-<topic>.md    the contract
docs/plans/<ID>-<topic>.md    the build steps
```

- `<ID>` is the stable roadmap id (`<PREFIX>-NNNN`). `<topic>` is two to
  four kebab-case words. Both are needed: the id links to the roadmap and
  is what `spec_query` routes on, the topic makes a directory listing
  readable.
- One spec per roadmap item. Cross-cutting work gets one spec per id,
  cross-referenced in the header — or one umbrella spec whose header lists
  every id it covers.
- A plan is optional for small items and mandatory once the build order
  matters (a migration, a change that must land in a specific sequence, or
  anything a second person will execute).

## 3. Required spec structure

In this order. Skip a section only when it would be empty, and **say so**
rather than leaving a bare heading — an omitted section reads as an
oversight, an explicit "none" reads as a decision.

### 3.1 Title

```
# <PREFIX>-NNNN — <short imperative title>
```

One line; this is what `spec_query` returns as `title`. Backtick code
identifiers.

### 3.2 Header block

Bold key-values immediately under the H1:

```
**Status:** spec draft (YYYY-MM-DD).
**Kind:** implement.
**Source:** ROADMAP <PREFIX>-NNNN (<provenance>).
```

- **Status** (required, parsed) — `spec draft (DATE)` → `accepted (DATE)` →
  `shipped X.Y.Z (DATE)`. The Status line names the **current state only**.
  Loop history belongs in the loop log (§6), never here — a Status line
  carrying history is a field with two jobs.
- **Kind** (required, parsed) — same taxonomy as the roadmap `Kind:` field.
- **Source** (required) — provenance: the roadmap id plus where the ask came
  from (`user-request-DATE`, `code-quality-review-DATE lane-N`, an incident, a
  dependency surfaced while sizing another item).
- **Relationship lines** where they apply: `**Blocker for:**`,
  `**Blocked by:**`, `**Pairs with:**`, `**Supersedes:** /
  **Superseded by:**`. The dependency graph belongs in the docs, not in
  someone's memory.

### 3.3 Goal

One paragraph: what is true after this ships that is not true now.

### 3.4 Problem

What is broken or missing, and why it matters *now*. Ground every claim
about current behaviour in a **symbol** reference (`src/foo.cpp::bar()`),
verified against live source — never a line number (§5.1). Number the
consequences when there is more than one, so the invariants in §3.7 trace
back to them.

### 3.5 Scope decisions (agreed with the user)

The choices that were preference rather than deduction, and who made them.
This is the section that stops the same argument being had twice. A design
fork resolved in conversation and recorded nowhere gets re-opened.

### 3.6 Design

The mechanism, broken into `### N.1`, `### N.2`… subsections by concern.
Conventions:

- Show new types, function signatures, schemas and wire formats as fenced
  blocks in the project's current idiom (per `coding.md`) — never as prose
  narrating them.
- Name the **exact** files, functions, libraries and config keys you will
  add or touch. "A helper in the cache layer" is not a contract;
  `src/auditcache.cpp` joining `audit_lib` is.
- Pseudocode is fine for an algorithm prose would obscure.

### 3.7 Invariants

Numbered, independently testable contracts. Bullet form:

```
- **INV-1** — <one testable claim>. *Test:* <test surface> → <expected result>.
  *Breaks when:* <the concrete input or state that makes this fail>.
```

Five rules, each of which exists because its absence shipped a defect:

- **Every invariant names its test surface.** An invariant with no test is
  a wish, not a contract. A spec that ships with an untested invariant is
  incomplete — that is the definition, not an opinion.
- **A `*Test:*` that is a command states what it should output.** The
  command is the test surface; the expected result is what turns running it
  into a comparison rather than a judgement — and a clause with nothing to
  compare against is one that can only be read. Three of the eight
  invariants in the first spec to adopt this standard shipped with clauses
  that failed or could not run: one cited a section that did not exist, one
  returned six files where it claimed five, one was a tautology over a
  gitignored path. All three die in seconds when the clause is executed;
  reading them caught none. `/write-spec` Step 3 owns *when* to run it.
- **Every invariant names what breaks it.** State the concrete input or
  state that makes the assertion fail. If the honest answer is *nothing
  can*, the invariant is not a contract — it is a tautology, and you have
  just found a defect for free. This rule exists because a financial-import
  checksum of the form `opening + Σ(deltas) == closing` shipped into a spec
  and reached cold-eyes review: it is a telescoping identity, true for any
  input, and could never have failed. Asking "what breaks this?" catches
  that class at authoring time; asking "is it testable?" does not, because
  a tautology is trivially testable.
- **State it so it can fail.** "Handles errors gracefully" cannot fail a
  test. "A failed step is recorded, emits a plain-English hint, and the run
  continues to the next step" can.
- **Never renumber.** `INV-N` ids are stable handles cited from CHANGELOG,
  CLAUDE.md and sibling specs. If an invariant dies, mark it withdrawn. If
  it changes, add a new one or annotate the old (`INV-7 amended by
  <ID>`). Never reflow the list.

The GFM table form (`| INV-1 | claim | test surface |`) also parses, but
the bullet form is the default — it is what `spec_log op:append_inv` writes,
so a table guarantees mixed formatting the first time anything appends
programmatically.

### 3.8 Failure modes

What happens when each assumption breaks. A design that only describes the
happy path has not been designed.

### 3.9 Tests

Which test locks which invariant, and where it lives: the test directory,
the label, and — per the project's test convention — the requirement to
**verify each test fails against pre-fix code** before the fix is restored.
Give the manual recipe as a subsection where a leg cannot be automated.

Do not claim a test proves more than it exercises. A build-smoke leg that
never loads an icon does not prove icon loading, and a Definition of Done
saying it does is a false contract.

### 3.10 Alternatives considered (and rejected)

Each with the reason it lost. A rejected option with no recorded reason
gets re-proposed in six months.

### 3.11 Out of scope

Deliberately, each line pointing at the follow-up roadmap id that carries
it — so absence reads as a decision rather than an oversight.

### 3.12 What checks this

One table: each rule or contract this spec sets, and what catches a breach.
`documentation.md` §1.8 owns the table's rules — the two permitted cell
forms, one row per rule, and why a wrong row is worse than a missing one.

| Rule | What catches a breach |
|------|----------------------|
| INV-1 | `tests/features/foo/test_foo.py::test_bar` |
| INV-4 | **nothing** — needs a GUI harness; tracked by `<PREFIX>-NNNN` |

Two spec-side specifics: rows are keyed by `INV-N` (or a section number for
a non-invariant rule), and in a spec this section is **numbered** like every
other — the unnumbered form is for standards.

### 3.13 Cross-doc impact

Which other documents change in the same release — CLAUDE.md module map,
CHANGELOG, README, sibling specs.

## 4. Recommended sections

Add when they carry weight:

- **Resource cost** — required for any feature that holds state or adds a
  build target. State the memory budget and eviction policy at design
  time: no unbounded growth ships without a named cap. Note new external
  dependencies (prefer none).
- **Migration / compatibility** — for changes to an existing on-disk
  format, schema, or public contract: how old data and callers are handled.
- **Open questions** — unresolved forks, so a reviewer knows where
  judgment is still needed.

## 5. Conventions

### 5.1 Grounding

`documentation.md` §1.7 owns the rule: cite by symbol, never by line
number, and back every claim with a read against current source.

The spec-side stakes, which is why it leads this section: a spec built on
an unverified assumption is found wrong on a later pass and forces a
rewrite of everything downstream. Two real examples from this corpus — a
function documented as returning one token, in a section headed *"Verified
API basis"*, that returned another; and a test seam described across
several paragraphs that did not exist at all. Both were written from
memory. Both cost a review pass that a symbol lookup would have saved.

### 5.2 One thing, one name

`documentation.md` §1.5 owns this rule. It is the single largest driver of
review cost, so it is restated here as a pointer and nothing more — a
second copy of the one-copy rule would be its own counterexample.

Spec-side application: when a review's findings are mostly "§A and §B
disagree", delete N−1 and leave a pointer rather than reconciling the
copies. `/cold-eyes` Phase 4 explains why that shortens the whole run.

### 5.3 Brevity

`documentation.md` §1.6 owns the length yardsticks. They apply to a spec
unchanged: the spec is subject to the same shortest-correct-form gate as
the code it specifies.

### 5.4 Size gate — split before reviewing

Before the first review pass, size the spec honestly. `/cold-eyes`
converges in one to three loops by design, with five as a runaway guard.
A spec that needs more than that is larger than the review's design point,
and the correct response is to split it — not to keep looping.

`/doc-lint` `size` reports each doc's line count and carries the evidence for
why an oversized spec costs more loops than it saves. If your spec is in
that territory, split it along the seams in §3.6 and give each part its own
id — splitting before the first review is cheap; splitting at loop eight
means eight loops were wasted.

### 5.5 Security boundaries

If the work crosses a trust boundary (network, filesystem, user input,
model output, IPC), the spec states the boundary and the defence as an
invariant. Re-state the existing defences the design must preserve — path
validation, secret redaction, scheme allowlists — rather than silently
relying on them.

### 5.6 Layman line

Where a spec describes user-facing behaviour, include a one-sentence
plain-English **Layman:** gloss so a non-technical reader can follow the
*what*.

### 5.7 Escalation — the same class twice becomes a check

When a reviewer or a human catches the same *class* of defect twice, it
stops being a review finding and becomes a mechanical check: add it to
`/doc-lint`'s `references/checks.md`.

The general rule, and the cheapest-first table of catchers it rests on,
live in `documentation.md` §8.2 — this section is the spec-side pointer at
it, not a second copy.

### 5.8 The table's count is checked, not trusted

The *What checks this* count (§3.12) was wrong in three consecutive review
loops — in this standard, and in the first spec to adopt it. Not bad luck: a
hand-maintained number nobody recomputes is a number that drifts, and the
failure is invisible because a wrong count reads exactly like a right one.

So it is now a `/doc-lint` `what-checks-this` check, along with two siblings: no cell may
blur a named catcher and a `nothing`, and no cell may name a `/doc-lint` check that
`/doc-lint` does not contain. That third one is the important one — an invented
catcher is precisely the defect the table exists to prevent, and it was
found twice.

The general lesson, which is §5.7's: a compliance artifact that is itself
unverifiable is a wish wearing a table's clothes.

## 6. Review gate

Every spec runs through `/cold-eyes` before implementation, looped until it
converges. The skill owns the procedure — the loop, the per-loop severity
tally, the definition of convergence, and the post-fix blast-radius check.
**This standard does not restate those rules** (§5.2); read the skill.

`documentation.md` §8.1 owns the loop-log requirements — that it is written
as the loops happen rather than back-filled, that every row carries an
outcome, and that a gated document without one has not been through the
gate. They apply to a spec unchanged.

One spec-side specific: `spec_log op:append_loop` writes **bullet** form. If
the spec's log is a table (as the skeleton ships), add the row with `Edit`
instead — mixing the two makes the row unreadable to `/doc-lint`'s `loop-log` check.

## 7. Machine-readability

`spec_query` parses a spec into
`{id, title, status, kind, invariants:[{id, body, test_surface?}]}`. To stay
parseable, keep the H1 as `# <PREFIX>-NNNN — title`, the `**Status:**` and
`**Kind:**` lines as the first bold key-values, and invariants in the
bullet form `- **INV-N** — body` with a `*Test:*` clause.

Where `spec_query` is available (it is an Ants MCP verb, so not every
project has it), `/doc-lint`'s `structure` check runs it against the draft and confirms the
title, status, kind and every invariant come back. Without the MCP this
rule has no mechanical catcher — the format still applies, but nothing
enforces it.

## 8. Plan format

A plan is deliberately thin: ordered steps, each with its verification.
Skeleton at `plan-skeleton.md` beside this file.

Rules:

- **Every step has a verification.** A step whose completion cannot be
  observed is a step nobody can tell you finished.
- **No design rationale** — it lives in the spec. `documentation.md` §10
  owns this rule and says why.
- **Steps cite the invariants they satisfy** where the mapping is not
  obvious.
- **Status** uses the plan's own vocabulary — `not started` / `in progress` /
  `done (DATE)` — not the spec lifecycle in §3.2. A plan is disposable: once
  the work ships it is history, while the spec stays.
- The whole-item check goes under **Definition of done**, the same term §3.9
  uses. One name per concept.

## 9. Skeletons

Two files beside this one. `/write-spec` copies them; there is no second
copy embedded here, because a skeleton in two places is two skeletons
(§5.2).

| File | For |
|------|-----|
| [`spec-skeleton.md`](spec-skeleton.md) | a new spec — every section pre-numbered, with the authoring prompt inline as a comment |
| [`plan-skeleton.md`](plan-skeleton.md) | a new plan |

The prompts live **in** the skeleton so an author never needs this standard
open. That is deliberate: a rule you must remember to look up is a rule that
gets applied inconsistently.

**Numbering differs on purpose.** The skeleton numbers its sections from 1
(`## 1. Goal`); this standard describes them as §3.3, §3.4… because they are
nested inside §3 *Required spec structure*. A finished spec uses the
skeleton's numbering. When citing a rule *about* specs, cite this file's
§3.N; when citing a section *of* a spec, use that spec's own number.

The mapping is **not a fixed offset**. It runs skeleton §1 ↔ §3.3 through
skeleton §9 ↔ §3.11, then the skeleton inserts *Resource cost* — a §4
recommended section, not a §3 required one — at its §10, so everything after
shifts by one more (skeleton §11 ↔ §3.12, §12 ↔ §3.13). The skeleton's last
section, §13 *Cold-eyes loop log*, has no §3.N counterpart at all — the loop
log is governed by §6, not by the required-structure list. Count the mapping,
don't compute it.

## What checks this

Unnumbered because this is a standard — see `documentation.md` §1.8.

| Rule | What catches a breach |
|------|----------------------|
| §3.1–3.2 title / Status / Kind shape, where the Ants MCP is present | `/doc-lint` `structure` (via `spec_query`) |
| §3.1–3.2 the same, where it is not | **nothing** — the format still applies, but no verb enforces it |
| §3.7 `INV-N` ids contiguous, no gaps | `/doc-lint` `structure` |
| §3.7 no `INV-N` id reused | **nothing mechanical** — `/doc-lint` `structure` checks for *gaps*, which a duplicate does not create; a cold reader or `spec_query`'s returned invariant list read by eye |
| §3.7 every INV names a test surface | `/doc-lint` `contract` |
| §3.7 a command `*Test:*` states its expected output | `/doc-lint` `contract`, as a *candidate* — "is this clause a command?" is a heuristic, so the check produces the short list and a lane makes the call |
| §3.7 every INV names its breaking input — the clause is present | `/doc-lint` `contract` |
| §3.7 that clause being honest rather than decorative | **nothing mechanical** — a cold reader |
| §5.1 no `path:line` citations | `/doc-lint` `links` |
| §5.1 cited symbols exist | `/doc-lint` `symbols` produces the unresolved list; **defect-vs-forward-reference is a lane's judgement**, not the check's |
| §5.2 one fact, one place | **nothing mechanical** — `/cold-eyes` Phase 4 diagnoses it from the finding pattern |
| §5.4 size gate | `/doc-lint` `size` emits the line count |
| §6 loop log present, every row has an outcome | `/doc-lint` `loop-log` |
| §3.12 every spec carries a What-checks-this table | `/doc-lint` `sections`, which reads this file's §3 list |
| §8 every plan step has a verification | **nothing mechanical** — a cold reader |

Fifteen rows, **five** with a bolded `nothing` — the metric §0 defines. That
is this standard's honest error budget; §5.7 is how it falls. The row count
rose from thirteen without the budget moving: two cells each blurred a named
catcher and a `nothing` together, and splitting them into one row apiece is
what makes the five countable rather than arguable.

This count has been wrong in three consecutive review loops, in this file
and in the spec that adopts it. See §5.8.

## Cold-eyes loop log

Loop numbers track the shared run recorded in `CFG-0001`'s §12, where this
file has been a lane since loop 1. Rows 1–3 are absent because they were not
written as those loops closed, and rule 14 forbids back-filling them.

| Loop | Date | Lanes | CRIT | HIGH | MED | LOW | Outcome |
|------|------|-------|------|------|-----|-----|---------|
| 4 | 2026-07-27 | 4 (breadth, all escalated) — this file + skeleton was lane 2 | 1 | 1 | 4 | 1 | 7 verified, 3 unverified. All 7 fixed. This file took 3: §5.7/§5.8 were out of order, two What-checks-this cells blurred a catcher with a `nothing`, and §9's numbering note implied a fixed offset that breaks at skeleton §10. |
| 5 | 2026-07-27 | 4 (same partition, cold) | 0 | 0 | 0 | 0 | **Clean.** Lane 2 re-read this file and the skeleton cold and found nothing — loop 4's three fixes held, including the §5 reorder and the row recount. |
| 6 | 2026-07-27 | 3 (lane 3 skipped — bytes unchanged since its last clean verdict) | 0 | 0 | 1 | 0 | **Converged (no build-changing findings).** One finding, in the §9 mapping added by loop 4: it stopped at skeleton §12 and never placed §13, whose home is §6 rather than the §3 list. Fixed; run closed. |
