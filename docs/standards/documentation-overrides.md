<!-- ants-documentation-overrides: 1 -->
# Documentation overrides — LocalWebServerManager

**Status:** v1 (2026-10-02).

Documentation for this project follows the machine-global
`~/.claude/standards/documentation.md`, read in place rather than copied.
This file holds only where this project differs, each with one line of why.
That file is on the author's machine and not in this repository, so a
contributor reads this file and `CONTRIBUTING.md`.

## DOC1. A prose count of a growing set fails the suite

Global § 2.3's rule against census counts is a test here:
`tests/test_docs.py::test_no_prose_count_of_a_growing_set` fails on a
number word counting a set that can grow, in any file on its `GOVERNED`
list, including a count split across a line wrap. It skips table rows,
lines carrying a `YYYY-MM-DD` date, and text inside quotes or backticks.
Because the suite reads these files, a push touching one runs the full
gate (`commits-overrides.md` § C2).

Why: review kept spending itself on stale counts in these files, and a red
build costs less than a review loop (global § 9.3).

## DOC2. A contract document is built first and reviewed after

When a spec or other contract document gets its cold read is set by
`CLAUDE.md` § Review cadence, not by global § 9.1's "before the work it
governs starts". Build first, then correct the spec to match what was
built. Spec-first is only for code that creates a durable artifact (an
on-disk format, a wire protocol, anything another item binds to), and
there the gate runs before building. When the gate runs, it runs as global
§ 9.1 and `review-contract` define it.

Why: measured here, few review findings were defects the build would not
have caught; a durable artifact is where a wrong contract costs a
migration rather than an edit.

## DOC3. Author-private facts go only in `docs/private/`

The repository is public, so every tracked file is world-readable. Facts
about the author's own machine — real services, ports, paths, the
inventory of the author's other projects — go only in `docs/private/`,
which `.gitignore` excludes. Public documents refer to them by a neutral
label, and `CHANGELOG.md` names none of the author's other projects.

Why: a fact pushed once stays in the public history, and removing it
means force-pushing `main`, which global `commits.md` § 3.3 refuses.

## What checks this

| Rule | What checks it |
|------|----------------|
| DOC1 prose counts | Partial: `tests/test_docs.py::test_no_prose_count_of_a_growing_set` covers the files on its `GOVERNED` list — it misses every other file, and a count in a table row, on a dated line, or inside quotes or backticks |
| DOC2 build first | nothing — the commit body's `CLAUDE.md rule 14:` line records the decision, and no check reads it |
| DOC3 private facts | Partial: `.gitignore` keeps `docs/private/` out of the index — nothing catches a private fact written into a tracked file, `CHANGELOG.md` included |
