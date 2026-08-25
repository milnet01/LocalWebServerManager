# LocalWebServerManager — Workflow state

## §1. Status header

| Field | Value |
|-------|-------|
| **Project phase** | **`P04` FEATURE-COMPLETE, close BLOCKED by `FP08` (2026-08-21).** Every P04 item is ✅ — LWSM-1033 (window geometry, Centre on screen) and LWSM-1156 (Enter in the filter box) shipped today, closing the appearance/accessibility/keyboard/layout theme. The close then ran four cold lanes, which returned **20 verified findings** — filed as `FP08`, LWSM-1162…LWSM-1181. **P04 stays 🚧 until FP08 closes**, and only then earns `P04-complete`, which is also LWSM-1152's gate for the first 0.1.0 release. **`P03b` REMAINS OPEN and is untouched by this** — LWSM-1039, LWSM-1008 and LWSM-1121 are still 📋. Two phases are legitimately in flight; `CLAUDE.md § Commit conventions` already records that the COMMIT LOG's prefix, not this header, decides what a commit is labelled, and this line is the reconciliation that note said a close would have to make. Was: **`P03b` OPEN (started 2026-08-12)** — the continuation phase carrying the four items P03 planned and did not deliver: **LWSM-1007** (registry persistence, active), LWSM-1039 (backup), LWSM-1008 (first-run flow), LWSM-1121 (extra port sources). **Why a suffix and not `P04`:** this roadmap assigns `P04`–`P09` to named themes in advance (P04 theme/accessibility/keyboard, P05 supervisor, P06 classifier, …), so a phase closed against partial scope has no free number to spill into. Three alternatives were put to the user and declined — renumbering the themes (28 bullets plus every doc citing a phase by number), folding the leftovers into P04 (one phase mixing storage internals with UI polish), and re-opening P03 by re-pointing the pushed `P03-complete` tag (needs the force-push authorisation `commits.md § 4.2` withholds). The suffix form is now recorded in `CLAUDE.md § Commit conventions`; commits read `P03b: …` and the close earns its own `P03b-complete` tag. **`P03-complete` stands and is not re-pointed** — it marks what P03 actually closed. Was: **P03 CLOSED 2026-08-12** — LWSM-1006 Scanner shipped, plus fix-pass FP06 (nine items). Tagged `P03-complete`. **P03's remaining items — LWSM-1007 registry persistence, LWSM-1039 backup, LWSM-1008 first-run flow and LWSM-1121 — are 📋 and were never part of this close**; they open the next phase. Was: P03 OPEN (started 2026-08-08) — LWSM-1006 Scanner is the active item and its spec is through the gate; LWSM-1007, LWSM-1039, LWSM-1008 and LWSM-1121 follow. **P02 CLOSED 2026-08-07** — vertical slice LWSM-1005 plus five fix-passes (FP02–FP05, 37 fix items). P01 stays open only for FP01's five 🚧 security items (P05/P06). Phases A–D closed 2026-08-03. **Next is P03** (LWSM-1006 Scanner, LWSM-1007 registry persistence, LWSM-1039 backup, LWSM-1008 first-run flow) |
| **Active item ID** | **`FP08` — next is LWSM-1171.** LWSM-1169 and LWSM-1170 shipped 2026-08-25 (`9d5b218`, `7a55ac7`). LWSM-1170's filed cause was CORRECTED by measurement, making that five consecutive FP08 bullets whose stated cause a reproduction changed — reproduce before designing, and treat a bullet's cause as a reading rather than a measurement (`CLAUDE.md` carries the trap). Previously: LWSM-1168 shipped 2026-08-25 (`599ea83`). Its supervisor half **reproduced**: a second real child spawned mid-stop, with the window held open at the `_on_wait` seam rather than raced for. Its UI half was **wrong in its stated mechanism** — `_settle_overlay` keeps a STOPPING overlay against a SIGTERM-ignoring child, and what re-enables Start early is LWSM-1133's port-less branch — so the residue is filed as **LWSM-1191** rather than folded in. Before FP08 resumed, the user-ordered detour shipped: **LWSM-1190** (a port read out of a quoted error message, which corrected MAME_Curator too — a second instance no fixture held) and **LWSM-1184** (a wrapper's program now gets the import walk; Contact_List detected, and RetroDB's 5000 now read from a declaration rather than guessed from Flask, so LWSM-1190's answer stopped being right by coincidence). **`confirm before implementing` is now three for three** — LWSM-1167, LWSM-1184 and LWSM-1168 each had a filed cause that measurement changed, and LWSM-1169 is the bullet flagged as most likely wrong. Was: **`FP08`, 13 items left — next is LWSM-1168.** LWSM-1167 shipped 2026-08-24 (`b594350`). **Six of the thirteen still rest on a review lane's quotation alone and say so on the bullet** — LWSM-1168, LWSM-1169, LWSM-1175, LWSM-1178, LWSM-1179 and three of LWSM-1180's five docstrings; LWSM-1169 is flagged as most likely wrong and LWSM-1179 as possibly not worth fixing. **Confirm before implementing**, which is what LWSM-1167 did and what turned its "fix shape" into a different, better fix. Was: **`FP08`, 14 items left — next is LWSM-1167, and it is CONFIRMED.** Its bullet carries a `CONFIRMED (2026-08-24)` block superseding its earlier "not independently confirmed" note: reproduced end to end, with the root cause and the fix shape written up on the bullet. Read `ADR-0004` before starting it — the ADR already specifies what the item asks for (`PortProbe` must answer *what holds the effective port?*, and `running (managed)` is *"effective port held by that child's group"*), and it carries two rules the bullet does not: the "looks like this project" test **may never be gated on**, and a managed server's identity is **the recorded child PID plus its `create_time`**, never the working directory. `LWSM-1011`'s seven-state classifier is the full implementation and `LWSM-1154` is blocked on it — LWSM-1167 is the foundation, not the whole thing. Was: **`FP08`, 5 of 21 shipped — next is LWSM-1166.** The four-lane fold-in from the P04 close, 2026-08-21: twenty findings, every one verified against the code before filing and three reproduced outright. **LWSM-1182 is the 21st and was filed on 2026-08-23 from inside the pass**, not by a lane. **Cadence, decided by the user 2026-08-23: all items in sequence, ONE AT A TIME** — red test, fix, `mutation_probe`, `local-ci.sh`, changelog, roadmap flip, one commit per item, push. Do not batch two items into one commit; the reason is that a mutation run measures one mechanism and a red gate must name one change. **Shipped 2026-08-23:** LWSM-1162 (launcher symlinked out of its project was not refused — `_contained` swallowed the escaping case, so ADR-0003's refusal was unreachable from `start()`), LWSM-1163 (one JSON typo plus one window close wrote defaults over every stored setting), LWSM-1164 (`RecursionError` is not a `ValueError`, so a nested settings file killed the app at startup), LWSM-1182 (a BOM refused `settings.json` and `scan-roots` where `registry`/`scanner` tolerate it — **taken out of order because LWSM-1163's write gate, shipped hours earlier, turned it from cosmetic into permanent**), LWSM-1165 (a child that exited on its own kept its slot for the session, so Start refused while Stop and Restart were greyed out). **Remaining, in order:** LWSM-1166 … LWSM-1181. LWSM-1181 is an investigate, not a confirmed defect. |
| **Active step** | **DO NOT RUN `roadmap_migrate` ON THIS PROJECT until Ants MCP fixes its parser (checked 2026-08-18).** This project is ALREADY in the store (`~/.local/share/ants-terminal/roadmap.sqlite`, project_id 8, 136 items, every field populated) and `ROADMAP.md` is its render, so there is nothing left to migrate. A re-run is not a no-op: `dry_run` plans **0 inserts and 47 updates**, because the store's own renderer wraps a long `**headline**` onto a second line and its importer cannot parse that back — it gives up partway through the bullet and reports `Kind:`/`Source:` as absent for 36 bullets whose `Kind:`/`Source:` are plainly in the file ~23 lines below. The correlation is exact: 36 of 136 bullets wrap, and those are precisely the 36 flagged, with no unwrapped bullet flagged and no wrapped bullet missed. So the migration would overwrite 47 correct rows with mis-parsed ones, in a store with **no undo**, while returning `ok:true` with the damage as advisory notes. **THE CONCLUSION STANDS AND THE REASON ABOVE NO LONGER DOES — re-checked 2026-08-19.** The wrap-and-mis-parse mechanism described above is not what is happening any more: the renderer no longer wraps those headlines, LWSM-1001 / LWSM-1044 / LWSM-1045 are byte-identical between the store and the rendered line, and `dry_run` STILL plans 48 updates (47 governed) naming `fields:["headline"]` on exactly those items. So the count is a phantom diff of unknown origin rather than a decoded mis-parse, which is strictly worse to act on: a caller cannot tell an idempotent re-run from real data loss, and `dry_run` is the only pre-flight there is. Filed upstream with the three-step repro in `../LocalWebServerManager_Ants_MCP_Feedback.md` (2026-08-19). **Do not re-derive the mechanism from the paragraph above — it was correct on 2026-08-18 and is not correct now.** Still: do not run it. **A related bug that is now FIXED and must not be worked around any longer (re-checked 2026-08-19):** `roadmap_query` used to silently omit `headline`, `headline_oneline`, `kind` and `lanes` for any item whose stored headline wraps, `mode:"headline_only"` included, so 36 of 136 items came back as id+status+section with no error and no flag. **ANTS-4437 shipped and this session verified it against the original repro** — LWSM-1005 and LWSM-1031 both still wrap in the markdown and both now return `headline_oneline` flattened, with `all_ids_resolved:true`. **So query the store; do NOT grep ROADMAP.md for a wrapped bullet.** This note cost this session a needless file read before it was checked, which is the standing hazard with a workaround that outlives its bug. Both are filed with repros in `/mnt/Games/Scripts/Linux/LocalWebServerManager_Ants_MCP_Feedback.md` (2026-08-18, "roadmap DB migration check"). **If a future session does run it, back the store up with sqlite3's backup API first — a plain `cp` of the `.sqlite` is inconsistent, because the store runs in WAL mode with a multi-MB `-wal`.** Was: **Release machinery is READY; the first release is LWSM-1152 (cut 0.1.0 once P04 closes, decided with the user 2026-08-18).** Shipped today after the layout items: LWSM-1150 (CI tool pinning + pre-push hook), **LWSM-1067** (version lockstep + `.claude/bump.json`), **LWSM-1151** (`scripts/local-release.sh`, the release preflight). 551 tests green, CI green. **`./scripts/local-release.sh 0.1.0` today reports exactly ONE blocker — no dated `## [0.1.0]` changelog section — and that is release-day work `cut-release` deliberately refuses to author.** **Four things worth not re-deriving.** (1) **Nothing on GitHub checks a release.** CI fires on `push` and `pull_request` only, with no tag trigger and no release trigger, so `local-release.sh` is the ONLY gate a release gets rather than a local mirror of a remote one. (2) **`LWSM-1052` claims the same filename for a different job** (AppImage build + smoke test, blocked on LWSM-1021) — its bullet now carries the resolution: ADD a step to the existing script, never create a second one. (3) **The version stays four hand-written literals and `importlib.metadata` was REJECTED** (LWSM-1067) — an editable install caches metadata, so the derived value is stale in exactly the window `cut-release` Phase 2 tests the bumped tree. (4) **`ROADMAP.md` is rendered from an Ants MCP SQLite store**, so a hand-edit outside a bullet is silently reverted by the next `roadmap_log` write, and `git checkout -- ROADMAP.md` on a dirty tree destroys uncommitted flips — both happened today. **P04 next: LWSM-1146 (menu bar), then LWSM-1147/LWSM-1031 (themes, dark by default), then LWSM-1018 (settings dialog), LWSM-1148 (profiles).** FP07's five items stay deferred; P03b open. Superseded active step: **CI is GREEN again (2026-08-18, `193226d`) — it had been red on eight consecutive pushes and nobody noticed.** LWSM-1150. **The cause was never a missing check: the two runs executed the same STEPS with different TOOLS.** Local shellcheck 0.11.0 passed `scripts/*.sh`; the runner's apt shipped 0.9, which reports SC2015 on `command -v` guards that 0.11 accepts. Fixed in four parts — the two lines are `if` blocks now; `scripts/ci-tools.env` pins shellcheck/yamllint/actionlint/uv and BOTH `ci.yml` and `local-ci.sh` read it; the gate reports **TOOL DRIFT** (warning locally, fatal under `LWSM_REQUIRE_ALL_TOOLS`, and a different final line so it cannot hide inside a green run); and `.githooks/pre-push` runs the gate, exempting a docs-only push **by path, never by commit subject**. Enable per clone: `git config core.hooksPath .githooks`. `tests/test_ci_contract.py` (15 tests) is what stops it going stale — `ci.yml` may add no check of its own, its install step must INTERPOLATE the pins rather than repeat them, and the hook must never exempt `scripts/`, `.github/`, `src/` or `tests/`. **Two things worth not re-deriving.** (1) **uv is pinned by literal, not interpolation** — `setup-uv` takes a `uses:` input and a `uses:` input cannot read a shell variable, so the contract test asserting equality IS the link. (2) **The version check's first live finding was a false alarm that failed the build**: `go install …@v1.7.12` reports `v1.7.12`, the release binary reports `1.7.12`. `check_version` strips a leading `v` from both sides; five parametrised cases lock both halves, and the harness EXTRACTS the bash function rather than reimplementing it. **Both defects were found by a push, not by reading the YAML — when the gate itself changes, the only proof is a push.** 547 tests green. Superseded active step: **P04 has started, and its first two items are ✅ SHIPPED (2026-08-18)** — **LWSM-1145** (shared column geometry: the rows line up) and **LWSM-1149** (the window opens at a size that fits the list, and the list scrolls). 532 tests green, `./scripts/local-ci.sh` green, verified offscreen against the user's real seven projects and against twenty. **Three things worth not re-deriving.** (1) **Qt syncs nothing between sibling layouts** — each `ProjectRow` owns its own `QHBoxLayout`, which is the whole reason the buttons stepped in and out by the width of each project's name. `MainWindow._align_columns` takes one width per column across every row and is re-run after every `_sync_rows` and after a language or font change; it cannot be settled at construction, because rows are updated in place (LWSM-1131). Its natural widths come from the rendered text and the stored floors, never from `minimumWidth()` — `apply_column_widths` sets a FIXED width, so reading it back makes the column monotonic. A mutant doing exactly that reddens the shrink test. (2) **The scroll area was not in LWSM-1149's filed scope and is the part that mattered most** — without it the window's minimum height is every row it holds, so twenty projects give a window taller than the screen that cannot be shrunk. (3) **Three of LWSM-1149's first-draft tests were vacuous and deleting the whole geometry mechanism left them green.** "A long list does not grow the window" passes trivially against a window that never grows at all. The fix was to pin the short case AGAINST the long case in one test. **Mutate the mechanism out before believing a geometry test.** **P04 next: LWSM-1146 (menu bar), then LWSM-1147/LWSM-1031 (themes, dark by default), then LWSM-1018 (settings dialog).** FP07's five open items stay deferred behind P04 by decision. Superseded active step: **Desktop integration and the scan-root fix are ✅ SHIPPED (2026-08-18)** — LWSM-1142 (`.desktop` entry, icon, `setDesktopFileName`), LWSM-1143 (the installer's icon-cache defect), LWSM-1144 (scan roots read from config). 523 tests green. **The single most important fact from this session: the app was NOT unfinished, it was pointed at a directory that does not exist.** `default_scan_roots()` returned `~/projects` and nothing could change it; pointed at the user's real tree it found 7 projects with ports and launchers on the first try, and the window renders status, port and Start/Stop/Restart/Open per row exactly as LWSM-1010/1016 promised. **Do not diagnose 'the UI is missing' from an empty window again — check the roots first.** The user's live config is `~/.config/localwebservermanager/scan-roots` (one dir per line), currently `/mnt/Games/Scripts/Linux`. Superseded active step: **`LWSM-1133`, `LWSM-1134` and `LWSM-1135` are ✅ SHIPPED (2026-08-18)** — 518 tests green (was 508), `./scripts/local-ci.sh` green, no leaked children. **Three things worth not re-deriving.** (1) **`Supervisor.running()` cannot answer "did the child exit"** — its entry is removed only in `_reap`, which only the stop sequence reaches, so a child that dies on its own stays in the map. That is why LWSM-1134 added `Supervisor.exited()`, built on the non-reaping `_alive`; `Popen.poll()` answers the same question in one line and must not be used, because it reaps and frees the PID that `start_new_session=True` made the process-group id (ADR-0003). (2) **The stop-side overlay clear is keyed on `StopOutcome.port_still_bound`, never on `warning`** — a warning is also emitted when the probe could not be read, and there the port's state is unknown rather than held, so nothing terminal has been observed. A test drives that case and the swapped mutant dies on it. (3) **Mutation earned its keep twice.** Dropping LWSM-1134's `pending is STARTING` guard left all 46 controller tests green and is NOT an equivalent mutant — mid-stop the child is already dead while its port is still bound, so a `stopping` overlay would clear early and the row would flicker. And LWSM-1135's bullet prescribed a `finally`, which run as a mutant fails: the button comes back but the exception still escapes a pool-delivered slot, where PySide6 swallows it and the user is told nothing — so it needed the catch-all as well. **A bullet is a reviewer's reading of a mechanism, not a measurement of it**, for the fifth time. Superseded active step: **`LWSM-1010` and `LWSM-1016` are ✅ SHIPPED (2026-08-14)** — 494 tests green. **The single most useful thing to know before touching the UI again**: the optimistic overlay settles on the state it was heading **for** (`starting` on running, `stopping` on stopped), not on any derived state. `design.md § State management` contains both readings; only this one makes "a slow start keeps the overlay" true, since a server that has not finished binding reads as *stopped*. The design doc was NOT edited — the sentences are reconcilable and the code records which reading wins. **Second**: the trust dialog and the browser opener are both **injected** (`confirm=`, `open_url=`), because a test that reached the real ones would block on a modal or launch the developer's browser. **Third, and the finding of the session**: on LWSM-1016 **four of six mutants survived the first pass**, and each was a genuine gap — no test reached the overlay states, and every fixture had ONE row, so the loop-variable closure bug that makes every row drive the last project was invisible. A one-row fixture cannot see a per-row bug. Superseded active step: **`LWSM-1131` is ✅ SHIPPED (2026-08-14)** — 473 tests green, five consecutive clean full runs. **Three things not to re-derive.** (1) `merge()` reaches the scan through **Protocols** in `registry.py`, never an import: § 4.3's signature names `ScanResult`, and importing it closes the cycle LWSM-1007 § 4.1 measured. (2) The Rescan **write lives in the window's slot**, not in `merge()` — the merge runs on a pool thread and is handed no `LoadResult`. (3) `unlistable_roots` is a new `ScanResult` field and NOT a reading of `skipped`; `skipped` is non-empty on any populated machine, so the blanket reading makes the *missing* flag unreachable in production while a clean fixture passes. **Two flakes were found by the full-suite run and fixed**, both worth knowing: a SIGTERM landing before `sh` had executed its `trap` line, and a `gc.get_objects()` assertion that was session-global and so really asserted "this is the only controller in the process". **Still out of scope and easy to misread as delivered:** nothing acts on `hidden`, a duplicate-identity row shows twice, and the duplicate-port flag's other half — refusing Start for the later claimant — belongs to P05. Superseded active step: **`LWSM-1007` is ✅ SHIPPED (2026-08-14)** — 448 tests green, fifteen mechanisms mutated and fifteen dead. **Next is `LWSM-1131`** (the rescan merge), then LWSM-1010 and LWSM-1016. **Three things not to re-derive.** (1) `LauncherKind` lives in `registry.py` now and `scanner.py` re-exports it; the reverse import stops the package importing at all and an AST test in `test_layering.py` holds the direction. (2) `RegistryMissing` is a **subclass** of `RegistryError`, so `build_window`'s handler is untouched and only the write gate discriminates — folding first run into "unreadable" is what would leave a clean machine permanently read-only. (3) The write gate keys on `rows_refused`, never on `reasons`; a field refusal keeps the row, and keying on the reason list would let one mistyped port disable persistence for a whole session. **The spec needed no fold-back** — every section was built as written, which is what the 2-loop cap was betting on. Superseded active step: **`LWSM-1009` is ✅ SHIPPED (2026-08-14).** `src/lwsm/supervisor.py` + `tests/test_supervisor.py` (27 tests), full gate green at 414. **Next is `LWSM-1010`** — start / stop / restart wired into the window with the bounded optimistic overlay (`design.md § State management`), which is also where LWSM-1046's confirmation dialog lands. **Two things a later session must not re-derive.** (1) The bullet's `SIGKILL … if anything is alive **or** the port is still bound` was NOT implemented, on purpose: ADR-0003 struck that `or` because it fires exactly when our child is already gone and something else holds the port, so it signalled a PID the kernel was free to have reissued. A bound port is now a warning on `StopOutcome`. (2) `TrustStore` is in memory, so a confirmation lasts the session — ADR-0003's "one-time per-project" needs LWSM-1007's writer, and re-asking is the safe direction to be wrong in. **The mutation pass is the finding worth carrying:** twelve mechanisms mutated, eleven died first time, and the twelfth — "the managed child is not reaped before the sequence ends" — survived because its fixture *ignored* SIGTERM, under which a premature `poll()` reads `None` anyway and the assertion holds whether or not the rule does. Superseded active step: **`LWSM-1007` and `LWSM-1131` are both ✅ ACCEPTED (2026-08-13) — at a 2-loop cap, not at convergence.** The umbrella spec was **split** along its § 4 seams (user, 2026-08-12): LWSM-1007 keeps the id and takes the file format and the writer (951 lines); **LWSM-1131 is new** and takes the rescan merge (855 lines). LWSM-1007 keeps the id because LWSM-1039 and LWSM-1008 both declare it and **neither binds to the merge**, so no dependency edge was re-pointed. Gate totals: LWSM-1007 loops 1–2 = 14 + 9 findings, LWSM-1131 loops 1–2 = 10 + 9, **all 42 verified, all fixed, nothing ever resurfaced.** **The gate was then CAPPED by the user (2026-08-13) and LWSM-1007's loop 3 was deliberately NOT run** — see `CLAUDE.md § Review cadence`, which is now the governing convention: ~1 finding in 10 was a defect implementation would not have caught, and a third were the review's own collateral. **Both roadmap bullets stay 📋** — the specs are accepted but implementation is NOT starting on them (see Next gate). |
| **Last update** | 2026-08-25 (**LWSM-1169 and LWSM-1170 shipped and pushed, plus two traps folded into `CLAUDE.md`; tip `67863e6`.** Gate green on each — 1275 tests, no SKIP, no tool drift; mutants 4/4 killed on LWSM-1170, including one modelling the fix as the bullet prescribed it. Ants MCP ANTS-4629 confirmed fixed and marked in the shared feedback file.) Was: (**LWSM-1190, LWSM-1184 and LWSM-1168 shipped and pushed, tip `599ea83`.** Three items, three commits, gate green on each; LWSM-1191 filed from inside the last one. The instrument that earned its keep twice is the live-tree verdict diff — it found LWSM-1190's second instance and proved LWSM-1184 surgical, and no test count can say either. Was: 2026-08-24 (**LWSM-1167 shipped and pushed, tip `b594350`; FP08 down to 13.** `managed` is now derived from who holds the port rather than from our own records — the shape came from **ADR-0004**, not from the bullet, and that ADR carries two rules the bullet did not (the "looks like this project" test may never be gated on; managed identity is the child PID **plus `create_time`**). Six mutants killed, but the `_alive` PID-reuse guard SURVIVED the first pass because `stop()` pops the registry entry, so the test never reached the guard — the replacement uses a launcher that exits on its own. Filed on the way: **LWSM-1189** (two pre-existing tests leak a real `sleep 30` per run) and a new `CLAUDE.md` trap (stopping a child mid-start leaks its grandchild while `StopOutcome` reports success). Earlier the same day: **Three user-requested features shipped, tip `4351ffd`; FP08 otherwise untouched.** `LWSM-1186` version in the title bar. `LWSM-1187` a per-project browser picker in the row — which turned out to duplicate **`LWSM-1055`**, filed 2026-08-06 and found only afterwards, because Phase 0's `invariant_check` reads `docs/specs/` and cannot see a roadmap bullet; **run `task_priors` or `roadmap_query query=<topic>` before building a feature**. Finding it caught a real gap, now fixed: an uninstalled browser must fall back *with a visible message*. `LWSM-1174` was fixed because the picker could not ship without it — the row's controls were 7 px inside `design-accessibility.md`'s ~600 px magnifier band and the picker cost 84 px, so the name column is now capped and elided; the row ends at 561 px. `LWSM-1188` files what 1.0.0 means (the five success criteria + security + a packaged download; P09 and the debt sweep are explicitly OUT). `LWSM-1043` annotated with the finbreak auto-update research the user asked for — its own warning that "build an updater" is likely wrong is untouched, and it is blocked on `LWSM-1021` either way. 1233 green, local-ci green, 13 mutants killed. **Running the app found a bug 1233 tests could not**: accessible names were built from the elided label. Was: 2026-08-23 (**FP08 opened and five items shipped, each its own commit, all pushed; tip `a384ca9`.** 1162 green at the last gate, `local-ci.sh` green, 15 mutants killed across the five items. **One mutant survived and is recorded rather than papered over** — removing `with self._registry.lock` from `Supervisor.reap_exited` while keeping the identity check is equivalent-under-test, since no deterministic test can force that interleaving; the lock stays, because without it the identity check is itself a check-then-act. Also repaired seven doubled CHANGELOG headings in their own commit `99dd410`, and filed the tool-side cause with Ants MCP after reproducing it with `changelog_log dry_run`.) |
| **Superseded (P03 close attempt)** | 2026-08-12 (**P03 close attempted and BLOCKED; `FP06` generated.** `/audit` clean for the fourth close running — ruff, bandit, semgrep, gitleaks, shellcheck all zero, and **the zero was verified by hand** because `audit_run` reported it with `artifacts: 0` on every tool, which is indistinguishable from having read nothing. Three review lanes produced **25 findings, zero false positives**: 9 → `FP06` (LWSM-1122…1130), 16 → `docs/known-issues.md` (017…033) with named owners. **The cross-cutting finding is a fourth non-`OSError` whole-scan crash** — `Path.exists`/`is_symlink` re-raise `EACCES` and `ENAMETOOLONG` on Python 3.13, four call sites are unguarded, and `scan()` catches only `_BudgetExpired`. Two lanes found it with different reproducers and both were reproduced again independently: `chmod 000` on one candidate returns **0 of 20** healthy projects, and a 3000-character hop token does the same from one attacker-written line. Three earlier loops fixed three instances of this class and none fixed the class; LWSM-1122 does it structurally. **The other half is the tests**: 81 mutants, 47 red, **34 green** — including three clauses the spec calls load-bearing (`_BudgetExpired` not being an `OSError`, the dependency-block scope, rule 1's execute bit), all correct today and protected by nothing. A timed-out scan under the first of those reports `timed_out=False`, and LWSM-1007 is about to persist that list. **Deliberate deviation:** no CHANGELOG entry was written for FP06 — nothing is fixed yet and `[Unreleased]` is public) |
| **Superseded (P03 open)** | 2026-08-08 (**P03 started; LWSM-1006's spec is through the gate and implementation is next.** The session's real finding is about the *gate*, not the spec: under the fifteen-dimension brief, loops 1–3 produced 75 findings of which roughly 34 would have changed what gets built — the count held flat at ~25 a loop and never converged, because six of the dimensions can never come back clean and fixing their findings is what introduced the next loop's real defects. **The brief was rewritten to four questions** — is a claim false, do two passages give different behaviour, is a required behaviour unspecified, is a test clause unfalsifiable — with everything else explicitly out of scope. Loops 4–6 then produced 28 findings, **100% build-changing, zero wording**, on a brief 7× smaller (24 KB → 3.4 KB). Global rule 14 has been rewritten around it. Two other instruments now carry work reviewers were doing badly: `LWSM-1006-conformance.py` executes every pattern the spec prescribes and has caught **five** defects including three of my own fixes on the run after I made them; and a **mechanical sweep** of `registry.py`'s twelve defensive mechanisms against the spec found the one gap reviewers had missed — a NUL byte in a hop token raises `ValueError`, not `OSError`, and escapes the scan) |
| **Superseded (P02 close)** | 2026-08-07 (**FP05 complete and P02 closed.** All nine items shipped, every fix mutation-verified, 185 tests up from 159, full gate green. Four of the nine bullets were corrected by measurement — LWSM-1117's wait is unbounded rather than ~3.3 s, LWSM-1116 had an unreported second half, and LWSM-1115's own fix introduced the defect known-issue-005 describes. The rule-14 gate ran as one batched `/cold-eyes` over `coding.md` + `testing.md`: **converged in 2 loops**, 12 then 15 verified findings, all fixed. Loop 2's split was 11 fix collateral vs 4 draft defects, so it converged by sweep rather than a third dispatch. Two user corrections folded in: prose counts of growing sets are now banned and tested (`tests/test_docs.py`), and the `.audit_cache` history exposure is assessed and accepted as known-issue-016) |
| **Superseded** | 2026-08-07 (**FP04's 14 bullets are all closed and green at 150 tests**, up from 125, in ten commits — one per bullet-group, each with its red test first. The 21 held commits plus these are **pushed**; GitHub Actions is healthy again and CI passed on `3ce8b18`. **The pass's own worst moment is the one to remember:** LWSM-1100's first shape put `os._exit` inside `main()`, and since tests call `main()` in-process and an earlier test abandons a probe, the pytest run ended at **40 % of the suite with exit code 0** and a report that read as green. The gate caught it, not review. That is the third time this project has been bitten by a green run that was not one) |
| **Superseded (older)** | 2026-08-06 (**P02 close re-run: BLOCKED again.** FP03's 14 items are all ✅ and the gate is green at 125 tests, verified on **cleared bytecode**. Static analysis clean for the third close running — ruff, bandit, semgrep (9 files scanned, 0 findings), gitleaks (82 commits), shellcheck, actionlint; pyright reports only LWSM-1066's pre-existing one. Three lanes re-read the FP03 code cold and produced **29 findings**, folded into `FP04`. Six reproduced independently rather than taken on the reviewers' word. **The shape is the finding:** FP03 left three of its own fixes half-done and wrote five confident comments that are false) |
| **Blocked on** | — (nothing). The `P02-complete` tag was re-pointed from `a17b7dd` to the closing commit `5225b80` and force-pushed, with the user's explicit authorisation on 2026-08-07 — `commits.md § 4.2` forbids that without it. The old commit predated 37 fix items, so the tag had been asserting a phase complete at a tree missing most of it. **2 commits are unpushed as of 2026-08-08** (`2f01d10` the scanner, `05624ee` its doc amendments) — deliberately, since the push is step 9's decision and P03 has not closed |
| **Next gate** | **FP08 must close before P04 does.** LWSM-1171 … LWSM-1181 left; only then does P04 earn `P04-complete`, which is LWSM-1152's gate for the first 0.1.0 release. **P03b remains open and untouched by any of this** — LWSM-1039, LWSM-1008 and LWSM-1121 are still 📋. |
| **Decision taken (was open)** | **No `/cold-eyes` re-gate for LWSM-1006's spec — user, 2026-08-12.** Global rule 14 says an *authoring* edit re-arms the gate, and § 4.6's rule-3 table was authored-edited on 2026-08-08 during implementation (Vite's script-value test: substring → whole-word). The exemption was granted on two grounds, both recorded here because a skipped gate that leaves no trace is indistinguishable from one nobody thought about: the change was forced by an **executed acceptance test**, which is stronger evidence than a cold read, and the user's standing instruction for this item is **no further review loops** (ROADMAP LWSM-1006's 2026-08-08 note). **This is an exemption, not a precedent** — a rule-14 re-arm is skipped only where an executed test, not judgement, forced the edit |
| **Convergence checkpoint** | 5 (consecutive `FP##` items immediately preceding any ✅-`implement`-Kind close in the active release block — see `~/.claude/commands/close-phase.md § 5a-6`). **Measured 2026-08-06: P02 is ONE feature item (LWSM-1005) that has so far produced 28 fix items across FP03 + FP04** — a 28:1 ratio. Two reasons to expect it not to hold: P02 absorbed every foundational decision at once (logging, threading, theming, accessibility), which later phases now inherit; and the second review found fewer *new kinds* of defect than the first. **If an `FP05` is generated, do not simply work it** — the checkpoint is at 5 and would not fire, but the ratio is the real signal. Stop and ask whether the review process has become the bottleneck, and say so to the user rather than grinding on. Committed to in chat 2026-08-07; recorded here because that promise otherwise lives nowhere. **FIRED AND HONOURED 2026-08-07.** `FP05` was generated (25 findings, 7 HIGH), the ratio was put to the user before any work started, and two decisions came back. **(1) Scope:** `FP05` takes the two root causes and the seven HIGHs; the MEDIUM/LOW tail is routed to the phase that owns the code it lands in, as 15 named-owner entries in `docs/known-issues.md`. P02 therefore ends at 37 fix items, not 54. **(2) Process, standing from now on:** **one `/audit` + `/code-quality-review` per phase, then the phase closes.** Findings above the bar are fixed; the rest are routed to owning phases. The reasoning is that three passes over P02 each found a new *class* of defect rather than repeats — a good argument for reviewing once and a bad one for reviewing until clean, which was turning review into the development method. The convergence checkpoint of 5 stays as a backstop but is no longer the primary control. **RE-FIRED 2026-08-12 for P03, and honoured the same way.** `FP06` is 1 in a fresh chain, so the count does not bind — but the ratio does again: LWSM-1006 is one feature item that produced **25 findings after seven spec-review loops**, and the promise recorded here is to put that to the user rather than grind. It was put, before any fix work began, and the user set the scope: 9 above the bar into `FP06`, 16 routed to `docs/known-issues.md` with named owners. **The number to watch on the next close is not the finding count but the class count** — P02's argument for reviewing once was that each pass found a new *kind* of defect. This pass found two kinds, both new: a fourth instance of the non-`OSError` crash family (three prior fixes, none of which fixed the class) and a mutation-survival rate of 34 in 81 on a suite that had never been mutation-tested as a whole. If the next close finds a third new kind, the review process is still buying something; if it repeats these two, it has become the development method again |
| **Debt-sweep phase threshold** | 5 (auto-prompt for `/debt-sweep` after this many phases without one) |
| **Last debt sweep** | 2026-08-06 (`DS01`, whole history — no dependency drift; doc drift fixed, four items filed to the roadmap) |
| **Repo visibility** | **PUBLIC** (`github.com/milnet01/LocalWebServerManager`, 2026-08-03) — free CI minutes, so pushes need no batching gate |

### Step progress

While an item is active, Claude marks the current step 🚧;
completed steps flip to ✅. Resets to all ⬜ when a new item
becomes active.

**`FP08` is the active item; LWSM-1171 … LWSM-1181 remain as of 2026-08-25** (generated 2026-08-21 by
the P04 close). Steps 5 and 6 of the parent loop are ✅ — they are what
generated it: four cold lanes over placement/geometry, settings and config
I/O, the window's UI surface, and the supervisor's concurrency.

**Two are critical.** LWSM-1163 — one JSON typo plus one window close writes
defaults over every stored setting (reproduced). LWSM-1162 — a launcher
symlinked out of its project is not refused, and its fingerprint is
byte-identical to a launcher that does not exist, so the trust gate never
re-arms on content (reproduced).

**Suggested order.** LWSM-1162 and LWSM-1163 first. Then LWSM-1164 (a
hostile settings file kills startup, and `registry.py` already carries the
guard this one is missing) and LWSM-1165 (a self-exited child is never
removed, so an ordinary crash locks the project out for the session).
LWSM-1163, LWSM-1164 and LWSM-1178 are one family — a reader that cannot say
whether it fell back, and a writer that does not ask — and are cheapest
together. LWSM-1180 is five docstring corrections and can ride along with
whichever item touches each file. **LWSM-1181 is an `investigate`, not a
confirmed defect**: verify it, then fix or dismiss with a reason.

1. ⬜ Verify spec — none expected; `spec-format.md § 1` skip case, twenty
   independent fixes to existing modules. LWSM-1162 and LWSM-1167 touch the
   trust model, so check ADR-0003 and ADR-0004 rather than writing a spec
2. ⬜ Verify dependencies — LWSM-1167 (`managed` semantics) reads on
   LWSM-1165 (the stale entry), and LWSM-1178 shares its answer with
   LWSM-1163. The rest are independent
3. ⬜ Write failing tests — **watch each one red first.** Three of this
   batch exist because a docstring was believed instead of a test:
   LWSM-1163, LWSM-1164 and LWSM-1180 all sit where prose asserted the
   behaviour and nothing checked it
4. ⬜ Implement until tests pass — 0 of 20 items
5. ⬜ Run `check-code` (read `docs/audit-allowlist.md` first — it now has
   allowlist-009 for the bandit B404/B603 subprocess pair)
6. ⬜ Run `review-code` — **once**, per the 2026-08-07 standing rule
7. ⬜ Fold actionable findings
8. ⬜ Update CHANGELOG / ROADMAP / journal — **the CHANGELOG entry for FP08
   belongs HERE, not at generation time.** It was deliberately not written
   when FP08 was filed, because nothing was fixed yet
9. ⬜ Commit, then re-run `/close-phase` to close `P04` and tag
   `P04-complete`

### Active item details

(filled in once Phase A → P01 hands over an active item)

```
Item: LWSM-1007 — Registry persistence and the rescan merge   [ACTIVE]
Phase: P03b (continuation of P03; see the status header for why the suffix)
Spec: docs/specs/LWSM-1007-registry-persistence.md — NOT YET WRITTEN
Policy: docs/decisions/0005-registry-and-rescan.md (ADR-0005) — settled
Branch: main (no feature branch yet)
Dependencies: LWSM-1006 ✅ shipped 2026-08-12
Blocks: LWSM-1039 (backup), LWSM-1008 (first-run flow) — both declare this
Lanes: core, ui, tests
Spec required: YES — spec-format.md § 1, all five triggers, not a close call
  1. on-disk contract      projects.json is hand-editable and schema-versioned;
                           LWSM-1039 binds to its exact shape
  2. three subsystems      registry.py / controller.py / mainwindow.py
  3. a real design choice  ADR-0005 sets policy, not mechanics (see below)
  4. hard to reverse       changing the shape after records are hand-tuned
                           means a migration
  5. edge cases            4 merge outcomes x override-present, the duplicate-
                           port tie-break, partial write failure
Open questions the spec must answer (found while making that call — these
are inputs to /write-spec, NOT deferred work):
  - UNKNOWN vs CHANGED. scanner uses port=None to mean "could not tell,
    never a guess". ADR-0005 refreshes the detected half when "detected
    fields differ". A scan that fails to read a port reports None, which
    differs from a stored 3000, so a known port is silently blanked.
    ADR-0005 has no clause separating unknown from changed. Nothing else
    in the tree does either.
  - What the JSON actually looks like, field by field, and what
    schema_version 1 is.
  - How the merge report reaches the user (ADR-0005 requires the Rescan
    button produce "a visible answer rather than a silent mutation" and
    stops there).
  - Concurrent writers: two app instances, or a hand-edit mid-run.
Sub-findings:
  - 🚧 Step 1: /write-spec LWSM-1007, which carries the rule-14 gate
Tests: 386 passing, 0 failing. Full gate green as of the P03 close.

Item: LWSM-1006 — Scanner implements the detection rules   [SUPERSEDED — ✅]
Spec: docs/specs/LWSM-1006-scanner-detection.md (+ LWSM-1006-conformance.py)
Branch: main (no feature branch yet)
Dependencies: LWSM-1005 ✅ shipped 2026-08-07
Also lands: LWSM-1050 (FP01 security — bounded scanner reads)
Split out:   LWSM-1121 (.env / docker-compose.yml / README + conflict reporting)
Sub-findings:
  - ✅ Spec drafted, gate run to convergence on the four-question brief
  - ✅ Conformance script executes every prescribed pattern — green
  - ✅ registry.py's twelve guards swept against the spec — one gap, closed
  - ✅ Spec Status flipped to accepted; roadmap bullet flipped to 🚧
  - ✅ src/lwsm/scanner.py implemented test-first; all 20 invariants covered
  - ✅ tests/test_layering.py CORE_MODULES widened (+ scanner.py, + applog.py),
       plus the derivation test so it cannot silently miss a module again
  - ✅ The § 12 doc amendments landed (design.md ×7, coding.md § O1,
       ADR-0003's unit-name class, CLAUDE.md, CHANGELOG)
  - ✅ Conformance cases moved into tests/test_scanner.py; the script is deleted
  - ✅ Steps 5-6 RUN ONCE (2026-08-12): /audit clean, review found 25
  - 📋 FP06 (LWSM-1122..1130) must close before LWSM-1006 can
Tests: 370 passing, 0 failing (was 178). Full gate green.

Item: FP06 - nine findings from the P03 close (2026-08-12)
Parent: LWSM-1006. Branch: main. Dependencies: none.
Suggested order (LWSM-1122 first; the rest are independent):
  LWSM-1122  CRITICAL  whole-scan crash, 4 unguarded metadata calls
  LWSM-1123  HIGH      hop-target falls back instead of aborting (§4.5 step 4)
  LWSM-1124  HIGH      _quoted at :605 - the last unescaped reason (INV-18)
  LWSM-1125  HIGH      lock _BudgetExpired not being an OSError
  LWSM-1126  HIGH      lock the package.json dependency-block scope
  LWSM-1127  HIGH      test rule 1's execute-bit precondition
  LWSM-1128  MEDIUM    surrogates in _CONTROL - un-encodable project name
  LWSM-1129  MEDIUM    test PortFinding.source's sanitiser (INV-18 clause 2)
  LWSM-1130  MEDIUM    Vite evidence test must use the comment stripper (§4.6)
Every bullet carries its reproducer and its acceptance criterion.
Three (1125, 1126, 1127) are TEST-ONLY: the code is already correct and
the red test must be shown failing against a deliberate mutation, not
against shipping code - see each bullet for the mutation that works.
```

**One spec correction came out of the implementation, not out of a review**
(`.claude/workflow.md § 2` — surfaced, not absorbed): § 4.6's rule-3 table said
`vite` is matched as a **substring** of the chosen `scripts` value, while the
same section's general rule two paragraphs later says every evidence test is
"exact or whole-word, never a substring" — and § 7's own `vitest` fixture, whose
`"dev"` script is `"vitest"`, comes back `DETECTED` on 5173 under the substring
form against its stated expectation of *unknown*. The acceptance test caught it
on its first run. The table now says whole-word; `design.md` item 6a states the
strict form. **Seven cold-eyes loops and a conformance script did not find this;
running the rules against the corpus did.**

**The one decision taken this session that outlives it:** `design.md`'s
three-level recursive walk is **not built** (user, 2026-08-08). Every launcher
rule matches at the project root and the one deeper file is named by the
launcher, so the walk would feed no reader. The depth bound and the eight
excluded directory names moved onto the one-hop target, and the roadmap's
"`node_modules` is never descended" clause is met by construction — with
INV-20 as its evidence, because that is the one place the decision trades a
mechanism for a claim.

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

### 2026-08-23 — FP08: the four criticals closed, and two vacuous tests found by probe

**1162 tests, up from 1148; six commits, one per item plus a changelog repair;
every fix watched failing first and every mechanism mutation-probed.** Five
roadmap items shipped: LWSM-1162, 1163, 1164, 1182, 1165.

**The pass's durable lesson is new and belongs in `CLAUDE.md`'s trap cluster if
a later session agrees — it is recorded here first because adding it there
re-arms global rule 14's gate, and that call is the user's, not a session's.**

- **PROMOTED to `CLAUDE.md` 2026-08-25** (rule 14 applied: a conformer hitting
  a reddened pre-existing test behaves differently, so it changes what gets
  written — no gate, since CLAUDE.md's Trap cluster records what was measured
  rather than directing new work). LWSM-1184 supplied the second and stronger
  instance, where the test was not wrong at all. Kept below as the record of
  where it came from.

- **A pre-existing test can encode the defect as the contract, and it reads
  exactly like coverage.** LWSM-1162's escaping-symlink refusal was
  unreachable from `start()` because `_contained` returned `None` for the
  escaping case — and
  `test_an_interpreter_script_outside_the_project_is_not_a_launcher` asserted
  precisely that, by name, with a docstring explaining why it was right.
  Fixing the code turned a green test red, which is the only reason anyone
  looked. **Where a defect has survived a review, check whether a test is
  holding it in place before assuming the tests are on your side.** It is the
  inverse of the LWSM-1136 trap already recorded: there the test asserted a
  mechanism nothing called, here it asserted a mechanism that was wrong.

- **Two vacuous tests this session, both mine, both caught by
  `mutation_probe` and neither by reading.** The first was the sequential
  stop-then-reap in LWSM-1165: it never reaches the identity check it claimed
  to cover, because the entry is gone before `running()` is sampled, so
  deleting the guard left it green. Replaced with one that parks the stop
  inside the window by patching `_group_members` — the CLAUDE.md rule that the
  first call has to be HELD OPEN, applied to a third call site. The second was
  the pre-existing test above. **Neither was visible without running the
  mutant**; both looked careful.

- **A survivor that is honestly equivalent-under-test.** Removing `with
  self._registry.lock` from `reap_exited` while keeping the identity check
  survives, because forcing that interleaving needs a preemption between two
  bytecode operations. Recorded in the commit and the roadmap note rather than
  chased. The lock stays: without it the identity check is itself a
  check-then-act. Same category LWSM-1016 recorded.

- **LWSM-1165 was not the one-line fix its bullet implies, and the bullet did
  not say so.** Dropping the entry when the launcher dies orphans a `start.sh`
  that spawns a server and exits — the server survives in the same process
  group and `stop()` signals *through* that entry, so the naive fix leaves a
  running server behind a greyed-out Stop button. The group decides, not the
  launcher. **Fourth or fifth time a fold-in bullet has been right about the
  defect and incomplete about the fix** (FP05 and FP06 both recorded the
  pattern); the guard test is
  `test_a_launcher_that_forks_and_exits_keeps_its_entry`.

- **One fix made another defect worse, within hours.** LWSM-1163's write gate
  is correct, and it turned a BOM in `settings.json` from cosmetic into
  permanently un-writable. Filed as LWSM-1182 and taken immediately out of
  list order rather than left for sixteen items. **A gate that refuses on a
  whole-document failure inherits every over-strict reader beneath it** — the
  second reader, `_leading_comment_block`, failed differently again and was
  found by reading the code, not by reasoning about it.

- **Seven CHANGELOG headings were malformed and the cause is tool-side.**
  `changelog_log op:"add"` wraps `summary` in `**` and appends `(id)`
  unconditionally, so an FP07 batch passing a summary that already carried
  both produced `- ****Title** (ID)** (ID)`. Reproduced with `dry_run` before
  filing. Repaired in `99dd410`; filed to
  `LocalWebServerManager_Ants_MCP_Feedback.md` with a suggested refusal.
  **Pass `summary` as plain text and let `id` place the reference.**

### 2026-08-12 — FP06: all nine closed, and three bullets corrected by measurement

**386 tests, up from 370; six commits, one per bullet-group, every test watched
failing before its fix.** The pass's durable lesson is the same one FP05
recorded and it recurred immediately: **a fold-in bullet is a reviewer's
reading, and three of these nine were wrong or incomplete about their own
mechanism.**

- **LWSM-1126's prescribed mutation is inert.** It asks for `*sorted(
dependencies)` to be appended to the scanned lines and says the result becomes
port 7. `dependencies` is a set of **keys**, so what gets scanned is
`get-port`, which holds no digits — the mutant ran and the suite stayed
193-green. The scope breach that is real is reading `package.json` as an
ordinary source file, and the fixture had to be **pretty-printed** to see it:
minified, the document is one line whose first `:` belongs to `"scripts"`, so
rule 2 stops there and never reaches the dependency pair. A fixture that cannot
fail is exactly what this bullet existed to remove.
- **LWSM-1124's test cannot see its own constant being loosened.** Measured
after writing it: `MAX_REASON_CHARS = 400` leaves it green, because the
assertion is expressed relative to that constant — known-issue-005's exact
shape, one item after that issue was closed elsewhere. The docstring now says
so rather than claiming otherwise. **`scanner`'s copy of that bound is pinned by
nothing**, where `registry`'s is pinned by `test_the_shipped_bounds_are_pinned`;
that gap is open and unrouted, and is the one thing this pass found and did not
fix.
- **Two bullets interlock and neither says so.** LWSM-1122 adds a per-candidate
`except OSError` in `scan()`; LWSM-1125 asserts that a budget expiry inside a
read still reports `timed_out=True`. Under `class _BudgetExpired(OSError)` it is
**1122's new handler** that swallows the signal, so 1125's behavioural test is
now the thing standing between the containment and a truncated scan reporting
itself complete.

**LWSM-1122 was fixed at the class, not at the four call sites the review
named** — the fourth instance of the non-`OSError`-shaped exception escaping a
per-item loop, after `TypeError`, `KeyError` and `ValueError`, each of which had
been closed one call site at a time. Both of its triggers were reproduced first:
`chmod 000` gives `EACCES` from `Path.exists`, a 3000-character hop token gives
`ENAMETOOLONG` from `is_symlink` at a different line, and they are carried as
two parametrised cases for that reason.

**LWSM-1123's control case is what made it diagnosable.** Three of the four
lines in its table detect nothing; the fourth is the same line without the
trailing token, and it passes — which isolates the abort as the only difference.
INV-20's depth fixture is a single token and could never have seen it.

**One flaky test, observed once and not reproduced.**
`test_completed_tasks_do_not_accumulate` reported `2 live tasks after 200
completed polls` on the first full gate run, then passed in 12 whole-file runs
and 4 whole-suite runs. It counts live objects through `gc` and touches nothing
this pass changed. Recorded rather than dismissed: this project has been bitten
three times by a green run that was not one, and an unexplained red is the same
report in the other direction.

### 2026-08-08 — LWSM-1006's spec, and the review that would not converge

**The spec is accepted and implementation has started. The durable finding is
about the gate, not the scanner.**

`/cold-eyes` ran seven loops. Loops 1–3 used the fifteen-dimension brief and
produced 75 findings — roughly 34 build-changing, 41 wording. The count held
**flat at ~25 a loop and never converged**, and the reason is structural: six of
those dimensions (clarity, structure, dedup, examples, token efficiency,
audience fit) can never come back clean, every finding became an edit, and the
edits broke things that were true. All three of loop 3's CRITICALs were defects
that loops 1 and 2's own fixes had introduced.

**The brief was rewritten to four questions** — is a claim false; do two
passages give different behaviour for the same input; is a required behaviour
unspecified; is a test clause unfalsifiable — with wording, structure,
duplication and examples named explicitly out of scope. Loops 4–7 produced 40
findings, **100 % build-changing, zero wording**, on a brief that went 24 KB →
3.4 KB. The user's global rule 14 was rewritten around it the same day.

**Two instruments took over work the reviewers were doing badly.**

- `docs/specs/LWSM-1006-conformance.py` executes every regex, bound and
  predicate the spec prescribes against inputs chosen to break them. It has
  caught **7** defects, three of them my own fixes on the run right after I made
  them — including a rule that fabricated port 23456 out of `PORT = 123456`, a
  stripper that read `# PORT=9999 (old)` as live, and a fix for that stripper
  which then ate `http://localhost:3000`. None needed a model.
- A **mechanical sweep** of `registry.py`'s twelve defensive mechanisms against
  the spec — one command — found the one gap seven reviewer lanes had missed: a
  NUL byte in a hop token raises `ValueError`, not `OSError`, and escapes the
  scan. `registry.py`'s own comment names P03 as the consumer.

**The method matters more than the loop count.** Loop 7's two lanes were given
different methods; the one told to *write the module on paper from the document
alone* found four gaps the adversarial lane did not, because "I cannot write
this line without choosing" is a sharper test than "is this wrong". That is the
argument for stopping review and implementing, and it is why loop 7 is the last.

**Three findings would each have let one hostile project directory crash the
whole scan** — `{"dependencies": 5}` raising `TypeError`, a non-total
`properties()` raising `KeyError`, and a NUL token raising `ValueError`, none of
them an `OSError`. And the containment check defeated itself:
`Path("").resolve()` **is the current working directory**, so an absent
`WorkingDirectory` "resolves inside" wherever the manager was launched from.
Measuring that found 13 of the 14 real user units on this machine print
`!/home/ants` — systemd's `-`/`!` prefixes were being resolved literally.

**Scope decisions taken with the user and not to be reopened:** the three-level
recursive walk is **not built** (every launcher rule is root-level and the one
deeper file is named by the launcher, so it would feed no reader); the `.env` /
`docker-compose.yml` / `README.md` port sources and conflict reporting moved to
**LWSM-1121**; port rule 3's framework default **is** built, with a fixture that
exercises it. Size was explicitly ruled out as a concern — the user's words:
*"I don't care if the spec is 10000 lines as long as it is accurate."*

### 2026-08-07 — FP05: all nine closed, P02 closes, and four bullets were wrong

**The pass's own bullets were corrected four times by measurement**, which is
the thing to carry forward: a fold-in bullet is a reviewer's reading, and this
pass found it understating the defect as often as overstating it.

- **LWSM-1117 said the abandoned-pool wait costs the suite ~3.3 s. It is
  unbounded.** A probe that genuinely never returns hung the interpreter
  indefinitely — killed at three minutes, main thread on a futex joining the
  pool thread. The suite only ever saw 2.6 s because the *fake* probe carries a
  5 s timeout. Four ways to avoid the destructor were tried (drop the
  reference, hold it, reparent, invalidate the Shiboken wrapper) and all four
  hung identically, so there was no new bound to add — only reach to fix.
- **LWSM-1116 had a second half nobody reported.** The end-to-end test failed
  after the named fix landed: `main` called `build_window(default_projects_path())`,
  and Python evaluates the argument *before* the call, so the `RegistryError`
  that LWSM-1026's guard raises was thrown outside the only catch written for
  it. The guard had been present and unreachable since 2026-08-03.
- **LWSM-1114's acceptance became a test rather than a grep**, because the same
  mechanism had been fixed at a single call site three times running.
- **LWSM-1115's own fix introduced the defect known-issue-005 describes** —
  `MAX_REASONS` was asserted relative to itself, so 100 → 100000 would have
  passed. Caught by re-reading the routed owners of the items this pass closed.

**Two tests could not fail for the thing they named, and both were caught by
running them rather than reading them.** LWSM-1118's first version took the
nearest pixel of the whole grab and *passed against the unfixed code*, because
the label's light-grey background sat nearer a near-white dark token than the
black text did. Its second version isolated the ink and still could not assert
the token: with antialiasing on, a name label held **0** pixels of a pure
`#ff00ff` out of 119, across 40 fringe colours. `NoAntialias` made the ink
exactly one colour — 80 px of `#000000` before, 80 px of `#eef0ff` after.

**The rule-14 gate earned its cost on the thing a self-read cannot do.** Two
clauses written in the same pass, by the same author, from the same root
causes — and they contradicted each other in three places, most sharply where
`coding.md § 1.6` recommended a sweep test that `testing.md § 2.1`, `§ 9` and
`§ 3.1` all forbade, with no test type admitting it. Loop 2 then found that
**loop 1's own fixes contradicted each other four more times**, and that loop 1
had introduced a false claim: "`ruff` enforces `snake_case` in the gate" — it
does not, and enabling `pep8-naming` flags nine sites, every one a Qt override
that must be camelCase. Collateral outnumbered draft defects 11 to 4, which is
the documented signal to sweep rather than dispatch a third loop.

**Executing a prescribed command before it shipped caught two wrong forms.**
`§ 2.2`'s revert recipe was ported from CMake/ctest to pytest; `git stash push`
reverts nothing when the fix is committed, and `git checkout HEAD~1` lands on a
revision that still has it. **Both reported the test passing in the "must
FAIL" position** — a mutation that reads as verified having changed nothing.

**Two user corrections landed mid-pass, and both were right.** Prose counts of
growing sets ("five standards", "eight modules") go stale during active
development — and loop 1 had just "fixed" one by substituting a fresh wrong
number for a stale one. Seven sites, second occurrence, so it became a test
(`tests/test_docs.py`). And `.audit_cache`: already gitignored, but four
scan-output files sit in two *published* commits, which `git status` cannot
show. Assessed as 184 doc-drift false positives plus one absolute path, and the
decision not to rewrite published history is recorded as known-issue-016.

**185 tests, up from 159.** Every fix mutation-verified; every acceptance met
or its shortfall stated.

### 2026-08-07 — FP04: all 14 closed, and the fix that faked a green suite

**The pass's own worst defect was mine, and the gate caught it rather than
review.** LWSM-1100 needs the process to stop waiting on an abandoned probe,
and the only mechanism that bounds it is `os._exit` — there is no Qt-level way
to cancel a running `QRunnable` or to stop `~QThreadPool` waiting in its
destructor. Put inside `main()`, it ended the pytest run at **40 % of the
suite, with exit code 0 and a truncated report that read as green**, because
tests call `main()` in-process and an earlier test deliberately abandons a
probe. The fix is structural: a thin `run()` holds anything that ends the
process, `main()` stays callable, and the console script names `run`. **Third
time this project has shipped against a green run that was not one** — after
the shared `actionlint`/`yamllint` flag and the stale `.pyc`.

**LWSM-1110 is the same family and is now closed at the root.** Exporting
`PYTHONDONTWRITEBYTECODE=1` is *not* enough on its own: `compileall`'s job is
to write bytecode so it ignores that variable, and by default it skips a file
whose `.pyc` looks current by the very mtime-and-size test that causes the bug.
The stale bytecode therefore survived the syntax gate and the tests imported
it. `-f --invalidation-mode checked-hash` is what actually closes it. Verified
by planting the trap — a same-second, same-length `120` → `400` substitution
imported as `400`, and as `120` after the new step.

**Three findings were reproduced before being touched and the numbers matched
the reviewers exactly**: 200 live tasks after 200 polls, a 200,038-character
rejection reason, 50 descriptors leaked over 50 refusals. Reproducing is cheap
and it is what made each fix a fix rather than a guess.

**One finding could not be closed the way it was written, and that is recorded
rather than papered over.** LWSM-1109 wanted `self.update()` in `update_from`
covered by a test. A `paintEvent` counter stays **green** with the line
deleted, because the three labels change text on the same tick and the row
repaints regardless — so in P02 there is no observable difference at all. The
test asserts the call, is marked as a deliberate retreat to the mechanism, and
goes red on the mutation, which no test did before. It stops being redundant at
LWSM-1011.

**One Qt behaviour did not do what the fix assumed, and the assumption was
tested rather than trusted.** LWSM-1107's `LanguageChange` handler works
perfectly when the event arrives — but with the loop running and the window the
only registered top-level widget, `installTranslator` returned `True` and Qt
never posted the event to it, while a bare `QMainWindow` in the same shape did
receive it. Unexplained after four probes, out of this project's hands, and no
user-visible impact in P02, which has no language switcher. The test delivers
the event by hand and says exactly what it therefore does not prove.

**Every fix that claims a test was mutation-checked**, and two of them were
rewritten because the first attempt could not fail: the glyph-overlap
assertion compared rectangles in two different coordinate spaces once the
widget was unparented, and the repaint counter above. LWSM-1105's two
mutations previously left the *whole* suite green and now redden exactly one
test each.

**Deliberately not fixed:** `_glyph_color`'s caching behind the equality guard
(unreachable in P02, named at the guard, LWSM-1031 is when it bites), and the
ROADMAP's dated resolution note repeating the false `RecursionError` claim —
a frozen record of what was believed on 2026-08-06, with the correction in the
FP04 bullet instead.

**150 tests, up from 125.** The 21 held commits went out with these; CI is
healthy again and green.

### 2026-08-06 — FP03: all 14 closed, and what the passing tests were hiding

**The pass was shaped by one lesson from the P02 close: three defects had been
sitting behind invariants that PASS.** So every FP03 test asserts the
observable surface rather than the mechanism — the accessibility tree's
children, the rendered pixels, the signal that actually arrives. That decision
paid immediately and repeatedly.

**Two invariants had to be rephrased, not just re-tested.** INV-16 said "no
task is outstanding after `stop()`", which was *true* while its stated purpose
("a snapshot arriving later cannot touch a torn-down controller") was being
violated: `waitForDone` waits for `run()` to return, and the emit inside it is
already queued. INV-4b said "a tick whose probe raised `ProbeError`", which
made it unfalsifiable against the failure that actually shipped — an exception
no clause named never reached a slot at all, so no status was held, nothing was
emitted, and the invariant was satisfied by the loop having stopped. **An
invariant phrased over the mechanism passes whenever the mechanism is intact.**

**Four times a test I had just written could not fail for the thing it named,
and each was caught by mutating the code rather than by reading it:**

- The focus-ring baseline was itself a *focused* render — Qt gives focus to the
  first focusable widget on show — so it reported "no ring" either way.
- The palette test asserted `color(role).isValid()`, which is true for an unset
  role. It passed for exactly the defect it was written to catch.
- The re-polish after a style property change was **deleted** on the strength
  of two tests that stayed green without it; both were blind to it, one
  comparing a freshly built row (correct either way) and one comparing two rows
  wrong in the same direction. The test that sees it forces identical text into
  both labels so colour is the only variable left. It went red at once.
- The unmapped-state test passed a bare `str` where a real new state is an enum
  member, so it hit `.value` instead of the lookup it was aimed at.

**One finding was dismissed with a measurement.** The review held that the
status bar leaves Qt's `AutoText` free to render markup. `QStatusBar` has no
child `QLabel` and paints via `style()->drawItemText`, which is plain-text
only: `<b>bold</b>` drew **508** ink pixels against **232** for `bold`. The
measurement is in the spec so it is not re-raised. The other three parts of
that finding were real and are fixed.

**A fix opened a hole in an earlier fix.** LWSM-1069 put a catch-all in
`run()`; LWSM-1073's abandoned-task path then showed the `emit` calls sat
*outside* it, so `RuntimeError: Signal source has been deleted` escaped the
very method that clause exists to seal. Found because the suite printed it to
stderr **after a green run** — PySide6 swallows it, so exit 0 is not evidence.

**Two placeholders, one real fragility.** The i18n test's translator uppercased
its input, turning `{port}` into `{PORT}`, and the row raised `KeyError` inside
a signal handler. A translation is data from outside the program, so the
placeholder became Qt's `%1` with `str.replace`, which cannot raise whatever
comes back.

**Left deliberately:** `state_running` sits at 4.61:1 — it clears the 4.5 floor
with no margin, and re-tuning a passing value was not this item's scope.
`applog.py:53`'s `_open` override is the one pyright error still standing; it
is the single pre-existing mismatch **LWSM-1066** was filed on, along with
putting the checker in the gate. `ci.yml:53` is 82 columns against yamllint's
80 — a pre-existing warning, not touched.

**Not pushed.** GitHub Actions is degraded, so CI has never run against the new
`uv` pin. 16 commits are queued.

### 2026-08-06 — LWSM-1005: P02 vertical slice, spec-first

**Spec through the gate first, then code.** `docs/specs/` was empty —
54 roadmap bullets and no contract for any of them. LWSM-1005 introduces
a persisted file format and three module contracts every later phase
builds against, so `/write-spec` ran before any implementation.

Three cold-eyes loops, 64 findings, all verified, all fixed, none
dismissed. What the gate actually bought, none of which a self-read
would have caught:

- **The probe was on the UI thread.** `design.md § State management`
  requires a worker unconditionally. Deferring it would have meant
  rebuilding `PortProbe`, `ProjectController` and the signal wiring at
  P06.
- **Two invariants could not fail for the breach they named.** INV-4's
  fixture was a *fresh* controller, which reports the right answer under
  a sticky implementation too; INV-11 named `psutil` and `MainWindow`,
  neither of which its fake-probe fixture has.
- **Loop 2 prescribed `_SnapshotTask(QObject, QRunnable)` without
  running it.** Loop 3 named that omission. Both shapes turn out to work
  under 6.11.1 — but the *justification* in the doc was wrong, and the
  composed-signaller shape is the documented idiom.
- **Both loop-2 lanes agreed the XDG citation was wrong and both named
  the same wrong replacement** (`§ O6`). It is `§ O3`. Verification, not
  consensus, is what caught it — this is the case for Phase 3 existing.

**Loop economics behaved exactly as the skill predicts.** Loop 2 was
~72% fix collateral from loop 1's own edits, loop 3 almost entirely so.
The doc grew 391 → 921 lines across the three loops. At 921 lines it is
large for a spec; if P03 needs one this size, split along the module
seams rather than repeating this shape.

**Beyond the suite:** four invariants mutation-tested — each assertion
watched failing against a deliberately broken implementation. The first
mutation run reported four clean passes because `python` is not on
PATH here (`uv run python3`); the mutants had never been applied. Read
the output, not the exit code.

**`ruff format` formats fenced ` ```python ` blocks inside Markdown**,
and `local-ci.sh` runs it over `.`. The spec failed the gate on its own
code blocks. Recorded in `CLAUDE.md § Module map`.

### 2026-08-06 — FP02: audit + two-lane cold review, 16 findings closed

**Every tool finding was a false positive; every real defect came from
reading.** Same result P01 recorded, now with numbers: 187
`contract_doc_drift` hits plus bandit, vulture, deptry, typos and
yamllint — all verified non-defects, all logged. The two reading lanes
produced 4 CRITICAL, 5 HIGH and 8 MEDIUM, and **not one false positive
between them**.

**The four that mattered**, each reproduced against shipping code before
being touched:

- **`O_NOFOLLOW` was doing about half the job it was added for.** A *hard
  link* is not a symlink, so linking `app.log` to any file the user owns
  fed it every record — the class docstring's stated guarantee was
  false. And `O_NOFOLLOW` does not reject a *FIFO*, where `O_WRONLY`
  blocks until a reader appears: a named pipe at `app.log` hung startup
  indefinitely with no error and no log line. The handler now
  interrogates the fd instead of trusting the path.
- **The gate could report a clean pass while a linter never ran.**
  `actionlint` and `yamllint` shared one flag, so with `actionlint`
  absent — the likelier case, it has no distro package — `yamllint` set
  the flag and suppressed the actionlint skip too: `Local CI passed.`,
  zero SKIPs, exit 0. This is exactly what the `SKIPPED` machinery was
  built to prevent, and it had been defeated by a variable name.
- **An externally deleted log file was lost silently forever.** The
  idempotence guard compared only the path, so it reused a handler
  holding an unlinked inode. logrotate and `systemd-tmpfiles` both do
  this.
- **CI floated its toolchain.** `setup-uv` was unpinned, so CI resolved
  whatever uv was newest (0.12.2) while this project is developed against
  0.11.7 — and `local-ci.sh`'s "Measured on uv 0.11.7" evidence comment
  therefore described a resolver CI did not run.

**One finding was calibrated DOWN rather than fixed, and it is the
instructive one.** The review asked for a symlinked state directory to be
refused. Implementing it broke
`test_idempotent_through_a_symlinked_state_dir`, which exists because a
symlinked `~/.local/state` is ordinary with dotfile managers. Planting
that symlink needs write access to the user's own `~/.local/state`, which
already implies enough access to edit their shell startup files — so it is
no escalation, while refusing it breaks a documented setup. The reviewer
had flagged the same threat-boundary uncertainty itself. **The test suite
is what caught the over-fix**, one run after it landed.

**Two fixes of mine broke things, both caught by the gate rather than by
review.** A `# nosemgrep` whose rule-qualified id is 106 characters
failed ruff's 88-column limit — and placed four lines above the call it
did not suppress anyway, since semgrep honours it only on the offending
line or the one directly above. And a new test **passed for the wrong
reason** on first run: its `SIGALRM` guard raised `TimeoutError`, which
subclasses `OSError` and so satisfied the `pytest.raises(OSError)` it
existed to protect. It now raises a `BaseException` subclass.

**Deliberately left alone: two frozen records.** `LWSM-1026`'s dated
resolution note and the P01 journal entry both still say the handler
stops a symlink, now an understatement. Both are past-tense records of
what was true on 2026-08-03; the FP02 bullets and the CHANGELOG carry the
correction instead of rewriting them.

**Verified after:** full gate green with `LWSM_REQUIRE_ALL_TOOLS=1` (22
tests, up from 14), every analyser clean, re-run audit down to the single
allowlisted class. `/feature-review` then ran all 12 user-visible
promises **by executing them**, including a real 2.7 MB rotation to check
the new `fstat` gate survives `doRollover` — it does, 4 generations, all
0600.

**Tail on the roadmap as `FP02` (LWSM-1064..1068):** bump uv to 0.12.2 on
both sides in one commit, decide whether two instances may share one
`app.log` (needs the ADR-0004 "no lock files" question settled — it reads
as banning *persisted* state, not a single-instance guard), put a type
checker in the gate, and settle where the version number lives.
`LWSM-1068` shipped in the same pass.

### 2026-08-06 — Public-facing docs corrected; three decisions taken, NOT yet implemented

**Session ended here deliberately (user restarted CC). Everything
below is written down because it exists nowhere else.**

**Done and pushed** (`9eacb03` and the three commits before it):

- **P01 is genuinely complete.** LWSM-1001, LWSM-1002 and LWSM-1026
  were still 📋 while their code had been in the tree since
  2026-08-03. Each was verified clause by clause against its own
  acceptance before flipping — pins and runner image, every
  `.gitignore` path plus `uv.lock` tracked, the log's XDG dir,
  1 MiB rotation and `O_NOFOLLOW` handler — and the local gate was
  run green (14 tests, ruff, shellcheck, YAML, entry points). The
  flip notes carry the evidence. **P01 as a phase still stays open
  until FP01's six 🚧 items land in P05/P06** — unchanged.
- **README rewritten where it lied.** It told visitors "design
  complete, no code yet" and "P01 is next" — both false since
  2026-08-03. It also said four standards (five), eight phases
  (ten), and had empty Install/Quickstart stubs. Now: an honest
  Status section separating done from not-done, real Requirements
  and Install sections, and every command in them executed before
  it landed (`uv sync`, `./scripts/local-ci.sh`, the clone URL
  against `gh repo view`).
- **CONTRIBUTING** gained a "the app does not run yet" warning up
  front, names `./scripts/local-ci.sh` as the gate rather than
  saying "run lint and tests", and its version-check command was
  replaced with one that works.
- **CHANGELOG** had **two `### Added` blocks** under
  `[Unreleased]`, the second still saying "nothing yet" while the
  first listed shipped P01 work. Removed.
- One real broken link fixed in `docs/private/`, and
  `design.md § Observability` corrected to `$XDG_STATE_HOME` —
  it stated only the fallback path, while the shipped code is
  XDG-first.

**THREE DECISIONS TAKEN BY THE USER — implement these next.**
None is written into the repo yet:

1. **SECURITY.md → GitHub private vulnerability reporting.** No
   email address anywhere in the repo. Needs the repo setting
   enabled (`gh api -X PATCH repos/milnet01/LocalWebServerManager
   -f security_and_analysis=...`, or the Settings → Security
   toggle) **and** a `SECURITY.md` pointing at the Report a
   vulnerability button. `documentation.md § 2.4` also wants a
   supported-version table — say plainly that no version is
   supported yet because nothing has been released.
2. **CODE_OF_CONDUCT.md → Contributor Covenant 2.1 verbatim**, per
   `documentation.md § 2.5`. Delete the three-line homemade code
   of conduct from `CONTRIBUTING.md` and link the new file
   instead. Its enforcement-contact slot uses the same GitHub
   private-reporting route as decision 1 — **do not put an email
   in it**.
3. **ADR-0007: copy the reasoning in, keep the names as credit.**
   Replace the unresolvable citations
   (`OneUp/updater.py:1932-1966`, `updater.py:1902`,
   `updater.py:541`, `OneUp/tests/gui-smoke.py:282-305`) with a
   description of the technique itself — the one-shot KWin script
   over D-Bus, why a script running inside KWin may place windows
   when the app may not, and the behavioural-test shape — so the
   ADR stands alone for a public reader. Keep `OneUp` /
   `finbreak` / `SystemManager` named as provenance, since the
   value of "proven on real code" is lost if they are stripped.
   This closes the last open item from the design re-gate.

**Known and deliberately not fixed:** `plan-skeleton.md:3` links
`../specs/<ID>-<topic>.md`, which `doc_integrity` reports as a
broken link every run. It is a **template placeholder and correct
as written** — do not "fix" it.

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
