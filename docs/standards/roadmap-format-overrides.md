<!-- ants-roadmap-format-overrides: 1 -->
# Roadmap format overrides — LocalWebServerManager

**Status:** v1 (2026-10-02).

The roadmap standard for this project is the machine-global
`~/.claude/standards/roadmap-format.md`, read in place rather than copied;
`CHANGELOG.md` follows the global `changelog-format.md` unchanged. This file
holds only where this project differs, each with one line of why. **That file is
on the author's machine**, so a contributor reads this file and `CONTRIBUTING.md`.

`ROADMAP.md` is rendered from the Ants roadmap store and is edited only through
`roadmap_log`; a hand edit is lost at the next render.

## R1. Every open item carries a priority

Every open item (📋, 🚧) carries `Priority: 1`–`5`, where 1 is critical,
2 high, 3 medium, 4 low and 5 someday. The global standard makes the field
optional. This project requires it.

Why: the order of work in R3 reads it. An item without one cannot be placed
in that order.

## R2. `Dependencies:` lists direct predecessors only

An item's `Dependencies:` line names only the items it directly depends on.
Earlier prerequisites are implied by following that chain, and are not
repeated.

Why: a repeated prerequisite becomes a second copy that goes stale when the
chain changes.

## R3. Order of work

Open findings come first, from every block including those not yet scheduled
into a release: items of Kind `fix`, `review-fix`, `audit-fix`, `doc-fix` or
`security`. Within them, critical items come first and then the rest from
oldest to newest. After them comes the rest of the active release. This
replaces the global § 3.5.4 step 1, which orders the findings by position
alone.

Why: the user's decision. A known defect is closed before new work, and the
oldest finding is the one whose cited code has drifted furthest.

## R4. Block layout

The roadmap has a `##` block for each release, in version order, and no `###`
theme groups. Alongside them sit `##` blocks that are not releases:
success-criteria coverage, work after 1.0.0 with no version yet, considered
and unscheduled items, retired ids, and how-to sections on adding an item and
folding in findings. A finding is filed directly into the block of the release
it gates, not into a fold-in subsection.

Why: each release is short enough to read whole, so theme groups would add a
level without helping anyone find an item.

## What checks this

| Rule | What checks it |
|------|----------------|
| R1 open items carry `Priority:` | **nothing** — `roadmap_log` takes no priority argument and the store accepts an item without one |
| R2 `Dependencies:` is direct-only | **nothing** — whether a listed item is a direct predecessor is a judgement |
| R3 order of work | **nothing** — no tool selects the next item; the agent working the roadmap applies the rule |
| R4 block layout | **nothing** — the render emits whatever sections the store holds, and `roadmap_log op:"create_section"` accepts a `###` |
