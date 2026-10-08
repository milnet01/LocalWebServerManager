# CLAUDE.md history

Pedigree moved out of `CLAUDE.md` on 2026-10-08, verbatim. Nothing here is a
rule; each entry names the section it came from.

## From § Which skill runs which job

**`/cold-eyes` and `/doc-lint` no longer exist** — the documentation
family cut over on 2026-08-12 (global `~/.claude/CLAUDE.md`):
`review-contract` replaced `/cold-eyes`, `check-doc-facts` replaced
`/doc-lint`, and each predecessor was **deleted** in the same commit
that promoted its replacement. This table named the dead ones until
2026-08-12, so a session following it would have invoked a skill that
is not there.

## From § Commit conventions

The 2026-09-28 rule that chore and doc commits use `P04:` lapsed when 0.1.0
shipped on 2026-10-01.

**A phase ID may carry a lowercase continuation suffix — `P03b`**
(user, 2026-08-12). It names a phase that finishes a predecessor's
undelivered scope, and exists because this roadmap assigns
`P04`–`P09` to named themes *in advance*, so a phase closed against
partial scope has no free number to spill into. `P03` closed
2026-08-12 with the scanner shipped and four planned items
undelivered; `P03b` carries those four. Renumbering the themes
instead would have re-labelled 28 bullets and every doc that cites
a phase by number, and re-pointing the pushed `P03-complete` tag
needs the force-push authorisation `commits.md § 4.3` withholds.

That rule is history now: no new phase opens, and no new `<ID>-complete` tag
is cut. The existing tags stay. `P03b`'s three open items (LWSM-1039,
LWSM-1008, LWSM-1121) sit in the roadmap's 0.2.0 section. A release is
tagged by `cut-release`.
