<!-- ants-spec-format-overrides: 1 -->
# Spec format overrides — LocalWebServerManager

**Status:** v1 (2026-10-02).

The spec standard for this project is the machine-global
`~/.claude/standards/spec-format.md`, read in place rather than copied. This
file holds only where this project differs, each with one line of why.

**That file is on the author's machine and not in this repository.** A
contributor reads this file and `CONTRIBUTING.md`.

## S1. When a spec is written and gated

`CLAUDE.md` § Review cadence decides when a spec is written and when it is
gated, in place of the global § 6's "before implementation". By default, build
first and then correct the spec to match what was built. A spec is written
first, and gated before anything is built, only where the code creates a
durable artifact: an on-disk format, a wire protocol, or anything another item
binds to.

Why: measured on this project, the pre-build review mostly found what the
build would have caught anyway, at a much higher cost. A durable artifact is
the exception because changing it after the build means a migration.

## What checks this

| Rule | What checks it |
|------|----------------|
| S1 spec timing follows `CLAUDE.md` § Review cadence | **nothing** — whether a spec came before or after the build, and whether the work creates a durable artifact, are judgements |
