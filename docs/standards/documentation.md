<!-- ants-doc-standards: 1 -->
# Documentation Standards — v1

Documentation contract for this project. Pairs with
[coding](coding.md), [testing](testing.md), [commits](commits.md);
see the [index](README.md). Governs `Kind: doc` / `doc-fix`
bullets. ROADMAP.md and CHANGELOG.md format details live in a
separate sub-spec at [`roadmap-format.md`](roadmap-format.md).


## 1. Principles

### 1.1 Six-month test

A reader six months from now should be able to use the doc
without the author present. If the doc says "see the recent
change", that won't be true in six months — replace with a
durable reference (`src/foo.cpp` + section name).

### 1.2 Show, don't claim

Examples beat prose. A README that *shows* the command + expected
output beats one that *describes* what the command does. Code
blocks should be runnable as-is.

### 1.3 Date format — ISO 8601

`YYYY-MM-DD`. No `Apr 28 2026`, no `28/04/2026`, no relative dates
(`yesterday`, `last week`) in committed docs. Relative dates rot.

### 1.4 Don't reference what isn't shipped

Doc lands when the feature lands. Forward-references to unshipped
features go in `ROADMAP.md`, not `README.md` or contract docs.

### 1.5 One source of truth per fact

Don't repeat the install steps in README + INSTALL + CONTRIBUTING
+ SETUP. Pick the canonical home; cross-link from the others.

State each limit, count, name and date **once**. Everywhere else
points at it. This is not tidiness — it is the largest single
driver of review cost. A fact written in four places gets
corrected in one, and the surviving three become the next review
pass's findings, so a document that repeats itself actively
delays its own convergence.

**A count of a set that can grow is not written in prose at all** —
not even once. Each of these was true when written and expired the
next time something was added:

- `Five short, focused standards`
- `the other four standards in this folder`
- `Eight modules at P02`
- `The five standards plus ROADMAP.md`

The list, table or directory *is* the count; prose beside it is a
second source of truth with a shorter shelf life than the first.
Write `the standards in this folder` and link the index.

This project has now fixed that exact drift **twice** — "four
standards (five), eight phases (ten)" on 2026-08-06, and seven more
sites on 2026-08-07, one of which was a *repair* of the first that
substituted a fresh wrong number for a stale one. That is why the
rule is "drop it", not "keep it current": keeping it current is the
step everybody skips, and refreshing it is indistinguishable from
fixing it.

**A dated measurement is the opposite and stays.** "524,271 reasons
at the file-size cap (2026-08-07)", "150 tests at the time", "4.29:1
on `alt_base`" — these are evidence about a past run, not claims
about the present, so they do not rot. The test is whether the
sentence would become *false* as the project grows, or merely
*older*. Anchor the second kind to its date; delete the first kind.

A field or concept has exactly one name, too. One thing with two
names is the beginning of two things.

### 1.6 Show it as a schema, not a paragraph

Request/response shapes, structs, config keys, limits and state
machines go in tables and fenced blocks — never in prose
narrating them. Prose restates; a table states.

Length is a defect, not just a reading cost. Two yardsticks: a
document several times longer than a sibling covering comparable
surface, or several times longer than the code it describes, is
over-built until it names the extra surface it covers.

### 1.7 Cite by symbol, never by line number

`src/vault.py::derive_key()`, not `src/vault.py:39-49`. A line
number verified today is stale two commits later, and the prose
form ("around line 786") is caught by nothing.

Every path, symbol, constant and version-specific behaviour is
backed by a read against current source — not recall. Writing
from memory is the most expensive class of documentation mistake,
because the result reads exactly as confidently as the truth.

### 1.8 A rule with no check is a wish

Whether a rule holds is settled by whether something cheap
catches it failing — not by how firmly it is written.

**Every standard and reference carries a `## What checks this`
section** as its last content section: one table, each rule the
document sets against what catches a breach of it.

In a **standard or reference**, leave it **unnumbered**, so adding
it to an existing document renumbers nothing and every
cross-reference into that document still resolves. Same for the
trailing `## Cold-eyes loop log`.

In a **spec**, number it like every other section — specs are
numbered throughout and an unnumbered section mid-sequence reads
as an editing accident. `spec-format.md` §3.12 is the spec-side
form of this rule.

**Not yet met by:** `coding.md`, `commits.md`, `testing.md`,
`roadmap-format.md` and this folder's `README.md`, which predate
this section. Recorded here rather than left silent — per this
very rule, an unmet requirement nobody has written down reads as
covered. Add the section to each when next editing it.

*Example only — these are not this document's rows; the real table is at
the end of the file:*

| Rule | What catches a breach |
|------|----------------------|
| §1.7 no `path:line` citations | `/doc-lint` `links` |
| §6 screenshots current | **nothing** — a cold reader; tracked by `<PREFIX>-NNNN` |

The right-hand cell says exactly one of two things and never
blurs them: a **named catcher** (the file, plus the assertion if
the file is large), or **`nothing`** in bold plus why — with a
roadmap id when the gap is a defect rather than a limit of what a
check can decide.

Keep each row about the rule its left cell names. **A row that is
wrong is worse than a row that is missing**, because the table's
whole value is being trustable without re-deriving it.

An unchecked rule recorded as unchecked gets fixed. An unchecked
rule left silent reads as covered. The count of `nothing` rows is
the document's honest error budget — watch it fall.


## 2. Project-level files

### 2.1 README.md

Required sections, in order:

1. **Masthead** — project name, one-line description, badges
   (build, license, version).
2. **Current version** — single line: `Current version: X.Y.Z`
   with links to CHANGELOG, ROADMAP, and any companion docs.
3. **Features** — bulleted list of headline capabilities.
4. **Install** — one-line install for each supported platform.
5. **Quickstart** — minimal command sequence to use the project.
6. **Plugin / extension** (if applicable) — link to the plugin
   author contract.
7. **Documentation** — links to `docs/`, including the four
   standards docs.
8. **License** — single line + link.

Avoid: a TOC for a short README; "About" / "Why" sections without
content; broken screenshot links.

### 2.2 CLAUDE.md

For projects worked on with Claude Code: the project-specific
instructions Claude should follow. Lives at the repo root.
Typical contents:

- Module map (one line per major subsystem).
- Build instructions.
- Testing instructions.
- Conventions specific to this codebase.
- Key design decisions that aren't obvious from reading the code.

Keep it terse — the global `~/.claude/CLAUDE.md` covers
machine-wide rules; this file only covers project-specific ones.

### 2.3 LICENSE / COPYING / NOTICE

Standard files at the repo root. Use the SPDX-tagged canonical
license text — don't paraphrase.

### 2.4 SECURITY.md

For projects that accept external bug reports: disclosure policy,
contact email, GPG key (if used), supported-version table.

### 2.5 CODE_OF_CONDUCT.md

Contributor Covenant 2.1 verbatim is the default. Don't write
your own unless the project has a specific reason.

### 2.6 CONTRIBUTING.md (optional)

For projects accepting external contributors: build steps, test
expectations, how to file issues, how to propose features. Should
link to the standards docs in this folder.


## 3. ROADMAP.md and CHANGELOG.md formats

The detailed format specs for both files — used by the Ants
Terminal Roadmap dialog and any tooling that consumes them
deterministically — live in
[`roadmap-format.md`](roadmap-format.md) (split out for
token efficiency; only relevant when authoring those files).

The high-level rules:

- `ROADMAP.md` is the single place to track unshipped work;
  shipped work moves to `CHANGELOG.md`.
- `ROADMAP.md` uses status emojis (✅🚧📋💭), theme emojis,
  and stable per-bullet IDs (`<project>-NNNN` from
  `.roadmap-counter`) plus phase IDs (`P##`, `FP##`, `DS##`,
  `DOC##`, `R##`).
- `CHANGELOG.md` follows
  [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) with
  an `[Unreleased]` block at the top.

For details — including the format-version comment, theme
emoji set, current-work signalling rules, bullet contract, and
release flow — read [`roadmap-format.md`](roadmap-format.md).

## 4. API / contract docs

For any project that exposes an API, a plugin contract, or a
machine-readable surface (`PLUGINS.md`, `API.md`,
`openapi.yaml`):

- **Document every public symbol.** If a function is exported,
  it's part of the contract.
- **Include the version it was added in.** Helps consumers know
  what they can rely on. Example: `Added in 0.6.5`.
- **Show input + output examples.** Type signatures alone aren't
  enough.
- **Mark deprecation explicitly.** `Deprecated since X.Y.Z; use
  Foo instead.`
- **Provide a migration path** for any deprecated / removed
  surface.


## 5. In-code documentation

Defer to [coding § 3](coding.md). Default is no comments; only
WHY non-obvious things need them. Don't write multi-paragraph
docstrings.


## 6. Screenshots

- **Path** — `docs/screenshots/` or `assets/screenshots/`.
- **Filename** — `<feature>-<state>.png`
  (`terminal-tabs-active.png`, not `Screenshot 2026-04-28.png`).
- **Format** — PNG for UI, JPG for photographic content.
- **Caption** every screenshot in the surrounding prose.
- **Replace, don't accumulate.** When the feature changes, swap
  the screenshot. Don't pile up `_old` / `_v2` versions.


## 7. Markdown style

- ATX headings (`# `, `## `, `### `) — never setext (`====`).
- One blank line before/after headings.
- Tables for structured data, fenced code blocks for code.
- Line wrap at ~70–80 columns for readability in `git diff`.
  Don't force-wrap inside code blocks or tables.
- Links: `[text](url)` not `<url>`, unless the URL itself is
  meant as the visible text.
- Lists: `- ` for bullets, `1. ` for numbered. Don't mix `*` and
  `-` in one file.
- Inline code: backticks for filenames, function names, CLI
  flags.


## 8. Review discipline

Three distinct activities, in order of when they apply: the
pre-implementation gate every spec and standard passes (§8.1), the
escalation rule that keeps that gate cheap (§8.2), and the
periodic sweep for drift in docs that already shipped (below).

### 8.0 Periodic doc reviews

Schedule periodic doc reviews independent from code reviews —
the two drift independently. A doc review surfaces:

- Stale CLI flag references.
- Screenshots showing the previous version's UI.
- "Recent change" / "yesterday" relative dates.
- Sections that document a feature that was removed.
- Cross-references to renamed files / functions.
- ROADMAP / CHANGELOG bullets whose claims don't match the
  shipped code.

Findings from a doc review fold into the ROADMAP under
`### 📚 Documentation review fold-in (YYYY-MM-DD)` per [`roadmap-format.md` § 3.8](roadmap-format.md).

### 8.1 The review gate

Every spec, design doc, ADR, standard and reference runs through
`/cold-eyes` before the work it governs starts, looped until it
converges. The skill owns the procedure — the loop, the severity
tally, the convergence test, the post-fix blast-radius check.
This standard does not restate them (§1.5); read the skill.

Two requirements this standard adds:

- **The loop log is written as the loops happen**, in a
  `## Cold-eyes loop log` section, as the document's last
  section. Back-filling destroys the audit trail, which is the
  only evidence the review was real. A document subject to this
  gate with no loop-log section has not been through the gate.
- **The tally must balance.** A row recording eight findings
  against six outcomes is a row where two findings were dropped
  without a decision.

### 8.2 Escalate a repeated class into a check

**When a reviewer or a human catches the same *class* of defect
twice, it stops being a review finding and becomes a mechanical
check** — added to `/doc-lint` or a CI gate, not to a
checklist someone must remember.

Spend a cold reader only on what a script cannot do. The
catchers, cheapest first:

| Catcher | Cost | Use for |
|---------|------|---------|
| a deterministic gate (`/doc-lint`, CI) | seconds, every run | anything countable or greppable |
| a checklist with a fixed trigger | a minute, when triggered | judgement a script cannot make |
| a cold reader (`/cold-eyes`) | a review pass | reasoning, contradictions, a wrong approach |
| the user | a bug report | what the first three missed |

A finding paid for at cold-reader prices that a grep could have
caught is a process defect, not a review success.


## 9. Anti-patterns

- ❌ Lorem ipsum or placeholder text in committed docs.
- ❌ Screenshots that show the previous version's UI.
- ❌ "We" / "I" — use second person ("the user", "you").
- ❌ Markdown that doesn't render correctly on GitHub (test it).
- ❌ Documentation for a feature that hasn't shipped (goes in
  ROADMAP.md instead).
- ❌ Stale CLI flag references — sweep every doc when a flag
  changes.
- ❌ Relative dates in committed docs (`recently`, `last week`).
- ❌ A README so long a new contributor bounces off the page.
- ❌ A rule stated in a document with nothing checking it and no
  row admitting so (§1.8).
- ❌ A `path:line` citation (§1.7).


## 10. Specs and plans

Two directories, each with one job:

| Path | Holds |
|------|-------|
| `docs/specs/<ID>-<topic>.md` | the **contract** — what must be true when the item ships, and how each claim is proven |
| `docs/plans/<ID>-<topic>.md` | the **build steps**, in order, each with its verification |

Design decisions live in the spec, never the plan. Build steps
live in the plan, never the spec. A plan that argues for its
approach has become a second spec, and the two will disagree.

Full format — required sections, invariant rules, the authoring
checklist — is the sub-spec at
[`spec-format.md`](spec-format.md). Write both with
`/write-spec`, which drives the review gate (§8.1) for you.


## What checks this

Unnumbered, so adding it renumbered nothing (§1.8).

| Rule | What catches a breach |
|------|----------------------|
| §1.3 ISO 8601 dates | **nothing** — `/doc-lint` has no date check; a cold reader, or add one to its catalogue (both forms are greppable) |
| §1.3 no relative dates in committed docs | **nothing** — same gap as above |
| §1.4 don't reference what isn't shipped | **nothing** — forward-reference-vs-defect is a judgement |
| §1.7 no `path:line` citations | `/doc-lint` `links` |
| §1.7 cited symbols exist | `/doc-lint` `symbols` — but defect-vs-forward-reference is a lane's judgement, not the check's |
| §1.5 one source of truth per fact | **nothing mechanical** — `/cold-eyes` Phase 4 diagnoses it from the finding pattern (findings of the form "§A and §B disagree") |
| §1.6 length yardsticks | `/doc-lint` `size` reports line counts; the judgement is a cold reader's |
| §1.8 every standard carries this section | `/doc-lint` `sections` |
| §3 ROADMAP / CHANGELOG format | `roadmap_query` / `changelog_query` parse failures |
| §6 screenshots show the current UI | **nothing** — a cold reader, or the user noticing |
| §8.1 loop log present, tally balances | `/doc-lint` `loop-log` |
| §8.2 repeated class becomes a check | **nothing** — a habit, and the only evidence it is working is the `nothing` rows in these tables falling over time |
| §10 spec/plan split respected | **nothing mechanical** — a cold reader; a plan containing rationale is a judgement call |


## Cold-eyes loop log

| Loop | Date | Lanes | CRIT | HIGH | MED | LOW | Outcome |
|------|------|-------|------|------|-----|-----|---------|
| — | — | — | — | — | — | — | Sections 1.5–1.8, 8.1–8.2, 10 added 2026-07-27; not yet reviewed. |
