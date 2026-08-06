# LocalWebServerManager — Workflow state

## §1. Status header

| Field | Value |
|-------|-------|
| **Project phase** | P01 — Bootstrap (next); Phases A–D closed 2026-08-03 |
| **Active item ID** | (none — pre-code phases produce documents, not roadmap items) |
| **Active step** | (n/a until P01) |
| **Blocked on** | — |
| **Last update** | 2026-08-06 (`design.md` re-gated — loops 3 and 4, 54 findings fixed; the 2026-08-03 standing risk is closed) |
| **Next gate** | P02 — vertical slice, now unblocked: `design.md` is gated and safe to build UI from. P01 stays open until FP01's six 🚧 items land in P05/P06 |
| **Convergence checkpoint** | 5 (consecutive `FP##` items immediately preceding any ✅-`implement`-Kind close in the active release block — see `~/.claude/commands/close-phase.md § 5a-6`) |
| **Debt-sweep phase threshold** | 5 (auto-prompt for `/debt-sweep` after this many phases without one) |
| **Last debt sweep** | (none yet) |
| **Repo visibility** | **PUBLIC** (`github.com/milnet01/LocalWebServerManager`, 2026-08-03) — free CI minutes, so pushes need no batching gate |

### Step progress

While an item is active, Claude marks the current step 🚧;
completed steps flip to ✅. Resets to all ⬜ when a new item
becomes active.

1. ⬜ Verify spec (research first if non-trivial)
2. ⬜ Verify dependencies on the roadmap DAG
3. ⬜ Write failing tests
4. ⬜ Implement until tests pass
5. ⬜ Run `/audit` (read `docs/audit-allowlist.md` first)
6. ⬜ Run `/code-quality-review` (same allowlist read)
7. ⬜ Fold actionable findings → new FP## roadmap item
8. ⬜ Update CHANGELOG / ROADMAP / journal
9. ⬜ Commit, tag `<ID>-complete`, ask user about push

### Active item details

(filled in once Phase A → P01 hands over an active item)

```
Item: <ID>
Spec: docs/specs/<ID>.md
Branch: main (no feature branch yet)
Sub-findings:
  - 📋 ...
  - 📋 ...
Tests: <count> passing, <count> failing
```

## §2. Workflow rules

The canonical rules — phases A–D, the per-phase 9-step loop,
ID scheme, triage table, fold-into-roadmap pattern,
false-positive learning loop, drift handling, Definition of
Done — live in
`~/.claude/skills/app-workflow/SKILL.md`.
Skills don't auto-load from filesystem presence — they fire
on description-match against your message. To engage the
workflow in a session, mention any of: phase / audit / drift
/ fix-pass / "where were we" / "resume" / "continue work" /
this `workflow.md` file by name. The project's `CLAUDE.md`
(loaded automatically on session start) reminds you of this
on every resume.

**Hard rule kept inline (most-load-bearing):** never silently
drift. If code being written diverges from the spec, stop and
surface. Either the spec was wrong (update spec → re-audit
affected sections → resume) or the code was wrong (fix code,
no spec change). Never both papered-over.

To refresh this file from the (upgraded) skill template, copy
`~/.claude/skills/app-workflow/templates/.claude/workflow.md`
over this file — preserve §1 (status header) and §3 (session
journal); §2 is the only part that changes.

## §3. Session journal

Append-only. Newest at the top.

### 2026-08-06 — `design.md` re-gated; the standing risk is closed

**The risk carried since 2026-08-03 is discharged.** Two more
cold-eyes loops (3 and 4 in the document's own log) ran over the
post-approval material — Detection rules' two Scanner subsections,
Custom project actions, Look and feel, Accessibility, ADR-0006/0007
— which until today only its author had read. **54 verified findings,
all fixed**; 2 dismissed. The ADR-0004 amendment rode along: bind
time past the old 15 s deadline now has two measured projects behind
it (~40 s and ~45 s), not one lucky catch.

**Loop 3's three biggest, each found independently by both lanes:**
six state tokens for ADR-0004's seven states (nothing could render
`running (foreign)`, and T7/T8 parametrise over the list, so the gap
would have surfaced as a missing test case rather than a visible
error); the two Scanner subsections nested under *Custom project
actions*, so every hardening rule was invisible from the section an
LWSM-1006 implementer reads; and a theme layer whose palette values
lived in a sibling project outside this public repo, which no one
else could build.

**Loop 4 is the more instructive one.** About 16 of its 27 findings
were **collateral from loop 3's own fixes** — a 7:1 contrast floor
promised against a test that did not carry it, a `ThemeManager` added
to the component list but not the diagram, a trust posture that cited
ADR-0007 as authority while stating the opposite of what ADR-0007
says. Collateral outnumbering draft defects on the first split is the
documented signal to **sweep rather than dispatch again**, so loop 4
closed with a blast-radius pass across `ROADMAP.md`, `discovery.md`,
ADR-0006 and `testing.md § T8` instead of a loop 5.

Its best find was a draft defect neither earlier loop reached:
**"effective port" is the input to every launch, stop and probe path
and was never defined.** Four fields can supply it and precedence was
stated for only one pair. It now has an explicit chain, and the
user-override-outranks-observation call is written down with its
reason — the reverse would make an overridden port impossible to
change.

**Two things the sweep caught that had nothing to do with design.md:**
real sibling project names had survived the LWSM-1045 scrub in
`ROADMAP.md` (including a name-plus-port pair, the exact target-list
shape), `discovery.md` and ADR-0006 — all now anonymised, tree
verified clean. And `design.md` claimed ADRs are "never edited after
acceptance" while ADR-0004 carries a dated amendment; the rule now
says what the project actually does.

**Left for the user:** whether ADR-0007 may keep depending on
`OneUp`/`finbreak`/`SystemManager` source citations that a public repo
cannot resolve. § Look and feel solved the equivalent problem by
transcribing values in; ADR-0007 has no such plan for its technique
citations.

### 2026-08-06 — Port-contract campaign complete; design.md re-gate is next

**All six adopters are done.** project-e (`CL-0056` / `1bb017c`)
was the last; project-f remains a deliberate permanent
non-adopter. Every adoption was verified with real processes, not
by reading. `docs/private/inventory.md` carries the per-project
evidence.

The campaign found three real bugs in sibling projects that had
nothing to do with ports, each surfaced by verifying rather than
trusting: a dead settings tier in project-d (closed by them the
same day), and in project-e a tray that **has never once appeared
from source** — its venv is built without system site-packages so
`gi` is invisible, and the graceful fallback hid it at INFO. That
one turned out wider than first diagnosed: a locally built
AppImage has it too, because the GI stack is installed only in
that project's CI release workflow. The one pre-release check
that should have caught it is structurally blind to it.

**Two prompt-template lessons** went back into
`docs/private/port-contract-prompt.md` for any future adopter:
wait for the port and never for a duration (a fixed `sleep`
produced a false negative on a project that takes ~45 s to bind),
and a frozen windowed build can have `sys.stdout` as `None`, so
the rule-5 URL print needs a guard or it turns the error path
into a crash.

**Agreed next action: re-gate `docs/design.md`** — the standing
risk recorded in the 2026-08-03 entry below is now the blocker
for P02. Four sections (Detection rules, Custom project actions,
Look and feel, Accessibility) and ADR-0006/0007 have only ever
been read by their author. **The one-line ADR-0004 amendment
rides along in the same pass**: "slowness is not failure" now has
two independently measured projects behind it (~40 s and ~45 s to
bind), not one lucky catch — recorded here because it is a
decision taken in conversation and it would otherwise be lost.

Note for whoever runs it: `design.md` is 817 lines / 39 KB, and
its own loop log ends with the lesson that produced loop 2's best
finding — **tell a reviewer what to check, not what is true.** A
brief that asserts facts gets them trusted.

### 2026-08-03 — P01 built; FP01 contracts landed

P01's code is in and the gate is green (14 tests, ruff, shellcheck,
actionlint, entry-point resolution). The phase is **not closed**:
FP01's six 🚧 items each owe an implementation in P05/P06.

The reviews earned their cost. Static analysis was clean across
every tool; every real finding came from reading. Three defects
were invisible to a green build — a console script naming a module
that did not exist, `get_logger(__name__)` producing
`lwsm.lwsm.<module>`, and an idempotence guard that compared
`abspath` to `resolve()` so a symlinked state dir wrote every line
twice (the test that existed to catch it could not, because
`tmp_path` is never a symlink).

**The security pass was the most valuable hour of the project so
far**, and its top finding was the repo itself: the docs published
a target list of the author's private local services, in all 26
commits. Tree scrubbed; the history is handled by publishing from a
squashed orphan commit.

Six FP01 items were **design** rather than code, so their contracts
landed now — a trust gate before running a discovered launcher,
PID-reuse-safe signalling, an environment allowlist, detection
treated as untrusted input, bounded scanner reads, and
`LWSM_MANAGED` declared security-worthless before the prompt
reaches seven codebases. Each cost an ADR edit today and would have
cost a rewrite after P05.


### 2026-08-03 — Post-gate scope additions (design changed a lot)

Five user requirements landed **after** the Phase B/D review
gates: AppImage + self-contained releases, broader web-server
support, macOS/Windows assessment, tray consolidation
(ADR-0006 + custom actions + systemd support), and appearance +
accessibility (theme layer, ADR-0007 geometry, a11y as a design
input). Roadmap 20 → 31 items; ADRs 5 → 7.

**Standing risk to carry into P01:** `docs/design.md` has gained
four substantial sections (Detection rules rewrite, Custom
project actions, Look and feel, Accessibility) and two ADRs since
the last cold read. The loop log covers loops 1–2; **none of the
post-gate material has been reviewed by anyone but its author.**
Either re-gate `design.md` before P02 starts building UI from it,
or accept that risk knowingly. P01 is build tooling and is not
exposed to it.

Two findings from reading sibling projects rather than assuming,
both of which changed the design:

- `project-a.service` is an **enabled systemd user unit** — the
  detection rules would have spawned a second copy of a server
  systemd already owns. Now a distinct launcher kind (LWSM-1028,
  P04, priority 1).
- OneUp's "doesn't reopen where I left it" bug is the Wayland
  placement limitation, and it is **fixable** — the KWin script
  it already uses for centring can equally place a window at
  remembered coordinates. ADR-0007 does both through one helper.

### 2026-08-03 — Phases C and D

**Phase C** — ROADMAP populated (P01–P09, 24 bullets, full field
set), `coding.md` and `testing.md` given project override
sections, README made honest. `commits.md` and
`documentation.md` were read and needed no project deviation.
Specs for P01/P02 **deliberately skipped** (user decision): their
roadmap bullets already carry checkable acceptance criteria, and
the first real spec is P03's scanner, where the contract is
non-obvious.

**Phase D** — one reviewer over the whole A–C set rather than the
usual fan-out, on token cost. 21 findings, all verified and
fixed **inline** rather than folded into a `DOC01` fix-pass —
a deliberate deviation from the workflow's fold-in pattern,
recorded here because there is no `DOC01` bullet to find later.

It earned its cost twice over. It closed loop 1's missing cold
re-read (finding stranded fix collateral), and it caught **three
wrong rows in the project inventory** — the docs described
project-g as a Vite app on 5173 when its `run.sh` starts a
Python backend on 8080 and already honours `PORT`. Those errors
had propagated into `port-contract-prompt.md`, which was about to
be pasted into seven other codebases.

**Three new requirements from the user**, folded into the
roadmap: publish a self-contained **AppImage** (LWSM-1021, new
P09); support **more kinds of web server** for a wider audience
(LWSM-1023, considered); and **macOS / Windows** builds —
assessed rather than promised (LWSM-1024 blocked on whether macOS
socket enumeration needs elevation; LWSM-1025 recommended against,
since Windows has no process groups and ADR-0003 would need
rewriting).

Next: P01 — Bootstrap.

### 2026-08-03 — Phase B: Design (approved, gate run)

`docs/design.md` + ADR-0002…0005 written and approved. Seven
project states, a 1-second status poll composed from one
socket-table snapshot per tick, launch-via-sibling-script under
`subprocess(start_new_session=True)`, and a registry whose merge
rules never discard user edits.

Rule-14 cold-eyes gate: **one loop**, 2 lanes, 26 verified
findings, all fixed (commit `9b4a853`). The run was capped at one
loop by the user on token cost — **not** by a convergence test.
The fixes are unverified by a second cold read; Phase D is where
that gap closes.

Two decisions recorded this session that outlive it:

- **Subagents are permitted** where they help and are token-
  efficient — reviews especially. Written into `CLAUDE.md`; the
  user noted it as a `/start-app` template update too.
- **Sibling projects adopt the port contract** (ADR-0002) via a
  prompt this project generates, run in each project's own Claude
  Code session. That prompt is not written yet.

Next: Phase C — standards, ROADMAP, first specs.

### 2026-08-03 — Phase A: Discovery (approved)

Scanned `<scan root>/` and found **seven**
server-running sibling projects (inventory table in
`docs/discovery.md § Problem`); two were live at scan time
(project-c:8765, project-a:4321).

Decided: a **PySide6 desktop app** that manages those servers —
auto-scan with a persisted list plus a Rescan button, start /
stop / restart with live status, port-conflict detection and
reassignment, per-project live log panel, open-in-browser, and a
system tray. It launches **each project's own script**; it never
edits sibling source.

Open thread carried into Phase B: several launchers hard-code
their port. User's call — **the siblings get updated to accept
an external port**, driven by a prompt this project supplies to
each project's own Claude Code session. Phase B owes a **port
contract ADR** defining that interface, plus honest degradation
when a project hasn't adopted it.

Public-GitHub optionals activated (`CONTRIBUTING.md`,
`.github/`).

Next: Phase B — `docs/design.md` + ADRs.

### 2026-08-03 — P00 scaffold

Project scaffolded from `~/.claude/skills/app-workflow/templates/`
via `/start-app`. Initial commit `chore: scaffold project from
template (P00)`.

Next: Phase A — Discovery. User says "let's start discovery"
in a fresh Claude Code session in this directory.
