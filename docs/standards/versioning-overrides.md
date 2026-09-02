<!-- ants-versioning-overrides: 1 -->
# Versioning overrides — LocalWebServerManager

**Status:** v1 (2026-09-02).

Versioning for this project is the machine-global
`~/.claude/standards/versioning.md`, which mandates
[Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html). It is read
in place rather than copied: a rule stated in two places is two rules that
will disagree.

**That file is on the author's machine and not in this repository.** It binds
the maintainer, who cuts the releases. A contributor needs only what is
restated here.

This file holds the two answers the global standard refuses to supply for
every project: **what a break means here**, and **what would make this
`1.0`**.

## 1. Breaking surfaces

Nothing imports this — it is a desktop application — so *"the public API"*
has no referent, and this list stands in its place.

- **`projects.json`**, the registry, and the profile written in the same
  format. Hand-editable, so its keys and their meanings are a promise.
  Adding a key is safe: unrecognised ones are carried through untouched
  (LWSM-1218).
- **`settings.json`**. Removing a key or repurposing one is breaking; adding
  one is not. The carry-through is what differs: this reader takes the keys it
  knows and the writer emits a fixed set, so a key added here is dropped by an
  older build. That is a stated limitation and not a break — the test below
  asks what happens to someone who upgrades (LWSM-1289 closes it).
- **`scan-roots`** — one directory per line, `#` comments, `~` expanded,
  order preserved because it is the walk order. An empty file means *use the
  default*, and that meaning is part of the format (LWSM-1213).
- **The `PORT` contract (ADR-0002).** The one surface not ours alone: other
  repositories were changed to read `PORT` from their environment. Changing
  the variable, its accepted range, or what an absent value means breaks
  software this project does not own.
- **The `lwsm` command** — that it exists, that `--version` and `--help`
  work, and that an unrecognised option exits 2.
- **The desktop entry id** `io.github.milnet01.LocalWebServerManager`, which
  a pinned launcher is attached to.
- **The keyboard interface.** `docs/design-accessibility.md` makes the app
  keyboard-first, and its shortcuts are in the fingers of the user it is
  keyboard-first *for*.

**A change is breaking if someone who upgrades has something that used to
work stop working.** That is the test, and it decides the cases this list does
not name.

**A surface nobody wrote down is still a surface.** The list makes the common
cases cheap; it does not bound the promise.

## 2. What would make this `1.0`

The global standard requires a `0.x` project to state its exit condition
where someone else can check it.

**`1.0.0` is the five success criteria in
[`docs/discovery.md`](../discovery.md) delivered end to end, plus `FP01`, the
security fold-in, plus `P10`'s packaged download.** Agreed with the user on
2026-08-24; `ROADMAP.md`'s LWSM-1188 holds the reasoning.

The membership rule is fixed — those five criteria, `FP01`, `P10` — so an
item filed into one of them tomorrow is in scope without renegotiation. The
criteria are carried by the phases the roadmap labels `criterion 1` …
`criterion 5`.

**Out of `1.0`:** `P09`'s shell work, `DS01`'s debt, and every fold-in
except `FP01` — `FP09` included. All of it has value; none of it is needed
to use the app for what it is for.

## 3. Which number moves

Inside `0.x` the global standard shifts the levels down one: a breaking
change bumps the MINOR and resets the PATCH, and everything else — a new
capability included — bumps the PATCH.

**The release meeting § 2's condition is cut as `1.0.0`**, whatever level
its own changes would otherwise be. That is the only planned version number;
every other is decided by the change rather than chosen ahead of it.

**Open: the number of the first release.** LWSM-1152 decided `0.1.0` with the
user on 2026-08-18, before this standard was adopted. The rule above gives
`0.0.1`, since a first release of existing capability is not a breaking
change. The global standard says a file like this one carries the answers it
refuses to supply, not a delta arguing with a rule — so `0.1.0` cannot simply
be asserted here. **Nothing is released until this is settled**, and it is the
user's call: keep `0.1.0` and record why the rule is overridden, or cut
`0.0.1`.

## 4. Review loop log

| Loop | Date | Lanes | Q1 | Q2 | Q3 | Q4 | Outcome |
|------|------|-------|----|----|----|----|---------|
| 1 | 2026-09-02 | 3, cold — genre pinned `standard` | 1 | 5 | 2 | n/a | **Nine verified, nine fixed.** All three lanes independently found that *"the security fold-in"* and *"the older fold-ins"* named no phase, so the exit condition was not checkable by someone else — the one thing § 2 exists to be. The Q1 was mine: `settings.json` was described as *"the same"* as `projects.json`, importing a carry-through carve-out that is false — that reader takes named keys and its writer emits a fixed set. Two lanes raised it as an open question and the source settled it. Four Q2s came from one paragraph of my own: an exclusion list *"so the list bounds rather than sprawls"* beside *"it does not bound the promise"*, with log contents excluded while criterion 5 is precisely that a failed server's output is readable, and palette names excluded while a theme id is stored in `settings.json`. The list is deleted rather than reconciled. Two more Q2s were the ladder: the rule gives `0.0.1` for a first release where LWSM-1152 says `0.1.0`, and *"a milestone version cannot be chosen in advance"* sat beside a `1.0.0` defined by its contents with nothing saying what triggers the MAJOR bump. Both are now stated as decisions in § 3. **The fix was mostly deletion** — the document is shorter than the draft the lanes read. |
| 2 | 2026-09-02 | 3, cold — identical brief, packet rebuilt from disk | 0 | 3 | 2 | n/a | **Six verified, five fixed, one surfaced. Every finding landed on text loop 1's own fixes wrote**, which is this gate's documented pattern rather than a surprise. **All three lanes found the same one:** § 2 named `FP01` in scope and then excluded *"every fold-in before `FP09`"* — and `FP01` is one, so the section put the same item in and out, while the wording also read `FP09` itself as in scope. The exclusion is now a complement. Two lanes found that the restatement of the `0.x` rule dropped *"and resets the PATCH"*, which matters precisely because this file tells a contributor it is the only copy they need — at `0.2.3` they would have published `0.3.3`. One lane found the `settings.json` bullet described a mechanism and returned no verdict, and that the harm it named is a DOWNGRADE, which the global breaking test does not reach; it now answers the question and points at LWSM-1289. One found that a contributor is told they need only what is restated here while the test for an unlisted surface was never restated. **The sixth is SURFACED, not fixed:** LWSM-1152's `0.1.0` is a delta arguing with the rule, which global § 3 says this file may not carry, and choosing between it and `0.0.1` is the user's. Recorded in § 3 as open, with nothing released until it is settled. |
