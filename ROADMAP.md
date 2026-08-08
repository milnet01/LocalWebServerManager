<!-- ants-roadmap-format: 1 -->
# LocalWebServerManager — Roadmap

> **Current version:** 0.0.0 (scaffolded 2026-08-03). See
> [CHANGELOG.md](CHANGELOG.md) for what's shipped; this file
> covers what's **planned**.
>
> **Format:** v1 — see
> [docs/standards/roadmap-format.md](docs/standards/roadmap-format.md)
> (spec v1.1). Every actionable bullet carries a stable
> `LWSM-NNNN` ID alongside its phase ID (`P##`, `FP##`, `DS##`,
> `DOC##`, `R##`); the phase ID categorises blocks while the
> stable ID identifies individual bullets within them. ID is
> identity, position is priority, items are tackled
> top-to-bottom. `Dependencies:` lines list **direct**
> predecessors only; transitive prerequisites are implied by
> walking the chain.
>
> **Every bullet carries its full field set** — `Layman:`,
> `Kind:`, `Source:`, `Priority:` — per
> `docs/standards/roadmap-format.md § 3.12`, so the eventual
> migration into the Ants roadmap store is a straight import
> rather than a defaulting exercise.

**Legend** (per `docs/standards/roadmap-format.md § 3.3`)

- ✅ Done (shipped)
- 🚧 In progress (being tackled now)
- 📋 Planned (next up for this phase)
- 💭 Considered (research phase; scope or feasibility uncertain)

**Themes** (per `docs/standards/roadmap-format.md § 3.4`)

- 🎨 Features · ⚡ Performance · 🔌 Plugins · 🖥 Platform
- 🔒 Security · 🧰 Dev experience · 📚 Documentation
- 📦 Packaging · 🐛 Bug fixes · 🔍 Findings fold-in
- 🧹 Cleanup / debt · 📝 Cold-eyes fold-in

**Priority bands** (per `docs/standards/roadmap-format.md § 3.12`)

- `1` CRITICAL · `2` HIGH · `3` MEDIUM · `4` LOW · `5` someday-maybe

---

## Success-criteria coverage

Every phase below traces to a numbered success criterion in
[`docs/discovery.md § Success criteria`](docs/discovery.md), so
nothing ships that nobody asked for and no criterion goes
unbuilt.

| Criterion | Phase that delivers it |
|---|---|
| 1 — zero-config first run finds all seven projects | P03 |
| 2 — start / restart / stop round-trip within 2 s, reachable in a browser | P05 (LWSM-1009, 1010, 1016) |
| 3 — truthful status across app restarts and foreign servers | P06 |
| 4 — port conflicts caught before launch, reassignment persists | P07 |
| 5 — failures readable without a terminal | P08 |

---

## FP03 — Audit + three-lane review fold-in (from the P02 close, 2026-08-06)

Static analysis over the whole tree came back **clean on every source file** —
cppcheck, ruff, bandit, semgrep, gitleaks and shellcheck found nothing, and all
173 sweep findings were `contract_doc_drift` against documentation. Every defect
below came from **reading**, which is the third phase running to record that
result. Three lanes ran cold against the spec's 16 invariants: the data boundary
(`registry`, `ports`), the concurrency boundary (`controller`), and the
presentation layer (`mainwindow`, `theme`, `__main__`).

**Every finding below was reproduced against shipping code before it was
written down.** Two lanes independently found the two halves of the CRITICAL,
neither half being sufficient alone — the cross-lane agreement is what made it
visible.

### 🐛 Bug fixes

- ✅ [LWSM-1069] **FP03: an unexpected exception wedges the poll loop
  permanently, and silently.** Two halves, found by two independent lanes.
  `ports.py:49` catches only `psutil.Error`, which is neither an `OSError` nor a
  `RuntimeError` (verified: both `issubclass` calls return `False`) — while
  psutil's own `_pslinux.process_inet` opens `/proc/net/tcp` unguarded and
  raises a bare `RuntimeError` on a malformed line, so hidepid, an LSM, a
  `/proc`-less container or one corrupt line escapes as itself. `controller.py:68`
  then catches only `ProbeError`, and an exception escaping `QRunnable.run()` is
  **swallowed by PySide6** — the process survives at exit 0, neither signal is
  emitted, `self._task` is never cleared, and `poll_once`'s in-flight guard
  returns early on every subsequent tick for the life of the process.
  Reproduced: after one such exception, ten further ticks issued **zero** probes
  and **zero** signals. There is no dialog, no status change and no further log
  line — the window shows plausible, permanently frozen data. This is the exact
  failure the worker exists to prevent, inverted.
  Acceptance: a probe raising a non-`ProbeError` leaves the loop still polling
  and the failure visible; a red test drives a fake probe raising `RuntimeError`
  and asserts a later tick still probes.
  Dependencies: none.
  **Layman:** If the part that checks which ports are busy hits an unexpected
  error, the app quietly stops checking forever — the window keeps showing
  whatever it last saw, with no hint it has gone stale.
  Kind: fix.
  Source: code-quality-review-2026-08-06.
  Priority: 1.
  Lanes: core, tests.
  Resolved (2026-08-06, d0cb39b): both halves fixed. `PortProbe.snapshot()` now catches `Exception` and keeps the original as `__cause__`; `_SnapshotTask.run()` ends in `except BaseException`, logging a traceback and emitting `failed` so the guard is always cleared. Seven tests, each watched red against shipping code first — they assert a later tick still probes, not that the process survived, since it always survived. Spec corrected too: § 4.2's false whole-surface premise, § 4.3's no-escape rule, INV-4b widened to any failure, new INV-4c, § 6 failure modes. Gate green at 75 tests, LWSM_REQUIRE_ALL_TOOLS=1.

- ✅ [LWSM-1073] **FP03: `stop()` returns while a queued emission is still in
  flight.** `controller.py:122` waits with `QThreadPool.globalInstance().waitForDone()`,
  which waits for `run()` to *finish* — but the `emit` happens inside `run()`
  over a queued connection, so the event is already posted and is dispatched on
  the next event-loop spin. INV-16 therefore passes on its wording ("no task is
  outstanding") while failing its stated purpose ("a snapshot arriving later
  cannot touch a torn-down controller"). Reproduced: zero emissions immediately
  after `stop()` returns, one after a single spin — and `mainwindow.py:127`
  connects that signal, so the late delivery re-enters the window's widgets after
  teardown. Two further defects in the same three lines: the wait is
  **unbounded**, so a probe that never returns makes the app unquittable —
  which `§ 6` does not promise, it promises only a stale display — and it is the
  **global** pool, so the controller's shutdown waits on every unrelated
  runnable in the process, including the per-project reader threads
  `design.md § State management` already plans.
  Acceptance: disconnect both signals before the wait; hold a private
  `QThreadPool` and give the wait a bounded budget.
  Dependencies: none.
  **Layman:** Closing the app can leave one last message arriving after the
  window has gone, and a stuck lookup makes the app refuse to quit at all.
  Kind: fix.
  Source: code-quality-review-2026-08-06.
  Priority: 2.
  Lanes: core, tests.
  Resolved (2026-08-06, 0b2a22f): all three. Both signals are disconnected before the wait (reproduced: one emission arrived a single spin after stop() returned; the test fails again with the disconnect removed). The controller holds a private single-thread QThreadPool (reproduced: stop() took 5.00 s waiting on one unrelated global-pool runnable). The wait is bounded at STOP_WAIT_MS = 2000 — a shutdown budget, not a watchdog, so ADR-0004's "slowness is not failure" is untouched; on expiry the pool and task are deliberately never released, since ~QThreadPool waits unbounded and collecting a running _SnapshotTask would destroy a live C++ object. Also closed a gap this exposed in LWSM-1069's fix: the emits sat outside the catch-all and `emit` on a destroyed signaller was escaping run(); it now has two layers. INV-16 rephrased over delivery rather than mechanism — its old wording was true while its purpose was violated. Gate green at 94 tests.

- ✅ [LWSM-1072] **FP03: the registry read is unbounded, and two exceptions
  escape the contract.** `registry.py:86` calls `path.read_bytes()` with no
  guard on type or size, so — reproduced — a **FIFO** at
  `~/.config/localwebservermanager/projects.json` blocks forever: no window, no
  error, no log line, the least debuggable failure this app can have. A 600 MB
  regular file peaked at 1214 MB RSS. `applog.py` already solved exactly this
  class for `app.log` (`fstat` the fd, demand a regular file); `registry.py` did
  not get it. Separately, `registry.py:94` lets two exceptions escape as
  themselves where INV-15 and `§ 6` promise a `RegistryError` and an empty
  window: a 5000-digit `port` raises `ValueError` (CPython's 4300-digit
  int-parse cap, **not** a `JSONDecodeError`), and deeply nested arrays raise
  `RecursionError`. Both reproduced; `__main__.py:30` catches only
  `RegistryError`, so the app dies with a traceback and no window.
  Acceptance: a FIFO, a device node and an oversized file each become a
  `RegistryError`; both escaping exceptions do too.
  Dependencies: none.
  **Layman:** A damaged or booby-trapped settings file can hang the app on
  startup or crash it, when it is supposed to open an empty window and tell you
  what is wrong.
  Kind: fix.
  Source: code-quality-review-2026-08-06.
  Priority: 2.
  Lanes: core, tests.
  Resolved (2026-08-06, fb2bd11): `_read_bounded()` opens with O_RDONLY|O_NONBLOCK, fstats the fd, refuses anything not a regular file, and reads one byte past a 1 MiB cap so a file that grew between fstat and read is still refused. Deliberately weaker than `applog._require_private_regular_file` and not a call to it — that also demands a single link and our own ownership, right for a log we write and wrong for a config file a user may hard-link. Both escaping exceptions now become RegistryError: the 5000-digit port (CPython's 4300-digit int cap, plain ValueError) and deeply nested arrays (RecursionError, not even an Exception). Six tests watched failing first — the FIFO one by hitting its 5 s alarm — including one asserting a file exactly at the cap still loads, since a size check is as easy to get wrong in the refusing direction. Gate green at 103 tests.

### 🔒 Security

- ✅ [LWSM-1078] **FP03: the registry's rejection reasons carry
  attacker-controlled text unescaped into the status bar.** `registry.py:136,141,146`
  interpolate `raw_name` **raw and unbounded** (unlike `value!r`, which `repr`
  escapes), and that reason reaches both `log.warning` at `__main__.py:38` — where
  an embedded newline forges log lines — and `mainwindow.py:135`
  `statusBar().showMessage(...)`, which unlike the row labels does **not** set
  `PlainText`, so Qt's `AutoText` may render markup in it. A 50 MB name produces a
  50 MB status string. Alongside, two identity defects reproduced in the same
  module: the duplicate-`path` check runs on the **un-normalised** `Path`, and
  `PurePath` keeps `..` — so `/a/b` and `/a/c/../b` both load with no reason
  recorded, defeating `§ 6`'s "two records with one identity is a malformed
  file"; and a `path` containing a NUL byte passes `is_absolute()` and loads,
  though every later `os` call on it raises. P03 will pass these paths as a spawn
  `cwd`, so identity has to be right before then.
  Acceptance: names are `repr`-escaped and clipped; the status bar forces
  `PlainText`; `..` and NUL are normalised or refused.
  Dependencies: none.
  **Layman:** A project name in your settings file can currently smuggle
  formatting or fake lines into the app's messages and log, and two entries that
  point at the same folder by different routes both load.
  Kind: security.
  Source: code-quality-review-2026-08-06.
  Priority: 2.
  Lanes: core, ui, tests.
  Resolved (2026-08-06, 5553d32): three of the four parts fixed, one dismissed with evidence. Fixed — reasons now go through a `repr`-and-clip helper (120 chars), so a newline cannot forge a log line and a 50 MB name cannot flood the status bar; a `..` component is refused rather than normalised (collapsing it lexically is wrong when a component is a symlink, and P03 uses this path as a spawn cwd); a NUL byte in `path` is refused. DISMISSED — "the status bar does not set PlainText, so Qt's AutoText may render markup" is not true of `showMessage`: measured against the pinned 6.11.1, QStatusBar has no child QLabel and paints via `style()->drawItemText`, which is plain-text only. `<b>bold</b>` drew 508 ink pixels vs 232 for `bold` — rendered literally. The measurement is recorded in spec § 4.1 so it is not re-raised. New INV-21. Gate green at 107 tests.

- ✅ [LWSM-1083] **FP03: the pinned `uv` carries a published advisory.**
  `uv 0.11.7` — this machine's toolchain and the version `ci.yml` pins — is
  affected by **GHSA-4gg8-gxpx-9rph** (moderate): uv fails to validate entry-point
  names, so a malicious wheel's `console_scripts` can place an executable outside
  the intended environment, including onto a directory already on `PATH`. Fixed
  in **0.11.15**; the advisory records no workaround. Practical exposure here is
  low — `uv.lock` is committed with 75 hashes and `pip-audit` against the locked
  environment reports no known vulnerabilities in the project's own dependencies
  — but the fix is a version bump that is already scheduled. **This does not
  duplicate LWSM-1064**, it re-frames it: that item is `Kind: chore` on the
  grounds of a floating reference, and the floor is now a security floor rather
  than a tidiness one.
  Acceptance: local toolchain, the `ci.yml` pin and any re-locked `uv.lock` move
  together to ≥ 0.11.15, and `local-ci.sh`'s "Measured on uv 0.11.7" evidence
  comment names the version it was re-measured on.
  Dependencies: LWSM-1064.
  **Layman:** The tool that installs our dependencies has a published security
  hole; updating it was already on the list, but now it has a deadline.
  Kind: security.
  Source: audit-2026-08-06.
  Priority: 2.
  Lanes: build, ci.
  Resolved (2026-08-06, dd574ec): local toolchain and the ci.yml pin both moved to 0.12.2 in one commit — bumping only CI would have re-introduced the local/CI divergence FP02 fixed. The local binary was replaced with the published release, checksum-verified against astral-sh's .sha256 (`uv self update` refused: not a standalone-script install); the 0.11.7 binary is kept in the session scratchpad. Re-locking under 0.12.2 left uv.lock byte-identical. The `--locked, NOT --frozen` evidence comment was RE-MEASURED rather than re-dated: with a dependency added to pyproject.toml and the lock untouched, `uv sync --frozen` exits 0 and `--locked` exits 1 on 0.12.2, as on 0.11.7; dependencies.md § 2.1 carries the same sentence and moved with it. Gate green at 125 tests; pip-audit against the locked environment reports no known vulnerabilities. NOT pushed — GitHub Actions degraded, so CI has not run against this pin.

### ♿ Accessibility

- ✅ [LWSM-1070] **FP03: the only focusable widget in the app draws no focus
  ring.** `mainwindow.py:56` sets `StrongFocus` on `ProjectRow` and nothing paints
  a focus indicator — `QFrame` renders only its frame, and `StyledPanel` does not
  consult `State_HasFocus`. Reproduced by grabbing the widget focused and
  unfocused and comparing: **the two images are identical**. Tab moves an
  invisible caret. `coding.md § O8` clause 2 requires "a visible focus ring",
  `design.md § Accessibility` calls it the thing "the magnifier user's 'where am
  I?' depends on entirely", and WCAG 2.4.7 is unmet — against a primary user who
  is partially sighted and reads with a magnifier.
  Acceptance: focused and unfocused renders differ; the ring's contrast is
  asserted against the `testing.md § T8` floor, not merely its presence.
  Dependencies: none.
  **Layman:** When you move around the window with the keyboard, nothing shows
  you where you are.
  Kind: accessibility.
  Source: code-quality-review-2026-08-06.
  Priority: 1.
  Lanes: ui, tests.
  Resolved (2026-08-06, 63f62ce): `ProjectRow.paintEvent` paints the ring `QFrame` does not, in the `accent` token expanded by `Theme.focus_ring_color()` (§ O7 forbids a widget building a QColor), at a pen width derived from the text metric so it survives LWSM-1032's 200 % setting. Measured: 858 of 6734 pixels change between the focused and unfocused grabs, ring width 2 px, contrast 5.42:1 against `window` — over § T8's 3:1 indicator floor. Asserted by rendering, since focusPolicy/hasFocus/accessible name were all already correct while the images matched. Watched failing with the ring neutered. New INV-17; `tests/contrast.py` holds the WCAG arithmetic, shared with LWSM-1075. Gate green at 79 tests.

- ✅ [LWSM-1071] **FP03: the decorative glyph is announced by a screen reader,
  and a code comment says it is not.** `mainwindow.py:64` calls
  `self._glyph.setAccessibleName("")`, and the comment above it states the glyph
  is "also hidden from the AT tree so a screen reader walking children does not
  find it either". That is **not what the call does**: `QAccessibleDisplay` falls
  back to `QLabel::text()` when the accessible name is empty. Reproduced by
  querying the live interface — the row exposes **four** children and child 0 is
  named `'●'`. INV-6 passes because its assertion only covers the *row's* name
  (correctly `'running, demo, port 8080'`), so the test cannot see the surface
  Orca actually walks. The defect is worse than an unhandled case because it is a
  reviewed-and-believed comment recording a behaviour Qt never provided.
  Acceptance: the glyph is either painted rather than labelled, or merged into
  the state label; the test asserts against the **AT tree's children**, not only
  the row name.
  Dependencies: none.
  **Layman:** The little status dot is read aloud as "black circle" by a screen
  reader, which is exactly what a note in the code claims cannot happen.
  Kind: accessibility.
  Source: code-quality-review-2026-08-06.
  Priority: 2.
  Lanes: ui, tests.
  Resolved (2026-08-06, 1b82a90): the glyph is painted in `ProjectRow.paintEvent` into a column reserved by widening the layout's left content margin, so it is not a widget and cannot be a child of the AT tree. Qt Widgets has no ignored flag — Qt Quick's `Accessible.ignored` has no widget equivalent — so leaving the tree means not being a widget. `Theme.state_color()` expands the token, since § O7 forbids widget code building a QColor. Reproduced first as ['●', 'running', 'a', 'port 5005']; the test now asserts childCount() and each child's name equals exactly ["running", "a", "port 5005"]. A second test guards the other direction — every AT assertion would also pass if the glyph were simply deleted, so it blanks the glyph and re-renders, the difference being the glyph. Exact-colour matching was tried and fails for '○' and '?' (antialiased strokes). New INV-19; § 4.4's accessibility-ignored claim corrected. Gate green at 92 tests.

- ✅ [LWSM-1074] **FP03: the row's cells are flung to opposite ends of the
  window.** `mainwindow.py:79` gives `stretch=1` to the **name** cell, so all
  slack is absorbed inside that label — and `QLabel`'s default alignment is
  `AlignLeft`, so the name's text stays at the left while the port cell is pinned
  to the right edge. Measured: at 1400 px the name text renders at x=84 and the
  port text at x=1333. `design.md § Accessibility` names this exact anti-pattern
  ("never name on the far left and state on the far right, which forces a pan and
  a memory test"), and LWSM-1032's own check is "assert name, state, port and
  controls all fall inside a 600 px-wide window" — which this fails at any width
  above it. One-line fix: add the port, then `addStretch(1)`.
  Dependencies: none.
  **Layman:** Widen the window and a project's name and its port drift to
  opposite edges, so you have to sweep the magnifier across to read one row.
  Kind: accessibility.
  Source: code-quality-review-2026-08-06.
  Priority: 2.
  Lanes: ui, tests.
  Resolved (2026-08-06, 846c514): the stretch moved off the name cell to after the last cell, so slack lands outside the row's content instead of inside a left-aligned QLabel. Reproduced first at 1400 px with the port cell ending at x=1371; it now stays inside LWSM-1032's 600 px band. A second test asserts the cells keep their order without overlapping, guarding the over-correction. New INV-20. Gate green at 94 tests.

- ✅ [LWSM-1075] **FP03: `state_unknown` fails the contrast floor in the default
  palette.** `theme.py:62` sets `state_unknown="#8a6d1f"`, which against
  `window="#f4f4f6"` computes to **4.46:1** — below the 4.5:1 that
  `testing.md § T8` and `design.md § Accessibility` require of every text pair.
  Computed against the shipped values, not estimated. `state_running` passes at
  4.61:1 but with no margin. This is the *default* palette, so it is what a first
  run gets. The contrast test is currently scheduled with LWSM-1031 alongside the
  other palettes; the palette that fails already exists, so the test should land
  now rather than with them.
  Acceptance: every token pair in `Theme.default()` clears 4.5:1, asserted by a
  test that computes the ratio rather than eyeballing it.
  Dependencies: none.
  **Layman:** The colour used for "unknown" is slightly too faint against the
  window to meet the readability standard the project set itself.
  Kind: accessibility.
  Source: code-quality-review-2026-08-06.
  Priority: 2.
  Lanes: ui, tests.
  Resolved (2026-08-06, 6c101b4): `state_unknown` darkened #8a6d1f → #856819, 4.46:1 → 4.79:1 against `window`. The test computes the ratio and is parametrised over tokens AND themes, so LWSM-1031's palettes inherit it. Measured: text 15.63, muted_text 6.21, state_stopped 6.21, state_unknown 4.79, state_running 4.61. `tests/contrast.py` is pinned to WCAG's published values first (21:1 black-on-white, the #767676/#777777 borderline) because a miscomputed ratio passes every palette silently; it reproduced the review's own 4.46 and 4.61 before anything changed. `state_running` left alone — it clears the floor, and re-tuning a passing value was not in scope, but it has no margin either. New INV-18. Gate green at 85 tests.

- ✅ [LWSM-1076] **FP03: a state change is never announced, and every row is
  re-styled on every tick.** Two halves of one fix. Qt does **not** notify AT-SPI
  when an accessible name changes, and `mainwindow.py:101` only calls
  `setAccessibleName` — so `design.md § Accessibility`'s promise that "a state
  change announces itself once" is unimplemented; it needs a
  `QAccessible.updateAccessibility` event. But `_sync_rows` (`:137-146`) calls
  `update_from` on **every** row on every signal, re-applying the style sheet and
  the accessible name unconditionally — `QLabel::setText` short-circuits, those
  two do not. Spec § 4.4 says "the changed rows' text and tokens only". Adding
  the announcement without fixing the second half turns a once-a-second no-op
  into a once-a-second re-announcement of every unchanged row, which is the
  failure INV-13 exists to prevent arriving by another route. `RowView` is a
  frozen dataclass, so an equality early-return is free.
  Dependencies: none.
  **Layman:** A screen reader is never told when a project's status changes —
  and the naive fix would make it read the whole list out once a second instead.
  Kind: accessibility.
  Source: code-quality-review-2026-08-06.
  Priority: 2.
  Lanes: ui, tests.
  Resolved (2026-08-06, d57b097): both halves together. `update_from` raises a `QAccessibleEvent(NameChanged)` — Qt never notifies AT-SPI on an accessible-name change, so the promise was unimplemented — and returns early when the `RowView` is unchanged, since `_sync_rows` calls it on every row on every signal and only `QLabel::setText` short-circuits. Verified the guard is load-bearing by removing it: the never-re-announced test goes red. `QAccessible.installUpdateHandler` is not exposed in PySide6 (checked against the pinned 6.11.1) and AT-SPI is unreachable headless, so the tests count the call itself — weaker than preferred, and the strongest surface available; recorded in the spec. New INV-22. Gate green at 109 tests.

- ✅ [LWSM-1081] **FP03: no user-visible string is translatable.** `grep` for
  `.tr(` and `QCoreApplication.translate` across `src/` returns **zero** hits,
  against `coding.md § 5.2`'s "wrap user-visible strings in `tr()`". Affected:
  the window title, `port …` / `no port`, the three status words, the two
  logging notices and the argparse description. The status words are the
  interesting case — they come from a core `StrEnum` that the UI renders with
  `str()`, so translating them needs a UI-side display map rather than a wrapper,
  which is a design decision worth recording rather than an edit. Filed at LOW
  priority: the project ships no translations and has no translator, so this is
  about not making the retrofit worse, in the same spirit as `§ O8`.
  Dependencies: none.
  **Layman:** None of the words in the window could be translated into another
  language yet.
  Kind: enhancement.
  Source: code-quality-review-2026-08-06.
  Priority: 4.
  Lanes: ui, core.
  Resolved (2026-08-06, 304e904): the window title, port text and the three status words go through one `QCoreApplication.translate` context. The status words get a UI-side display map (`state_word()`) rather than a wrapped enum — wrapping the core StrEnum would put user-visible text in a core module, which is the design decision the bullet said to record. The placeholder is Qt's `%1` substituted with `str.replace`, not `str.format`: found when the test's uppercasing translator turned `{port}` into `{PORT}` and the row raised KeyError inside a signal handler — LWSM-1082's crash class by a new route; `replace` cannot raise, so a bad translation loses the number rather than the window, and there is a test for that. Log messages and the argparse text are deliberately untranslated (logs match the source; translating the CLI text needs Qt before argparse, which INV-14 forbids). Tested by installing a QTranslator and reading the rendered text, since a wrapper that is never consulted looks identical to one that is. Gate green at 125 tests.

### 🧹 Cleanup / debt

- ✅ [LWSM-1077] **FP03: the theme layer owes a generated style sheet, and the
  widget is composing CSS instead.** Spec § 4.4 and `design.md § Tokens, not
  colours` both say a `Theme` expands into a `QPalette` **and** a generated style
  sheet — finbreak's two-layer split. `theme.py` implements `to_palette()` and
  nothing else, so `mainwindow.py:96-97` hand-builds `f"color: {token};"`.
  INV-8b still passes (there is no colour *literal*), but the layer the design
  asked for is absent and its job has leaked into widget code, which is what
  `§ O7` exists to prevent one level up. Cheaper to add now than after LWSM-1031
  lands six more palettes against the same seam. Also: `to_palette()` sets 8
  roles and leaves `Button`, `ButtonText`, `HighlightedText` and `ToolTipBase` at
  the style default, so P05's buttons will not follow the theme.
  Dependencies: none.
  **Layman:** The colour rules are being written inside the window code instead
  of in the one place that is supposed to own them.
  Kind: refactor.
  Source: code-quality-review-2026-08-06.
  Priority: 3.
  Lanes: ui.
  Resolved (2026-08-06, 6279c35): `Theme.style_sheet()` generates one rule per state selecting on a dynamic property, set once on the window; the row sets a property instead of composing CSS, and re-polishes. `to_palette()` also fills Button, ButtonText, HighlightedText, ToolTipBase and ToolTipText, which were at the style default. Two test lessons recorded in the spec as INV-23: the re-polish was deleted partway through on the strength of two tests that were blind to it (one compared a freshly built row, whose first polish is correct either way; one compared two rows wrong in the same direction) — the test that catches it forces identical text into both labels so colour is the only remaining variable. And the palette test first asserted `color(role).isValid()`, which is true for an unset role, i.e. it passed for exactly the defect it was written to catch; it now asserts each role against its token. Gate green at 117 tests.

- ✅ [LWSM-1079] **FP03: a failing probe logs once a second, for ever.**
  `controller.py:150` logs a WARNING on every failed poll, and the poll is
  1000 ms — so a permanently unreadable socket table (a hardened kernel, a
  persistent `AccessDenied`) writes roughly **86,400 lines a day** into a handler
  that rotates at 1 MiB keeping 5, discarding the history the user is told to
  consult. Log the first failure, then only when the message text changes, with a
  count.
  Dependencies: none.
  **Layman:** If port-checking keeps failing, the app writes the same complaint
  every second until it has scrubbed away everything else in the log.
  Kind: fix.
  Source: code-quality-review-2026-08-06.
  Priority: 3.
  Lanes: core.
  Resolved (2026-08-06, 04e8658): logged on the first failure, then only when the message text changes. Suppressed by message rather than by count — a different failure is news, and there is a test for that direction too. The suppressed count is flushed when the message changes, when a poll succeeds, and on stop(), so silence and suppression are never indistinguishable and a run's count does not die with the process. A success clears the state, so a failure recurring after a recovery is logged again. Gate green at 112 tests.

- ✅ [LWSM-1080] **FP03: three type errors in `registry.py`, and a missing
  return annotation on the seam INV-15 depends on.** `pyright` reports
  `registry.py:74` twice and `:76` once: `_is_int()` returns a plain `bool`, so a
  checker cannot narrow `value: object` to `int`, and both the range comparison
  and the return fail. **Correct at runtime** — the `or` short-circuits — so this
  is a typing defect, not a bug; the fix is one import and one annotation
  (`TypeGuard[int]`). Separately `__main__.py:11` declares
  `def build_window(projects_path: Path):` with no return type, where spec § 4.5
  gives `-> tuple[MainWindow, ProjectController]`; `from __future__ import
  annotations` is already in force so it costs no import. **This is the evidence
  for LWSM-1066**, which was filed on the strength of one pre-existing mismatch:
  a single phase of new code added three more, which is what an ungated checker
  does.
  Dependencies: none.
  **Layman:** A type-checking tool finds four small mistakes that nothing in our
  build currently looks for.
  Kind: fix.
  Source: audit-2026-08-06.
  Priority: 3.
  Lanes: core, build.
  Resolved (2026-08-06, 2bba9f7): `_is_int` is now `TypeGuard[int]`, which narrows `object` at the call site and closes all three registry.py reports; `build_window` carries spec § 4.5's `-> tuple[MainWindow, ProjectController]` via a TYPE_CHECKING block, so the runtime imports stay inside the function and INV-14's no-Qt-for---version property is untouched. Also fixed one this pass introduced: LWSM-1071's glyph column unpacked `getContentsMargins()`, typed `object` in PySide6 — now `contentsMargins()` -> QMargins. pyright 5 errors → 1, the survivor being applog.py:53's `_open` override, the single pre-existing mismatch LWSM-1066 was filed on and left for it along with putting the checker in the gate. Gate green at 112 tests.

- ✅ [LWSM-1082] **FP03: the low-severity tail from the P02 review.** Each
  verified, none urgent, grouped so they are not lost. `mainwindow.py:137`
  `_sync_rows` only ever **adds** a row — nothing removes one when
  `controller.rows()` shrinks, so a removed project would linger showing its last
  observed state, which `§ O5` forbids; harmless in P02 where the list cannot
  change, but the signal is already named `projects_changed`. `__main__.py:90-95`
  — if `build_window` or `app.exec()` raises, `controller.stop()` never runs and
  a pool thread outlives the controller, the race INV-16 exists to prevent; wants
  `try/finally`. `mainwindow.py:84-85` computes both minimum widths **once**,
  with no `changeEvent`/`FontChange` handler, so LWSM-1032's promised 100–200 %
  text-size control will leave them stale. `mainwindow.py:90` `STATE_GLYPHS[...]`
  raises `KeyError` inside a signal handler if a state is ever added — a UI crash
  rather than a missing glyph, and LWSM-1011 adds four states. `mainwindow.py:125`
  types `_rows` as `dict[object, ProjectRow]` where the key is always a `Path`.
  `registry.py:94` decodes with `utf-8` rather than `utf-8-sig`, so a BOM added
  by an editor — invisible in that editor — refuses the file with a confusing
  reason. `registry.py:59` `Path.home()` can raise `RuntimeError`, uncaught,
  before any logging exists.
  Dependencies: none.
  **Layman:** Seven small things worth tidying, none of which breaks anything
  today.
  Kind: fix.
  Source: code-quality-review-2026-08-06.
  Priority: 4.
  Lanes: core, ui.
  Resolved (2026-08-06, 812b871): all seven. `_sync_rows` removes rows as well as adding them; `main` wraps show()/exec() in try/finally so `controller.stop()` always runs; the row's minimum widths moved into `_apply_text_metrics`, re-applied on a FontChange `changeEvent`; `STATE_GLYPHS` and `Theme.state_token` are both `.get()` with a fallback, so a state LWSM-1011 adds is a missing glyph rather than a UI crash inside a signal handler; `_rows` is typed `dict[Path, ProjectRow]`; the registry decodes `utf-8-sig` so an editor-added BOM no longer refuses the file; and `Path.home()`'s RuntimeError becomes a RegistryError, which INV-15 already turns into an empty window. Five tests — the try/finally and the annotation are structural and carry none. Gate green at 122 tests.

---

## FP04 — Second three-lane review fold-in (from the re-run P02 close, 2026-08-06)

Static analysis was clean again — ruff, bandit, semgrep (9 files scanned, 0
findings), gitleaks (82 commits), shellcheck and actionlint all found nothing,
and pyright reports only the pre-existing `applog.py:53` that LWSM-1066 owns.
Every defect below came from reading, for the third close running.

Three lanes re-read the FP03 code cold: the data boundary, the concurrency
boundary and the presentation layer. **29 findings.** The shape is the point:
FP03 fixed 14 real defects and, in doing so, left three of its own fixes
half-done and wrote four confident comments that are false. A fix-pass is not
self-verifying — this is the evidence for reviewing one.

**Every finding below was reproduced against shipping code before it was written
down**, and the four most serious were re-reproduced independently rather than
taken on the reviewers' word.

The pass also surfaced a **tooling** defect that is not about this project's
code at all: a same-second edit-and-revert whose replacement text is the same
byte length leaves Python running stale bytecode, because the default `.pyc`
validation compares only the source's mtime and size. A green test run then
reports on code that is not on disk. Filed as LWSM-1110.

- ✅ [LWSM-1098] **FP04: `stop()`'s disconnect does not cancel an emission that is already posted, so INV-16 is still violated.**
  LWSM-1073 disconnected the task's signals before waiting, and that closes
  only the window it was measured against. Qt dispatches a `QMetaCallEvent`
  that has already been **posted** regardless of a later disconnect, so a
  probe that finishes just before `stop()` still delivers on the next spin.
  Reproduced independently of the reviewer: emissions `[]` when `stop()`
  returned, `[1]` after one `processEvents()`, status rewritten to `running`.
  The disconnect only helps when the emit has not yet happened.

  **The test written for this cannot fail against it.**
  `test_no_snapshot_is_delivered_after_stop` sets the gate and calls `stop()`
  immediately, so the emit lands *inside* `waitForDone`, after the
  disconnect. Letting the probe actually finish first makes the same test
  fail. It catches "no disconnect at all" and not "disconnect too late",
  which is the defect present.

  Reachable damage today is the test suite, where the fixture stops a
  controller while pytest-qt keeps spinning; `__main__` stops after
  `app.exec()` returns, so that one call site never spins again. Any future
  reload path or `closeEvent` makes it live.
  Acceptance: a `_stopped` flag the slots themselves check (or
  `removePostedEvents`), and a test that lets the probe complete before
  `stop()` and still sees zero emissions.
  **Layman:** Closing the window can still let one last status message arrive afterwards — the fix for this landed earlier today and only closed half the gap.
  Kind: fix.
  Lanes: core, tests.
  Source: code-quality-review-2026-08-06b.
  Resolved (2026-08-07, a3804b2): a `_stopped` flag checked inside the slots, replacing the disconnect — Qt dispatches an already-posted QMetaCallEvent regardless of a later disconnect. The test now lets the probe COMPLETE before stop() and went red at [1] == [] first. The same flag guards poll_once.

- ✅ [LWSM-1099] **FP04: one `_SnapshotTask` and one `_SnapshotSignals` leak per poll, for the life of the process.**
  `setAutoDelete(False)` means the pool never deletes the task, and
  `QThreadPool.start()` has already transferred ownership to C++, so the
  slot setting `self._task = None` frees nothing. Measured independently:
  **200 live `_SnapshotTask` objects after 200 completed polls**, one per
  poll, ~2.5 KiB each — about **210 MiB/day** at the 1000 ms interval.
  Each leaked signaller is a live `QObject` still holding two connections
  into the controller, so the connection list grows without bound too.

  **Pre-existing, not introduced by FP03** — `setAutoDelete(False)` dates
  from `a17b7dd`. FP03 reworked `run()` and the pool and did not catch it.
  The spec asserts the opposite in § 10: "the ceiling is one task, not one
  per tick elapsed". That sentence is false and is part of this fix.

  The original comment is still right that the pool must not free a task
  while a queued emission is in flight, so the fix is not simply flipping
  `autoDelete` back on.
  Acceptance: live `_SnapshotTask` count is flat across 200 polls, asserted
  by a test; § 10's ceiling claim matches what the code does.
  **Layman:** The app slowly eats memory while it sits there watching — about 210 MB a day, in a program meant to stay open.
  Kind: fix.
  Lanes: core, tests.
  Source: code-quality-review-2026-08-06b.
  Resolved (2026-08-07, a3804b2): the signaller moved onto the controller and is created once, so the task keeps auto-delete and the pool frees it as run() returns. Reproduced first at 200 live tasks and 200 live signallers after 200 polls; test_completed_tasks_do_not_accumulate now asserts a flat count. Spec § 10's false ceiling claim corrected with the measurement.

- ✅ [LWSM-1100] **FP04: the abandoned-pool list defers the unbounded wait to interpreter shutdown instead of removing it.**
  LWSM-1073 bounded `stop()` at `STOP_WAIT_MS` and moved a still-running
  pool into a module-level `_ABANDONED` list, on a stated premise that is
  **factually wrong**: "deliberately never released ... holding these is the
  point, not an oversight". CPython releases module globals at interpreter
  shutdown, which runs `~QThreadPool`, which calls `waitForDone()` with no
  timeout.

  Reproduced independently with a 4 s probe and `STOP_WAIT_MS = 100`:
  `stop()` returned in **0.10 s** exactly as designed, and the **process
  took 4.16 s** to exit. § 6 promises a stale display, not a process you
  cannot quit — the outcome the budget exists to prevent, moved thirty lines
  later.
  Acceptance: total process wall time after `stop()` is bounded, asserted by
  a subprocess test that measures exit rather than `stop()`; the comment
  states the mechanism that actually holds.
  **Layman:** The app can still refuse to close for as long as a stuck lookup takes — the bounded-wait fix moved the freeze to the very end of shutdown instead of removing it.
  Kind: fix.
  Lanes: core, tests.
  Source: code-quality-review-2026-08-06b.
  Resolved (2026-08-07, ab407f0): exit_without_waiting_for_abandoned_probes os._exit()s after flushing, and only while an abandoned pool still holds a thread. Reproduced first: stop() 0.10 s, process exit 4.16 s. The call lives in a new run(), not main() — placed in main() first, it ended the pytest run at 40% of the suite with exit code 0 and a report that read as green. Console script now names lwsm.__main__:run, pinned by a test. Subprocess test 30.2 s red -> 0.59 s green.

- ✅ [LWSM-1101] **FP04: the glyph column is stale after a font change, so the state glyph is clipped at 200 % text.**
  `_glyph_width` and the widened left content margin are computed once in
  `__init__`; `changeEvent`'s `FontChange` branch calls
  `_apply_text_metrics`, which recomputes only the state and port minimum
  widths. `paintEvent` draws into `QRect(self._glyph_x, 0,
  self._glyph_width, ...)`, and `drawText` **clips** to that rectangle.

  Reproduced independently — reserved width stays 13 px while the glyph
  needs 14 px at 2x and 22 px at 3x, so it already over-runs at 200 %:

  | scale | reserved | needed | clipped |
  |---|---|---|---|
  | 1.0 | 13 | 7 | no |
  | 2.0 | 13 | 14 | yes |
  | 3.0 | 13 | 22 | yes |

  This breaks `coding.md § O8` clause 4 ("reflows at 200 % text size without
  clipping") — and `_apply_text_metrics`'s own docstring states the
  opposite of what it does, which is the LWSM-1071 shape again: a
  reviewed-and-believed comment describing behaviour the code never had.
  Acceptance: the glyph column and the left margin are recomputed on
  `FontChange`; a test asserts the rendered glyph is not clipped at 200 %,
  not merely that a minimum width changed.
  **Layman:** Turn the text size up for readability and the little status dot gets sliced in half — which is exactly the setting the people who need it will be using.
  Kind: accessibility.
  Lanes: ui, tests.
  Source: code-quality-review-2026-08-06b.
  Resolved (2026-08-07, 4e248ec): the glyph column and left margin are derived in _apply_text_metrics from a stored base margin. Reserved 13/20/28 px at 100/200/300% against 7/14/22 needed; ink strictly inside the column at every scale and the 300% glyph recovers its clipped pixels (195 -> 237). The test asserts rendered ink bounds, not that a width changed.

- ✅ [LWSM-1102] **FP04: a rejection reason built from a *port* field is completely unbounded.**
  `_port_or_reason` interpolates `{value!r}`, which escapes but does **not**
  clip; `_quoted()` is applied to `name` and `path` and never to the port
  value. Reproduced independently: a 200 KB string in `port` produced a
  reason of **200,038 characters** against a `MAX_REASON_CHARS` of 120. The
  ceiling is the 1 MiB file cap, so a hand-edited file yields a ~1 MiB
  status-bar string and a ~1 MiB log record into a handler that rotates at
  1 MiB keeping 5 — scrubbing the history the user is told to consult.

  This is LWSM-1078 left half-done, and the spec records **why** it was
  missed: INV-21's own *Breaks when* clause asserts `{value!r}` on the port
  fields "already did the right thing". That is half true — escaping yes,
  bounding no — and the false half is what made the call site look finished.
  Acceptance: every rejection reason is bounded whatever the file contains,
  asserted against `MAX_REASON_CHARS` rather than a loose literal; INV-21's
  clause corrected.
  **Layman:** The fix that stopped a project's name flooding the status bar was applied to the name and the folder path, and missed the port field right beside them.
  Kind: security.
  Lanes: core, tests.
  Source: code-quality-review-2026-08-06b.
  Resolved (2026-08-07, d4ec994): _port_or_reason routes the value through _quoted, and _quoted now escapes THEN clips so the bound is the constant rather than ~10x it. Reproduced first at 200,038 characters. INV-21's Breaks-when clause corrected — its false half is why LWSM-1078 stopped at the name and path.

- ✅ [LWSM-1103] **FP04: two records still share one filesystem identity via a doubled leading slash.**
  Reproduced independently: `/srv/a` and `//srv/a` both load with **no
  reason recorded**. POSIX gives exactly two leading slashes an
  implementation-defined meaning and `PurePosixPath` preserves them as a
  distinct root — `Path('//srv/a').parts == ('//', 'srv', 'a')` — while
  `realpath` resolves both to the same directory. Three or more slashes
  collapse; exactly two do not.

  Same class as the `..` hole LWSM-1078 closed, and § 6 calls it out: "two
  records with one identity is a malformed file". `mainwindow` keys rows on
  `Path`, so it renders two rows for one directory, and P03 would spawn
  twice with the same `cwd`.

  Verified clean in the same sweep, so they are not re-searched: trailing
  slash, `///`, `.` components and `/srv/a/.` all normalise and are caught.
  Acceptance: a `//` root is refused or normalised, with a reason; the test
  covers the doubled-slash case explicitly.
  **Layman:** Two entries pointing at the same folder can still both load if one is written with two slashes at the front.
  Kind: security.
  Lanes: core, tests.
  Source: code-quality-review-2026-08-06b.
  Resolved (2026-08-07, d4ec994): a `//` root is refused with a reason, like `..`. Reproduced first: /srv/a and //srv/a both loaded with no reason recorded. Spec § 4.1 now lists three refused path shapes, with the trailing-slash, ///, and `.` cases recorded as verified clean.

- ✅ [LWSM-1104] **FP04: `_read_bounded` leaks a file descriptor when the path is a directory.**
  `os.open()` on a directory with `O_RDONLY` **succeeds** on Linux;
  `os.fdopen()` then raises `IsADirectoryError` before the `with` block is
  entered, so nothing closes the descriptor. Reproduced independently:
  **50 calls leaked 50 descriptors.**

  Impact is one descriptor today, since `load_projects` runs once from
  `build_window`. It matters because this helper exists *for* resource
  discipline, "a directory at that path" is an enumerated shape in § 4.1 and
  in `test_unusable_files_are_refused` — which therefore leaks on every test
  run — and LWSM-1008's rescan turns it into an unbounded leak.
  Acceptance: the descriptor is closed on every failure path, asserted by
  counting `/proc/self/fd` across repeated calls.
  **Layman:** Pointing the app at a folder instead of a settings file quietly uses up a system resource each time.
  Kind: fix.
  Lanes: core, tests.
  Source: code-quality-review-2026-08-06b.
  Resolved (2026-08-07, d4ec994): the fstat runs on the raw descriptor and every path out of _read_bounded closes it. Reproduced first at 50 descriptors leaked over 50 calls, asserted now by counting /proc/self/fd.

- ✅ [LWSM-1105] **FP04: the painted ring's colour and the painted glyph's colour are owned by no test.**
  Both verified by mutation, both leaving the whole suite green:

  - Painting the focus ring in the **state** token instead of the accent —
    all tests pass. INV-17's two halves never meet: one test asserts a
    contrast property of the `accent` *token*, the other asserts only that
    the focused and unfocused renders differ. Neither observes which colour
    the widget paints, so a palette whose state token sits at 2:1 would ship
    an invisible ring with INV-17 reporting green.
  - Painting **every** glyph in the `stopped` token regardless of state —
    all tests pass. § 4.4 requires "both take the matching state token's
    colour", and colour is one of `design.md § Accessibility`'s three
    redundant signals. INV-19 checks the glyph is *drawn*; INV-23 checks only
    the *word*.

  The same shape as LWSM-1077's re-polish, one level out: the assertion
  tests a token in isolation rather than the pixel it produces.
  Acceptance: both are asserted against rendered output with the text or
  shape held constant, so only the colour can differ.
  **Layman:** Two of the coloured things on screen could be drawn in completely the wrong colour and every test would still pass.
  Kind: test.
  Lanes: ui, tests.
  Source: code-quality-review-2026-08-06b.
  Resolved (2026-08-07, 3a266ab): the ring test reads the pen colour off the top edge (QPainter antialiasing is off, so it is exact) and names the state token as the value it must not be; the glyph test drives one row through two statuses with the glyph text held constant. Both mutations previously left the WHOLE suite green and now redden exactly one test each.

- ✅ [LWSM-1106] **FP04: a removed row stays visible and overlapping, and its test cannot fail for that.**
  `QLayout.removeWidget` neither hides nor reparents. Verified by running
  with two rows and dropping the first: the removed row is still
  `isVisible()`, still parented to the central widget, still at
  `QRect(9, 9, 182, 37)` — and the surviving row has moved **into** that
  rectangle, so the two geometries intersect. `deleteLater` only lands on a
  `DeferredDelete` pass, so the object is still valid after
  `processEvents()`.

  In production the loop spins before the next paint, making this sub-frame
  — but it is an undocumented dependence on Qt's delete ordering, and one
  `setParent(None)` removes it.

  **The test cannot see any of this.** `test_a_removed_project_loses_its_row`
  asserts `rows_of(window) == []`, which reads the `_rows` dict and is
  satisfied by the `pop()` alone; deleting *both* `removeWidget` and
  `deleteLater` leaves it green. Its docstring says the row "lingered
  showing its last observed state" — nothing in it can observe showing.
  Acceptance: the removed widget is hidden and unparented; the test asserts
  against the widget's visibility and geometry, not the dict.
  **Layman:** A project removed from the list leaves its row still drawn on screen, on top of the row that moved up into its place.
  Kind: fix.
  Lanes: ui, tests.
  Source: code-quality-review-2026-08-06b.
  Resolved (2026-08-07, 25f8294): setParent(None) instead of removeWidget, which neither hides nor reparents. The test asserts visibility and parenthood rather than the _rows dict — deleting both removeWidget and deleteLater left the old assertion green. A second test pins the overlap scenario, asserting as a precondition that the survivor moves into the vacated rectangle.

- ✅ [LWSM-1107] **FP04: two user-visible strings sit outside the translation contract, and a translator installed later never reaches an existing row.**
  § 4.4 states "**every** user-visible string in this file goes through
  `QCoreApplication.translate` under one context". Three gaps, all verified
  by running:

  - `f" (+{len(notices) - 1} more)"` is never translated — the status bar
    reads the same with a translator installed.
  - `self.tr("Local Web Server Manager")` resolves under context
    `"MainWindow"`, not the `_TR_CONTEXT = "ProjectRow"` the file declares.
  - A translator installed **after** the window is built never reaches an
    existing row: there is no `LanguageChange` branch in `changeEvent`, and
    LWSM-1076's equality guard suppresses the only path that would
    re-render. A row built after the install renders translated; one built
    before does not.

  The third makes § 4.4's stated rationale for translating at call time
  untrue as written. No user-visible impact in P02, which has no language
  switcher.
  Acceptance: one context for the whole file, the status-bar string included;
  a `LanguageChange` branch that retranslates existing rows; the test
  installs the translator **after** the window is built.
  **Layman:** A couple of bits of text still cannot be translated, and switching language after the window opens would not change what is already on screen.
  Kind: fix.
  Lanes: ui, tests.
  Source: code-quality-review-2026-08-06b.
  Resolved (2026-08-07, 25f8294): one context for the whole file including the status-bar summary and the window title (self.tr resolved under the CLASS), plus a LanguageChange branch driving ProjectRow.retranslate, which clears the held view so LWSM-1076's guard cannot swallow it. Honest limit recorded in the spec: the handler is pinned, Qt's broadcast is not — with the loop running and the window the only registered top-level widget, installTranslator returned True and Qt did not post LanguageChange to it, while a bare QMainWindow did receive it.

- ✅ [LWSM-1108] **FP04: five comments, docstrings and spec claims are verifiably false.**
  Each verified. None is a runtime bug on its own; together they are the
  mechanism by which the FP03 defects above went unnoticed, because a
  reviewed comment gets trusted.

  1. `"RecursionError ... is not even an Exception"` — in a code comment, a
     test docstring, the spec and a commit message. **False:**
     `RecursionError → RuntimeError → Exception`. The clause is still needed
     because it is not a `ValueError`, which is all the comment should say.
     Dangerous because a reader who believes it will "fix" `ports.py`'s
     `except Exception` to `BaseException` and start swallowing
     `KeyboardInterrupt`.
  2. `_apply_text_metrics`'s docstring claims it keeps sizes fresh on a font
     change; it leaves the glyph column stale (LWSM-1101).
  3. `_ABANDONED`'s comment claims the objects are never released; Python
     frees module globals at shutdown (LWSM-1100).
  4. § 10 claims the outstanding-task ceiling is one, not one per tick
     (LWSM-1099).
  5. § 11 lists focus-ring contrast and state-token contrast as checked by
     "nothing", both false since INV-17/INV-18 landed — and its closing
     "eight `nothing` rows ... eight is this spec's honest error budget" is
     therefore wrong by two. § 7's table *was* updated; § 11 was not.
  Acceptance: each corrected in place, and § 11's count recomputed rather
  than re-asserted.
  **Layman:** Several notes in the code and the design document confidently state things that turn out not to be true — which is how the last round of bugs got believed.
  Kind: doc-fix.
  Lanes: core, ui, docs.
  Source: code-quality-review-2026-08-06b.
  Resolved (2026-08-07, 9aee812): all five corrected. RecursionError IS an Exception (RecursionError -> RuntimeError -> Exception); the comment, test docstring and spec now say it is not a ValueError, which is what they meant. § 11's two false `nothing` rows removed — focus-ring and state-token contrast are covered by test_theme.py — one row moved to `partly` for LWSM-1101's 200% test, and the error budget re-derived mechanically at five rather than re-asserted. The ROADMAP's own dated resolution note repeating the RecursionError claim is left alone as a frozen record.

- ✅ [LWSM-1109] **FP04: six tests pass against the defect they were written to catch.**
  Each verified by mutation — the named change leaves the suite green:

  - The `MAX_FILE_BYTES + 1` grow-race read can be replaced with a plain
    `read()` and the post-check deleted. The mechanism § 4.1 names by name is
    unguarded; only the `fstat` path is tested.
  - `MAX_REASON_CHARS` can be set to 400. The clip test asserts `< 500`
    against a 100,000-char input, so it detects removal and nothing between.
  - `log.exception` in `run()` can be replaced with `pass`. The assertion
    looks for `"RuntimeError"`, which the *wrapping* `ProbeError` message
    supplies from a different log line — so it cannot distinguish
    "traceback reported" from "no traceback".
  - `self.update()` in `update_from` can be deleted. `grab()` repaints
    unconditionally, so no render-based test can see a missing repaint
    request — and § 4.4 flags this exact line as the hazard.
  - `_port.setMinimumWidth` can be deleted.
  - `stop()`'s bounded-wait test patches the budget to 100 ms then asserts
    `< 2.0` — a 20x-loose threshold that a 1.9 s `stop()` would pass.
  Acceptance: each assertion is tightened against the constant or the
  observable it names, and re-mutated to confirm it now goes red.
  **Layman:** Six of our checks would not notice if the thing they are meant to guard were removed.
  Kind: test.
  Lanes: tests.
  Source: code-quality-review-2026-08-06b.
  Resolved (2026-08-07, 085e90f): five tightened and each re-mutated to confirm it now goes red — the grow-race read (matched on `too large`, since without the post-check the file fails as invalid JSON, also a RegistryError), MAX_REASON_CHARS, log.exception (now asserts a record carrying exc_info), _port.setMinimumWidth, and stop()'s budget. The sixth, self.update(), is NOT closable at the pixel level: a paintEvent counter stays green with it deleted because the labels change text on the same tick. The test asserts the call and says so; it becomes load-bearing at LWSM-1011.

- ✅ [LWSM-1110] **FP04: stale bytecode can make the gate report on code that is not on disk.**
  Found during this close, and it is about the toolchain rather than this
  project's code. Python's default `.pyc` invalidation compares only the
  source's **mtime and size**. A same-second edit-and-revert whose
  replacement text is the same byte length therefore leaves the stale
  bytecode looking valid.

  Observed live: a constant read `400` from an import while the file on
  disk, `git status` and `git show HEAD` all said `120` — source mtime and
  the `.pyc`'s recorded mtime were the identical second, and `"120"` and
  `"400"` are the same length. Clearing `__pycache__` restored `120`.

  This is the "green test over a stale binary" false pass in a language with
  no build step, and it is invisible: the tree is clean, the diff is empty,
  and the test run is green. The full gate was re-run on cleared bytecode
  and is genuinely green at 125 tests, so nothing shipped wrong — but only
  because it was checked.
  Acceptance: `scripts/local-ci.sh` exports `PYTHONDONTWRITEBYTECODE=1` (or
  uses hash-based invalidation) so the gate can never trust a `.pyc`; the
  trap is recorded in `CLAUDE.md`.
  Dependencies: none.
  **Layman:** Python can keep running an old compiled copy of a file after you change it back, so a passing test may not be testing what you are looking at.
  Kind: chore.
  Lanes: build, tests.
  Source: in-session-2026-08-06.
  Resolved (2026-08-07, c7908aa): PYTHONDONTWRITEBYTECODE=1 exported for the whole script, AND the syntax gate given -f --invalidation-mode checked-hash — compileall's job is to WRITE bytecode so it ignores that variable, and by default it skips a file whose .pyc looks current by the same mtime-and-size test that causes this, so the stale .pyc survived it. Verified by planting the trap: a same-second same-length 120 -> 400 substitution imported as 400, and as 120 after the new syntax step.

- ✅ [LWSM-1111] **FP04: the low-severity tail from the second P02 review.**
  Each verified, grouped so none is lost.

  - `_quoted` clips **before** the `repr`, so the bound is ~10x the
    constant: a 400-char astral non-printable string returns **1203**
    characters, and a reason interpolates two of them. Contract-conformant
    ("bounded") but not what the constant reads as.
  - `ports.snapshot()`'s comprehension sits outside the `try`, so malformed
    psutil output raises `AttributeError`, not `ProbeError`, against § 4.2's
    "one exception type". Mitigated by `run()`'s catch-all; costs one line.
  - Both of `snapshot()`'s filters are untested: dropping `and conn.laddr`
    passes the **entire** suite, and dropping the `CONN_LISTEN` filter
    passes everything except one `integration` test — so under `--fast`
    neither is covered. One fake `net_connections` list closes both.
  - `poll_once()` after `stop()` is unguarded and re-arms delivery; a
    `_stopped` flag closes this and LWSM-1098 together.
  - `test_layering`'s colour detector misses named constants
    (`Qt.GlobalColor.red` passes) and false-positives on a **trailing**
    comment, contradicting its own comment about comments.
  - `_glyph_color` is cached behind the equality guard, so a theme swap with
    an unchanged row would leave the glyph in the old palette while the word
    followed the new one. Unreachable in P02; LWSM-1031 is exactly when it
    becomes reachable.
  - The chmod-000 registry test silently passes as root, where mode bits are
    ignored; a `skipif` would make the reason explicit.
  - `test_refuses_a_device_node` reads the real `/dev/null`, the one test
    outside `tmp_path` that `testing.md § T1` otherwise forbids.
  - `vulture` flags unused `context` / `disambiguation` parameters in the
    test translator overrides; the signature is mandated by
    `QTranslator.translate`, so an underscore prefix is the fix.
  - `typos`: "unparseable" should be "unparsable" in the spec.
  Dependencies: none.
  **Layman:** Nine small things worth tidying, none of which breaks anything today.
  Kind: fix.
  Lanes: core, ui, tests.
  Source: code-quality-review-2026-08-06b.
  Resolved (2026-08-07, c045e62): nine of ten closed — snapshot()'s comprehension moved inside the try, both of its filters tested (each mutation reddens under -m 'not integration', where neither was covered before), the colour detector taught named constants and given tokenise-based comment stripping, the chmod-000 case skipped explicitly as root, the device-node test moved into tmp_path, the vulture parameters underscore-prefixed, and the spec typo fixed. _glyph_color's caching behind the equality guard is deliberately NOT fixed — unreachable in P02 because the theme is built once — and is named at the guard pointing at LWSM-1031.

## FP05 — Third three-lane review fold-in (from the second re-run P02 close, 2026-08-07)

Static analysis was clean for the **fourth** close running — ruff, bandit,
semgrep, gitleaks, trivy, shellcheck, actionlint, zizmor and pip-audit all found
nothing, each verified to have actually run rather than trusted on a zero. The
170 `contract_doc_drift` hits are allowlist-003 and allowlist-006 in full. Every
defect below came from reading.

Three lanes re-read the FP04 code cold — the data boundary, the concurrency
boundary and the presentation layer. **25 findings, 7 of them HIGH.** The four
highest-consequence were re-reproduced independently of the reviewers and all
four held exactly.

**This pass is deliberately not the whole list.** P02 is one feature item that
had already produced 28 fix items across FP03 and FP04; a third full fold-in
would have made it 54, and the ratio — not the convergence checkpoint, which
would not have fired — is what stopped it. The user's call on 2026-08-07 was to
fix the **two root causes and the seven HIGH findings** here, and hand the
MEDIUM and LOW tail to the phases that already own the code it lands in. Those
are in `docs/known-issues.md` with a named owner each, not dropped.

**Two themes were found independently by all three lanes**, and they are the
first two bullets because the leaf findings are their instances:

1. **A fix landed at the call site it was reported against, not at the
   mechanism.** Six instances this pass. This is the same shape FP04 reported
   about FP03, now for the third time running.
2. **Tests assert the artefact, not the delivery.** Four separate shipped fixes
   can be deleted with all 150 tests still green, because what is covered is
   the helper and never the wiring that reaches it.

- ✅ [LWSM-1112] **FP05: a fix is applied at the mechanism, and the sweep for sibling call sites is a rule rather than a habit.**
  Root cause 1. Six instances found this pass, each a fix that closed the one
  call site it was reported against: `_quoted` applied to the port fields but
  not `schema_version` (LWSM-1102); `Path.home()` guarded in
  `registry.default_projects_path` but not `applog.default_state_dir`; the
  shutdown bound placed in `run()` rather than in the abandonment mechanism
  (LWSM-1100); LWSM-1069's staleness handling covering the exception path but
  not the hang path; the `_stopped` flag checked in `_on_snapshot` but not
  `_on_probe_error` (LWSM-1098); and the contrast floor enforced against
  `window` but not `alt_base`.

  The leaf fixes are separate bullets below. What this one owns is the rule:
  `docs/standards/coding.md` gains a clause requiring that a fix names the
  other call sites of the same mechanism and either fixes them or says why
  they are out of scope — and `/apply-fixes` already owns a blast-radius
  sweep, so the gap is that nothing makes it mandatory.
  Acceptance: `coding.md` carries the clause; each of the six instances is
  either fixed by its own bullet here or filed with an owner.
  **Layman:** The same bug keeps getting fixed in one place while its twin two files over is left alone — this makes checking for the twin part of the job.
  Kind: refactor.
  Lanes: docs, core.
  Source: code-quality-review-2026-08-07.
  Resolved (2026-08-07, 812460c): `coding.md § 1.6` carries the clause. Numbered 1.6 rather than 1.4 (where it reads better) because README.md and dependencies.md both cite § 1.5 and inserting ahead would have silently repointed them — the rule itself, broken while writing it, and the note records that. Two additions beyond the finding: search for the defect's SHAPE not the symptom, and a mechanism is not only a function (three of the six were a *rule* applied unevenly, which "who else calls this?" does not catch). All six instances closed: 1, 2, 3 and 5 fixed by LWSM-1114/1116/1117/1113; 4 filed as known-issue-006 (P06), 6 as known-issue-010 (P03), both with live owners. APPLYING THE CLAUSE TO THIS PASS FOUND TWO MORE: known-issue-005 and known-issue-007 named LWSM-1115 and LWSM-1117 as their owners and both were closed without them — now fixed and marked resolved, pinning the shipped STOP_WAIT_MS (with spec § 4.3's headroom reasoning) and MAX_REASON_CHARS. And MAX_REASONS, added by LWSM-1115 four commits earlier, carried the identical defect: its assertions read `<= MAX_REASONS + 1`, so 100 -> 100000 would have passed and restored the flood the cap exists to stop. Both mutation-verified.

- ✅ [LWSM-1113] **FP05: a test proves the fix is reached, not merely that its helper works.**
  Root cause 2, and the more serious of the two. Four shipped fixes are
  deletable with the full suite green, verified by mutation:

  | Deleted | Suite |
  |---|---|
  | `run()`'s call to `exit_without_waiting_for_abandoned_probes` — all of LWSM-1100 | 150 passed |
  | `MainWindow.setPalette(theme.to_palette())` | 150 passed, twice |
  | `main()`'s `finally: controller.stop()` | 150 passed |
  | all three of `applog`'s `S_ISREG` / `O_DIRECTORY` / `fchmod` checks at once | 19 passed |

  The pattern is exact: the palette test asserts the `QPalette` **object**
  and never that a widget receives it; the entry-point test asserts the
  **string** `lwsm.__main__:run` and never that `run()` does anything. The
  computational assertions in this codebase are strong — the presentation
  lane killed 10 of 11 mutations against rendered pixels. What nothing covers
  is whether the thing that was built is plugged in.

  Also folded in here, same class: `_on_probe_error`'s `_stopped` guard,
  `run()`'s outer catch-all (INV-4c's second layer, which demonstrably fires),
  and `_flush_repeated_error` on the success path — each deletable with 150
  green.
  Acceptance: `docs/standards/testing.md` carries the rule; every mutation in
  the table above reddens at least one test named for it.
  **Layman:** Several fixes we shipped could be deleted and every test would still pass — the tests check the part that was built, not that it is switched on.
  Kind: test.
  Lanes: tests, docs.
  Source: code-quality-review-2026-08-07.
  Resolved (2026-08-07, 6e32593): nine wiring tests added, each mutation-verified — the shipped line it guards was deleted and the named test confirmed red. All four table mutations now redden at least one test named for them. `docs/standards/testing.md § T9` carries the rule and is written but UNGATED: it is deliberately batched with LWSM-1112's `coding.md` clause into one rule-14 /cold-eyes run. Bullet flip itself was missed on 2026-08-07 and corrected in the FP05 continuation session; the work and the commit predate this note.

- ✅ [LWSM-1114] **FP05: `schema_version` is the one field still interpolated raw, so a hand-edited file yields a 1 MiB log record and status string.**
  `registry.py:232` uses `{version!r}`, which escapes but does not clip;
  `_quoted` (escape **and** clip to `MAX_REASON_CHARS`) is applied to `name`
  and `path` and not to this one. `grep '!r}'` finds exactly one hit in the
  module. Reproduced independently of the reviewer: a 200 KB
  `schema_version` produced a `RegistryError` of **200,093 characters**
  against a cap of 120; at the 1 MiB file cap the reviewer measured
  1,000,093 and a single log record of 1,093,449 bytes, which forces an
  immediate rollover.

  This is INV-21's own *Breaks when* clause verbatim, and the exact defect
  LWSM-1102 fixed on the port fields one call site over — an instance of
  LWSM-1112.
  Acceptance: `schema_version` goes through `_quoted`; a test feeds an
  oversized value and asserts the message length against
  `MAX_REASON_CHARS`; no bare `!r}` interpolation of file-sourced data
  remains in the module.
  **Layman:** One field in the project file was never length-limited, so a big value in it can blow away the whole log the user is told to check.
  Kind: fix.
  Lanes: core, tests.
  Source: code-quality-review-2026-08-07.
  Resolved (2026-08-07, 38a4439): `schema_version` goes through `_quoted`. The acceptance's third clause — "no bare `!r}` interpolation of file-sourced data remains in the module" — is now a test rather than a one-off grep: `test_no_file_sourced_value_is_interpolated_without_the_clip` reads the module and fails on any non-comment `!r}`, so the fourth call site is caught at the gate rather than by a fourth review. INV-21 rephrased from "a rejection reason" to "every message carrying a hand-edited value", because the narrow wording is what let a *raised* message sit unbounded through two fixes of this mechanism. Both new tests mutation-verified against the restored `{version!r}`.

- ✅ [LWSM-1115] **FP05: nothing bounds the *number* of rejection reasons, so a 1 MiB file costs 8.7 s of blank screen and destroys the log.**
  `_quoted` bounds each reason; nothing bounds how many there are, and
  `build_window` emits one `log.warning` per reason. The cheapest bad element
  is two bytes. Reproduced: a maximally dense malformed file at the cap gave
  **524,271 reasons / 20,859,730 total characters**, then **8.7 s** spent
  logging, all five backups overwritten and prior history gone. `build_window`
  runs before `window.show()`, so that is 8.7 s of no window and no way to
  interrupt.

  Spec § 6 identifies this exact amplification for the probe path and answers
  it with per-message suppression (LWSM-1079). The registry path has the same
  amplification, a worse constant, and no suppression.
  Acceptance: the reason list is capped with an "and N more" tail; a test at
  the file-size cap asserts both the reason count and the wall time.
  **Layman:** A badly broken project file can freeze the app for nine seconds before the window appears, and wipe the log while it does it.
  Kind: fix.
  Lanes: core, tests.
  Source: code-quality-review-2026-08-07.
  Resolved (2026-08-07, 2ea6803): reproduced first and the numbers matched the reviewer exactly — 524,271 reasons / 20,859,730 characters / 28.7 MB written. `load_projects` now keeps at most MAX_REASONS (100) and appends one tail naming the rest; the tail is not optional, because a cap with no tail reads as completeness. Measured after: 101 reasons, 5,153 bytes, 1 ms of logging. Three tests, all mutation-verified, and the third is the delivery half in test_mainwindow.py — that the cap reaches `build_window`, which is where the 8.7 s was spent. The wall-time clause of the acceptance is met as an order-of-magnitude smoke bound only; the log-record count is the real assertion, because a loaded machine makes any timing assertion flaky. Spec § 6 gains the registry half of an amplification it described only for the probe path.

- ✅ [LWSM-1116] **FP05: `applog.default_state_dir()` is missing the `Path.home()` guard its registry twin has, so the app dies with a traceback and no window.**
  `Path.home()` raises `RuntimeError` when neither `HOME` nor a passwd entry
  resolves. `registry.default_projects_path()` wraps it and re-raises as
  `RegistryError` (`registry.py:75-82`); `applog.default_state_dir()`
  (`applog.py:160`) calls it bare, and `main` guards `configure_logging()`
  with `except OSError` only — so the `RuntimeError` sails straight past.
  Reproduced: `main([])` died with `RuntimeError`, `caught by except OSError?
  False`.

  `__main__.py:76-78` states the contract this breaks — "A log we cannot write
  is worth a warning, not a crash" — and the `configure_stderr_logging`
  fallback, whose own docstring says the hardening "would have converted a
  log-integrity attack into a total-outage one", is never reached. Another
  instance of LWSM-1112.
  Acceptance: the guard matches `registry.py:75-82`; a test clears `HOME` and
  the passwd entry and asserts a window still opens with a stderr warning.
  **Layman:** On a machine with no home directory set, the app crashes instead of falling back to printing its log to the terminal.
  Kind: fix.
  Lanes: core, tests.
  Source: code-quality-review-2026-08-07.
  Resolved (2026-08-07, 8e9c779): the guard matches registry.py:75-82 in shape, raising `OSError` rather than `RegistryError` — that is applog's existing error contract and the one type `main`'s handler catches. Reproduced first: `main([])` died with `RuntimeError`, `caught by except OSError? False`, on 3.13.14. The end-to-end test then found a SECOND half not in this bullet: `main` called `build_window(default_projects_path())`, and an argument is evaluated before the call, so the `RegistryError` LWSM-1026's guard raises was thrown outside the only catch written for it — the guard was present and unreachable, the same root cause one layer up. `build_window` now takes `Path | None` and resolves the default inside its own try. Spec § 4.5 and INV-15 updated. Both tests drive the real mechanism (HOME cleared, passwd entry removed) and assert the window is shown WITH its reason; mutation-verified both ways.

- ✅ [LWSM-1117] **FP05: the abandoned-pool wait is bounded only for callers that go through `run()` — the mechanism is still unbounded, and the test suite pays it today.**
  `stop()` bounds its own wait and moves a still-running pool into
  `_ABANDONED`; `~QThreadPool` then calls `waitForDone()` with no timeout at
  interpreter shutdown. The only thing bounding that is
  `exit_without_waiting_for_abandoned_probes`, whose only caller is `run()`.
  Every other process — the test suite, any future embedder or reload path —
  inherits the unbounded wait.

  Measured independently of the reviewer, and the numbers matched:

  | run | pytest reports | process wall |
  |---|---|---|
  | full suite | 4.13 s | **7.65 s** |
  | minus `test_stop_is_bounded_when_a_probe_never_returns` | 4.03 s | **4.31 s** |

  So every `./scripts/local-ci.sh` and every CI run pays ~3.3 s blocked in a
  destructor, invisible to the suite, which reports 150 passed either way. The
  reviewer showed it scales with the gate: raising only the fake probe's
  timeout moved process wall by +14.95 s while pytest's own number did not
  move. LWSM-1100's note says the wait was "removed"; it was removed on one
  path. Instance of LWSM-1112.
  Acceptance: nothing outside `run()` can reach interpreter shutdown holding an
  abandoned pool; the suite's own process wall drops to within ~0.5 s of the
  time pytest reports, asserted rather than observed.
  **Layman:** The fix that stopped the app hanging on quit only works when it is launched the normal way — our own test runs still wait three seconds for it every time.
  Kind: fix.
  Lanes: core, tests.
  Source: code-quality-review-2026-08-07.
  Resolved (2026-08-07, 9918aea): `wait_for_abandoned_probes(timeout_ms)` is the non-exiting half — it reaps idle pools and returns how many are still live; a session fixture calls it, and the test that abandons a pool now releases its own fake probe. Suite gap 2.58 s -> 0.26 s (5.09/7.67 became 8.99/9.25), inside the acceptance's 0.5 s and asserted by a subprocess test that stamps its last line and compares it to process exit, isolating shutdown cost from startup. TWO CORRECTIONS to this bullet, both measured: (1) the wait is UNBOUNDED, not ~3.3 s — a probe that truly never returns hung the interpreter indefinitely, killed at three minutes, main thread on a futex joining the pool thread; the suite's 2.6 s was 2.6 s only because FakeProbe.gate.wait carries a 5 s timeout. (2) No Python-level ownership trick avoids it — dropping, holding, reparenting and Shiboken-invalidating the wrapper all hung identically against a stuck probe, so there was no new bound to add, only reach to fix. Acceptance clause 1 is met for every caller that reaps; a caller that neither exits nor reaps still blocks, and that is unfixable from a core module because ending the process would override an exit code it cannot see (LWSM-1100's exact failure). An atexit guard prints the reason to stderr first — a diagnosis, not a bound, documented as one in both the docstring and spec § 6.

- ✅ [LWSM-1118] **FP05: the theme's palette reaches the `QMainWindow` and nothing below it, so a dark palette renders text at 1.25:1.**
  `mainwindow.py:318` calls `setPalette(theme.to_palette())` and `:321` then
  calls `setStyleSheet(...)`, which installs `QStyleSheetStyle` — and that
  re-resolves every descendant's palette from the **application** palette,
  discarding the one just set. `to_palette()`'s 13 roles never reach the
  central widget, the rows, or the cell labels. Verified on live widgets:
  `window WindowText=#1b1b1f` (themed) against `row`/`state`
  `WindowText=#000000` (Fusion defaults).

  The light default hides it — Fusion's black is *darker* than the `text`
  token, so contrast is accidentally better. Building a dark theme makes it
  visible at once: name and port cells rendered at **1.25:1 and 1.27:1**
  against a 4.5:1 floor, i.e. invisible, for a primary user who is partially
  sighted. `theme.py:127` claims "Tokens expand into a QPalette so native
  widgets follow the theme"; they do not. Confirmed independently that
  deleting the `setPalette` call leaves **150 tests green** — this is also a
  LWSM-1113 instance.
  Acceptance: a rendered-pixel test asserts a cell's ink matches the `text`
  token under a non-default palette; the fix survives the style sheet.
  **Layman:** The colour theme only reaches the window frame, not the text inside it. Harmless in the light theme by luck, and unreadable the day a dark theme ships.
  Kind: fix.
  Lanes: ui, tests.
  Source: code-quality-review-2026-08-07.
  Resolved (2026-08-07, 16f267b): the palette goes on the QApplication, which is both the fix and the right scope — QStyleSheetStyle resolves descendants from there, and the theme governs P05's dialogs and P09's tray too. Reproduced first on live widgets, matching the report exactly. `self.setPalette` became redundant and was removed with it: a line no test can redden is the LWSM-1113 defect this pass closes, and the single remaining line now reddens BOTH the new cell test and LWSM-1113's window test. TWO versions of the test could not fail and both are recorded in the helper: the first took the nearest pixel of the whole grab and PASSED against unfixed code (the label's light-grey background sat nearer a near-white dark token than the black text did); the second isolated the ink but could not assert the token, because with antialiasing on a name label held 0 pixels of a pure #ff00ff out of 119 across 40 fringe colours. With QFont.StyleStrategy.NoAntialias the ink is exactly one colour — 80 px of #000000 before, 80 px of #eef0ff after — so INV-24 asserts the token itself. Also corrected two comments that stated the defect as current fact (LWSM-1108 class): `to_palette`'s docstring and LWSM-1113's test docstring. A conftest fixture restores the application palette between tests, since MainWindow now writes global state that outlives the window.

- ✅ [LWSM-1119] **FP05: a runtime application-font change never reaches an existing row, so O8 clause 4's 200 % path does not work by the route a text-size control uses.**
  Same stylesheet root cause as LWSM-1118. Measured: `QApplication.setFont()`
  and `MainWindow.setFont()` produce **no `FontChange` event on the row at
  all** — 0 calls to `_apply_text_metrics`, metrics unchanged at
  `(13, 52, 47)`. Only `row.setFont()` works, and `grep -rn setFont src tests`
  returns three hits, all `row.setFont`, in the three tests that cover this.
  So the suite reports the 200 % path as covered while the route a real
  control would use is dead.

  `_apply_text_metrics`'s docstring says it is re-applied "so LWSM-1032's
  100-200 % text-size control does not leave these stale" — the third false
  comment of this class, after LWSM-1071 and LWSM-1101. Rows built *after* the
  app font changes do pick it up, so only existing rows are frozen.
  Acceptance: `QApplication.setFont()` reflows an already-built row; the test
  drives the application font, not the widget's.
  **Layman:** Turning up the system text size does nothing to rows already on screen — and the setting our partially-sighted user is most likely to change is exactly this one.
  Kind: accessibility.
  Lanes: ui, tests.
  Source: code-quality-review-2026-08-07.
  Resolved (2026-08-07, b43ccb0): reproduced exactly — zero calls to _apply_text_metrics for QApplication.setFont() and MainWindow.setFont(), 1 for row.setFont(). Isolated the cause beyond the bullet's claim: against a bare QWidget tree the same change delivers 1 FontChange with NO style sheet and 0 WITH one, which pins QStyleSheetStyle's font resolution as the mechanism rather than anything about ProjectRow. MainWindow.changeEvent now pushes self.font() down to the rows — the same shape as its LanguageChange branch, and self.font() rather than QApplication.font() so MainWindow.setFont() works too. INV-25 added; § 7's O8.4 coverage row corrected, since it read "partly covered" while the covered route was the one nothing uses. _apply_text_metrics's docstring corrected — the third false comment of this class in this file after LWSM-1071 and LWSM-1101. NOTED HONESTLY: the conftest fixture's application-font restore is an unexercised safety net (deleting it leaves all 171 green); kept because the hazard is real and cheap, not because anything proves it works.

- ✅ [LWSM-1120] **FP05: nothing verifies that `run()` calls the bounded exit, or that `main()` stops the controller.**
  The two shutdown promises in spec § 6, neither of them wired-tested.
  `test_the_process_exits_promptly_when_a_probe_is_abandoned` writes a
  subprocess script that calls
  `exit_without_waiting_for_abandoned_probes(0)` **directly**
  (`tests/test_controller.py:602`), so it tests the function and not the
  wiring; `test_the_console_script_names_run_not_main` asserts only the
  entry-point string. Confirmed independently: reducing `run()` to
  `code = main(); return code` — the whole of LWSM-1100 — leaves **150
  passed**. Removing `main()`'s `finally: controller.stop()` likewise leaves
  150 passed.

  Given LWSM-1117, `run()`'s call is the single line bounding process exit,
  and it is the highest-consequence unguarded line in the tree. `build_window`
  is already the testable seam INV-15 uses.
  Acceptance: a test fails when `run()` no longer calls the bounded exit, and
  another fails when `main()` no longer stops the controller.
  **Layman:** The line that stops the app hanging on quit could be deleted and every test would still pass.
  Kind: test.
  Lanes: tests.
  Source: code-quality-review-2026-08-07.
  Resolved (2026-08-07, 6e32593): closed by LWSM-1113 rather than separately — its acceptance was exactly two of that item's nine tests. test_run_bounds_the_process_exit and test_main_stops_the_controller_when_the_loop_returns both go red on the mutation they name (run() reduced to `code = main(); return code`, and main()'s `finally: controller.stop()` removed); both left all 150 tests green before.

## FP01 — Security fold-in (from the P01 review, 2026-08-03)

**Theme:** findings from the P01 `/audit` + code review + security
pass. The static scanners were all clean (ruff, bandit, semgrep,
gitleaks over 24 commits, trivy); everything below came from
review, and most of it is **design that is still cheap to
change** rather than code that exists.

### 🔒 Security

- ✅ [LWSM-1045] **FP01: scrub the repo before it is ever public —
  BLOCKS LWSM-1004.** `docs/discovery.md § Problem` publishes a
  working target list for the author's private local services:
  seven project names with exact ports, `file:line` references,
  which two were listening at scan time, and the absolute scan
  root `<scan root>/`, which is also shipped as the
  **default** scan root. `docs/standards/testing.md § T1`,
  `docs/design.md`, ADR-0002/0003/0007 and
  the adoption prompt (now `docs/private/port-contract-prompt.md`,
  author-private) repeat the paths and name
  sibling projects. Two of those services carry personal data.
  **This is in all 24 commits**, so `.gitignore` cannot fix it —
  either rewrite history or start the public repo from one
  squashed commit. Also: change the shipped default scan root to
  something generic.
  **Scrubbed 2026-08-03 (commit 9dcabc9): author-private facts moved to gitignored `docs/private/`, 13 files rewritten to neutral labels, default scan root now `~/projects`. **Remaining, and it blocks LWSM-1004:** the public repo must start from a squashed orphan commit — the names are in all 26 commits and 12 commit-message lines, which no edit to the tree can fix.**
  Dependencies: none.
  **Layman:** Before this goes public, take out the list of your own
  sites and the paths on your machine — right now the repo would
  tell a stranger exactly what you run and where.
  Kind: security.
  Source: security-review-2026-08-03.
  Priority: 1.
  Lanes: docs, build.

- 🚧 [LWSM-1046] **FP01: a trust gate before running a discovered
  launcher.** Start executes arbitrary code from any directory in
  a scan root — a hostile repo cloned there is auto-listed and
  visually identical to a real project, and `npm run <script>`
  passes an untrusted string through `/bin/sh`, so ADR-0003's
  "shell=False removes injection" claim is false one level down.
  Add a one-time per-project confirmation showing the resolved
  absolute launcher and exact argv, re-armed whenever the
  launcher or its content hash changes (ADR-0005 already detects
  *Changed*). Refuse launchers that are symlinks out of the
  project or group/other-writable. Correct the ADR-0003 claim.
  **Contract landed 2026-08-03 in ADR-0003 § Trust (one-time per-project confirmation showing resolved path + argv, re-armed on change; symlink and world-writable launchers refused; the false injection-immunity claim corrected). **Implementation lands with LWSM-1009.****
  Dependencies: LWSM-1009.
  **Layman:** Ask once before running a project's start script, and
  ask again if that script changes — so a folder someone slipped
  into your projects directory can't run itself.
  Kind: security.
  Source: security-review-2026-08-03.
  Priority: 1.
  Lanes: core, ui.

- 🚧 [LWSM-1047] **FP01: signal process objects, never bare PIDs.**
  ADR-0003 escalates to `SIGKILL` when "anything is alive **or**
  the port is still bound" — the `or` fires when our child is
  already reaped and something else holds the port, so
  `os.killpg(child.pid, …)` targets a number the kernel may have
  reissued. The foreign path is worse: it enumerates
  descendants, waits on a modal dialog for an unbounded time,
  then signals a stale set. Use `psutil.Process` handles
  (`_raise_if_pid_reused` makes reuse an error), don't reap the
  managed child until the stop sequence ends, and re-enumerate
  after the user confirms.
  **Contract landed 2026-08-03 in ADR-0003 (signal through `psutil.Process` handles, never a bare PID; do not reap the child until the stop sequence ends; a bound port warns rather than signals) and ADR-0004 (re-enumerate the foreign set after the user confirms). **Implementation lands with LWSM-1009.****
  Dependencies: LWSM-1009.
  **Layman:** Make sure Stop can never kill an unrelated program that
  happened to inherit the same process number.
  Kind: security.
  Source: security-review-2026-08-03.
  Priority: 1.
  Lanes: core, tests.

- 🚧 [LWSM-1048] **FP01: don't hand the whole environment to
  launched projects.** ADR-0003 extends `os.environ`, so every
  scanned project's launcher — including a hostile one —
  inherits `SSH_AUTH_SOCK` (a live signing oracle), API keys and
  cloud credentials, readable afterwards from `/proc/<pid>/environ`.
  Build the child environment from an explicit allowlist plus
  `PORT` and `LWSM_MANAGED`.
  **Contract landed 2026-08-03 in ADR-0003: the child environment is an explicit allowlist plus `PORT` and `LWSM_MANAGED`, so `SSH_AUTH_SOCK` and credentials are never inherited. **Implementation lands with LWSM-1009.****
  Dependencies: LWSM-1009.
  **Layman:** Don't pass your passwords and keys to every project you
  start.
  Kind: security.
  Source: security-review-2026-08-03.
  Priority: 1.
  Lanes: core.

- 🚧 [LWSM-1049] **FP01: treat detection results as untrusted
  input.** The plausibility test ("holder's cwd is under the
  project") is forgeable with one `chdir`, and the design lets a
  forged match enable **Open in browser** — localhost phishing
  with the manager's own credibility behind it. Alongside:
  validate systemd unit names and pass `--` (a leading `-` is
  consumed as a `systemctl` option such as `--host=`); bind a
  unit to a row by `FragmentPath`, not by directory name; parse
  window geometry through `int()` before it reaches the KWin
  script (ADR-0007 interpolates into JavaScript); constrain
  `open_url` to http/https with `QUrl.setPort`, and `open_file`
  to inside the project with no `.desktop` or executable files;
  render logs and the stop dialog as **plain text**
  (`QPlainTextEdit`, `setTextFormat(PlainText)`), since Qt's
  auto-detected rich text loads local resources; open per-project
  logs with `O_NOFOLLOW` and a path-hashed filename.
  **Contract landed 2026-08-03 across ADR-0004 (plausibility test declared security-worthless; foreign Open-in-browser gains the Stop path's disclosure; unspoofable columns in the stop dialog), ADR-0003 (systemd unit-name validation, `--` separator, bind by `FragmentPath`), ADR-0007 (geometry parsed through `int()` before reaching KWin JavaScript; script written 0600 via `mkstemp`) and `design.md` (plain-text widgets; `open_url`/`open_file`/`run_command` constraints; detected-only record type). **Implementation lands with LWSM-1011.****
  Dependencies: LWSM-1011.
  **Layman:** Assume everything the app reads off disk might be
  hostile, and stop it turning into a way to run or open something
  unexpected.
  Kind: security.
  Source: security-review-2026-08-03.
  Priority: 2.
  Lanes: core, ui.

- 🚧 [LWSM-1050] **FP01: bound the scanner's reads.** Detection
  regexes run unanchored over attacker-controlled files three
  levels into any scanned repo, and the 20-second budget is a
  per-scan wall check that cannot interrupt a backtracking match.
  A 2 GB `README.md` is read whole; a FIFO blocks `open()`
  forever. Cap file size, read line-by-line with a per-line
  length cap and a deadline checked per line, replace the
  backtracking pattern with a non-backtracking two-step,
  `os.walk(followlinks=False)`, skip non-regular files, and
  `commonpath`-check the one-hop launcher target.
  **Contract landed 2026-08-03 in `design.md § Everything the Scanner reads is hostile`: 256 KB per-file cap, per-line deadline, non-backtracking two-step, `followlinks=False`, non-regular files skipped, one-hop target `commonpath`-checked. **Implementation lands with LWSM-1006.****
  Dependencies: LWSM-1006.
  **Layman:** Stop a huge or malicious file in a scanned folder from
  hanging the app.
  Kind: security.
  Source: security-review-2026-08-03.
  Priority: 2.
  Lanes: core.

- ✅ [LWSM-1051] **FP01: say plainly that `LWSM_MANAGED` is not
  authentication.** It is unauthenticated, forgeable, inherited
  by every descendant and readable from `/proc`. ADR-0006 rule 3
  reads as style advice, and the prompt is about to be pasted
  into seven codebases where the obvious next step is "if
  managed, skip the confirmation". One sentence in ADR-0006 and
  the adoption prompt (now `docs/private/port-contract-prompt.md`,
  author-private): a presentation hint with no
  security value — never grant, skip or relax anything on it.
  Free now, impossible to retrofit across seven repos later.
  **Done 2026-08-03 — ADR-0006 and the adoption prompt now state in the normative voice that `LWSM_MANAGED` has no security value and may never grant, skip or relax anything.**
  Dependencies: none.
  **Layman:** Make sure nobody later treats "the manager started me"
  as proof of anything.
  Kind: security.
  Source: security-review-2026-08-03.
  Priority: 2.
  Lanes: docs.

---

## P01 — Bootstrap (target: next)

**Theme:** wire up the build, lint, format, test and CI plumbing
chosen in Phase A. Zero user-facing features. Forces the audit
harness to be known-working before any business code lands.

### 🧰 Dev experience

- ✅ [LWSM-1001] **P01: uv + ruff + pytest + pytest-qt + CI wired
  up.** `pyproject.toml` declaring Python ≥ 3.13, PySide6 and
  psutil as runtime deps and pytest / pytest-qt / ruff as dev
  deps; `uv sync` resolves and writes `uv.lock`; `pytest` exits 0
  on a placeholder suite under `QT_QPA_PLATFORM=offscreen`;
  `ruff check` and `ruff format --check` both exit 0; a GitHub
  Actions workflow runs all three on `ubuntu-24.04`. A trivial
  `src/lwsm/__init__.py` with a version constant is the only
  source.
  Dependencies: none.
  **Layman:** Set up the tools that build and check the code, before
  writing any of it.
  Kind: chore.
  Source: in-session-2026-08-03.
  Priority: 2.
  Lanes: build, ci, tests.
  Done 2026-08-03; status corrected 2026-08-06 (the code landed but the bullet was never flipped). Verified against the acceptance clause by clause: pyproject.toml declares requires-python >=3.13, PySide6==6.11.1 and psutil==7.2.2 as runtime deps, pytest-qt==4.5.0 and ruff==0.16.1 as dev deps; uv.lock is resolved and committed; scripts/local-ci.sh exports QT_QPA_PLATFORM=offscreen and 14 tests pass; ruff check and ruff format --check both exit 0; .github/workflows/ci.yml runs on ubuntu-24.04 and calls the same script.

- ✅ [LWSM-1002] **P01: `.gitignore` populated for Python + Qt.**
  Adds `__pycache__/`, `*.py[cod]`, `.venv/`, `.pytest_cache/`,
  `.ruff_cache/`, `dist/`, `build/`, `*.egg-info/`, plus
  `.roadmap-counter` (already present) and KDE/IDE dotfiles.
  `uv.lock` is **committed**, not ignored.
  Dependencies: LWSM-1001.
  **Layman:** Tell git which generated files to leave out of the
  project history.
  Kind: chore.
  Source: in-session-2026-08-03.
  Priority: 3.
  Lanes: build.
  Done 2026-08-03; status corrected 2026-08-06. Every path named in the acceptance is present in .gitignore (__pycache__/, *.py[cod], .venv/, .pytest_cache/, .ruff_cache/, dist/, build/, *.egg-info/, .roadmap-counter, KDE/IDE dotfiles), and uv.lock is committed rather than ignored — confirmed with git ls-files, with a comment in .gitignore recording why.

- ✅ [LWSM-1004] **P01: create the public GitHub repository.**
  `github.com/milnet01/LocalWebServerManager`, public, MIT, with
  the existing `.github/` templates and dependabot config pushed.
  **Done 2026-08-03** — created public at
  `github.com/milnet01/LocalWebServerManager` on the user's
  authorisation, published from a squashed orphan commit per
  LWSM-1045. Verified by re-cloning: 1 commit, 52 files, no
  project names, machine paths or emails in tree or history, and
  `docs/private/` absent. First CI run green; dependabot accepted
  both ecosystems.
  Dependencies: LWSM-1001.
  **Layman:** Put the project on GitHub so it has a home and CI can
  run.
  Kind: chore.
  Source: user-2026-08-03.
  Priority: 3.
  Lanes: build, ci.

- ✅ [LWSM-1026] **P01: application log.** `app.log` at
  `~/.local/state/localwebservermanager/`, INFO by default,
  rotating at 1 MB with 5 kept, recording every spawn, signal,
  port-probe result and config write — as specified in
  `docs/design.md § Observability` but previously owned by no
  roadmap item. Wired at bootstrap so every later phase logs from
  its first line rather than having logging retrofitted.
  Dependencies: LWSM-1001.
  **Layman:** Keep a diary of what the app did, so "why did it say
  that?" is answerable later.
  Kind: implement.
  Source: doc-audit-2026-08-03.
  Priority: 3.
  Lanes: core.
  Done 2026-08-03; status corrected 2026-08-06. src/lwsm/applog.py logs at INFO into $XDG_STATE_HOME/localwebservermanager (falling back to ~/.local/state), rotating at MAX_BYTES = 1 MiB with BACKUP_COUNT kept. Went beyond the bullet on the security review's finding: _NoFollowRotatingFileHandler opens O_NOFOLLOW 0600 in a 0700 directory, so the log cannot be written through a symlink. Covered by tests/test_applog.py.

---

## P02 — Vertical slice (target: after P01 closes)

**Theme:** the smallest feature that touches every layer —
config file → core logic → OS probe → widget → test. Forces the
integration pain to surface before more code lands on it.

### 🎨 Features

- ✅ [LWSM-1005] **P02: one hand-written project renders a live
  status dot.** A `projects.json` written by hand (no scanner
  yet) is loaded by `Registry`; `PortProbe` reads the socket
  table once per second; `MainWindow` shows one row with a
  green/red dot that flips within 2 seconds when a server on that
  port starts or stops. Only two states — running and stopped —
  and no start/stop buttons; the point is the vertical wiring,
  not the feature. **The row is built accessibly from the first
  commit** — state as a word, an accessible name, keyboard
  reachable, one theme applied through tokens — because
  `docs/standards/coding.md § O8` makes that part of "done" and
  because retrofitting it across a finished UI is how it fails to
  happen. The full theme set and the text-size control come later
  (LWSM-1031, LWSM-1032); the *shape* starts correct. Test: a
  fake server binding an OS-assigned port flips the row, verified
  with `qtbot.waitUntil`.
  Dependencies: LWSM-1001.
  **Layman:** Get one project showing up correctly in the window, all
  the way from the saved file to the coloured dot, to prove the
  pieces fit together.
  Kind: implement.
  Source: in-session-2026-08-03.
  Priority: 2.
  Lanes: core, ui, tests.
  Progress (2026-08-06): spec written and gated — docs/specs/LWSM-1005-vertical-slice.md, accepted after 3 cold-eyes loops (64 findings verified, 64 fixed, 0 unverified). Contract beyond the bullet: the probe runs on a QThreadPool worker per design.md § State management, a third status `unknown` covers "no observation available", and the controller exposes RowView rather than a bare status map. 16 invariants, 8 `nothing` rows. Implementation next.
  Resolved (2026-08-06): five modules (registry, ports, controller, theme, mainwindow) plus `build_window()` in the entry point. 68 tests pass, `./scripts/local-ci.sh` green with no SKIPs. Verified beyond the suite by running the real entry point against a bound OS-assigned port: rows read "running, demo-live, port 57367" / "stopped, demo-down, port 1" / "unknown, demo-noport, no port", and the first flips to stopped when the socket closes. Four invariants mutation-tested (INV-4, INV-6, INV-11, INV-13) — each assertion seen to fail against a deliberately broken implementation and pass against the real one. Three deltas from the bullet, all specced: a third status `unknown` where nothing can be observed, the probe on a QThreadPool worker per design.md § State management, and `RowView` rather than a bare status map.

---

## P03 — Project discovery (criterion 1)

**Theme:** find the projects on disk so the user never types a
path. `docs/design.md § Detection rules` is the contract.

### 🎨 Features

- 📋 [LWSM-1006] **P03: Scanner implements the detection rules.**
  Walks each scan root's immediate subdirectories, ≤ 3 levels
  deep, skipping `node_modules` / `.git` / `.venv` / `venv` /
  `__pycache__` / `dist` / `build` / `.cache`, under a 20-second
  budget. Launcher precedence and declared-port sources exactly
  as specified, including framework defaults, read from the
  launcher and the **one** file it runs — which for a `systemd`
  project means the unit's `Environment=` / `ExecStart`, the unit
  being that project's launcher. Every value carries **its
  provenance** and a confidence of *detected* or *unknown*.
  Acceptance: against a fixture tree mirroring the seven real
  projects, each is found with the right launcher and port or an
  honest *unknown*, `node_modules` is never descended, and the
  fixture tree is the **regression corpus every future
  mis-detection gets added to**.
  **Scope narrowed 2026-08-08 (user, size gate).** The three
  remaining sources measure 2 names — `.env`, `docker-compose.yml`,
  `README.md` — and measure 3's conflict reporting moved to
  **LWSM-1121**; none of the seven is detected by them. This item
  also lands **LWSM-1050**'s hardening, per that bullet, and
  widens `tests/test_layering.py`'s `CORE_MODULES` per
  `coding.md § O1`.
  Dependencies: LWSM-1005.
  **Layman:** Teach the app to find your projects by itself and work
  out how each one starts.
  Kind: implement.
  Source: in-session-2026-08-03.
  Priority: 2.
  Lanes: core, tests.

- 📋 [LWSM-1007] **P03: Registry persistence and the rescan
  merge.** Atomic writes, `schema_version` checking, and the
  merge rules in [ADR-0005](docs/decisions/0005-registry-and-rescan.md):
  new / unchanged / changed / missing, user overrides winning,
  nothing auto-deleted, duplicate ports flagged with the
  first-registered tie-break. A **Rescan** button reports what
  changed.
  Dependencies: LWSM-1006.
  **Layman:** Remember the project list between runs, and let a
  rescan pick up new projects without undoing your edits.
  Kind: implement.
  Source: in-session-2026-08-03.
  Priority: 2.
  Lanes: core, ui, tests.

- 📋 [LWSM-1039] **P03: keep one backup of the registry.** Every
  write of `projects.json` keeps the previous version alongside
  it (`projects.json.bak`), and a file that fails to parse or
  fails its `schema_version` check offers to restore from it
  rather than starting empty. The registry accumulates hand-tuned
  work — renamed projects, port overrides, custom actions,
  confirmed ports — that no rescan can reconstruct, so losing it
  to a bad merge or a botched hand-edit is the one data loss this
  app is capable of. A few lines against that is cheap.
  Dependencies: LWSM-1007.
  **Layman:** Keep yesterday's copy of your project list, so a
  corrupted file doesn't throw away your settings.
  Kind: implement.
  Source: user-2026-08-03.
  Priority: 2.
  Lanes: core, tests.

- 📋 [LWSM-1008] **P03: first-run confirmation flow.** No config
  file present → scan → present the detected list for
  confirmation before anything is written. Acceptance: criterion
  1 demonstrated end to end on a machine with no config.
  Dependencies: LWSM-1007.
  **Layman:** On the very first run, show what was found and let you
  confirm it before saving.
  Kind: implement.
  Source: in-session-2026-08-03.
  Priority: 2.
  Lanes: ui, tests.

- 📋 [LWSM-1121] **P03: Scanner reads the extra port sources and
  reports conflicts.** Beyond the launcher and its one-hop file
  (LWSM-1006), the three remaining sources
  [`design.md § Robustness`](docs/design.md) measure 2 names: a
  `.env` / `.env.local` `PORT=`, a `docker-compose.yml` `ports:`
  mapping, and — lowest confidence — a `localhost:NNNN` in the
  project's `README.md`. Each value carries its provenance, and
  measure 3 lands with them: when two sources give different ports
  the higher-confidence one wins **and the conflict is shown**,
  never silently resolved.
  Split out of LWSM-1006 by the user on 2026-08-08 on the size gate
  (`docs/standards/spec-format.md § 5.4`): the seven known projects
  are all detected from the launcher and its one-hop file, so these
  sources are robustness beyond that item's acceptance test rather
  than part of it. The systemd unit's `Environment=` / `ExecStart`
  stays with LWSM-1006, because for a `systemd` project the unit
  **is** the launcher and reading it is that item's one-hop rule.
  Acceptance: a fixture project per source is detected with the
  right port and the right provenance label, and a fixture whose
  `.env` and launcher disagree reports both rather than resolving
  to one.
  Dependencies: LWSM-1006.
  **Layman:** Also look in a few other common places for a
  project's port, and say so when two of them disagree instead of
  quietly picking one.
  Kind: implement.
  Source: in-session-2026-08-08 (split from LWSM-1006).
  Priority: 2.
  Lanes: core, tests.

---

## P04 — Appearance and accessibility foundation

**Theme:** the visual and accessible foundation, laid **before**
the real UI is built on it. Moved ahead of the feature phases by
the user on 2026-08-03: the primary user reads with a screen
magnifier, so this is a design input, and
`docs/standards/coding.md § O8` forbids retrofitting it.

### 🖥 Platform

- 📋 [LWSM-1031] **P04: theme layer — six themes plus
  high-contrast.** Nine semantic tokens plus `is_dark`, expanded
  into both a `QPalette` and a generated style sheet, switchable
  without a restart. The six palettes are **adopted from
  `finbreak/src/finbreak/ui/theme.py`** (midnight, graphite,
  emerald, ledger, parchment, mint) rather than invented, plus
  this project's **seven** state tokens — one per ADR-0004 derived
  state, `design.md § Tokens, not colours` canonical — and a
  **high-contrast theme in light and dark**, which is an assistive
  tool rather than a seventh colour scheme. finbreak is
  **provenance**: the values are transcribed into this repo as the
  item's first step, since a public repo cannot depend on a path
  outside it. Follow-system resolves to midnight or ledger.
  Acceptance: the contrast test in `docs/standards/testing.md § T8`
  passes for every theme, including the adopted ones — any finbreak
  pair that falls short is adjusted here and the divergence
  recorded — and T8 gains the 7:1 floor for the two high-contrast
  palettes.
  Dependencies: LWSM-1005.
  **Layman:** Make it look modern, with a set of dark and light
  colour schemes plus a high-contrast one, switchable on the fly.
  Kind: implement.
  Source: user-2026-08-03.
  Priority: 2.
  Lanes: ui, tests.
  Cold-eyes 2026-08-06 (design.md loops 3-4): this item now owns
  transcribing the finbreak palette values INTO this repo as its
  first step — a public repo cannot depend on a path outside it, so
  the theme layer had no buildable contract until that lands. Token
  count corrected six -> seven (one per ADR-0004 derived state,
  including the previously missing running (foreign)). Acceptance
  gains the 7:1 floor for the two high-contrast palettes, now
  written into testing.md § T8.

- 📋 [LWSM-1032] **P04: accessibility pass — magnifier-first.**
  The primary user is partially sighted and reads with a screen
  magnifier, so this is a design constraint rather than a
  compliance sweep: state spelled out as a **word** with colour
  and glyph reinforcing it, related information grouped inside
  one lens view, feedback surfacing next to the control that
  caused it, dialogs opening near the focus, nothing hover-only,
  an unmissable focus ring, and an **in-app text-size control
  (100–200 %)** that reflows without clipping. Accessible names
  and descriptions on every interactive widget; state exposed as
  text so a screen reader announces "project-b, running, port
  5005". Acceptance: all four checks in
  `docs/standards/testing.md § T8` pass, **and** every row of
  `design.md § Accessibility`'s check table lands — greyscale
  readability, the 7:1 high-contrast floor, focus-ring contrast,
  target size, announce-once, reduce-motion, confirmation
  placement, state-word-first, one-lens-view, feedback placement,
  no-hover-only, focus-never-stolen and system-font honouring.
  Four checks alone would let this close with most of the section
  unbuilt.
  Dependencies: LWSM-1031.
  **Layman:** Make the app genuinely usable with a magnifier — big
  readable state text, things that belong together kept together,
  and everything reachable from the keyboard.
  Kind: accessibility.
  Source: user-2026-08-03.
  Priority: 1.
  Lanes: ui, tests.
  Cold-eyes 2026-08-06 (design.md loops 3-4): acceptance widened.
  "All four T8 checks pass" would have let this close green with
  most of the section unbuilt — thirteen of its promises had no test
  surface at all. design.md § Accessibility now carries a check
  table, and every row of it is part of this item's acceptance.

- 📋 [LWSM-1040] **P04: keyboard-first navigation.** Number keys
  jump to a project, Enter starts or stops the selected one, `/`
  focuses a filter box that narrows the list, Escape clears it.
  Placed in the accessibility foundation rather than treated as a
  power-user extra: for a magnifier user, reaching a control by
  keystroke beats panning a lens across the window to find it,
  and a filter that shrinks the list to one row removes the
  panning entirely. It also makes
  `docs/standards/testing.md § T8`'s keyboard-reachability check
  natural to satisfy rather than a retrofit.
  Dependencies: LWSM-1031.
  **Layman:** Drive the whole app from the keyboard, and filter the
  list down so what you want is right in front of you.
  Kind: accessibility.
  Source: user-2026-08-03.
  Priority: 2.
  Lanes: ui, tests.

- 📋 [LWSM-1033] **P04: window geometry and Centre on screen.**
  Size, position and maximised state persisted as plain integers
  in `settings.json` and restored on launch — **including
  position under Wayland**, via the same one-shot KWin script
  that centres the window, per
  [ADR-0007](docs/decisions/0007-window-geometry-and-centering.md).
  A **Centre on screen** action, disabled with an explanatory
  tooltip where the platform cannot honour it. Restored geometry
  is clamped to the currently-attached screens. Acceptance is
  **behavioural** — the window ends up at the requested
  coordinates under both `XDG_SESSION_TYPE` values — never that a
  placement call was made, which is precisely the test that
  passes while OneUp reopens in the wrong place.
  Dependencies: LWSM-1005.
  **Layman:** Reopen the window the size and place you left it, and
  add a button to bring it back to the middle of the screen.
  Kind: implement.
  Source: user-2026-08-03.
  Priority: 2.
  Lanes: ui, tests.

---

## P05 — Start, stop, restart (criterion 2)

**Theme:** the buttons. [ADR-0003](docs/decisions/0003-launch-via-project-scripts.md)
is the contract.

### 🎨 Features

- 📋 [LWSM-1009] **P05: Supervisor spawns and reaps process
  groups.** `subprocess.Popen(start_new_session=True)` with an
  argument vector, `cwd` at the project, `PORT` in the
  environment, output merged into a per-project log file. Stop
  signals the group with `SIGTERM`, then `SIGKILL` after 5 s if
  anything is alive **or** the port is still bound; stop runs on
  a worker thread. **Includes the pre-flight port check** — the
  design makes it step 1 of every start and ADR-0003 makes
  Restart "stop then start *with the same pre-flight check*", so
  Start cannot ship without it; it needs only the port → PID
  direction that P02 already builds. The conflict-warning *UI*
  stays in P07. Per-project log files are capped at 5 MB with one
  rotation. Acceptance: the wrapper-script fixture (`start.sh`
  spawning a Python child) is fully reaped — no orphan holds the
  port.
  Dependencies: LWSM-1005.
  **Layman:** Make Start and Stop actually work, including stopping
  the hidden helper processes that would otherwise keep the port.
  Kind: implement.
  Source: in-session-2026-08-03.
  Priority: 1.
  Lanes: core, tests.

- 📋 [LWSM-1028] **P05: service-managed projects driven through
  `systemctl`.** A project owned by a systemd **user unit** gets
  its verbs from the service manager — `start` / `stop` /
  `restart` / `is-active`, with logs from `journalctl --user -u`
  — instead of being spawned directly. Detection makes the
  systemd kind outrank every script rule, per
  `docs/design.md § Detection rules` rule 0. **Not optional:**
  `project-a` is driven by an enabled
  `project-a.service` (verified 2026-08-03), so spawning
  `node serve.mjs` for it would collide with systemd's instance
  on port 4321 or create a second, unsupervised copy.
  Acceptance: that project starts, stops and reports status
  correctly with systemd remaining the owner throughout.
  Dependencies: LWSM-1009.
  **Layman:** Some servers are already run by the system's own
  service manager — drive those through it instead of starting a
  second copy that fights the first.
  Kind: implement.
  Source: user-2026-08-03.
  Priority: 1.
  Lanes: core, tests.

- 📋 [LWSM-1010] **P05: start / stop / restart in the UI with the
  optimistic overlay.** Buttons wired through `ProjectController`,
  with the bounded overlay in `docs/design.md § State management`
  so the UI responds immediately and probing always wins.
  Acceptance: criterion 2's full round-trip, each transition
  visible within 2 seconds.
  Dependencies: LWSM-1009.
  **Layman:** Wire the buttons into the window so they respond the
  instant you click them.
  Kind: implement.
  Source: in-session-2026-08-03.
  Priority: 2.
  Lanes: ui, tests.

- 📋 [LWSM-1016] **P05: open in browser.** Opens
  `http://localhost:<bound port>` via `QDesktopServices` — the
  port actually bound, never the requested one, since the two
  differ exactly when a project ignored `PORT`. Enabled in all
  three running states, including `running (foreign)`. **Moved
  from P08 into P05 (user, 2026-08-03):** it completes success
  criterion 2, which requires a started project to be "observed
  to be reachable in a browser", and it is half of what replaces
  the per-project tray icons — see LWSM-1027.
  Dependencies: LWSM-1010.
  **Layman:** One click to open a running site in your browser.
  Kind: implement.
  Source: user-2026-08-03.
  Priority: 2.
  Lanes: ui.

- 📋 [LWSM-1055] **P05: a per-project browser choice for Open in
  browser.**
  LWSM-1016 opens the desktop default. A project the user always
  wants in a *particular* browser — a work profile, one carrying the
  right extensions, one kept apart from a personal session — means
  opening it by hand every time. Store an optional browser choice
  per project in the registry, falling back to the desktop default
  when unset. **Pick from the browsers the system reports, never a
  free-text command string:** LWSM-1049 constrains Open in browser
  to http/https through `QDesktopServices` precisely because this
  button carries the manager's credibility, and a per-project
  *command* hands that back. The field is user-set only and must
  never be populated by detection, which LWSM-1049 already classes
  as untrusted input. Acceptance: two projects set to different
  browsers each open in the right one; a project with none set opens
  in the desktop default; a browser since uninstalled falls back to
  the default with a visible message rather than failing silently.
  **Interacts with LWSM-1053** — a sibling that opens its own
  browser at startup ignores this preference entirely, so once this
  lands the sibling browser-open stops being cosmetic and starts
  contradicting a setting the user deliberately chose.
  Dependencies: LWSM-1016, LWSM-1007.
  **Layman:** Choose which browser each site opens in — handy if
  you keep one browser for work and another for everything else —
  instead of every site using the system default.
  Kind: implement.
  Source: user-2026-08-06.
  Priority: 2.
  Lanes: ui, core, tests.

---

## P06 — The full state model (criterion 3)

**Theme:** tell the truth in every case, including the awkward
ones. [ADR-0004](docs/decisions/0004-runtime-truth-from-probing.md)
is the contract.

### 🎨 Features

- 📋 [LWSM-1011] **P06: the seven-state classifier.** One
  socket-table snapshot per tick classified against ADR-0004's
  table, including `running (wrong port)`, `port blocked`, the
  plausibility test for foreign holders, `starting` with **no
  deadline** — a real managed project takes ~40 s to bind, so a
  timer would report a healthy launch as `failed` (ADR-0004
  § Slowness is not failure) — and the one-poll lifetime of an
  exited-child record.
  Includes **post-flight verification** — the process-group → ports
  lookup that detects a project which ignored `PORT` and produces
  the `running (wrong port)` state. Delivered as the parametrised
  test named per state that `docs/standards/testing.md § T7`
  requires.
  Dependencies: LWSM-1009.
  **Layman:** Work out honestly what each project is really doing —
  including when someone else started it, or it ignored the port
  you asked for.
  Kind: implement.
  Source: in-session-2026-08-03.
  Priority: 1.
  Lanes: core, tests.

- 📋 [LWSM-1038] **P06: confirmed ports — detection learns from
  what actually happens.** The first time a project is observed
  listening — started by us, or found already running with a
  holder whose working directory is inside the project — record
  the port it **actually bound** as `confirmed_port`, and prefer
  it over any detected guess thereafter. The highest-value
  robustness measure in the design: it turns every project into a
  measured fact after one run, and it is the only mechanism that
  reaches a port the static rules cannot read at all — such as
  `project-e`'s, which sits two hops from its launcher.
  Confidence is shown as *confirmed* / *detected* / *unknown*, so
  the user can see which projects are guesses.
  Dependencies: LWSM-1011.
  **Layman:** Once the app has seen a project run, it knows that
  project's real port for certain instead of guessing from the code.
  Kind: implement.
  Source: user-2026-08-03.
  Priority: 1.
  Lanes: core, tests.

- 📋 [LWSM-1034] **P06: health check — bound is not the same as
  working.** An optional HTTP `GET` to `http://localhost:<bound
  port>/` per project, on a slower cadence than the status poll,
  showing the result **as words**: "running, HTTP 200",
  "running, HTTP 500", "running, no response". A port probe
  structurally cannot see a server that binds and then errors on
  every request, which is the failure this catches. Off by
  default per project, with a configurable path — a `GET /` is
  harmless for a dev server but is still a request someone else's
  code will handle. Timeouts are short and never block the poll.
  Dependencies: LWSM-1011.
  **Layman:** Actually ask the site if it's OK, rather than just
  noting that something is listening — so a broken site reads as
  broken instead of green.
  Kind: implement.
  Source: user-2026-08-03.
  Priority: 2.
  Lanes: core, ui, tests.

- 📋 [LWSM-1012] **P06: foreign-server adoption and guarded
  stop.** A server started outside the app shows as running and
  labelled; Stop enumerates the holder's descendants, names them
  in a confirmation dialog, and signals exactly that set — never
  a process group the app did not create. Acceptance: criterion 3's
  three cases, including the app being closed and reopened.
  Dependencies: LWSM-1011.
  **Layman:** Recognise servers you started in a terminal, and be
  careful about stopping something the app didn't start.
  Kind: implement.
  Source: in-session-2026-08-03.
  Priority: 2.
  Lanes: core, ui, tests.

- 📋 [LWSM-1054] **P06: cover the sibling that respawns itself
  detached.** project-e's settings page has a Restart button that
  spawns a fresh copy in a **new session** and then exits 0. So the
  process this app started exits *cleanly* while the port stays
  bound by a grandchild in a process group we never created.
  ADR-0004 already answers it — a clean exit is not evidence of
  failure, and the re-probe should land on `running (foreign)` with
  Stop routed through LWSM-1012's guarded path — but nothing
  exercises it, and `docs/standards/testing.md` T2 names five
  fixture launcher shapes, none of which respawn. Add a sixth
  (spawn a detached replacement, then exit 0) and a case to the T7
  state-table test; T2's list is updated in the same change.
  Acceptance: after the fixture respawns, the app reports
  `running (foreign)` rather than `stopped`, and Stop names the
  surviving process in the confirmation dialog rather than
  signalling a group it does not own.
  Dependencies: LWSM-1011, LWSM-1012.
  **Layman:** One of the sites can restart itself from its own
  settings page, which makes it look like it stopped when it is
  really still running. Make sure we notice that instead of
  mis-reporting it.
  Kind: test.
  Source: in-session-2026-08-06.
  Priority: 2.
  Lanes: core, tests.

---

## P07 — Ports (criterion 4)

**Theme:** never launch into an occupied port, and make
reassignment stick. [ADR-0002](docs/decisions/0002-port-contract.md)
is the contract.

### 🎨 Features

- 📋 [LWSM-1013] **P07: the conflict warning UI.** When the
  pre-flight check built in LWSM-1009 refuses a start, the window
  says what is holding the port — naming the process, or saying
  plainly that the holder cannot be inspected — and offers to
  reassign. (Post-flight verification ships with LWSM-1011, which
  owns the `running (wrong port)` state it produces.)
  Dependencies: LWSM-1011.
  **Layman:** Check the port is free before starting, and say what's
  in the way when it isn't.
  Kind: implement.
  Source: in-session-2026-08-03.
  Priority: 2.
  Lanes: core, ui, tests.

- 📋 [LWSM-1041] **P07: "what's using this port?" lookup.** A
  search box answering the question the whole project started
  from — type a port, get the process holding it, whether or not
  it belongs to a known project, or "nothing is listening on
  that". Nearly free: it queries the socket-table snapshot the
  status poll already takes every second. Where the holder cannot
  be attributed to this user it says so, per ADR-0004, rather
  than inventing an owner. Replaces reaching for `ss -tlnp`.
  Dependencies: LWSM-1013.
  **Layman:** Type a port number and find out what's sitting on it —
  even if it isn't one of your projects.
  Kind: implement.
  Source: user-2026-08-03.
  Priority: 3.
  Lanes: ui, core.

- 📋 [LWSM-1037] **P07: suggest a free port.** When reassigning,
  propose a port that is actually free — checked against the live
  socket table and against every other project's effective port,
  so the suggestion cannot collide with a project that simply
  is not running yet. Offered as a default the user can override,
  never imposed.
  Dependencies: LWSM-1013.
  **Layman:** When you change a port, offer one that's actually
  free instead of letting you guess and be refused.
  Kind: implement.
  Source: user-2026-08-03.
  Priority: 3.
  Lanes: core, ui.

- 📋 [LWSM-1014] **P07: port override, validated and
  persisted.** Assign a different port from the UI; validated at
  entry against 1024–65535; survives restart; passed as `PORT` on
  the next launch. Acceptance: criterion 4 demonstrated against a
  sibling that has adopted the contract, and honest degradation
  against one that has not.
  **A real non-adopter exists to test against** — one managed
  project will never adopt the contract (ADR-0002 § Adoption is
  not universal), and its launcher *assigns* `PORT` rather than
  reading it, so it is the honest-degradation case in the flesh
  rather than a fixture.
  Dependencies: LWSM-1013.
  **Layman:** Let you change a project's port and have it stay
  changed.
  Kind: implement.
  Source: in-session-2026-08-03.
  Priority: 2.
  Lanes: core, ui, tests.

---

## P08 — Logs (criterion 5)

### 🎨 Features

- 📋 [LWSM-1015] **P08: live log panel.** Tails the per-project
  log file into a bounded ring (2000 lines), follows unless the
  user has scrolled up, and retains the tail after exit so a
  crash can be read after the fact. A foreign server, which has
  no log file, says so rather than showing an empty panel.
  Acceptance: criterion 5 — a server that dies on startup is
  diagnosable without opening a terminal.
  Dependencies: LWSM-1009.
  **Layman:** Show each server's output in the app, so when one
  breaks you can see why without hunting for a terminal.
  Kind: implement.
  Source: in-session-2026-08-03.
  Priority: 2.
  Lanes: ui, tests.

- 📋 [LWSM-1036] **P08: find the error in the log.** A **jump to
  last error** action and an **errors-only** filter over the log
  panel, matching the usual markers (`Traceback`, `ERROR`,
  `CRITICAL`, `Exception`, a non-zero exit line). Scrolling a
  wall of output under a magnifier is slow and easy to lose your
  place in, so the app finds the line rather than making the user
  hunt for it. The match set is configurable, because every
  runtime shouts differently.
  Dependencies: LWSM-1015.
  **Layman:** Take me straight to what went wrong, instead of making
  me scroll through everything that went right.
  Kind: implement.
  Source: in-session-2026-08-03.
  Priority: 2.
  Lanes: ui, tests.

---

## P09 — Shell: tray, settings, session

### 🎨 Features

- 📋 [LWSM-1017] **P09: minimal system tray — show/hide and
  quit.** Closing the window hides to tray and leaves servers
  running; the tray offers *Show window*, *Hide*, and the app's
  only genuine Quit. **Deliberately no per-project submenu**
  (user, 2026-08-03): a 22-pixel icon with a nested menu is a
  poor surface for a magnifier user, it would be a second UI
  owing the same accessibility bar as the first, and once
  restore-last-session (LWSM-1035) and start-at-login
  (LWSM-1027) exist, the tray's real job is bringing the window
  back. A tray tooltip summarising how many projects are running
  is enough status for an icon to carry.
  Dependencies: LWSM-1010.
  **Layman:** Tuck the app into the system tray instead of quitting,
  so your sites keep running — but keep the icon simple, since a
  tiny menu is awkward to use with a magnifier.
  Kind: implement.
  Source: user-2026-08-03.
  Priority: 3.
  Lanes: ui, tests.

- 📋 [LWSM-1035] **P09: restore last session, and stop all.**
  Two bookends for a working day. On launch, optionally start
  whatever was running when the app last quit — recorded as an
  observation at shutdown, not as a per-project flag the user has
  to maintain. And a single **Stop all** action that frees every
  port at once, with one confirmation naming what it will stop,
  never seven. Both honour the pre-flight check and the
  foreign-server guard.
  Dependencies: LWSM-1010.
  **Layman:** Pick up where you left off, and one button to shut
  everything down at the end of the day.
  Kind: implement.
  Source: user-2026-08-03.
  Priority: 2.
  Lanes: core, ui, tests.

- 📋 [LWSM-1029] **P09: custom per-project actions.** A
  user-authored `actions` list per project — `open_file`,
  `open_url`, `run_command` — rendered in the detail pane and the
  tray submenu, per `docs/design.md § Custom project actions`.
  This is what stops the consolidation being a downgrade: the
  applets being retired carry actions the manager otherwise
  loses. Known cases to reproduce: project-c's *Edit prompts.md*
  and *Edit blocks.md* (`open_file`), and project-d's tray
  *Refresh stats now* (`run_command`). Detection never authors an
  action — only the user does.
  Dependencies: LWSM-1015.
  **Layman:** Let each project have its own extra buttons, so the
  handy things its old tray icon could do aren't lost.
  Kind: implement.
  Source: user-2026-08-03.
  Priority: 2.
  Lanes: ui, core, tests.

- 📋 [LWSM-1030] **P09: set `LWSM_MANAGED` so siblings suppress
  their own tray.** The manager sets `LWSM_MANAGED=1` in every
  process it spawns, per
  [ADR-0006](docs/decisions/0006-managed-mode-signalling.md). The
  manager's half is one line; the sibling half ships in the
  adoption prompt. Grouped here rather than in P05 because it is
  only *useful* once the manager can replace what the trays do —
  start at login (LWSM-1027) and their extra actions
  (LWSM-1029).
  Dependencies: LWSM-1009.
  **Layman:** Tell each project "I'm managing you now", so it hides
  its own tray icon and you're not looking at two of everything.
  Kind: implement.
  Source: user-2026-08-03.
  Priority: 3.
  Lanes: core.

- 📋 [LWSM-1042] **P09: crash-loop guard.** Any path that starts
  a server **automatically** — restore-last-session today, and
  anything added later — stops retrying after 3 failures inside
  60 seconds, marks the project `failed (crash loop)`, and
  surfaces the log tail. Without it, "restore my session" can
  spend a morning respawning a server that dies on startup, and
  the app becomes the thing generating the noise it exists to
  reduce. Deliberately scoped to automatic starts: a human
  pressing Start three times means it, and is never blocked.
  Dependencies: LWSM-1035.
  **Layman:** If something keeps dying the moment it starts, stop
  retrying and tell me, instead of thrashing in the background.
  Kind: implement.
  Source: user-2026-08-03.
  Priority: 2.
  Lanes: core, tests.

- 📋 [LWSM-1027] **P09: start-at-login, per project.** A
  per-project *start automatically* flag, plus an autostart
  `.desktop` entry for the manager itself, so the chosen projects
  come up with the session. **This is the piece that makes the
  per-project tray icons redundant** — without it, replacing them
  costs the user a manual start every morning, which is a
  downgrade, not a simplification. Verified 2026-08-03: two of
  the five entries in `~/.config/autostart/` are per-server trays
  (`project-c-tray.desktop`, `project-a-tray.desktop`) and are
  the ones this can retire; the other three are unrelated apps.
  Acceptance: after enabling the flag for a project and logging
  out and back in, that project is running and reachable, with no
  per-project tray involved.
  Dependencies: LWSM-1017, LWSM-1016, LWSM-1029, LWSM-1030.
  **Layman:** Have chosen sites start on their own when you log in,
  so you can delete the little tray icons each project has today.
  Kind: implement.
  Source: user-2026-08-03.
  Priority: 2.
  Lanes: ui, core, tests.

- 📋 [LWSM-1018] **P09: settings dialog.** Edits scan roots, poll
  interval, slow-start threshold, log-buffer size and tray behaviour, all
  persisted to `settings.json` with its own `schema_version`.
  Dependencies: LWSM-1007.
  **Layman:** A settings screen for the folders it scans and how
  often it checks.
  Kind: implement.
  Source: in-session-2026-08-03.
  Priority: 3.
  Lanes: ui, tests.

- 📋 [LWSM-1053] **P09: decide whether an unattended start may open
  a browser.** A sibling's launcher may open the user's browser on
  every start — project-e's does, unconditionally — so a managed
  start throws a browser window onto the screen nobody asked for.
  ADR-0006 forbids a sibling conditioning anything but its tray
  icon on `LWSM_MANAGED`, so a compliant sibling **cannot** fix
  this itself; the choice is ours. Three ways out: (a) accept it,
  on the grounds that a project the user chose to start may show
  itself; (b) widen ADR-0006 from *tray icon* to *unattended-start
  presentation* — an ADR amendment with a cold-eyes gate, which
  re-opens the boundary LWSM-1051 pinned; (c) set `BROWSER` to a
  no-op inside the curated environment of LWSM-1048, which is a
  standard documented mechanism rather than a private hint, but
  reaches only siblings that go through Python's `webbrowser` and
  misses one that shells out to `xdg-open` directly. **(c) has
  since been tested both ways, and it is **partial by
  measurement, not by inference**. project-e's session pointed
  `BROWSER` at a recording script and observed `webbrowser.open`
  honouring it — that is the lever working. It then built that
  project's *frozen* artefact and watched it ignore `BROWSER`
  entirely, because a frozen build shells out to `xdg-open`
  directly. So (c) covers from-source siblings and silently
  misses frozen ones, which is the worst shape for a suppression
  mechanism: it would look like it worked. Decide before
  LWSM-1030 ships, because the answer changes what the adoption
  prompt asks of the siblings.
  Dependencies: LWSM-1030.
  **Layman:** When the app starts a site for you, that site may
  fling a browser window open by itself. Decide whether that is
  fine, or whether we suppress it.
  Kind: investigate.
  Source: in-session-2026-08-06.
  Priority: 3.
  Lanes: core, docs.

---

## P10 — Release for other people (📦 Packaging)

**Theme:** the project is public and meant to be useful to
strangers, so a release has to be something a person downloads
and runs. Nothing here is needed for the author's own use, which
is why it sits after the app works.

### 📦 Packaging

- 📋 [LWSM-1021] **P10: self-contained AppImage, built in CI.**
  One downloadable file that runs on any reasonably current
  x86-64 Linux without installing Python, PySide6 or anything
  else. Built by GitHub Actions on tag, attached to the release,
  and **smoke-tested in the workflow** by launching it headless
  and asserting it starts — an AppImage nobody ran is not a
  release. Includes the `.desktop` entry and icon so it
  integrates with the KDE launcher.
  Dependencies: LWSM-1017.
  **Layman:** Publish one file people can download and double-click,
  with nothing to install first.
  Kind: package.
  Source: user-2026-08-03.
  Priority: 2.
  Lanes: build, ci.

- 📋 [LWSM-1043] **P10: decide how updates reach users —
  research first.** The user already runs **OneUp**
  (`<scan root>/OneUp/`), an updater with a weekly
  systemd user timer, so the first question is whether this app
  should simply register with it rather than grow an update
  checker of its own. **Read OneUp before deciding** — this item
  is written from its file layout, not from its contract, and
  what it is designed to update is exactly the unverified part.
  Outcome is a decision either way: integrate, or record in an
  ADR why a released AppImage checking GitHub releases directly
  is the better fit. Not "build an updater" — that is the option
  most likely to be wrong.
  Dependencies: LWSM-1021.
  **Layman:** Work out how people get new versions — probably by
  reusing the updater you already have, rather than writing another.
  Kind: research.
  Source: user-2026-08-03.
  Priority: 3.
  Lanes: build, docs.

- 📋 [LWSM-1052] **P10: a local release script, run before CI is
  asked to build one.** `scripts/local-release.sh` builds and
  smoke-tests the AppImage on this machine, so a broken release
  surfaces locally rather than inside a tagged CI run that has
  already published a tag. Same rule as `scripts/local-ci.sh` and
  for the same reason: **the script is the source of truth and the
  release workflow calls it**, so the two cannot drift. A release
  is the worst possible place to discover a packaging bug, because
  the tag already exists by the time CI fails.
  Dependencies: LWSM-1021.
  **Layman:** Build and test the downloadable file on your own
  machine first, so a broken release never gets as far as GitHub.
  Kind: package.
  Source: user-2026-08-03.
  Priority: 2.
  Lanes: build, ci.

- 📋 [LWSM-1022] **P10: release process and user-facing docs.**
  A tagged release carrying the AppImage, a CHANGELOG section, and
  a README Install/Quickstart written for someone who has never
  seen the project. Success: a stranger gets from the repo page to
  a running window without asking a question.
  Dependencies: LWSM-1021.
  **Layman:** Make the download page and instructions good enough
  for someone who has never met you.
  Kind: doc.
  Source: user-2026-08-03.
  Priority: 3.
  Lanes: docs, build.

---

## DS01 — Debt sweep (2026-08-06)

The first debt sweep, run over the whole history because there had
never been one and the only tag is not an ancestor of HEAD. Every
dependency, action pin and runner image came back current, so
nothing below is technology debt. These are the items the sweep
could not close itself: each needs a decision, or work, or the
program actually running.

### 🧹 Cleanup / debt

- 📋 [LWSM-1056] **DS01: `main()` is a shipped entry point with no test.**
  `src/lwsm/__main__.py::main` takes an optional argv, branches on
  `--version` and returns an exit code, and nothing asserts on any of
  it. `scripts/local-ci.sh` § Entry points only `e.load()`s the
  console script — it proves the module resolves, never that calling
  it does the right thing. Assert `main(["--version"]) == 0` and the
  string it prints, with the state dir injected so the test does not
  touch the real one (testing.md § T1).
  Dependencies: none.
  **Layman:** The one command the app already ships is never actually run by a test — only checked that it exists.
  Kind: test.
  Source: debt-sweep-2026-08-06.
  Priority: 3.
  Lanes: tests.

- 📋 [LWSM-1057] **DS01: two measurements of the pre-scrub commit count disagree.**
  `ROADMAP.md` § FP01 intro and LWSM-1045's body say the leak was in
  "all 24 commits"; LWSM-1045's own resolution note says "all 26
  commits", and `docs/journal/P01.md` says 24. Derived this sweep:
  the `pre-public-history` tag holds 30 commits and the scrub commit
  `9dcabc9` is the 27th, so 26 preceded it. Either both were true
  when written and each needs its date, or 24 is simply wrong. The
  sweep did not adjudicate, because rewriting a dated finding is a
  call the author makes, not a sweep.
  Dependencies: none.
  **Layman:** Two places in the roadmap count the same thing differently; the real number looks like 26.
  Kind: doc-fix.
  Source: debt-sweep-2026-08-06.
  Priority: 4.
  Lanes: docs.

- 📋 [LWSM-1058] **DS01: decide whether contract-landed-only items are 🚧 or 📋.**
  LWSM-1046 … LWSM-1050 are all 🚧, which the legend defines as
  "being tackled now". What actually landed is each one's *contract*
  (ADR edits, 2026-08-03); every implementation is deferred to P05 or
  P06 and none has started. Either the legend gains a word for
  "designed, not built", or these five flip to 📋 with the contract
  noted in the body. Left alone by the sweep: it is a question about
  the roadmap's own vocabulary, and five statuses move on the answer.
  Dependencies: none.
  **Layman:** Five security items are marked "in progress" when only their design is done and no code has started.
  Kind: doc-fix.
  Source: debt-sweep-2026-08-06.
  Priority: 3.
  Lanes: docs.

- 📋 [LWSM-1059] **DS01: `pytest-qt` and the `gui` / `integration` markers are declared but unexercised.**
  `pyproject.toml` pins `pytest-qt==4.5.0` and registers both
  markers; no test uses either, so `local-ci.sh --fast` (which
  deselects `integration`) currently deselects nothing and the
  headless Qt path under `QT_QPA_PLATFORM=offscreen` has never run.
  That is expected before P02 — but it means the first GUI test is
  also the first proof the harness works, which is the wrong moment
  to find out it does not. Cannot be confirmed without running Qt.
  Dependencies: LWSM-1005.
  **Layman:** The test tools for the window are installed but nothing has used them yet, so we do not know they work.
  Kind: test.
  Source: debt-sweep-2026-08-06.
  Priority: 3.
  Lanes: tests, build.
  Progress (2026-08-06): LWSM-1005 is the first work to exercise any of these. `pytest-qt` now drives `test_controller.py` and `test_mainwindow.py`; both markers are used, and `tests/conftest.py` sets `QT_QPA_PLATFORM=offscreen` when unset so a bare `pytest` cannot open a real window. One lesson worth keeping when this item closes: markers belong on tests, not files — marking a whole file by its heaviest test makes `local-ci.sh --fast` silently skip every light test beside it.

- 📋 [LWSM-1060] **DS01: three agreed doc tasks exist only in a session journal.**
  `.claude/workflow.md` § 3 records three decisions the user took on
  2026-08-06 that are in no roadmap item: a `SECURITY.md` pointing at
  GitHub private vulnerability reporting (with the repo setting
  enabled), `CODE_OF_CONDUCT.md` as Contributor Covenant 2.1 verbatim
  replacing the homemade paragraph in `CONTRIBUTING.md`, and
  replacing ADR-0007's four unresolvable `OneUp/updater.py` citations
  with the technique itself. `docs/standards/documentation.md` § 2.4
  and § 2.5 require the first two files; neither is at the repo root.
  Filed here so they outlive the journal entry.
  Dependencies: none.
  **Layman:** Three jobs you already decided on are written down only in a session note — this puts them on the roadmap so they cannot get lost.
  Kind: doc.
  Source: debt-sweep-2026-08-06.
  Priority: 2.
  Lanes: docs.

- 📋 [LWSM-1061] **DS01: `spec-format.md` has no required-sections block, so that check never runs.**
  `spec_lint` only runs its `missing_section` check when the
  project's format standard carries a `<!-- required-sections -->`
  block. `docs/standards/spec-format.md` has none (verified
  2026-08-06), so the check is silently disabled and every run
  returns `sections_checked: false`. Nothing is wrong today because
  `docs/specs/` is still empty — but the first spec written will not
  be checked for missing sections, and a `false` nobody reads is
  indistinguishable from coverage. One-time fix: add the block
  naming spec-format's own required headings.
  Dependencies: none.
  **Layman:** One of the automatic spec checks is switched off and reports nothing, which looks the same as passing.
  Kind: doc-fix.
  Source: debt-sweep-2026-08-06.
  Priority: 3.
  Lanes: docs.

- 📋 [LWSM-1062] **DS01: reconcile the four forked standards against the app-workflow template.**
  Measured 2026-08-06 by lineage test (shared H2 headings, so these
  are forks and not independent authorship). `testing.md` is +98
  lines project-only, a clean one-way fork. `coding.md` is +105 / -4,
  `README.md` +7 / -4, `roadmap-format.md` 3 / 3 — all two-way, so
  both sides hold content the other lacks. **The hunk worth a
  decision:** the template's `coding.md` carries a rule this
  project's copy dropped — prefer the latest stable release of an
  external library, and call it with that version's current idioms.
  That is a live policy gap, not cosmetic drift, and
  `docs/standards/dependencies.md` may or may not already cover it.
  Reconciling a fork is a per-hunk judgement and neither side is
  authoritative by position, so `/debt-sweep` reports it and never
  edits it.
  Dependencies: none.
  **Layman:** Four of the shared standards have drifted from the template they came from, and one may have lost a rule about keeping libraries current.
  Kind: doc-fix.
  Source: debt-sweep-2026-08-06.
  Priority: 2.
  Lanes: docs.
  Progress (2026-08-07, FP05 rule-14 gate): the cold-eyes run over coding.md + testing.md found the fork's most consequential residue and fixed the load-bearing part. Both lanes independently flagged that `testing.md § 2.2` was a CMake/ctest recipe in a Python project — which matters because § T9 explicitly stands on § 2.2, so a developer following the new clause landed on an unrunnable command. § 2.2 is now the project's own pytest form and was EXECUTED before it shipped (which caught two wrong revert forms — see the section). coding.md § 4's naming examples were camelCase with `m_` prefixes and are now Python. STILL OUTSTANDING and owned here: 16 further C++/CMake hits in testing.md — § 3.2's CMakeLists/`test_<name>.cpp` block, § 3.4 and § 6's `LABELS perf` / `LABELS fast` vocabulary (pytest has markers, and this project's convention is that markers go on tests not files), and § 5's QVERIFY2 example. Left deliberately: porting them is a per-hunk judgement across a standard, which is this bullet's job, not a gate's.

- 📋 [LWSM-1063] **DS01: `design.md` cites a path inside a sibling repo that no reader can resolve.**
  `docs/design.md:253` points at `project-g/run.sh:87` to evidence
  the `${PORT:-N}` detection rule. `project-g` is an anonymised
  sibling project outside this repository, so the citation resolves
  for nobody — `doc_citations` returns `missing_file`. This is the
  same class as ADR-0007's four `OneUp/updater.py` citations already
  queued in LWSM-1060, and should get the same treatment: keep the
  fact, drop the unresolvable line reference, or restate it as an
  illustrative snippet inline. Filed separately because the sweep
  initially judged it acceptable and the two were being treated
  inconsistently.
  Dependencies: none.
  **Layman:** The design doc points at a line in another project's file, which nobody reading this repo can open.
  Kind: doc-fix.
  Source: debt-sweep-2026-08-06.
  Priority: 4.
  Lanes: docs.

---

## FP02 — Audit + review fold-in (2026-08-06)

A static-analysis pass and a two-lane cold code review over the whole 540-line
tree. Every finding was reproduced against the shipping code before it was acted
on, and every one of the tool findings turned out to be a false positive: all
187 `contract_doc_drift` hits, plus bandit, vulture, deptry, typos and yamllint.
The reading review found the real defects, which is the same result P01
recorded. Both reviewers independently confirmed the delegation property, the
pins and the workflow's security posture. Items below are what remained after
triage; the fixed ones landed in commits 3520359, 86313a7 and b7604b5.

- ✅ [LWSM-1064] **Bump uv to 0.12.2 on both machines in one commit.**
  CI was resolving whatever uv was newest at run time while this project
  is developed against 0.11.7 — a floating reference dependencies.md § 6
  forbids. FP02 pinned CI to 0.11.7 so the two sides match TODAY, which
  fixes the floating reference but leaves the project a minor version
  behind (0.12.2 was current 2026-08-06). The resolver writes uv.lock, so
  the bump must move the local toolchain, the ci.yml pin and any
  re-locked uv.lock together, and re-check the `--locked` vs `--frozen`
  evidence comment in local-ci.sh, which is measured against 0.11.7.
  Acceptance: `uv --version` matches the ci.yml pin, the gate is green,
  and that comment names the version it was re-measured on.
  **Layman:** Update the tool that installs our dependencies, on this computer and on GitHub at the same time.
  Kind: chore.
  Source: code-quality-review-2026-08-06.
  Progress (2026-08-06, FP03): this is no longer only a floating-reference
  tidy-up. `pip-audit` during the P02 close found the pinned 0.11.7 is affected
  by **GHSA-4gg8-gxpx-9rph** (moderate; a malicious wheel's entry point can be
  written outside the environment, onto `PATH`), fixed in 0.11.15. LWSM-1083
  carries the security framing and the floor; this item still owns the
  both-sides-in-one-commit mechanics. Do them together.
  Resolved (2026-08-06, dd574ec): closed by LWSM-1083, which needed the same bump for a security floor rather than a tidiness one. Both sides are 0.12.2, uv.lock re-locked byte-identical, and local-ci.sh's evidence comment re-measured on the new version.

- 📋 [LWSM-1065] **Decide whether two instances may share one app.log.**
  `RotatingFileHandler` is not multi-process safe, and ADR-0004 rules out
  PID and lock files, so nothing currently prevents two instances. A
  renames app.log to app.log.1 while B still holds the old descriptor and
  keeps appending to the renamed inode; B's own rollover then renames A's
  fresh file, and `doRollover`'s `os.remove` can discard a whole
  generation. Verified as a property of the stdlib handler, not observed
  in the wild — nothing runs two copies yet. Two candidate answers: the
  single-instance guard P09's tray/session work needs anyway, or a
  PID-qualified filename, which costs the single fixed path
  design.md § Observability promises. Needs the ADR-0004 question settled
  first: does "no lock files" ban a single-instance guard, or only
  PERSISTED runtime state? It reads as the latter.
  **Layman:** If you open the app twice, the two copies can scramble each other's log files. Decide how to stop that.
  Kind: investigate.
  Source: code-quality-review-2026-08-06.

- 📋 [LWSM-1066] **Put a type checker in the gate.**
  Nothing type-checks this project. Running pyright by hand during the
  2026-08-06 audit found one real mismatch on the tree as it stands:
  `_NoFollowRotatingFileHandler._open` returns the `IO[Any]` that `open()`
  infers from a `str` mode, where `logging.FileHandler._open` declares
  `TextIOWrapper`. No runtime effect — the object IS a TextIOWrapper —
  which is why it was left rather than papered over with a cast plus two
  imports in a five-line security-critical method. The fix is a checker
  that keeps it honest, not one annotation. Acceptance: the checker runs
  in scripts/local-ci.sh (so it is runnable before a push, per this
  project's arrangement), its strictness level is a recorded decision
  rather than a default, and `_open` is clean under it.
  **Layman:** Add a tool that catches a class of mistake nothing currently checks for.
  Kind: test.
  Source: audit-2026-08-06.

- 📋 [LWSM-1067] **Settle where the version number lives.**
  `pyproject.toml`, `src/lwsm/__init__.py`, `README.md` and `ROADMAP.md`
  all carry it, all reading 0.0.0, with no lockstep check and no
  `.claude/bump.json`. Both review lanes raised it independently. Not a
  defect today — nothing has been released and all four agree — which is
  exactly why it is cheap to fix now. `importlib.metadata.version()`
  is the obvious source for `__init__.py`, but it needs a decision about
  running from an uninstalled source tree, so it is a call to make rather
  than an edit to apply. Belongs with P10 packaging, or earlier if a
  `/bump` recipe lands first.
  **Layman:** The version is written in four places by hand; make it one place.
  Kind: chore.
  Source: code-quality-review-2026-08-06.

- ✅ [LWSM-1068] **Give contract_doc_drift a scope carve-out in the audit allowlist.**
  The rule treats every backticked token in a doc as a claim about this
  project's source symbols. Against `docs/specs/` that is useful; against
  `docs/standards/` — generic format standards — it can never come back
  clean, because their backticks are naming counter-examples the docs
  themselves forbid (`strName`, `iCount`), C++/Qt idioms a Python project
  will never contain, format vocabulary (`Kind:`, `Layman:`), plain prose
  (`yesterday`, `recently`), citations into other repositories
  (`roadmapdialog.cpp`), and forward references to modules
  coding.md § O1 itself names as unbuilt. Verified line by line and
  logged to `.ants_review_falsepos.jsonl` on 2026-08-06; this bullet is
  the allowlist entry that ledger cannot substitute for, since
  `docs/audit-allowlist.md` is what triage reads first. Entries
  allowlist-001 and -002 are the pattern to follow.
  **Layman:** Stop one checker from reporting the same 187 non-problems on every single run.
  Kind: doc.
  Source: audit-2026-08-06.
  Resolved 2026-08-06 in the same pass that raised it: `docs/audit-allowlist.md` gains allowlist-003 for the 187 `contract_doc_drift` hits across `docs/standards/`, with the per-category evidence, and allowlist-004 for bandit B101 in the test files. Both follow the allowlist-001/-002 format and both name a re-verify trigger.

## 💭 Considered — not scheduled

- 💭 [LWSM-1023] **Support more kinds of web server.** Detection
  today targets the seven shapes found on this machine — shell
  launchers, npm scripts, plain Python and Node entry points. To
  be broadly useful it would also need Docker Compose services,
  PHP built-in server / Laravel `artisan serve`, Ruby `rails s`,
  Go, `.NET`, Django `manage.py runserver`, and static-site dev
  servers (Hugo, Jekyll, Astro). Each is a detection rule plus a
  port-extraction rule, so this grows the *Detection rules*
  section rather than the architecture. Deliberately later: the
  rules should be extended against real projects that need them,
  not guessed at up front.
  Dependencies: LWSM-1006.
  **Layman:** Recognise more kinds of web project than the ones on
  your own machine, so the app is useful to other people.
  Kind: feature.
  Source: user-2026-08-03.
  Priority: 3.
  Lanes: core.

- 💭 [LWSM-1024] **macOS build.** Feasible in principle — macOS is
  POSIX, so process groups, signals and launcher shapes carry
  over, and PySide6 ships macOS wheels. **Blocked on one research
  question:** whether enumerating other processes' listening
  sockets on macOS requires elevated privileges. If it does,
  ADR-0004's whole probing approach needs a macOS answer before
  any packaging work is worth starting. Ship as a self-contained
  `.app` in a `.dmg` if it clears.
  Dependencies: LWSM-1021.
  **Layman:** A Mac version — probably workable, but one thing needs
  checking before promising it.
  Kind: research.
  Source: user-2026-08-03.
  Priority: 4.
  Lanes: build, core.

- 💭 [LWSM-1025] **Windows build.** Recorded with its reasoning so
  the question does not get re-asked from scratch. The supervisor
  rests on POSIX process groups (`os.killpg`,
  `start_new_session=True`) and `SIGTERM`; Windows has neither,
  and the equivalent — Job Objects plus `CTRL_BREAK_EVENT` — is a
  rewrite of ADR-0003, the layer everything else depends on.
  Launcher detection would additionally need a `.bat` / `.ps1`
  vocabulary, and `.sh`-based projects would not run at all
  without WSL. **Recommendation: don't**, unless real demand
  appears — the work is a second supervisor, not a packaging job.
  Dependencies: LWSM-1021.
  **Layman:** A Windows version. Honestly assessed as a big job for
  uncertain benefit — worth revisiting only if people ask.
  Kind: research.
  Source: user-2026-08-03.
  Priority: 5.
  Lanes: build, core.

- 💭 [LWSM-1044] **Startup ordering between projects — considered
  and declined.** Recorded so it is not re-proposed as a fresh
  idea. "Start the database before the site" sounds reasonable
  and opens a rabbit hole: a dependency graph, wait-for-ready
  conditions, timeouts, cycle detection, and a failure mode for
  each. The seven known projects are independent, and where a
  real dependency exists the project's **own start script** is
  the right place for it — that is what launching each project's
  own launcher (ADR-0003) buys. Revisit only if a concrete case
  appears that a start script genuinely cannot express.
  Dependencies: none.
  **Layman:** Deliberately not building "start this one before that
  one" — it adds a lot of machinery for a problem your projects
  don't have.
  Kind: feature.
  Source: in-session-2026-08-03.
  Priority: 5.
  Lanes: core.

- 💭 [LWSM-1020] **Unix-socket servers.** ADR-0004 probes TCP
  listeners only, so a project serving over a unix socket would
  be invisible. None of the seven does today; recorded as a known
  limitation rather than designed around.
  Dependencies: LWSM-1011.
  **Layman:** Support a different, rarer way of serving that none of
  your projects currently uses.
  Kind: feature.
  Source: cold-eyes-2026-08-03.
  Priority: 5.
  Lanes: core.

---

## Retired IDs

IDs are identity and are never reused, so gaps in the sequence
are expected rather than lost work. For the record:

- **LWSM-1003** — the template's placeholder for "P02: vertical
  slice, TBD feature". Superseded by LWSM-1005 when Phase C gave
  the slice a real definition.
- **LWSM-1019** — "desktop entry and packaging". Folded into
  LWSM-1021, which covers the AppImage, the `.desktop` entry and
  the icon as one deliverable.

---

## How to add an item

Prefer the MCP verb — it allocates the ID, formats the bullet
and writes it atomically:

```
roadmap_log op:append section:<slug> status:planned
            headline:"…" kind:… source:… layman:"…"
```

By hand:

1. Allocate the next ID:
   ```bash
   echo $(($(cat .roadmap-counter) + 1)) > .roadmap-counter
   printf "LWSM-%04d\n" $(cat .roadmap-counter)
   ```
2. Insert at the **position** where it should be tackled (not
   blindly at the end) — position is priority.
3. Set the status emoji (📋 Planned, 💭 Considered).
4. Write **every** field: `Layman:`, `Kind:`, `Source:`,
   `Priority:`, plus `Lanes:` where ownership is known. None of
   these are optional on this project (§ 3.12) — a missing one
   migrates as `defaulted` provenance and stays second-class.
5. Use a **dated** `Source:` (`user-YYYY-MM-DD`,
   `audit-YYYY-MM-DD`, …) — it becomes the item's `created` date
   and survives archive rotation.

`.roadmap-counter` is a per-machine cache, not source — it is
gitignored, and its true value is the highest ID across
`ROADMAP.md` + `CHANGELOG.md` + `docs/roadmap/*.md`
(§ 3.5.1).

See `docs/standards/roadmap-format.md § 3.5` for the full bullet
contract and § 3.12 for the field-completeness rule.

## How findings get folded

After every `/audit` + `/code-quality-review` (and `/debt-sweep`):

```
Phase closes
  → Run /audit + /code-quality-review
  → Triage findings
  → If clean: phase fully closed.
  → If actionable: batch into one new fix-pass FP## (next-up),
    add [Unreleased] entry, run that fix-pass through the
    9-step loop; its own closing audits may produce another.
```

See `docs/standards/roadmap-format.md § 3.8` and the
app-workflow skill (`~/.claude/skills/app-workflow/SKILL.md`, local to the author's machine)
for the full pattern.
