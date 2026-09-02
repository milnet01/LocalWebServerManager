<!-- ants-versioning-overrides: 1 -->
# Versioning overrides — LocalWebServerManager

**Status:** v1 (2026-09-02).

**Versioning for this project is
[`~/.claude/standards/versioning.md`](https://semver.org/spec/v2.0.0.html)**
— the machine-global standard, local to the author's machine, which
mandates Semantic Versioning 2.0.0. It is read in place and not copied
here: a rule stated in two places is two rules that will disagree.

This file holds the two answers that standard deliberately refuses to
supply, because they cannot be true of every project: **what a break
means here**, and **what would make this `1.0`**. Everything else —
which number to bump, when it moves, pre-release suffixes — is the
global file's.

## 1. Breaking surfaces

SemVer is written for something other code imports. Nothing imports
this: it is a desktop application. So *"the public API"* has no
referent, and the list below is what stands in its place. Breaking any
of these bumps the level the global standard's § 2 and § 4 require.

- **`projects.json`** — the registry, and the same format a profile is
  written in. Hand-editable by design, so its keys and their accepted
  types are a promise. Dropping a key, narrowing a type, or changing
  what an absent key means is breaking. Adding one is not: unrecognised
  keys are carried through untouched (LWSM-1218).
- **`settings.json`** — the same, for preferences and window geometry.
- **`scan-roots`** — one directory per line, `#` comments, `~`
  expanded, order preserved because it is the walk order. An empty file
  means *use the default*, and that meaning is part of the format
  (LWSM-1213).
- **The `PORT` contract with sibling projects (ADR-0002).** The one
  surface that is not ours alone: other repositories were changed to
  read `PORT` from their environment. Changing the variable, its
  accepted range, or what an absent value means breaks software this
  project does not own and cannot fix.
- **The `lwsm` command** — that it exists, that `--version` and
  `--help` work, and that an unrecognised option exits 2.
- **The desktop entry id** `io.github.milnet01.LocalWebServerManager`.
  A pinned launcher and a taskbar grouping are attached to it.
- **The keyboard interface** — the number keys, `/`, Escape and Enter.
  `design-accessibility.md` makes the app keyboard-first, and these are
  in the fingers of the user it is keyboard-first *for*.

**Deliberately not breaking surfaces**, so the list bounds rather than
sprawls: the on-screen layout, the palettes and their names, log file
contents and rotation, the wording of any message, and every internal
module boundary. A user can see all of these change without anything
they rely on ceasing to work.

**A surface nobody wrote down is still a surface.** This list makes the
common cases cheap; it does not bound the promise.

## 2. What would make this `1.0`

The global standard's § 4 requires a `0.x` project to state its exit
condition where someone else can check it, and warns that a `0.x`
without one is a project whose leading zero has gone inert.

**`1.0.0` is the five success criteria in
[`docs/discovery.md`](../discovery.md) delivered end to end, plus the
security fold-in, plus a packaged download.** Agreed with the user on
2026-08-24 and recorded in `ROADMAP.md` as **LWSM-1188**, which holds
the reasoning and the running counts; this is the pointer the standard
asks for, not a second copy of it.

The membership rule is what is fixed — the five criteria, security,
packaging — so an item filed into one of those phases tomorrow is in
scope by construction and needs no renegotiation. The phases carrying
them are labelled `criterion 1` … `criterion 5` in the roadmap.

**Out of `1.0`, and this is the half that makes the condition
checkable:** the shell work in P09, the debt in DS01, and the older
fold-ins. All of it is of genuine value and none of it is needed to use
the app for what it is for.

**Inside `0.x` the levels shift down one**, which the global § 4 states
and which is easy to get wrong here: a breaking change to anything in
§ 1 bumps the MINOR and resets the PATCH, and **everything else — a new
capability included — bumps the PATCH.** So the road from the first
release to `1.0` is `0.1.0`, then `0.1.1`, `0.1.2` … and a `0.2.0` only
appears if something in § 1 breaks. A milestone version cannot be
chosen in advance; it is decided by the change.
