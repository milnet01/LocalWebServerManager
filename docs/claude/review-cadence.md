# Review cadence — history and evidence

Moved word for word out of `CLAUDE.md` on 2026-10-01, to keep the
always-loaded instructions under Claude Code's size limit.
`CLAUDE.md` § Review cadence — build first points here and still holds the rules.

- **"Cap the gate at 2 loops" is gone.** The cap is `review-contract`'s: 2 for
  a spec or a plan, 3 for a standard or an ADR (its § At the cap). Global rule
  14 forbids a project changing the cap. `docs/design.md` is gated as an ADR,
  so it gets 3. The cap is a backstop, not a quota: a run ends when
  `review-contract` says it has converged. The best finding of the 2026-08-13 exercise
  arrived in loop 2, which is why 1 was never the answer.
- **The "would the first test run have caught this?" filter is gone.** Every
  verified finding is fixed, as global rule 14 says. The filter to use is the
  one `review-contract` already applies: *would a conformer build something
  different?* The old filter let a known-wrong contract ship because a test
  would catch the fallout after the work was done.

Both corrections came from the `~/.claude` session (2026-09-25). It ruled that
capping an ADR at 2 is a redefinition. It flagged the finding filter as a grey
area and did not settle it; the user chose the built-in test.

**The rationale for rule 1, because it is the part that generalises:** global
rule 14 assumes the spec is handed to a *different* implementer, so "a wrong
contract makes the implementation wrong by construction". When the author and
the implementer are the same agent, that premise is much weaker — the
contract's errors surface while coding. What survives is the narrow class where
correct code faithfully implements a wrong contract **and the tests pass**.

**One piece of evidence arrived after the decision and cuts against rule 1, so
it is recorded here rather than left in a journal.** The P03b close
(2026-08-15) found 55 defects in five items built under the build-first default,
including three CRITICALs — one of which, `_launcher_path` refusing three of the
four launcher kinds, meant the app did not do what the roadmap said it did for a
full day. **That is not yet an argument for reverting.** Ask of each such
defect: *would a test have caught it?* For the launcher bug the honest answer
is **yes, if a test had used any argv but `./start.sh`** — so it is a
fixture-coverage failure, not a missing-contract failure, and a spec would not
have caught it either. The same is true of the unbounded overlay: no fixture
had a port-less project.
**What to watch on the next pre-release review is the class, not the count.** If a defect
turns up that a *contract* would have caught and a test could not have, that is
the signal rule 1 is wrong. So far none has.
