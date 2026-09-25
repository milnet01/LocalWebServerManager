# Phase and fold-in section intros (retired 2026-09-25)

`ROADMAP.md` was organised by phase (`## P04`) and fold-in (`## FP09`) until
2026-09-25, when LWSM-1311 regrouped it by version. The items moved and kept
their ids and bodies. This file keeps the section intros, verbatim, because
they record what each review found and why. Nothing here is live.


## FP03 — Audit + three-lane review fold-in (from the P02 close, 2026-08-06)

Static analysis over the whole tree came back **clean on every source file** —
cppcheck, ruff, bandit, semgrep, gitleaks and shellcheck found nothing, and all
173 sweep findings were `contract_doc_drift` against documentation. Every defect
below came from **reading**, which is the third phase running to record that
result. Three lanes ran cold against the spec's 16 invariants: the data boundary
(`registry`, `ports`), the concurrency boundary (`controller`), and the
presentation layer (`mainwindow`, `theme`, `__main__`).

**Every finding below was reproduced against shipping code before it was
written down.** Two lanes independently found the two halves of the CRITICAL,
neither half being sufficient alone — the cross-lane agreement is what made it
visible.

### 🐛 Bug fixes

### 🔒 Security

### ♿ Accessibility

### 🧹 Cleanup / debt

---

## FP04 — Second three-lane review fold-in (from the re-run P02 close, 2026-08-06)

Static analysis was clean again — ruff, bandit, semgrep (9 files scanned, 0
findings), gitleaks (82 commits), shellcheck and actionlint all found nothing,
and pyright reports only the pre-existing `applog.py:53` that LWSM-1066 owns.
Every defect below came from reading, for the third close running.

Three lanes re-read the FP03 code cold: the data boundary, the concurrency
boundary and the presentation layer. **29 findings.** The shape is the point:
FP03 fixed 14 real defects and, in doing so, left three of its own fixes
half-done and wrote four confident comments that are false. A fix-pass is not
self-verifying — this is the evidence for reviewing one.

**Every finding below was reproduced against shipping code before it was written
down**, and the four most serious were re-reproduced independently rather than
taken on the reviewers' word.

The pass also surfaced a **tooling** defect that is not about this project's
code at all: a same-second edit-and-revert whose replacement text is the same
byte length leaves Python running stale bytecode, because the default `.pyc`
validation compares only the source's mtime and size. A green test run then
reports on code that is not on disk. Filed as LWSM-1110.

## FP05 — Third three-lane review fold-in (from the second re-run P02 close, 2026-08-07)

Static analysis was clean for the **fourth** close running — ruff, bandit,
semgrep, gitleaks, trivy, shellcheck, actionlint, zizmor and pip-audit all found
nothing, each verified to have actually run rather than trusted on a zero. The
170 `contract_doc_drift` hits are allowlist-003 and allowlist-006 in full. Every
defect below came from reading.

Three lanes re-read the FP04 code cold — the data boundary, the concurrency
boundary and the presentation layer. **25 findings, 7 of them HIGH.** The four
highest-consequence were re-reproduced independently of the reviewers and all
four held exactly.

**This pass is deliberately not the whole list.** P02 is one feature item that
had already produced 28 fix items across FP03 and FP04; a third full fold-in
would have made it 54, and the ratio — not the convergence checkpoint, which
would not have fired — is what stopped it. The user's call on 2026-08-07 was to
fix the **two root causes and the seven HIGH findings** here, and hand the
MEDIUM and LOW tail to the phases that already own the code it lands in. Those
are in `docs/known-issues.md` with a named owner each, not dropped.

**Two themes were found independently by all three lanes**, and they are the
first two bullets because the leaf findings are their instances:

1. **A fix landed at the call site it was reported against, not at the
   mechanism.** Six instances this pass. This is the same shape FP04 reported
   about FP03, now for the third time running.
2. **Tests assert the artefact, not the delivery.** Four separate shipped fixes
   can be deleted with all 150 tests still green, because what is covered is
   the helper and never the wiring that reaches it.

## FP06 — Three-lane review fold-in (from the P03 close, 2026-08-12)

The P03 close ran `/audit` and `/code-quality-review` once, per the standing
2026-08-07 process decision. Static analysis was clean for the fourth close
running — ruff, bandit (2116 lines), semgrep, gitleaks, shellcheck, all zero,
re-run by hand inside the venv because the sweep's zero carried no evidence it
had read anything. Every real finding came from reading, again.

Three lanes over `scanner.py`, its tests and the hardening surface produced 25
findings and **no false positives**. Every load-bearing claim was reproduced
independently before it was written down here.

This section is the nine above the bar. The remaining sixteen are routed to
`docs/known-issues.md` with named owners rather than worked here, per the same
2026-08-07 decision: one review per phase, fix what is above the bar, route the
rest to the phase that owns the code.

**The cross-cutting finding is the one to remember.** Two lanes, different
reproducers, landed on the same defect: `pathlib` metadata calls sitting outside
any `except OSError`. `Path.exists` / `is_symlink` / `is_file` re-raise `EACCES`
and `ENAMETOOLONG` on Python 3.13 — this is not the older behaviour where
`exists()` swallowed them — and `scan()` catches only `_BudgetExpired`. That is
the fourth distinct non-`OSError`-shaped whole-scan crash this item has
produced, after the `TypeError`, `KeyError` and `ValueError` the spec gate
found. The class is now understood as structural rather than incidental: the fix
is per-candidate containment, not a fourth patch.

**The test findings are the other half, and they are the more uncomfortable
one.** 81 mutants were applied to `scanner.py`; 47 went red, 34 did not. Three
separate clauses the spec calls load-bearing — the execute-bit precondition, the
dependency-block scope, `_BudgetExpired` not being an `OSError` — are all
correct in the code today and protected by nothing. A suite of 370 green tests
said nothing about any of them.

## FP07 — Three-lane review fold-in (from the P03b close, 2026-08-15)

The P03b close ran `check-code` and `/code-quality-review` once, per the
standing 2026-08-07 process decision. Static analysis was clean for the fifth
close running — ruff, bandit, semgrep, gitleaks, shellcheck, actionlint and
zizmor all zero. Every real finding came from reading, for the fifth time.

Three lanes over `supervisor.py`, `registry.py` and the UI pair produced **55
findings — 3 CRITICAL, 7 HIGH, 19 MEDIUM and the rest LOW/INFO**. This section
is the ten above the bar. The MEDIUM and LOW tail is routed to
`docs/known-issues.md` with named owners, per the same 2026-08-07 decision.

**Two findings mean the app does not do what this roadmap and
`.claude/workflow.md` recorded it doing on 2026-08-14.** Success criterion 2 was
written up as closed end to end. It is closed for **shell-launcher projects
only**: `npm run dev`, `python3 serve.py` and `node serve.mjs` are all refused
before they spawn, and any project whose port the scanner could not pin sticks
in `starting` forever with every button disabled. Both were reproduced against
the shipped module before this section was written.

**The cross-cutting finding is one all three lanes hit independently: a
documented mechanism with no caller.** `rotate_if_needed` (the 5 MB per-project
log cap), `DETECTED_FIELDS` / `USER_FIELDS` (the merge's classification spine),
and `wait_for_abandoned_probes` are each declared, documented as delivered, and
consulted by nothing in `src/`. No lane saw the other lanes' reports. This is
the same class as FP06's non-`OSError` family — an instance found three times
before the class was named — and it is named here rather than patched three
times.

**The second cross-cutting theme is LWSM-1069's shape, three more times.** An
exception escaping a Qt slot leaves a control permanently disabled with no
message: the raw `OSError` from `mkstemp`, the `AttributeError` from an unset
`load`, and the unbounded overlay all end there. LWSM-1069 fixed this on the
poll loop and nowhere else.

**Why 494 green tests said nothing about any of it.** Every `start()` test in
`test_supervisor.py` uses `("./start.sh",)` — a launcher-kind monoculture, so
the one branch that works is the only one exercised. No fixture has a port-less
project. No fixture fills a disk. Same family as the one-row-fixture trap
recorded on 2026-08-14: a fixture set that cannot express the variation the code
branches on.

## FP08 — Four-lane review fold-in (from the P04 close, 2026-08-21)

Four cold lanes over the code shipped since the P03b close: placement and window
geometry, settings and config I/O, the window's UI surface, and the supervisor's
concurrency. Every finding below was verified against the code before filing —
three by reproduction — and the ones that did not survive checking were dropped
rather than filed.

The static-analysis half came back clean: ruff, gitleaks (244 commits), semgrep
on `src/`, and bandit at 0 medium and 0 high. Its only findings were the
B404/B603 subprocess pair, now recorded as allowlist-009.

Two things about this batch are worth keeping. **Six of the findings are in code
written the same day**, which is the argument for a cold read that no amount of
care by the author replaces. And **the two most severe are both in places a
docstring said were safe** — `settings.py` claimed three times that a refusal
here cannot lose data, and `supervisor.py`'s trust gate claimed a symlink out of
the project is refused outright. Neither was true, and in both cases the sibling
module states the correct rule in almost the same words.

## FP09 — Fourteen-lane review fold-in (check-code + review-code, 2026-09-01)

A whole-tree check-code run followed by a fourteen-lane review-code sweep over
every src/ module, all five scripts, the pre-push hook and ci.yml. check-code
returned ONE surviving finding across eleven tools; everything else it raised
was calibrated or verified false and is recorded in .ants_review_falsepos.jsonl.
The lanes returned 0 CRITICAL, 15 HIGH and 53 MEDIUM, plus roughly 100 LOW/INFO
grouped per lane at the end of this section. Severities below are the
orchestrator's calibrated ranks, not the lanes' raw ones; the four that moved
say so in their body. mainwindow.py:169 is the only finding two independent
lanes cited at the same file and line, and it is the one to fix first. No fix
has been applied yet — every item in this section is open.

## Findings filed in passing

Findings noticed while doing something else and not fixed on the spot — a
surviving mutant, an untested mechanism, a defect in a neighbouring subsystem.
Standing instruction from the user, 2026-08-31: anything found and not fixed
immediately is filed here rather than reported once and lost.

This is NOT a fix-pass. A fold-in section (`FP##`) collects what a phase close
produced and is worked as a batch through the 9-step loop; these arrive one at a
time, gate nothing, and are picked up whenever a phase has room. An item here is
not evidence a phase is unclosed.

Each bullet says who found it and while doing what, because a finding's value is
mostly in the measurement behind it.

### 🐛 Bug fixes

### 🔒 Security

## FP01 — Security fold-in (from the P01 review, 2026-08-03)

**Theme:** findings from the P01 `/audit` + code review + security
pass. The static scanners were all clean (ruff, bandit, semgrep,
gitleaks over 24 commits (the count at 2026-08-03 15:37 — see LWSM-1057),
trivy); everything below came from
review, and most of it is **design that is still cheap to
change** rather than code that exists.

### 🔒 Security

---

## P01 — Bootstrap (target: next)

**Theme:** wire up the build, lint, format, test and CI plumbing
chosen in Phase A. Zero user-facing features. Forces the audit
harness to be known-working before any business code lands.

### 🧰 Dev experience

---

## P02 — Vertical slice (target: after P01 closes)

**Theme:** the smallest feature that touches every layer —
config file → core logic → OS probe → widget → test. Forces the
integration pain to surface before more code lands on it.

### 🎨 Features

---

## P03 — Project discovery (criterion 1)

**Theme:** find the projects on disk so the user never types a
path. `docs/design.md § Detection rules` is the contract.

### 🎨 Features

---

## P04 — Appearance and accessibility foundation

**Theme:** the visual and accessible foundation, laid **before**
the real UI is built on it. Moved ahead of the feature phases by
the user on 2026-08-03: the primary user reads with a screen
magnifier, so this is a design input, and
`docs/standards/coding.md § O8` forbids retrofitting it.

### 🖥 Platform

---

## P05 — Start, stop, restart (criterion 2)

**Theme:** the buttons. [ADR-0003](docs/decisions/0003-launch-via-project-scripts.md)
is the contract.

### 🎨 Features

---

## P06 — The full state model (criterion 3)

**Theme:** tell the truth in every case, including the awkward
ones. [ADR-0004](docs/decisions/0004-runtime-truth-from-probing.md)
is the contract.

### 🎨 Features

---

## P07 — Ports (criterion 4)

**Theme:** never launch into an occupied port, and make
reassignment stick. [ADR-0002](docs/decisions/0002-port-contract.md)
is the contract.

### 🎨 Features

---

## P08 — Logs (criterion 5)

### 🎨 Features

---

## P09 — Shell: tray, settings, session

### 🎨 Features

---

## P10 — Release for other people (📦 Packaging)

**Theme:** the project is public and meant to be useful to
strangers, so a release has to be something a person downloads
and runs. Nothing here is needed for the author's own use, which
is why it sits after the app works.

### 📦 Packaging

---

## DS01 — Debt sweep (2026-08-06)

The first debt sweep, run over the whole history because there had
never been one and the only tag is not an ancestor of HEAD. Every
dependency, action pin and runner image came back current, so
nothing below is technology debt. These are the items the sweep
could not close itself: each needs a decision, or work, or the
program actually running.

### 🧹 Cleanup / debt

---

## FP02 — Audit + review fold-in (2026-08-06)

A static-analysis pass and a two-lane cold code review over the whole 540-line
tree. Every finding was reproduced against the shipping code before it was acted
on, and every one of the tool findings turned out to be a false positive: all
187 `contract_doc_drift` hits, plus bandit, vulture, deptry, typos and yamllint.
The reading review found the real defects, which is the same result P01
recorded. Both reviewers independently confirmed the delegation property, the
pins and the workflow's security posture. Items below are what remained after
triage; the fixed ones landed in commits 3520359, 86313a7 and b7604b5.

