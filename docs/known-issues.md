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
- **Will be addressed in:** P04 (LWSM-1030 — appearance and accessibility
  foundation). **Re-routed 2026-08-12** from LWSM-1007, which was named on the
  reading that it was "the list view that first paints on `alt_base`".
  LWSM-1007 is registry persistence — it adds no palette and paints nothing —
  and its spec (`docs/specs/LWSM-1007-registry-persistence.md § 9`) excludes
  this explicitly. known-issue-011 and -012, from the same review batch and
  about the same surface, were already routed to LWSM-1030.
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
- **Will be addressed in:** P04 (LWSM-1032 — accessibility pass), with
  LWSM-1030 if the role change falls out of the appearance work first.
  **Re-routed 2026-08-12** from LWSM-1007 for the reason recorded on
  known-issue-010: choosing a list/listitem structure is an AT-SPI decision,
  and LWSM-1007 is registry persistence. Its spec
  (`docs/specs/LWSM-1007-registry-persistence.md § 9`) excludes this
  explicitly.
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


### From the P03 close (`/code-quality-review`, 2026-08-12)

Sixteen findings routed rather than worked, per the standing 2026-08-07
process decision: one review per phase, fix what is above the bar, hand the
rest to the phase that owns the code. The nine above the bar are `FP06`
(LWSM-1122…1130). **None of these is a false positive** — every one was
verified by the lane that raised it, and the crash-class findings were
reproduced a second time before being written down. They are deferred on
value, not on doubt.

Ten of the sixteen are *tests that cannot fail for the thing they name*
rather than defects. That distinction matters when reading them: the
behaviour is correct today in every case below unless the entry says
otherwise. What is missing is the thing that would notice it stopping.

## known-issue-017 — Hop-rejection reasons do not name the candidate that produced them

- **Found by:** code-quality-review during the P03 close (lane 1, #4)
- **Class:** handed to owning phase
- **Detail:** `scanner.py:974-975` calls `note(reason)` on `_hop_target`'s bare
  string, while every other per-candidate note is `f"{quoted}: …"`. On a mixed
  scan root the operator sees `hop target '../shared/conf.ini' is outside the
  project` with no way to tell which project produced it. § 4.4's own reason
  examples are all `<name>: …`-shaped, so the code is the side that deviates.
- **Why deferred:** cosmetic until there is a UI that shows skip reasons to a
  user. Today they reach the log only. LWSM-1008's first-run flow is the item
  that puts them in front of somebody, and it should decide the format once
  rather than have this changed twice.
- **Will be addressed in:** LWSM-1008 (P03 — first-run flow)
- **Logged:** 2026-08-12

## known-issue-018 — A hex literal yields a fabricated port (`0x1F90` → 1)

- **Found by:** code-quality-review during the P03 close (lane 1, #6)
- **Class:** handed to owning phase
- **Detail:** rule 2's `(?<![0-9-])\d{1,5}(?![0-9])` matches the `1` of `1F90`
  (preceded by `x`, followed by `F`) once `0` is rejected as out of range.
  **The code is character-identical to the spec's fenced `rule_2`**, so this is
  a spec finding, not an implementation one — the same family as the
  documented-and-accepted `PORT = 80.80` → 80.
- **Why deferred:** hex is the one remaining shape where the rule invents a
  value rather than reporting unknown, but fixing it means editing a pattern
  the spec prescribes verbatim, which re-arms the rule-14 gate on a spec the
  user has explicitly closed to further review loops. LWSM-1121 is already
  scheduled to reopen § 4.6 for the `.env` / `docker-compose.yml` / `README.md`
  sources; this rides along with that edit at no extra gate cost.
- **Will be addressed in:** LWSM-1121 (the remaining port sources)
- **Logged:** 2026-08-12

## known-issue-019 — TOCTOU between the hop containment check and the hop read

- **Found by:** code-quality-review during the P03 close (lane 2, F6 — reasoned,
  not demonstrated; the lane says so explicitly)
- **Class:** handed to owning phase
- **Detail:** `scanner.py:543` resolves and containment-checks `target`, and
  `:598` re-opens it by path. `O_NOFOLLOW` guards only the **final** component,
  so an attacker who swaps an intermediate directory for a symlink inside that
  window reads a file outside the project.
- **Why deferred:** the disclosure is bounded to a single port number and a rule
  name — `PortFinding` deliberately carries no file bytes — and the attacker
  must already be able to write inside the scan root. `O_PATH`-anchored
  `openat` on the candidate directory closes it, which is the same mechanism
  LWSM-1049's trust gate needs for launching, so building it twice would be
  waste.
- **Will be addressed in:** LWSM-1049 (FP01 — trust gate before running a
  discovered launcher)
- **Logged:** 2026-08-12

## known-issue-020 — A hard link reads outside the project through the `_open_source` seam

- **Found by:** code-quality-review during the P03 close (lane 2, F7 —
  demonstrated)
- **Class:** handed to owning phase
- **Detail:** `_open_source` / `_checked_descriptor` (`scanner.py:240-270`)
  have no `st_nlink == 1` check. Measured: a hard-linked `start.sh` was read
  and its port returned (`PortFinding(port=4444, …)`). For **symlinks**
  `O_NOFOLLOW` is sufficient and was verified so — a symlinked, dangling,
  self-looping and `/dev/zero`-pointing launcher are all refused with `ELOOP`.
- **Why deferred, and the precedent that matters:** the sibling module
  `applog.py::_NoFollowRotatingFileHandler` solved exactly this class with an
  `fstat` requiring one link and our own ownership, after the same gap was
  found there on 2026-08-06. **The difference between the two modules is not
  written down anywhere**, which is the real defect being recorded here. It is
  weaker than the `applog.py` case in two ways: `fs.protected_hardlinks=1` is
  the distro default and already requires the linker to own or be able to
  read+write the target, and the leak is one 16-bit number rather than the
  user's whole project inventory. LWSM-1049 is where the trust posture for
  reading foreign files is decided; this belongs in that decision, recorded
  either way.
- **Will be addressed in:** LWSM-1049 (FP01 — trust gate)
- **Logged:** 2026-08-12

## known-issue-021 — `_UnitLookup.properties` guarantees totality by docstring only

- **Found by:** code-quality-review during the P03 close (lane 2, F8)
- **Class:** handed to owning phase
- **Detail:** `scanner.py:786-793` returns the adapter's dict verbatim, so the
  `SupportsUnitLookup` Protocol's totality guarantee (`:183-192`) rests on every
  future adapter remembering it. `props["LoadState"]` (`:855`) and
  `props["FragmentPath"]` / `["WorkingDirectory"]` (`:864`) are the `KeyError`
  the spec gate already paid for once. A
  `{name: got.get(name, "") for name in UNIT_PROPERTIES}` in `_UnitLookup`
  makes it structural.
- **Why deferred:** the one shipping adapter is correct and the only other
  implementations are test fakes. It becomes live the moment a second real
  adapter exists, which is LWSM-1028's systemd launcher work.
- **Will be addressed in:** LWSM-1028 (P04 — systemd as a launcher kind)
- **Logged:** 2026-08-12

## known-issue-022 — `systemctl` stdout is read with no size bound

- **Found by:** code-quality-review during the P03 close (lane 2, F9)
- **Class:** handed to owning phase
- **Detail:** `scanner.py:728-735` uses `subprocess.run(capture_output=True)`
  with no output cap.
- **Why deferred:** reachable only by someone who can write a user unit, which
  is a strictly higher privilege than the scan-root attacker this module is
  hardened against — such a person can already set `ExecStart`. Named for
  completeness so a future reader does not assume it was missed.
- **Will be addressed in:** LWSM-1028 (P04 — systemd as a launcher kind)
- **Logged:** 2026-08-12

## known-issue-023 — Neither half of INV-5's deadline mechanism is individually constrained

- **Found by:** code-quality-review during the P03 close (lane 3, M1 — mutation)
- **Class:** handed to owning phase
- **Detail:** deleting the per-line check (`scanner.py:319-320`) leaves the
  suite green; deleting the per-candidate check (`:1212-1213`) leaves it green;
  only deleting **both** reddens it. Coverage shows `:1213` never fires — expiry
  always happens inside `_read_lines`. Giving the hop-file read an infinite
  deadline is also green. INV-5's own *Breaks when* names precisely this case:
  "the deadline is checked once per scan instead of per line and per candidate,
  and one pathological file consumes the whole budget".
- **Why deferred:** the behaviour is correct, and lane 2 measured the worst
  256 KB inputs it could construct at **59 ms** against a 20 s budget, so the
  unreached arm is not currently reachable in practice either. LWSM-1039's
  backup/restore work is the next thing to touch the budget plumbing.
- **Will be addressed in:** LWSM-1039 (P03 — registry backup)
- **Logged:** 2026-08-12

## known-issue-024 — INV-17's `ExecStart` half has zero coverage

- **Found by:** code-quality-review during the P03 close (lane 3, M2)
- **Class:** handed to owning phase
- **Detail:** `grep ExecStart tests/*.py` returns nothing; no `FakeUnits`
  fixture sets the key; `scanner.py:904` is in the coverage miss list. The
  existing `test_exec_start_is_a_record_and_only_its_argv_field_is_scanned`
  (`test_scanner.py:404`) calls `_exec_start_argv` and `rule_1` as pure
  functions and never reaches `_systemd_port`. The path was verified to work
  when driven by hand (`argv[]=… --port 8080` → 8080); a regression in it would
  be invisible.
- **Why deferred:** `Environment=` is the half every real project on this
  machine uses, and it *is* covered. The `ExecStart` half becomes load-bearing
  when systemd is a launcher kind rather than a detection source.
- **Will be addressed in:** LWSM-1028 (P04 — systemd as a launcher kind)
- **Logged:** 2026-08-12

## known-issue-025 — `DetectedProject.path` being resolved is untested, and a symlinked scan root gives one project two identities

- **Found by:** code-quality-review during the P03 close (lane 3, M3 —
  demonstrated)
- **Class:** handed to owning phase
- **Detail:** mutating `.resolve()` → `.absolute()` at `scanner.py:1232` leaves
  the suite green. Demonstrated: `scan([symlinked_root, real_root])` returns
  **2 projects for 1 directory**. The existing
  `test_the_same_directory_reached_twice_is_listed_once`
  (`test_scanner.py:1365`) passes the *same* root twice, which dedups under
  either implementation. `scan()`'s own docstring says a symlinked scan root is
  followed deliberately, so this is a shape that occurs rather than a
  contrivance. This was loop 4's finding — "`path` was 'absolute' where four
  other clauses need it *resolved*" — and the fix landed without a test.
- **Why deferred:** the code is correct; the identity only becomes durable when
  it is written to disk, and nothing persists it yet. The item that makes a
  duplicate identity a *persisted* duplicate needs the same fixture for its own
  merge rules.
- **Will be addressed in:** **LWSM-1131** (P03b — merge a rescan into the stored
  registry), as its INV-5, with this entry's own fixture. **Re-pointed from
  LWSM-1007 on 2026-08-12**, when that spec was split: identity here is a
  question about what a *merge* treats as one project, and the merge went to
  LWSM-1131 while LWSM-1007 kept the file format and the writer. The routing
  reason above is unchanged — only the id that now owns it.
- **Logged:** 2026-08-12

## known-issue-026 — INV-15's fixtures make zero calls to the matcher the invariant names

- **Found by:** code-quality-review during the P03 close (lane 3, M4 —
  instrumented)
- **Class:** handed to owning phase
- **Detail:** instrumenting `re.finditer` shows **both** INV-15 fixtures
  (`test_scanner.py:353-378`) make **0** calls to
  `re.finditer(r"(?<![0-9-])\d{1,5}(?![0-9])", right)` — the only part of rule 2
  with a quantifier, a lookbehind and a lookahead, and exactly where the
  invariant's own *Breaks when* ("a single pattern with a nested quantifier")
  would land. The 102-colon fixture runs in 4 µs against a 1 s ceiling on 40
  characters of input: a 250,000× margin. A fixture with a long *right* side
  reaches it — `"port = " + "0"*4000 + " 1"` → `digit_finditer=[4003]`, 116 µs.
- **Why this is uncomfortable:** § 12 of the spec **already records this exact
  defect once** — the earlier `"a"*4092 + "port"` fixture had no separator, so
  `rule_2` returned before `KEY_IS_PORT` ever ran, and the fix replaced it with
  a fixture that reaches `KEY_IS_PORT` but still not the digit scan. The same
  green-by-construction shape survived its own correction.
- **Why deferred:** no defect exists — lane 2 independently confirmed no nested
  quantifier anywhere in the module, and `MAX_SOURCE_LINE_CHARS` bounds the
  input regardless. This is a test that proves less than it claims, in a place
  where the claim is currently true.
- **Will be addressed in:** LWSM-1121 (the remaining port sources — the next
  item to add a pattern to § 4.6, and the point at which the guard starts
  mattering)
- **Logged:** 2026-08-12

## known-issue-027 — The tokenise-and-select rule is unconstrained in all three of its open steps

- **Found by:** code-quality-review during the P03 close (lane 3, M5 — three
  mutations, all green)
- **Class:** handed to owning phase
- **Detail:** at `scanner.py:585-606`, all three of these leave the suite green:
  reversing the line scan so the *first* invocation wins; reversing the token
  scan; and deleting the `if not token.startswith("-")` option filter. The
  last-invocation fixture (`test_scanner.py:1045`) has only one surviving
  invocation after comment-stripping, so it tests the stripper — which *is*
  covered, neutering it reddens — and not the ordering. The token fixtures rely
  on non-path tokens simply not existing on disk, so forward and reverse agree.
  § 4.5 steps 2-4 were loop 5's best find and the mechanism that replaced the
  prose is locked by nothing.
- **Why deferred:** LWSM-1123 (FP06) rewrites this exact function to add
  constraint fallback, and will have to build discriminating fixtures to prove
  the fallback works. Writing them twice is waste; writing them now against a
  function about to change is worse.
- **Will be addressed in:** LWSM-1123 (FP06 — hop-target fallback)
- **Logged:** 2026-08-12

## known-issue-028 — `_RULE_1_ONLY` on the `ExecStart` argv is untested

- **Found by:** code-quality-review during the P03 close (lane 3, M6 — mutation)
- **Class:** handed to owning phase
- **Detail:** removing `rules=_RULE_1_ONLY` at `scanner.py:904` leaves the suite
  green. A discriminating fixture exists and was verified:
  `argv[]=/opt/my-port:5432/bin/app serve` → `rule_1: None`, `rule_2: 5432`, so
  the restriction is what stops a path fragment being read as a port.
- **Why deferred:** same owner and same fixture family as known-issue-024 —
  both need the first `ExecStart` fixture to exist, and building it once serves
  both.
- **Will be addressed in:** LWSM-1028 (P04 — systemd as a launcher kind)
- **Logged:** 2026-08-12

## known-issue-029 — `systemctl`'s own 2-second bound is untested

- **Found by:** code-quality-review during the P03 close (lane 3, M7 — mutation)
- **Class:** handed to owning phase
- **Detail:** mutating `min(SYSTEMCTL_TIMEOUT_SECONDS, remaining())` →
  `remaining()` at `scanner.py:766-767` leaves the suite green.
  `FakeUnits.unit_names` / `properties` accept a `timeout` argument and discard
  it; nothing asserts the value passed. This is loop 5's "one hang consumed all
  20 s" fix shipping without a regression test.
- **Why deferred:** asserting it means teaching the fake to record its timeout,
  which is the same fixture change known-issue-030 needs.
- **Will be addressed in:** LWSM-1028 (P04 — systemd as a launcher kind)
- **Logged:** 2026-08-12

## known-issue-030 — `_UnitLookup.properties`' failure path is unexercised, and the fake that claims to test it cannot

- **Found by:** code-quality-review during the P03 close (lane 3, M8)
- **Class:** handed to owning phase
- **Detail:** two halves. `scanner.py:791-793` and `:850` are uncovered — no
  fake ever raises from `properties()`, so a `systemctl` that lists units and
  then fails on `show` (the ordinary partial-D-Bus case) is untested. And in
  `test_a_machine_with_no_systemd_scans_normally` (`test_scanner.py:636`),
  `Absent.properties`' `raise AssertionError("rule 0 should be disabled")` is
  **unreachable**: `names()` returns `[]`, so `_match_systemd`'s loop never runs
  and `properties` is never called. Setting `_disabled = False` in `_disable`
  keeps the suite green — the "recorded once" property is carried by the
  `_names is None` cache, not by the flag the fake claims to be testing.
- **Why deferred:** the second half is a test asserting nothing rather than a
  defect, and both need the same fake rework.
- **Will be addressed in:** LWSM-1028 (P04 — systemd as a launcher kind)
- **Logged:** 2026-08-12

## known-issue-031 — Two of the three byte-cap enforcement sites never execute

- **Found by:** code-quality-review during the P03 close (lane 3, M9 — coverage)
- **Class:** handed to owning phase
- **Detail:** `scanner.py:295` and `:326` are in the coverage miss list;
  deleting all three sites reddens, because the `fstat` site does all the work
  in every existing test. **This is not a redundancy complaint** — the project's
  position on layered guards is settled and correct, and the lane says so
  explicitly. The finding is narrower: a typo in either of the other two
  (`<` for `>`, a wrong constant) would never be caught, because the
  file-grows-between-`fstat`-and-read scenario the redundancy exists *for* has
  no fixture. A fake handle whose `read` / `readline` returns more than the
  `fstat` reported reaches both.
- **Why deferred:** the guards are correct and the class is understood. Note for
  whoever takes it: per `CLAUDE.md`, mutating one of three redundant guards
  proves nothing and mutating the *constant* is worthless when the fixture
  derives its size from it — the fake-handle fixture above is the mutation that
  actually discriminates.
- **Will be addressed in:** LWSM-1121 (the remaining port sources — the next
  item to add a reader, and so the next time the cap gets a fourth site)
- **Logged:** 2026-08-12

## known-issue-032 — Rule 3's Django-before-Flask tie-break is untested

- **Found by:** code-quality-review during the P03 close (lane 3, M10 —
  mutation)
- **Class:** handed to owning phase
- **Detail:** checking Flask first at `scanner.py:512-515` leaves the suite
  green. § 4.6 states the table order **is** the precedence and names the exact
  case — "a project with a root-level `manage.py` *and* an `import flask`" — and
  no fixture holds both. Verified working by hand: such a project returns
  Django 8000.
- **Why deferred:** one fixture, but it belongs in the corpus beside the other
  framework cases rather than as a standalone test, and LWSM-1121 is the next
  item to touch rule 3's table.
- **Will be addressed in:** LWSM-1121 (the remaining port sources)
- **Logged:** 2026-08-12

## known-issue-033 — Six small test weaknesses, bundled because none is worth its own entry

- **Found by:** code-quality-review during the P03 close (lane 3, § 4 LOW)
- **Class:** handed to owning phase
- **Detail:** filed as one entry deliberately — each is a single assertion or a
  single unreached line, and six separate entries would bury the twelve above
  that matter. Listed so none is lost:
  1. `test_a_script_that_execs_its_own_name_cannot_loop` (`test_scanner.py:1007`)
     **cannot fail** — deleting `if target == launcher` (`scanner.py:559-560`)
     stays green, because the fixture's `start.sh` declares no port and
     re-reading it yields `None` either way. A fresh object tested for
     stickiness.
  2. `test_exec_start_is_a_record_and_only_its_argv_field_is_scanned`
     (`:404`) **passes for the wrong reason** — its load-bearing assertion
     `rule_2(record) is None` is made against `record`, not against the
     function's return value, so `_exec_start_argv` returning the whole record
     stays green.
  3. Three defensive arms are never reached and stay green when removed:
     `_bound_inside`'s `ValueError` catch (`scanner.py:816-817` — a NUL in
     `WorkingDirectory`, the named non-`OSError` family), `commonpath`'s
     `ValueError` catch (`:548-549`, which cannot fire with two absolute
     paths), and the fd-close on `fstat` failure (`:267-269`).
  4. Untested small bounds, all green when deleted: `utf-8-sig` BOM handling
     (`:1016`), the dangling-symlink `package.json` arm (`:1006`), the "is not
     a directory" reason (`:1229-1230`), the node script's line-cap clip
     (`:1074`).
  5. `test_layering.py:110` globs `SRC.glob("*.py")`, which is **non-recursive**
     — a core module landing in `src/lwsm/<subpackage>/` is invisible to the
     derivation test that exists to stop a module being silently missed. Adding
     a name to `NON_CORE_MODULES` (`:42`) also silently exempts it, though that
     is at least a visible edit.
  6. `test_the_package_json_failure_shapes_are_not_all_value_errors` (`:771`)
     and `test_a_writer_less_fifo_reads_as_eof_not_as_a_block` (`:748`) assert
     **stdlib and OS behaviour**, not scanner behaviour — no mutation of
     `scanner.py` can redden either. Both are deliberately framed as
     kept-executable measurements, so this is informational rather than a
     defect; the point is that they must not be counted toward INV-3 or INV-4
     coverage, and today's invariant table implies they are.
- **Why deferred:** item 5 is the only one with any reach, and it needs a
  subpackage to exist before it can bite. The rest are single assertions in
  tests whose neighbours do constrain the behaviour.
- **Will be addressed in:** LWSM-1007 (P03 — registry persistence; the next
  item to add source files and so the first that could add a subpackage)
- **Logged:** 2026-08-12

## known-issue-034 — `scanner`'s copy of `MAX_REASON_CHARS` and `MAX_DISPLAY_NAME_CHARS` is pinned by nothing

- **Found by:** writing LWSM-1124's test during FP06, then mutating it
- **Class:** handed to owning phase
- **Detail:** `registry.MAX_REASON_CHARS` is pinned at 120 by
  `test_the_shipped_bounds_are_pinned` (`test_registry.py:490`), added when
  known-issue-005 was closed. **`scanner.py` declares its own copy of that
  constant and `MAX_DISPLAY_NAME_CHARS` beside it, and no test asserts either
  value.** Every scanner assertion about a clipped string is expressed
  *relative* to the constant — `<= scanner.MAX_REASON_CHARS + 50`
  (`test_scanner.py:1037`), `< scanner.MAX_REASON_CHARS + 60` (`:1647`),
  `== scanner.MAX_DISPLAY_NAME_CHARS` (`:1658`) — so raising the bound raises
  the assertion with it. Measured 2026-08-12: setting
  `scanner.MAX_REASON_CHARS = 400` leaves the whole suite green. That is
  known-issue-005's exact shape, in the module written after it was closed, and
  the fix is the same one line: assert the literal value once.
- **Why deferred:** it is a two-line addition and nothing is wrong today, but it
  belongs beside the *other* bound the same test would pin. LWSM-1007 adds the
  persisted registry that gives both constants a second consumer, which is the
  point at which one shared pin is obviously right and two copies are obviously
  wrong.
- **Will be addressed in:** LWSM-1007 (P03 — registry persistence)
- **Logged:** 2026-08-12

## known-issue-035 — `test_completed_tasks_do_not_accumulate` failed once and has not reproduced

- **Found by:** the full `local-ci.sh` run closing FP06
- **Class:** handed to owning phase
- **Detail:** the gate reported
  `AssertionError: 2 live tasks after 200 completed polls` at
  `tests/test_controller.py:523`, then passed on every rerun — 12 whole-file
  runs and 4 whole-suite runs, plus two clean full-gate runs. The assertion
  counts live `_SnapshotTask` objects through `gc.get_objects()` after 200
  completed polls and allows at most the one the controller still references.
  Nothing FP06 changed is on that path: the pass touched `scanner.py` only, and
  the controller does not import it. The likely cause is `QThreadPool` still
  holding a reference to a just-finished runnable at the moment of counting,
  which is a timing property of the pool rather than of the code under test —
  so the test is measuring something it cannot fully control.
- **Why deferred:** a test that fails once in ~20 runs cannot be fixed by
  guessing at it, and the mechanism it guards (LWSM-1073's task accumulation) is
  worth keeping. It needs a run under load to characterise, not a patch.
  Recorded rather than dismissed because this project has been bitten three
  times by a green run that was not one, and an unexplained red is that report
  in the other direction.
- **Will be addressed in:** LWSM-1011 (P04 — the next item that touches the
  controller's polling, where the pool's lifetime behaviour is in scope anyway)
- **Logged:** 2026-08-12


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

## known-issue-036 — `spec_lint`'s required-section check has never run on any spec in this project, and reports `ok` while skipping

- **Found by:** writing LWSM-1007's spec (P03b), reading `spec_lint`'s raw
  envelope rather than only its `findings` array
- **Class:** handed to owning phase
- **Detail:** every `spec_lint` call in this project returns
  `{"findings": [], "ok": true, "sections_checked": false}`. The last field is
  the whole finding: `missing_section` runs **only** when the project's format
  standard carries a `<!-- required-sections -->` block, and
  `docs/standards/spec-format.md` carries none (`grep -c required-sections`
  → `0`). So the required-section structure has never been verified on
  `LWSM-1005`, `LWSM-1006` or `LWSM-1007`, and a clean-looking `spec_lint`
  result is silent about the one thing it is most often run to check.
  **This is a fourth instance of the class this project has already been bitten
  by three times** — a report that cannot distinguish "passed" from "never ran"
  (`actionlint`/`yamllint` sharing one skip flag; a stale `.pyc`; `os._exit`
  ending pytest at 40 % with exit code 0). It is worse than those in one
  respect: nothing is degraded and no tool is missing, so there is no warning
  anywhere — only a field nobody reads.
- **Second half, same file:** `docs/standards/spec-format.md` names the
  **retired** skills `/cold-eyes` and `/doc-lint` throughout (16 occurrences on
  2026-08-12), including in its own What-checks-this table, which therefore
  attributes checks to a skill that no longer exists. `CLAUDE.md`'s skill table
  was corrected on 2026-08-12; this file was not.
- **Why deferred:** the fix is to add a `<!-- required-sections -->` block
  listing the project's thirteen sections and to sweep the retired names — but
  `spec-format.md` is a **standard**, so editing it re-arms global rule 14's
  `review-contract` gate, and doing that mid-flight during LWSM-1007's own
  capped gate would have interleaved two reviews of two documents.
- **Measured 2026-08-12, and it enlarges the fix: the block cannot simply be
  added, because the standard and the corpus disagree about the structure.**
  The list is read **verbatim** (working example:
  `~/.claude/standards/spec-format.md:155` — the marker, then a fenced block of
  `## N. Heading` lines). Against that, two mismatches:
  - § 3 lists **eleven** numbered sections (3.3 Goal … 3.13 Cross-doc impact,
    3.1/3.2 being the title and header block), but every spec here carries
    **thirteen** — `## 10. Resource cost`, which § 4 files as *Recommended*,
    and `## 13. Cold-eyes loop log`, which § 3 does not mention at all. So the
    thirteen the entry above assumed are not the eleven the standard states.
  - `LWSM-1005`'s heading is `## 3. Scope decisions (and who made each)` where
    `LWSM-1006` and `LWSM-1007` read `(agreed with the user)`. A verbatim block
    written today makes `missing_section` fire on a shipped, conforming spec —
    the exact failure `spec_lint`'s own docstring says the skip exists to
    prevent.

  The fix is therefore a § 3 renumbering, a heading correction in a shipped
  spec, and the retired-name sweep (**24 occurrences** on 2026-08-12, not 16 —
  recounted with `grep -c "cold-eyes\|doc-lint"`), all in a standard, all
  behind rule 14's gate.
- **Will be addressed in:** the next doc-fix pass (`DOC##`). **Re-routed away
  from P03b on 2026-08-12**, when LWSM-1007's spec was split: the entry offered
  the split as the natural moment because the split writes two fresh specs, but
  the measurement above turns a block-insert into a third gated review of a
  third document, mid-task.
- **Third measurement, and it names which list is right.** The precedence
  inverted on 2026-08-08: `~/.claude/standards/spec-format.md` is authoritative
  and a project states only its **deltas**, in
  `docs/standards/spec-format-overrides.md`. This project carries a **full
  fork** instead, which predates that change — so the fork is not a local
  convention, it is an un-extracted override file, and `/write-spec` Step 1
  requires saying so rather than silently obeying it. Against the global § 3
  the corpus is wrong in a second way: § 4 there reads **"appended after § 3's
  twelve, numbered from 13 … never interleaved"**, and all three specs
  interleave `## 10. Resource cost`, pushing *What checks this*, *Cross-doc
  impact* and *Cold-eyes loop log* to 11/12/13 against the standard's 10/11/12.
  `/write-spec` Step 1 settles which wins — *"a sibling numbering `What checks
  this` differently is a sibling that is wrong, not a local convention to
  copy"* — so **LWSM-1007 and LWSM-1131 are renumbered to the global order**
  and `Resource cost` moves to `## 13`. They are the first two conforming specs
  here; `LWSM-1005` and `LWSM-1006` are the ones the `DOC##` sweep renumbers.
  This is also what a `required-sections` block would have to be written
  against, which is why it could not simply be added.
- **Logged:** 2026-08-12
