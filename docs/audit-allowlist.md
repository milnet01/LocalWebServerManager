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


## allowlist-003 — contract_doc_drift:docs/standards/ — format standards are not source contracts

- **Status:** active
- **Tool / rule:** `contract_doc_drift` (via `audit_run`) —
  `contract_doc_drift`
- **Location:** every `docs/standards/*.md` file. 187 findings on
  2026-08-06 — `roadmap-format.md` 68, `coding.md` 31,
  `spec-format.md` 21, `testing.md` 21, `commits.md` 19,
  `documentation.md` 19, `README.md` 7, `dependencies.md` 1.
  **Re-verified 2026-08-07 (FP05): 164 findings** — `roadmap-format.md` 63,
  `coding.md` 22, `spec-format.md` 19, `commits.md` 18,
  `documentation.md` 18, `testing.md` 16, `README.md` 7,
  `dependencies.md` 1. The drop is the rule getting quieter, not the
  standards changing; the reasoning below still holds line for line.
- **Why this is a false positive:** the rule reads a backticked token
  in a document as a claim that the project's source contains that
  symbol. That is a fair check against `docs/specs/`, which states
  this project's own contracts. `docs/standards/` states **formats and
  conventions**, so its backticks are none of them source claims.
  Verified line by line: naming counter-examples the document itself
  forbids (`coding.md` § 4 gives `strName` and `iCount` as Hungarian
  notation *not* to use); C++ and Qt idiom names in `coding.md`
  § 5.1/5.2, which a Python project will never contain
  (`std::make_unique`, `QSaveFile`, `qDebug`); roadmap and commit
  vocabulary (`Kind:`, `Lanes:`, `Layman:`, `PROJ-NNNN`,
  `Co-Authored-By:`); ordinary prose that happens to be backticked
  (`yesterday`, `recently`, `size`); citations into **other**
  repositories (`roadmap-format.md` cites Ants Terminal's
  `roadmapdialog.cpp` and `remotecontrol.cpp`); and forward references
  to core modules that `coding.md` § O1 itself lists as not yet built
  (`supervisor`, `logbuffer`, `controller`) plus P04 theme tokens
  (`accent`, `state_running`). The check cannot come back clean against
  these files while they remain format standards. Re-verify if it gains
  a path scope, or if a standard starts citing this project's symbols
  as its own contract.
- **Suppression applied:** none — the verb offers no inline
  suppression and no scope filter. Also recorded in
  `.ants_review_falsepos.jsonl` so a re-run's brief carries it.
- **Logged:** 2026-08-06
- **Confirmed by phase:** FP02

## allowlist-004 — bandit:B101 — pytest's assert is how pytest works

- **Status:** active
- **Tool / rule:** `bandit` — `B101` (`assert_used`)
- **Location:** `tests/test_applog.py`, `tests/test_main.py` — every
  assertion in them (28 findings on 2026-08-06, all LOW severity /
  HIGH confidence)
- **Why this is a false positive:** pytest's entire assertion mechanism
  is the bare `assert` statement, so the rule fires on correct test
  code by construction. No production `assert` exists — bandit over
  `src/` alone reports nothing. The project already encodes this
  judgement for ruff's port of the same rule:
  `pyproject.toml [tool.ruff.lint.per-file-ignores]` sets
  `"tests/**" = ["S101", …]`, scoped to tests so the production rule
  keeps its teeth. bandit's own default severity floor (`-ll`, which
  `audit_run` uses) filters these to zero; they were visible only
  because this session re-ran bandit without the floor to prove the
  tool had analysed the tree rather than crashed. Re-verify if a B101
  ever appears under `src/`.
- **Suppression applied:** none needed at the default severity floor.
- **Logged:** 2026-08-06
- **Confirmed by phase:** FP02


## allowlist-005 — semgrep:insecure-file-permissions — 0o700 on the state directory

- **Status:** active
- **Tool / rule:** `semgrep` —
  `python.lang.security.audit.insecure-file-permissions.insecure-file-permissions`
- **Location:** `src/lwsm/applog.py`, the `os.fchmod(fd, 0o700)` call in
  `_prepare_state_dir`
- **Why this is a false positive:** the rule's message is wrong on its own
  terms here. It calls `0o700` "widely permissive" and recommends `0o644`
  as "a good default" — but `0o644` is world-**readable**, strictly more
  permissive than `0o700`, and this is the directory holding a log of the
  user's whole project inventory and directory layout. `0o700` is
  owner-only, and on a *directory* the execute bit is what makes it
  traversable at all, so `0o644` would also make it unusable. Following
  the advice would regress the finding this project fixed deliberately and
  would break `test_state_dir_and_log_are_not_world_readable`, which
  asserts exactly `0o700`. The rule appears to be written for regular
  files and does not distinguish a directory mode. It began firing on
  2026-08-06 only because the mode is now set through `os.fchmod` on a
  directory fd rather than `Path.chmod`; the mode itself is unchanged.
  Re-verify if the rule learns to distinguish directories.
- **Suppression applied:** inline — a trailing `# nosemgrep` on the
  `os.fchmod` call, with a comment above citing this entry. Deliberately
  the bare form rather than the rule-qualified one: the qualified id is
  106 characters, which exceeds the project's 88-column `ruff` limit and
  failed the gate. `# nosemgrep` on its own line four lines above the
  call also did **not** suppress — semgrep honours it only on the
  offending line or the line immediately preceding it.
- **Logged:** 2026-08-06
- **Confirmed by phase:** FP02


## allowlist-006 — contract_doc_drift:docs/specs/ — builtin names and prose identifiers in a spec

- **Status:** active
- **Tool / rule:** `contract_doc_drift` (via `audit_run`) —
  `contract_doc_drift`
- **Location:** `docs/specs/LWSM-1005-vertical-slice.md`. 5 findings on
  2026-08-06 at lines 144 (`ValueError`), 157 (`TypeError`), 449
  (`state_text`), 618 (`QMessageBox`), 796 (`ImportError`).
  **Re-verified 2026-08-07 (FP05): 6 findings**, the spec having grown
  945 → 1430 lines — lines 209 (`QStatusBar`), 212 (`bold`), 217
  (`TypeError`), 595 (`state_text`), 920 (`QMessageBox`), 1254
  (`ImportError`). `ValueError` no longer fires. **Two tokens are new
  and were verified individually rather than waved through on the
  entry's existing reasoning**, since this entry must not mask a real
  drift: both are from the FP03 measurement prose the spec now records.
  `QStatusBar` is absent from source because the code reaches the widget
  through `self.statusBar()` (`mainwindow.py:372`) and never names the
  class — a source match would require an import the project does not
  need. `bold` is the literal string that measurement rendered
  (`<b>bold</b>` drew 508 ink pixels against 232 for `bold`), i.e. test
  data quoted in prose, not a symbol. Both fall inside this entry's
  existing two token classes.
- **Why this is a false positive:** narrower than allowlist-003 and
  deliberately so — the rule **is** useful against `docs/specs/`, which
  states this project's own contracts, so this entry carves out two
  token classes rather than the directory. Verified line by line.
  Four are **language or framework names appearing in a negative
  clause**: the spec's `*Breaks when:*` lines describe what the code
  must **not** do (`TypeError` escaping `load_projects`, a
  `QMessageBox` reached for inside the controller, an `ImportError`
  proving only that a module is missing), and `ValueError` names the
  class CPython raises, not a symbol this project defines. A source
  match for any of them would be evidence of the defect, not of
  correctness. The fifth, `state_text`, is a **variable name inside an
  illustrative f-string** — `f"{state_text}, {name_text}, {port_text}"`
  — showing how the accessible name is composed; `grep` confirms it
  appears in no `.py` file and is not meant to. Re-verify if the rule
  gains a way to distinguish a normative clause from a negative one,
  or if a spec starts naming a symbol it genuinely requires and the
  symbol is absent — which is the case this check exists to catch and
  which this entry must not mask.
- **Suppression applied:** none — the verb offers no inline
  suppression and no scope filter.
- **Logged:** 2026-08-06
- **Confirmed by phase:** FP03

## allowlist-007 — vulture:theme.py — the adopted token set is kept whole on purpose

- **Status:** active
- **Tool / rule:** `vulture` — unused variable (60% confidence)
- **Location:** `src/lwsm/theme.py:38` (`accent_soft`), `:39`
  (`attention`), `:41` (`is_dark`); plus `pytestmark` in
  `tests/test_controller.py:24` and `tests/test_mainwindow.py:22`.
  **Extended 2026-08-07 (FP05)** with three more names pytest reads by
  convention and no source will ever reference: `_reset_logging` in
  `tests/test_applog.py:41` and `tests/test_main.py:27` (both
  `@pytest.fixture(autouse=True)`, so pytest runs them without any
  call-site), and `_no_event_loop` in `tests/test_main.py:73` (a plain
  fixture, requested via `@pytest.mark.usefixtures("_no_event_loop")` at
  `:86` — a **string**, which is structurally invisible to a static
  reference scan). Verified by grep before adding. `applog.py:53`
  (`_open`) also appears in vulture's output; it is a real
  `FileHandler` override that logging calls through the base class and
  is the single pre-existing pyright mismatch **LWSM-1066** owns —
  tracked there, not suppressed here.
- **Why this is a false positive:** the three `Theme` fields are read
  by nothing in `src/` today, and that is the **documented outcome of
  a reviewed decision** rather than an oversight.
  `docs/design.md § Tokens, not colours` defines a theme as nine
  semantic tokens **plus `is_dark`**, `docs/specs/LWSM-1005-vertical-slice.md`
  § 4.4 mandates their presence, and § 8 records the rejected
  alternative — shipping only the tokens P02 renders — on the grounds
  that the nine are an adopted set and splitting them is arbitrary.
  `is_dark` drives the light/dark grouping in LWSM-1031's picker, and
  `accent_soft` / `attention` are consumed by the same item's palettes.
  Deleting them to satisfy the tool would put the spec and the code in
  conflict and cost a re-add three items later. `pytestmark` is
  separate and simpler: pytest reads that name by convention from the
  module namespace, so no source will ever reference it. Re-verify
  after LWSM-1031 lands — at that point the three fields **should**
  have readers, and a still-firing finding would mean the palette
  layer skipped them.
- **Suppression applied:** none. `vulture` is not in
  `scripts/local-ci.sh`, so nothing is gated on it; a whitelist file
  would be more machinery than the finding is worth.
- **Logged:** 2026-08-06
- **Confirmed by phase:** FP03

## allowlist-008 — deptry:DEP002/DEP003 — the project's own package, and dev tools invoked as commands

- **Status:** active
- **Tool / rule:** `deptry` — `DEP003` (transitive dependency) and
  `DEP002` (declared but unused)
- **Location:** 15 findings on 2026-08-06 — `DEP003` x12 on `import lwsm`
  in `src/lwsm/controller.py`, `mainwindow.py`, `theme.py`, `__main__.py`;
  `DEP002` x3 on `pytest`, `pytest-qt`, `ruff` in `pyproject.toml`.
  **Re-verified 2026-08-07 (FP05): 16 findings** — `DEP003` x13, the extra
  one being the deferred `from lwsm.controller import ...` inside `run()`
  at `__main__.py:125`, added by LWSM-1100. Same intra-package self-import
  class; the count moved, the reasoning did not.
- **Why this is a false positive:** two distinct misreadings, both
  verified. `DEP003` fires on `lwsm` importing **itself** — every one of
  those lines is an intra-package import (`from lwsm.ports import ...`),
  and `lwsm` is this project, not a dependency of it; declaring itself
  would be circular. `DEP002` fires on three dev tools that are correctly
  declared in the `dev` extra and are invoked as **commands**
  (`uv run pytest`, `uv run ruff`) rather than imported, which is the only
  way a test runner and a linter are ever used; `pytest-qt` is loaded by
  pytest as a plugin through an entry point, so no source will import it
  either. Acting on any of the five would break the build. Re-verify if
  deptry gains first-party-package detection, or if a dev tool ever needs
  a real `import`.
- **Suppression applied:** none. `deptry` is not in
  `scripts/local-ci.sh`, so nothing is gated on it; adding a
  `[tool.deptry]` config section would be more machinery than the finding
  is worth.
- **Logged:** 2026-08-06
- **Confirmed by phase:** FP04

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
