# LocalWebServerManager — Known issues

> **Status:** Empty until first deferral.
> **Bar for entry:** high — only items genuinely blocked by
> an unbuilt dependency, with the dependency named
> explicitly. The
> app-workflow skill (`~/.claude/skills/app-workflow/SKILL.md`, local to the author's machine)'s
> default disposition is to fold every actionable finding
> into a fix-pass; this file is the exception case.

**A second class of entry was created by the user on 2026-08-07:
a finding handed to the phase that owns the code it lands in.**
Until then the only legitimate deferral was a hard dependency on
an unbuilt item. P02's third review pass forced the distinction:
it produced 25 findings against a feature item that had already
generated 28 fix items, and folding all of them again would have
made a single vertical slice cost 54 fixes. The decision was to
close the root causes and the HIGH findings in `FP05` and file
the rest here **against the phase whose implementer will be
reading that code anyway** — a MEDIUM about `alt_base` contrast
is genuinely cheaper to fix in the pass that first paints on
`alt_base` than in a fix-pass three phases earlier.

The bar for this second class is narrower than it sounds, and
the entry must say which it is:

- **Named owner required.** "Later" is not an owner. The entry
  names the roadmap ID whose work touches the same code.
- **It must not be a live user-facing defect.** Anything a user
  can hit today goes in a fix-pass, whatever its severity label.
  Every entry below is either unreachable in the current build or
  bounded to a cost the user does not see.
- **Deferring is not dismissing.** When the owning item starts,
  its implementer reads this file first — the same way `/audit`
  reads the allowlist.


## Format

```markdown
## known-issue-NNN — One-line summary

- **Found by:** <audit / code-quality-review / debt-sweep / user>
  during <phase / context>
- **Why deferred:** depends on roadmap item <ID> "<title>"
  (status: 📋 not started / 🚧 in progress)
- **Will be addressed in:** <ID>
- **Logged:** YYYY-MM-DD
```

When the named dependency lands, the corresponding
known-issue is folded back into the roadmap automatically as
a new fix-pass (per the workflow skill's drift-handling
rules).


## Entries

All fifteen below are the MEDIUM/LOW tail of the 2026-08-07
three-lane review (`FP05` carries the two root causes and the
seven HIGH findings). Each was reproduced by its lane before
being written down; none is reachable as a user-visible defect
in the current build. Owners are named, not implied.

### From the data boundary lane

## known-issue-001 — An accepted record's `name` is stored raw, so an unbounded string reaches the accessible name

- **Found by:** code-quality-review during FP05
- **Class:** handed to owning phase
- **Detail:** `registry.py:256` computes `_quoted(raw_name)` for the
  *rejection* path but `:311` stores `raw_name` on the record, so the
  hardening applies only to records that are rejected. A 300,000-character
  name, one containing newlines, and one containing ANSI escapes all load
  cleanly and reach `setAccessibleName` (`mainwindow.py:288`).
  `setTextFormat(PlainText)` stops markup but not length or control
  characters. Spec § 4.1 accepts `name` as "non-empty `str`" with no bound,
  so the code conforms — the spec is what needs the bound.
- **Why deferred:** not reachable without the user hand-writing a hostile
  entry into their own config file; the fix belongs with the bound on every
  displayed string rather than this one field.
- **Will be addressed in:** P04 (LWSM-1030 — appearance and accessibility
  foundation)
- **Logged:** 2026-08-07

## known-issue-002 — No cap on record count, and `MAX_FILE_BYTES`' stated calibration is ~6× optimistic

- **Found by:** code-quality-review during FP05
- **Class:** handed to owning phase
- **Detail:** the comment at `registry.py:23-26` justifies the 1 MiB cap as
  "a thousand projects is roughly 200 KB". Minimal valid records are far
  denser: 29,743 records fit under the cap and took **11.1 s** to build the
  window (offscreen; a real display is slower).
- **Why deferred:** P03 is what determines how many records a real registry
  holds, and a count cap set before the scanner exists would be a guess.
- **Will be addressed in:** P03 (LWSM-1006 — project discovery)
- **Logged:** 2026-08-07

## known-issue-003 — A pre-existing `app.log` keeps whatever mode it has

- **Found by:** code-quality-review during FP05
- **Class:** handed to owning phase
- **Detail:** `applog.py:55` passes `0o600` to `os.open(..., O_CREAT)`, which
  applies only on creation. `_require_private_regular_file` checks type, link
  count and owner but not mode; a pre-created `0644` log stays `0644`.
- **Why deferred:** `_prepare_state_dir` re-`fchmod`s the containing directory
  to `0700` every run, so the file is unreachable by other users regardless.
  It matters only if the log is copied out or `XDG_STATE_HOME` is pointed at a
  shared location, neither of which the current build does.
- **Will be addressed in:** P09 (LWSM-1019 — settings and session, which is
  when a configurable state location first exists)
- **Logged:** 2026-08-07

## known-issue-004 — `test_refuses_a_device_node` reads the real `/dev/null` on any unprivileged run

- **Found by:** code-quality-review during FP05
- **Class:** handed to owning phase
- **Detail:** `tests/test_registry.py:237-239` creates the node with
  `os.mknod`, which needs `CAP_MKNOD` and raises `PermissionError` as this
  user, so the fallback branch to `Path("/dev/null")` always fires. The
  docstring claims the node "is created under `tmp_path` rather than reading
  the real `/dev/null`" — **so the `testing.md § T1` violation LWSM-1111
  recorded as fixed is still live, behind a branch.** The test still proves
  the char-device refusal; the defect is the false claim. Secondary:
  `except (PermissionError, OSError)` is redundant.
- **Why deferred:** no coverage is lost, and the honest fix is a `skipif` on
  `CAP_MKNOD` — which is the same shape as the root-cause work in LWSM-1113,
  where it can be done once for every test making a claim it cannot keep.
- **Will be addressed in:** LWSM-1113 (FP05 — wiring-test rule)
- **Logged:** 2026-08-07

## known-issue-005 — `MAX_REASON_CHARS`' value is pinned by nothing

- **Found by:** code-quality-review during FP05
- **Class:** handed to owning phase
- **Detail:** after LWSM-1109 every clip assertion is expressed relative to
  `registry.MAX_REASON_CHARS`, so it detects removal of the clip but not
  loosening of it. Changing 120 → 100000 leaves `30 passed`. Spec § 4.1
  states the number as part of the contract.
- **Why deferred:** one-line fix, but it lands naturally with LWSM-1115's
  reason-count cap, which is rewriting the same assertions.
- **Will be addressed in:** LWSM-1115 (FP05 — bound the reason count)
- **Logged:** 2026-08-07
- **RESOLVED 2026-08-07** (with LWSM-1112's sweep, one item later than routed):
  `test_the_shipped_bounds_are_pinned` asserts both `MAX_REASON_CHARS == 120`
  and their product, so raising either has to be justified against the volume
  a status bar and a log line actually absorb. It also pins **`MAX_REASONS`**,
  which LWSM-1115 had just added carrying this exact defect — its assertions
  read `<= MAX_REASONS + 1`, so 100 → 100000 would have passed and restored the
  flood the cap exists to stop. Found by re-reading the routed owners of the
  items this pass closed, which is `coding.md § 1.6` applied to the pass's own
  output.

### From the concurrency lane

## known-issue-006 — A permanently wedged probe produces no signal anywhere

- **Found by:** code-quality-review during FP05
- **Class:** handed to owning phase
- **Detail:** when a probe never returns, `poll_once` returns at the
  `_in_flight` guard (`controller.py:267-271`) on every subsequent tick with
  no log line and no state change; the row renders its last observation
  indefinitely. Measured: 6 s of event loop, 5 ticks skipped, log output the
  empty string, row still reading `running`. Spec § 6 promises the state is
  left "**visibly** stale, rather than wrongly confident" — nothing conveys
  staleness to the user or the log. **The code and the contract disagree; one
  of them is wrong.**
- **Why deferred:** the remedy is a freshness field on `RowView` and a way to
  render it, which is the state model P06 builds. Fixing it now would mean
  designing that field twice.
- **Will be addressed in:** P06 (LWSM-1012 — the full state model)
- **Logged:** 2026-08-07

## known-issue-007 — The shipped `STOP_WAIT_MS` is unpinned and INV-16's budget clause is tautological

- **Found by:** code-quality-review during FP05
- **Class:** handed to owning phase
- **Detail:** both budget tests substitute their own value
  (`tests/test_controller.py:628`, `:641`) and then assert against
  `controller_module.STOP_WAIT_MS`, so INV-16's "returned within
  `STOP_WAIT_MS`" is true for any value. 2000 → 60000 leaves `150 passed`.
  Spec § 4.3 justifies 2000 ms as "~60× headroom" over a 33.4 ms probe, and it
  is a user-visible quit delay.
- **Why deferred:** same shape as known-issue-005 — an assertion on the
  literal, landing with the teardown work.
- **Will be addressed in:** LWSM-1117 (FP05 — bound the abandoned-pool wait)
- **Logged:** 2026-08-07
- **RESOLVED 2026-08-07** (with LWSM-1117, as routed):
  `test_the_shipped_stop_budget_is_pinned` asserts the shipped 2000 and the
  ~60× headroom over the measured 33.4 ms probe that spec § 4.3 justifies it
  with, so an edit has to change the reasoning too. The patching tests are left
  alone deliberately — a test must not wait two real seconds, so the shipped
  value needs its own assertion rather than a rewrite of theirs. Verified: 2000
  → 60000 left the whole suite green before, and reddens exactly this test now.

## known-issue-008 — If `main()` raises, the bounded exit is skipped and the process hangs

- **Found by:** code-quality-review during FP05
- **Class:** handed to owning phase
- **Detail:** `__main__.py:127-128` runs `code = main()` then the bounded
  exit; an exception out of `main()` propagates past the bound while `main()`'s
  own `finally` has already abandoned the pool. Reproduced at **30.14 s** wall.
  Reachability was measured and is narrow: against the pinned PySide6 6.11.1
  both obvious triggers are swallowed — an exception in a queued slot and a
  SIGINT mid-loop each leave `exec()` returning normally with rc 0.
- **Why deferred:** one `try/finally` fixes it, and it belongs in the same
  edit as LWSM-1117's mechanism-level bound rather than as a separate pass.
- **Will be addressed in:** LWSM-1117 (FP05 — bound the abandoned-pool wait)
- **Logged:** 2026-08-07

## known-issue-009 — `start_polling()` after `stop()` starts a timer that can never observe

- **Found by:** code-quality-review during FP05
- **Class:** handed to owning phase
- **Detail:** `_stopped` is set at `controller.py:242` and never cleared, so
  `start_polling()` on a stopped controller runs `self._timer.start()` at
  `:225` while `poll_once` returns immediately at `:263` — a 1 Hz timer that
  can never produce an observation, silently. Nothing calls it that way today.
- **Why deferred:** it becomes reachable the moment a reload or rescan path
  exists, which is P03's Rescan button — and that is the item that has to
  decide whether a controller is restarted or replaced.
- **Will be addressed in:** P03 (LWSM-1006 — project discovery)
- **Logged:** 2026-08-07

### From the presentation lane

## known-issue-010 — Contrast is only ever computed against `window`; `state_running` is 4.29:1 on `alt_base`

- **Found by:** code-quality-review during FP05
- **Class:** handed to owning phase
- **Detail:** `tests/test_theme.py:68-77` checks the state tokens against
  `theme.window` only, and `:80-85` checks `base`/`alt_base` for the `text`
  token alone. Computed with the project's own `tests/contrast.py`:
  `state_running` on `alt_base` = **4.29:1** and `state_unknown` on
  `alt_base` = **4.46:1**, both under the 4.5 floor; `attention` on `window` =
  4.62:1 and is checked against nothing. INV-18's stated purpose is that
  "adding a palette that fails is a failing build" — the parametrisation
  covers tokens × themes but not tokens × **surfaces**.
- **Why deferred:** nothing renders on `alt_base` yet, so no user can see it.
  It is materially cheaper to fix while one palette exists than after seven.
- **Will be addressed in:** LWSM-1007 (P03 — the list view that first paints
  on `alt_base`)
- **Logged:** 2026-08-07

## known-issue-011 — INV-20's 600 px band breaks on a realistic project name

- **Found by:** code-quality-review during FP05
- **Class:** handed to owning phase
- **Detail:** the name cell takes its natural width uncapped
  (`mainwindow.py:142`), so an ordinary name pushes the port cell out of the
  band INV-20 promises. Measured at 1400 px window width, port cell right
  edge: `customer-dashboard-frontend-v2` → **630 px** at 100 % text;
  `my-portfolio-site` → **638 px** at 200 %. The test
  (`tests/test_mainwindow.py:369-381`) varies window width but uses a
  one-character name, so the variable that actually breaks it is never varied.
- **Why deferred:** the fix is an elide-or-wrap policy on the name cell, which
  is a layout decision P04 owns; `design.md § Accessibility` calls the
  spread-out shape "a pan and a memory test" and P04 is where that is settled.
- **Will be addressed in:** P04 (LWSM-1030 — appearance and accessibility
  foundation)
- **Logged:** 2026-08-07

## known-issue-012 — INV-15's status-bar message is truncated at the window's own default size

- **Found by:** code-quality-review during FP05
- **Class:** handed to owning phase
- **Detail:** the status message does not contribute to the window's minimum
  width, so at the default ~202 px the `RegistryError` text INV-15 promises
  "names the file and the reason" renders about a third of itself. Measured:
  message needs **590 px**, status bar is **202 px**, rendered ink stops at
  x=184 and moves to x=594 when widened to 900 px.
  `test_registry_error_opens_an_empty_window` asserts `currentMessage()` — the
  model string, always complete — so it cannot fail for this.
- **Why deferred:** the honest fix is a minimum window width derived from
  content, which is the same layout decision as known-issue-011.
- **Will be addressed in:** P04 (LWSM-1030 — appearance and accessibility
  foundation)
- **Logged:** 2026-08-07

## known-issue-013 — The row's accessible role is `Border`, and no widget has an accessible description

- **Found by:** code-quality-review during FP05
- **Class:** handed to owning phase
- **Detail:** `ProjectRow` is a bare `QFrame`, so its AT-SPI role is `Border`
  — a decorative role — while being the only focusable, semantically
  meaningful element in the app. Live interface query confirms
  `role=Border name='running, demo, port 5005' focusable=1`.
  `setAccessibleDescription` appears **nowhere** in `src/`, so O8 clause 1's
  second half is unimplemented for every widget. Keyboard reachability itself
  was verified working.
- **Why deferred:** the name is self-explanatory today, so the practical
  impact is small; fixing the role properly means choosing a list/listitem
  structure, which is LWSM-1007's job.
- **Will be addressed in:** LWSM-1007 (P03 — the list view)
- **Logged:** 2026-08-07

## known-issue-014 — The port cell reserves the width of its shortest possible string

- **Found by:** code-quality-review during FP05
- **Class:** handed to owning phase
- **Detail:** `mainwindow.py:162` reserves `horizontalAdvance("no port_")` =
  47 px, but `port 5005` needs 54 px and `port 65535` needs 61 px, so the
  reservation never binds and the column does not line up down the list. No
  clipping occurs. The state cell is correct only by luck — `stopped_` is
  52 px and its widest word `unknown` is also exactly 52 px.
- **Why deferred:** column alignment across rows is the same layout decision
  as known-issue-011 and known-issue-012.
- **Will be addressed in:** P04 (LWSM-1030 — appearance and accessibility
  foundation)
- **Logged:** 2026-08-07

### From static analysis

## known-issue-015 — Two new pyright errors on an unguarded `self.layout()`

- **Found by:** audit (pyright) during FP05
- **Class:** handed to owning phase
- **Detail:** `mainwindow.py:165-166` calls `.spacing()` and
  `.setContentsMargins()` on `self.layout()`, which pyright types as
  `QLayout | None`. **Verified it cannot fire:** `QHBoxLayout(self)` at
  `mainwindow.py:102` sets the layout during construction and both call sites
  (`:144` in `__init__`, `:176` in `changeEvent`) run after it. 18 further
  pyright errors sit in `tests/test_mainwindow.py`, all from FP04's translator
  overrides. The one pre-existing error is `applog.py:53`.
- **Why deferred:** pyright is not in `scripts/local-ci.sh`, so nothing is
  gated on it. These matter exactly when it is added, and LWSM-1066 is the
  item that adds it — fixing them earlier means fixing them against a checker
  configuration that does not exist yet.
- **Will be addressed in:** LWSM-1066 (FP02 — put a type checker in the gate)
- **Logged:** 2026-08-07

### From the repository itself

## known-issue-016 — Generated audit output sits in two published commits

- **Found by:** user, 2026-08-07, asking whether `.audit_cache` should be
  gitignored so the world cannot read the app's problems
- **Class:** accepted, will not be fixed — see the decision below
- **Detail:** the answer to the question as asked is **yes, and it already is**:
  `.gitignore:126` ignores `.audit_cache/*`, with one deliberate exception for
  `.gitleaks-audit-run.toml` (120 bytes of gitleaks *input* config: two path
  regexes, no findings, no paths). But the tree is not the exposure. Four files
  — two `.sarif`, two `findings-*.json` — were tracked between **`aa3e0f4`**
  ("FP02: record the pass") and **`7c5e63d`** ("chore: stop tracking generated
  audit output"), and **both commits are on `origin/main`**, so the content is
  retrievable from GitHub history. `git status` cannot show this, which is why
  it survived a security pass and three reviews.
- **What is actually exposed**, read rather than assumed:
  - `findings-*.json` — **184 findings, every one `contract_doc_drift`,
    severity `UNKNOWN`**, e.g. "doc references `PROJ-NNNN` but no match in
    project sources". The FP02 journal records that every tool finding that
    pass was a false positive, and this is that set.
  - `*.sarif` — the same, plus a `clang++` error carrying **one absolute
    path**: `/mnt/Games/Scripts/Linux/LocalWebServerManager/build/compile_commands.json`.
  - **No credentials, no unfixed vulnerabilities, no `/home/<user>` path.** The
    single real disclosure is the drive-and-directory layout in that path.
- **Decision (2026-08-07, user deferred to the recommendation): leave the
  history alone.** Rewriting it means force-pushing `main` on a public repo,
  which `commits.md § 3.3` forbids without explicit authorisation and which
  costs more than the disclosure is worth: every commit SHA from `aa3e0f4`
  onward changes, published tags including `P02-complete` must be re-pointed,
  existing clones and forks break — and GitHub retains unreferenced objects and
  fork copies regardless, so the removal would not even be reliable. A
  disclosure of "this project lives on a drive called `/mnt/Games`" does not
  justify that.
- **Why it will not recur:** the ignore rule predates this entry and holds. Note
  for whoever reads this next: today's ignored output is *also* 170 ×
  `contract_doc_drift` and nothing else, so the rule is currently protecting
  low-value content — its value arrives the first time a scan surfaces a real
  unfixed vulnerability, which is exactly when it must already be in place.
- **Residual, if it ever matters:** teaching the audit tooling to emit
  repo-relative paths only would make a future accidental commit leak nothing.
  That is Ants tooling rather than this project, so it is named here and not
  filed as a roadmap item.
- **Logged:** 2026-08-07


## What does NOT belong here

- Findings that *could* be fixed today but feel like work
  for "later". Those go into a fix-pass roadmap item, not
  here. **The second class above does not weaken this** — it
  requires a named owning item whose work touches the same
  code, which "later" by definition does not have. If you
  cannot name the item, you are deferring, not routing.
- Findings that turned out to be false positives. Those go
  in [`docs/audit-allowlist.md`](audit-allowlist.md) (the
  closed-loop memory used by `/audit` and `/code-quality-review` to
  pre-discard), with a short note in the active phase's
  `docs/journal/<ID>.md`.
- Findings that the user decided to accept as-is. Those go
  into a permanent ADR explaining the trade-off, not a
  known-issue.

The bar is deliberately high. If you're tempted to defer
something here, ask: "Could I write a fix-pass roadmap item
for this right now?" If yes, do that. If no — and only if no
— file it here with the named dependency.
