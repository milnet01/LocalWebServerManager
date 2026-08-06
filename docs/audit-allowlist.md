# LocalWebServerManager — Audit allowlist

> **Bar for entry:** high — every entry requires written
> reasoning. Future audits re-verify the suppression is still
> warranted.
> **Scope:** project-specific. Each project develops its own
> list. There is no global allowlist.

This file is the **closed-loop memory** for false positives from
`/audit`, `/code-quality-review` and the deterministic document
checkers `/doc-lint` and `/debt-sweep` run (`doc_integrity`,
`spec_lint`, `doc_citations`, `doc_dedup`). Without it, the same
false positive gets surfaced and dismissed every run, burning
tokens and tempting "skip without thinking" reflexes.

**The doc checkers were added to this file's scope on 2026-08-06
(DS01).** They were left out originally, and the first debt sweep
then confirmed two false positives that had nowhere to go — a
deterministic checker that fires on the same non-defect forever is
the exact problem this file exists to solve, and which tool
produced it makes no difference to that.

The
app-workflow skill (`~/.claude/skills/app-workflow/SKILL.md`, local to the author's machine)
reads this file **before** triaging audit findings, so
already-confirmed false positives are discarded without
re-evaluating.


## How entries are added

When `/audit` or `/code-quality-review` produces a finding F that
triage classifies as a tool false positive (verified, not just
dismissed), Claude **must**:

1. Add an entry to this file with the rule, location,
   reasoning, date, and confirming phase.
2. Apply a tool-level suppression where the toolchain supports
   it — `# noqa: <RULE>` for ruff, `// NOLINT(<rule>)` for
   clang-tidy, `eslint-disable-next-line <rule>` for ESLint,
   `# pylint: disable=<rule>` for pylint, etc. — and cite this
   allowlist entry by number in the suppression comment.
3. Log the false positive inline in the active phase's
   `docs/journal/<ID>.md`.

If a tool-level suppression isn't possible (e.g. semantic
code-quality-review finding with no rule ID), the allowlist entry
alone is enough — triage subagents read it before flagging.


## How entries are revoked

If a previously-allowlisted finding turns out to be a real
issue (e.g. the surrounding code shape changed and the
suppression is now hiding a genuine bug):

1. Update the entry's `Status:` to `revoked YYYY-MM-DD` with
   reasoning.
2. Remove the tool-level suppression in code.
3. Fold the finding into the next fix-pass like any actionable
   issue.

Do not delete revoked entries — the history is the value.


## Format

```markdown
## allowlist-NNN — <rule>:<location> short summary

- **Status:** active | revoked YYYY-MM-DD (<reason>)
- **Tool / rule:** e.g. cppcheck:nullPointer, ruff:B902,
  code-quality-review:R-7
- **Location:** file:line, or finding signature for
  non-line-bound findings
- **Why this is a false positive:** one paragraph. Be specific.
  Future audits may re-verify.
- **Suppression applied:** none | inline (cite suppression
  syntax used)
- **Logged:** YYYY-MM-DD
- **Confirmed by phase:** P##/FP##/etc.
```


## Entries

## allowlist-001 — doc_integrity:broken_link — the plan skeleton's placeholder link

- **Status:** active
- **Tool / rule:** `doc_integrity` (via `/doc-lint`, `/debt-sweep`) — `broken_link`
- **Location:** `docs/standards/plan-skeleton.md:3` —
  `[docs/specs/<ID>-<topic>.md](../specs/<ID>-<topic>.md)`
- **Why this is a false positive:** the file is a skeleton, and
  `<ID>-<topic>` is its placeholder syntax, substituted by
  `/write-spec` when a real plan is created from it. A target
  containing `<` and `>` cannot resolve to a path by construction,
  so the check can never come back clean while the skeleton exists.
  Making it resolve would mean either deleting the skeleton's own
  link or committing a file literally named `<ID>-<topic>.md` —
  both worse than the warning. Re-verify only if the skeleton stops
  using angle brackets for placeholders.
- **Suppression applied:** none — the verb offers no inline
  suppression. Filed upstream as an Ants MCP suggestion (skip link
  targets containing unescaped `<` / `>`), 2026-08-06.
- **Logged:** 2026-08-06
- **Confirmed by phase:** DS01

## allowlist-002 — spec_lint:invariant_no_test — testing.md's INV format examples

- **Status:** active
- **Tool / rule:** `spec_lint` (via `/doc-lint`, `/debt-sweep`) —
  `invariant_no_test`
- **Location:** `docs/standards/testing.md`, INV-1 / INV-2 / INV-3
  (the worked example under the invariant-numbering section)
- **Why this is a false positive:** those three are *specimens*
  showing an author how to write an invariant — `- **INV-1**:
  <observable behaviour, written as an assertion>.` They are not
  this document's own contract, and `testing.md` is a standard
  rather than a spec, so it has no invariants for a test to cover.
  Giving them test-surface clauses would mean inventing tests for
  placeholder text. Only fires because a sweep widened `spec_lint`
  past `docs/specs/`; a default-scoped run does not reach this
  file. Re-verify if `testing.md` ever gains real invariants.
- **Suppression applied:** none available.
- **Logged:** 2026-08-06
- **Confirmed by phase:** DS01


## What does NOT belong here

- **Findings that are real but blocked by a missing feature.**
  Those go in `docs/known-issues.md` with the named dependency.
- **Findings that should be fixed but the user wants to
  defer.** No deferral disposition exists outside of "blocked
  by dependency" — every actionable finding becomes a fix-pass.
- **Findings the user accepts as a permanent trade-off.**
  Those become an ADR in `docs/decisions/`, not a suppression.

The bar is deliberately high. If you're tempted to allowlist
something, ask: "Have I verified, with a specific argument,
that this finding cannot be acted on?" If yes — file. If
"probably not relevant" — file as a fix-pass instead and let
the implementation prove the point.
