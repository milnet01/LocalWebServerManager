<!-- ants-dependency-standards: 1 -->
# Dependencies Standard — v1

Governs every version this project pins: Python packages, GitHub Actions,
runner images and the Python runtime. It binds anyone adding, bumping or
reviewing a pin — there is no "done" here, because the versions move whether or
not anyone is looking. Its purpose is that a pin is either *current* or
*explained*, and that an explanation carries the trigger for its own
re-evaluation.

Governs `Kind: chore` dependency work, and any `Kind: implement / fix` change
that touches a pin. Pairs with the other standards — see the
[index](README.md).

**This standard is canonical for version policy.** `coding.md § 1.5` states the
same preference in one line and defers here; where the two ever differ, this
document wins and `coding.md` is the bug.

## 1. Principles

1. **Latest, unless there is a demonstrated reason.** Staying current is the
   default state, not a periodic project. Security fixes arrive in new
   versions, and the cost of a bump grows superlinearly with how long it was
   deferred — three years of breaking changes land in one commit that nobody
   can review.
2. **"It might break" is not a reason. "It broke, here is the evidence" is.**
   An unbumped dependency needs a demonstrated failure, not an anticipated
   one. Anticipated breakage is how a project ends up pinned to a version
   nobody has tested against in years.
3. **Every exception carries its own expiry.** A pin held back for a real
   reason records what broke and which version broke it, so a later release
   can be retested rather than assumed to be broken forever. An exception with
   no retest trigger is a permanent decision made by accident.
4. **Verify a version exists before writing it.** Version numbers are the
   purest form of recall failure: a tag that never existed and a tag that is
   merely stale feel identical from memory.
5. **A bump includes the code it breaks.** Bumping a dependency and leaving
   its callers on the old idiom ships a codebase that compiles for reasons
   nobody intended.

## 2. The default: track latest

**2.1 The pin unit differs by ecosystem, and each is exact within its own
convention.** "Pinned" does not mean the same syntax everywhere, and treating
it as though it does makes this project's own CI look non-conforming:

| What | Pin unit | Example |
|------|----------|---------|
| Python runtime & dev dependencies | exact `==` | `psutil==7.2.2` |
| GitHub Actions | major tag, or a commit SHA where supply-chain risk warrants it | `actions/checkout@v7` |
| Runner images | an explicit label, never `-latest` | `ubuntu-24.04` |
| The Python interpreter | the exact version CI installs | `uv python install 3.13` |

A major tag on an Action **is** a moving reference, deliberately: it takes
security and bug fixes without a PR per patch, which is the trade the whole
ecosystem is built around. That is why § 2.3's rationale is about being left on
an *old major*. A floating `-latest` or `:latest` is a different thing and is
forbidden — it can change behaviour with no version to name.

**Not covered by this rule:** `requires-python` and `[build-system] requires`
are **floors, not pins** — `>=3.13` states what the package needs, and pinning
it exactly would falsely claim newer interpreters are unsupported. They are
governed by § 2.2's currency rule, not by an exactness rule.

Exact pins plus a committed `uv.lock` are what make `scripts/local-ci.sh` and
GitHub CI resolve identically; a range means the two runs can differ, and the
difference surfaces as a failure that does not reproduce locally.

**2.2 An exact pin must be the latest release at the time it is written or
touched**, unless § 3 applies. Check it — `curl -fsS
https://pypi.org/pypi/<pkg>/json | jq -r .info.version` for Python,
`gh api repos/<owner>/<repo>/releases/latest --jq .tag_name` for an Action.
This is seconds, and it is the check that caught `pytest-qt==4.6.0` — a
version that has never existed — before the resolver did.

**2.3 GitHub Actions, runner images and container bases are dependencies**
and are governed by every rule here. An Action left on an old major gets a
deprecation warning today and a hard failure later; a runner image label is
pinned explicitly rather than `-latest` so an image roll cannot turn a green
build red with no commit explaining it.

**2.4 Bump on contact.** Any change to `pyproject.toml`, a workflow, or the
lockfile is the moment to check what else in that file is behind. Waiting for
a scheduled sweep means the sweep is the only thing that ever bumps anything.

**2.5 The lockfile is committed and the gate runs `uv sync --locked`.**
Specifically `--locked`, **not** `--frozen`. Measured on uv 0.11.7 (2026-08-03)
with `pyproject.toml` at `psutil==7.1.0` and `uv.lock` still at `7.2.2`:
`--frozen` exited 0 and left the lock untouched, so the whole run tested the
*old* version, while `--locked` exited 1. `--frozen` means "do not update the
lock", which silently tolerates exactly the disagreement this rule exists to
catch — a commit that edits a pin and forgets to re-lock.

**2.6 Every package ecosystem the project uses is registered in
`.github/dependabot.yml`.** An ecosystem left commented out gets no update PRs
at all, which is indistinguishable from having no outdated dependencies. This
is the only mechanism that surfaces § 2.2 staleness without a human going
looking, so an unregistered ecosystem quietly removes the project's only
automated currency signal.

## 3. Exceptions: when an older version may be held

**3.1 The only acceptable reason is a demonstrated break.** Not a suspicion,
not a changelog that mentions a breaking change, not "the newer one is only
days old". Someone must have tried the newer version and observed a specific
failure.

**3.2 Every held-back pin is recorded in § 5 — the exception register.** Both
places: a short comment beside the pin saying *why* and pointing at the
register, and a full row in the register. The comment is what a reader sees;
the register is what a future sweep reads.

**3.3 A register entry is incomplete without its retest trigger.** It records
the last-good version (the one pinned), the first broken version, what broke,
the evidence needed to re-run it, and *what would make this worth retesting* —
normally "any release after the broken one". Every column in § 5 exists because
one of those is unusable without it.

**3.4 A held pin is retested when its trigger fires**, and the register is
updated either way. "Still broken in 7.3" is as valuable as lifting the
exception, because it stops the next person repeating the test.

**3.5 An exception with no evidence and no trigger is a bug**, and is fixed by
retesting rather than by writing the missing entry from memory.

## 4. Bumping

**4.1 A bump updates the code the new version changed, in the same commit.**
Otherwise the cleanup never happens and the codebase becomes a museum of
idioms that work by accident. Where the bump is a patch with no API change,
say so explicitly in the commit message rather than skipping the check
silently.

**4.2 A bump re-verifies any behaviour a design document rests on.** Some
decisions are *caused* by a version's behaviour, so a bump can quietly turn an
architectural constraint into a free choice — or reintroduce one that was
designed around. The live example in this project is
[ADR-0003](../decisions/0003-launch-via-project-scripts.md), which states the
fact and owns it; the check itself is recorded beside the pin it governs in
`pyproject.toml`. **The fact is not restated here** — a version-specific
observation copied into a second document is one that goes stale the day it
changes.

**4.3 The gate for a bump is `scripts/local-ci.sh`, run locally before the
push.** A dependency change is exactly the class of change that passes review
by eye and fails at runtime.

## 5. The exception register

Every pin currently held below its latest release **on purpose**.

**An empty table means no pin is being deliberately held back. It does not mean
everything is current** — ordinary staleness is § 2.2's job, and the
enforcement table below records that nothing catches it automatically. Reading
an empty register as "all up to date" is the one misreading that would make
this section actively harmful.

Dates are ISO 8601 (`documentation.md § 1.3`). "Dependency" rather than
"package", because § 2.3 puts Actions and runner images under the same rules.

| Dependency | Pinned (last good) | Latest seen | First broken version | What broke | Evidence | Retest when | Last checked |
|------------|--------------------|-------------|----------------------|-----------|----------|-------------|--------------|
| *(none)* | | | | | | | |

`Evidence` points at something re-runnable — a CI run, an issue, a commit, or a
command and its output. A row whose `What broke` cannot be reproduced from its
`Evidence` is a rumour, and § 3.5 says to retest rather than to trust it.

## 6. Anti-patterns

- ❌ Writing a version number from memory. Every one is checkable in seconds,
  and a wrong one either fails loudly at resolve time or — worse — silently
  installs something you did not intend.
- ❌ `>=` or `~=` on a runtime dependency, so local and CI resolve differently
  and the failure only reproduces on the runner.
- ❌ Holding a version back because a newer one *might* break something.
- ❌ An exception comment with no register row, or a register row with no
  retest trigger — both become permanent by accident.
- ❌ Bumping the pin and leaving the calling code on the old idiom.
- ❌ Treating Actions, runner images or the Python version as "not really
  dependencies" and letting them rot while the packages stay current.
- ❌ `ubuntu-latest`, or any `-latest` / `:latest` reference, where a green
  build turning red should require a commit to explain it. Distinct from an
  Action's major tag (§ 2.1), which is a supported moving reference — including
  a tool installed inside a workflow step, where `go install …@latest` is the
  same defect wearing a different hat.
- ❌ Leaving a package ecosystem out of `.github/dependabot.yml` and then
  reading the absence of update PRs as "nothing is outdated".
- ❌ Adding a dependency to avoid writing twenty lines. Every one is weight in
  the AppImage and a future bump someone has to review.

## What checks this

| Rule | What catches a breach |
|------|----------------------|
| §2.1 (exact pins) | **nothing** — a `>=` or `~=` specifier locks and syncs perfectly cleanly. A grep for `>=`/`~=` inside `[project]` and `[project.optional-dependencies]` would catch it; none exists today |
| §2.1 (lock agrees with `pyproject.toml`) | `uv sync --locked` in `scripts/local-ci.sh`. **Not `--frozen`** — measured on uv 0.11.7, `--frozen` exits 0 against a lockfile that disagrees, so the run tests the *old* pin |
| §2.2 (latest) | **nothing** — a stale-but-valid pin resolves cleanly. Caught only by a human checking, by `/debt-sweep`, or by dependabot once §2.6 is satisfied |
| §2.3 (Actions, images) | **nothing automated** — `actionlint` checks syntax, not currency. `.github/dependabot.yml` raises PRs, which is a prompt rather than a gate |
| §2.4 (bump on contact) | **nothing** — a habit, not a check |
| §2.5 (lockfile committed) | `uv sync --locked` fails if `uv.lock` is absent or disagrees |
| §2.6 (every ecosystem registered) | **nothing** — but the omission is visible in `.github/dependabot.yml`, where a missing block is a commented-out example |
| §3.2–3.5 (the register) | **nothing** — the register is prose. `/debt-sweep` reads it; nothing enforces that an entry exists, is complete, or was retested |
| §4.1 (bump the callers) | The test suite, where a caller actually broke; **nothing** where the old idiom still works |
| §4.2 (re-verify design premises) | **nothing automated** — the `hasattr` check is documented beside the pin and run by the person bumping |
| §4.3 (run the gate) | `scripts/local-ci.sh` itself, if it is run |
| §6 (anti-patterns) | Each restates a rule above and inherits its row. The floating-tag one (`*-latest`, `:latest`) is the only greppable one and **nothing** greps it today |

Most of this standard is unenforced, and saying so is the point: the rules
that matter most here — retest triggers, bumping callers with the bump — are
exactly the ones no tool catches. A table claiming otherwise would be worse
than an honest one.

## Cold-eyes loop log

| Loop | Date | Lanes | C | H | M | L | Outcome |
|---|---|---|---|---|---|---|---|
| 1 | 2026-08-03 | 1 (general-purpose, genre pinned `standard`) | 1 | 3 | 5 | 4 | All 13 verified and fixed. The CRITICAL was a **live bug in the CI gate**, not only in this document — see below. |

**Loop 1.** The CRITICAL is the finding this gate exists for: the enforcement
table credited `uv sync --frozen` with catching a lockfile that disagrees with
`pyproject.toml`. Verified empirically rather than from the help text — with
`pyproject.toml` at `psutil==7.1.0` and `uv.lock` at `7.2.2`, `--frozen` exited
**0** and left the lock untouched, so the entire run would have tested the old
version; `--locked` exited **1**. So `scripts/local-ci.sh` was fixed as well as
this table. A "What checks this" row claiming a check that does not happen is
worse than an honest **nothing**, because it is trusted.

Three findings were the document contradicting the project it governs: it had
no entry in `docs/standards/README.md` or `CLAUDE.md` (an unrouted standard is
an unread one); its blanket "pin exactly" rule condemned this repo's own
`actions/checkout@v7`, since the pin *unit* differs by ecosystem; and it
duplicated a version-specific fact that ADR-0003 already owns. Two fixes landed
outside this file as a result — `actionlint@latest` in the workflow became a
pinned `@v1.7.12`, and `.github/dependabot.yml` gained the `pip` ecosystem that
had been sitting commented out, which had silently left the project with **no**
automated staleness signal at all.
