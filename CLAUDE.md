# LocalWebServerManager — Project instructions for Claude Code

## Session start — MANDATORY summarise-back

1. **Read the roadmap's open items** from the store, not the file:
   `roadmap_query status:"in-progress" mode:"headline_only"`, then the
   release section's intro for the order. With nothing in flight, the first
   unreleased section's intro names what is next. Fetch an active item's
   body by id.
2. **Read the standard matching the item's `Kind`**: the shared file in
   `~/.claude/standards/` plus this project's
   `docs/standards/<name>-overrides.md` ([index](docs/standards/README.md)).
   Read `dependencies-overrides.md` before touching any pin.
3. **Read `docs/specs/<active-id>.md`** if the item has one.
4. **Summarise back**: "We're on `<ID>`, last did `<X>`, next is `<Y>`."
   Wait for confirm or redirect. Never skip this.

Before `check-code` or `review-code`, also read `docs/audit-allowlist.md`.
`check-code` matches its entries through `tools/audit/audit-config.json`;
nothing new is added to it. A new false positive goes in
`.audit_cache/learned-fp.jsonl` (tool findings) or
`.ants_review_falsepos.jsonl` (reviewer claims), and recording it is
`close-findings`' job.

Each job goes through its skill, never by hand (user, 2026-08-03): specs
`/write-spec`, contract reviews `review-contract`, applying review fixes
`close-findings`, source code `/write-code`.

## Review cadence — build first (user, 2026-08-13; revised 2026-09-25)

1. **Default: build it, then correct the spec to match what was built**
   (`/write-spec` Step 8's fold-back). Most work needs no spec.
2. **Spec-first only when code creates durable artifacts** — an on-disk
   format, a wire protocol, anything another item binds to.

Rule 1 cancels no gate: global rule 14 applies as written, with no cap or
finding filter of this project's own (LWSM-1305). Read
[`docs/claude/review-cadence.md`](docs/claude/review-cadence.md) before
arguing for or against rule 1.

**Never silently drift.** When code diverges from its spec, decide which was
wrong and fix that one, never both. Under rule 2, stop and say so. Under
rule 1, note the divergence on the item's bullet and fold it back after the
build — a deliberate departure from `~/.claude/workflow.md` § 7's first row.

**A review of `CLAUDE.md` tells its lanes to read it from disk**: a lane is
briefed with the session-start copy, not the edited one (CFG-0593).

## Before pushing

**Code, tooling or CI changes: `./scripts/local-ci.sh`. Docs-only:
`./scripts/local-ci.sh --docs`.** A `pre-push` hook enforces both; enable
it once per clone with `git config core.hooksPath .githooks`. Read
[`docs/claude/ci-gate.md`](docs/claude/ci-gate.md) before changing the hook,
the gate, the tool pins or `test_docs.ASSERTED`.

**Escaping the hook is the user's call, never yours** (LWSM-1318).
`LWSM_SKIP_PREPUSH=1` skips the gate but keeps the secrets scan;
`git push --no-verify` skips both. Use one only when the user says so for
that push, and never export the variable.

**Never add a check to `.github/workflows/ci.yml` instead of the script**:
the workflow only calls `local-ci.sh`, so a check added there is one nobody
can run before pushing.

The repo is **public**: push freely (global rule 6).

## Build and test

```bash
uv sync --extra dev            # from the committed uv.lock
./scripts/local-ci.sh          # the whole gate
./scripts/local-ci.sh --fast   # minus the integration tests
./scripts/build-appimage.sh    # AppImage into dist/, smoke-tested; needs podman or docker
```

Python 3.13 + PySide6, `uv`, `pytest` + `pytest-qt`, `ruff`; reasoning in
[`docs/discovery.md § Tech stack`](docs/discovery.md). The app runs each
sibling project's own launcher and never edits sibling source
(`coding-overrides.md` § O3).

**Releases:** read [`docs/claude/release.md`](docs/claude/release.md) first.

## Commits

Subject `<ID>: <description>` with the roadmap item's `LWSM-NNNN`
([overrides](docs/standards/commits-overrides.md)). Phases are retired: no
new `P##`/`FP##`/`DS##`/`DOC##`/`R##` ids and no `<ID>-complete` tags; a
commit with no item follows `commits.md` § 1.2. History:
[`docs/history/claude-md.md`](docs/history/claude-md.md).

## Public repository

- **Everything in this tree is world-readable**, including `ROADMAP.md`
  and `docs/specs/`. Author-private facts go only in the gitignored
  `docs/private/`.
- **`LICENSE` names Anthony Schemel**; keep it a legal person, not the
  project name.

## The roadmap store

`ROADMAP.md` is rendered from the Ants store; edit it through `roadmap_log`,
never by hand.

- **Never run `roadmap_migrate` here**: already migrated, and the store has
  no undo.
- **A calibrated-down finding is closed as a finding** (user, 2026-09-03):
  flip it shipped, say no code changed, and name the item that owns the work.
- **`roadmap_log` traps:** `set_intro` leaves the old table (delete and
  recreate the section, rebuild with `bundle_row`); `amend_field
  field:"section"` naming the current section moves nothing (move away and
  back); `delete_section` refuses a parent with sub-sections (delete those
  first).

## Code

Read a module's entry in [`docs/claude/module-map.md`](docs/claude/module-map.md)
before changing it. A core module may import `QtCore` but never `QtWidgets`
(`coding-overrides.md` § O1), enforced by `tests/test_layering.py`.

Read the matching entries in [`docs/claude/traps.md`](docs/claude/traps.md)
before writing a test, a mutation run, or code touching Qt, a subprocess or
the compositor. A test docstring citing a "`CLAUDE.md` trap" means that file.

## Hard rule: never kill by pattern

**Never find or kill a process by command-line pattern.** Other sessions and
the user's own copy of the app run here; `pkill -f` has killed both. Select
by PID and confirm it is yours first — its cwd, or its `/proc/<pid>/environ`
holding the test's private `XDG_RUNTIME_DIR` (LWSM-1287).
