# LocalWebServerManager — Project instructions for Claude Code

Scaffolded from the **Ants App-Build** template; follows the
`app-workflow` (`~/.claude/skills/app-workflow/SKILL.md`, local to the author's machine)
skill.

## Where state lives

Read these in order on every session start:

1. **This file** — stable rules and conventions.
2. **`.claude/workflow.md`** — live status header (current
   phase, active item, step number, blockers, last-update
   timestamp). After reading, **summarise back to the user**
   before doing any work.
3. **`docs/standards/{coding,documentation,testing,commits,dependencies}.md`**
   — the five v1 standards. `dependencies.md` is canonical for
   version policy and is read before touching any pin.
4. **`docs/specs/<active-id>.md`** — the contract for the
   currently-active roadmap item.
5. **`docs/audit-allowlist.md`** — read **additionally** before
   invoking `/audit` or `/code-quality-review` so already-confirmed
   project-specific false positives aren't re-flagged. The
   allowlist is the closed-loop memory for this project — see
   the app-workflow skill (`~/.claude/skills/app-workflow/SKILL.md`, local to the author's machine)
   "False-positive learning" section.

## Which skill runs which job

Standing instruction (user, 2026-08-03). These are not
suggestions to weigh per task — each job has one entry point,
and the point is the pitfalls the skill already knows about:

| Job | Skill |
|-----|-------|
| Writing a spec or plan | **`/write-spec`** |
| Reviewing a spec, design, ADR or standard | **`review-contract`** |
| Deterministic doc checks alone (links, citations, counts) | **`check-doc-facts`** |
| Applying fixes a review produced | **`/apply-fixes`** |
| Writing or editing source code | **`/write-code`** |

**`/cold-eyes` and `/doc-lint` no longer exist** — the documentation
family cut over on 2026-08-12 (global `~/.claude/CLAUDE.md`):
`review-contract` replaced `/cold-eyes`, `check-doc-facts` replaced
`/doc-lint`, and each predecessor was **deleted** in the same commit
that promoted its replacement. This table named the dead ones until
2026-08-12, so a session following it would have invoked a skill that
is not there. **`docs/standards/spec-format.md` still names both
throughout** — see known-issue-036; that file is a standard, so
correcting it re-arms rule 14's gate and it was not swept here.

`/write-spec` carries the `review-contract` gate itself, so a spec
written through it does not need the review invoked separately.
`/apply-fixes` is for closing a list someone else produced —
review findings, audit findings, a fix-pass — and it owns the
blast-radius sweep that catches what a fix moved elsewhere.

## Review cadence — measured and capped (user, 2026-08-13)

**Build first and fold the spec back afterwards; spec-first is the exception,
not the default.** Decided after measuring `review-contract`'s yield across four
loops on `LWSM-1007` + `LWSM-1131`: of ~42 verified findings, **roughly 1 in 10
was a defect implementation would not have caught**, and about a third were the
review's own collateral — loop 2 of each document landed almost entirely in text
loop 1's fixes had added.

Three rules, in force for this project:

1. **Default: build it, then correct the spec to match what was built.**
   `/write-spec` Step 8 already describes this fold-back; it is now the normal
   path rather than the repair path. Most work needs no spec at all
   (`spec-format.md § 1`).
2. **Spec-first only when code creates durable artifacts** — an on-disk format,
   a wire protocol, anything another item binds to. There, coding first means a
   migration rather than an edit. **Cap the gate at 2 loops**, never
   loop-to-convergence. Not 1: the best finding of the whole exercise — the
   merge writing `None` over a stored port, because `port` is in
   `DETECTED_FIELDS` and the replacement rule was unqualified — arrived in
   **loop 2**.
3. **Skepticism filter on every finding: *would the first test run have caught
   this?*** If yes, it is not worth a fix pass — note it and let implementation
   find it. Applied to that session's 42 findings this filter would have left
   about 12. A circular import announces itself with a traceback; a wrong
   on-disk format does not.

**The rationale, because it is the part that generalises:** global rule 14
assumes the spec is handed to a *different* implementer, so "a wrong contract
makes the implementation wrong by construction". When the author and the
implementer are the same agent, that premise is much weaker — the contract's
errors surface while coding. What survives is the narrow class where correct
code faithfully implements a wrong contract **and the tests pass**.

**Global rule 14 still mandates loop-to-convergence and has NOT been changed —
and that is now a decision rather than an unanswered question.** Asked on
2026-08-13, **answered 2026-08-15: keep the divergence local.** The global rule
stands for every other project; this section governs here, and the gap is
deliberate. Nothing further is pending — a later session should not re-open it
as though the user had gone quiet.

**One piece of evidence arrived after the decision and cuts against this
section, so it is recorded here rather than left in a journal.** The P03b close
(2026-08-15) found 55 defects in five items built under the build-first default,
including three CRITICALs — one of which, `_launcher_path` refusing three of the
four launcher kinds, meant the app did not do what the roadmap said it did for a
full day. **That is not yet an argument for reverting**, and the reason is the
skepticism filter in rule 3 above: *would the first test run have caught this?*
For the launcher bug the honest answer is **yes, if a test had used any argv but
`./start.sh`** — so it is a fixture-coverage failure, not a missing-contract
failure, and a spec would not have caught it either. The same is true of the
unbounded overlay: no fixture had a port-less project.
**What to watch on the next close is the class, not the count.** If a defect
turns up that a *contract* would have caught and a test could not have, that is
the signal this cadence is wrong. So far none has.

## Before pushing

**Run `./scripts/local-ci.sh` before any push that touches code,
tooling or CI config** (user, 2026-08-03). A **docs-only push is
exempt** — the gate has nothing to say about prose, and making it
mandatory there just trains people to skip it.

**Since 2026-08-18 a `pre-push` hook enforces both halves of that**, so
it is no longer a rule someone has to remember. Enable it once per
clone — `core.hooksPath` cannot be committed:

```bash
git config core.hooksPath .githooks
```

**The hook gates the commits being pushed, not your working tree**
(LWSM-1160). It checks each pushed tip out into a detached worktree and
runs the gate there, so uncommitted work neither hides a failure nor
invents one. Your tree is not touched, and the extra checkout costs
about five seconds.

The hook decides docs-only **by the paths in the push, never by the
commit subject**, and `scripts/`, `.github/`, `src/` and `tests/` are
never exempt — a change to the checker must run the check.
`tests/test_ci_contract.py` asserts that, because an exemption that
grew to cover `scripts/` would let an edit to the gate skip the gate.

**Some markdown is a gate input too, and that was missed until
2026-08-19**: `CLAUDE.md`, `README.md` and every file under
`docs/standards/` are asserted against by `tests/test_docs.py`, so an
edit to one can redden the suite. They are carved out of the exemption
and always run the gate. The cost of learning this was a red CI run on
`5f1891f`, a markdown-only push that skipped the gate on the strength of
its paths and was caught by GitHub instead. **The carve-out list is
imported from `test_docs.GOVERNED`, never copied** — a standard added
there alone would otherwise leave the contract test green while the file
it governs pushes ungated. And the test **runs** `docs_only()` rather
than reading it: its predecessor scanned the case arms as strings, which
can say which patterns are present but never which arm a path lands in.
Every assertion in it held while the escape went through.
Escape with `git push --no-verify` or `LWSM_SKIP_PREPUSH=1`.

**The hook runs the gate under CI's environment, not a developer's** — it
sets `LWSM_REQUIRE_ALL_TOOLS=1`, so a check that did not run and a tool at
a version CI does not install both REFUSE the push instead of warning about
it. Added 2026-08-21 (LWSM-1159), and it is the same argument the hook
already made for `--fast`: what runs here has to be what runs on GitHub.
Measured with actionlint off PATH, the identical tree exited **0** through
the hook and **1** under the workflow — so the push went out and GitHub
failed it, which is precisely the split the hook exists to close. Running
`./scripts/local-ci.sh` **by hand** is unaffected and stays lenient.

**The tool VERSIONS are pinned in `scripts/ci-tools.env`, which both
the workflow and the gate read**, and the gate reports any tool whose
version differs from the pin as **TOOL DRIFT** — a warning locally, and
fatal under `LWSM_REQUIRE_ALL_TOOLS=1`, where a mismatch means CI did
not install what it promised. **Pinning the steps was never enough; a
gate is its tools.** Found the hard way on 2026-08-18: local shellcheck
0.11.0 passed `scripts/*.sh` while the runner's apt shipped 0.9, which
reports SC2015 on `command -v` guards that 0.11 accepts — so five
consecutive pushes went red against a green local run. To bump a tool,
change the version there; the workflow interpolates it and
`tests/test_ci_contract.py` fails if the two ever part.

**`uv` is the exception to the interpolation**, because `setup-uv` takes
its version as a `uses:` input and a `uses:` input cannot read a shell
variable. The workflow repeats the literal and the contract test asserts
the two are equal — the test is doing the job interpolation does for the
other three.

The script is the single source of truth for CI: `.github/workflows/ci.yml`
prepares a machine and then calls it. **Never add a check to the
workflow instead of the script** — that produces a check nobody can
run before pushing, which is the whole thing this arrangement
exists to prevent.

## Standing quality passes

Both added by the user on 2026-08-03, and both run as part of closing a
phase rather than when someone remembers:

- **Look for refactoring opportunities.** Python is interpreted, so
  there is no compiler catching a tangle — structure is held by
  reading alone. On every phase close, ask what got duplicated, what
  grew a second responsibility, and what a name now lies about.
  Refactor when there is something to refactor; **say "nothing to
  refactor at this size" when there isn't**, rather than inventing
  churn to look diligent.
- **Run a security pass.** Not just the scanners — this app spawns
  processes, signals process groups, reads other projects' files and
  will eventually run user-authored commands. That is a real attack
  surface, and the scanners only see the code that exists today.

## Subagents

**Agents are permitted where they genuinely help and are token-
efficient** (user, 2026-08-03). Reviews are the clearest case —
`review-contract`, `/audit` and `/code-quality-review` all depend on a
fresh pair of eyes that has not been reading along, so the rule-14
gate runs its reviewers here without asking first. Broad
"where is X used across the tree" searches are the other case.

This overrides any session-level default that says not to spawn
agents unless asked. It is not a licence to fan out on work one
context can already do.

## Closing a phase

Run **`/close-phase`** once steps 1–4 of the per-phase loop
are done — see SKILL.md for the full description.

## Tech stack

Chosen in Phase A (2026-08-03) — full reasoning and runner-ups
in [`docs/discovery.md § Tech stack`](docs/discovery.md).

- **Python 3.13** + **PySide6 6.11** (Qt 6) — a desktop app, not
  a website. Native on KDE; both already installed.
- **`QProcess`** for launching and supervising servers, so
  status, live log output and exit signals share one source of
  truth. **`psutil`** for "who holds this port".
- **`uv`** + `pyproject.toml` for dependencies; **`pytest`** +
  **`pytest-qt`** for tests; **`ruff`** for lint and format.

The app **runs each sibling project's own launcher** (`start.sh`,
`run.sh`, `serve.py`, `serve.mjs`, `npm run dev`) and never
edits sibling source. Ports become reassignable via a port
contract the siblings adopt — see `docs/discovery.md §
Feature set`, formalised as an ADR in Phase B.

## Build and test

```bash
uv sync --extra dev     # resolves from the committed uv.lock
./scripts/local-ci.sh   # the whole gate
./scripts/local-ci.sh --fast   # same, minus the integration tests
```

There is no compile step. `scripts/local-ci.sh` runs, in order:
`uv sync --locked`, `ruff check`, `ruff format --check`,
`python -m compileall src tests` (the syntax gate), an
entry-point resolution check, `pytest`, `shellcheck`, and
`actionlint` + `yamllint`. A check whose tool is missing is
reported as an explicit **SKIP**, never folded into the pass —
**each tool is tracked separately**, because sharing one flag
between `actionlint` and `yamllint` made a missing `actionlint`
report a clean pass (reproduced and fixed 2026-08-06).

**`yamllint` runs `--strict` against `.yamllint.yml`, not `-d relaxed`**
(2026-08-18). Two changes, and both were needed to make CI *fully*
clean rather than merely passing. The config raises `line-length` to
**100**, because 80 is the wrong limit for a file whose central security
practice is pinning every action to a 40-character commit SHA — 63
characters of a pinned `uses:` line are spoken for before the action is
named, and `actions/checkout` fit inside 80 by a single character while
`astral-sh/setup-uv` did not. Neither the SHA nor the trailing version
comment can be shortened: the comment must stay trailing or dependabot
stops rewriting it. And `--strict` makes a warning exit non-zero,
because yamllint's default is to report one and exit 0 — which is how an
82-character line sat in the CI annotations of runs everyone read as
green. **Turn a warning class fatal only once its count is zero**; the
alternative is a gate people learn to push past.

`-c` and `-d` are mutually exclusive, so reverting to `-d relaxed`
silently discards the config *and* the raised limit together.

In CI, a SKIP is **fatal**: the workflow sets
`LWSM_REQUIRE_ALL_TOOLS=1`, so the machine that is supposed to
hold every tool cannot report green on a degraded run. **The
`pre-push` hook sets it too** (LWSM-1159) — a local run standing in
for CI has to answer the question CI will ask. What stays lenient is
running the script **by hand**: a missing linter should not stop you
testing your own change, and that is the only case the asymmetry was
ever for.

`.python-version` is committed, so a developer's machine and the
runner resolve the **same** interpreter. `requires-python` is only
a floor, and `filterwarnings = ["error"]` would turn any
divergence into a red build that does not reproduce locally.

See **Before pushing** above for when the gate is mandatory.

## Before releasing

**Run `./scripts/local-release.sh [X.Y.Z]`** (LWSM-1151). It is
`cut-release`'s Phase 0 made runnable, and it reports without changing
anything.

**It mirrors nothing, and that is the difference from `local-ci.sh`.**
That script is the CI — the workflow calls it. CI here fires on `push`
and `pull_request` only, with **no tag trigger and no release trigger**,
so *nothing on GitHub ever checks a release*. This script is the only
gate a release gets.

Two things to know. **The verdict never reads "ready" while a check was
skipped** — a blocker and a check that could not run are tracked
separately, because "no blockers found" and "the blocker check did not
run" must not print the same way. And **`--dry-bump` refuses on a dirty
tree**: its revert is a `git checkout`, which destroys uncommitted work.
That is the mistake LWSM-1067 made twice in one session, once taking a
`roadmap_log` flip with it and leaving ROADMAP.md saying 📋 while the
store said ✅.

`cut-release` still owns the release itself — this performs no bump, no
commit, no tag and no publish.

## Commit conventions

Per [`docs/standards/commits.md § 1.1`](docs/standards/commits.md):
every commit subject is `<ID>: <description>`, where `<ID>` is
either a phase ID (`P##`, `FP##`, `DS##`, `DOC##`, `R##`) or a
stable per-bullet ID for ROADMAP_FORMAT v1 projects
(`LWSM-NNNN`).

**More than one phase can be in flight at once, and the status header names
only one.** Observed 2026-08-19 and recorded rather than resolved, because
resolving it is `/close-phase`'s call and not a session's. `.claude/workflow.md`
§ 1 says `P03b` OPEN, which is true — LWSM-1039, LWSM-1008 and LWSM-1121 are
still 📋. Meanwhile LWSM-1145, LWSM-1146, LWSM-1147, LWSM-1149 and LWSM-1031
are all `P04:` items and all shipped, so `P04` is the live label for work with
no item id (`P04: record the theme layer`, `P04: the README says…`) while
`P03b:` carries the FP07 bookkeeping. **Follow the commit log's precedent for
the prefix, not the status header** — the header names the phase whose ITEMS
are outstanding, which is not the same question as which phase you are
committing under. Costs one lookup per session until a close reconciles them.

**A phase ID may carry a lowercase continuation suffix — `P03b`**
(user, 2026-08-12). It names a phase that finishes a predecessor's
undelivered scope, and exists because this roadmap assigns
`P04`–`P09` to named themes *in advance*, so a phase closed against
partial scope has no free number to spill into. `P03` closed
2026-08-12 with the scanner shipped and four planned items
undelivered; `P03b` carries those four. Renumbering the themes
instead would have re-labelled 28 bullets and every doc that cites
a phase by number, and re-pointing the pushed `P03-complete` tag
needs the force-push authorisation `commits.md § 4.2` withholds.

The suffix is a continuation, **not a sub-phase**: `P03b` runs the
full 9-step loop and earns its own `P03b-complete` tag. Only reach
for one when a phase closes against partial scope and the next
number is already spoken for — a phase that simply has more work
in it stays one phase.

Every implementation phase ends with `git tag -a <ID>-complete`
on the closing commit. Tags are local until the user explicitly
authorises a push.

## Licence and visibility

MIT, and **published as a public repository** at
`github.com/milnet01/LocalWebServerManager` (LWSM-1004, created
2026-08-03 from a squashed orphan commit — the pre-publication
history named author-private services and is kept locally under
the `pre-public-history` tag).

Two consequences to hold on to:

- **Everything in this tree is world-readable**, including
  `ROADMAP.md`, `docs/specs/`, and any security finding folded
  into the roadmap while still open. `docs/private/` is
  gitignored and is the only place author-private facts go.
- **`LICENSE` names Anthony Schemel** as copyright holder. Keep
  it a legal person, not the project name.

## Push policy

Inherits from the user's global `~/.claude/CLAUDE.md` § 6
(public repos: push freely; private: batch + ask). This repo is
**public**, so the free-CI-minutes rule applies: push freely, no
batching gate. `main` tracks `origin/main`.

Detect repo visibility once per session via
`gh repo view --json visibility -q .visibility` and cache; the
result is recorded in `.claude/workflow.md` § 1 status header.

## Module map

The modules below are the list; P03 and P05 each add to it, so no
count is written here (`documentation.md § 1.5`). The layering rule is
[`docs/standards/coding.md § O1`](docs/standards/coding.md): a
core module may import `QtCore` but never `QtWidgets`, so every
one of them is testable without a display. **`tests/test_layering.py`
enforces it by parsing the AST, not by grepping for the string** —
every core module *documents* the rule in its docstring, so a
substring search reports all of them as violations.

- **`src/lwsm/__init__.py`** — the package docstring stating that
  rule, and `__version__`.
- **`src/lwsm/__main__.py`** — `main()`, plus the thin **`run()`**
  the `lwsm` console script and `python -m lwsm` actually name.
  `run()` is `main()` followed by
  `exit_without_waiting_for_abandoned_probes`, and the split is
  load-bearing: that call is an `os._exit` when a probe was
  abandoned, and while it sat inside `main()` **one abandoned probe
  ended the pytest run at 40 % of the suite with exit code 0** and
  a report that read as green (LWSM-1100). Anything that ends the
  process belongs behind `run()`, never in `main()`, which tests
  call in-process. An `argparse` parser, so
  `--version` and `--help` work and an unrecognised option exits
  2 rather than being ignored. Prints where it is logging to, and
  starts anyway — with a warning on stderr — when the log
  directory cannot be used. Since P02 it also opens the window,
  via **`build_window()`** — a deliberate seam: `main()` ends in a
  blocking `app.exec()`, so anything inside it is unreachable from
  an in-process test. `QApplication` is imported and constructed
  *inside* `main`, after `argparse`, so `--version` needs no
  display.
- **`src/lwsm/applog.py`** — the application log.
  `default_state_dir()`, `get_logger()`, `configure_logging()`,
  `configure_stderr_logging()` (the fallback the entry point uses
  when the file log is unavailable), and a
  `_NoFollowRotatingFileHandler` that writes only to a private
  regular file: `O_NOFOLLOW` 0600 inside a 0700 directory, and
  then an `fstat` requiring one link and our own ownership, so
  neither a symlink nor a **hard link** nor a **FIFO** planted at
  `app.log` can redirect or block the log. The last two were
  reproduced against the `O_NOFOLLOW`-only version on 2026-08-06.

Added at P02 (LWSM-1005), contract in
[`docs/specs/LWSM-1005-vertical-slice.md`](docs/specs/LWSM-1005-vertical-slice.md):

- **`src/lwsm/registry.py`** — core. `ProjectRecord`,
  `RegistryError`, `default_projects_path()`, `load_projects()`,
  and since LWSM-1007 also `LauncherKind`, `LoadResult`,
  `RegistryMissing`, `DETECTED_FIELDS`, `USER_FIELDS` and
  `save_projects()`. Returns a **`LoadResult`**, not a tuple: the file
  being unusable raises, one bad *record* never does, and
  `rows_refused` is carried **separately from `reasons`** because a
  field refusal keeps the row and only a row refusal may stop a
  write. A bad **port** loses the field, not the row. **Port ranges
  differ by field** — declared
  `port` is 1–65535 (a project may legitimately declare 80),
  `port_override` is ADR-0005's 1024–65535. Type checks use
  `type(v) is int`, because `isinstance(True, int)` is `True` and
  the file is hand-editable.
  Since LWSM-1148 it also holds the profile pair — `export_profile`,
  `merge_imported` and `_user_half_applied` — on one claim: **a profile IS a
  `projects.json`**, same `schema_version`, same writer, same parser. That is
  why the item needed no format, no second parser and no migration, and why it
  was built rather than specced. The two merges are **mirrors**: a rescan
  refreshes the detected half and preserves the user half, an import does the
  reverse, and both are driven by `DETECTED_FIELDS` / `USER_FIELDS` so
  LWSM-1007 INV-1 keeps each complete. **`_user_half_applied` needs no
  per-field qualifier where `_detected_half_applied` needs one for `port`** —
  a scan's `None` means *unknown*, a profile's `None` is a real value — and
  that rests entirely on the window refusing an import whose load reported
  ANY refusal. Change one and you must change the other.
  **`export_profile`'s gate is not `save_projects`' gate**: there the risk is
  destroying a recoverable registry, here it is saving a profile that looks
  known-good and silently lost the rows the load refused.
- **`src/lwsm/ports.py`** — core, no Qt at all. `PortProbe`,
  `PortSnapshot`, `ProbeError`, and the `SupportsSnapshot`
  Protocol the controller accepts so test fakes are the contract.
  One `psutil.net_connections` call per snapshot.
- **`src/lwsm/controller.py`** — core, `QtCore` only.
  `ProjectController`, `ProjectStatus`, `RowView`. Since LWSM-1010
  it also drives the buttons: `start_project`, `stop_project`,
  `restart_project`, and the **optimistic overlay**. **The overlay
  settles on the state it was heading *for*** — `starting` on
  running, `stopping` on stopped — never on any derived state:
  `design.md § State management` contains both readings, and only
  this one makes "a slow start keeps the overlay" true, since a
  server that has not finished binding reads as *stopped*. Polls every
  1000 ms **on a `QThreadPool` worker** (design.md § State
  management requires it). **`QRunnable` is not a `QObject`**, so
  the task holds a composed `_SnapshotSignals(QObject)` — a
  `Signal` declared on a bare `QRunnable` has no `emit`.
  `stop()` waits for the pool, and every test fixture calls it. Its bounded-wait
  escape is **`abandon_pool`**, public since LWSM-1139 because the window's
  rescan pool needs the identical two lines and a second copy that forgot the
  `setParent(None)` would look right and hang on exit. Since LWSM-1136 the poll
  also calls **`_rotate_logs`** — before the in-flight guard, since a log cap
  that lapses when the socket table is slow is not a cap — and `RowView` carries
  **`managed`**, read once per render from `supervisor.running()`, because
  ADR-0004 derives state from the socket table and `status` therefore cannot say
  whose server it is.
- **`src/lwsm/configfile.py`** — core. `ConfigFileError`,
  `MAX_FILE_BYTES`, `MAX_REASON_CHARS`, `quoted()`, `read_bounded()`,
  `prepare_config_dir()`, `refuse_existing_target()` and
  `write_json_atomically()`. **Extracted from `registry.py` by LWSM-1031,
  which needed a second config file** — every function in it was written
  after a measured defect (a FIFO that made the read block forever with no
  window and no log line, a symlink destroyed by `os.replace`, a
  `mkdir(parents=True, mode=0o700)` leaving every parent at the umask
  default, a 600 MB file peaking at 1214 MB RSS), so a second weaker copy
  for `settings.json` is what `coding.md § 1.3` forbids. `RegistryError`
  subclasses `ConfigFileError` and `save_projects` **converts rather than
  propagating**, because its contract and four tests promise the narrow
  type and `except RegistryError` does not catch a base-class instance.
- **`src/lwsm/settings.py`** — core, no Qt. `Settings`, `LoadResult`,
  `SettingsError`, `default_settings_path()`, `load()`, `save()`.
  Minimal by design: `schema_version` plus the theme id, on the file
  **LWSM-1018 grows**. **`load()` never raises** — that is the one rule
  separating it from `registry.py`: a project list nobody can parse is a
  refusal the user must see, because the alternative is inventing projects
  (ADR-0005), while a preference nobody can parse has an obvious right
  answer. Every refusal still reports a reason, and `build_window` puts
  those in the status bar; a mutant logging them and never showing them
  survived every other test. It **does not check that a theme id names a
  theme** — a core module may not import `theme.py` (`§ O1`), and
  `theme.theme_for_id` owns the fallback.
- **`src/lwsm/placement.py`** — core, and the only module importing **no Qt
  at all**, not even `QtCore`: the arithmetic in it is ADR-0007's security
  boundary, and a boundary is worth testing with no display. `Rect`,
  `clamp_to_screens`, `centre_in`, `pair_or_none`, `on_wayland`,
  `placement_available`, `position_is_readable`, `kwin_script`,
  `run_kwin_script`, `place_window`. Added by LWSM-1033; the technique is
  transcribed from `OneUp/oneup/gui/placement.py`, **not** the
  `OneUp/updater.py` lines ADR-0007 cites, which no longer resolve (DS01,
  scheduled with P10). **Restoring a position and centring are one operation
  with two targets**, so both go through `place_window` and the clamp cannot
  be forgotten by either. **Setting a position and READING one are not
  symmetric** — see the Wayland trap below, which is the item's whole shape.
- **`src/lwsm/theme.py`** — UI layer, and the **only** module
  allowed a colour literal; `test_layering.py` exempts it by an
  explicit allowlist and asserts it still holds the palette.
  Since LWSM-1031 it holds **eight palettes** — `THEMES`, `DEFAULT_THEME`
  (`midnight`, LWSM-1147) and `theme_for_id()`. The six are **transcribed**
  from `finbreak/src/finbreak/ui/theme.py`, never imported: a public repo
  cannot depend on a path outside it. **Every state token was solved for,
  not chosen** — a fixed hue per meaning, lightness walked *away* from the
  palette's surfaces until the worst of `window`/`base`/`alt_base` clears
  the floor, then stopped. **Walking from the far end instead returns
  near-white for every hue on a dark palette**, which is legible and
  carries no meaning at all; that draft passed every contrast check, which
  is why `test_the_state_tokens_are_distinguishable_from_the_body_text`
  exists. Four `muted_text` values diverge from finbreak, each recorded
  beside its value: finbreak tuned them against `window` alone and
  `alt_base` is darker. `high_contrast` is a flag **on the theme** rather
  than a set of ids beside it, because the floor a palette is judged
  against is a property of the palette.
- **`src/lwsm/mainwindow.py`** — UI layer.
  Since LWSM-1033 it also owns
  **window geometry and Centre on screen** — `showEvent`/`eventFilter`,
  `_restore_geometry`, `closeEvent`, `centre_on_screen`, `_place_at`,
  `_screens` and the eighth and ninth injected seams (`save_geometry`, which
  defaults to doing NOTHING for `save_theme`'s reason, and `place`, the only
  seam defaulting to the real function because ADR-0007 requires the
  verification to be behavioural). **What is stored is a FRAME corner and a
  CLIENT size**, because those are what `move()` and `resize()` round-trip
  exactly; storing `normalGeometry()`'s corner and restoring it through
  `move()` walks the window two pixels down and right on every launch
  (measured). `normalGeometry`, never `geometry`, or a maximised window
  reopens filling the screen without being maximised — which the user cannot
  undo with the maximise button. The **View** menu is a third top-level menu
  for one action on purpose: "Centre on screen" is a verb, and every entry in
  Settings is a choice that then stays chosen.
  Since LWSM-1131 it also
  owns the **Rescan** seam: `RescanContext` (scan roots, the scan
  function and the writer, all injected so `testing.md § T1` holds),
  `summarise_merge`, and a `_RescanTask` on its own `QThreadPool`.
  **The write happens in the slot, never in `merge()`** — the merge
  runs on the pool thread and is handed no `LoadResult`, so the
  window is the only place the records and LWSM-1007's read-only
  gate are both in scope. Rows are created once
  and **updated in place**; rebuilding would drop keyboard focus
  and re-announce every unchanged row. The state glyph is
  decorative and excluded from the accessible name, which is
  built from the rendered cell strings.
  Since P04 it also owns the **layout**: `_align_columns` (LWSM-1145)
  and `_apply_default_geometry` (LWSM-1149), with `DEFAULT_VISIBLE_ROWS`
  and `MIN_VISIBLE_ROWS` as **counts of rows, never pixels** (`§ O7`).
  **Qt syncs nothing between sibling layouts** — each `ProjectRow` owns
  its own `QHBoxLayout`, which is why every row's buttons landed at a
  different x. One width per column, the widest cell winning, re-run
  after every `_sync_rows` and after a language or font change; it
  cannot be settled at construction, because rows are updated in place.
  `natural_widths` reads the rendered text and the stored floors and
  **never `minimumWidth()`** — `apply_column_widths` sets a FIXED width,
  so reading it back makes the column monotonic: it grows for a
  long-named project and never shrinks when that project leaves.
  The row list sits in a **`QScrollArea`**, which was not in LWSM-1149's
  filed scope and is the part that mattered most: without it the
  window's minimum height is every row it holds, so twenty projects give
  a window taller than the screen that cannot be shrunk.
  Since LWSM-1031 it also owns the **theme picker** — `_build_theme_menu`,
  `set_theme` and `ProjectRow.apply_theme`. **The swap goes to the
  APPLICATION palette, the window's style sheet and then every row**, which
  is the same three places `__init__` applies it and for the same reasons:
  a `self.setPalette` themes the frame and nothing inside it (LWSM-1118),
  and a row caches its own `Theme` **and its glyph colour**. LWSM-1111
  named that cache as the live edge the day the palette could change and
  predicted the fix would look like `retranslate()` — it does, both going
  through `_rerender`. **`save_theme` is the fourth injected seam and the
  first defaulting to doing NOTHING**: `confirm` and `open_url` default to
  the real behaviour safely because an untriggered test never reaches
  them, while this one would write to the developer's own `settings.json`
  the moment a test exercised the picker.
  Since LWSM-1146 it also owns the **menu bar** — `_build_menus`,
  `_retranslate_menus` and `_set_rescan_enabled`. It owns the BAR only; the
  settings dialog is LWSM-1018's and arrives through the injected
  **`open_settings`** seam, the third of the same shape as `confirm` and
  `open_url`. Every label carries an `&` mnemonic so the bar is keyboard-
  reachable before LWSM-1040 lands, and the labels are set in
  `_retranslate_menus` rather than at construction so `LanguageChange` has one
  place to go. **The menu bar counts as chrome in `_apply_default_geometry`** —
  leave it out and the window opens one bar too short, so a list that fits
  scrolls; two LWSM-1149 geometry tests die on that mutant. Rescan is one
  control with two faces, which is why the enable/disable is a helper and not
  two call sites.
  Since LWSM-1139 **`shutdown()` is `controller.stop()`'s shape, both halves**:
  it sets `_stopped` (checked by `_on_rescan_done` and `_on_rescan_failed`, so a
  merge landing after teardown cannot save over the project list) and it TAKES
  the pool, waits, and hands a timed-out one to `abandon_pool`. Logging the word
  "abandoning" and returning leaves the pool parented, so `~QThreadPool` runs
  the unbounded join anyway — the claim in `__main__` was false for a day.
  **`update_from`'s announcement is gated on the accessible NAME, not on
  `RowView` equality** (LWSM-1141): `managed` is the first field that renders as
  button enablement and as no text at all, so the view can change while nothing
  a screen reader reads out does. Any future non-textual field inherits that.
  Since LWSM-1040 it also owns **keyboard-first navigation** — `_filter`,
  `_apply_filter`, `_ordered_rows`, `_retranslate_filter` and the window's
  `keyPressEvent`, with `ProjectRow.matches` and `ProjectRow.keyPressEvent` on
  the row. **The filter box SHARES the Rescan strip** (user decision,
  2026-08-19) rather than taking a second one: every row of chrome is a row the
  list does not get, and `_apply_default_geometry` therefore measures the
  **strip**, not the button in it. The strip is now unconditional, because the
  filter is there whether or not the window has anything to rescan.
  **The two mechanisms share one keyboard by relying on Qt's propagation, not
  on a guard**: a `QLineEdit` consumes every digit and `/`, so typing `1` into
  the filter types rather than jumping, and no line in `keyPressEvent` says so.
  Escape is the deliberate exception — `QLineEdit` ignores it, which is what
  lets one handler clear the filter from inside the box and from anywhere else.
  **Enter CLICKS the row's enabled button** rather than calling the controller,
  so which action is legal in which state stays stated once in
  `_apply_button_state`; both overlay states disable Start and Stop together,
  so Enter does nothing mid-transition without naming a state.
  **Filtering hides rows, never rebuilds them** (INV-13), and `_sync_rows`
  re-applies the filter so a rescan cannot land a project into a list the user
  has narrowed.
  Since LWSM-1148 it also owns **profile export and import** — `_export_profile`,
  `_import_profile`, `summarise_import` and the sixth and seventh injected seams,
  `choose_profile_to_save` / `choose_profile_to_open` (a real `QFileDialog` in a
  test hangs the run, which is `choose_directory`'s reason). **Both File-menu
  entries appear or neither**: exporting needs the `LoadResult` its gate reads
  and importing needs somewhere to write back to, so one condition covers both
  and states nothing untrue. **Import is disabled while a rescan is in flight**
  and export is not — a rescan that started first writes last, so a restored
  user half would be silently dropped; export only reads. `_apply_rescan`'s body
  became **`_apply_merge`**, shared by both, because the write gate, the
  `RegistryError` handling and the `self._load` refresh after a successful write
  are the same three rules either way — and a second copy is a second place to
  forget the refresh.

Added at P03 (LWSM-1006, which also lands LWSM-1050), contract in
[`docs/specs/LWSM-1006-scanner-detection.md`](docs/specs/LWSM-1006-scanner-detection.md):

- **`src/lwsm/scanner.py`** — core, no Qt at all, like `ports.py`.
  `scan()`, `DetectedProject`, `PortFinding`, `ScanResult`,
  `PortRule`, `Confidence`, `Deadline`, and the
  `SupportsUnitLookup` Protocol the systemd surface is injected
  through. **`LauncherKind` moved to `registry.py` with LWSM-1007**
  and is re-exported from here, so `scanner.LauncherKind` still
  resolves; the direction is `scanner` → `registry` and adding the
  reverse import stops the package importing at all, on either entry
  order. `tests/test_layering.py` asserts that by AST. **Everything it reads belongs to somebody else**, so
  every open goes through **one** function, `_open_source`
  (`O_RDONLY|O_NONBLOCK|O_NOFOLLOW`) — that single seam is what the
  tests patch to prove no file outside a candidate is ever touched.
  `port is None` means *unknown*; it is never a guess.
  **`CORE_MODULES` in `tests/test_layering.py` now covers
  `applog.py` too**, and a new source-invariant test derives the
  list from `coding.md § O1`'s four-way split so a core module can
  no longer be silently missing from it.

Added at P05 (LWSM-1009, which also lands LWSM-1048 and the core
halves of LWSM-1046 and LWSM-1047). **No spec** — the first item
built under § Review cadence's build-first default:

- **`src/lwsm/supervisor.py`** — core, no Qt at all, like
  `ports.py`; stop needs a worker thread and a plain
  `ThreadPoolExecutor` is enough for one. `Supervisor`,
  `ManagedProcess`, `StopOutcome`, `TrustStore`,
  `build_child_env`, `validate_launcher`, `launcher_fingerprint`,
  and the refusals `LauncherRefused` / `LauncherUntrusted` /
  `PortAlreadyBound` / `AlreadyRunning`. **Stop signals the process
  *group*, not the descendants** — a launcher that double-forks
  leaves a server reparented to init, which `Process.children()`
  can no longer see while `start_new_session=True` guarantees it is
  still in the group. Every signal goes through a `psutil.Process`
  handle **captured at spawn**, which is what lets
  `_raise_if_pid_reused` fire at all. **Log rotation copies and
  truncates rather than renaming**, because the child holds a
  duplicate of our descriptor and a rename would leave it writing
  into an unlinked inode — which is also why the log is opened
  `O_RDWR` rather than `O_WRONLY`. **Which file an argv names is
  decided by POSIX, not by path arithmetic**: `_launcher_path`
  returns the script for `./start.sh`, `python3 serve.py` and
  `node serve.mjs`, and `None` for `npm run <script>`, whose
  untrusted content is a string inside `package.json` that
  `launcher_fingerprint` hashes under its own marker
  (LWSM-1132, LWSM-1140). **Both halves of the registry are guarded under the
  lock across the whole operation, not at one end of it** (LWSM-1137/1138):
  `start()` RESERVES the key in `_Registry.starting` before it releases the lock
  for the pre-flight, the trust gate, the log open and the spawn — a set beside
  `processes` rather than a sentinel inside it, so `running()`, `_get` and
  `exited()` never see a row that is not a `ManagedProcess` — and `stop()` POPS
  the entry before it signals anything, so whoever pops owns the sequence and
  the log descriptor is closed exactly once. The reservation's discard lives in
  a `finally`: one that only ran on success would turn a single refused start
  into a project that can never start again this session.
  **Popping is not RESERVING, and for a while `stop()` only popped**
  (LWSM-1168) — the grace, kill and reap window ran with the project in
  neither map, so a Start arriving inside it passed the pre-flight and spawned
  a second child, after which the in-flight stop killed the old group and the
  manager reported its own new server as a stranger's. Reproduced by holding
  the window open at the `_on_wait` seam rather than racing for it. `stop()`
  now holds the key in `_Registry.stopping` for the whole sequence, discarded
  in the same `finally` shape and for the same reason. It gates `start()`
  alone: a second `stop()` still finds nothing and returns an empty outcome,
  which is what makes stop() idempotent.

Added at P04 (LWSM-1018). **No spec** — build-first, per § Review cadence:

- **`src/lwsm/settingsdialog.py`** — UI layer. `SettingsDialog`,
  `keyboard_focus_order`. **It edits three fields, not the four the bullet
  filed**, and both absences were settled with the user (2026-08-21) rather
  than dropped: *scan roots* stay in the `scan-roots` file (LWSM-1144) and the
  dialog edits that file in place, because copying them into `settings.json`
  buys a migration and a second owner for no user-visible gain; and there is no
  *slow-start threshold* to configure, because ADR-0004 § Slowness is not
  failure deleted the 15-second `starting` deadline on measured evidence, so a
  setting for it would re-introduce the defect that ADR reversed.
  **The dialog owns no I/O** — it is handed values and returns values, and
  `build_window` is the only scope where both config files and both live
  objects are in reach, which is what the `open_settings` seam was left for
  (LWSM-1146). `choose_directory` is the sixth injected seam, for `confirm`'s
  reason: a real `QFileDialog` in a test hangs the run.
  **Both numbers apply without a restart** — `QTimer.setInterval` is honoured
  on a live timer, and `rotate_if_needed` re-reads `Supervisor.max_log_bytes`
  each poll. `settings.py` owns both defaults and `controller.POLL_INTERVAL_MS`
  / `supervisor.MAX_LOG_BYTES` are aliases of them, so the file's default and
  the code's default cannot drift.
  **A saved scan-roots file keeps the user's LEADING comment block and loses
  interleaved ones** — a stated loss, pinned by a test: re-attaching a comment
  to the wrong surviving line is worse than dropping it.

Tests: `test_applog.py`, `test_main.py`, `test_registry.py`,
`test_settings.py`, `test_settingsdialog.py`, `test_placement.py`,
`test_ports.py`, `test_controller.py`, `test_mainwindow.py`,
`test_layering.py`, `test_scanner.py`, `test_supervisor.py`,
`test_ci_contract.py` (the gate's own contract — that `ci.yml` adds no
check of its own, that both sides install the versions
`scripts/ci-tools.env` pins, and that the `pre-push` hook is present,
executable and does not exempt the gate's own inputs) (+ `scanner_fixtures.py`,
the detection regression corpus every future mis-detection is
added to), plus `conftest.py` (sets
`QT_QPA_PLATFORM=offscreen` when unset, so a bare `pytest` cannot
open a real window, and **pins `XDG_CONFIG_HOME` to a fresh directory
per test** — since LWSM-1031 `build_window` reads `settings.json`, and
three `build_window` tests pin only `projects_path`, so without this they
pass or fail depending on which palette the author last chose in the real
app; and since LWSM-1033 **pins `XDG_SESSION_TYPE` to `x11`**, because
`placement.py` branches on it — this machine runs Wayland and the CI runner
has it unset, so an unpinned test asserting either branch passes on one
and fails on the other). **Markers go on tests, not files** — marking
a whole file by its heaviest test makes `--fast` silently skip
every light test beside it.

**Trap: a `testing.md § T9` mutation that removes ONE of several
redundant guards proves nothing.** LWSM-1006's byte cap is checked in
three places — the `fstat`, the bytes `_read_bytes` actually read, and
`_read_lines`' running total — deliberately, so a file that grows
between the fstat and the read is still refused. Deleting any one left
the test green, which reads exactly like "the bound is untested" and is
not what it means. **Mutate the whole mechanism, not one line of it**;
and mutating the *constant* instead is worthless whenever the fixture
derives its own size from that constant. Hit 2026-08-08 — two of the
four prescribed mutations came back green on the first attempt, and one
of them was a genuinely dead assertion (a tail reading `xxxPORT=9999`,
which rule 1's left boundary rejects anyway, so the discard logic it
claimed to test could be deleted).

**And a mutation *prescribed by a review bullet* can be inert — run it and read
the output before trusting the bullet.** LWSM-1126 asked for `*sorted(
dependencies)` to be appended to the scanned lines and stated the result becomes
port 7. `dependencies` is a set of **keys**, so what gets scanned is `get-port`,
which holds no digits: the mutant ran and the suite stayed green. A fold-in
bullet is a reviewer's reading of a mechanism, not a measurement of it — four
times across FP05 and FP06 a bullet has been wrong about its own mechanism, in
both directions. **Also check the fixture can express the hazard at all**: the
same item's dependency pair had to be pretty-printed onto its own line, because
in a minified `package.json` rule 2 stops at the document's first `:` and never
reaches it.

**A mutation YOU write can be inert too, and a shell loop is where it happens.**
LWSM-1155 ran seven mutants through a bash helper driving `python3` string
replacements; **two came back green without having been applied.** One meant to
*move* `hops += 1` and instead *deleted* it, so the counter never incremented
and the test passed for a reason unrelated to the mutation. The other never
applied at all — the pattern held quotes and backslashes the shell mangled
before `python3` saw them. Both read exactly like "the mutant survived", which
is the conclusion *"this code is untested"* — the same false confidence the
mutation was run to remove, arrived at from the opposite side. **Assert the
anchor matched before running the test** (`assert t.count(a) == 1`), and prefer a
heredoc'd `python3` over shell-interpolated arguments for anything holding a
regex. A mutant that reports green without having been applied is worse than no
mutant, because it is counted.

**And an anchored EDIT needs two guards, not one — `t.count(a) == 1` is only
the first.** Two shapes cost a cycle each on 2026-08-21 while shipping
LWSM-1148. **An "already applied" sentinel must name a SYMBOL, never the item
id**: `assert "LWSM-1148" not in t` refused a file whose only mention of the id
was a docstring the same run had written one call earlier — which reads as
"this is already done" and is the opposite of the truth. Guard on
`"def export_profile" not in t`. And **assert the replacement differs from the
anchor** (`assert repl != anchor`) — a mutation that is textually a no-op
applies cleanly, reports green, and is counted as a survivor, which is the
LWSM-1155 failure reached from a third direction. Both are one line, and both
fire before anything runs. **The anchor itself is the third case and it is
self-announcing**: prose here is hard-wrapped at ~70 columns, so an anchor
pasted as one logical sentence matches zero times. That one is safe — a zero
count stops the run — which is exactly why the two above are worth writing
down and it is not.

**Trap: a scanner fixture cannot tell you what a matcher does to files nobody
wrote for it — the author's own sibling projects can.** `/mnt/Games/Scripts/Linux`
holds the real population this app scans: 7 projects across all five launcher
kinds, detected live by `scanner.scan([root], units=FakeUnits({}))` in about a
second. **Diff the verdicts across a change** — dump `name/kind/port/source` per
project before and after, and read every line that moved. On LWSM-1155 exactly
one moved, and that is the evidence the change was surgical; no test count can
say that. Then **read every hit the new matcher produces over those same files**:
that pass found three defects no fixture had asked for, including `\bimport\b`
matching inside `not-an-import` (a `-` is a word boundary, so a presence test
fires on any line carrying the word beside a quoted relative path) and a
`from ..up import x` whose stripped dots became a **root-level `up.py`** — not a
refusal but a *different file*, read and believed.
**`tests/scanner_fixtures.py` is the regression corpus and is a different tool**:
it locks what we already know, and by construction contains only hazards someone
thought of. The live tree is the only thing here that answers *what else did this
match?* — it is also the only source for a magnitude, and it is where
`MAX_IMPORT_HOPS = 8` came from (a real launcher's three relative imports).
**Read-only and someone else's**, so never write to it, and expect its contents
to drift — quote a measured number with its date, as the traps above do.

**Trap: `ruff format` formats fenced ` ```python ` blocks inside
Markdown**, and `local-ci.sh` runs it over `.`. A spec with code
blocks fails the gate until they are ruff-formatted. Run
`uv run ruff format docs/specs/<file>.md` after writing one.

**Trap: an exception escaping `QRunnable.run()` is swallowed by
PySide6.** Verified against the pinned 6.11.1 on 2026-08-06: the
traceback prints to stderr, the process survives at exit 0, and **no
signal is emitted** — so any state the task was meant to clear stays
set. This is what makes an unhandled probe error freeze the poll loop
permanently rather than crash (LWSM-1069). Any `run()` body needs a
catch-all that still reports, not just the exception it expects.

**Trap: `setAccessibleName("")` does not hide a widget from the
accessibility tree.** `QAccessibleDisplay` falls back to
`QLabel::text()` when the accessible name is empty, so a decorative
label is still announced — verified by querying the live interface,
which exposes the glyph as a named child (LWSM-1071). To exclude
something from a screen reader, paint it or merge it into a labelled
sibling; do not blank its name. **Assert against the AT tree's
children**, not only the parent's accessible name, or the test cannot
see this.

**Trap: a stale `.pyc` can make a green run report on code that is not
on disk.** Python's default bytecode invalidation compares only the source's
**mtime and size**, so a same-second edit-and-revert whose replacement text is
the same byte length leaves the stale bytecode looking valid. Observed live on
2026-08-06: a constant read `400` from an import while the file, `git status`
and `git show HEAD` all said `120`; clearing `__pycache__` restored it. Clean
tree, empty diff, passing suite — nothing visible is wrong. `local-ci.sh` now
exports `PYTHONDONTWRITEBYTECODE=1` so the gate can never trust a `.pyc`
(LWSM-1110); **do the same (`PYTHONDONTWRITEBYTECODE=1 uv run pytest`) or clear
`__pycache__` before believing any ad-hoc measurement**, because the gate's
guard does not cover a bare `pytest` you run yourself.

**Trap: monkeypatching a Qt virtual method after the widget exists does
nothing.** PySide6 decides whether a Python override exists when the object is
*constructed*, so `monkeypatch.setattr(ProjectRow, "paintEvent", spy)` on an
already-built row is never called and the test silently measures nothing. Two
routes that do work: substitute a subclass for the *name the code constructs*
(`monkeypatch.setattr(mainwindow, "ProjectRow", CountingRow)`) **before** the
window is built, or — for a method you merely *call* rather than override, like
`update()` — set the spy on the instance, since `ProjectRow` is a Python class
and `self.update()` finds the instance attribute first. Hit on 2026-08-07 while
writing LWSM-1109's repaint test.

**Trap: a Qt CONTAINER does not carry the property its children carry, and
`QDialogButtonBox` is the case that bites.** Its own `focusPolicy()` is
`NoFocus` while the Ok and Cancel buttons inside it are focusable, so an
accessibility test that asks the box reports the two most important controls in
a dialog as keyboard-unreachable. Measured 2026-08-21 on LWSM-1018's first run.
Ask `box.button(QDialogButtonBox.StandardButton.Ok)`, not the box. The general
form is worth more than the instance: **when asserting a property for
accessibility, assert it on the widget that actually receives the
interaction** — the same lesson as the `setAccessibleName("")` trap above,
where the answer was also to read the AT tree's children rather than the
parent.

**Trap: a Qt object held only through an inlined attribute access is deleted
mid-test.** `box = getattr(build(qtbot), "_poll")` drops the last Python
reference to the dialog as the expression ends, PySide destroys the C++ object,
and the next call on `box` raises `RuntimeError: Internal C++ object already
deleted` — which reads as a bug in the code under test rather than in the test.
`qtbot.addWidget` does **not** save you: it registers the widget for cleanup,
not for ownership. Bind the parent to a name and keep it alive for the whole
test. Hit 2026-08-21 on LWSM-1018.

**Trap: `QCoreApplication.installTranslator` only broadcasts once the event
loop is running**, because it is gated on `is_app_running`. With no `exec()`,
no `LanguageChange` is posted anywhere and a translator test sees nothing
happen. Worse, and unexplained after four probes on 2026-08-07: with the loop
running and the window the only registered top-level widget, `installTranslator`
returned `True` and Qt still did **not** post the event to `MainWindow`, while a
bare `QMainWindow` in the same shape did receive it. So a language test must
send `QEvent.Type.LanguageChange` by hand and say what it therefore does not
prove — see `test_a_translator_installed_later_reaches_an_existing_row`.

**Trap: `pathlib` metadata calls raise on a directory you cannot enter.**
`Path.exists()`, `is_symlink()`, `is_file()` and `is_dir()` swallow only
`ENOENT / ENOTDIR / EBADF / ELOOP` (`_IGNORED_ERRNOS` in
`/usr/lib64/python3.13/pathlib/_abc.py`). **`EACCES` and `ENAMETOOLONG` are
re-raised** — this is not the older behaviour where `exists()` returned `False`
for anything it could not stat, and code written against that memory is wrong
on 3.13. Found 2026-08-12: four such calls in `scanner.py` sat outside any
handler, and one `chmod 000` directory in a scan root returned **0 of 20**
healthy projects. **This is the fourth shape of the same class** — a
non-`OSError`-shaped, or unguarded-`OSError`, exception escaping a per-item
loop and taking the whole batch with it, after `{"dependencies": 5}` →
`TypeError`, a non-total `properties()` → `KeyError`, and a NUL byte →
`ValueError`. Three earlier fixes each closed one instance and none closed the
class. **When a loop processes untrusted items, contain per item and prove it
with a hostile fixture**; do not add a fifth guard to a fifth call site.

**Trap: a suite can be 370-green and still not hold its own contract.** 81
mutants against `scanner.py` on 2026-08-12: 47 red, **34 green**. Three clauses
the spec calls load-bearing were correct in the code and protected by nothing —
`_BudgetExpired` not subclassing `OSError` (under which a timed-out scan
reports `timed_out=False` and claims completeness), the `package.json`
dependency-block scope, and rule 1's execute-bit precondition, whose line never
executed in any test. **Coverage found what reading did not**: `scanner.py:943`,
`:295`, `:326`, `:904` and `:1213` were all in the miss list, and the last is
the *per-candidate* half of a deadline whose per-line half does all the work.
Before believing an invariant is held, mutate it — and check the line runs at
all.

**Trap: a supervisor test that fails before its own `stop()` leaves a real
process running on the developer's machine.** `Supervisor.close()` deliberately
does **not** signal anything — ADR-0003 leaves servers running on manager exit —
so a fixture that only calls `close()` is correct for the app and wrong for a
test. Found 2026-08-14: five orphans (`/bin/sh ./start.sh`, `child.py`) survived
from two runs where an intermediate version of a test failed mid-way, and they
were still holding their ports **2.5 hours and ~85 test runs later**, reparented
to pid 1 with their pytest tmpdirs already deleted. **A supervisor fixture must
stop everything it started before closing** — `for path in sup.running():
sup.stop(path, grace=0.5)` in a `finally`, which is what `tests/test_supervisor.py`
now does. Verify with `pgrep -af "start\.sh|child\.py"` after a run; the count
before and after a full suite must be equal. **Measured 2026-08-24: it is
not** — `test_a_live_child_has_not_exited` and `test_a_lowered_log_cap_rotates`
leave one `sleep 30` each, every run. Filed as LWSM-1189 rather than fixed
inside an unrelated item.

**Trap: stopping a child that has not finished STARTING leaks its grandchild,
and `stop()` reports success.** `killpg` sweeps the group as it stands at that
instant, so a server the launcher forks a microsecond later never joins the
sweep — it is reparented to init and outlives the run, while `StopOutcome`
comes back clean and the test passes. Measured 2026-08-24 on LWSM-1167: one
orphan per run from a test that called `stop()` on the line after `start()`.
**The code is not at fault and changing it would be wrong** — the real app
polls before it offers a Stop button, so it never asks this. **A test must wait
for the launcher to signal that it has spawned**, which means a launcher that
backgrounds the real process FIRST and touches a file second (`await_ready` in
`test_supervisor.py`), so the file existing proves the grandchild exists. A
bare sleep only makes the race less likely, and a *shorter* sleep in the
launcher is worse than useless: the orphan then expires on its own and the
`pgrep` check goes quiet while the defect stands.

**Trap: a one-row fixture cannot see a per-row bug.** Hit on 2026-08-14
mutation-testing LWSM-1016. Every window fixture in `test_mainwindow.py` built
**one** project, so a `lambda` closing over the loop variable — which makes
every row's buttons drive the *last* project in the list — passed the whole
suite. Four of six mutants survived that first pass and each was a genuine gap:
the closure, no test reaching the two overlay states at all, a mutation that
had not applied cleanly, and one that could not be caught because the code was
equivalent. **When a widget is created per item, at least one fixture must have
two of them**, and the assertion must name which one it expects.

**Trap: `psutil.wait_procs` reaps a process that is your own child.**
It calls `Process.wait()`, which for a direct child is `os.waitpid` — so
waiting on the stop set collects the managed child's status mid-sequence,
frees its PID for reuse, and `Popen.wait()` afterwards returns `0` instead
of the real exit code (`Popen._try_wait` swallows the `ChildProcessError`
and reports success). ADR-0003 forbids reaping until the sequence ends
precisely because that PID is in use as a process-group id. `supervisor.py`
polls `is_running() and status() != ZOMBIE` instead — a zombie is unreaped,
which is exactly the state that keeps the PID reserved.

**Trap: a "we did not reap too early" test is vacuous against a child that
ignores SIGTERM.** Hit on 2026-08-14 while mutation-testing LWSM-1009. The
test asserted `Popen.returncode` stayed `None` through the wait loop; with a
launcher holding `trap '' TERM`, a premature `poll()` finds the child still
running and reads `None` anyway, so the assertion held whether or not the rule
did — the mutant survived. **The launcher must die *during* the window the
property covers.** Same family as the § T9 note above: eleven of twelve
mutants died on the first pass and the twelfth was the one that mattered.

**Trap: a method with no production caller looks exactly like a working one,
and its own unit test is what hides it.** `Supervisor.rotate_if_needed`
implemented `design.md § Observability`'s "capped at 5 MB with one rotation"
correctly and was called by **nothing** outside `tests/test_supervisor.py` — so
the cap was green, documented in two places, and absent from the shipped build
(LWSM-1136, found 2026-08-15, fixed 2026-08-19). A chatty server appended to an
`O_APPEND` descriptor until the disk filled. **The test could not have caught
it**, because a test that invokes the mechanism directly asserts the mechanism
and never the wiring — and green is what you were expecting either way. **When
a method's whole value is being CALLED from somewhere, the test must drive that
caller**, not the method: LWSM-1136's replacement drives `poll_once` against a
real `Supervisor` and a real child. And `find_caller` on the symbol is the
cheapest way to ask; one caller, in a test file, is the tell. Same family as
the `semgrep` and stale-`.pyc` notes above — a mechanism that ran nothing looks
exactly like a mechanism that found nothing to do.

**Trap: a green test can be holding the defect in place, and it reads exactly
like coverage.** Two shapes, both measured here. LWSM-1162's escaping-symlink
refusal was unreachable from `start()`, and a test asserted precisely that, by
name, with a docstring explaining why it was right — fixing the code turned a
green test red, which is the only reason anyone looked. LWSM-1184's was
stronger, because nothing was wrong with the test: `project-e` pinned "the port
is two hops out, and exactly one hop is followed" as **an honest limit rather
than a bug**, and that limit was the thing the user filed as the defect.
**When a change reddens a pre-existing test, read what the test CLAIMS before
assuming the change is wrong** — a fixture can encode a limit that has since
stopped being one. Then say so where it is visible: the fixture moves, the
reason moves with it, and something narrower takes its place holding whatever
bound is left (`project-e-deep`). Silently editing a fixture to go green and
silently backing out a correct change are the same mistake from opposite
sides. The inverse of the LWSM-1136 trap above — there a test asserted a
mechanism nothing called, here one asserted a mechanism that was no longer
wanted.

**Trap: a fold-in bullet's stated CAUSE is a reading, not a measurement, and it
has now been wrong six times.** LWSM-1184 was filed as "the launcher uses an
ordinary import rather than the relative form the walk follows" — and
`_import_specifiers` already resolved the dotless form; the walk was simply
never wired into the shell launcher's hop. LWSM-1168's supervisor half
reproduced exactly as filed while its UI half named the wrong branch entirely.
**Reproduce before designing, and prefer an instrument to an argument.** Two
that pay for themselves in one run here: patch `scanner._open_source` to
record every path a live scan opens, which answers "where did it stop?"
outright; and diff live-tree verdicts across the change, which is the only
thing that catches a SECOND project with the same defect (LWSM-1190's
MAME_Curator) or proves a change surgical. Neither is expensive. Both have
overturned a bullet the same session it was read.

**Trap: a concurrency test that issues two calls back to back proves nothing
about a check-then-act.** Python serialises the two threads on the GIL often
enough that the loser arrives after the winner has finished, so the broken code
passes. **The first call has to be HELD OPEN inside the window** — which means
knowing where the window is: for `Supervisor.start` (LWSM-1137) it is between
the lock being released and the registry insert, so the first start is parked
inside the trust gate by patching `trust.is_confirmed`. Assert the outcomes,
not the timing. The same shape applies to `stop()` (LWSM-1138), where the two
overlapping calls come free from the stop pool's own `max_workers=4` and the
assertion belongs on the **descriptor** rather than on the `StopOutcome` — two
plausible-looking outcomes is exactly what the broken version returned.

**Trap: to prove an fd-reuse hazard, make the reuse HAPPEN — a test that only
asserts the fix's shape proves nothing.** LWSM-1169's two tests run a real
`stop()` from inside the rotation's window, then `os.open()` a sentinel-filled
bystander file: lowest-free-fd means it takes the number `stop()` just freed,
and the pre-fix code truncates that bystander to zero. **Assert the steal
happened** (`stolen == managed.log_fd`) or the test passes for a reason
unrelated to the defect. Where the fix holds a lock across the window, the
`stop()` must run on its own thread with a BOUNDED join, or the test deadlocks
instead of failing. Same family as the held-open note above — the window has to
be entered, never raced for.

**Trap: a fixture set that only exercises one branch of a four-way split.**
Every `start()` test in `test_supervisor.py` used `("./start.sh",)`, so the one
launcher kind that works was the only one tested — and `_launcher_path` refusing
`npm`, `python3` and `node` outright survived 494 green tests and shipped as
"success criterion 2 closed end to end" (found 2026-08-15, `FP07`/LWSM-1132).
This is the **one-row-fixture trap one layer up**: there, one row could not see a
per-row bug; here, one launcher kind could not see a per-kind bug. **When code
branches on a closed set — launcher kinds, states, schema versions — at least
one fixture must exist per member, and a test that names the branch must say
which member it drives.** The same pass found no fixture with `port=None`, which
is what hid an overlay that can never settle.

**Trap: `semgrep` silently excludes test directories, and its zero has been read
as whole-tree on five closes.** It ships a default ignore list covering
`tests/`, so `semgrep --config p/security-audit src tests` scanned **11 files,
all under `src/`** (measured 2026-08-15). Nothing in the output says `tests/` was
skipped. Report semgrep's result as a statement about `src/` only, or pass an
explicit file list. Same family as the `actionlint`/`yamllint` shared-flag bug
and the stale `.pyc`: **a tool that analysed nothing looks exactly like a tool
that found nothing.**

**Trap: an exit status can report the TRANSPORT and not the operation.**
Measured against real KWin on 2026-08-25 (LWSM-1170): `dbus-send` exits 1 with
`ServiceUnknown` on stderr when nothing owns the destination — and exits **0**
for a `loadScript` naming a file that does not exist, and for an `unloadScript`
of a name never registered. So the status says the call landed and nothing
more, and a check written as "did the load succeed?" asks a question the tool
never answers. **Measure what a nonzero status actually means before building a
check on it**, and say in the code what it does not cover. Third costume of the
family above: a call that did nothing looks exactly like a call that found
nothing to do.

**Trap: `.editorconfig`'s blanket `[*]` section is not a declared shell style**,
so `shfmt` has no config to run against here and must be reported as skipped
rather than run against its own tab default — which would diff every 4-space
shell file in the project as malformed.

**Trap: `subprocess.Popen` resolves a bare `argv[0]` against the PASSED
`env`'s `PATH`, not the parent's.** Verified 2026-08-17. So
`build_child_env`'s allowlist is load-bearing for *launching*, not only for
keeping secrets out of the child: drop `PATH` from `ENV_ALLOWLIST` and every
`npm` / `node` / `python3` launcher stops resolving — while the shell kind,
whose `argv[0]` is `./start.sh`, keeps working. That is the same
one-branch-in-four blind spot LWSM-1132 shipped behind, so a change to the
allowlist must be tested against a fixture per launcher kind and not just
against `./start.sh`.

**Trap: under Wayland a client can SET its window position and can never READ
one — and the two look like one feature.** ADR-0007 treated "Wayland discards
the position" as a *restore* problem that a KWin script closes. It is also a
*capture* problem that nothing closes: Wayland gives a client no global
coordinates, so Qt answers 0,0 forever. Measured 2026-08-21 — KWin reported
the app's window at 640,480 while Qt reported 0,0, and **0,0 is a plausible
position rather than an error**, so it was written to `settings.json` as though
the user had put the window in the corner. This is the deeper reason
`saveGeometry()`/`restoreGeometry()` loses position there, and why KDE's own
apps save size and let KWin place. So a Wayland session records size and
maximised state and **leaves the stored coordinates alone**; a position
recorded under X11 or typed in by hand is still restored there. Position and
size are therefore stored and passed as **separate pairs, never one
rectangle** — joined, the unknowable half takes the knowable half with it.

**Trap: three things about the KWin placement path were settled by measuring,
and each had a plausible wrong answer that reasoning reached first.** All
against real KWin, Plasma 6 Wayland, 2026-08-21, and all invisible to the test
suite because the tests substitute a stand-in for the compositor that honours
whatever it is handed whenever it is handed it. **The delay:** ADR-0007's "one
event-loop tick after the window is shown" fails outright; 50 ms works, the
first `Expose` alone still fails, and `Expose` **plus one tick** worked 5/5 —
so the trigger is that condition, not a number. **The size:** KWin's geometry
write is authoritative, so a script that preserves the current size by reading
`c.frameGeometry.width` back pins the window at whatever KWin currently
believes — a 700x500 window came back at its undecorated minimum of 239x216
with the position exact, and swapping the order does not help because it is
not a race. **The decoration:** converting a client size to a frame size in
the app sends 0 for the margins, because the window is not decorated yet when
placement runs; `c.clientGeometry` inside the script is where the answer is.
**The general lesson is the one ADR-0007 already states and this proved twice
over: for anything the compositor owns, a green suite is not evidence — run
the app and ask KWin where the window went.** A KWin script's `print()` reaches
`journalctl --user -u plasma-kwin_wayland`, which is how all of this was read.

**Trap: `setToolTip("")` does not remove a `QAction`'s tooltip.** Qt falls
back to the action's own **text**, so an entry meant to carry an explanation
only when disabled reports its label the rest of the time — and a test
asserting `toolTip() == ""` fails against correct code. Exactly the
`setAccessibleName("")` trap above in a second costume: **an empty string is
not an absent value in Qt.** Assert what is actually there.

**Trap: a default argument bound to a module function cannot be monkeypatched.**
`def f(which=shutil.which)` captures the function object when `f` is *defined*,
so `monkeypatch.setattr(shutil, "which", ...)` never reaches it and the test
silently measures the developer's real machine. Cost a cycle on LWSM-1033 and
then nearly cost a second one in `MainWindow.__init__`, where the same shape
decided whether a `build_window` test could keep its hands off the live
compositor. **Default the parameter to `None` and resolve it in the body.**

**Trap: `git checkout <file>` on work that is not committed yet destroys it.**
Used to revert a hand-applied mutant mid-session on 2026-08-21, it reverted the
file to HEAD and took every uncommitted LWSM-1033 edit in `mainwindow.py` with
it — about an hour's work, recovered only because it was still in the session's
context. The mutation harness itself was never at risk: it holds the original
text in memory and writes it back in a `finally`. **Restore from a copy you
made, never from git, while the work is uncommitted** — and the cheaper habit
is to commit before starting a mutation run at all.

**Trap: `QIcon.fromTheme` returns a null icon under `QT_QPA_PLATFORM=offscreen`.**
The icon theme search paths are populated by the *platform theme plugin*, so
under `offscreen` `QIcon.themeSearchPaths()` is `[':/icons']` and
`themeName()` is empty — every theme lookup misses, including one whose file
is definitely installed. Measured 2026-08-18 while shipping LWSM-1142: the
same lookup returned a 128px SVG under the real Wayland session and null under
`offscreen`. **`conftest.py` sets `offscreen` when unset, so any test
asserting an icon resolves by theme name fails in the suite and in CI for a
reason that says nothing about the icon.** Assert the file is installed where
the theme expects it, or inject the icon; do not assert `fromTheme`.

**Trap: an installer that writes into `~/.local/share/icons/hicolor` can hide
every OTHER application's icons.** That directory is shared by every app that
installs a per-user icon, and it normally has no `index.theme` and no
`icon-theme.cache`. Generating a cache there does not merely speed lookup up —
once a cache exists it is treated as authoritative for that directory, so
anything it fails to list stops resolving. Measured 2026-08-18 (LWSM-1143):
one `gtk-update-icon-cache -f` produced a 1,932-byte cache over a tree of 90
icons and about seventeen of the user's pinned launchers went blank until it
was deleted and plasmashell restarted. **The `|| true` on that line gave false
comfort — it guards against the command *failing*, and the command succeeded;
succeeding was the damage.** Every check passed: `desktop-file-validate`,
`shellcheck`, the icon resolved, the entry launched. **When a step writes into
a directory shared with other software, the verification has to ask what
happened to the other software, not only to us.**

**Trap: two runs executing the same STEPS with different TOOLS is not one
gate.** `local-ci.sh` has said "the single source of truth for CI" since P01
and it was true of the step list and false of everything else. On 2026-08-18
local shellcheck 0.11.0 passed `scripts/*.sh` while the runner's apt shipped
0.9, which reports SC2015 on `command -v` guards that 0.11 accepts — **eight
consecutive red pushes against a green local run**, and four of those were
pushed after the first failure because nobody read the email. Pins now live in
`scripts/ci-tools.env`, both sides read it, and the gate reports TOOL DRIFT.
**The second lesson is smaller and cost its own red build**: the first thing
the new check found was `go install …@v1.7.12` reporting `v1.7.12` against a
release binary's `1.7.12` — the same version, spelled differently. **A version
comparison must normalise before it compares**, or its first live finding is a
false alarm and the whole check stops being believed. And **when the gate
itself changes, the only proof is a push** — both defects were found by GitHub,
not by reasoning about the YAML.

**Trap: a geometry test can pass against a window that never grows.** Three
of LWSM-1149's first-draft tests survived deleting the entire
`_apply_default_geometry` mechanism (2026-08-18): with the scroll area in
place, Qt's own default size happened to satisfy "a short list needs no
scrolling", "a long list does not grow the window" and "the minimum does not
clip a column". The second is the pure vacuous form — a window that ignores
its content passes it by never growing at all. **The fix is to pin the two
cases against each other in ONE test** (3 rows shorter than 8, 8 equal to 48),
so neither half can hold on its own. The third was worse than weak and was
dropped: the columns are fixed-width, so Qt's layout minimum already forbids
clipping one and the assertion could not fail. Same family as the § T9 note
above and the SIGTERM-ignoring launcher — an assertion that holds whether or
not the rule does. **Mutate the mechanism out before believing a geometry
test, and say which mutant each test dies on.**

**Trap: a widget's SIZE depends on the runner's default font, so a pixel-floor
test can pass locally and fail in CI.** `design-accessibility.md § Accessibility` puts a
24x24 floor under every clickable target. Qt's style derives a button's height
from the font, and on this machine that gave **25 px** — clearing the floor by
one pixel — while the GitHub runner's smaller default font gave **22**. So the
floor was breached for every user with a small system font, the suite could not
see it, and CI was the only thing that could (found 2026-08-19, LWSM-1032).
**A floor belongs in the SOURCE, not only in the assertion** —
`setMinimumHeight(MIN_TARGET_PX)`, a minimum so it still grows with the
text-size control. And **parametrise the test over the font** rather than
trusting the ambient one: the 6 pt case fails on a build with no explicit floor
whatever machine it runs on, while the ambient case passes on this one either
way. Same family as the TOOL DRIFT note above — two machines running the same
steps with different inputs is not one gate.

**Trap: a colour solved for CONTRAST alone converges on white.** LWSM-1031
derives each palette's state tokens by walking a fixed hue's lightness until it
clears § T8's floor. The first draft walked from the far end of the range and
stopped at the first pass, which on a dark palette is near-white for *every*
hue — so all eight state tokens came out `#ffffff`, perfectly legible and
carrying no state information at all. **Every contrast check passed**, because
contrast is exactly what it was solving for. Walk *away* from the surfaces and
stop at the first clear, so the token keeps as much of its hue as the floor
allows; and hold the result to a second property the first cannot imply —
`test_the_state_tokens_are_distinguishable_from_the_body_text`. Same family as
the vacuous geometry test: an assertion that holds whether or not the rule
does, here because the rule as stated was not the rule that was wanted.

**Trap: run analysis tools inside the project venv (`uv run`, or
`uv run --with <tool>`).** Bare `deptry` / `pip-audit` resolve the
*system* Python and report the project's own declared dependencies as
missing — 21 bogus findings on 2026-08-06 against a `pyproject.toml`
that declares them. Same family as `python` not being on PATH: the
output looks authoritative and is about the wrong interpreter.

## Resumption flow — MANDATORY summarise-back

Per the app-workflow skill:

1. **Parallel batch:** read this file + `.claude/workflow.md`
   status header + active-item details (one tool-call batch).
2. Once `Kind` is known from the active item, read the
   matching `docs/standards/<which>.md` (single read).
3. **Summarise back to the user:** "We're on `<ID>` step
   `<N>`, last did `<X>`, next is `<Y>`."
4. Wait for confirm or redirect.

**Never skip step 3.** Catching state-recovery errors before
working is cheaper than corrective rounds later.

## Standards reference

The standards (`coding`, `documentation`, `testing`,
`commits`, `dependencies`) plus `roadmap-format` live in
[`docs/standards/`](docs/standards/) — see its
[README](docs/standards/README.md) for the index, the
closed-loop diagram, and which kinds each governs.
