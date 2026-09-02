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
- **`settings.json`**. Its keys and meanings are a promise in the same way,
  but the carry-through is not: this reader takes the keys it knows and the
  writer emits a fixed set, so a key added here is dropped by any build that
  predates it.
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

**A surface nobody wrote down is still a surface.** This list makes the
common cases cheap; it does not bound the promise, and a release that broke
something absent from it was still breaking.

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
before `FP09`. All of it has value; none of it is needed to use the app for
what it is for.

## 3. Which number moves

Inside `0.x` the global standard shifts the levels down one: a breaking
change bumps the MINOR, and everything else — a new capability included —
bumps the PATCH.

Two things that rule does not settle, decided here:

- **The first release is `0.1.0`, by decision** (LWSM-1152), not derived
  from the rule, which would give `0.0.1`.
- **The release meeting § 2's condition is cut as `1.0.0`**, whatever level
  its own changes would otherwise be. That is the only planned version
  number; every other is decided by the change rather than chosen ahead of
  it.

## 4. Review loop log

| Loop | Date | Lanes | Q1 | Q2 | Q3 | Q4 | Outcome |
|------|------|-------|----|----|----|----|---------|
| 1 | 2026-09-02 | 3, cold — genre pinned `standard` | 1 | 5 | 2 | n/a | **Nine verified, nine fixed.** All three lanes independently found that *"the security fold-in"* and *"the older fold-ins"* named no phase, so the exit condition was not checkable by someone else — the one thing § 2 exists to be. The Q1 was mine: `settings.json` was described as *"the same"* as `projects.json`, importing a carry-through carve-out that is false — that reader takes named keys and its writer emits a fixed set. Two lanes raised it as an open question and the source settled it. Four Q2s came from one paragraph of my own: an exclusion list *"so the list bounds rather than sprawls"* beside *"it does not bound the promise"*, with log contents excluded while criterion 5 is precisely that a failed server's output is readable, and palette names excluded while a theme id is stored in `settings.json`. The list is deleted rather than reconciled. Two more Q2s were the ladder: the rule gives `0.0.1` for a first release where LWSM-1152 says `0.1.0`, and *"a milestone version cannot be chosen in advance"* sat beside a `1.0.0` defined by its contents with nothing saying what triggers the MAJOR bump. Both are now stated as decisions in § 3. **The fix was mostly deletion** — the document is shorter than the draft the lanes read. |
