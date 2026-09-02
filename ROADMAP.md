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

- 📋 Planned (next up for this phase)
- 🚧 In progress (being tackled now)
- ✅ Done (shipped)
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
| --- | --- |
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

- ✅ [LWSM-1069] **FP03: an unexpected exception wedges the poll loop permanently, and silently.**
  Two halves, found by two independent lanes.
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

- ✅ [LWSM-1073] **FP03: `stop()` returns while a queued emission is still in flight.**
  `controller.py:122` waits with `QThreadPool.globalInstance().waitForDone()`,
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

- ✅ [LWSM-1072] **FP03: the registry read is unbounded, and two exceptions escape the contract.**
  `registry.py:86` calls `path.read_bytes()` with no
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

- ✅ [LWSM-1078] **FP03: the registry's rejection reasons carry attacker-controlled text unescaped into the status bar.**
  `registry.py:136,141,146`
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

- ✅ [LWSM-1070] **FP03: the only focusable widget in the app draws no focus ring.**
  `mainwindow.py:56` sets `StrongFocus` on `ProjectRow` and nothing paints
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

- ✅ [LWSM-1071] **FP03: the decorative glyph is announced by a screen reader, and a code comment says it is not.**
  `mainwindow.py:64` calls
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

- ✅ [LWSM-1074] **FP03: the row's cells are flung to opposite ends of the window.**
  `mainwindow.py:79` gives `stretch=1` to the **name** cell, so all
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

- ✅ [LWSM-1075] **FP03: `state_unknown` fails the contrast floor in the default palette.**
  `theme.py:62` sets `state_unknown="#8a6d1f"`, which against
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

- ✅ [LWSM-1076] **FP03: a state change is never announced, and every row is re-styled on every tick.**
  Two halves of one fix. Qt does **not** notify AT-SPI
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

- ✅ [LWSM-1081] **FP03: no user-visible string is translatable.**
  `grep` for
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

- ✅ [LWSM-1077] **FP03: the theme layer owes a generated style sheet, and the widget is composing CSS instead.**
  Spec § 4.4 and `design.md § Tokens, not
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

- ✅ [LWSM-1080] **FP03: three type errors in `registry.py`, and a missing return annotation on the seam INV-15 depends on.**
  `pyright` reports
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

- ✅ [LWSM-1082] **FP03: the low-severity tail from the P02 review.**
  Each
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

## FP06 — Three-lane review fold-in (from the P03 close, 2026-08-12)

The P03 close ran `/audit` and `/code-quality-review` once, per the standing
2026-08-07 process decision. Static analysis was clean for the fourth close
running — ruff, bandit (2116 lines), semgrep, gitleaks, shellcheck, all zero,
re-run by hand inside the venv because the sweep's zero carried no evidence it
had read anything. Every real finding came from reading, again.

Three lanes over `scanner.py`, its tests and the hardening surface produced 25
findings and **no false positives**. Every load-bearing claim was reproduced
independently before it was written down here.

This section is the nine above the bar. The remaining sixteen are routed to
`docs/known-issues.md` with named owners rather than worked here, per the same
2026-08-07 decision: one review per phase, fix what is above the bar, route the
rest to the phase that owns the code.

**The cross-cutting finding is the one to remember.** Two lanes, different
reproducers, landed on the same defect: `pathlib` metadata calls sitting outside
any `except OSError`. `Path.exists` / `is_symlink` / `is_file` re-raise `EACCES`
and `ENAMETOOLONG` on Python 3.13 — this is not the older behaviour where
`exists()` swallowed them — and `scan()` catches only `_BudgetExpired`. That is
the fourth distinct non-`OSError`-shaped whole-scan crash this item has
produced, after the `TypeError`, `KeyError` and `ValueError` the spec gate
found. The class is now understood as structural rather than incidental: the fix
is per-candidate containment, not a fourth patch.

**The test findings are the other half, and they are the more uncomfortable
one.** 81 mutants were applied to `scanner.py`; 47 went red, 34 did not. Three
separate clauses the spec calls load-bearing — the execute-bit precondition, the
dependency-block scope, `_BudgetExpired` not being an `OSError` — are all
correct in the code today and protected by nothing. A suite of 370 green tests
said nothing about any of them.

- ✅ [LWSM-1122] **FP06: one unreadable or hostile directory can no longer destroy the whole scan.**
  `Path.exists` / `is_symlink` / `is_file` re-raise `EACCES` and `ENAMETOOLONG` on
  Python 3.13.14 — `pathlib` only swallows `ENOENT/ENOTDIR/EBADF/ELOOP`
  (`_IGNORED_ERRNOS`). Four call sites sit outside any handler, and `scan()`
  catches only `_BudgetExpired`, so the exception escapes and the caller gets no
  `ScanResult` at all.
  Four sites: `scanner.py:923` (`_read_alternate`, reached for every candidate),
  `:1006` (`_match_node_package`), `:512` (`_python_framework`), `:561`
  (`_accept_hop`).
  Two triggers, both reproduced twice — once by the reviewing lane and once
  independently before this bullet was written:
  - `chmod 000` on any candidate directory. Needs no attacker: a root-owned or
  another user's directory under a scan root does it. Measured: 20 healthy
  projects returned **0**. Mode `0o444` (listable, not searchable) is the same.
  - A 3000-character hop token in a hostile `start.sh` → `OSError [Errno 36]
  File name too long` at `:561`. This one is attacker-authored: one line in a
  file under a scan root. `MAX_SOURCE_LINE_CHARS` is 4096 and `NAME_MAX` is
  255, so the form is trivially writable.
  Spec § 4.3 states the opposite outright: *"Any `OSError` rejects that file with
  a reason and continues. A permission denial on one project is not a failure of
  the scan."*
  **Fix at the class, not the four sites.** Per-candidate `OSError` containment in
  `scan()` — verified by the lane to restore 20/20 projects with one reason
  recorded (`'aaa-hostile': cannot be examined (Permission denied)`), and
  `_BudgetExpired` is not an `OSError`, so INV-5 is untouched. Patching only the
  two sites with reproducers would leave the same line of code twice more.
  Acceptance: a regression test carrying **both** triggers — they reach different
  lines — asserting the healthy projects are all returned and the bad one is
  skipped with a reason.
  **Layman:** A single folder the app is not allowed to open currently makes it find nothing at all. It should skip that one folder and carry on.
  Kind: fix.
  Lanes: core.
  Source: code-quality-review-2026-08-12 lane-1 #1 + lane-2 F1/F2/F3 (corroborated by two independent lanes).
  Resolved (2026-08-12, 1910a6c): per-candidate `except OSError` around `_detect` in `scan()`, at the class rather than the four sites. Both triggers were watched failing first — `chmod 000` gave EACCES from `Path.exists`, the 3000-character token gave ENAMETOOLONG from `is_symlink` at a different line — and both now leave the three healthy siblings detected with one reason recorded. The containment is also what LWSM-1125's behavioural test proves does NOT swallow the budget signal.

- ✅ [LWSM-1123] **FP06: hop-target selection falls back to earlier tokens instead of abandoning the hop.**
  Spec § 4.5 step 4: *"Take the **last** remaining token that satisfies § 4.5's
  six constraints."* The code treats any constraint failure as terminal —
  `_accept_hop` returns a reason and `_hop_target` (`scanner.py:592-594`) returns
  `(None, [], reason)` immediately, never trying the preceding token.
  Measured, with the port in the hop file in every case:
  | `start.sh` last line | spec | code |
  |---|---|---|
  | `exec python3 app.py` (control) | 8123 | 8123 ✅ |
  | `exec python3 app.py >> /var/log/app.log` | 8123 | **None** |
  | `exec python3 app.py --cfg ../shared/conf.ini` | 8123 | **None** |
  | `exec python3 app.py --cfg node_modules/x/c.json` | 8123 | **None** |
  The control passing is what isolates the abort as the only difference.
  The recorded reasons are actively misleading as well —
  `hop target '/var/log/app.log' is outside the project` describes a hop the
  launcher never asked for.
  Direction of failure is **safe** (unknown, never a fabricated port), which is
  why this is HIGH and not CRITICAL. But an absolute-path redirect on the `exec`
  line is ordinary in real launchers, so it will show up as silent
  under-detection.
  INV-20's depth fixture (`exec python3 a/b/c/d.py`) is a single token and cannot
  see this, which is how it survived seven review loops.
  Acceptance: the three lines above each detect their port; the reason recorded
  for a rejected token names that token, and a line with no acceptable token at
  all still comes back *unknown* with a reason.
  **Layman:** If a start script mentions a log file at the end of its command, the app currently gives up on finding the port instead of looking at the rest of the line.
  Kind: fix.
  Lanes: core.
  Source: code-quality-review-2026-08-12 lane-1 #2.
  Resolved (2026-08-12, f4079e2): `_hop_target` keeps the first refusal and tries the preceding token. All three shapes in the bullet's table now detect 8123, the control still passes, and a line with no acceptable token still reports the refusal rather than silence. `_accept_hop`'s docstring said the search stops on a refusal and was corrected in the same commit.

- ✅ [LWSM-1124] **FP06: the last unescaped reason string is routed through `_quoted`, closing INV-18's first clause.**
  `scanner.py:605`:
  ```
  return None, [], f"{token} cannot be read ({exc.strerror or exc})"
  ```
  Its seven neighbours in `_accept_hop` (`:541, :545, :553, :556, :558, :560,
  :565`) all wrap the token in `_quoted`, which escapes and then clips at
  `MAX_REASON_CHARS = 120`. This one interpolates raw foreign bytes.
  INV-18: *"Every reason and every `PortFinding.source` is escaped before it is
  clipped."* This reason is neither.
  Reached whenever a hop token passes all six constraints and `_read_lines`
  raises an `OSError` other than `FileNotFoundError` / `NotADirectoryError` — a
  directory, a FIFO, an oversized file, `EACCES`.
  Measured independently twice, at **248** and **635** characters against the
  stated 120 bound, both carrying a live `\x1b` and one a `\x07`, reaching the
  app log and the status bar. `line.split()` does rule out a raw newline, so this
  is control-character injection and cap breach rather than full log-record
  forgery (LWSM-1078's shape) — but the length bound is simply absent.
  Fix is one call: `_quoted(token)`, matching its neighbours.
  Acceptance: a hop token carrying `\x1b` and `\x7f` in a 200-character name
  produces a reason at or under `MAX_REASON_CHARS` containing no raw control
  byte. Mutating `_quoted` back out must redden it.
  **Layman:** A folder with a strange name could push invisible control characters into the app's log; this escapes them first, like every other message already does.
  Kind: security.
  Lanes: core.
  Source: code-quality-review-2026-08-12 lane-1 #3 + lane-2 F4 (corroborated by two independent lanes).
  Resolved (2026-08-12, 1127100 + 80ee5e2): one call to `_quoted`, matching its seven neighbours. The test drives the line through a directory hop target — it passes all six § 4.5 constraints and then fails § 4.3's `fstat`, which is the only arm that reaches it — and was watched failing with a live \x1b in the reason. What it does NOT prove is recorded in its docstring: the assertion is relative to `MAX_REASON_CHARS`, so raising that constant to 400 leaves it green (measured), and scanner's copy of the bound is pinned by nothing where registry's is pinned by `test_the_shipped_bounds_are_pinned`.

- ✅ [LWSM-1125] **FP06: `_BudgetExpired` not being an `OSError` becomes a tested invariant rather than a docstring.**
  Mutation: `class _BudgetExpired(Exception)` → `class _BudgetExpired(OSError)` at
  `scanner.py:195`. **182/182 tests stay green.**
  Under the mutant, `_read_alternate`'s `except OSError` (`:927`) swallows the
  budget signal, and the lane measured the result directly:
  ```
  timed_out: False   projects: []
  skipped: ("'proj': start.sh cannot be read ()", "'proj': no launcher matched")
  ```
  A scan that ran out of budget reports itself **complete**. The caller is told
  the project list is the whole truth when it is partial — and LWSM-1007 is about
  to persist exactly that list, so a truncated scan would overwrite a good
  registry.
  The code is **correct today** — verified: `_BudgetExpired.__mro__` is
  `(_BudgetExpired, Exception, BaseException, object)` and
  `issubclass(_BudgetExpired, OSError)` is `False`. The defect is that nothing
  protects it, and the docstring saying it is "deliberately not an `OSError`" is
  the only thing standing there.
  This is the project's own named trap in a second location: `TimeoutError`
  subclasses `OSError`, which is how a `SIGALRM` guard once satisfied the
  `pytest.raises(OSError)` it existed to protect.
  Acceptance: `assert not issubclass(scanner._BudgetExpired, OSError)` as a
  source invariant, **plus** a behavioural test — expiry mid-read asserting
  `timed_out is True` and the candidate absent — so the guarantee is held at both
  the structural and the observable end. The class mutation must redden it.
  **Layman:** If a scan runs out of time it must say so. Right now it would silently claim it had finished, and no test would notice.
  Kind: test.
  Lanes: tests.
  Source: code-quality-review-2026-08-12 lane-3 H1.
  Resolved (2026-08-12, e764f47): both halves. `test_the_budget_signal_is_not_an_oserror` is the source invariant; `test_a_budget_expiring_inside_a_read_still_reports_a_timeout` is the observable one, using a single candidate so the per-candidate check has already passed and expiry can only happen inside `_read_lines`. `class _BudgetExpired(OSError)` reddens both.

- ✅ [LWSM-1126] **FP06: the `package.json` dependency-block scope gets the regression test it never had.**
  Mutation: `_scan_source("package.json", [script[:MAX_SOURCE_LINE_CHARS]])` at
  `scanner.py:1074` → the same call with `*sorted(dependencies)` appended.
  **182/182 tests stay green.**
  This was the spec review's single highest-value finding (loop 4), and the
  mechanism that closed it is unlocked. Current behaviour on
  `{"scripts":{"dev":"vite"},"dependencies":{"get-port":"^7.0.0"}}` is
  `5173 (Vite)`; under the mutant it becomes **7**.
  The existing test — `test_a_dependency_pair_is_kept_away_from_the_rules_by_scope_not_by_them`
  (`tests/test_scanner.py:340`) — asserts `rule_2('"get-port": "^7.0.0"') == 7`
  and then explains in prose that § 4.4's scoping is what keeps that string away
  from the rules. **It asserts the hazard and never the guard.** No fixture
  anywhere holds a real dependency name that could yield a port.
  Acceptance: a fixture with a Vite-positive `scripts` block **and** a
  port-shaped dependency key, asserting `5173/Vite`. Widening the scanned lines
  to include the dependency block must redden it.
  This also closes a gap the corpus has: no fixture currently exercises a
  Vite-positive `package.json` at all.
  **Layman:** A package named something like `get-port` must not be mistaken for a port setting. That protection works, but nothing would catch it being removed.
  Kind: test.
  Lanes: tests.
  Source: code-quality-review-2026-08-12 lane-3 H2.
  Resolved (2026-08-12, e764f47) — and the bullet's prescribed mutation is WRONG, corrected by measurement. `dependencies` is a set of KEYS, so appending `*sorted(dependencies)` scans `get-port`, which holds no digits: the suite stays 193-green and the mutant is inert. The scope breach that is real is reading package.json as an ordinary source file, which is what the new `project-m-vite` fixture reddens for (port 7 instead of 5173). Its dependency pair is pretty-printed onto a line of its own on purpose — minified, rule 2 stops at the document's first `:` and the fixture cannot see the breach at all.

- ✅ [LWSM-1127] **FP06: launcher rule 1's execute-bit precondition gets its first test.**
  Mutation: the whole `os.access(path, os.X_OK)` block at `scanner.py:940-944`
  deleted. **182/182 tests stay green**, and line coverage confirms `:943` is
  **never executed** by any test in the suite.
  Spec § 4.4 (line 495) states it normatively: *"**Rule 1 requires the execute
  bit** (`os.access(path, os.X_OK)`)."*
  Every fixture that plants a `start.sh` also chmods it, so the fall-through case
  has no coverage at all. The lane verified a discriminating fixture:
  ```
  proj/start.sh      (NOT executable)   PORT=1111
  proj/package.json  {"scripts":{"dev":"vite --port 2222"}}
  current →  NODE ('npm','run','dev')  port 2222
  mutant  →  SHELL ('./start.sh')      port 1111
  ```
  Acceptance: that fixture, asserting `NODE` and 2222, plus the reason recorded
  for the skipped `start.sh`. Deleting the `os.access` guard must redden it.
  Worth folding into the corpus rather than writing standalone — a
  non-executable launcher beside a usable one is a real shape, and
  `scanner_fixtures.py` has no fixture for it.
  **Layman:** A start script that is not marked runnable should be skipped in favour of the next option. That works, but no test checks it.
  Kind: test.
  Lanes: tests.
  Source: code-quality-review-2026-08-12 lane-3 H4.
  Resolved (2026-08-12, e764f47): folded into the corpus as `project-n-unexecutable-launcher`, both files declaring a different port so which rule fired is visible in the result. The skip reason is asserted by a separate test. Deleting the `os.access` block reddens both.

- ✅ [LWSM-1128] **FP06: a directory name that is not valid UTF-8 no longer produces an un-encodable project name.**
  `_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")` at `scanner.py:206` covers C0
  and C1 but not surrogates. A directory name that is not valid UTF-8 comes back
  from `os.scandir` through `surrogateescape` as lone surrogates in
  `\udc80–\udcff`, which `_display` (`:218`) passes straight through into
  `DetectedProject.name` and on to the output at `:1259`.
  Measured:
  ```
  name = 'bad\udcff\udcfename'
  *** UnicodeEncodeError encoding to utf-8: surrogates not allowed
  --- Logging error ---
  ```
  **The observable is worse than a crash.** `logging` catches its own encode
  failure, so the record is silently dropped with a traceback on stderr — the
  app keeps running and the evidence is gone. Anything that does not catch it
  raises: a `json.dumps(...).encode()`, which is precisely what **LWSM-1007** is
  about to do to persist this list, or a Qt call.
  `_quoted` is immune because `repr` escapes surrogates, which is why every
  reason string is fine and only the one surviving-detection path is affected.
  This is the same call site loop 6 already fixed once ("`DetectedProject.name`
  travelled raw and unbounded") — the fix reached for `_display`, and
  `_display`'s character class is one range short.
  Fix: extend to `[\x00-\x1f\x7f-\x9f\ud800-\udfff]`.
  Acceptance: a candidate directory created with invalid UTF-8 bytes in its name
  is listed with a name that round-trips through `.encode("utf-8")` and through
  `json.dumps`. Reverting the character class must redden it.
  **Layman:** A folder whose name contains broken text currently makes the app's log entry vanish without a word. The next feature would crash on it outright.
  Kind: fix.
  Lanes: core.
  Source: code-quality-review-2026-08-12 lane-2 F5.
  Resolved (2026-08-12, 6b592df): `_CONTROL` extended to `\ud800-\udfff`. The test builds the candidate with raw bytes (`b"bad\xff\xfename"`) and asserts the name round-trips through `.encode("utf-8")` and `json.dumps`. Reverting the range reddens it.

- ✅ [LWSM-1129] **FP06: INV-18's `PortFinding.source` clause is tested, not just its reason clause.**
  Mutation: `source=_display(name)` → `source=name` at `scanner.py:467`.
  **182/182 tests stay green.**
  INV-18 has two halves: *"Every reason **and every `PortFinding.source`** is
  escaped before it is clipped"* (spec line 1414). The existing test —
  `test_a_newline_in_a_directory_name_cannot_forge_a_log_record`
  (`tests/test_scanner.py:1471`) — checks `result.skipped` and
  `DetectedProject.name`, and never touches `PortFinding.source`.
  Demonstrated live with a hop target whose filename holds control bytes:
  ```
  hop file  ev\x7fil\x1b[31m.py
  current → source = 'ev?il?[31m.py'      (escaped, correct)
  mutant  → source = 'ev\x7fil\x1b[31m.py'  (raw, undetected)
  ```
  The source string reaches the app log and the status bar, so this is the
  LWSM-1078 shape at the one call site the sweep missed — the third time a
  sanitiser sweep in this project has stopped one site short.
  Acceptance: the fixture above, asserting `PortFinding.source` carries no raw
  control byte. Removing `_display` from `:467` must redden it.
  Cheap to combine with LWSM-1124's test, but assert them separately — they are
  two clauses and a single test covering both would go green again the moment
  one regressed and the other did not.
  **Layman:** The app already cleans up strange characters in the filename it reports a port came from — but nothing was checking that half.
  Kind: test.
  Lanes: tests.
  Source: code-quality-review-2026-08-12 lane-3 H3.
  Resolved (2026-08-12, 6b592df): a hop file named `ev\x7fil\x1b[31m.py` carrying a port, asserting `PortFinding.source` holds no raw control byte. Kept separate from LWSM-1124's reason test as the bullet asked. `source=_display(name)` → `source=name` reddens exactly this one.

- ✅ [LWSM-1130] **FP06: rule 3's Vite evidence test reads a comment-stripped script, as § 4.6 requires.**
  Spec § 4.6: *"The stripper is shared by both port rules **and by rule 3's
  evidence scan**, so a framework identified from a commented-out import cannot
  happen either."*
  `_imports` strips (`scanner.py:495`) and `_scan_source` strips by default
  (`:1074`), but `_VITE_SCRIPT.search(script)` at `:1077` searches the **raw**
  chosen script value.
  Measured, side by side:
  | fixture | result |
  |---|---|
  | `serve.py` containing `# import flask` | `port=None` ✅ |
  | `{"scripts":{"dev":"node server.js # switch to vite later"}}` | **5173, FRAMEWORK_DEFAULT, source `Vite`** ✗ |
  Reproduced independently. `#` genuinely is a comment in an npm script — the
  value is handed to `sh` — so the spec's rule is the right one and the code is
  the side that is wrong.
  Same line also searches the **unclipped** script value while the port rules see
  it clipped to `MAX_SOURCE_LINE_CHARS`; fix both together.
  Acceptance: the fixture above comes back *unknown*; a genuine
  `{"dev": "vite"}` still comes back 5173; and the existing whole-word guard
  (`\bvite\b`, which keeps `vitest` out) still holds. That last one matters —
  the whole-word form was forced by an executed acceptance test on 2026-08-08 and
  must not be lost while editing this line.
  **Layman:** A note in a project's config saying "switch to vite later" is currently read as if the project already used Vite, and it gets given the wrong port.
  Kind: fix.
  Lanes: core.
  Source: code-quality-review-2026-08-12 lane-1 #5.
  Resolved (2026-08-12, 6b592df): the evidence test now searches `strip_comment(script[:MAX_SOURCE_LINE_CHARS])`, so it sees what the port rules see. `\bvite\b` is untouched — the whole-word form was forced by an executed acceptance test on 2026-08-08 — and `project-k-vitest` still comes back unknown. New corpus fixture `project-o-vite-in-a-comment` covers the note-about-a-migration shape.

## FP07 — Three-lane review fold-in (from the P03b close, 2026-08-15)

The P03b close ran `check-code` and `/code-quality-review` once, per the
standing 2026-08-07 process decision. Static analysis was clean for the fifth
close running — ruff, bandit, semgrep, gitleaks, shellcheck, actionlint and
zizmor all zero. Every real finding came from reading, for the fifth time.

Three lanes over `supervisor.py`, `registry.py` and the UI pair produced **55
findings — 3 CRITICAL, 7 HIGH, 19 MEDIUM and the rest LOW/INFO**. This section
is the ten above the bar. The MEDIUM and LOW tail is routed to
`docs/known-issues.md` with named owners, per the same 2026-08-07 decision.

**Two findings mean the app does not do what this roadmap and
`.claude/workflow.md` recorded it doing on 2026-08-14.** Success criterion 2 was
written up as closed end to end. It is closed for **shell-launcher projects
only**: `npm run dev`, `python3 serve.py` and `node serve.mjs` are all refused
before they spawn, and any project whose port the scanner could not pin sticks
in `starting` forever with every button disabled. Both were reproduced against
the shipped module before this section was written.

**The cross-cutting finding is one all three lanes hit independently: a
documented mechanism with no caller.** `rotate_if_needed` (the 5 MB per-project
log cap), `DETECTED_FIELDS` / `USER_FIELDS` (the merge's classification spine),
and `wait_for_abandoned_probes` are each declared, documented as delivered, and
consulted by nothing in `src/`. No lane saw the other lanes' reports. This is
the same class as FP06's non-`OSError` family — an instance found three times
before the class was named — and it is named here rather than patched three
times.

**The second cross-cutting theme is LWSM-1069's shape, three more times.** An
exception escaping a Qt slot leaves a control permanently disabled with no
message: the raw `OSError` from `mkstemp`, the `AttributeError` from an unset
`load`, and the unbounded overlay all end there. LWSM-1069 fixed this on the
poll loop and nowhere else.

**Why 494 green tests said nothing about any of it.** Every `start()` test in
`test_supervisor.py` uses `("./start.sh",)` — a launcher-kind monoculture, so
the one branch that works is the only one exercised. No fixture has a port-less
project. No fixture fills a disk. Same family as the one-row-fixture trap
recorded on 2026-08-14: a fixture set that cannot express the variation the code
branches on.

## FP08 — Four-lane review fold-in (from the P04 close, 2026-08-21)

Four cold lanes over the code shipped since the P03b close: placement and window
geometry, settings and config I/O, the window's UI surface, and the supervisor's
concurrency. Every finding below was verified against the code before filing —
three by reproduction — and the ones that did not survive checking were dropped
rather than filed.

The static-analysis half came back clean: ruff, gitleaks (244 commits), semgrep
on `src/`, and bandit at 0 medium and 0 high. Its only findings were the
B404/B603 subprocess pair, now recorded as allowlist-009.

Two things about this batch are worth keeping. **Six of the findings are in code
written the same day**, which is the argument for a cold read that no amount of
care by the author replaces. And **the two most severe are both in places a
docstring said were safe** — `settings.py` claimed three times that a refusal
here cannot lose data, and `supervisor.py`'s trust gate claimed a symlink out of
the project is refused outright. Neither was true, and in both cases the sibling
module states the correct rule in almost the same words.

- ✅ [LWSM-1162] **FP08: a launcher symlinked out of its project is not refused, and its fingerprint carries no content.**
  ADR-0003 § Trust says a launcher that is a symlink pointing outside its
  project "is refused outright". It is not. `_launcher_path` calls
  `_contained`, which resolves the symlink and returns `None` for exactly the
  escaping case — so `validate_launcher` is never called and its
  "a symlink leaving the project" refusal is unreachable from `start()`.

  **Reproduced 2026-08-21.** An escaping symlink produces a fingerprint
  IDENTICAL to a launcher that does not exist at all (both fall through to
  `digest.update(b"\0nofile\0")`, hashing argv only), and rewriting the
  symlink target's CONTENT does not change the fingerprint. So the trust gate
  never re-arms: the user confirms `./start.sh` once and the target can be
  replaced with anything afterwards.

  Compounding it, `_ask_to_trust` renders `str(resolved or argv[0])`, so the
  confirmation dialog shows `./start.sh` while `execvp` runs the symlink
  target — which is the "security theatre" ADR-0003 names.

  Fix: refuse the escaping symlink at `start()` as the ADR requires, and make
  the dialog show what will actually run.
  Resolved (2026-08-23): `_contained` no longer swallows the escaping
  case. Containment is `validate_launcher`'s decision, taken on the
  resolved target `execve` actually runs, and `start()` calls it on
  whatever `_launcher_path` returns — so the ADR's refusal is reachable,
  an escaping symlink cannot reach the trust dialog, and the fingerprint
  hashes the target's bytes instead of colliding with a launcher that
  does not exist. The dialog's `str(resolved or argv[0])` needed no
  change once the escape is refused: `resolved` is now `None` only for
  `npm`, whose `argv[0]` is what runs.
  Tests: a parametrised `start()`-driven refusal over two launcher kinds
  (the escape is per-argument — `argv[0]` for `./start.sh`, `argv[1]` for
  `python3 serve.py`), plus a fingerprint-collision test. The existing
  `test_an_interpreter_script_outside_the_project_is_not_a_launcher` had
  encoded the defect as the contract and was corrected — classifying an
  escaping path as "no launcher" is exactly what made the refusal
  unreachable.
  Three mutants killed: restoring the filter, skipping `validate_launcher`
  from `start()`, and disabling its containment refusal. 1148 green,
  local-ci green.
  **Layman:** A project can point its start script at a file somewhere else on the disk; the app shows you the harmless-looking name, runs the other file, and never asks again even if that file is rewritten.
  Kind: security.
  Source: close-phase-2026-08-21 lane-4 (supervisor).
  Lanes: security, supervisor.

- ✅ [LWSM-1163] **FP08: one JSON typo plus one window close destroys every stored setting.**
  `settings.load()` is total by design — a syntax error, a non-object root, a
  wrong `schema_version` or a transient read error all return `Settings()`
  plus a reason. `save_field` reads that back and writes it out with no gate,
  so a whole-document refusal is written back as defaults.

  **Reproduced 2026-08-21**: a trailing comma in `settings.json` holding
  theme=parchment, text_scale=150, poll=2500, log=42 became midnight/100/
  1000/5 after one `save_field` — and the malformed text the user could have
  fixed is gone with it.

  Three passages say this cannot happen (`settings.LoadResult`'s docstring,
  `save_field`'s, and `settings.save`'s). All three are wrong, and
  `registry.py` states the counter-argument in almost the same words it
  needed here: "a raised `RegistryError` produces no reasons at all, so such
  a gate would write a fresh file over a hand-edited registry that had only a
  JSON typo or a stale `schema_version` — destroying a fully recoverable
  file". `settings.load` cannot raise, so EVERY whole-file refusal is that
  state.

  `save_geometry` fires on every close, which makes this the normal case
  rather than a corner. Fix: `load()` reports whether the DOCUMENT was
  refused, and `save_field` refuses to write when it was — the analogue of
  `rows_refused`.
  Resolved (2026-08-23): exactly the fix the bullet prescribes.
  `LoadResult` gained `document_refused`, set on all four whole-document
  paths (unreadable, invalid JSON, non-object root, wrong
  `schema_version`) and left false on the two that read the document — a
  clean file and a missing one, since a first run has nothing to lose and
  must stay writable. `save_field` raises `SettingsError` when it is set.
  The gate is the CALLER's and could not be `save()`'s: `save()` is handed
  a `Settings` and cannot tell one built from a file that was read from
  one built from a file that was refused. `save_field` is the only call
  site, and the only scope where the `LoadResult` and the write are both
  visible.
  All three passages that denied this could happen are corrected rather
  than left standing — `LoadResult`'s docstring, `save_field`'s and
  `save()`'s. The first had reasoned that a file of fields has no rows to
  drop, which is true and beside the point: what a document refusal drops
  is the whole file.
  Tests: `load()` reports the flag on three refusal shapes and withholds
  it on three readable ones, the three existing OSError-path tests (FIFO,
  directory, oversized) each gained the assertion, and a `build_window`
  test drives a real theme change against a trailing-comma file and
  asserts the bytes are untouched — driving the writer rather than
  `save_field`, for LWSM-1136's reason.
  Six mutants killed: each of the four refusal paths dropping the flag,
  the flag defaulting to true, and `save_field` dropping the gate. 1155
  green, local-ci green.
  **Layman:** If you hand-edit the settings file and make a small mistake, closing the window quietly wipes your theme, text size and everything else you had chosen.
  Kind: fix.
  Source: close-phase-2026-08-21 lane-2 (settings).
  Lanes: settings, data-loss.

- ✅ [LWSM-1164] **FP08: `settings.load()` raises RecursionError, so a hostile file kills the app at startup.**
  `load()`'s docstring says "Never raises.", the module docstring says "A bad
  settings file must never cost the user a window", and `build_window`'s
  comment says reading it needs no handler. All three are false for one input
  class this project has already met next door.

  **Reproduced 2026-08-21**: `"[" * 20000 + "]" * 20000` (40 KB, well inside
  `MAX_FILE_BYTES`) makes `load()` raise `RecursionError`, which is not a
  `ValueError` and so escapes the `except (UnicodeDecodeError, ValueError)`.
  `registry.py:369` already catches `(ValueError, RecursionError)` with a
  comment explaining exactly why, and `tests/test_scanner.py` pins the shape.

  It propagates out of `build_window` (whose `try` catches only
  `RegistryError`) and out of `main()` — LWSM-1116's shape exactly: a guard
  that exists next door and is missing here. The same escape reaches
  `save_field` from inside `closeEvent`, where only `(ConfigFileError,
  OSError)` is caught.
  Resolved (2026-08-23): `RecursionError` added to `load()`'s parse
  handler, which is the whole fix — `registry.py` has caught it since
  LWSM-1108 and its comment already carries the reasoning, including the
  warning not to widen some other handler to `BaseException` instead.
  `load()` no longer raising also closes the `closeEvent` half the bullet
  names: `save_field`'s only raising call was the load, and `save()`
  serialises a flat dict of our own, which cannot recurse.
  The reproduction is pinned as a test at 40 KB — well inside
  `MAX_FILE_BYTES`, so the size cap never sees it — and asserts
  `document_refused` alongside, so LWSM-1163's gate covers this shape too
  rather than the two fixes leaving a seam. One mutant killed: dropping
  `RecursionError` from the tuple. 1156 green, local-ci green.
  Also corrected `load()`'s docstring, which promised "never raises" while
  the handler did not deliver it. The module docstring and
  `build_window`'s comment are now true as written and were left alone.
  **Layman:** A specially-crafted settings file stops the app opening at all — every launch, until someone deletes the file by hand.
  Kind: fix.
  Source: close-phase-2026-08-21 lane-2 (settings).
  Lanes: settings.

- ✅ [LWSM-1165] **FP08: a child that exits on its own is never removed from the registry.**
  **Verified 2026-08-21**: only two lines touch `_registry.processes` — the
  insert in `start()` and the pop in `stop()` (plus `close()`). Nothing
  removes an entry for a child that exited by itself, and `exited()`'s own
  docstring states the premise and stops there.

  So after a launcher dies on its own — a missing dependency, a bad
  `scripts.dev`, an ordinary crash — the port is free, `_classify` returns
  STOPPED, the UI disables Stop and enables Start, and every Start from then
  on raises `AlreadyRunning`. Stop and Restart are both disabled, so there is
  no route back. The log descriptor is never closed either.

  LWSM-1134 fixed the overlay symptom and left the entry.
  Resolved (2026-08-23): `Supervisor.reap_exited` decides what is safe to
  release, and the controller's poll calls it once a tick — both halves,
  because LWSM-1136 is what happens when only the first ships.
  **It is not the one-line fix the bullet's phrasing suggests, and the
  reason is the case it would break.** A `start.sh` that spawns a server
  and exits leaves the launcher gone and the server alive in the same
  process group — the double-forking wrapper `_group_members` and
  LWSM-1009's acceptance test exist for. Dropping the entry on the
  launcher's death alone orphans that server behind a greyed-out Stop
  button, which is worse than the defect. So `_alive(handle)` only selects
  a candidate and the GROUP decides; the cheap check is first because
  `_group_members` walks every process on the machine and this runs once a
  second.
  Pops under the lock and by identity, so a project a concurrent `stop()`
  already took is left alone (LWSM-1138) — the descriptor must be released
  exactly once.
  Five mutants killed: the group check, the identity check, the candidate
  check, and the poll's call to it. **One survived and is recorded rather
  than papered over**: removing the `with self._registry.lock` while
  keeping the identity check. A missing lock is observable only under an
  interleaving of two bytecode operations that no deterministic test can
  force, so it is equivalent-under-test rather than a coverage gap — the
  same category LWSM-1016 recorded. The lock stays; without it the
  identity check is itself a check-then-act.
  The first draft of the race test was VACUOUS and the probe caught it: a
  sequential stop-then-reap never reaches the identity check, because the
  entry is gone before `running()` is sampled. Replaced with one that
  parks the stop inside the window by patching `_group_members`, asserts
  the stop actually fired, and asserts on the DESCRIPTOR rather than the
  return value. The sequential test is kept with a docstring saying what
  it is worth.
  Also corrected `exited()`'s docstring, which said the removal happens in
  `_reap`; the pop has been in `stop()` since LWSM-1138. 1162 green,
  local-ci green.
  **Layman:** If a project's server crashes on startup, the app refuses to start it again for the rest of the session and the Stop button is greyed out — there is no way back except restarting the app.
  Kind: fix.
  Source: close-phase-2026-08-21 lane-4 (supervisor).
  Lanes: supervisor.

- ✅ [LWSM-1166] **FP08: a refused registry write is reported once and then never retried.**
  `_should_write` compares the merge against `self._controller.records()` —
  the in-memory set — while `_apply_merge` calls `set_records(merged.records)`
  UNCONDITIONALLY and refreshes `self._load` only on the success branch. So
  the two diverge the moment a write is refused.

  **Verified 2026-08-21** at `mainwindow.py:2004` and `:2026`. With one bad
  row in `projects.json` the save raises every time: rescan 1 reports "not
  saved", and rescan 2 finds `merged.records == stored`, returns False, and
  attempts no save and shows no refusal — status reads "no changes". The app
  looks healthy while nothing is persisted, and the projects are gone on the
  next start. Any transient failure (read-only mount, ENOSPC) has the same
  shape: the retry the user makes is silently a no-op.

  The docstring calls the test "differs from the loaded one", which is what
  it should be comparing against.
  Resolved (2026-08-24): `_should_write` now compares
  `merged.records` against `self._load.records` — the load, which
  `_apply_merge` refreshes only on the success branch — instead of
  against `self._controller.records()`, which it updates
  unconditionally. The `stored` parameter is gone rather than left
  unused, so there is no second candidate to compare against.

  A load that is not a `LoadResult` offers the write: for
  `RegistryMissing` that is first run as before, and for any other
  `RegistryError` the write is refused by `save_projects`' own gate
  and reported every time, which is the same defect this item names
  seen from the unparseable-file side.

  Red first: `test_a_refused_write_is_retried_by_the_next_rescan`
  runs two rescans against a save that always raises and pins them
  against each other — a gate that never writes passes the second
  half alone, one that always writes passes the first half alone.
  It failed 1 == 2 before the fix.

  Four mutants, all killed against a green 165-test baseline:
  reading the in-memory set again, `return True`, `return False`,
  and never taking the `LoadResult` branch. Full gate green (1164
  tests).
  **Layman:** If saving the project list fails, the app tells you once and then reports "no changes" forever while quietly saving nothing.
  Kind: fix.
  Source: close-phase-2026-08-21 lane-3 (window).
  Lanes: window, data-loss.

- ✅ [LWSM-1167] **FP08: `RowView.managed` does not mean what Open-in-browser's gate needs it to mean.**
  The comment says `managed` is "whether THIS manager spawned the process
  holding the port". It is computed as `set(self._supervisor.running())` —
  the registry keys — which says only that we have an ENTRY for that project,
  not who holds the port, and (per the self-exit finding above) not even that
  our child is alive.

  `mainwindow.py:730` gates Open on it: `self.open_button.setEnabled(running
  and row.managed)`. Two states ADR-0004 names by row give `managed=True`
  over a holder we did not spawn — `running (wrong port)`, where our child is
  alive on another port while a stranger holds the registered one; and the
  crashed-child case, where the stale entry persists and something else binds
  the port. Both open a browser at a stranger's port with this app's
  credibility behind it, which `mainwindow.py:717` says is the exact thing
  the gate exists to prevent.

  ADR-0004 requires managed identity to be "the recorded child PID plus its
  `create_time`". This is neither.
  Verification status (2026-08-21): **NOT independently confirmed.** This
  rests on the review lane's quotation and reasoning, which cite real
  file:line evidence, but the session that filed it did not itself trace
  `managed` through to an Open-in-browser click. The section intro's "every
  finding verified" overstates this bullet. **Confirm the mechanism before
  fixing** — start by checking what `supervisor.running()` actually returns
  against a project whose port is held by something else.
  CONFIRMED (2026-08-24), superseding the verification-status
  paragraph above. Reproduced end to end, not read: a real
  `Supervisor` started a real child whose launcher binds NOTHING,
  a separate real process then bound the registered port, and the
  row came back `running` with `managed` True — so Open was
  enabled over the stranger. The bullet's reasoning was right.

  Root cause is structural, not a wrong comparison. `_classify`
  asks only `snapshot.is_bound(port)`, and `PortSnapshot` carries
  the set of listening ports and nothing else. So no code can
  currently tell our holder from anyone's: the data to answer
  ADR-0004's "the recorded child PID" is not in the model.

  The fix is cheap because the data is already read and thrown
  away — `psutil.net_connections` returns the holding pid, and
  `PortProbe.snapshot` discards it. Carry it, then identify the
  holder by PROCESS GROUP against the recorded child's pid, which
  is also its pgid under `start_new_session=True`. The group, not
  the pid, because the server is usually a grandchild; and it is
  the same group `stop()` already signals, so the two cannot
  disagree. A holder pid psutil will not name (another user's) is
  correctly refused.

  TRAP — do NOT add `exited()` to the managed test. It reports
  that the LAUNCHER is gone, and LWSM-1165 deliberately keeps the
  registry entry while the group lives, because a `start.sh` that
  forks and exits leaves the server running. Gating on `exited()`
  would disable Open for exactly the double-forking launcher that
  item protects.

  Test shape, both needed. A controller-level test where the
  snapshot names a stranger as holder while `running()` holds our
  entry, which no fake could express before. And a probe-level
  integration test that the REAL socket table names our own pid
  for a socket we bind — without it the whole mechanism could be
  plumbed through fakes and never work live.

  Cost to expect: every existing fake probe reports no holder, so
  each test that asserts Open is ENABLED needs its fake taught who
  holds the port. That churn is correct rather than incidental —
  those fakes were asserting a gate that did not work.
  Resolved (2026-08-24) as the bullet's CONFIRMED block prescribes, and the
  shape came from ADR-0004 rather than from the bullet.

  `PortSnapshot` carries `holders` (port to pid) beside `listening`, and
  `PortProbe` keeps the pid `psutil.net_connections` was already returning and
  throwing away. `Supervisor.owns_pid(project, pid)` answers ownership, and
  `_managed_paths` now derives `managed` from the SAME snapshot that derives
  the statuses, in the same tick.

  **Read ADR-0004 before touching this again; it carries two rules the bullet
  did not.** It already specified the missing question -- classification
  "combines what the `Supervisor` knows ... with two questions `PortProbe`
  answers: *what holds the effective port?* and *which ports does this process
  group hold?*" -- and only the second was ever built. It also forbids gating
  on the "looks like this project" test: that is "a display heuristic with no
  security value, and nothing may be gated on it", because `chdir()` is free.
  And it fixes managed identity as "the recorded child PID **plus its
  `create_time`**, never the working directory".

  **`os.getpgid` rather than `_group_members`.** The bullet's fix shape said
  group, and it is right -- the server is usually a grandchild -- but
  `_group_members` walks every process on the machine and this runs once per
  project per second. `getpgid` is one syscall about one pid.

  **A holder the kernel will not name is not ours.** `psutil` reports no pid
  for another user's socket unless we are root, so `holders` is deliberately
  partial, and the gap must never become a claim.

  Six mutants, six killed -- but the sixth needed a second test, and the
  reason is worth keeping. Deleting the `_alive` PID-reuse guard SURVIVED the
  first pass, because `stop()` pops the registry entry (LWSM-1138), so the
  stop-path test answered False from the `managed is None` branch and never
  reached the guard. The replacement drives a launcher that exits ON ITS OWN,
  leaving the entry in place and the child an unreaped zombie whose pid is
  still reserved -- so `getpgid` still answers and only `_alive` separates a
  live child from a dead one. It asserts both preconditions explicitly.

  **Cost paid as predicted**: every fake probe reported no holder, so
  `FakeProbe` gained `holder=` / `holders=` and the fake supervisor gained
  `owns_pid`. That churn is correct rather than incidental -- those fakes were
  asserting a gate that did not work.

  Two things found on the way, filed rather than folded in: **LWSM-1189**, two
  pre-existing supervisor tests that leak a real `sleep 30` per run (confirmed
  pre-existing against a stashed tree). And a new trap in `CLAUDE.md` --
  stopping a child that has not finished STARTING leaks its grandchild while
  `StopOutcome` reports success, which cost one orphan per run until the tests
  waited for the launcher to signal it had spawned.

  Still open and untouched: **LWSM-1154**, the disclosure dialog ADR-0004 asks
  for. This keeps LWSM-1141's interim -- Open restricted to servers we
  started -- and makes that restriction TRUE, which it was not. The dialog
  still needs LWSM-1011's state model.
  1237 green, local-ci green.
  **Layman:** The button that opens a project in your browser is supposed to be off unless this app started the server. It can be on for a server the app did not start.
  Kind: security.
  Source: close-phase-2026-08-21 lane-4 (supervisor).
  Lanes: security, controller.

- ✅ [LWSM-1168] **FP08: `stop()` releases exclusivity at its first line, so a second child can be spawned mid-stop.**
  `stop()` pops the entry under the lock and then holds nothing for the whole
  grace/kill/reap window — the symmetric counterpart of the `starting` set
  LWSM-1137 added to `start()` is missing. Meanwhile `controller.py:797`
  clears the STOPPING overlay on the first derived STOPPED and
  `mainwindow.py:713` re-enables Start.

  So against a child that ignores SIGTERM: Stop is clicked, ~1 s later the
  overlay clears and Start re-enables while `stop()` is still inside its 5 s
  grace loop. Start finds the project in neither `processes` nor `starting`,
  passes the pre-flight and spawns a SECOND child. The old sequence then
  SIGKILLs the old group and `_port_after_stop` sees the new child's port
  bound, reporting "still bound by something this manager did not start" —
  false, it is the child this manager started three seconds earlier — and the
  controller discards the new STARTING overlay.
  Verification status (2026-08-21): **NOT independently confirmed.** The
  session that filed it did not drive a real Stop against a SIGTERM-ignoring
  child and then click Start inside the grace window. The lane's reading of
  the code is quoted and plausible, and the missing counterpart to
  LWSM-1137's `starting` set is real, but the UI timing half — that the
  overlay clears and Start re-enables before `stop()` returns — was not
  observed. **Reproduce first**; `tests/test_supervisor.py` already has a
  `trap '' TERM` launcher to build on.
  Resolved (2026-08-25). **Reproduced first, as the bullet demanded, and
  the supervisor half is CONFIRMED**: a second real child was spawned
  mid-stop, pid and all. The window is held open at the `_on_wait` seam
  rather than raced for — two calls back to back serialise on the GIL
  often enough to pass against the broken code.

  Fix: `stop()` now RESERVES the key in `_Registry.stopping` in the same
  locked block that pops it, and discards it in a `finally` — LWSM-1137's
  reservation read backwards, with `finally` for the same reason a
  half-failed stop must not leave a project unstartable for the session.
  It gates `start()` alone; a second `stop()` still returns an empty
  outcome, pinned by its own test.

  **The UI half of the filed diagnosis is WRONG in its stated mechanism
  and right in its conclusion.** The bullet says the STOPPING overlay
  clears about a second in against a SIGTERM-ignoring child. It does not:
  `_settle_overlay` settles STOPPING only on a derived STOPPED, and a
  child ignoring SIGTERM keeps holding its port, so the overlay persists
  for the whole grace window. The reachable route is a different branch —
  LWSM-1133's `effective_port is None` clause, which clears any overlay on
  the next poll. So it is a PORT-LESS project that re-enables Start
  mid-stop, not a stubborn one. MAME_Curator is such a project today.

  That leaves a smaller UI defect this item does not close: for a
  port-less project Start is enabled during a stop and now answers with a
  refusal instead of a second child. Correct, but a live button that
  always errors is worth a follow-up rather than widening this item.

  This is the sixth fold-in bullet found wrong about its own mechanism.
  The reproduction cost one test and settled both halves.

  Five mutants, five killed, baseline green. `CLAUDE.md`'s module map
  amended. `./scripts/local-ci.sh` green, no orphaned children after the
  run.
  **Layman:** Press Stop on a stubborn server and the Start button comes back before the stop has finished; pressing it starts a second copy, and the app then reports your own new server as a stranger's.
  Kind: fix.
  Source: close-phase-2026-08-21 lane-4 (supervisor).
  Lanes: supervisor.

- ✅ [LWSM-1169] **FP08: log rotation holds a descriptor outside the lock that a concurrent stop may have closed.**
  `_reap`'s comment claims the log descriptor "is one nothing else can still
  reach". `rotate_if_needed` takes the `ManagedProcess` under the lock and
  then releases it for the whole body, using `managed.log_fd` for `fstat`,
  `pread` and `ftruncate` — on the GUI thread, every poll tick, while
  `stop_async` runs `_reap` on a worker.

  This is LWSM-1138's hazard — "an integer the kernel is free to have
  reissued" — reached from rotation rather than from a double close, and
  popping the entry earlier does not close it. If the fd is reissued between
  the two, the GUI thread truncates whatever now holds that number: another
  project's log, the `.1` backup, or an atomic-write temp file.
  `_rotate_logs`' `except Exception` hides the benign EBADF variant and
  cannot see this one.
  Verification status (2026-08-21): **NOT independently confirmed, and this
  is the one most likely to be wrong.** The lane's reasoning is intricate —
  it needs `rotate_if_needed` to hold `managed.log_fd` past the lock, a
  concurrent `_reap` to close it, AND the kernel to reissue that exact
  integer before the `pread`/`ftruncate`. Each step is quoted from real code,
  but the window was never measured and may be too narrow to hit in practice.
  **Decide whether it is real before writing a fix**; if it is only
  theoretical, closing the fd inside the lock is still the cheaper answer
  than proving the race cannot happen.
  Resolved (2026-08-25): REPRODUCED before designing, so the bullet's
  "most likely to be wrong" caveat is now answered — it was right. A real
  `stop()` driven from inside the rotation's first `pread` left a bystander
  file truncated to zero bytes, with the freed descriptor provably reissued
  to it. The lane's framing understated it: fd reissue is not the improbable
  step, it is what the next `open` does, and the rotation opens the `.1`
  backup inside its own window. Fixed by duplicating the descriptor under
  the lock — while the entry is provably still held — and running the whole
  rotation on the duplicate, which is ours alone to close. Two tests: one
  forcing the window at `pread` (the truncation), one at `os.dup` (the
  check-then-act the lock closes). Mutants 4/5 killed; the survivor reverts
  `fstat` to the shared descriptor, which is bounded to the cap comparison —
  the copy loop stops at EOF, so it can select no wrong file to write or
  truncate.
  **Layman:** A rare timing collision between rotating a log and stopping a server could blank a different file the app owns.
  Kind: fix.
  Source: close-phase-2026-08-21 lane-4 (supervisor).
  Lanes: supervisor.

- ✅ [LWSM-1170] **FP08: `dbus-send`'s exit status is discarded, so placement fails silently off KWin.**
  `run_kwin_script` calls `runner(call, capture_output=True, timeout=...)`
  with no `check=True` and never reads `returncode` — **verified 2026-08-21,
  zero occurrences of either in the module**. A failed `loadScript` is
  indistinguishable from a successful one, so `run_kwin_script` returns True,
  `place_window` returns the rectangle rather than `None`, and
  `centre_on_screen` skips its status message.

  On GNOME or wlroots — where `XDG_SESSION_TYPE=wayland` and `dbus-send` is
  installed, so `placement_available()` says yes — the call fails with
  `ServiceUnknown: org.kde.KWin`, the window does not move, and nothing is
  reported. ADR-0007 requires the opposite in as many words: placement
  "degrades honestly ... rather than being offered and doing nothing".

  Fix: check the `loadScript` returncode.
  Resolved (2026-08-25): every one of the three D-Bus calls now has its
  exit status read; a nonzero one is warned about, with `dbus-send`'s
  stderr, and returns False, so `place_window` returns None and
  `centre_on_screen` reports it. The reporting chain already existed and
  was untouched.

  MEASURED FIRST, and it corrects the bullet's prescribed fix. Against
  real KWin on this machine's Plasma 6 Wayland session, 2026-08-25: a
  nonzero exit is the ONLY failure `dbus-send` reports, and it means the
  CALL did not land (absent service or bad method → exit 1,
  `ServiceUnknown` / `UnknownMethod` on stderr). It says NOTHING about the
  script — `loadScript` naming a file that does not exist still exits 0
  (reply `int32 0`), and `unloadScript` for a name never registered exits
  0 (reply `boolean false`). So "check the `loadScript` returncode" reads
  as though the status reported the load, and singling out one call would
  have left `start` and `unloadScript` exactly as silent. A mutant
  restricting the check to `loadScript` is killed by the new test's
  `start` case.

  Seam change, deliberately loud: the injected `run` must now return a
  `subprocess.CompletedProcess`, and its annotation says so. Four test
  fakes returned `None` and raised `AttributeError` rather than passing
  quietly — a stand-in that stopped modelling the status must not look
  like a success. Fixed in `test_placement.py` (2) and
  `test_mainwindow.py` (1 shared helper covering 3 tests).

  Verified: ./scripts/local-ci.sh green, no SKIP, no tool drift.
  Mutants 4/4 killed — status discarded, `loadScript`-only, warn-and-
  carry-on, stderr dropped from the warning.
  **Layman:** On a non-KDE Linux desktop the "Centre on screen" menu item looks available, does nothing when clicked, and says nothing about why.
  Kind: fix.
  Source: close-phase-2026-08-21 lane-1 (placement).
  Lanes: placement.

- ✅ [LWSM-1171] **FP08: the KWin script's directory is created with the mkdir form this project measured as wrong.**
  `placement.py` uses `state_dir.mkdir(parents=True, exist_ok=True,
  mode=0o700)` — the exact form `applog.py:70` and `configfile.py:121` both
  document as measured-wrong: the mode applies to the LEAF only, so every
  intermediate lands at the umask default (measured 0o755 on 2026-08-06).
  `exist_ok=True` also means an existing 0755 directory is used as-is, where
  `_prepare_state_dir` would re-chmod it.

  This is also a Rule-of-Three failure: `configfile.prepare_config_dir` and
  `applog._prepare_state_dir` both exist to do this correctly, and
  `supervisor.py` already calls the latter for this same tree. A weaker third
  copy is what `coding.md § 1.3` forbids.

  Not an open door on its own — `mkstemp` still creates the script at 0600
  with an unguessable name — but the window between writing it and KWin
  reading it is then guarded only by the file mode, in a directory another
  local account may be able to unlink from, for content the compositor
  executes.
  Resolved (2026-08-25): reproduced first — with umask 0o022 the filed form
  left both intermediates at 0o755 and reused an existing 0o755 leaf
  unchanged, exactly as filed. `run_kwin_script` now calls
  `applog._prepare_state_dir`, the name `supervisor.py` already uses for this
  same tree, rather than a third copy of the job. `configfile.prepare_config_dir`
  was the other candidate and is wrong here: it deliberately does NOT re-chmod
  an existing directory, which is the second half of this defect. Two tests, one
  per half, on a pinned umask. Three mutants, 3/3 killed, none inert — the full
  revert kills both tests and each partial fix kills exactly the one that names
  its half.
  **Layman:** A directory the app creates for a file the desktop then executes may be left readable by other accounts on the machine.
  Kind: security.
  Source: close-phase-2026-08-21 lane-1 (placement).
  Lanes: placement, security.

- ✅ [LWSM-1172] **FP08: the remembered window size is applied without the clamp ADR-0007 requires.**
  `_restore_geometry` calls `self.resize(*self._remembered_size)` and
  discards the clamped rectangle `place_window` returns; on X11 the `move`
  seam only moves. ADR-0007 requires a restored geometry to be "validated
  against the current screens" — naming "sized larger than the current
  display" explicitly.

  So `"width": 3800, "height": 2100` recorded on a 4K monitor opens
  uncapped on a 1920x1080 laptop. Note the inconsistency this creates: when
  the project list is empty at construction, `_apply_default_geometry` runs
  AFTER the restore and does bound the same stored size via
  `want.boundedTo(cap)` — so the identical file gives a capped window on one
  path and an uncapped one on the other.
  Resolved (2026-08-25): reproduced first, and the filed INCONSISTENCY is wrong
  in a way that matters. The bullet says the empty-list path bounds the size via
  `_apply_default_geometry` while the other does not. Measured on an 800x800
  screen with a stored 2400x2400: BOTH paths opened at 2400x2400. With rows,
  `_apply_default_geometry` runs inside `__init__` and its `boundedTo` is then
  overwritten by `_restore_geometry`, which fires off the first `showEvent`;
  with no rows it returns early and never runs. So there was no capped path,
  and a fix to `_restore_geometry` alone would have been enough.

  Fixed by one rule in one place — `_bounded_to_screen`, called from both — with
  the fraction lifted to `SCREEN_FRACTION` so two copies of `0.9` cannot drift.
  `_restore_geometry` now passes the window's own size to `_place_at` rather
  than the stored one, so KWin is asked for the rectangle the window actually
  is: its geometry write is authoritative, and asking for the unbounded size
  would undo the bound on the one platform where the user cannot drag the
  window back.

  Four tests: the two restore paths (parametrised), the reversed ordering where
  rows arrive after the restore, and what the compositor is told. Six mutants,
  four killed. Two survived, BOTH on pre-existing defensive lines this item did
  not introduce and neither is claimed as covered: the `floor` bound in
  `_apply_default_geometry` (the content minimum never exceeds the cap at any
  font the suite drives) and the no-screen headless branch (unreachable — the
  suite always has an offscreen screen).

  Noted, NOT fixed here: `_restore_geometry`'s docstring opens "Position first,
  then size" and its measured-KWin paragraph concludes place-then-resize, while
  the code has resized first since `kwin_script` stopped preserving the current
  size and began sending it explicitly. The prose is stale rather than the code
  wrong, but confirming that needs a real KWin session, which this item did not
  have.
  **Layman:** A window size remembered from a big monitor opens off the edge of a smaller screen.
  Kind: fix.
  Source: close-phase-2026-08-21 lane-1 (placement).
  Lanes: placement, window.

- ✅ [LWSM-1173] **FP08: `default_scan_roots` reads a user-controlled file with the unhardened reader.**
  `__main__.py:396` uses `config.read_text(encoding="utf-8")` on the
  `scan-roots` path. Twelve lines above, `_leading_comment_block` reads the
  SAME file through `read_bounded`, and its docstring says why: "this runs
  against a path the user controls, and that helper is where the
  FIFO-blocks-forever and the read-600 MB-into-memory cases are already
  closed." Two readers of one path, one hardened and one not — **verified
  2026-08-21**.

  `default_scan_roots()` runs inside `build_window` before any window exists,
  so a FIFO there blocks with no window, no error and no log line, and the
  `except (OSError, UnicodeDecodeError)` never fires because nothing is
  raised.
  Resolved (2026-08-27). Reproduced exactly as filed before designing:
  a FIFO at the scan-roots path blocked until killed, while
  `_leading_comment_block` on the same FIFO returned. `default_scan_roots`
  now reads through `read_bounded`.

  Two things the bullet did not name, both measured on the way:
  the size cap is load-bearing here for more than memory — a 2.4 MB file
  yielded 349,796 roots at 145 MB RSS, and every one of them is a
  directory the scan then walks; and the decode had to be chosen, because
  the fix replaces the read. `utf-8-sig`, matching the sibling reader of
  the same file — under plain `utf-8` a BOM left `# my header` as a scan
  root. That is LWSM-1182's class on the one reader its sweep could not
  reach, since that sweep was scoped to `read_bounded` consumers and this
  was the `read_text` one.

  `ConfigFileError` was deliberately NOT added to the `except`:
  `read_bounded` raises `OSError` only, and both real callers
  (`registry.load_projects`, `settings.load`) catch exactly that. The
  sibling's extra arm is dead code and was not copied.

  Three tests, one per hazard: FIFO (alarm safety net, `_Blocked` from
  `BaseException` so the code under test cannot swallow it), oversize,
  BOM. All three red first. mutation_probe 3/3 killed against a green
  baseline — reverting the whole reader kills 3, reverting the decode
  alone kills 1, which is what pins the decode independently.
  local-ci green, 1284 tests, no SKIP, no tool drift, no leaked processes.
  **Layman:** A booby-trapped scan-roots file can make the app hang on startup with no window and nothing in the log.
  Kind: fix.
  Source: close-phase-2026-08-21 lane-2 (settings).
  Lanes: settings.

- ✅ [LWSM-1174] **FP08: a long project name pushes every row's buttons out of reach, unrecoverably.**
  Nothing bounds a project `name` on the way in — the registry validators
  impose no length limit and a scanned directory name is legal to 255 bytes —
  and `ProjectRow._name` has no elide or word-wrap, so `natural_widths()`
  returns the full text advance. `_align_columns` then applies that as a
  FIXED width to EVERY row.

  **Verified 2026-08-21**: the scroll area sets
  `ScrollBarAlwaysOff` horizontally, `apply_column_widths` uses
  `setFixedWidth`, and `_apply_default_geometry` runs once and is capped at
  90% of the screen — so the window minimum does not protect the content and
  the window is never resized again. The controls are then off-screen for all
  projects, unreachable by mouse, and the filter does not help because
  `_align_columns` iterates every row including hidden ones and is not re-run
  on a filter keystroke.

  Also reachable through an imported profile, since `name` is in
  `USER_FIELDS` and is restored verbatim.
  Resolved (2026-08-24): the name column is capped at `NAME_COLUMN_CHARS`
  and elided past it, measured through the font metric rather than in pixels
  (`§ O7`) so the 100-200 % text-size control still reaches it.

  Fixed while shipping LWSM-1187, which could not fit inside
  `design-accessibility.md`'s ~600 px lens band until this was closed --
  measured at 593 px before the picker existed and 677 px with it. The row
  now ends at 561 px with the picker AND the longest fixture name, which is
  more headroom than it had before either change.

  **What was fixed is the BOUND, not the two mechanisms the bullet also
  names.** `_align_columns` still iterates hidden rows and still is not
  re-run on a filter keystroke. Both were only harmful because the width was
  unbounded; with a cap the worst case is bounded by construction, so
  neither can push a control off-screen. Recorded rather than silently
  treated as covered.

  The full name is kept: tooltip when something was actually cut, and the
  accessible name of the row and of every control in it. That last part was
  not true of the first version and the suite could not see it -- see
  LWSM-1187's note.

  Two mutants killed: uncapping the column, and eliding a name that fits.
  The second is not hypothetical -- `elidedText` will cut a string whose
  advance merely EQUALS the width it is given, and the column is set to
  exactly that advance for every name under the cap, so a first version
  rendered "alpha" as "alp...".
  **Layman:** One project with a very long folder name can push the Start and Stop buttons off the edge of the window for every project, with no scrollbar and no way to get them back.
  Kind: fix.
  Source: close-phase-2026-08-21 lane-3 (window).
  Lanes: window.

- ✅ [LWSM-1175] **FP08: changing the theme or the language deletes a row's visible failure message.**
  `update_from` calls `clear_error()` on the grounds that "the state has
  moved on, so a failure describing the old one is now a lie". That reason is
  false on two paths: `_rerender` — shared by `retranslate` and
  `apply_theme` — deliberately nulls `_view` so the equality guard cannot
  fire, precisely because both change how the view is RENDERED without
  changing the view.

  So `set_theme` → `apply_theme` → `_rerender` → `update_from` →
  `clear_error()` destroys a message nothing has invalidated. The user this
  hurts is the one switching to a high-contrast theme in order to read it,
  which is the user the theme exists for.
  Verification status (2026-08-21): **NOT independently confirmed.** The
  `_rerender` → `update_from` → `clear_error()` path is quoted from real
  code and reads correctly, but the session that filed it did not show an
  error on a row and then switch theme to watch it vanish. **One qtbot test
  settles it** — and that test is worth writing whichever way it comes out.
  Resolved (2026-08-27). The bullet filed itself NOT independently
  confirmed and said one qtbot test would settle it whichever way it came
  out. Written first, before any fix: it came out REPRODUCED, on both
  `_rerender` callers. A row showing "it would not start" lost the message
  on `set_theme` and on `retranslate`.

  The fix is to `_rerender`, not to `clear_error`. Nulling `_view` to get
  past the equality guard worked on the guard and had collateral one line
  below it, so `_rerender` now says what it is — `update_from(view,
  rerendering=True)` — and the one flag answers both keys, which are the
  same question: is this a state change or a redraw? Everything else in
  `update_from` is rendering and is correctly re-run. The announcement
  needed nothing: LWSM-1141 already gates it on the accessible NAME, so a
  language change re-announces and a theme change does not.

  Not over-corrected, and that is pinned rather than asserted:
  `test_the_failure_clears_when_the_row_moves_on` already existed and
  kills the "never clear at all" mutant. mutation_probe 3/3 killed against
  a green baseline — reverting the fix kills the two new tests, the
  over-correction kills the pre-existing one, and dropping the guard
  escape kills two. local-ci green, 1286 tests, no SKIP, no tool drift.
  **Layman:** If a project fails to start and you switch to the high-contrast theme to read the message, the message disappears.
  Kind: fix.
  Source: close-phase-2026-08-21 lane-3 (window).
  Lanes: window, accessibility.

- ✅ [LWSM-1176] **FP08: two translated strings use `str.format`, the one construct this file forbids by name.**
  **Verified 2026-08-21**: exactly two `.format(` calls exist in
  `mainwindow.py`, at `:1322` and `:1430`, and both are on
  `QCoreApplication.translate` results — the text-size and theme save-failure
  messages.

  The file states the rule against this three times, once as "The rule is the
  file's, not that function's", and records that it was written as `.format`
  first and caught within the hour: a translator returning some other
  string's text raises `KeyError` out of the handler, leaving every window in
  the process half-retranslated (LWSM-1082).

  Both sites are inside `except` blocks written to prevent a crash, so a
  hostile or merely mismatched translation turns a handled save failure into
  an exception out of a `QAction.triggered` slot. Fix: `%1` plus
  `str.replace` at both.
  Resolved (2026-08-31): reproduced exactly as filed — both sites still
  present, line numbers moved. The red test installs a `QTranslator`
  returning a renamed placeholder and drives both `except` blocks: with
  `.format` the text-size path raised `KeyError` out of a
  `QAction.triggered` slot, which PySide6 swallowed, so the status bar was
  left EMPTY rather than the process dying. The test therefore asserts the
  message, not the absence of an exception. Both sites now use `%1` plus
  `str.replace`, the idiom the rest of the file already uses. Mutants 4/4
  killed — reverting either site to `.format`, and dropping either
  substitution entirely (the over-correction), each of which a pre-existing
  test catches. Gate green, no leaked processes.
  **Layman:** A translation mistake in two error messages could crash the app instead of showing the message.
  Kind: fix.
  Source: close-phase-2026-08-21 lane-3 (window).
  Lanes: window, i18n.

- ✅ [LWSM-1177] **FP08: the Rescan button's label is never retranslated.**
  **Verified 2026-08-21**: `setText` is never called on `_rescan_button` —
  the only uses are its construction and `setEnabled`. `_retranslate_menus`
  covers `_rescan_action` and stops there.

  `_set_rescan_enabled`'s docstring calls the button and the menu entry "one
  control with two faces", and `changeEvent`'s LanguageChange branch claims
  the shape of a generated `retranslateUi`. Both are false for the most
  prominent control in the window, and its accessible name comes from that
  text, so a screen reader gets the stale string too.
  Resolved (2026-08-31): reproduced as filed. The red test sends
  `LanguageChange` by hand and asserts BOTH faces, so it cannot pass by the
  pair going stale together — the menu entry retranslated, the button did
  not.

  The fix did NOT go where the bullet's evidence pointed. Putting the
  button's `setText` beside the menu entry's in `_retranslate_menus` broke
  182 tests: `_build_menus` runs before the strip is built, so the button
  does not exist at that point. `_retranslate_filter` is the method that
  runs after construction AND on `LanguageChange`, so the label went there
  and the method is renamed `_retranslate_strip` — it now owns the strip's
  labels rather than the filter box's alone. The button is also constructed
  unlabelled, so one place owns the text and the two cannot drift again.

  Mutants 3/3 killed (reversion, an untranslated literal in the same shape,
  inverted guard). A FOURTH survived and is a pre-existing gap, not this
  item's: deleting `_filter.setPlaceholderText` entirely leaves the suite
  green. The only assertion touching it (LWSM-1040) compares it against the
  accessible name for inequality, which an empty placeholder still
  satisfies. Reported, not fixed here.
  **Layman:** After switching language, the Rescan button stays in the old language while its menu entry changes.
  Kind: fix.
  Source: close-phase-2026-08-21 lane-3 (window).
  Lanes: window, i18n.

- ✅ [LWSM-1178] **FP08: a scan-roots file that failed to read is written back as if it were the user's list.**
  `default_scan_roots` returns `fallback` on `OSError` / `UnicodeDecodeError`
  and records nothing to say the value is a fallback rather than the user's
  list. `save_scan_roots` then writes whatever the dialog holds.

  So: six roots, one containing a non-UTF-8 byte (or a momentary read
  failure); the dialog shows one folder; the user clicks OK; the other five
  are gone — and `_leading_comment_block` fell back too, so the user's header
  goes with them. The docstring's stated loss covers only interleaved
  comments; this case is stated nowhere.

  Same shape as the `settings.json` finding above and wants the same answer:
  the reader must say whether it fell back, and the writer must refuse.
  Verification status (2026-08-21): **NOT independently confirmed.** Filed
  from the lane's reading. It is the same shape as LWSM-1163, which WAS
  reproduced, so the mechanism is credible — but the specific claim that
  `_leading_comment_block` falls back on the same input was not tested.
  Reproduce alongside LWSM-1163's fix; they want one answer.
  Resolved (2026-08-31): CONFIRMED, including the half the bullet said was
  untested. A throwaway probe wrote a two-line header plus six roots with one
  non-UTF-8 byte: `default_scan_roots` returned `(~/projects,)`,
  `_leading_comment_block` returned OUR header, and one `save_scan_roots`
  replaced all 115 bytes. Both readers fall back on the same input, exactly as
  filed.

  The gate is LWSM-1163's, placed differently and for a stated reason. There
  the reader reported and the CALLER refused, because `settings.save` cannot
  tell a refused document from a clean one. Here `save_scan_roots` reads the
  same path itself, through `_leading_comment_block`, so that read is the one
  place where the file's condition and the impending write are both in scope —
  no signature change, no second read, and the refusal holds for every caller
  rather than the one that remembered.

  Absence is the split LWSM-1163 named: only `FileNotFoundError` returns the
  default header, because a first run has nothing to lose and must stay
  writable. `UnicodeDecodeError` is CONVERTED to `ConfigFileError` and an
  `OSError` is not — the first is not a type `build_window`'s handler catches
  and would have escaped as a bare traceback; the second already is, so a
  conversion would be a layer that buys nothing. The test asserts that handler
  tuple rather than one class, and pins what matters: the save refuses and the
  bytes survive.

  Tests: both arms (a non-UTF-8 byte, and mode 0o000) — they are different
  `except` arms and a fix closing one left the other writing the file away.
  Mutants 4/4 killed: the blanket fallback restored, the conversion dropped,
  absence refused too (the over-correction, caught by a pre-existing test), and
  absence widened to any `OSError`. Gate green, no leaked processes.
  **Layman:** If the app cannot read your list of folders to scan, opening Preferences and clicking OK replaces your list with the fallback.
  Kind: fix.
  Source: close-phase-2026-08-21 lane-2 (settings).
  Lanes: settings.

- ✅ [LWSM-1179] **FP08: a scan root with surrounding whitespace or a newline does not survive the round trip.**
  `save_scan_roots` writes one root per line verbatim; `default_scan_roots`
  reads each back through `Path(line.strip())`. `SettingsDialog._add_root`
  deliberately stores the chooser's text unmodified.

  So `/home/user/my projects ` (trailing space, legal on Linux) is written
  verbatim and read back as `/home/user/my projects`, which does not exist:
  the scan finds nothing there and reports no problem, and the dialog now
  shows a path the user did not choose. A directory name containing a newline
  is worse — one configured root becomes two nonexistent ones.
  Verification status (2026-08-21): **NOT independently confirmed** — a
  one-line round-trip check would settle it and was not run. Note this is
  the lowest-value bullet in FP08: a trailing space in a directory name is
  rare, and the fix (strip on the way IN, at the chooser) may be worth less
  than the test that pins it. Decide whether it is worth doing at all before
  doing it.
  Resolved (2026-08-31): CONFIRMED by the one-line round-trip check the bullet
  asked for. `/srv/trailing ` came back stripped, `/srv/tabbed\t` likewise, and
  `/srv/two\nlines` came back as TWO roots — the second RELATIVE, so the scan
  would walk it from the process's working directory, which the bullet did not
  anticipate. A LEADING space survives: the reader strips the LINE, and a
  leading space inside a rooted path is interior.

  The bullet asked for a decision before acting, and it is recorded here. Fixed,
  but not where it proposed. Stripping at the chooser leaves a hand-edited file
  wrong, and it changes the directory the user picked without saying so. The
  refusal lives in `save_scan_roots` instead — before anything is read or
  written, so the previous list survives — which is fewer lines, covers every
  caller, and is the shape LWSM-1178 had just given the same function one item
  earlier.

  The guard is about what the round trip LOSES, never about spaces:
  `/srv/my projects` is ordinary, round-trips exactly, and has its own test, so
  a widened check dies.

  Mutants 4/5 killed — no guard, whitespace-only, newline-only, and reject-any-
  space. The fifth (strip in the body instead of refusing) SURVIVED and is an
  equivalent mutant rather than a finding: the guard raises before that line is
  reached, so no test can distinguish it. Gate green, no leaked processes.
  **Layman:** A folder whose name starts or ends with a space silently stops being scanned after you save it.
  Kind: fix.
  Source: close-phase-2026-08-21 lane-2 (settings).
  Lanes: settings.

- ✅ [LWSM-1180] **FP08: five docstrings describe mechanisms the code no longer has.**
  All five verified 2026-08-21, and four are in code written the same day —
  which is the point: prose ages against its own edit within hours.

  1. `_restore_geometry` explains its resize-then-place order by a race with
     a script that reads `c.frameGeometry.width` back. The shipped script is
     handed the size instead, so that race cannot happen; the genuinely
     load-bearing constraint (KWin's write is authoritative, so the script
     must carry the size) is stated only in `placement.py`.
  2. `clamp_to_screens` claims "what reaches the KWin script is a rectangle
     inside a real screen". The decoration is added AFTER the clamp, inside
     the script, so the frame can exceed the clamped rectangle.
  3. `Rect`'s docstring calls it "a type that can only hold integers" and
     half the injection guarantee. A frozen dataclass validates nothing —
     `Rect("0); evil(); //", 0, 1, 1)` constructs fine (verified). The real
     guard is `settings._bounded_int_or_reason` plus the `int()` calls in the
     template, and this claim would invite deleting the latter as redundant.
  4. `settings.py`'s geometry comment routes the reader to
     `_remembered_rect`, which exists nowhere in the tree — the decision is
     split between `placement.pair_or_none` and `_restore_geometry`.
  5. `exited()` says the registry entry "is removed in `_reap`". LWSM-1138
     moved the pop to `stop()`; anyone fixing the self-exit finding above by
     following this comment looks in the wrong function.
  Verification status (2026-08-21): **items 3 and 4 were confirmed
  directly** — `Rect("0); evil(); //", 0, 1, 1)` was constructed successfully
  in a live interpreter, and `_remembered_rect` was grepped and appears
  nowhere but its own comment. **Items 1, 2 and 5 rest on reading both sides
  of the contradiction** and were not otherwise checked; they are docstring
  corrections, so the cost of being wrong is a re-read rather than a bad fix.
  Progress (2026-08-25): item 1 independently re-derived while shipping
  LWSM-1172, from the code rather than from this bullet, and it holds exactly as
  written — the summary line reads "Position first, then size", the measured
  paragraph concludes place-then-resize, and the code resizes first. Still
  unfixed, still a docstring correction, and this item remains its owner: the
  LWSM-1172 note records the finding and points nowhere, so do not file a
  duplicate.

  One thing changed underneath it. LWSM-1172 made `_restore_geometry` hand
  `_place_at` the window's OWN size rather than the stored one, which only reads
  correctly if the resize has already happened — so the resize-first order is now
  load-bearing for a second, independent reason that has nothing to do with the
  KWin race this docstring describes. Whatever replaces the prose has to say
  that. Confirming the race itself is dead still needs a real KWin session; a
  green suite is not evidence for anything the compositor owns.
  Resolved (2026-08-31): four corrected, and ITEM 5 NEEDED NO FIX — `exited()`'s
  docstring was corrected by LWSM-1165 and names that item by id while saying the
  pop has been in `stop()` since LWSM-1138. This bullet was stale on it, which is
  the same ageing it was filed about.

  All four re-verified before editing rather than taken from the bullet. Item 3
  was re-run live (`Rect("0); evil(); //", 0, 1, 1)` constructs); item 4's
  `_remembered_rect` still appears nowhere but its own comment, and
  `placement.pair_or_none` plus `_restore_geometry` are the real deciders; items
  1 and 2 were read against the shipped `kwin_script`, which is handed the size
  and adds the decoration margins itself.

  Item 1 is now honest about a thing the bullet did not ask for. The old text
  justified the order by a race, and the summary line said "Position first" while
  the code resizes first. The measurement it quoted was taken against the
  REFUTED script, so it could not be kept as evidence for the current order —
  what keeps the order today is LWSM-1172, and the docstring says so and says
  outright that nothing has been re-measured under a live compositor since the
  script changed.

  Item 2 keeps the security claim it can support and drops the one it cannot: the
  clamp bounds the CLIENT rectangle, and the script adds decoration after it, so
  the placed frame can exceed it. The injection half is untouched and now points
  at `Rect`, where item 3 states where the guarantee actually lives.

  No test: documentation-only, and `testing.md § 8` / `write-test` both refuse
  one. No CHANGELOG entry either — every entry there is user-visible and an
  internal comment is not. Gate green (1294 verified), no leaked processes.
  **Layman:** Five comments explain how something works and are now out of date, which would mislead the next person who reads them.
  Kind: doc-fix.
  Source: close-phase-2026-08-21 lanes 1 and 4.
  Lanes: docs.

- ✅ [LWSM-1181] **FP08: check whether an untrusted project name can distort the trust dialog.**
  Raised by the window lane from OUTSIDE its assigned slice and passed on
  rather than dropped, so it is filed to be checked rather than as a
  confirmed defect.

  `_confirm_dialog` builds the trust prompt with three chained `.replace`
  calls, the first substituting `project.name` — a directory name from
  someone else's tree — into a template that still contains `%2` and `%3`. A
  name containing `%2`, `%3` or a newline therefore reaches a later
  substitution as part of the template.

  This matters more than the usual escaping question because it is the one
  dialog whose entire purpose is telling the user what is about to run, and
  the launcher-symlink finding above already shows that dialog naming the
  wrong file. Verify, then fix or dismiss with a reason.
  Resolved (2026-08-31): investigated and CONFIRMED, and the investigation found
  the larger half the bullet had not reached.

  As filed: `%1` was substituted into a template still holding `%2` and `%3`, so
  a directory called `evil%2` had the resolved launcher path pasted into its own
  name. Real, and fixed.

  Not as filed, and worse: reordering the substitutions would not have been
  enough. ALL THREE fields — name, resolved path, argv — come from someone
  else's tree, and the dialog is one plain-text block whose headings are its
  only structure. A line break in ANY of them draws a second "This will
  execute:" naming a different program above the real one. So the fix is not an
  ordering change: all three go in on one `re.sub` pass, which never rescans what
  it substituted, and each is rendered with its line breaks escaped.

  Stated loss: a name holding a literal backslash-n now displays the same as one
  holding a line break. Distinguishing them costs escaping every backslash in
  every path shown, and neither can forge the dialog, which is what this
  defends.

  Tests: the `%2` case, and a forgery asserted against a BENIGN prompt rather
  than a fixed count — what is pinned is that an untrusted value adds no line,
  whatever the template says. The forged name deliberately holds no `/`, so the
  whole structure comes from ONE directory name.

  Mutants 4/4 killed, in two runs. The first three left the one-pass property
  unpinned — the mutant labelled for it had removed the escape instead — so a
  fourth was run that reverts ONLY the single pass, keeping the escape. It dies.
  Gate green (1296 verified), no leaked processes.
  **Layman:** Check whether a project with an unusual folder name can make the "do you want to run this?" box say something misleading.
  Kind: investigate.
  Source: close-phase-2026-08-21 lane-3 (window), outside its assigned slice.
  Lanes: security, window.

- ✅ [LWSM-1182] **FP08: a BOM refuses settings.json where projects.json tolerates it, and LWSM-1163 made that permanent.**
  `registry.load_projects` decodes `utf-8-sig`; `settings.load` decodes
  plain `utf-8`. `registry.py`'s own comment states the reasoning and it
  applies here word for word: "an editor-added BOM is invisible in that
  editor and would otherwise refuse the whole file with a reason naming
  byte 0, which sends the user looking at the wrong thing."

  The same class as LWSM-1164 and LWSM-1116 — a guard that exists next door
  and is missing here — and found the same way, by reading the two loaders
  side by side.

  **LWSM-1163 turned it from cosmetic into permanent.** Before that gate a
  BOM meant the defaults were used and the file was silently rewritten
  clean on the next save. Now a whole-document refusal blocks every write,
  so a BOM makes `settings.json` un-writable for good: no preference
  persists, the status bar reports a reason naming byte 0, and the user
  cannot see the character it names.

  Not a regression to revert — the gate is right and the decode is wrong.
  Fix: decode `utf-8-sig` in `settings.load`, matching `registry`. Then
  check the other `read_bounded` consumers for the same divergence — the
  `scan-roots` file (LWSM-1144) at least has not been looked at.
  Resolved (2026-08-23), taken immediately after filing rather than in
  list order, because LWSM-1163 shipped the same day is what made it
  permanent and leaving that window open while sixteen other items landed
  was the worse trade.
  `settings.load` now decodes `utf-8-sig`, matching `registry` and
  `scanner`. The bullet's second half — check the other `read_bounded`
  consumers — found exactly one more, and it fails DIFFERENTLY, which is
  why reading the code beat reasoning about it. In
  `__main__._leading_comment_block` a BOM does not fail to decode at all:
  `U+FEFF` is a valid character, `lstrip()` leaves it alone because it is
  not whitespace, so the first line is not a comment, the loop breaks
  immediately, and the user's entire header is replaced by ours on the
  next save. Measured before it was fixed.
  Two tests, one per reader, each dying on its own decode reverted. The
  scan-roots one sits beside `test_the_users_own_header_survives_a_save`,
  which passes on the unfixed code — the defect is entirely in a character
  no assertion can display, so the pair is what makes it visible. 1157
  green, local-ci green.
  **Layman:** If your text editor adds an invisible marker to the start of the settings file, the app stops remembering any of your choices, and nothing on screen says why.
  Kind: fix.
  Source: in-session-2026-08-23, found while shipping LWSM-1163.
  Lanes: settings.

- ✅ [LWSM-1191] **FP08: a port-less project re-enables Start while its stop is still running.**
  Found while closing LWSM-1168, which fixed the dangerous half. The
  supervisor now refuses a Start issued mid-stop, so no second child is
  spawned — but the button that issues it is still live, so the user
  gets an error for pressing an enabled control.

  The route is not the one LWSM-1168 was filed with. `_settle_overlay`
  settles a STOPPING overlay only on a derived STOPPED, so a child that
  holds its port keeps the overlay for the whole grace window. What
  clears it early is LWSM-1133's separate branch: a project whose
  `effective_port is None` has nothing to wait for, so the overlay is
  dropped on the very next poll — within the poll interval, while
  `stop()` may still have seconds to run.

  MAME_Curator is such a project today, deliberately: it declares no
  default port at all, and LWSM-1190 stopped the scanner inventing one.
  So this is reachable on the author's own tree rather than
  hypothetical.

  The fix is not simply to keep the overlay — LWSM-1133 removed a real
  defect where a port-less project read `starting` for the life of the
  session with every button dead. Whatever lands has to leave that
  closed. The narrower question is whether Start specifically may be
  enabled while the supervisor holds a stop reservation, which is a
  fact the controller can ask for rather than infer from the port.
  Resolved (2026-08-31): reproduced, and the ROUTE is narrower than filed —
  measured, not argued. Stop and Restart are BOTH gated on a derived `running`,
  which needs a port, so a project that has never had one cannot be stopped from
  the UI at all. What reaches this state is a project stopped WHILE it had a
  port whose port then goes away under it: a rescan that no longer detects one,
  which is exactly what LWSM-1190 made possible for a project declaring none.
  The reproduction drives that sequence and the two preconditions are asserted,
  so it cannot pass by never reaching the state.

  Fixed the way the bullet's last paragraph proposed: `Supervisor.is_stopping`
  reads the reservation `stop()` already holds, `RowView.stopping` carries it,
  and Start is gated on it. Nothing infers anything from the port, and
  LWSM-1133's branch is untouched.

  Asked at RENDER time, unlike `managed`, and the reason differs: `managed` must
  come from the poll's own snapshot (LWSM-1167) because it is a fact about the
  socket table, while this is the supervisor's own bookkeeping and the only
  useful answer is the current one.

  The test found a second defect the gate itself introduced, which is why it
  pins both halves in one test. `_maybe_emit` compares statuses only, and a
  port-less project's status never changes — so nothing re-rendered the row when
  the stop finished and Start would have stayed disabled for the session, which
  is LWSM-1133's defect by another route. `_on_stopped` now emits in a `finally`.
  Caught by the second assertion timing out, not by review.

  Mutants 7/7 killed across three files: Start ignoring the reservation, Start
  never returning, the view never reporting it, no re-render on completion, and
  `is_stopping` always-false / always-true / reading `processes`. The real
  `Supervisor.is_stopping` has its own test held open at `_on_wait` rather than
  resting on the window fake. Gate green (1298 verified), no leaked processes.
  **Layman:** On a project whose port the app cannot detect, the Start button comes back before the stop has finished, and pressing it just shows an error.
  Kind: fix.
  Source: in-session-2026-08-25.
  Lanes: controller, window.

## FP09 — Fourteen-lane review fold-in (check-code + review-code, 2026-09-01)

A whole-tree check-code run followed by a fourteen-lane review-code sweep over
every src/ module, all five scripts, the pre-push hook and ci.yml. check-code
returned ONE surviving finding across eleven tools; everything else it raised
was calibrated or verified false and is recorded in .ants_review_falsepos.jsonl.
The lanes returned 0 CRITICAL, 15 HIGH and 53 MEDIUM, plus roughly 100 LOW/INFO
grouped per lane at the end of this section. Severities below are the
orchestrator's calibrated ranks, not the lanes' raw ones; the four that moved
say so in their body. mainwindow.py:169 is the only finding two independent
lanes cited at the same file and line, and it is the one to fix first. No fix
has been applied yet — every item in this section is open.

- ✅ [LWSM-1196] **HIGH: _no_line_breaks escapes only CR and LF, so U+2028 still forges a trust-dialog heading.**
  mainwindow.py:169. The only finding two independent lanes cited at the
  same file and line. Qt hard-breaks on U+2028 LINE SEPARATOR, U+2029
  PARAGRAPH SEPARATOR and U+0085 NEL; QTextDocument uses the first two as
  its own internal break characters. A Linux directory name admits every
  byte but / and NUL, so `evil  This will execute: /usr/bin/true`
  reproduces exactly the forgery LWSM-1181 shipped to close. Fix by
  category, not by two literals: escape Zl/Zp/Cc/Cf, or at minimum add
       \v \f. VERIFY AGAINST A REAL DIALOG before and
  after, the way LWSM-1181 was measured - the suite cannot see this.
  Resolved (2026-09-02). Reproduced against a real QMessageBox, and the
  measurement CORRECTED the bullet twice. Qt breaks on U+2028 AND U+2029;
  it does NOT break on U+0085 NEL, nor on VT or FF — so the bullet's
  "at minimum add VT FF" would have added three dead branches and still
  missed U+2029. Cf earns its place on its own measurement rather than as
  defence in depth: `start<U+202E>abc.sh` renders pixel-identically to
  `starths.cba`, forging the path in place in the dialog whose job is
  naming what runs. Fixed by category (Cc/Cf/Zl/Zp) and renamed to
  `_no_layout_forgery`, since the old name is the reading that caused
  the defect. The FIRST red test was vacuous — its control string held a
  slash, so `Path` split it and the name under test collapsed to the last
  component; the pre-existing test's own comment warns of exactly that.
  Also: the claim "the suite cannot see this" is WRONG. It can, offscreen,
  by comparing rendered heights of two names differing by one character —
  a relative comparison, so the CI-font trap does not apply. 4/4 mutants
  killed, including the over-correction. Gate green, 1307 tests.
  **Layman:** A folder with a sneaky name can still fake a line in the "do you trust this?" box — the fix that was meant to stop that only covers two of the characters that break lines.
  Kind: security.
  Source: review-code 2026-09-01 lanes 10+12 (corroborated).

- ✅ [LWSM-1197] **HIGH: Stop and Restart signal an unverified holder, without the managed gate Open has.**
  mainwindow.py:882-883. `open_button` is gated on `running and
  row.managed` with a nine-line comment deriving that gate from ADR-0004's
  threat model. The two buttons that actually SIGNAL got neither the gate
  nor a substitute. ADR-0004 requires the opposite for Stop specifically:
  enabled but confirming first, with an unspoofable pid/path/create-time
  disclosure. Interim fix until P06 lands: gate Stop and Restart on
  `row.managed` too, and extend the comment at :884 to say so.
  Resolved (2026-09-02). The FILED SECURITY CLAIM DOES NOT HOLD, and the
  code already said so: `controller.stop_project` refuses any project the
  supervisor holds no handle for, emitting "was not started by this
  manager", and a test has pinned that since LWSM-1032. `Supervisor.stop`
  independently returns an empty outcome for a key it does not hold. So
  nothing foreign was ever signalled and ADR-0003 was never breached; this
  is a UX defect, not a HIGH security one, and should have been filed as
  such. Restart was the same story by a different route: it falls through
  to `start_project`, which the bound-port pre-flight then refuses.
  What WAS real: both buttons were offered and could only ever fail. Fixed
  as the bullet prescribed - gate both on `row.managed`, as Open already
  is - so the control says what it can do. A pre-existing test reddened
  (`test_enter_stops_a_running_project`) and the trap applied: it claims
  Enter clicks Stop when Stop is enabled, and its fixture simply had no
  way to express "running AND ours" because `window_for` built a
  controller with no supervisor at all. Widened the fixture, kept the
  claim. 4/4 mutants killed including both over-corrections. Gate green.
  **Layman:** The Stop button will signal whatever is holding the port, even when it is not a server this app started.
  Kind: security.
  Source: review-code 2026-09-01 lane 10.

- ✅ [LWSM-1198] **HIGH: the Centre-on-screen disabled tooltip is set on a surface that never renders it.**
  mainwindow.py:1598. ADR-0007 promises the action is "disabled with a
  tooltip saying why - rather than being offered and doing nothing".
  QMenu::toolTipsVisible defaults to false and setToolTipsVisible appears
  NOWHERE in the tree, so the string is never rendered. Hits exactly the
  population placement_available() returns false for. setToolTipsVisible(True)
  is necessary and NOT sufficient: design-accessibility.md says nothing
  important may be hover-only, so also carry the reason at rest - append it
  to the action text when disabled, or set statusTip.
  Resolved (2026-09-02). Reproduced as filed, and both halves were needed.
  `QMenu.toolTipsVisible()` measured False by default, and
  `setToolTipsVisible` was absent from the tree, so ADR-0007's "disabled
  with a tooltip saying why" was never rendered for the population it is
  written for. Necessary but not sufficient, exactly as the bullet said:
  `design-accessibility.md` puts nothing important behind a hover, so the
  label now carries the fact ("unavailable on this desktop") and the
  tooltip the detail. This bullet's stated cause needed no correction -
  the third of the run, against two that did. The enabled label is
  unchanged, which the pre-existing mnemonic test pins. 4/4 mutants
  killed; the over-correction needed narrowing first, because its anchor
  matched the tooltip block too and would have reported a kill for a
  wider mutation than its label described. Gate green, 1309 tests.
  **Layman:** When "Centre on screen" is greyed out we wrote an explanation nobody can see, because Qt menus hide tooltips by default.
  Kind: review-fix.
  Source: review-code 2026-09-01 lane 11.

- ✅ [LWSM-1199] **HIGH: a rescan in flight silently discards a hide or browser choice made while it ran.**
  mainwindow.py:2292. The merge's `stored` half is snapshotted when the
  rescan STARTS. set_project_hidden and set_project_browser can write while
  it is in flight; the rescan lands, _should_write compares its stale-snapshot
  merge against the fresh _load, finds a difference and writes. The project
  already reasoned its way to the right answer for IMPORT ("a rescan that
  started first writes last") and did not apply it to the other two writers.
  Fix: disable both controls while _rescan_in_flight as import already is, OR
  re-apply current USER_FIELDS onto merged.records inside _apply_rescan.
  Resolved (2026-09-02). Reproduced exactly as filed, with the rescan HELD
  OPEN inside the window rather than raced for - the scan blocks on an
  event until the hide has landed. Took the bullet's SECOND option
  (re-apply the current user half) over the first (disable the controls),
  because blocking a two-second action for the length of a scan is a
  workaround for the stale snapshot rather than a fix for it, and
  `coding.md § 1.2` asks for the root cause. Applied in `_apply_rescan`
  and deliberately NOT in `_apply_merge`: an import goes through that too,
  and an import's whole purpose is to bring a user half with it, so
  refreshing there would undo the import. Reused the registry's own helper
  - promoted `_user_half_applied` to `user_half_applied` - rather than
  writing the field list out again, since INV-1 keeps USER_FIELDS
  complete. 3/4 mutants killed. The fourth SURVIVED and is equivalent by
  construction: `current.get(path, record)` on a discovered project gives
  `user_half_applied(record, record)`, which is the no-op the `else`
  branch already is. Recorded rather than cleared with a contrived
  fixture. One mutant was discarded before that: it died on a SyntaxError,
  which is a collection failure and not a test noticing anything. Gate
  green, 1310 tests.
  **Layman:** Hide a project while a scan is running and your change is thrown away without warning - the app says it saved it.
  Kind: fix.
  Source: review-code 2026-09-01 lane 12.

- ✅ [LWSM-1200] **HIGH: the window minimum is measured once, so content is clipped at 200% with no scrollbar.**
  mainwindow.py:2828. _align_columns is deliberately re-run on LanguageChange
  and FontChange because those change what a cell needs; _apply_default_geometry
  is one-shot. An explicit minimumSize overrides minimumSizeHint and
  apply_column_widths sets FIXED widths, so the rows outgrow the floor the
  window still holds - and horizontal scrolling is ScrollBarAlwaysOff, so the
  overflow is unreachable. Breaks design-accessibility.md's "must reflow at
  every step, never clip". Fix: split the floor calculation out of
  _apply_default_geometry and call it from both changeEvent branches beside
  _align_columns; keep the one-shot guard on the resize alone.
  Resolved (2026-09-02). Reproduced with numbers: at 200 % the rows needed
  801 px against a 461 px viewport, with the floor still reading 495.
  Fixed as the bullet prescribed - `_content_metrics` and
  `_apply_size_floor` split out, called from both `changeEvent` arms, the
  one-shot guard left on the resize alone.
  TWO measurements changed the design, neither of them in the bullet.
  First, MY OWN first assertion was vacuous: the scroll area is
  `widgetResizable`, so `host.width() >= host.sizeHint().width()` is true
  whether or not anything is clipped, and it passed against the defect.
  The observable is the VIEWPORT. Second, the floor cannot be recomputed
  SYNCHRONOUSLY: `apply_column_widths` sets fixed widths and the layout
  does not recompute its hint until the posted `LayoutRequest` is
  delivered, so a translation read the old 422 px where the settled value
  was 937 and the floor did not move. Hence `_schedule_size_floor` and a
  zero-timer. The FontChange arm happened to work synchronously, which is
  exactly how the LanguageChange arm would have shipped broken.
  A mutant is what found that: deleting the re-floor from FontChange
  reddened the suite and deleting it from LanguageChange did not. Rather
  than report the survivor, the arm now has a test - a padding translator
  widening every label, which is the real mechanism and not a contrivance.
  Asserted at 150 %, not 200 %: the offscreen screen is 800 px and 200 %
  needs 801, so ADR-0007's clamp would decide the result instead of the
  mechanism. 3/3 mutants killed, including the deferral itself. Gate
  green, 1312 tests.
  **Layman:** Turn the text size up and the rows get wider than the window will allow, with no way to scroll across to them.
  Kind: accessibility.
  Source: review-code 2026-09-01 lane 13.

- ✅ [LWSM-1201] **HIGH: only the effective port is probed, so a port override lets Start spawn a duplicate server.**
  controller.py:959. ADR-0004 rule 3 is explicit that the declared port is
  probed as well as the effective one whenever they differ, and spells out
  this exact consequence: "the whole running (wrong port) case evaporates...
  then Start would cheerfully spawn a duplicate". registry.py:121 makes
  effective_port the override when set, so the declared port goes unprobed.
  Both come from the same snapshot, so the ADR notes the fix costs nothing
  extra. Return the wrong-port state when only the declared one is bound.
  Resolved (2026-09-02). Reproduced exactly as filed and as ADR-0004
  predicts: override 5999, declared 5005 held, status came back `stopped`.
  The bullet asks to "return the wrong-port state", and THAT STATE DOES
  NOT EXIST YET - `ProjectStatus` has five members and `running (wrong
  port)` is one of the four P06's model adds (LWSM-1011). Inventing it
  here would be that item. So the fix is the probe alone: `running` if
  EITHER port is held, `stopped` only if neither is. That is true at
  today's granularity and it is what stops the duplicate, which is the
  harm the ADR names. Which port is held stays P06's distinction.
  Two mutants SURVIVED and both are equivalent by construction, recorded
  rather than cleared with a fixture: dropping `declared != port` cannot
  change the outcome, because reaching that line means the effective port
  is unbound and an equal declared port is the same number; and dropping
  `declared is not None` is safe because `is_bound(None)` is
  `None in frozenset[int]`, which is False rather than an error. Both
  guards state intent, not behaviour. A third mutant was inert - a wrong
  anchor, no evidence either way - and re-run correctly it was killed.
  Gate green, 1313 tests.
  **Layman:** If you override a project's port but the project ignores it, the app thinks nothing is running and starts a second copy.
  Kind: fix.
  Source: review-code 2026-09-01 lane 5.

- ✅ [LWSM-1202] **HIGH: starting a second project erases the first one's starting overlay, with nothing to derive it back.**
  controller.py:652. The overlay is one slot by design (design.md covers
  "exactly one project"). Start A then Start B and A renders `stopped` while
  its child is alive and still binding, with Start enabled - pressing it gives
  an AlreadyRunning refusal. There is no derived value to fall back to because
  `starting` exists ONLY as an overlay (see the missing-states item). Two
  servers is the app's whole premise, so this is a common path. Fix: derive
  `starting` from the supervisor's live-child-with-no-bound-port fact.
  Resolved (2026-09-02). Reproduced as filed. Took the bullet's own fix -
  derive `starting` - rather than a second overlay slot, and the reason is
  worth keeping: `design.md § State management` says the overlay "covers
  exactly one project" deliberately, so widening it would have changed a
  contract to fix a symptom. ADR-0004 already lists `starting` among its
  SEVEN DERIVED states ("live child, effective port held by nobody, child
  holds no port"), so this implements a rule that was already written
  rather than inventing a state - which is what keeps it out of P06.
  Ordering is load-bearing and follows the ADR: the two port questions run
  first, because a live child while someone else holds the port is
  `failed` or `running (wrong port)`, never `starting`. LWSM-1201 reports
  both of those as `running` one line earlier, so the `starting` branch is
  reached only on the ADR's own row. No deadline, so § Slowness is not
  failure is untouched - losing the child ends it, not a timer.
  It also corrected a fixture I widened for LWSM-1197 hours earlier:
  marking every keyboard-test project as ours was too broad, because a
  live child on an unbound port now derives `starting` and disables Start.
  Ownership is per test now, and both directions are stated. 3/3 mutants
  killed. Gate green, 1314 tests.
  **Layman:** Start two servers at once and the first one goes back to looking stopped while it is still coming up.
  Kind: fix.
  Source: review-code 2026-09-01 lane 5.

- ✅ [LWSM-1203] **HIGH: a failed port probe freezes every row with plausible data and emits nothing.**
  controller.py:931. _on_probe_error holds the previous statuses (correct,
  INV-4b), logs, then calls self._maybe_emit(self._statuses) - passing the SAME
  object it compares against, so `previous != self._statuses` is always false
  and no signal is ever emitted. Under hidepid=2, an LSM, or a /proc-less
  container the whole display is stale for the session with only app.log as
  evidence. design.md forbids this outright: "Every failure has a visible
  home... Nothing is swallowed." Fix: emit an app-scoped failure on the first
  failure and on recovery, reusing the existing _last_error suppression.
  Resolved (2026-09-02). Reproduced: a probe failure AFTER the first poll
  was logged and reached nobody. Fixed as the bullet asks - an app-scoped
  report on the first failure and on recovery, behind the existing
  `_last_error` suppression so a permanent failure does not write a status
  bar nobody can read (LWSM-1079's reason, one surface along). Emitted
  with no path, which `_report_failure` already routes to the status bar
  rather than to a row: an unreadable socket table is a fact about the
  table, not about one project.
  ONE CORRECTION TO THE BULLET, found by breaking four tests. It says
  `_maybe_emit(self._statuses)` "is always false and no signal is ever
  emitted", and the first half is right while the second is not: that call
  also carries the FIRST-POLL branch, which emits unconditionally so a
  window whose first poll fails does not sit blank for ever. Removing the
  call - which the bullet's wording invites - broke
  `test_a_failing_first_poll_still_emits` and three others. It is restored,
  with the reason written where the next reader will be tempted again. The
  comparison being self-referential is deliberate: nothing derived HAS
  changed, which is INV-4b. 5/5 mutants killed, including reporting every
  repeat, announcing recovery on every good poll, and attaching the
  failure to a row. Gate green, 1315 tests.
  **Layman:** If the app loses the ability to see which ports are busy, the screen keeps showing the last answer and never tells you it has stopped looking.
  Kind: fix.
  Source: review-code 2026-09-01 lane 5.

- ✅ [LWSM-1204] **HIGH: the process group is enumerated once, so a process forked during the grace window is never signalled.**
  supervisor.py:802, reused at :811 and :821. A process forked into the group
  DURING the grace window - a trap handler that respawns, an npm run dev
  watcher, a node cluster replacing a worker - is in no list, gets neither
  SIGTERM nor SIGKILL, survives holding the port, and StopOutcome comes back
  clean. ADR-0003 calls stopping the whole tree "the single most important
  correctness property of the Stop button", and its own killpg-per-phase
  prescription does not have this hole. NOT the CLAUDE.md start-race trap:
  this fires after a healthy poll. Fix: re-enumerate before escalating and
  again after the kill wait; report survivors in StopOutcome.warning.
  Resolved (2026-09-02). Reproduced with a launcher whose SIGTERM trap
  backgrounds a new process into the group and exits: the newcomer got
  neither signal, outlived the stop, and StopOutcome came back clean.
  Fixed as the bullet asks - re-enumerate before escalating and again
  after the kill wait, with survivors named in `warning`.
  UNPLANNED RESULT WORTH THE NEXT READER'S TIME: this also closes
  LWSM-1189's process leak. Measured on the supervisor suite, exact
  pattern, fix stashed and restored: 2 leaked `sleep 30` WITHOUT it and 0
  WITH it, which matches that item's "two tests leave one each, every
  run". Those leaks were the same defect seen from the test side - a
  grandchild forked around the stop that the single enumeration could not
  see. LWSM-1189 is flipped separately rather than folded in here.
  Two mutants SURVIVED the first run and both were the straggler REPORT,
  not the enumeration - a real gap rather than equivalence, so the report
  now has its own test. It drives `_group_members` through a seam, because
  a straggler is by definition something SIGKILL did not remove and
  SIGKILL cannot be blocked; the enumeration itself is tested beside it
  with a real child. 3/3 killed after that. Gate green, 1317 tests.
  **Layman:** Stop can leave a server running and still report success, if the thing it is stopping starts a new process while being asked to quit.
  Kind: fix.
  Source: review-code 2026-09-01 lane 4.

- ✅ [LWSM-1205] **HIGH: ADR-0005's duplicate-port Start refusal has no channel to reach Start, so two projects both start.**
  registry.py:1070. ADR-0005:68 promises every later claimant is flagged AND
  "its Start is refused with that message". Only the flag half exists: the
  report entry dies in registry.py, LWSM-1007 4.2 persists no merge outcome,
  LWSM-1131 4.4 renders no per-row flag, and nothing reads DUPLICATE_PORT
  outside registry.py. The only Start-time port check is supervisor.py:670's
  LIVE-SOCKET probe, which fires only if the other project is currently
  running - precisely not the state the rule is about. Structurally
  unimplementable as designed. Decide it either way: derive the claim at Start
  time from records the controller already holds, or amend ADR-0005.
  Resolved (2026-09-02). The bullet asks to decide it either way -
  implement the refusal, or amend ADR-0005. DECIDED: implement it. The
  ADR's rule is sound and specific (two projects configured on one port is
  a real misconfiguration with a stated tie-break), and amending it would
  have weakened a promise for no reason beyond its never having been
  wired up. Amending would also have re-armed rule 14's gate.
  Reproduced as filed: the later claimant started with no refusal at all.
  Fixed by deriving the claim at Start time from the records the
  controller already holds - the bullet's first option.
  The tie-break is NOT reimplemented. `_flag_duplicate_ports` already
  encoded it, so the rule moved into a public `registry.port_claims` that
  both callers use: a second copy is how the message a user is refused
  with and the message the rescan report shows would come to disagree
  about who won (`coding.md § 1.3`). The merge report's wording and
  ordering are unchanged, which the registry tests pin.
  Checked in the controller rather than in the supervisor deliberately.
  The supervisor's pre-flight probes the LIVE SOCKET, so it fires only
  when the other project is already running - precisely not the state this
  rule is about. Two projects configured on one port, neither running, is
  the ADR's case, and the records are the only evidence for it.
  3/3 mutants killed, including refusing the winner too and reporting
  without stopping the spawn. Gate green, 1320 tests.
  **Layman:** Two projects set to the same port are supposed to refuse to start; the warning is produced and then thrown away.
  Kind: fix.
  Source: review-code 2026-09-01 lane 2.

- ✅ [LWSM-1206] **HIGH: the 24x24 target floor is applied to two of the settings dialog's seven focusable controls.**
  settingsdialog.py:96-102. The floor covers _add and _remove only. Ok/Cancel
  (via self._buttons) and both spinboxes get none. LWSM-1032 already measured
  25px here against 22px on the CI runner, so on any machine with a smaller
  font the two most important controls in the dialog are under the floor.
  Ask box.button(StandardButton.Ok), never the box - QDialogButtonBox's own
  focusPolicy is NoFocus, which is the CLAUDE.md container trap.
  Resolved (2026-09-02). Reproduced as filed, and the numbers are the
  bullet's own argument: at a 6 pt system font the two spinboxes measured
  23 px and Ok and Cancel 19 px, against a floor of 24 - while the ambient
  font on this machine passed. That is LWSM-1032 exactly, one dialog
  along, which is why the test is PARAMETRISED over the font rather than
  trusting the one the runner happens to have.
  Ok and Cancel are asked individually and the floor is set on each
  button, never on `self._buttons` - the container trap the bullet names
  and `keyboard_focus_order` already records for focus. A mutant setting
  it on the box is killed.
  `_roots` is deliberately not in the set: it is a list several hundred
  pixels tall, and a 24 px floor under it asserts nothing.
  3/4 mutants killed. The survivor is the WIDTH floor, which no test can
  see because all four controls are far wider than 24 px anyway (256 for
  the spinboxes, 80 for the buttons). Kept for symmetry with the Add and
  Remove pair above it and with the standard's "24x24" wording, and
  recorded here as unmeasured rather than dropped or dressed up with a
  fixture. Gate green, 1319 tests.
  **Layman:** The OK and Cancel buttons can be too small to click comfortably on machines with a smaller default font.
  Kind: accessibility.
  Source: review-code 2026-09-01 lane 6.

- ✅ [LWSM-1207] **HIGH: selected-text contrast fails WCAG AA in four of eight palettes, and no check looks at the pair.**
  theme.py:179. Highlight <- accent with HighlightedText <- base gives ledger
  3.37:1, mint 3.49:1, parchment 3.73:1, graphite 4.18:1, against the 4.5:1
  floor design-accessibility.md:161 and testing.md T8 both state. This is LIVE
  text - Qt paints selected text with it, including the filter QLineEdit.
  Arithmetic recomputed by hand from the WCAG formula (anchor: #767676 on
  white = 4.54:1, the published value). derive_state_tokens.py:114 checks
  accent against theme.window ONLY, so neither the tool nor its shortfall
  report can see this pair. Fix BOTH: add ("base","accent") to the shortfall
  loop, then darken the four accents or set HighlightedText per palette.
  Resolved (2026-09-02). The bullet's arithmetic reproduced EXACTLY -
  ledger 3.37, parchment 3.73, mint 3.49, graphite 4.18 - and both halves
  of its fix were needed.
  Took "darken the four accents" over "set HighlightedText per palette",
  after measuring that neither existing token can carry it: the best of
  `base` and `text` against the current accent is 4.26 (ledger), 3.73
  (parchment), 4.03 (mint), 4.18 (graphite), all still short. So a
  per-palette HighlightedText would have needed a NEW token in all eight
  palettes to fix four.
  The new accents are SOLVED, not chosen - the method `derive_state_tokens`
  already uses: walk lightness away from the surface, hue and saturation
  untouched, stop at the first value clearing the floor. Graphite's got
  LIGHTER, not darker, because it is the dark palette; the bullet's
  "darken the four" is right for three of them. accent/window stays above
  the indicator floor on all four (4.02-4.20).
  The tool's blind spot is closed too, and PROVEN to fire rather than
  assumed: run against the old accents it reports the four shortfalls by
  name and the exact ratios; against the new ones, zero.
  A mutant then found a second gap and it is the LWSM-1031 trap one token
  along: an accent solved for contrast ALONE converges on black or white,
  so replacing ledger's with #000000 cleared every ratio and survived the
  whole suite. `test_the_accent_still_carries_a_hue` holds it on
  saturation, which is the property contrast cannot express. 5/5 mutants
  killed after that. Gate green, 1336 tests.
  **Layman:** Highlighted text is too faint to read in half the colour themes, and the tool that checks contrast never looks at that combination.
  Kind: accessibility.
  Source: review-code 2026-09-01 lane 8.

- ✅ [LWSM-1208] **HIGH: CONTRIBUTING.md step 5 is wrong three ways and re-enables the 2026-08-19 red-CI incident.**
  CONTRIBUTING.md:59-63. (a) "a green run locally is a green run in CI" is
  precisely what the LWSM_REQUIRE_ALL_TOOLS split exists to DENY - a hand run
  treats SKIP and TOOL DRIFT as warnings and still prints "Local CI passed".
  (b) "A docs-only change is exempt" omits the .githooks/pre-push:54 carve-out
  for CLAUDE.md, README.md and docs/standards/*.md, so a contributor editing a
  standard follows this sentence, skips the gate and reddens CI - the measured
  2026-08-19 incident, re-enabled by the doc. (c) it never mentions
  `git config core.hooksPath .githooks`, which is the enforcement mechanism.
  Document side is wrong, not the code.
  Resolved (2026-09-02). All three claims confirmed against
  `.githooks/pre-push` and `local-ci.sh`, and step 5 is rewritten: the
  `core.hooksPath` command is given, the hand run is described as
  deliberately lenient with `LWSM_REQUIRE_ALL_TOOLS` named, and the
  exemption carries its carve-out for `CLAUDE.md`, `README.md` and
  `docs/standards/` plus the never-exempt code paths.
  The bullet says the document side is wrong and not the code, which is
  right - so the fix went further only in one direction: a test in
  `test_ci_contract.py`, where the hook's other contract assertions live,
  so a change to the CARVE-OUT that is not mirrored in the doc now
  reddens the gate. `GOVERNED` is imported rather than restated, for the
  sibling test's reason.
  MY FIRST VERSION OF THAT TEST WAS WORTHLESS AND MUTANTS PROVED IT. It
  asserted `"core.hooksPath" in text` and `"docs/standards/" in text`, and
  BOTH pass against a document with the instruction and the carve-out
  deleted - the token appears in the sentence explaining it, and
  `docs/standards/` appears in steps 2 to 4 citing the standards. The
  assertions are now the exact command, and the carve-out is scoped to the
  exemption's own paragraph. 4/4 mutants killed after that, 2/4 before.
  Rule 14 was applied and CONTRIBUTING.md is OUT of scope: nothing is
  built from it, and `verify-instructions` names it by name as a document
  whose review is to execute its steps. Gate green, 1337 tests.
  **Layman:** The instructions we give contributors tell them to skip a check they must not skip.
  Kind: doc-fix.
  Source: review-code 2026-09-01 lane 14.

- ✅ [LWSM-1209] **HIGH: the desktop entry writes Exec= unquoted and through an unescaped sed replacement.**
  scripts/install-desktop-entry.sh:53-55. The resolved path goes into Exec=
  raw, against the Desktop Entry Spec's quoting requirement, so a checkout
  under "/home/u/My Projects/..." yields an Exec the launcher splits into two
  argv words - the entry appears and fails to start, the exact failure the
  file's own header says it prevents. desktop-file-validate PASSES it. Second
  failure on the same line: $exec_path is interpolated into a sed REPLACEMENT,
  where & expands to the whole match and | terminates the s-command. Fix: emit
  with awk -v or a heredoc, and write Exec="<escaped>" escaping " ` $ and
  backslash per the spec. TryExec is a path, not a command line - leave it
  unquoted.
  Resolved (2026-09-02). Both defects reproduced before any design, with
  the exact outputs the bullet predicts: `a&b` wrote
  `Exec=/home/u/aExec=lwsmb/lwsm` because `&` is the whole match in a sed
  replacement, `pipe|x` made sed exit non-zero, and a path with a space
  went in unquoted. The script had NO test file at all; there is one now,
  and it RUNS the installer against seven path shapes rather than reading
  it - `desktop-file-validate` passes the unquoted form, so a text
  assertion would have agreed with the defect.
  ONE THING THE BULLET DID NOT SAY, and the validator taught it: the spec
  has TWO escaping layers, not one. The quoting rule reserves `"`,
  backtick, `$` and backslash inside a quoted argument, and the
  string-value rule then escapes the backslashes that produced - so a
  literal backslash is FOUR in the file. A single pass wrote
  `Exec="...back\\slash..."` and `desktop-file-validate` REJECTED it as an
  unclosed quote. Both layers are applied now, in that order.
  `awk` via ENVIRON rather than the bullet's `awk -v`, which processes
  backslash escapes in the value and would have reintroduced the same
  class one tool along. TryExec stays unquoted, as the bullet says: it is
  a path compared against the filesystem, and a mutant quoting it is
  killed. 4/4 mutants killed. Gate green, 1346 tests.
  **Layman:** Install the app from a folder whose name has a space in it and the launcher entry appears but will not start.
  Kind: fix.
  Source: review-code 2026-09-01 lane 14.

- ✅ [LWSM-1210] **MEDIUM: RescanContext is built with projects_path=None when there is no home directory.**
  __main__.py:257. On the branch where default_projects_path() raises,
  projects_path is still None and the dataclass does not check. Because
  _rescan is not None, File > Export/Import are created too. Contradicts the
  rule at mainwindow.py:1116. Fix: rescan=None if projects_path is None.
  Resolved (2026-09-02). Reproduced exactly: with no home directory the
  window held `RescanContext(projects_path=None, roots=())`, inside a
  field typed `Path`. Fixed as the bullet prescribes - no path, no
  context - which is the answer this file already gives for the log, the
  theme and the project list on that machine.
  One correction, and it is about the bullet's CITATION rather than its
  claim: "the rule at mainwindow.py:1116" points at LWSM-1141's
  accessibility comment, not at any rule about the rescan path. The line
  has drifted. The claim itself is right, and the rule it means is the
  window's own - a control it cannot honour is not offered - so the test
  asserts on the button as well as on the attribute. Line numbers in a
  fold-in age; the claim is what to check.
  2/2 mutants killed, including never building a context at all. Gate
  green, 1347 tests.
  **Layman:** On a machine with no home folder the Rescan and Import buttons appear but crash when used.
  Kind: fix.
  Source: review-code 2026-09-01 lane 1.

- 📋 [LWSM-1211] **MEDIUM: the shutdown finally runs three unguarded statements, so one failure defeats the other two.**
  __main__.py:562-569. controller.stop() / close_supervisor() / window.shutdown()
  in one finally. If stop() raises, shutdown() never runs and the rescan pool
  falls to ~QThreadPool's unbounded join - the LWSM-1100/1139 hazard the block
  exists to prevent. Fix: guard each, or ExitStack.
  **Layman:** If the first cleanup step fails on quit, the other two never run and a background thread can outlive the app.
  Kind: fix.
  Source: review-code 2026-09-01 lane 1.

- 📋 [LWSM-1212] **MEDIUM: a settings write failure silently skips the healthy scan-roots write.**
  __main__.py:230-231. Two independent files in one try. save_field raises
  routinely (any malformed settings.json sets document_refused). The roots are
  applied in memory and absent next launch. Fix: two try blocks, collect both
  failures, report both paths.
  **Layman:** If preferences cannot be saved, the folder list you just edited is dropped too, and the error only mentions preferences.
  Kind: fix.
  Source: review-code 2026-09-01 lane 1.

- 📋 [LWSM-1213] **MEDIUM: an empty scan-roots list means two different things on read and on write.**
  __main__.py:476-477 reads empty as "scan ~/projects"; save_scan_roots(())
  writes header-only and set_scan_roots(()) sets roots=() literally. So a
  restart can re-add the very projects the user cleared the roots to exclude.
  Fix: pass the resolved default to set_scan_roots, or give the dialog an
  explicit use-the-default state.
  **Layman:** Clear every scan folder and the app scans nothing now, but silently goes back to the default folder after a restart.
  Kind: fix.
  Source: review-code 2026-09-01 lane 1.

- 📋 [LWSM-1214] **MEDIUM: design.md says two config files and puts scan roots in the wrong one.**
  docs/design.md:766,774. Section Persistence says two files under XDG paths
  and puts scan roots in settings.json; the code keeps them in a third file,
  scan-roots, in its own line-based format with no schema_version - while the
  section says both files are version-checked. DOCUMENT side wrong (the split
  was settled with the user 2026-08-21). Route to review-contract.
  **Layman:** The design document describes where settings live and it does not match what the app actually does.
  Kind: doc-fix.
  Source: review-code 2026-09-01 lane 1.

- 📋 [LWSM-1215] **MEDIUM: export_profile gates on row refusals, so a bad user field exports as null and later erases a good one.**
  registry.py:1115. A hand-typed "port_override": "8080" is dropped with
  rows_refused == 0, export succeeds, the profile carries null, it re-loads
  cleanly so the window's refuse-any-refusal gate passes it, and
  _user_half_applied writes the null over a good stored override. A dropped
  ROW is visibly absent; a nulled FIELD looks intentional. Fix: refuse the
  export when any reason names a USER_FIELDS member.
  **Layman:** A typo in one setting can quietly wipe that setting on every machine you import the profile to.
  Kind: fix.
  Source: review-code 2026-09-01 lane 2.

- 📋 [LWSM-1216] **MEDIUM: merge_imported appends an absent-counterpart profile record whole, detected half included.**
  registry.py:1221. Contradicts the rule stated 80 lines above at :1147 -
  "Nothing here touches DETECTED_FIELDS... this machine's own scan owns them."
  argv is the launch command. Fix: append with the detected half cleared
  (port=None, kind=None, argv=(), unit=None) and let a rescan derive it.
  **Layman:** Importing a profile can bring in a launch command for a project this machine has never scanned.
  Kind: fix.
  Source: review-code 2026-09-01 lane 2.

- 📋 [LWSM-1217] **MEDIUM: _actions_or_reason is missing the RecursionError guard its sibling call site has.**
  registry.py:306 catches (TypeError, ValueError). load_projects:375 catches
  (ValueError, RecursionError) with a comment explaining at length that
  RecursionError is not a ValueError and needs naming. The guard was fixed at
  one call site and not this one. json.dumps runs three frames deeper than
  json.loads, so a document that cleared the load can exceed it here; the
  escape reaches a caller that tolerates only RegistryError - LWSM-1108's
  exact shape at a new call site. Fix: add RecursionError.
  **Layman:** A deeply nested project file can kill the app at startup with no window and no message.
  Kind: fix.
  Source: review-code 2026-09-01 lane 2.

- 📋 [LWSM-1218] **MEDIUM: schema v1 strips unknown keys, so an older build silently destroys the browser field.**
  registry.py:583-599 with SCHEMA_VERSION = 1. The writer emits a fixed key
  set and the loader drops unknown keys, so any field added INSIDE v1 is
  stripped. browser was added by LWSM-1187 with no bump (correctly, per
  LWSM-1007 INV-5). Same on a profile round-tripped through an older build.
  Fix: carry unrecognised keys per record in an opaque field and re-emit them.
  **Layman:** Run an older version of the app once and every per-project browser choice is deleted without warning.
  Kind: fix.
  Source: review-code 2026-09-01 lane 2.

- 📋 [LWSM-1219] **MEDIUM: override differs fires only when the detected port moves, so a stale override is announced once.**
  registry.py:968. ADR-0005:104 states the mitigation for its own accepted
  negative as the flag that makes it visible ON EVERY RESCAN. Document is
  probably the wrong side (ADR-0005:55 and LWSM-1131 4.3's table both say "the
  field that moved"), but the hazard the ADR accepted is unmitigated either
  way. Decide which side, then fix it.
  **Layman:** A port override that no longer matches what was detected is mentioned once and then never again.
  Kind: fix.
  Source: review-code 2026-09-01 lane 2.

- 📋 [LWSM-1220] **MEDIUM: a scan budget expiry inside the import walk is swallowed and reported as an honest unknown.**
  scanner.py:775. `if hops >= MAX_IMPORT_HOPS or deadline.expired(): return None`.
  Spec 4.3 requires expiry to ABANDON the candidate - not listed, no partial
  port. Inconsistent with itself: expiry noticed two lines later inside
  _read_lines propagates correctly via _BudgetExpired. LWSM-1007 is about to
  persist that fabricated unknown. Fix: split the conditions - expiry raises,
  hop exhaustion returns None.
  **Layman:** When a scan runs out of time mid-project it lists that project as "port unknown" instead of admitting it never finished.
  Kind: fix.
  Source: review-code 2026-09-01 lane 3.

- 📋 [LWSM-1221] **MEDIUM: an unguarded is_symlink drops a whole project when a hop target is unreadable.**
  scanner.py:675, and the same class at :605 and :1193. On Python 3.13
  _IGNORED_ERRNOS swallows only ENOENT/ENOTDIR/EBADF/ELOOP - EACCES and
  ENAMETOOLONG are RE-RAISED. Path.resolve() above it is non-strict and
  swallows, so is_symlink() is the first call that can raise, and nothing
  catches it before scan()'s per-candidate handler drops the project. Spec 4.3
  requires the project stay listed with only the port unknown. This is the
  project's own measured pathlib trap at a fifth call site - contain per item.
  **Layman:** One folder the app is not allowed to open makes a working project vanish from the list entirely.
  Kind: fix.
  Source: review-code 2026-09-01 lane 3.

- 📋 [LWSM-1222] **MEDIUM: rule 1 re-slices the whole line prefix per rejected match, which is quadratic on untrusted input.**
  scanner.py:478. finditer means every REJECTED match re-slices line[:start]
  and _declaration_position runs seven rfind scans over it. A 4096-char line of
  repeated ".PORT=1 " gives ~512 rejected matches, ~7M char operations and 1MB
  of copying per line, with no deadline check between lines. INV-15 asserts
  linearity for rule_2 only and predates the LWSM-1190 position rule. Fix:
  scan backwards from match.start() to the nearest separator; add a rule_1
  case to INV-15.
  **Layman:** A long, awkward line in someone else's file can make a scan take far longer than it should.
  Kind: perf.
  Source: review-code 2026-09-01 lane 3.

- 📋 [LWSM-1223] **MEDIUM: the invocation walk checks the deadline nowhere in its own loops.**
  scanner.py:829. Every keyword-bearing line is tokenised and every token pays
  a Path.resolve() plus an os.open() attempt; the only deadline check on that
  path is inside _read_lines, never reached when the token names nothing. A
  256KB start.sh of `node a` lines is ~74,000 syscalls for one candidate, with
  the 20s budget re-checked only at the NEXT candidate - the failure spec 4.2
  names. _import_hop_port already checks per specifier. Fix: check at the top
  of the per-line loop.
  **Layman:** A very large launcher script can hold up a scan well past its time limit.
  Kind: fix.
  Source: review-code 2026-09-01 lane 3.

- 📋 [LWSM-1224] **MEDIUM: signal failures are logged at INFO and dropped from the stop outcome.**
  supervisor.py:808-809, :818-819, and :820-821 where the escalation's return
  value - the processes still alive AFTER SIGKILL - is discarded entirely.
  design.md: "nothing is reported as success that was not verified."
  StopOutcome.warning exists and is populated only for the port case. Fix:
  collect unsignalled and surviving pids into warning.
  **Layman:** If the app cannot signal part of a server, Stop still reports a clean success.
  Kind: fix.
  Source: review-code 2026-09-01 lane 4.

- 📋 [LWSM-1225] **MEDIUM: the port-still-bound message asserts a stranger owns it without checking.**
  supervisor.py:972-975. Nothing calls owns_pid or re-reads the group before
  saying it; combined with LWSM-1205 the holder can be our own unsignalled
  grandchild. design.md requires the opposite for this surface: say the port
  is held by a process the user cannot inspect, rather than inventing an owner.
  Fix: reword, or check the holder's pgid first.
  **Layman:** The app tells you another program is holding the port when it may well be a leftover of its own.
  Kind: fix.
  Source: review-code 2026-09-01 lane 4.

- 📋 [LWSM-1226] **MEDIUM: the group-writable launcher refusal covers the file but not its parent directory.**
  supervisor.py:345. Checks S_IWGRP|S_IWOTH on the file only; a launcher in a
  group-writable directory can be replaced by unlink-and-create, defeating the
  refusal whose docstring says "whoever else can write it changes what they
  vouched for afterwards". Ownership is not checked either. ADR-0003 Trust has
  the same gap, so the DOCUMENT needs the same fix. Fix: refuse a group/other-
  writable parent without the sticky bit, and a st_uid that is neither ours nor 0.
  **Layman:** A launcher in a folder other people can write to can be swapped after you approved it.
  Kind: security.
  Source: review-code 2026-09-01 lane 4.

- 📋 [LWSM-1227] **MEDIUM: the launcher byte cap truncates instead of refusing, so appended content never re-arms trust.**
  supervisor.py:438. os.read(fd, MAX_LAUNCHER_BYTES) truncates, so a launcher
  over 1MiB is fingerprinted on its first mebibyte and anything appended past
  that never re-arms the gate ADR-0003 says re-arms "whenever the launcher
  command or its content hash changes". Diverges from scanner.py's three-place
  REFUSE discipline. Fix: read cap+1 and refuse, or mix st_size and an
  oversize marker into the digest.
  **Layman:** A very large launcher can be changed after you trusted it without the app noticing.
  Kind: security.
  Source: review-code 2026-09-01 lane 4.

- 📋 [LWSM-1228] **MEDIUM: an argv of three or more elements names no launcher, so it skips validate_launcher entirely.**
  supervisor.py:290-292. Anything that is not `npm run <name>` and is not
  length 2 returns None, so start() at :672-674 never calls validate_launcher.
  ("python3","-m","http.server"), ("env","node","serve.mjs") and
  ("bash","-x","start.sh") skip the containment AND group-writable refusals
  that LauncherRefused's docstring says "cannot be confirmed away". The scanner
  emits only the four handled shapes, but a record is hand-editable and
  LWSM-1148 makes it importable from a profile. Fix: classify the last argv
  element resolving to a file inside the project, or refuse unknown shapes.
  **Layman:** Some ways of writing a start command bypass the safety checks on what is about to run.
  Kind: security.
  Source: review-code 2026-09-01 lane 4.

- 📋 [LWSM-1229] **MEDIUM: the log rotation backup is the one open in supervisor.py not hardened like the others.**
  supervisor.py:599-603. O_WRONLY|O_CREAT|O_TRUNC|O_NOFOLLOW with no
  O_NONBLOCK and no S_ISREG check, while _open_log (:557) and _launcher_bytes
  (:432) both have them. O_NOFOLLOW does not stop a FIFO, so one planted at
  <log>.1 makes os.open block FOREVER on the poll thread - the hazard
  configfile.py and applog.py were written after measuring. Also the module's
  only diverged-duplication instance. Fix: add O_NONBLOCK + the S_ISREG/link
  check, then set_blocking(out, True).
  **Layman:** A booby-trapped file where the old log goes can freeze the app's status updates forever.
  Kind: fix.
  Source: review-code 2026-09-01 lane 4.

- 📋 [LWSM-1230] **MEDIUM: four of ADR-0004's seven derived states are absent from ProjectStatus.**
  controller.py:183-195. Missing: running (wrong port), running (foreign),
  port blocked, failed. ADR-0004 calls its list "exhaustive for states derived
  from observation". A stranger holding the port derives running where the ADR
  requires port blocked with Start refused; a child that exits without binding
  derives stopped where both ADR-0004 and design.md require failed with the log
  tail. CALIBRATED DOWN from the lane's HIGH: this is P06/LWSM-1011 scope, not
  a regression. Also: ProjectStatus.UNKNOWN appears in no row of ADR-0004's
  table - a doc-side gap worth settling with it.
  **Layman:** The app can only say running, stopped or unknown, where the design calls for seven distinct states.
  Kind: feature.
  Source: review-code 2026-09-01 lane 5 (calibrated HIGH -> MEDIUM: P06 scope).

- 📋 [LWSM-1231] **MEDIUM: the managed flag survives a probe outage, so Open can point at a stranger's server.**
  controller.py:851. _managed is recomputed only on a SUCCESSFUL snapshot, so
  it is held through an outage exactly as the statuses are. But managed gates
  Open-in-browser, and ADR-0004's stated safe direction is "a holder we cannot
  name is not ours". Combined with the frozen RUNNING status this is the
  localhost-credibility shape ADR-0004 was written to close, reached through
  staleness rather than chdir(). Fix: clear or mark-unverified in
  _on_probe_error.
  **Layman:** If the app loses track of who owns a port it keeps saying the server is ours, and Open still offers to visit it.
  Kind: fix.
  Source: review-code 2026-09-01 lane 5.

- 📋 [LWSM-1232] **MEDIUM: the port snapshot discards the listening address, so any interface counts as bound.**
  ports.py:104 keeps only conn.laddr.port. A process on 192.168.1.5:5000 makes
  is_bound(5000) true, so an unrelated project reads running and Open opens
  http://localhost:5000, which nothing answers. Separately at :111,
  holders.setdefault first-one-wins is justified by the dual-stack case and is
  false for two processes on one port at different addresses - the holder then
  depends on psutil's return order. Fix: key listening and holders on
  (ip, port) and answer for loopback and wildcard.
  **Layman:** A program listening on your network address makes an unrelated project look like it is running.
  Kind: fix.
  Source: review-code 2026-09-01 lane 5.

- 📋 [LWSM-1233] **MEDIUM: abandon_pool retains the pool but not the signaller the abandoned task still holds.**
  controller.py:76-77. _SnapshotTask keeps self._signals, which is
  _SnapshotSignals(self) - a CHILD of the controller. _ABANDONED defers the
  pool's destructor to interpreter shutdown, but if the controller is dropped
  first the signaller's C++ object is destroyed while a pool thread may be
  inside emit(). run()'s outer clause covers already-gone, not a destructor
  racing an in-progress emit. Fix: retain the signaller alongside the pool, or
  give an abandoned task a parentless signaller.
  **Layman:** A background check that was given up on can crash the app as it shuts down.
  Kind: fix.
  Source: review-code 2026-09-01 lane 5.

- 📋 [LWSM-1234] **MEDIUM: design.md's overlay rule contradicts its own next sentence.**
  docs/design.md:745-747 says the overlay is "discarded the moment a poll
  returns a derived state", and three lines later says "a slow start keeps the
  overlay until a poll disagrees". The first would drop a starting overlay on
  the very next tick, since an unbound server derives stopped.
  controller.py:205-208's _OVERLAY_SETTLES_ON implements the second. DOCUMENT
  side. Rewrite as "discarded when a poll reports the state the action was
  heading for". Route to review-contract.
  **Layman:** The design document gives two different answers about when a start/stop indicator disappears.
  Kind: doc-fix.
  Source: review-code 2026-09-01 lane 5.

- 📋 [LWSM-1235] **MEDIUM: a settings schema mismatch permanently blocks every future write.**
  settings.py:333-345 treats a version mismatch identically to unparsable
  text, and __main__.save_field turns document_refused into a PERMANENT write
  refusal. Three consequences: a hand-written file with no schema_version
  loses every value and blocks every save; a downgrade leaves the app unable to
  persist anything; and it makes the NEXT schema bump self-blocking, since
  every existing v1 file would be refused and no v2 could be written over it.
  No migration hook exists. Fix: separate "could not parse" from "parsed,
  version older" - migrate the second forward and keep the refusal only for a
  version NEWER than ours.
  **Layman:** One bad line in the preferences file can leave the app unable to save any preference ever again.
  Kind: fix.
  Source: review-code 2026-09-01 lane 6.

- 📋 [LWSM-1236] **MEDIUM: the config size cap is a caller obligation that two of four callers do not meet.**
  configfile.py:186-189 states the obligation; registry._encoded honours it,
  settings.save and __main__.save_scan_roots do not. Reachable on scan-roots:
  _leading_comment_block re-emits the user's whole leading comment block, which
  read_bounded accepts up to 1MiB, so header+body can cross the cap on write -
  after which the file is unreadable AND, by LWSM-1178's gate, can never be
  rewritten. Fix: enforce inside write_json_atomically, which holds the data.
  **Layman:** A long comment block in the scan-roots file can make it unwritable and unreadable at the same time.
  Kind: fix.
  Source: review-code 2026-09-01 lane 6.

- 📋 [LWSM-1237] **MEDIUM: the settings error clip removes the cause rather than the hostile input.**
  settings.py:433 clips str(exc) to 120 chars. The attacker-controlled
  fragment is already bounded by quoted(); the clip only eats the fixed
  diagnostic tail. Worked case on the default path: repr(path) is 55 chars and
  the fixed prefix is 60 - 115 of 120 - so on the directory-fsync branch the
  errno text is ALWAYS truncated away. Both sibling converters (registry.py:1127)
  pass it through unclipped. Fix: drop the slice.
  **Layman:** When saving preferences fails, the part of the message that says why is cut off.
  Kind: fix.
  Source: review-code 2026-09-01 lane 6.

- 📋 [LWSM-1238] **MEDIUM: no theme emits any focus styling, so the focus ring is whatever the platform gives.**
  theme.py:152-156. style_sheet() returns only QLabel[state=...] colour rules.
  design-accessibility.md requires "a thick, high-contrast focus ring on every
  focusable widget in every theme", and the check table lists it as a row
  LWSM-1032 lands. Related: focus_ring_color() returns accent, which is
  2.85:1 against alt_base in ledger - below the 3:1 non-text floor. Fix: emit
  a *:focus rule from style_sheet() and add a focus token to Theme.
  **Layman:** There is no visible outline showing which control the keyboard is on, in any colour theme.
  Kind: accessibility.
  Source: review-code 2026-09-01 lane 6+8.

- 📋 [LWSM-1239] **MEDIUM: on_wayland tests one environment variable, so a real Wayland session can take the X11 branch.**
  placement.py:194 tests XDG_SESSION_TYPE alone, which is routinely absent -
  the project's own conftest.py pins it because "the CI runner has it unset".
  A systemd --user unit or a shell that scrubbed the environment takes the
  else branch at :423, Wayland discards the move, and place_window RETURNS
  asked - reporting the placement as done. Verbatim the shape ADR-0007 calls
  "the worst possible failure shape". The code conforms to the ADR, so the
  ADR's test is not sufficient either - amend both. Fix: also accept
  WAYLAND_DISPLAY being set.
  **Layman:** On some Wayland setups the app moves the window, the system ignores it, and the app reports success anyway.
  Kind: fix.
  Source: review-code 2026-09-01 lane 7.

- 📋 [LWSM-1240] **MEDIUM: the D-Bus timeout is per call inside a three-call loop, giving a 9 second GUI block.**
  placement.py:46 and :365. The comment justifies the deadline as "a
  compositor that has wedged must not take the window with it", but 3.0s is
  per call across three iterations. An ABSENT service returns immediately
  (ServiceUnknown), so the slow case is precisely the wedged one the comment is
  for. Fix: compute one deadline and pass the remaining budget, or state 3x3s.
  **Layman:** If the window manager hangs, the app can freeze for nine seconds at startup instead of three.
  Kind: fix.
  Source: review-code 2026-09-01 lane 7.

- 📋 [LWSM-1241] **MEDIUM: the KWin script never calls clientArea, so centring ignores panels.**
  placement.py:269-288. ADR-0007 requires the target be "the centre of
  workspace.clientArea(workspace.PlacementArea, c) - the usable area, so it
  respects panels either way". The shipped script only assigns frameGeometry
  from numbers the app interpolated; the centre is computed app-side by
  centre_in. The one place that can ask KWin for the work area does not. Fix:
  let the script compute the centre when centring.
  **Layman:** Centre on screen can put the window under the taskbar instead of in the usable area.
  Kind: fix.
  Source: review-code 2026-09-01 lane 7.

- 📋 [LWSM-1242] **MEDIUM: the X11 placement branch applies the clamped position and drops the clamped size.**
  placement.py:417 and :423. The Wayland branch sends clamped width and height
  into the script; the X11 branch applies only the position. place_window's own
  docstring claims "one code path and one set of failure modes". ADR-0007
  requires a geometry larger than the display be clamped rather than restored
  off-screen. Fix: resize on the X11 branch, or state in the docstring that the
  caller must apply the returned size on every platform.
  **Layman:** A window remembered as bigger than the current screen is moved to fit but not resized to fit.
  Kind: fix.
  Source: review-code 2026-09-01 lane 7.

- 📋 [LWSM-1243] **MEDIUM: a partial KWin failure leaves the script registered while its file is deleted.**
  placement.py:350-375 returns False on the FIRST nonzero status, so a
  successful loadScript followed by a failing start leaves the script
  registered under the constant name lwsm_place while the finally deletes the
  file it was loaded from. KWIN_SCRIPT_NAME's comment asserts "it is unloaded
  in the same call", true only on the success path. The module's own measured
  note says unloadScript for an unregistered name exits 0, so unloading is
  nearly free. Fix: attempt the unload unconditionally in cleanup.
  **Layman:** If placing the window half-fails, a leftover registration stays inside the window manager.
  Kind: fix.
  Source: review-code 2026-09-01 lane 7.

- 📋 [LWSM-1244] **MEDIUM: Follow system is documented in two places and implemented nowhere.**
  theme.py:199 / design-look-and-feel.md:67-71, which also promises it switches
  to contrast-dark or contrast-light when the desktop reports a high-contrast
  preference. Grep: follow.?system appears ONLY in two theme.py docstrings.
  _build_theme_menu iterates THEMES, so the picker has exactly eight entries.
  Consequence on the stated primary user: a high-contrast desktop opens
  midnight on first run with no signal the assistive palettes exist.
  CALIBRATED DOWN from the lane's HIGH - an unbuilt promise, not a broken
  mechanism. Deleting the promise is a legitimate fix; decide which.
  **Layman:** The look-and-feel doc promises a theme that follows your desktop's light/dark and high-contrast setting; it does not exist.
  Kind: feature.
  Source: review-code 2026-09-01 lane 8 (calibrated HIGH -> MEDIUM: unbuilt promise).

- 📋 [LWSM-1245] **MEDIUM: the shipped high-contrast theme ids do not match the ids every document gives.**
  theme.py:340,362 ship highcontrast-light and highcontrast-dark;
  design-look-and-feel.md:64-65 and design-accessibility.md:108,212 all say
  contrast-light and contrast-dark. The id is what is persisted in
  settings.json, and theme_for_id falls back silently, so a user who hand-edits
  to the documented id gets midnight with no error, no log line and no status
  message. CODE side is right - the ids are shipped and stored, so renaming
  them breaks live settings files. Fix the DOCUMENTS. Route to review-contract.
  **Layman:** Follow the docs to set a high-contrast theme by hand and you silently get the default one instead.
  Kind: doc-fix.
  Source: review-code 2026-09-01 lane 8.

- 📋 [LWSM-1246] **MEDIUM: derive_state_tokens prints a colour that failed the floor in the exact format of one that passed.**
  scripts/derive_state_tokens.py:90. When no lightness clears the floor, solve
  returns the closest candidate and main prints it with its contrast ratio like
  any passing token, without incrementing shortfalls - so the run ends
  "# 0 shortfall(s)" and main returns 0 unconditionally (:120). Reachable:
  min() is taken across all three surfaces, so any mid-tone palette can make
  the constraints unsatisfiable. The project's own recorded class - a tool that
  analysed nothing looks like a tool that found nothing. Fix: return a cleared
  flag, print # SHORTFALL, count it, and exit nonzero.
  **Layman:** The tool that works out theme colours can fail and still print a clean-looking result someone pastes in.
  Kind: fix.
  Source: review-code 2026-09-01 lane 8.

- 📋 [LWSM-1247] **MEDIUM: Theme.default has no caller and DEFAULT_THEME is written as two independent literals.**
  theme.py:76-93. Theme.default() has zero non-test callers and its docstring
  claims "what a first run gets", while __main__.py:251 actually calls
  theme_for_id(settings.theme), defaulted at settings.py:52 by a SECOND
  DEFAULT_THEME = "midnight" literal. CLAUDE.md states the aliasing pattern
  exists precisely so "the file's default and the code's default cannot drift",
  and it was not applied here. A core module may not import theme.py (O1), so
  invert it or delete Theme.default(). Also fold in: accent_soft and attention
  (theme.py:46-47) have ZERO readers - my first false-positive dismissal of
  those two was wrong and is corrected in .ants_review_falsepos.jsonl.
  **Layman:** The default theme is spelled out twice in two files, so the two can drift apart.
  Kind: fix.
  Source: review-code 2026-09-01 lane 8 + check-code vulture.

- 📋 [LWSM-1248] **MEDIUM: installed() never reads mimeapps.list, so Removed Associations is ignored.**
  browsers.py:190 tests a substring of the entry's own MimeType. The MIME
  Applications Associations spec resolves handlers through mimeapps.list with
  [Added], [Default] and [Removed] Associations. Measured on this machine:
  ~/.config/mimeapps.list names firefox.desktop only, and
  /usr/share/applications/kde-mimeapps.list exists - the mechanism is live and
  unread. The set is both WIDER (a [Removed] entry is still offered) and
  NARROWER (an [Added]-only handler never appears). BOTH sides need fixing: the
  module docstring and registry.py:111-112 overclaim; ignoring [Removed] is a
  code defect.
  **Layman:** A browser you explicitly told your desktop not to use for links is still offered in the picker.
  Kind: security.
  Source: review-code 2026-09-01 lane 9.

- 📋 [LWSM-1249] **MEDIUM: a .desktop Name is unbounded and unsanitised and drives a column width.**
  browsers.py:204. Name is untrusted, up to configfile.MAX_FILE_BYTES (1MiB),
  with neither the 4096 per-line cap nor control-character stripping, and is
  consumed at mainwindow.py:581 in a horizontalAdvance() column-width
  computation. design.md calls 4096 "the canonical per-line limit... one number
  governs every untrusted string the app reads or displays". Fix: truncate and
  elide at 4096 and strip control characters in _browser_from.
  **Layman:** One bad browser entry on your machine can stretch a column wider than the screen.
  Kind: security.
  Source: review-code 2026-09-01 lane 9.

- 📋 [LWSM-1250] **MEDIUM: per-entry .desktop failures are silent, producing a message that tells the user something false.**
  browsers.py:232-235 and :224-226. The per-entry containment is correct and
  the exception tuple is complete, but no reason is collected and the module
  imports no logger, against design.md's "Every failure has a visible home...
  Nothing is swallowed". by_id returns None and mainwindow.py:2158 reports
  "%1's chosen browser is not installed - opening in the default", pointing the
  user at reinstalling a browser that IS installed. Fix: return
  (browsers, reasons) in the LoadResult shape this project already uses, log at
  INFO, and let _open_project distinguish absent from refused.
  **Layman:** If your chosen browser's entry becomes unreadable the app says it is not installed, and it is.
  Kind: fix.
  Source: review-code 2026-09-01 lane 9.

- 📋 [LWSM-1251] **MEDIUM: the rescan outer catch-all logs at DEBUG, below the shipped level.**
  mainwindow.py:381. design.md sets the app log to INFO by default, so at the
  shipped level this path leaves no record at all. It catches more than a dead
  signaller - any failure between the except at :375 and the emit at :377 -
  and per LWSM-1131 section 6 the consequence is "Rescan stays disabled
  forever". The one residual instance of the failure the two layers exist to
  prevent is the one with no observable record. Fix: log.warning.
  **Layman:** The one failure that can disable Rescan forever leaves no trace in the log people actually read.
  Kind: fix.
  Source: review-code 2026-09-01 lane 10.

- 📋 [LWSM-1252] **MEDIUM: summarise_merge passes a loop variable to translate, so all six summary fragments are unextractable.**
  mainwindow.py:285. template is a loop variable, so lupdate cannot extract
  "%1 new", "%1 changed", "%1 port no longer detected", "%1 override differs",
  "%1 duplicate" or "%1 missing". The function's own docstring states the rule
  it breaks. Fix: call translate() on each literal inside the tuple and keep
  .replace("%1", ...) on the result. NO LINTER CATCHES THIS - see the tool-gap
  item.
  **Layman:** Every word of the rescan and import summary can never be translated.
  Kind: fix.
  Source: review-code 2026-09-01 lane 10.

- 📋 [LWSM-1253] **MEDIUM: the browser combo takes the height floor but not the width one, and has no tooltip when elided.**
  mainwindow.py:590-591. setMinimumHeight(MIN_TARGET_PX) is applied; the width
  is not wrapped in max(..., MIN_TARGET_PX) the way _fit_buttons does at
  :664-666. With available_browsers=() - the constructor default, and the real
  state where no browser is found - widest is 0 and the control lands at about
  20-22px. Separately it is the only control in the row with no tooltip when
  cut: index 0 reads "Default browser" (15 chars) inside BROWSER_COLUMN_CHARS =
  10, so it is elided on every row on every machine, while _elide_name gives
  the name label a full-text tooltip in the same situation.
  **Layman:** The browser dropdown can be too narrow to click, and its text is cut off with no way to see the full name.
  Kind: accessibility.
  Source: review-code 2026-09-01 lane 10.

- 📋 [LWSM-1254] **MEDIUM: the app elides row text deliberately while design-accessibility.md forbids truncation outright.**
  mainwindow.py:731-733 with NAME_COLUMN_CHARS=16 and BROWSER_COLUMN_CHARS=10.
  design-accessibility.md:124-125 says the layout "must REFLOW at every step,
  never clip or truncate; the test asserts no text is elided at 200%". The code
  elides at 100% too, with a measured reason (LWSM-1174: a 30-char name pushed
  the row to 593px inside a 600px lens). DOCUMENT is the wrong side - elision
  was adopted to answer the lens budget the same document sets. The amendment
  needs a REPLACEMENT check-table row, e.g. "elided text always carries the
  full string in a tooltip and in the accessible name". Route to review-contract.
  **Layman:** The accessibility doc promises text is never cut off; the app cuts it off on purpose, for a good reason nobody wrote down.
  Kind: doc-fix.
  Source: review-code 2026-09-01 lane 10.

- 📋 [LWSM-1255] **MEDIUM: the rescan failure message reaches the status bar unclipped and unquoted.**
  mainwindow.py:377 emits f"{type(exc).__name__}: {exc}" straight to
  set_status_message, which is showMessage with no clip and no escape. exc can
  carry a path or launcher name from a scanned tree. LWSM-1131 INV-10 states
  the rule for the neighbouring surface - "No value read from the file or from
  a scan reaches a merge report entry without passing _quoted" - and names
  LWSM-1078/1102/1114 as three call sites where this class was closed one at a
  time. This is a fourth. configfile.MAX_REASON_CHARS already exists.
  **Layman:** Text from someone else's project files can reach the status bar without being cleaned up first.
  Kind: security.
  Source: review-code 2026-09-01 lane 10.

- 📋 [LWSM-1256] **MEDIUM: pointSizeF returns -1 under a pixel-sized desktop font, making the text-size control a silent no-op.**
  mainwindow.py:1227 captures app.font().pointSizeF(), which is -1 when the
  font was set with setPixelSize, so the guard at :1547 is false and
  set_text_scale changes nothing - while :1553 still ticks the checkmark and
  :1557 still persists. The user is told it worked. Breaks a stated
  non-negotiable. Fix: resolve through QFontInfo(app.font()).pointSizeF(),
  which converts pixels to points; if still <= 0, report via set_status_message
  rather than returning silently.
  **Layman:** On some desktops choosing a bigger text size ticks the menu and saves the choice while nothing gets bigger.
  Kind: fix.
  Source: review-code 2026-09-01 lane 11.

- 📋 [LWSM-1257] **MEDIUM: layout margins are computed once, so they behave exactly like the pixel constant O7 forbids.**
  mainwindow.py:1266-1268. gap = fontMetrics().height() is computed once,
  before set_text_scale runs at :1353, and outer is a LOCAL that nothing keeps
  a reference to. changeEvent's FontChange branch pushes the font to every
  descendant and re-runs _align_columns, and re-computes no margin. The comment
  above the line states the rule it breaks. Fix: bind self._outer and re-run
  both setters from the FontChange branch beside _align_columns.
  **Layman:** Raise the text size and the text grows but the spacing around it does not.
  Kind: accessibility.
  Source: review-code 2026-09-01 lane 11.

- 📋 [LWSM-1258] **MEDIUM: the hide/show messages put a conditional inside translate(), so neither is extractable.**
  mainwindow.py:2204-2206. The conditional is INSIDE translate(), whose second
  argument lupdate/pylupdate require to be a string literal. The identical
  defect _notice_summary's own docstring records as LWSM-1107. Every other
  branch in the slice does it correctly (:2229-2237). Fix: hoist the
  conditional out so each literal is the direct argument.
  **Layman:** The "project is hidden" and "project is shown again" messages can never be translated.
  Kind: fix.
  Source: review-code 2026-09-01 lane 12.

- 📋 [LWSM-1259] **MEDIUM: keyboard jump moves focus to a row without scrolling it into view.**
  mainwindow.py:1949 and :1895. QScrollArea calls ensureWidgetVisible only
  from its focusNextPrevChild override, i.e. for Tab - a programmatic setFocus
  does not scroll. ensureWidgetVisible appears ZERO times under src/. With
  MIN_VISIBLE_ROWS = 3, pressing 4-9 focuses an off-screen row and Enter then
  acts on a row the user cannot see. WCAG 2.4.7, and design-accessibility.md's
  "the magnifier user's 'where am I?' depends on it entirely". Fix:
  self._scroll.ensureWidgetVisible(row) after both setFocus calls.
  **Layman:** Press a number key to jump to a project and the highlight can land somewhere you cannot see.
  Kind: accessibility.
  Source: review-code 2026-09-01 lane 12.

- 📋 [LWSM-1260] **MEDIUM: sequential %1/%2 substitution lets a project name capture the second placeholder.**
  mainwindow.py:2394-2398 and :2230-2232 do
  .replace("%1", message).replace("%2", str(exc)), where message ALREADY
  carries a project name taken from a scanned directory. A project named %2
  lands in the template first and the second pass substitutes the error text
  into the attacker's name. This is LWSM-1181's sequential-substitution defect
  relocated to the status bar, and the one-pass fix is already in this file -
  _TRUST_FIELD.sub at :2102. Fix: route both through a single re.sub over
  %[12] with a field map.
  **Layman:** A project named %2 can swallow an error message into its own name in the status bar.
  Kind: security.
  Source: review-code 2026-09-01 lane 12.

- 📋 [LWSM-1261] **MEDIUM: an operator-precedence bug can render a completely blank trust dialog that still grants trust.**
  mainwindow.py:2123. `str(resolved or argv[0] if argv else "")` parses as
  `(resolved or argv[0]) if argv else ""` because a conditional expression
  binds looser than or - so an empty argv DISCARDS the known resolved path and
  the dialog shows "This will execute:" followed by nothing. Yes still calls
  confirm_and_start with fingerprint defaulted to "" (:2122). ADR-0003: "The
  confirmation is not security theatre only if it shows what will actually
  run." Fix: str(resolved or (argv[0] if argv else "")), and refuse outright
  when both are empty rather than showing an empty prompt.
  **Layman:** In one case the "do you trust this?" box can appear with nothing filled in, and saying yes still approves it.
  Kind: security.
  Source: review-code 2026-09-01 lane 12.

- 📋 [LWSM-1262] **MEDIUM: _bounded_to_screen is applied to the content floor, withdrawing the guarantee stated two lines above.**
  mainwindow.py:2828. The comment at :2823-2825 says "the floor is the content
  itself", and _bounded_to_screen caps at SCREEN_FRACTION of availableGeometry,
  so whenever content exceeds 90% of the screen the floor drops below it.
  Reachable from ordinary input: the name column is the widest cell across ALL
  rows, so one long sibling directory name sets it for everyone. Fix: bound
  want only, leave floor at the content width. Fix together with LWSM-1200 -
  one edit.
  **Layman:** On a small screen the window is allowed to be narrower than its own contents, so the columns collide.
  Kind: fix.
  Source: review-code 2026-09-01 lane 13.

- 📋 [LWSM-1263] **MEDIUM: maximised state is applied on the deferred placement path rather than directly.**
  mainwindow.py:2680-2682. ADR-0007 divides the work explicitly: "Size and
  maximised state are applied directly on every platform - resize() is honoured
  under Wayland; only placement is refused", and only "The KWin call is
  deferred". _restore_geometry runs after Expose PLUS one event-loop tick, a
  measured delay for the KWin call, and showMaximized() rides along - on X11
  too, where nothing needed deferring. Fix: apply resize + showMaximized at the
  top of showEvent and defer only _place_at. VERIFY UNDER REAL KWIN, not the
  suite.
  **Layman:** Leave the window maximised and it reopens small, then jumps to maximised a moment later, every launch.
  Kind: fix.
  Source: review-code 2026-09-01 lane 13.

- 📋 [LWSM-1264] **MEDIUM: the --dry-bump write loop runs under the ERR trap, so a mid-loop failure leaves the tree half-bumped.**
  scripts/local-release.sh:295-306. If the write fails on the third of four
  files, fail exits 1 and the revert at :327 never runs. The author reasoned
  about exactly this for post_check ("Not under the ERR trap: the revert below
  MUST run even when this fails", :312-314) and covered one of the two windows.
  Fix: record the bumped paths and revert from a trap ... EXIT armed before the
  first write, so an exception or a Ctrl-C also unwinds.
  **Layman:** The release dry-run can fail part way through and leave version numbers half-changed.
  Kind: fix.
  Source: review-code 2026-09-01 lane 14.

- 📋 [LWSM-1265] **MEDIUM: the release pre-flight turns a failed tag query into an all-clear.**
  scripts/local-release.sh:191-199. Both `git ls-remote --tags` and
  `gh release view` turn FAILURE into ABSENCE, then fall through to
  "$TAG is free - no local tag, no remote tag, no release". An unreachable
  remote (SSH agent not loaded) with a working gh gives a false all-clear and
  no SKIP, so the verdict can read READY - the one thing the file's own comment
  at :73-75 forbids. Fix: branch on exit status; non-zero is skip, not ok.
  **Layman:** If the release script cannot reach the server it says the version number is free, instead of saying it could not check.
  Kind: fix.
  Source: review-code 2026-09-01 lane 14.

- 📋 [LWSM-1266] **MEDIUM: CI downloads and executes a shellcheck tarball that is pinned but never verified.**
  .github/workflows/ci.yml:107-110. curl | tar -xJ then sudo install to
  /usr/local/bin, executed over the checkout - in a job that SHA-pins its two
  actions precisely to protect against this. zizmor does not read run: payloads,
  so no tool flagged it. Blast radius is a poisoned CI result rather than a
  credential (contents: read, public repo, no secrets), which is why this is
  MEDIUM. Fix: pin the SHA256 beside the version in scripts/ci-tools.env and
  sha256sum -c before extracting.
  **Layman:** The build downloads a tool over the internet and runs it without checking it is the real one.
  Kind: security.
  Source: review-code 2026-09-01 lane 14.

- 📋 [LWSM-1267] **MEDIUM: the desktop entry is validated after it is already installed into the live directory.**
  scripts/install-desktop-entry.sh:60-64. desktop-file-validate runs after the
  entry and icon are in ~/.local/share, under set -e with no cleanup, so a
  failure exits having left a broken entry visible in the launcher. The comment
  above it is right about WHAT and wrong about WHERE. Fix: sed to a temp file,
  validate that, then mv into place - the same atomic discipline
  configfile.write_json_atomically holds on the Python side.
  **Layman:** If the launcher entry turns out to be malformed, it has already been put where your desktop can see it.
  Kind: fix.
  Source: review-code 2026-09-01 lane 14.

- 📋 [LWSM-1268] **MEDIUM: the release script counts workflow triggers and then prints an unconditional sentence about them.**
  scripts/local-release.sh:279-285 counts the PRESENCE of trigger keys, then
  prints "$runs workflow run(s) would fire: no tag trigger and no release
  trigger means the release commit's push is the only one". The number and the
  sentence are unrelated - add a tags: trigger and it prints "2 workflow run(s)
  would fire: no tag trigger". Also `^\s+release:` matches a JOB named release.
  Fix: derive the sentence from runs, or block when a tag/release trigger
  appears.
  **Layman:** The release check will claim no tag trigger exists even after someone adds one.
  Kind: fix.
  Source: review-code 2026-09-01 lane 14.

- 📋 [LWSM-1269] **MEDIUM: the pre-push hook skips a ref whose range it cannot resolve, against its own stated rule.**
  .githooks/pre-push:71-77. The comment says "If that cannot be resolved we run
  the gate - an unknown range is not an exemption"; four lines later
  `oldest=$(git rev-list "$local_sha" --not --remotes | tail -n 1)` followed by
  `if [[ -z $oldest ]]; then continue; fi` skips the ref, contributes nothing to
  changed, and can reach "nothing to check" with the gate never run. Bites when
  a commit is reachable from ANY remote-tracking ref, so a second remote (a
  backup or a fork) can exempt a first push to origin. The comment may be about
  the root-commit fallback at :79 instead - settle which, then either run the
  gate on the empty case or state why the exemption is safe.
  **Layman:** In one case the push check quietly decides there is nothing to check and lets the push through.
  Kind: fix.
  Source: review-code 2026-09-01 lane 14.

- 📋 [LWSM-1270] **LOW: TrustStore.revoke has no caller anywhere - the one finding that survived check-code's eleven tools.**
  supervisor.py:210, vulture 60% confidence, verified by search: zero
  references in src/ and zero in tests/. Same family as LWSM-1136, which
  CLAUDE.md records - a method whose whole value is being called from
  somewhere looks identical to a working one. Deliberately NOT a review-code
  dimension-2b zombie: no contract promises a revoke surface, so it is a dead
  symbol rather than a broken promise. Decide: wire it to a UI affordance, or
  delete it.
  **Layman:** There is a piece of code for forgetting a trusted project that nothing ever calls.
  Kind: chore.
  Source: check-code --tree 2026-09-01.

- 📋 [LWSM-1271] **LOW batch (entrypoint + logging): five small defects from lane 1.**
  __main__.py:69 - notices aliases LoadResult.reasons, so settings reasons are
  appended into the registry load record (harmless today, both gates key on
  rows_refused). :151 - save_field refuses a whole-document refusal but not a
  FIELD refusal, so a hand-typed "text_scale": "150" is destroyed on the next
  write. applog.py:92-98 - check-then-act mkdir races two first-run copies;
  use exist_ok=True. __main__.py:542 - log path printed raw to a terminal;
  quoted() exists. applog.py:225-227 - configure_logging removes only rotating
  handlers where configure_stderr_logging removes all, so a stderr fallback
  could survive and duplicate every record (latent, no caller reaches it).
  **Layman:** A handful of smaller issues in the app's startup and logging code.
  Kind: chore.
  Source: review-code 2026-09-01 lane 1.

- 📋 [LWSM-1272] **LOW batch (registry): six small defects from lane 2.**
  registry.py:357,363,372,374,389,395,407,414 - the loader interpolates path
  RAW at eight sites while the writer half quotes every time, and since
  LWSM-1148 path is USER-CHOSEN (mainwindow.py:1757), so a filename with a
  newline or escape reaches the status bar and the log. :614-617 - the payload
  comprehension sits OUTSIDE _encoded's try, and :597 calls json.loads on
  stored text. :1195 - merge_imported's identity pass is a drifted copy of
  merge()'s: merge() flags DUPLICATE_IDENTITY, this one silently keeps the
  first while its docstring claims "the same three rules"; resolved_of at :918
  is appended to and never read. :1104 - docstring describes an implementation
  that :1110 contradicts. start_at_login and launcher_override have zero
  readers (deferred by LWSM-1131, not zombies).
  **Layman:** Smaller issues in the code that stores and merges the project list.
  Kind: chore.
  Source: review-code 2026-09-01 lane 2.

- 📋 [LWSM-1273] **LOW batch (scanner): nine small defects from lane 3.**
  scanner.py:898 - UNIT_NAME ends in $ not \Z, so "x.service\n" passes and a
  raw newline reaches a systemctl argv and DetectedProject.unit, the one field
  not passed through _display. :1140 - an assembled reason carrying two quoted
  values reaches ~280 chars against a stated 120 bound. :354 - counts
  CHARACTERS against a BYTE cap, up to 4x loose on multibyte; and section 10's
  residency figure ignores the lines list. :646 - docstring describes a
  (None, None) return that never happens, making the target is None half of the
  guards at :786 and :854 unreachable. :774 - anything not .py is treated as
  JavaScript, so `export FOO="./bin"` in a shell hop target is read as an
  import. :37 - "every consumer spells it scanner.LauncherKind" is stale.
  :1518 - an entire scan root is sorted before the first deadline check. :784 -
  one candidate can exhaust the 100-entry skipped budget. :657/:790 -
  intermediate-component TOCTOU (recorded, not fixable without O_PATH).
  DOC: spec 4.1's ScanResult block omits unlistable_roots.
  **Layman:** Smaller issues in the code that discovers projects and their ports.
  Kind: chore.
  Source: review-code 2026-09-01 lane 3.

- 📋 [LWSM-1274] **LOW batch (supervisor): seven small defects from lane 4.**
  supervisor.py:18 - the trust store defers persistence to "until LWSM-1007's
  writer exists", which now exists (registry.save_projects), so ADR-0003's
  "one-time per-project confirmation" re-asks every session and gets clicked
  through. :614 - os.write return ignored; a short write drops bytes and the
  following ftruncate(fd,0) discards the original. :782-787 - stop() has no
  mirror of start()'s stopping refusal against a start reserved in starting
  (latent; the overlay disables both buttons). :1080 - close() blocks the
  caller up to grace+KILL_TIMEOUT (~7s), re-introducing on Quit what ADR-0003
  made stop async to avoid. :943-948 - a TimeoutExpired leaves the child
  unreaped AND the entry popped: a permanent zombie plus a ResourceWarning.
  :901-903 - the self-group SupervisorError propagates after the pop, losing
  the child and leaking its log fd. :408 - ("npm","start") and
  `npm run dev --port 3000` fall through to \0nofile\0, so scripts.start is
  never hashed. :696-698 - full argv logged, so a hand-edited argv carrying a
  token lands in the log unredacted.
  **Layman:** Smaller issues in the code that launches and stops servers.
  Kind: chore.
  Source: review-code 2026-09-01 lane 4.

- 📋 [LWSM-1275] **LOW batch (controller + ports): six small defects from lane 5.**
  ports.py:74 - net_connections(kind="tcp") returns every TCP socket and, on
  Linux, walks /proc/<pid>/fd for EVERY process on the machine, once per
  second, against design.md's 250ms budget - while _managed_paths only ever
  asks holder() for registered ports. controller.py:745 - close() is the only
  cross-boundary getattr call not wrapped, on the shutdown path where an
  exception has nowhere to go. :716 - _stopped is never reset, so
  start_polling() after stop() runs a live 1s QTimer driving a dead loop with
  no error. :511 - record.name reaches a user-facing message with no control-
  character stripping or elision. wait_for_abandoned_probes has zero non-test
  callers (already in known-issues.md; its docstring names the suite as the
  intended consumer). Nothing measures the 250ms snapshot budget, so a
  regression against it is unobservable.
  **Layman:** Smaller issues in the polling loop that keeps the status column up to date.
  Kind: chore.
  Source: review-code 2026-09-01 lane 5.

- 📋 [LWSM-1276] **LOW batch (settings + dialog): four small defects from lane 6.**
  __main__.py:210-216 - the settings dialog is parented and exec()'d with no
  deleteLater(), so every Preferences open leaks a dialog and its widget tree
  for the window's lifetime (WA_DeleteOnClose is wrong here - values() is read
  after exec() returns). :229-236 - a directory name with a newline or trailing
  space is refused by save_scan_roots AFTER the two spinbox values are already
  written, so a partial success reports as a total failure. settings.save has
  no concurrent-writer guard: two instances read-modify-write and os.replace
  makes the loser's change vanish silently - a stated-limit gap rather than an
  ADR-0005 breach. DOC: design.md:768-773 lists four settings.json keys that
  are false (scan roots, slow-start threshold, log-buffer size, tray behaviour)
  and omits log_max_mib, which IS stored.
  **Layman:** Smaller issues in the preferences window and the files behind it.
  Kind: chore.
  Source: review-code 2026-09-01 lane 6.

- 📋 [LWSM-1277] **LOW batch (placement): three small defects from lane 7.**
  placement.py:420 - clamp_to_screens and kwin_script are evaluated OUTSIDE any
  handler, so a Rect whose fields are not integers raises straight out of
  place_window, against run_kwin_script's promise that "a traceback out of a
  startup path" is not acceptable. Closed today by
  settings._bounded_int_or_reason; one caller away from open. :385-386 - a
  failed unlink leaves a place-*.js in the state directory with no log line at
  all. :366-375 - a failing unloadScript (the third call, after the window has
  almost certainly already moved) returns False, so place_window returns None
  and the caller reports a placement that DID happen as failed.
  **Layman:** Smaller issues in the code that positions the window.
  Kind: chore.
  Source: review-code 2026-09-01 lane 7.

- 📋 [LWSM-1278] **LOW batch (theme): six small findings from lane 8, including three unchecked colour pairs.**
  All eight state tokens sit AT the floor and are luminance-identical: in
  ledger, state_wrong_port #8f620c (L=0.14602) and state_unknown #7f691b
  (L=0.14696) are 1.005:1 to each other with hues 7.2 degrees apart, so for
  that pair colour is not the third signal design-accessibility.md:127-131
  promises - and the greyscale check cannot detect it because it passes on the
  word alone. accent vs alt_base is 2.85:1 in ledger (parchment 3.00, mint
  3.02) against a 3:1 non-text floor, and focus_ring_color() returns accent.
  border is checked against NOTHING - ledger #d8d3c4 on #f5f4ef is 1.36:1.
  theme_for_id:401 falls back silently where settings.py:278 states the sibling
  rule the other way ("the same condition reaches them as the default theme AND
  a log line"). derive_state_tokens.py:47 - HIGH_CONTRAST_FLOOR's "kept here
  rather than imported" comment is falsified by line 41, which imports two
  other floors from that same module. Derivation and verification share one
  contrast_ratio implementation, so an arithmetic error would agree with
  itself (checked independently this run; the emitted ratios are correct).
  DOC: four citations to design.md section "Tokens, not colours", which moved
  to design-look-and-feel.md on 2026-08-20.
  **Layman:** Smaller colour and contrast issues, plus some colours nothing ever checks.
  Kind: chore.
  Source: review-code 2026-09-01 lane 8.

- 📋 [LWSM-1279] **LOW batch (browsers): eight small defects from lane 9.**
  browsers.py:190 - `handler in mime` is a substring test against a
  semicolon-separated list, so x-scheme-handler/httprelay is offered as a
  browser. Terminal=true is never checked, so a console browser would be
  launched into DEVNULL and open_url returns success (not reproduced here -
  neither of this machine's two entries sets it). :270 - the Popen handle is
  discarded and never waited on, leaving a zombie until some other Popen
  triggers subprocess._cleanup. :85-88 - XDG_DATA_HOME/DIRS used verbatim where
  the spec requires absolute and says to ignore a relative component. :222 -
  non-recursive glob and entry_id = path.name, where the spec's desktop-file ID
  includes the subdirectory prefix; 45 of this machine's 374 entries live in
  subdirectories, which also weakens the cross-machine-profile argument at
  :64-70. :85 - Path.home() raises RuntimeError in the for header outside every
  guard, and installed() is called synchronously in MainWindow.__init__, so
  window construction fails rather than degrading to no browsers. :219-238 - no
  budget and no entry cap, unlike scanner.py; cheap today, blocks the UI thread
  over an NFS XDG_DATA_DIRS. :128-151 - a quoted field code is substituted
  (spec says it is not a field code) and string escapes are never unescaped
  before tokenising. DOC: design.md section Components still describes
  QDesktopServices with no per-project choice, and Persistence omits browser.
  **Layman:** Smaller issues in the code that finds and launches your browsers.
  Kind: chore.
  Source: review-code 2026-09-01 lane 9.

- 📋 [LWSM-1280] **LOW batch (mainwindow rows): eight small defects from lane 10.**
  mainwindow.py:1003 - _glyph_color is assigned only in update_from, never in
  __init__, while _rerender's docstring contemplates a never-populated row
  reaching update(); paintEvent:819 would raise AttributeError into a swallowed
  paint handler. Unreachable today, latent on any construction reorder. :579
  and :596 - two hasattr guards whose comments ("this runs from __init__ before
  the widgets exist") are FALSE: _apply_text_metrics is called at :524, after
  every widget is constructed. They are dead AND they silently skip, which is
  LWSM-1101's failure shape. :558,:584 - horizontalAdvance("x") as an average
  character gives a CJK name about eight of the intended sixteen characters;
  use averageCharWidth(). :641 - the docstring cites READABLE_BAND_PX, which
  exists only in tests/test_mainwindow.py:537 - source citing a test-tree
  constant inverts the contract direction. :1066 - the announcement's ", "
  separator is hardcoded (not every locale's list separator) and an untrusted
  name containing ", running, port 80" forges a row announcement. :1002 - both
  STATE_GLYPHS.get and state_word's .get fall back silently, so a state added
  without a glyph renders with two of three signals; no invariant asserts the
  maps cover the enum. error_rect has zero production callers (not a zombie -
  no contract promises it). RescanContext.scan/.save field defaults are bound
  at class-definition time, the project's own monkeypatch trap in a second
  costume.
  **Layman:** Smaller issues in how each project row is drawn and announced.
  Kind: chore.
  Source: review-code 2026-09-01 lane 10.

- 📋 [LWSM-1281] **LOW batch (mainwindow chrome): six small defects from lane 11.**
  mainwindow.py:1551 - settings.py:358 range-checks text_scale to 100-200 but
  never against TEXT_SIZE_STEPS, so a hand-edited 137 is accepted, applied, and
  matches no action: the exclusive Text size group ends up with NO item
  checked (WCAG 4.1.2 value). :1631-1633 - str(percent) hard-codes
  Western-Arabic digits; QLocale().toString(percent). :1767 - profile import
  overwrites the user half wholesale INCLUDING actions, a second channel that
  design.md section Custom project actions' by-type argument does not cover;
  latent until run_command lands, then live. Four handlers (set_text_scale,
  set_theme, _export_profile, _refuse_import) report through set_status_message,
  which design-accessibility.md calls invisible to the magnifier user - and the
  doc's remedy ("next to the row that raised them") has no referent for a menu
  action, so the DOC needs a clause for chrome-level feedback. Ten injected
  seams, nine numbers - list_browsers is uncounted, and CLAUDE.md's module map
  repeats the same nine. :1387/:1397 - two addSeparator() calls with nothing
  between them in the shipped configuration. _base_point_size is captured once
  and never refreshed, so a desktop font change makes the control replace
  rather than multiply the desktop size.
  **Layman:** Smaller issues in the menus and window setup.
  Kind: chore.
  Source: review-code 2026-09-01 lane 11.

- 📋 [LWSM-1282] **LOW batch (mainwindow interaction): four small defects from lane 12.**
  mainwindow.py:1942-1945 - the jump shortcut requires NoModifier, so on
  layouts where digits are shifted (AZERTY, several QWERTZ) Key_1 always
  arrives with ShiftModifier and the feature is silently unavailable. Tab still
  reaches every row, so not a 2.1.1 failure - a feature that does not exist for
  those users. Test event.text() instead. :2387-2388 - the `if self._rescan is
  None: return message` guard returns BEFORE set_records at :2408, so on a
  hand-built window set_project_hidden and set_project_browser change nothing
  and still report success. :2099 - " ".join(argv) renders the argv unquoted in
  the one dialog that must not misrepresent; configfile.quoted() exists.
  :2185-2188 - _set_show_hidden calls only _apply_filter, so unhiding a row
  that introduces a wider cell leaves columns stale until the next _sync_rows.
  **Layman:** Smaller issues in filtering, keyboard shortcuts and the trust prompt.
  Kind: chore.
  Source: review-code 2026-09-01 lane 12.

- 📋 [LWSM-1283] **LOW batch (mainwindow geometry): three small defects from lane 13.**
  mainwindow.py:2573-2575 - `area = self._screen_area(); if area is None:
  return` is a user-invoked menu action that does nothing and says nothing,
  while every other Centre failure reports at :2582-2587 and ADR-0007 forbids
  the action "being offered and doing nothing". Reachable on monitor
  hot-unplug. :2623-2625 - `if handle is None or handle.isExposed():` merges
  two different cases: isExposed() genuinely has no Expose still to come,
  handle is None does, and merging them takes the 0ms-after-show timing this
  very method's docstring records as MEASURED-FAILING under Wayland.
  Defensive-only today. OPEN: SCREEN_FRACTION = 0.9 vs ADR-0007's "clamped to
  the available area" - if the 10% margin is not justified at its definition
  (line 109), a user who sizes the window to fill the screen gets it shrunk by
  10% on the next launch.
  **Layman:** Smaller issues in window sizing and the Centre on screen action.
  Kind: chore.
  Source: review-code 2026-09-01 lane 13.

- 📋 [LWSM-1284] **LOW batch (shell tooling): thirteen small defects from lane 14.**
  .githooks/pre-push:23 cites tests/test_hooks.py, which does not exist - that
  assertion is in test_ci_contract.py. ci.yml:41-42's "these two lines are the
  only third-party CODE that runs in this job" is false since the install step
  landed (a shellcheck binary, a go-built actionlint and a PyPI yamllint all
  run). pre-push:127-129 discards the worktree-remove error two lines below a
  comment saying a leftover is worth seeing. local-release.sh:184-187,
  :307-309, :324-326 interpolate $TARGET/$RECIPE into `python3 -c` SOURCE while
  four other sites in the same file use the safe heredoc+argv form, and the
  [0-9]*.[0-9]*.[0-9]* arg filter is a shell GLOB that admits an injecting
  argument. :92 - a missing python3 exits 127 into `|| fail "recipe is not in
  the dialect cut-release reads"`, reporting a malformed recipe when the
  interpreter is absent. GNU-only sed/grep -E '\s'/mapfile with no guard;
  check-version-drift.sh would report "no version found" on BSD sed and fail
  the gate for the wrong reason. install-desktop-entry.sh:47-56 - mkdir -p,
  install and the > redirect all follow a symlink at the destination, and
  XDG_DATA_HOME is environment-influenceable, where the Python side treats this
  as a real threat. pre-push:132 - trap cleanup EXIT with no INT/TERM.
  local-ci.sh:295-302 - under LWSM_REQUIRE_ALL_TOOLS=1 the DRIFT block exits
  before the SKIPPED block prints. check-version-drift.sh:33 - sed prints EVERY
  match, so a second version line garbles every comparison.
  install-desktop-entry.sh:96,99 - || true on both cache refreshes then an
  unconditional "Installed:". INFO: eval "$post_check" executes a string from
  .claude/bump.json (repo-controlled, inherent to the recipe design), and
  LWSM_SKIP_PREPUSH=1 is exportable so it persists for a whole shell where
  commits.md 2.3 allows a bypass only for a specific commit. DOC: CLAUDE.md
  section Build and test and CONTRIBUTING.md:60-61 both omit "Tool versions
  match CI" and "Version lockstep" from the ordered step list.
  **Layman:** Smaller issues in the build, release and install scripts.
  Kind: chore.
  Source: review-code 2026-09-01 lane 14.

- 📋 [LWSM-1285] **INFO: three fillable gaps in check-code's tool set, measured against what the lanes found.**
  review-code's synthesis part 4 is a measurement of check-code's coverage, per
  charters-item-building.md section 11. check-code ran this tree the same day,
  so its status is KNOWN, not assumed. (1) mainwindow.py:2123's operator-
  precedence bug inside a security gate - ruff ran clean and no configured rule
  covers mixed or/conditional precedence; a pylint C0325-family or bugbear rule
  would decide it. (2) translate() called with a non-literal first argument
  (mainwindow.py:285 and :2204) - lupdate silently skips these and nothing in
  the tool set looks at translation extractability; a pylupdate diff in
  local-ci.sh would make it mechanical. (3) local-release.sh's
  `python3 -c "$VAR"` interpolation - shellcheck -x ran clean because the
  variable IS quoted, and no semgrep shell pack is configured. Everything else
  the lanes found is genuinely beyond what a tool decides.
  **Layman:** Three kinds of bug the linters could have caught but currently do not.
  Kind: chore.
  Source: review-code 2026-09-01 synthesis part 4.

- 📋 [LWSM-1286] **INFO: three paths no lane covered, named so the sweep is not mistaken for complete.**
  The 14 lanes tiled all 15 src/ modules (mainwindow.py split 1-1086 /
  1087-1847 / 1848-2510 / 2511-2883, no gap, no overlap), all five scripts,
  .githooks/pre-push, ci.yml, ci-tools.env, .claude/bump.json and
  CONTRIBUTING.md. NOT covered and owned by nobody yet: (1)
  .github/dependabot.yml - lane 14 flagged that it did not open it, so
  dependencies.md 2.6 is UNVERIFIED for the three tool pins in ci-tools.env
  that no package ecosystem watches; (2) .github/FUNDING.yml; (3)
  packaging/*.desktop - the gate lints that template nowhere,
  desktop-file-validate runs only at install time on the rewritten copy.
  Deliberately out of scope and correctly owned elsewhere: tests/ (review-tests),
  docs/ as subjects (review-contract), dependency versions (check-dependencies).
  Also: no lane could RUN the app, so several findings - the U+2028 rendering,
  the KWin behaviours, the pointSizeF return - are reasoned from documented
  semantics and need a live check.
  **Layman:** A short list of files this review did not look at, written down so nobody assumes it checked everything.
  Kind: chore.
  Source: review-code 2026-09-01 synthesis part 5.

## Findings filed in passing

Findings noticed while doing something else and not fixed on the spot — a
surviving mutant, an untested mechanism, a defect in a neighbouring subsystem.
Standing instruction from the user, 2026-08-31: anything found and not fixed
immediately is filed here rather than reported once and lost.

This is NOT a fix-pass. A fold-in section (`FP##`) collects what a phase close
produced and is worked as a batch through the 9-step loop; these arrive one at a
time, gate nothing, and are picked up whenever a phase has room. An item here is
not evidence a phase is unclosed.

Each bullet says who found it and while doing what, because a finding's value is
mostly in the measurement behind it.

- 📋 [LWSM-1192] **The filter box's placeholder text is asserted by nothing.**
  Deleting `_filter.setPlaceholderText` from `_retranslate_strip` entirely
  leaves the whole suite green (measured, mutation probe).

  The one assertion that touches it compares the placeholder against the
  accessible name for INEQUALITY — deliberately, since LWSM-1040 records that
  a placeholder is erased by the first keystroke and so must not be the
  accessible name. An empty placeholder still satisfies that, so the
  assertion holds whether or not the placeholder exists.

  Pre-existing, from LWSM-1040. Surfaced by an over-correction mutant while
  shipping LWSM-1177 — the mutation asked whether that method still does the
  job it already had, and the answer was that nothing checks.
  **Layman:** A test would not notice if the "Filter…" hint inside the search box disappeared.
  Kind: test.
  Source: in-session-2026-08-31, mutation probe while shipping LWSM-1177.
  Lanes: window, tests.

- 📋 [LWSM-1193] **The ban on `str.format` for translated text is stated three times and enforced by nothing.**
  `mainwindow.py` states the rule in prose three times, once as "The rule is
  the file's, not that function's", and records that it was written as
  `.format` first and caught within the hour. It was then broken again in two
  places and shipped, which is LWSM-1176.

  So the rule has been broken twice and caught twice by reading. A source
  invariant would close the class rather than the instances:
  `tests/test_layering.py` already asserts the layering rule by parsing the
  AST rather than grepping, and the same shape answers this — no `.format`
  call whose receiver is a `QCoreApplication.translate` result.

  Out of scope for LWSM-1176, which fixed the two sites it was filed for.
  CLAUDE.md's own note applies: do not add a fifth guard to a fifth call
  site.
  **Layman:** A rule the code explains three times has no automatic check, and it has already been broken twice.
  Kind: test.
  Source: in-session-2026-08-31, while shipping LWSM-1176.
  Lanes: tests, i18n.

- 📋 [LWSM-1194] **Check whether a change to `RowView.managed` alone ever re-renders the row.**
  **Filed unverified, and the reasoning is here so the check is cheap.**
  LWSM-1191 hit exactly this shape for `stopping`: `_maybe_emit` compares
  `_statuses` and nothing else, so a field that changed while every status
  stayed the same never reached the screen. `_on_stopped` now emits in a
  `finally` to close it for `stopping`.

  `managed` is recomputed in the same tick and is not in that comparison
  either, so the same gap looks present. The reachable case: our child dies
  and a stranger binds the same port between two polls. `_classify` reads the
  socket table, so the status stays `running` both times, while
  `_managed_paths` flips the project out. No status changed, so nothing
  emits, and the row is not re-rendered.

  That matters because Open is gated on `managed` for a security reason
  (LWSM-1141, ADR-0004): the whole point is not offering to open a browser on
  a port this manager cannot vouch for. A stale `True` is the wrong
  direction.

  **Not measured.** The window is one poll interval wide and needs a fake
  whose `owns_pid` flips while the probe keeps the port bound — the shape
  `ManagingSupervisor` already has. Reproduce before designing; the fix may
  be as small as `_on_stopped`'s was, or the case may turn out unreachable,
  in which case say so and close it.
  **Layman:** The Open button may stay available after the app stops being able to vouch for what is answering on that port.
  Kind: investigate.
  Source: in-session-2026-08-31, noticed while shipping LWSM-1191.
  Lanes: controller, security.

- 📋 [LWSM-1195] **Two `###` subsections holding FP07 items render outside FP07.**
  `### 🐛 Bug fixes` and `### 🔒 Security` hold FP07 items (LWSM-1132,
  LWSM-1140 and their neighbours) and are rendered AFTER `## FP08`'s bullets
  rather than under `## FP07`, which has no children of its own. So a reader
  attributes finished FP07 work to whatever `##` precedes it.

  Pre-existing in the store's section order, not caused by the section added
  on 2026-08-31 — but that addition MOVED the problem: those two blocks now
  render under `## Findings filed in passing` instead of under `## FP08`.
  Both parents are wrong; the new one is at least a generic bucket rather
  than a specific claim about a fix-pass.

  **It cannot be fixed with the roadmap verbs as they stand.** `roadmap_log`
  has no op that moves or deletes a section, and `roadmap_query
  check_sync:true` reports `file_in_sync: true`, so ROADMAP.md is rendered
  from the store and a hand-edit is reverted by the next write. Filed with
  Ants MCP the same day. Whoever picks this up should check whether a move
  or delete op has landed before attempting anything else.
  **Layman:** Two groups of finished work appear under the wrong heading in the roadmap, so a reader is told they belong to a different batch.
  Kind: doc-fix.
  Source: in-session-2026-08-31, found while creating the Findings filed in passing section.
  Lanes: docs.

- 📋 [LWSM-1287] **CLAUDE.md's prescribed orphan-killing pattern also matches other sessions' processes.**
  CLAUDE.md's supervisor-leak trap prescribes `pkill -f 'sleep [3]0'` and
  warns only that the unbracketed form kills your own session. The
  bracketed form is a SUBSTRING match, so it also matches `sleep 300` --
  and this machine runs several Claude Code sessions whose monitoring
  loops use exactly that. Running it as written on 2026-09-02 killed two
  `sleep 300` processes belonging to other projects' sessions.

  Match by CWD, not by command line: `tests/conftest.py`'s
  `_no_orphans_outlive_the_run` (LWSM-1189) does this, scoping to the
  run's own temp directory, which makes every hit ours by construction.
  The trap text should say so and drop the pkill recipe, or anchor it.

  Not fixed in passing because CLAUDE.md is a gate input, so editing it is
  not a docs-only push, and rule 14's test has to be applied to it rather
  than assumed.
  **Layman:** The cleanup command our own notes tell you to run can kill unrelated programs on this machine.
  Kind: doc-fix.
  Source: in-session-2026-09-02.

### 🐛 Bug fixes

- ✅ [LWSM-1132] **FP07: three of the four launcher kinds cannot start at all.**
  `_launcher_path` (`supervisor.py:261`) builds `(project / argv[0]).resolve()`
  for every argv. For a PATH-resolved command that yields `<project>/npm`,
  `.resolve()` is non-strict so it returns unchanged, `is_relative_to(project)`
  is True, and a path is returned — after which `validate_launcher`'s `os.stat`
  raises ENOENT and `start()` refuses with `LauncherRefused`.
  **The function contradicts its own docstring**, which says
  `["npm", "run", "dev"]` has no launcher file and that returning `None` there
  "is honest rather than convenient".
  `scanner.py` emits exactly the refused shapes: `:1086` `("npm","run",…)`,
  `:1144` `("python3"|"node", filename)`. Only `:981` `(f"./{filename}",)`
  survives. Reproduced against the installed module 2026-08-15:
  `./start.sh` validates; the other three refuse with
  `cannot read <project>/npm: [Errno 2]`.
  The user sees a message blaming their project for a supervisor bug.
  Fix: return `None` when `argv[0]` contains no `/` — POSIX `execvp` semantics
  decide this, not path arithmetic. Keep the containment check for `./…` and
  subdirectory cases.
  Acceptance: a red test per launcher kind — `npm`, `python3`, `node` — each
  watched failing first; the shell kind still validates; and at least one
  `start()` fixture per kind, so the monoculture that hid this cannot return.
  Dependencies: none.
  **Layman:** Only projects started by a shell script actually work. Anything using npm, Python or Node refuses to start and blames your project for it.
  Kind: fix.
  Lanes: core, tests.
  Source: code-quality-review-2026-08-15 lane-1 CRITICAL.
  Resolved (2026-08-17): `_launcher_path` now decides by POSIX `execvp` semantics — an `argv[0]` containing no `/` is resolved against `PATH` and names no file of ours, so it returns `None` instead of building `<project>/npm`. The two interpreter shapes (`python3 <file>`, `node <file>`) resolve `argv[1]` inside the project instead, because that script *is* the launcher and must carry `validate_launcher`'s symlink-out and group-writable refusals. `npm` is excluded by name: its arguments are subcommands, never files. All four launcher kinds now start.
  Tests: a `launcher_factory` fixture with one member per kind — the monoculture this defect hid behind — driving `start()` for shell, python3, node and npm, plus unit tests per argv shape. Fourteen new test cases from nine functions; 508 green (was 494). **Twelve were watched red first (10 failed, 2 passed — the shell kind and the regression guard). The two `npm run`-length cases were NOT: they were added after the fix, from the verdict diff, and lock a defect the fix itself introduced and then removed.** Recorded rather than glossed, because "each watched failing first" is the claim this project checks.

- ✅ [LWSM-1133] **FP07: the optimistic overlay is not bounded and can never settle.**
  `_settle_overlay` (`controller.py:650`) clears the overlay only when the
  derived status equals `_OVERLAY_SETTLES_ON[pending]`, which maps
  `STARTING → RUNNING` and `STOPPING → STOPPED`. `_classify`
  (`controller.py:703`) returns `UNKNOWN` whenever `record.effective_port is
  None`, and `start_project` requires `argv` but **not** a port. So pressing
  Start on any project whose port the scanner could not pin — a documented,
  supported outcome, `port is None` meaning *unknown, never a guess* — sets
  `STARTING` and nothing can ever clear it. `_clear_overlay` is called from one
  place only, the stop-failed branch at `:498`.
  The row then reads `starting` for the life of the session with **all four
  buttons dead** (`mainwindow.py:450-459`).
  Three documents promise otherwise: `design.md § State management` ("bounded so
  it cannot become that second store"), LWSM-1010's bullet ("the bounded
  overlay"), and ADR-0004 § Consequences ("a labelled, **expiring** layer").
  The docstring's "There is no timeout here either" is correct and deliberate
  per ADR-0004 § Slowness is not failure — the defect is the unreachable target
  state, not the absence of a timer, and the fix must not add one.
  Fix: settle on a terminal *observation* as well as the target state — a
  project the supervisor no longer holds cannot still be `starting` — and give
  the port-less case an explicit exit.
  Acceptance: a red test starting a project with `port=None` and asserting the
  overlay clears; a fixture with no port must exist, since none does today.
  Dependencies: none.
  **Layman:** Start a project the app could not find a port for and its row freezes on "starting" forever, with every button greyed out until you restart the app.
  Kind: fix.
  Lanes: core, tests.
  Source: code-quality-review-2026-08-15 lane-3 CRITICAL.
  Resolved (2026-08-18): `_settle_overlay` now clears the overlay
  outright when the record's `effective_port` is None, before the
  target comparison. That is the "explicit exit" this bullet asked
  for, and it is not a timeout — nothing is waited out. The overlay
  covers the gap between the button and a port appearing; a project
  with no port has no such gap, so the honest answer (`unknown`) is
  already available and the overlay settles on the observation that
  there is nothing to observe. The docstring's "no timeout here
  either" therefore still holds and no timer was added.
  The mirror case needed its own test: `_on_stopped` deliberately
  leaves a successful stop's overlay for a poll to clear, and that
  poll could never clear it either, so `stopping` froze the same way.
  Two red tests added, both driven by `startable(port=None)` — the
  factory has always taken `port: int | None` and no test had ever
  passed None, which is exactly why this shipped.
  Verdict-diffed old against new over the 12-case population
  (pending x derived x in-list x port, with port-is-None and
  derived-UNKNOWN correctly coupled): **2 of 12 moved**, both the
  defect. The discriminating case ADR-0004 protects — `starting` with
  a real port reading `stopped` because the server has not finished
  binding — still holds.
  510 tests green (was 508). The supervisor half of this bullet's fix
  line — "a project the supervisor no longer holds cannot still be
  starting" — is LWSM-1134's, which is next and depends on this.

- ✅ [LWSM-1134] **FP07: the overlay also sticks on the two failure paths that matter most.**
  Same mechanism as LWSM-1133, reached two other ways (`controller.py:508-509`).
  A launcher that spawns and exits without ever binding — ADR-0004's own
  definition of `failed` — leaves the derived status at `stopped`, which never
  equals `RUNNING`, so the row sits at `starting` permanently. The mirror case:
  a stop that succeeds while something else still holds the port
  (`StopOutcome.warning`, handled at `:501-503`) leaves `stopping` permanently.
  The evidence ADR-0004 requires — "the child exited without ever binding" — is
  available from the `Supervisor` and the controller never asks for it.
  Recovery in both cases is restarting the app.
  Filed separately from LWSM-1133 because the fix is a different question:
  1133 is about an unreachable target state, this is about not consulting the
  supervisor at all.
  Acceptance: two red tests — a launcher that exits at once, and a stop
  returning `warning` — each asserting the overlay clears.
  Dependencies: LWSM-1133.
  **Layman:** If a project fails to start, or stops while something else is still using its port, its row gets stuck the same way.
  Kind: fix.
  Lanes: core, tests.
  Source: code-quality-review-2026-08-15 lane-3 HIGH.
  Resolved (2026-08-18): the two paths needed different evidence, and
  the obvious fix for the first one does not work. **`running()`
  cannot answer "did the child exit"** — its entry is removed only in
  `_reap`, which only the stop sequence reaches, so a child that dies
  on its own stays in the map. A new `Supervisor.exited()` answers it
  from `_alive` (the non-reaping check the stop sequence already
  uses); `Popen.poll()` would answer it in one line and must not be
  used, because it reaps and frees the PID that
  `start_new_session=True` made the process-group id, which ADR-0003
  forbids until the sequence ends. `_settle_overlay` consults it for
  a STARTING overlay only.
  The stop path is keyed on `StopOutcome.port_still_bound`, **not on
  `warning`**: a warning is also emitted when the probe itself could
  not be read, and there the port's state is unknown rather than
  held, so nothing terminal has been observed and the ordinary settle
  must still apply. A test drives that case and a mutant swapping the
  two dies on it.
  Verdict-diffed `_settle_overlay` over the 24-case population: **1 of
  24 moved**, exactly ADR-0004's `failed`. The slow-start case it
  protects — `starting`, derived `stopped`, child still alive — still
  holds the overlay.
  **Mutation found a gap the tests did not.** Dropping the
  `pending is STARTING` guard left all 46 tests green, and it is not
  an equivalent mutant: mid-stop the child is already dead while its
  port is still bound, so a STOPPING overlay would clear early and the
  row would flicker `running` then `stopped` — the flicker the design
  exists to prevent. A test now covers it and the mutant dies.
  Four mutants run in total, all four now die, including the plausible
  wrong implementation (`exited` via `Popen.poll()`), which is caught
  by asserting `returncode is None` after asking.
  516 tests green (was 510).

- ✅ [LWSM-1135] **FP07: a raw `OSError` escapes `save_projects` and kills Rescan for the session.**
  `tempfile.mkstemp` (`registry.py:819-821`) is the only syscall in the writer
  outside a handler. Everything either side is guarded — `_prepare_config_dir`
  (`:809`), the serialise (`:792`), `_refuse_existing_target` (`:717`), the
  write/replace block (`:829`). Three contracts promise `RegistryError` there:
  the function's own docstring, LWSM-1007 § 4.3 step 5, and § 6's *disk is full*
  row ("the user is told the write failed").
  Reproduced 2026-08-15 with the config directory at mode `0500`:
  `PermissionError [Errno 13] … /cfg/.projects-*.tmp` escapes uncaught. ENOSPC,
  EDQUOT and EROFS reach the same line.
  **The consequence is not the wrong exception type.** `mainwindow.py:857`
  catches only `RegistryError`, and `_finish_rescan` — the sole place
  `_rescan_button.setEnabled(True)` happens (`mainwindow.py:821-824`) — sits
  after the try block rather than in a `finally`. So on a full disk the merge is
  silently discarded, no message reaches the user, and **Rescan is disabled for
  the rest of the session**.
  Fix: wrap the `mkstemp` call and raise `RegistryError`; and move
  `_finish_rescan` into a `finally` so no future escape can repeat this.
  Acceptance: a red test writing into an unwritable directory and asserting
  `RegistryError`; a second asserting the Rescan button is re-enabled after it.
  Dependencies: none.
  **Layman:** If your disk is full when the app saves its project list, the save fails silently and the Rescan button stops working until you restart.
  Kind: fix.
  Lanes: core, ui, tests.
  Source: code-quality-review-2026-08-15 lane-2 HIGH.
  Resolved (2026-08-18): `tempfile.mkstemp` is wrapped and raises
  `RegistryError`, matching the three contracts that promised it.
  Reproduced first at mode 0500 exactly as the bullet describes, and
  the test skips under root rather than passing vacuously.
  **The bullet's UI fix is not sufficient on its own, and the mutant
  proves it.** Moving `_finish_rescan` into a `finally` re-enables the
  button, but the exception still escapes the slot — and this slot is
  delivered from the pool thread, so PySide6 swallows it: no signal,
  no message, nothing in the status bar. `finally` alone was run as a
  mutant (M2) and the test fails on the missing report. So the fix is
  `finally` **plus** a `BaseException` catch-all that reports through
  the existing translated "Rescan failed: %1" string —
  `_RescanTask.run`'s guard, one thread along, and no new UI string.
  The body moved to `_apply_rescan()` returning the message, leaving
  `_on_rescan_done` as nothing but the always-finish guard. That also
  closed a second leak of the same shape: the `self._rescan is None`
  early return skipped `_finish_rescan` entirely.
  Five mutants run. Four die. **M3 — the `finally` removed while the
  catch-all stays — survives, and is reported rather than hidden**:
  it is the redundant-guard case `CLAUDE.md § Trap` names, where
  removing one of several guards proves nothing. The whole-mechanism
  mutant (M4, both removed) dies, which is the meaningful one. The
  `finally` is kept as the structural backstop if the catch-all is
  ever narrowed.
  518 tests green (was 516).

- ✅ [LWSM-1136] **FP07: the 5 MB per-project log cap is a zombie — nothing calls it.**
  `rotate_if_needed` (`supervisor.py:458`) has three occurrences in the tree:
  its definition, a docstring reference at `:439`, and
  `tests/test_supervisor.py:427`. **Zero production callers** — no timer, no
  poll hook, nothing in `controller.py` or `__main__.py`. `MAX_LOG_BYTES`
  (`:86`) is referenced only inside the method nobody calls.
  So `design.md § Observability` ("capped at 5 MB with one rotation") and
  LWSM-1009's bullet (same words) are both false in the shipped build: a chatty
  or looping server appends to an `O_APPEND` fd with no bound until the disk
  fills. Compounding it, a server that prints a token to stdout retains it
  indefinitely with no rotation and no deletion.
  Fix: call it from the controller's existing 1000 ms poll for each entry in
  `running()`. If it is instead meant to wait for LWSM-1011's reader thread,
  the two documents must say so rather than reading as delivered.
  Acceptance: a red test writing past `MAX_LOG_BYTES` through a running poll
  loop and asserting one rotation happened — a test calling `rotate_if_needed`
  directly is what let this ship and does not close it.
  Dependencies: none.
  **Layman:** The app promises to cap each project's log file at 5 MB. Nothing actually does it, so a noisy server can fill your disk.
  Kind: fix.
  Lanes: core, tests.
  Source: code-quality-review-2026-08-15 lane-1 HIGH.
  Resolved 2026-08-19. `ProjectController._rotate_logs`, called from `poll_once`
  before the in-flight guard — the log cap is not a probe, and a bound that
  lapses whenever the socket table is slow is weaker than the one design.md
  promises. Keyed on `supervisor.running()` rather than on the record list, so a
  project the window is not rendering is still capped. Cost on an ordinary tick
  is one `fstat` per running project; the copy happens only on the tick that
  crosses the cap, so the overshoot is bounded by one poll interval of output
  instead of by the disk.
  Reached through `getattr` for `close_supervisor`'s reason rather than by
  widening `SupportsSupervision`: a fake with no logs has nothing to rotate.
  Contained per project under `except Exception` — this runs in a timer slot on
  the GUI thread, so anything escaping it is swallowed by PySide6, and one
  unreadable log would silently stop every other project being capped AND take
  the tick's probe with it.
  Two tests, and the first drives the POLL against a real Supervisor and a real
  child rather than calling `rotate_if_needed`: a test that calls it directly is
  what let this ship, and cannot tell a wired cap from an unwired one. Mutants
  run and dead: removing the `_rotate_logs()` call, and narrowing the catch to
  `OSError`.

- ✅ [LWSM-1137] **FP07: `AlreadyRunning` is a check-then-act and does not hold.**
  `start()` checks `resolved_project in self._registry.processes` under the lock
  (`supervisor.py:520`), then **releases it** for the port probe, trust gate,
  log open and `Popen`, then inserts at `:543`. Two concurrent starts for one
  project both pass the check, both spawn, and the second insert overwrites the
  first `ManagedProcess` — leaking its log fd and losing its PID.
  That is verbatim the hazard the exception's own docstring names (`:148`):
  *"a double-click orphans the first child, whose PID we would then have
  forgotten while it still holds the port."*
  Fix: reserve the key under the lock before spawning — insert a sentinel,
  replace on success, remove on failure.
  Acceptance: a red test issuing two starts whose first spawn is held open,
  asserting one `AlreadyRunning` and exactly one child.
  Dependencies: none.
  **Layman:** Double-clicking Start can launch two copies of a server, and the app forgets about the first one.
  Kind: fix.
  Lanes: core, tests.
  Source: code-quality-review-2026-08-15 lane-1 HIGH.
  Resolved 2026-08-19. `_Registry` grows a `starting` set and `start()` RESERVES
  the key under the lock before the port pre-flight, the trust gate, the log open
  and the spawn — all of which run with the lock released, which is what made the
  old membership test a check-then-act. A set beside `processes` rather than a
  sentinel value inside it, so `running()`, `_get` and `exited()` never see a
  row that is not a `ManagedProcess`.
  The discard is in a `finally`, and that half has its own test: a reservation
  that only ended on success would turn one refused start — an unconfirmed
  launcher, a bound port — into a project that can never be started again for
  the life of the session, which is worse than the race it closes.
  The red test holds the first spawn open INSIDE the trust gate, which is where
  the window actually is; two starts issued back to back serialise on the GIL and
  pass against the broken code. Mutants run and dead: reverting to the bare
  check, and moving the discard out of the `finally`.

- ✅ [LWSM-1138] **FP07: `stop()` is not idempotent and can close another project's descriptor.**
  The registry entry is popped only inside `_reap` (`supervisor.py:722`), so two
  overlapping `stop()` / `stop_async()` calls for one project both retrieve the
  same `ManagedProcess` from `_get` (`:611`) and both reach
  `_close_quietly(managed.log_fd)` (`:724`). The second `os.close` operates on
  an integer the kernel is free to have reissued — to `_open_log` for another
  project, or to the rotation backup fd. The pool has `max_workers=4` (`:402`),
  so the overlap is reachable, and `controller.py:436`'s
  `if path not in self._supervisor.running()` is itself a check-then-act and
  does not close it.
  Fix: pop the registry entry at the top of `stop()` under the lock, return an
  empty `StopOutcome` if it was already gone, and carry `managed` locally.
  Acceptance: a red test issuing two concurrent stops and asserting one
  `os.close` per descriptor — assert on the descriptor, not on the outcome.
  Dependencies: none.
  **Layman:** Stopping a project twice at once can close a file belonging to a different project.
  Kind: fix.
  Lanes: core, tests.
  Source: code-quality-review-2026-08-15 lane-1 HIGH.
  Resolved 2026-08-19. `stop()` pops the registry entry under the lock before it
  signals anything, returns an empty `StopOutcome` when it was already gone, and
  carries `managed` locally; `_reap` no longer pops and only closes. Whoever pops
  owns the sequence, so exactly one `os.close` per descriptor.
  Checked before shipping, because popping early changes what `running()` and
  `exited()` report DURING a stop: `exited()` is consulted only under a
  `STARTING` overlay, a stop's overlay is `STOPPING`, and `restart_project`
  sequences through `_on_stopped` rather than racing it — so no caller reads the
  window differently. `close()` iterating a map a stop has already left is a
  second double-close avoided rather than a regression.
  Asserted on the DESCRIPTOR, not on the outcome: two plausible-looking
  `StopOutcome`s is exactly what the broken version returned. Mutant run and
  dead: the pop moved back into `_reap`.

- ✅ [LWSM-1139] **FP07: `MainWindow.shutdown()` is not the bounded teardown its caller documents.**
  `__main__.py:163-166` states the rescan worker "gets the same bounded wait
  rather than being left to `~QThreadPool`, which joins with no timeout at all".
  It does not: on `waitForDone` timeout (`mainwindow.py:792`) the method logs
  and returns, leaving `self._rescan_pool` parented to the window
  (`mainwindow.py:626`), so its destructor runs the unbounded join anyway.
  `ProjectController.stop()` does the other half — `setParent(None)` plus
  `_ABANDONED.append(...)` (`controller.py:583-584`) — and the window has no
  equivalent.
  Second half of the same gap: `shutdown()` sets no `_stopped` flag, so a rescan
  finishing after teardown still delivers `done`, and `_on_rescan_done` runs
  `save()` and `set_records()` on an already-torn-down window and controller —
  the INV-16 race `controller._stopped` exists for.
  This matters beyond tidiness: a wrong claim about shutdown is exactly how
  LWSM-1100's green-but-truncated suite happened.
  Fix: reparent and abandon the pool the way `stop()` does, so
  `exit_without_waiting_for_abandoned_probes` covers it; add a `_stopped` guard
  to `_on_rescan_done` and `_on_rescan_failed`.
  Acceptance: a red test whose rescan completes after `shutdown()`, asserting no
  write occurs; and one asserting the pool is unparented on timeout.
  Dependencies: none.
  **Layman:** Closing the app while it is scanning can make it save over your project list on the way out, and the app can hang instead of exiting.
  Kind: fix.
  Lanes: ui, tests.
  Source: code-quality-review-2026-08-15 lane-3 HIGH.
  Resolved 2026-08-19. Both halves, and it had neither.
  `shutdown()` now takes the pool, waits `RESCAN_STOP_WAIT_MS`, and on timeout
  calls the new `controller.abandon_pool` — so the pool is unparented and held,
  and `exit_without_waiting_for_abandoned_probes` covers it. Before this it
  logged the word "abandoning" and returned, leaving the pool parented to the
  window, so `~QThreadPool` ran the unbounded join anyway and `__main__`'s claim
  that the rescan worker "gets the same bounded wait" was false.
  `abandon_pool` is `ProjectController.stop()`'s own two lines lifted into one
  public function rather than copied — a second copy that forgot the
  `setParent(None)` would look identical and hang on exit (`coding.md § 1.3`).
  And `shutdown()` sets `_stopped`, which `_on_rescan_done` and
  `_on_rescan_failed` check: a merge landing after teardown ran `save()` and
  `set_records()` against an already-torn-down window, saving over the user's
  project list on the way out. INV-16's race, one pool along, and it cannot be
  closed by disconnecting — a posted `QMetaCallEvent` is dispatched regardless
  (LWSM-1098).
  Taking the pool also makes `shutdown()` idempotent and makes a later
  `_start_rescan` refuse. Mutants run and dead: removing the `_stopped` guard,
  and removing the `abandon_pool` call.

### 🔒 Security

- ✅ [LWSM-1140] **FP07: the trust gate covers no content for `npm`, `node` and `python3` launchers.**
  `launcher_fingerprint` (`supervisor.py:304-325`) hashes argv bytes plus the
  marker `b"\0nofile\0"` (`:322`) whenever `_launcher_path` returns `None` — no
  file content at all.
  ADR-0003 § Trust names precisely this case as the reason the gate exists:
  *"`npm run <script>` executes the `scripts.dev` **string** from an untrusted
  `package.json` through `/bin/sh`"*, and requires re-arming *"whenever the
  launcher command or its content hash changes"*. Rewriting `scripts.dev` —
  which a compromised transitive dependency's `postinstall` can do — changes
  what runs and does **not** re-arm the confirmation.
  The docstring at `:307` argues only the converse direction (that `npm run dev`
  must not authorise `npm run deploy`), which is a different property and is
  held correctly.
  Note the ordering: this is only reachable once LWSM-1132 lets these launcher
  kinds start at all, which is why it has never been exercised end to end.
  Fix: for an `npm run` argv, hash the resolved `scripts.<name>` string from
  `package.json`; for `python3 serve.py` / `node serve.mjs`, hash `argv[1]`
  resolved inside the project — that file **is** the launcher.
  Acceptance: a red test confirming trust for an `npm run dev`, rewriting
  `scripts.dev`, and asserting the next start raises `LauncherUntrusted`.
  Dependencies: LWSM-1132.
  **Layman:** Once you approve running a project, someone can change what that project actually runs and the app will not ask you again.
  Kind: security.
  Lanes: core, tests.
  Source: code-quality-review-2026-08-15 lane-1 HIGH.
  Resolved (2026-08-17): `launcher_fingerprint` now hashes three materials under three distinct markers — a launcher file's bytes (`\0content\0`), the `scripts.<name>` string an `npm run <name>` argv hands to `/bin/sh` (`\0npm-script\0`), and nothing (`\0nofile\0`). Rewriting `scripts.dev` re-arms the gate; so does rewriting a `serve.py`, which LWSM-1132's `_launcher_path` change covers for free. Only the chosen script is hashed, never the whole manifest — re-arming on every dependency bump would fire the confirmation dialog during ordinary development, which is the failure `validate_launcher`'s docstring already records. Every failure path returns `None` and therefore fingerprints as `\0nofile\0`, which *differs* from a confirmed value: an unreadable or unparseable manifest re-arms the gate rather than passing it.
  Citation correction: this bullet attributes *"`npm run <script>` executes the `scripts.dev` string from an untrusted `package.json` through `/bin/sh`"* to ADR-0003 § Trust. That sentence is not in the ADR — it is LWSM-1046's own roadmap bullet (`ROADMAP.md:1692`). The substance stands unchanged: ADR-0003 § Trust does require the gate to re-arm *"whenever the launcher command or its content hash changes"*, and that is the clause this fix satisfies.
  Found while implementing, not by any test: diffing `_launcher_path`'s verdicts old against new over the argv population showed a *two*-element `npm run` matching the interpreter shape on length alone, so a project holding a file called `run` would have had the trust gate vouching for a file with nothing to do with what executes. `npm` is now excluded by name.

- ✅ [LWSM-1141] **FP07: Open-in-browser fires on a foreign server with no disclosure.**
  `mainwindow.py:459` — `self.open_button.setEnabled(running)` — enables Open on
  any running row, and the docstring above it (`:453-457`) argues for that:
  *"including a server this manager did not start … a foreign server is just as
  reachable."*
  ADR-0004:84-86 says the opposite, in a paragraph carrying the threat model:
  *"That is localhost phishing with this app's credibility behind it. So
  Open-in-browser on a `running (foreign)` row carries the same disclosure the
  Stop path does: the holder's executable path, uid, cmdline and start time,
  shown before anything opens."* No such dialog exists.
  **The ADR governs — user decision, 2026-08-15.** It carries the threat model;
  LWSM-1016's bullet ("Enabled in all three running states, including `running
  (foreign)`") does not, and is corrected rather than the ADR.
  The full mitigation needs the seven-state model, which does not exist —
  `_classify` produces three states (`RUNNING` / `STOPPED` / `UNKNOWN`), so
  foreign and managed are indistinguishable today. **Scope here is therefore the
  interim**: Open is restricted to servers this manager started, which the
  supervisor's `running()` set already answers exactly. The disclosure dialog
  itself is P06's, once the state exists to trigger it.
  Acceptance: a red test asserting Open is disabled for a port held by a process
  the supervisor did not spawn; LWSM-1016's bullet corrected in the same commit.
  Dependencies: none. Full disclosure dialog blocked on P06's state model.
  **Layman:** The app will happily open a web page from a server it did not start and cannot vouch for, which is exactly how a fake login page would get in front of you.
  Kind: security.
  Lanes: ui, docs, tests.
  Source: code-quality-review-2026-08-15 lane-3 CRITICAL.
  Resolved 2026-08-19. Open is enabled only for a server this manager started.
  `RowView` grows `managed`, filled from `supervisor.running()` once per render,
  and `_apply_button_state` gates the button on `running and row.managed`.
  ADR-0004 governs (user decision, 2026-08-15) and LWSM-1016's bullet is
  annotated rather than the ADR corrected: `chdir()` is free, so any local
  process can bind a project's port, be classified `running`, and have this app
  send the user to it — localhost phishing with the app's credibility behind it.
  SCOPE: this is the interim the bullet scoped. The ADR's full mitigation is a
  disclosure dialog naming the holder's executable path, uid, cmdline and start
  time, which needs a state model that can tell foreign from managed — `_classify`
  still produces three states. Filed as LWSM-1154 under P06 so it is not lost.
  The row still READS `running`: this restricts the action, it does not make the
  app lie about what it observed.
  One consequence found while shipping and fixed with it: `managed` is the first
  `RowView` field that renders as button enablement and as no text at all, so
  `update_from`'s view-equality gate stopped being sufficient for INV-22 — a
  project leaving the supervisor's set changed the view without changing a word
  a screen reader reads out. The announcement is now gated on the accessible
  NAME having changed, with its own test.
  Fixtures: two rows, both `running`, differing only in ownership. A one-row
  fixture could not tell "Open is disabled for a foreign server" from "Open is
  disabled". Mutants run and dead: ungating the button, and ungating the
  announcement.

## FP01 — Security fold-in (from the P01 review, 2026-08-03)

**Theme:** findings from the P01 `/audit` + code review + security
pass. The static scanners were all clean (ruff, bandit, semgrep,
gitleaks over 24 commits (the count at 2026-08-03 15:37 — see LWSM-1057),
trivy); everything below came from
review, and most of it is **design that is still cheap to
change** rather than code that exists.

### 🔒 Security

- ✅ [LWSM-1045] **FP01: scrub the repo before it is ever public — BLOCKS LWSM-1004.**
  `docs/discovery.md § Problem` publishes a
  working target list for the author's private local services:
  seven project names with exact ports, `file:line` references,
  which two were listening at scan time, and the absolute scan
  root `<scan root>/`, which is also shipped as the
  **default** scan root. `docs/standards/testing.md § T1`,
  `docs/design.md`, ADR-0002/0003/0007 and
  the adoption prompt (now `docs/private/port-contract-prompt.md`,
  author-private) repeat the paths and name
  sibling projects. Two of those services carry personal data.
  **This is in all 24 commits** (as of this bullet's authoring, `4ef2781`
  2026-08-03 15:37; two more landed before the scrub an hour later, which is
  why the resolution note below says 26 — both counts are correct at their own
  moment, see LWSM-1057), so `.gitignore` cannot fix it —
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

- 🚧 [LWSM-1046] **FP01: a trust gate before running a discovered launcher.**
  Start executes arbitrary code from any directory in
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
  Progress 2026-08-14 (e559645, with LWSM-1009): the **core half** is in
  `supervisor.py` and the bullet stays 🚧 for the UI half. Shipped:
  `validate_launcher` refuses a launcher resolving outside its project and one
  that is group- or other-writable — the second is a refusal that cannot be
  confirmed away, because whoever else can write it changes what was vouched
  for afterwards. `launcher_fingerprint` covers the exact argv **and** the
  launcher's bytes, so a confirmed `npm run dev` cannot authorise
  `npm run deploy` (same file) and a rewritten `start.sh` re-arms the gate.
  `Supervisor.start` refuses an unconfirmed launcher with `LauncherUntrusted`,
  carrying the resolved path, the argv and the fingerprint, so the dialog can
  show what will actually run rather than a friendly summary.
  **Not shipped, and named rather than implied:** the confirmation dialog
  itself (LWSM-1010 owns the UI), and persistence — `TrustStore` is in memory,
  so a confirmation lasts the session and re-asks on the next launch. ADR-0003
  says "one-time per-project", which properly means one time ever and needs
  LWSM-1007's writer. Re-asking is the safe direction to be wrong in.
  A symlink that stays **inside** the project is deliberately allowed: the
  ordinary `start.sh -> scripts/start.sh` arrangement, and a rule that fires on
  the legitimate case is a rule that gets switched off.

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
  Progress 2026-08-14 (e559645, with LWSM-1009): the **managed-stop half** is
  done and the bullet stays 🚧 for the foreign path. Shipped: every signal goes
  through a `psutil.Process` handle and never `os.killpg`; the leader's handle
  is captured at spawn while the process is certainly alive, which is what lets
  `_raise_if_pid_reused` fire at all — a handle built later from a scanned PID
  has no creation time to compare. The managed child is not reaped until the
  sequence ends, so its PID cannot be recycled while still in use as the group
  id, and the wait loop polls rather than calling `psutil.wait_procs`, which
  would reap it. A bound port after a stop sets `StopOutcome.port_still_bound`
  and a warning; nothing is signalled for it.
  **Not shipped:** the foreign-stop path — enumerating a process set this
  manager did not spawn, and re-enumerating it after the user confirms
  (ADR-0004). Nothing enumerates a foreign set yet, so there is no stale set to
  re-enumerate; that arrives with the foreign-stop UI.
  A test pins the non-reaping rule, and it took two attempts to make it able to
  fail: with a launcher that *ignores* SIGTERM, a premature `poll()` finds the
  child still running and reads `None` anyway, so the assertion held whether or
  not the rule did. The launcher now exits on the signal.

- ✅ [LWSM-1048] **FP01: don't hand the whole environment to launched projects.**
  ADR-0003 extends `os.environ`, so every
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
  Resolved 2026-08-14 (e559645) with LWSM-1009.
  `supervisor.build_child_env` is an explicit `ENV_ALLOWLIST` — ADR-0003's
  names verbatim — plus the `LC_` prefix family, `PORT` and `LWSM_MANAGED`.
  `os.environ` is never passed through. `PORT` is set only when there is one:
  exporting an empty `PORT` is not the same as not exporting it, since a
  launcher reading `${PORT:-3000}` would get the empty string rather than its
  own default (ADR-0002 case 3). A source-invariant test asserts the list holds
  no `SSH_AUTH_SOCK` and nothing ending `_TOKEN` / `_KEY` / `_SECRET`, so a
  future addition reddens on the commit that makes it rather than at the next
  security review.

- 📋 [LWSM-1049] **FP01: treat detection results as untrusted input.**
  The plausibility test ("holder's cwd is under the
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
  Status corrected 2026-08-15 (LWSM-1058, user decision): 🚧 → 📋. The contract
  landed 2026-08-03 and **no implementation has started** — the bullet's own body
  says it lands with LWSM-1011, which is 📋. 🚧 means "being tackled now" in this
  roadmap's legend, so this was claiming work nobody was doing. The contract
  note above is what 🚧 was standing in for and it stays.
  **One clause of this bullet turned out to be live and is now `FP07`'s**: the
  forged-`chdir` route into Open-in-browser is real today, because
  `mainwindow.py:459` enables Open on any running row with no disclosure — see
  LWSM-1141, which takes the interim restriction. The rest of this bullet still
  waits on LWSM-1011.

- ✅ [LWSM-1050] **FP01: bound the scanner's reads.**
  Detection
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
  Resolved (2026-08-15, status corrected): **the implementation shipped with
  LWSM-1006 on 2026-08-12 and this bullet was left at 🚧 for three days.** Found
  while settling LWSM-1058 — the status-vocabulary question — rather than by any
  review, which is the argument for that question being worth answering. All
  five contract clauses verified present before the flip: the 256 KB per-file
  cap (`scanner.py:46` `MAX_SOURCE_FILE_BYTES`), the per-line deadline
  (`Deadline` at `:166`, `expired` at `:175`), `followlinks=False` (`:1271`),
  non-regular files skipped via `S_ISREG` (`:279`) behind a single
  `O_RDONLY|O_NONBLOCK|O_NOFOLLOW` open (`:269`), and the `commonpath` check on
  the one-hop target (`:568`). The byte cap is enforced in three places on
  purpose — see `CLAUDE.md`'s § T9 trap, which is about this item.

- ✅ [LWSM-1051] **FP01: say plainly that `LWSM_MANAGED` is not authentication.**
  It is unauthenticated, forgeable, inherited
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

- ✅ [LWSM-1001] **P01: uv + ruff + pytest + pytest-qt + CI wired up.**
  `pyproject.toml` declaring Python ≥ 3.13, PySide6 and
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

- ✅ [LWSM-1026] **P01: application log.**
  `app.log` at
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

- ✅ [LWSM-1150] **The local gate and the GitHub run install the same tools, and a hook runs it before every push.**
  Every push on 2026-08-18 went red while `./scripts/local-ci.sh` was
  green. The cause was not a missing check: local shellcheck was 0.11.0,
  the runner's apt shipped 0.9, and 0.11 relaxed SC2015 for `command -v`
  guards — so two lines in `install-desktop-entry.sh` were clean here and
  a failure there. The steps matched perfectly. **Pinning the steps was
  never enough; a gate is its tools.**

  Four parts.

  1. The two SC2015 lines are `if` blocks, which both versions accept.
  2. `scripts/ci-tools.env` pins shellcheck, yamllint, actionlint and uv.
     The workflow SOURCES it and interpolates each version rather than
     restating it, and installs shellcheck from its release tarball
     instead of apt, which can only offer what the runner image pins.
  3. `local-ci.sh` verifies every tool it runs against that pin and
     reports **TOOL DRIFT** — checked FIRST, before anything runs, so it
     is a statement about the run rather than a footnote to a green one.
     Warning locally (a developer whose distro moved ahead must still be
     able to test their own change); fatal under `LWSM_REQUIRE_ALL_TOOLS`,
     where a mismatch means CI did not install what it promised. The
     final line differs too — "passed, but N tool(s) DRIFTED" is not
     "Local CI passed.", because the second is read as "GitHub will pass".
  4. `.githooks/pre-push` runs the gate, exempting a docs-only push by
     the PATHS in the push and never by the commit subject.

  `tests/test_ci_contract.py` (10 tests) holds the arrangement together:
  `ci.yml` may add no check of its own, its install step must interpolate
  the pins rather than repeat them, and the hook must exist, be
  executable, run the unreduced gate, and never exempt `scripts/`,
  `.github/`, `src/` or `tests/` — an exemption covering the gate's own
  inputs would let an edit to the checker skip the check. uv is the one
  pin asserted by equality rather than interpolation, because `setup-uv`
  takes a `uses:` input and a `uses:` input cannot read a shell variable;
  the test is what interpolation does for the other three.

  Nine mutants run, all dead: a check step added to `ci.yml`, a hard-coded
  version replacing an interpolation, a uv pin parted from the workflow, a
  non-executable hook, a `--fast` hook, and `scripts/` added to the docs
  exemption. A tenth deliberately SURVIVES — bumping a version in
  `ci-tools.env` alone is correct, because the workflow follows it; what
  catches that case is the drift report, verified separately in both its
  warning and its fatal form.
  Follow-up (2026-08-18): the last CI annotation is gone and yamllint warnings are now fatal. The 82-character line was `uses: astral-sh/setup-uv@<40-char sha> # v9.0.0`, and nothing in it is removable — the SHA is the pin (dependencies.md § 2.1) and the version comment must stay TRAILING or dependabot stops rewriting it. 63 characters of a pinned `uses:` line are spoken for before the action is even named, so `actions/checkout` cleared 80 by exactly one character and `astral-sh/setup-uv` did not: the old limit was passing by luck. So the LIMIT was wrong, not the line. `.yamllint.yml` extends relaxed with `line-length: max 100` and the reasoning beside it, and `local-ci.sh` runs `yamllint --strict -c .yamllint.yml .yamllint.yml .github/` — the config lints itself, which `-d relaxed` could not express. `--strict` is the second half and matters more: yamllint's default reports a warning and exits 0, which is how that line sat in the annotations of runs everybody read as green, in the same week four pushes went out after a red build because nobody read the notification. **Turn a warning class fatal only once its count is zero.** Verified by mutation both ways: a 117-character line fails the gate (exit 1) and the 82-character SHA pin passes. One process note worth keeping — the first mutant SURVIVED and the gate was right: my test line was 98 characters, under the limit I had just set. A mutant that does not actually express the hazard proves nothing, which is the CLAUDE.md trap about LWSM-1126's inert bullet arriving from the other direction. Measure the mutant before believing the result.
  **Layman:** The check you run on your machine before pushing now uses exactly the same tool versions GitHub does, and it runs itself automatically — so a green run at home means a green run online.
  Kind: fix.
  Source: user-request-2026-08-18.
  Lanes: ci, tooling.

- ✅ [LWSM-1151] **A runnable release preflight, so a release stops on this machine rather than half-way through.**
  `scripts/local-release.sh` is `cut-release`'s Phase 0 made runnable —
  the same relationship `local-ci.sh` has to the CI gate, with one
  difference worth stating: `local-ci.sh` MIRRORS a remote gate, and this
  mirrors nothing. CI fires on push and pull_request only, with no tag or
  release trigger, so **nothing on GitHub ever checks a release.** This
  script is the only gate a release gets, not a local copy of one.

  It reports and changes nothing. No bump, no commit, no tag, no publish
  — `cut-release` still owns Phases 1-7.

  Checks: the recipe exists and is in the dialect `cut-release` reads
  (all three `bump-recipe.md § Validating` tells, plus a `post_bump`
  fourth); OLD extracts; the four files agree (delegated to
  `check-version-drift.sh`, so one implementation answers here, at the
  gate, and as `post_check`); **every recipe pattern matches exactly
  once**; the tree is clean; the tag and release are free; a DATED
  changelog section exists and is non-empty; every roadmap ID that
  section claims shipped is ✅; and what the release would cost in CI
  runs.

  Two design points. **A blocker and a skipped check are tracked
  separately** and the verdict never says "ready" while anything was
  skipped — the same split `local-ci.sh` draws, because "no blockers
  found" and "the blocker check did not run" must not print the same
  way. And **`--dry-bump` refuses on a dirty tree**: its revert is a
  `git checkout`, and running it against uncommitted work destroys it.
  That is not hypothetical — it happened twice during LWSM-1067, once
  taking a `roadmap_log` flip with it and leaving the file saying 📋
  while the store said ✅. Phase 0c exists to prevent exactly that, and
  the flag now enforces it.

  Every path exercised before shipping: no-target (3 skips), target with
  no changelog section, a synthetic dated section carrying a ✅ ID (passes)
  a 📋 ID and a nonexistent ID (both blocked) and a cross-reference in
  continuation prose (correctly not read as a claim), the dirty-tree
  refusal, and a clean-tree `--dry-bump` round trip.
  **Layman:** A script you can run before releasing that says whether the release would fail, and why, without changing anything.
  Kind: implement.
  Source: user-request-2026-08-18.
  Lanes: ci, tooling.

- ✅ [LWSM-1159] **The pre-push hook ran the gate in a developer's environment, not the runner's.**
  LWSM-1150 pinned the gate's TOOL VERSIONS and added the hook, and left the
  hook invoking `./scripts/local-ci.sh` bare. The script's SKIP and TOOL DRIFT
  reports are a warning by default and fatal under `LWSM_REQUIRE_ALL_TOOLS=1`,
  which only the workflow set — so the one moment a local run stands in for CI
  was the one moment it was not asked CI's question.

  Measured 2026-08-21 with actionlint off PATH: the same tree, the same script,
  exit **0** through the hook and exit **1** under the workflow's environment.
  The push goes out and GitHub fails it — the exact split LWSM-1150 was filed to
  close, surviving in the half nobody set an environment for.

  The hook already made this argument for `--fast`, one line above the
  invocation, and stopped at the flag. Fix is `LWSM_REQUIRE_ALL_TOOLS=1` on that
  line. Running the script BY HAND is untouched and stays lenient: a missing
  linter must not stop someone testing their own change.

  The test EXECUTES the hook rather than scraping it — a throwaway git repo
  whose `scripts/local-ci.sh` is a stub that reports the environment it was
  handed — for the reason `_hook_says_docs_only` gives: a scrape can say the
  variable appears in the file, never that the gate was invoked under it. And it
  CLEARS `LWSM_REQUIRE_ALL_TOOLS` from the inherited environment, because CI sets
  it for the whole gate step: an inheriting stub would report the right answer on
  the runner whatever the hook did, and the test would have passed on GitHub
  while the defect it names shipped.
  **Layman:** The check that runs before you push now refuses a push when one of its tools is missing or the wrong version, instead of just warning — which is what GitHub does, so the two now agree.
  Kind: fix.
  Source: user-request-2026-08-21.

- ✅ [LWSM-1160] **The pre-push hook gated the working tree, not the commits being pushed.**
  The hook already read the pushed range from stdin and used it to decide
  the docs-only exemption. It then ran `./scripts/local-ci.sh` from the
  repo root, which tests the working tree.

  Those are the same tree only when the tree is clean. An uncommitted fix
  turned the run green for commits that would go red on GitHub. Unrelated
  scratch work turned it red for commits that were fine. Neither
  announced itself.

  Fixed by checking each pushed tip out into a detached worktree and
  running the gate there. Not a stash: `git stash` exits 0 having stashed
  nothing when there is nothing to stash, so the hook could not tell a
  clean tree from a failed one, and the `pop` would have to survive a
  gate that just exited non-zero.

  Measured 2026-08-21: the checkout plus `uv sync --locked` costs 5.2s,
  against the gate's own runtime. Verified both directions on this tree —
  an uncommitted ruff error now exits 0 where the old hook exited 1, and
  a committed one still exits 1. The working tree is untouched and no
  worktree is left behind.

  Reported by a session reviewing this hook. Also filed globally as
  CFG-0182, because all nine pre-push hooks on this machine have it.
  **Layman:** The check before a push tested the files as they sit on disk, which is not what GitHub receives.
  Kind: fix.
  Source: localwebservermanager-session-2026-08-21.

## P02 — Vertical slice (target: after P01 closes)

**Theme:** the smallest feature that touches every layer —
config file → core logic → OS probe → widget → test. Forces the
integration pain to surface before more code lands on it.

### 🎨 Features

- ✅ [LWSM-1005] **P02: one hand-written project renders a live status dot.**
  A `projects.json` written by hand (no scanner
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

- ✅ [LWSM-1006] **P03: Scanner implements the detection rules.**
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
  Cold-eyes 2026-08-08 (rule-14 gate, `docs/specs/LWSM-1006-scanner-detection.md`): **converged by cap at 3 loops.** 75 findings verified, 75 fixed, 0 unverified, 0 deferred — plus 9 collateral the blast-radius sweeps caught. Loop 1 found that a `systemd` project had no port-detection path at all (both roadmap bullets say this item carries the unit's `Environment=` / `ExecStart`), and that INV-14 prescribed a layering test that fails on landing. Loop 2 found the security gap: INV-1 had promised since the first draft that a symlink out of the project is refused, and nothing implemented it for the launcher itself — a `start.sh` symlinked outside passes both `S_ISREG` and `os.access`, since each describes the target. Loop 3 was ~77% collateral from the first two loops' own fixes, which is why the run stops here: all three of its CRITICALs were defects those fixes introduced, including a `\d{1,5}` that fabricated port 12345 out of `PORT=123456`. **Spec is 1258 lines and is BLOCKED on one user decision** — § 3's third scope decision, whether the recursive walk is built as `design.md` words it. **`design.md` needs seven amendments and `coding.md § O1` one**, all listed in the spec's § 12 and shipping with the implementation, not before it. Scope narrowed the same day: the extra port sources moved to LWSM-1121.
  Spec accepted 2026-08-08 and implementation started. **Supersedes the earlier "converged by cap at 3 loops / 75 findings" note above** — that was true when written and the run did not stop there. Final: **7 cold-eyes loops + 1 conformance pass + 1 mechanical sweep, ~120 findings verified, all fixed, 0 deferred.**

  The run's own method changed halfway and that is the durable part. Loops 1–3 ran the fifteen-dimension brief: ~25 findings a loop, roughly 40 % of them build-changing, count flat, never converged — because six of those dimensions can never come back clean and fixing their findings is what introduced the next loop's real defects. Loops 4–7 ran a **four-question brief** (is a claim false; do two passages give different behaviour; is a required behaviour unspecified; is a test clause unfalsifiable) with everything else explicitly out of scope: 40 findings, **100 % build-changing, zero wording**, on a brief 7× smaller. Global rule 14 has been rewritten around it.

  Two instruments now carry work the reviewers were doing badly, and both are in the repo: `docs/specs/LWSM-1006-conformance.py` executes every pattern the spec prescribes against a breaking corpus (it has caught **7** defects, three of them my own fixes on the run after I made them), and a **mechanical sweep** of `registry.py`'s twelve guards against the spec found the one gap reviewers missed. Loop 7's best lane was told to *write the module on paper*; it found four gaps the adversarial lane did not, which is the evidence for stopping review and implementing.

  **Not to be redone:** the recursive walk is deliberately not built (user, 2026-08-08); the extra port sources are LWSM-1121's; this item also lands LWSM-1050. **Owed with the code:** the twelve doc amendments in the spec's § 12 (`design.md` ×7, `coding.md § O1`, ADR-0003's unit-name pattern), widening `tests/test_layering.py`'s `CORE_MODULES` by `scanner.py` **and** `applog.py`, and moving the conformance cases into `tests/test_scanner.py` before deleting the script.
  Resolved (2026-08-12, FP06 closing): `src/lwsm/scanner.py` ships with all 20 invariants covered, the detection corpus at 15 fixtures (three added by FP06: `project-m-vite`, `project-n-unexecutable-launcher`, `project-o-vite-in-a-comment`), and 386 tests green. Steps 5-6 ran ONCE, on 2026-08-12 — /audit clean, /code-quality-review 25 findings with zero false positives, 9 into FP06 and 16 routed to `docs/known-issues.md`. FP06 is closed; its nine fixes and the two findings that came out of writing them (known-issue-034, -035) are the last of it. **What ships unreviewed, said plainly:** FP06's own ~350 new lines were never read by a cold reviewer, per the 2026-08-07 one-review-per-phase rule and the user's decision at this close. **LWSM-1121 carries the split-out scope** (.env / docker-compose.yml / README port sources, conflict reporting) and is untouched.

- ✅ [LWSM-1007] **P03b: Persist the registry — the file format and the writer.**
  `projects.json` becomes a file the app writes
  as well as reads: the record grows the eleven fields
  [ADR-0005](docs/decisions/0005-registry-and-rescan.md) names,
  every one classified user-owned or detected, and an atomic
  write (temp file, `fsync`, `os.replace`, directory `fsync`)
  that refuses a symlinked target and refuses to write at all
  when the load that produced the records rejected a whole row.
  `schema_version` stays 1, so every hand-written file still
  loads.
  **Narrowed on 2026-08-12**, when the umbrella spec hit
  `review-contract`'s 3-loop cap on a size diagnosis and was split
  along its § 4 seams (`spec-format.md § 5.4`). The merge is now
  **LWSM-1131** and depends on this. The id and the spec path are
  kept rather than reallocated, so inbound citations stay valid.
  Dependencies: LWSM-1006.
  **Layman:** Remember the project list between runs, and never
  lose a hand-edited file to a bad save.
  Kind: implement.
  Source: in-session-2026-08-03.
  Priority: 2.
  Lanes: core, tests.
  Resolved 2026-08-14 (0b29662), from the spec accepted the day before at a
  2-loop cap. `ProjectRecord` grows nine fields across `DETECTED_FIELDS` and
  `USER_FIELDS`, `load_projects` returns a `LoadResult` carrying
  `rows_refused` separately from `reasons`, and `save_projects` writes
  atomically behind the read-only gate. `LauncherKind` moved to
  `registry.py`; `scanner.py` re-exports it, so every consumer still spells it
  `scanner.LauncherKind` and no test moved.
  **Brought forward ahead of the rest of P03b for a reason found by building
  rather than by reading:** LWSM-1010 declares only LWSM-1009, but the record
  carried no launcher, so Start had nothing to spawn — `argv` and `kind` are
  this item's schema fields. See the note on LWSM-1010.
  **The spec's own best finding survived contact with the code**: the loader's
  `except OSError` folded a missing file into "unreadable", which would have
  left a clean machine permanently read-only — the write gate refusing to
  create the very file whose absence it was reading. `RegistryMissing` is the
  fix and a subclass, so `build_window`'s existing handler is untouched.
  Fifteen mechanisms mutated, fifteen died — after one fixture repair:
  `test_write_then_load_round_trips` survived `sorted(records, key=name)`
  because its two fixture names were already in sorted order, and file order
  is load-bearing twice over in LWSM-1131.

- 📋 [LWSM-1039] **P03b: keep one backup of the registry.**
  Every
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

- 📋 [LWSM-1008] **P03b: first-run confirmation flow.**
  No config
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

- 📋 [LWSM-1121] **P03b: Scanner reads the extra port sources and reports conflicts.**
  Beyond the launcher and its one-hop file
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
  Evidence (2026-08-19), from the live app rather than a fixture:
  Ants_Projects_Hub_Website renders `? unknown` / `no port`, and the
  trace says why. Its launcher is `serve.mjs`; the port lives in
  `lib/port.mjs` as `export const DEFAULT_PORT = 4321`, reached only
  by an ES `import`. LWSM-1006's one-hop rule follows an
  `exec`/`node`/`python3` INVOCATION line, so an import is not a hop
  and that file is never opened. Inside `serve.mjs` itself `4321`
  appears only in a comment, which is stripped before the rules run.
  Port therefore stays `None`, and ADR-0004 derives state from the
  socket table, so no port means no state — the `unknown` is correct
  behaviour on a wrong input.
  **This project is the fixture measure 3 needs, and it argues the
  README source is sharper than "lowest confidence" suggests.** Its
  README carries TWO ports: `http://localhost:3000` on line 35 (a
  `npx serve dist` preview of the PUBLISHED site) and
  `http://127.0.0.1:4321` on line 44 (the stats server this app
  manages). A rule taking the first `localhost:NNNN` returns 3000 —
  confidently wrong, and worse than the honest `unknown` shipping
  today. Neither is a conflict between SOURCES, which is what measure
  3 resolves; both hits come from one source, and nothing in this
  bullet says how to choose within one.
  Also worth weighing: an ES-import hop would catch this at full
  confidence and is not in this bullet's three sources at all. File
  it separately rather than widening this item.

---

- ✅ [LWSM-1131] **P03b: merge a rescan into the stored registry.**
  **Split out of LWSM-1007 on 2026-08-12**, which kept the file
  format and the writer. LWSM-1007's spec reached `review-contract`'s
  3-loop cap without converging on a size-and-scope diagnosis — 540
  → 979 lines with findings flat at 12/10/12, each loop clustering
  in a different region — so it was split along its § 4 seams per
  `spec-format.md § 5.4`, each part re-gated from loop 1 on its own
  bytes. This part carries the merge.

  The merge rules from
  [ADR-0005](docs/decisions/0005-registry-and-rescan.md): new /
  unchanged / changed / missing, user overrides winning, nothing
  auto-deleted, duplicate ports flagged with the first-registered
  tie-break. Plus the two outcomes the spec adds that ADR-0005 does
  not name — *not re-observed* (a scan that cannot read a port must
  not erase the stored one) and *duplicate identity* (two stored
  paths resolving to one directory). A **Rescan** button reports
  what changed as a one-line summary.
  Dependencies: LWSM-1007.
  Kind: implement.
  Priority: 2.
  **Layman:** Let a rescan pick up new projects without undoing anything you changed by hand.
  Kind: implement.
  Lanes: core, ui, tests.
  Source: split-of-LWSM-1007-2026-08-12.
  Resolved 2026-08-14 (6c64d9d), from the spec accepted the day before at a
  2-loop cap. `registry.merge()` with `MergeResult`, `ScanResult.unlistable_roots`,
  and the Rescan seam in `MainWindow` — button, `QThreadPool` worker, one-line
  summary, and the write in the slot behind LWSM-1007's read-only gate.
  `merge()` reaches the scan through **Protocols** (`ScanLike`,
  `ScannedProject`, `DetectedPort`) rather than importing `scanner`: the
  direction is `scanner` → `registry`, importing back stops the package
  importing at all, and Protocols make the fakes the contract the way
  `SupportsSnapshot` already does for the probe.
  Fourteen merge mechanisms mutated, fourteen died.
  **Two out-of-scope items from § 9 are still out of scope and are named again
  here so neither reads as delivered**: nothing acts on `hidden`, and a
  duplicate-identity row still shows twice — both need a channel from the merge
  to `ProjectController`, and the honest version of `hidden` also needs a way to
  un-hide. And the duplicate-port flag is produced but its **other half —
  refusing Start for the later claimant — is not built**; P05 owns that, and
  this flag is the input it will act on.
  Deviation worth recording: the summary renders § 4.4's six outcomes and does
  **not** render the duplicate-port count, which that table does not list. Those
  entries still reach the application log with every other reason.

- ✅ [LWSM-1155] **P03b: The one-hop rule follows an IMPORT, not only an invocation.**
  LWSM-1006 § 4.5 hops from a launcher to one more file, and
  `_HOP_KEYWORD` matches `exec`/`python3`/`python`/`node` — an
  INVOCATION. A launcher that is itself the program imports its
  config rather than invoking it, so the hop never fires and a port
  one file away is invisible.
  Measured 2026-08-19 against a real sibling. Ants_Projects_Hub_Website
  renders `? unknown` / `no port` in the app: its launcher is
  `serve.mjs`, and the port is `export const DEFAULT_PORT = 4321` in
  `lib/port.mjs`, reached by `import { resolvePort } from "./lib/port.mjs"`.
  Inside `serve.mjs` itself `4321` appears only in a comment, which is
  stripped before the rules run. **The project is not at fault and needs
  no change** — it is fully ADR-0002 compliant (`PORT` → `STATS_PORT` →
  4321, 1024–65535, fatal on a bad value, standalone behaviour intact).
  This is the scanner's gap.
  Scope: extend the hop's keyword set to the import forms — ES
  `import ... from "./x.mjs"`, `require("./x")`, Python `from .x import`
  / `import x` — subject to § 4.5's SIX existing constraints unchanged.
  Those constraints are what keep this safe, and none of them relax:
  in-project, not the launcher, not under an excluded directory, within
  MAX_HOP_DEPTH, not a symlink, no NUL. **Relative specifiers only**; a
  bare `import { readFile } from "node:fs/promises"` or a bare package
  name is not a path and must not become one, or the hop walks into
  `node_modules` on every Node project.
  Confidence: an import hop lands at ASSIGNMENT confidence like any
  other rule-2 hit — HIGHER than LWSM-1121's README source, which is
  the point. `DEFAULT_PORT = 4321` is the project stating its port;
  a URL in prose is someone describing it.
  Still ONE hop. A launcher importing a module that imports another is
  out of scope and stays undetected — bounding the walk is what makes
  this cheap and what stops a scan following an import graph through a
  project it does not own.
  Acceptance: a fixture whose launcher imports a sibling module holding
  the port is detected with that port and an ASSIGNMENT-confidence
  provenance; a fixture importing a bare package name is NOT hopped to,
  proven by the `_open_source` seam never being called for it; the
  existing six-constraint refusals each still fire, with their reason.
  Dependencies: LWSM-1006.
  Priority: 2.
  Note (2026-08-19): the symptom is no longer reproducible from the
  app alone. A `"port_override": 4321` was set by hand on that
  project's entry in `~/.config/localwebservermanager/projects.json`
  (backup beside it, `projects.json.bak-2026-08-19`), so it now
  renders a port and a real state. **That is a user-side workaround
  and not a fix** — the override is a USER_FIELD, so a rescan keeps
  it and the detection gap stays invisible. To reproduce this item,
  clear that field first; the scanner still returns `port is None`
  for that project either way, which is what a test fixture should
  assert against rather than the rendered row.
  Resolved (2026-08-20): shipped, and the filed **Scope** line was insufficient on its own — recorded because the gap is the useful part. It said to extend `_HOP_KEYWORD` to the import forms. Measured first: `_match_named_file` (launcher rules 3 and 4 — PYTHON and NODE) calls the hop **not at all**, and § 4.5 opened *"only for `kind == SHELL`"*, so for `serve.mjs` — the launcher this item was filed against — a wider keyword set is never reached. The **Acceptance** line is what settles it (*"a fixture whose LAUNCHER imports a sibling module holding the port"*), and it requires the hop wired into rules 3 and 4. Reproduced before fixing (`port=None`) and after (`port=4321 via lib/port.mjs`).
  Three ways the import form had to differ from the invocation form, each forced by measurement: it reads EVERY import line (the invocation form reads exactly one — the last, because the rule is *the last invocation* — and the port-bearing import need not be last); it takes the first specifier that YIELDS a port rather than the first readable one (the real launcher imports `./stats.mjs`, `./lib/github.mjs`, `./lib/port.mjs` and only the third declares anything); and a MISS must not spend the budget (a real Flask launcher yields 95 specifiers whose first eight are all stdlib, and stdlib imports sit above local ones, so counting misses would exhaust the bound before the first local module and make the Python half detect nothing on any realistic file).
  All six § 4.5 constraints still apply — the target goes through `_accept_hop` unchanged — and it is still exactly one hop.
  **Reading every hit over the author's 7 real projects found three defects no fixture had asked for**: `\bimport\b` matches inside `not-an-import` (`-` is a word boundary), so `console.log("./not-an-import")` hopped, and the keyword now has to be in statement position; `from ..up import x` had its dots stripped into a ROOT-level `up.py`, which is not a refusal but a *different file* read and believed; and the budget defect above.
  **Verdict diff over that population: exactly ONE moved, and it is this item's.** That is the evidence the change is surgical, and a test count cannot give it.
  7 mutants, 7 dead. Two of the first-draft mutants were INERT and reported green (one deleted the increment instead of moving it, one never applied through shell escaping) — both re-run properly; sixth occurrence of CLAUDE.md's *a prescribed mutation can be inert* trap. One property is NOT mutation-proven and the test says so: one-hop-ness is the absence of recursion, so breaking it means ADDING code.
  Spec folded back — § 4.5 now states both forms and why the original reasoning was true of `exec` and false of `import`; INV-10 extended to rules 3 and 4.
  970 tests (was 957), `./scripts/local-ci.sh` green, `doc_integrity` clean.
  Known limits, deliberate and stated in the spec: an extension-less specifier (`require("./config")`) is not resolved against `.js`/`.mjs`; two hops still comes back unknown. The bullet's own note about clearing `port_override` on that project to re-observe the symptom still applies — the override is a USER_FIELD and survives a rescan.
  **Layman:** When a project keeps its port number in a small file next to the launcher, find it there too.
  Kind: implement.
  Source: in-session-2026-08-19 (measured against Ants_Projects_Hub_Website).
  Lanes: core, tests.

- ✅ [LWSM-1183] **The launcher follower picks a shell assignment as its next file.**
  Scanning RetroDB, the follower reads `start.sh` and then tries to
  open a file named `PYTHON=python` — a shell variable assignment,
  not a path. Confirmed by recording every path `_open_source`
  receives during a live scan of the author's own tree.

  So the walk never reaches `server_port.py`, where the default port
  is declared, and the row reads `unknown` with no port.

  The fixture corpus cannot see this: the shape only appears in a
  launcher that assigns an interpreter to a variable before using
  it, which no fixture does.
  Resolved (2026-08-24): a `$VAR` / `${VAR}` reference in command
  position is now a hop keyword, a `NAME=` token is dropped as a
  shell assignment, and a keyword line that yields no target falls
  back to the next one up instead of ending the walk. The variable
  is still never expanded — `$PYTHON app.py` resolves because the
  token beside it is a literal, and `exec "$DIR/launcher.py"` still
  gives no hop.

  Verified on the live tree, which is the only instrument that can
  see this: exactly one verdict moved, RetroDB from *unknown* to a
  port read from `app.py`, and the paths opened went from
  `start.sh` + `PYTHON=python` to `start.sh` + `app.py`.

  Six mutants; six killed. Two further mutations of the assignment
  guard were provably EQUIVALENT — `^` is redundant with
  `re.match()`, so neither unanchoring the pattern nor swapping to
  `search()` changes any input; the mechanism-level form of that
  mutation dies. Three of the six only died after three extra tests
  were written for the gaps the first probe exposed.

  The port LWSM-1183 now surfaces for RetroDB is WRONG (5001, from
  a quoted error message; the real default is 5000). That is
  LWSM-1190, filed rather than folded in, and built next by the
  user's decision.

  Spec § 4.5 steps 2, 3 and a new step 5 amended to record what was
  built.
  **Layman:** RetroDB shows no port because the scanner went looking for a file that does not exist.
  Kind: fix.
  Source: user-report-2026-08-24.
  Lanes: scanner.

- ✅ [LWSM-1184] **The import walk stops at a launcher that uses ordinary imports.**
  Scanning Contact_List, the follower reads `run.sh`, then
  `launcher.py`, and stops. The port is declared in `config.py`,
  which `launcher.py` reaches by an ordinary import rather than the
  relative form the walk follows.

  Same symptom as the RetroDB item and a different cause, so both
  need their own fixture. Confirmed the same way, by recording the
  paths a live scan opened.

  Worth checking together with the two items above: both projects
  resolve the port through a FUNCTION CALL rather than writing a
  literal where the server starts, so reaching the right file may
  not be sufficient on its own.
  Resolved (2026-08-25). The filed cause was wrong and measuring said
  so before any code was written: `_import_specifiers` already resolves
  the dotless form, and `from config import ...` on Contact_List's own
  `launcher.py` returns `config.py` today. What actually stopped the
  walk is that the import walk was wired only into launcher rules 3 and
  4 — a shell launcher's invocation hop never reached it. Recorded here
  because this is the fifth time a fold-in bullet has been wrong about
  its own mechanism; the path recorder settled it in one run.

  The fix is one call in `_shell_port`. The invocation hop already
  grants its target program status for rule 3 — `_python_framework`
  runs on the hop file, not on the wrapper — so this is the same grant
  for the port rules, ahead of rule 3 because a port another file
  DECLARES outranks one a framework merely defaults to.

  The contract moved and it is worth being plain about it. `project-e`
  IS this shape, and the corpus pinned it as *unknown* with the reason
  "an honest limit rather than a bug". That limit is what the user
  filed as the defect, so `project-e` is now a detected fixture and
  `project-e-deep` adds one more import to hold the line that is left:
  the bound is one invocation and one import, and nothing recurses.

  Live-tree diff: Contact_List *unknown* → 5002 from `config.py`, which
  is its real `DEFAULT_PORT`. RetroDB kept 5000 and gained real
  provenance — read from `settings_manager.py`'s `'server_port': 5000`
  rather than guessed from Flask's default, so LWSM-1190's answer is no
  longer right by coincidence. Five projects unmoved.

  Five mutants, five killed, baseline green. Spec § 4.5 amended to
  record what was built. `./scripts/local-ci.sh` green.
  **Layman:** Contact_List shows no port because the scanner stopped one file short of where the port is written.
  Kind: fix.
  Source: user-report-2026-08-24.
  Lanes: scanner.

- ✅ [LWSM-1190] **A port rule reads a number out of a quoted error message.**
  Exposed by LWSM-1183, not caused by it. With the follower fixed,
  the walk correctly reaches `app.py` — which `start.sh` really does
  run — and rule 1 then matches `PORT=5001` inside a quoted string:

      '    Settings -> System -> Server Port, or PORT=5001 in the',

  That is English advice telling the user how to move off a busy
  port, not a declaration. RetroDB's default is 5000, which is what
  `_python_framework` returns for its Flask import once rule 1 stops
  firing first.

  So the row went from blank to CONFIDENTLY WRONG. A wrong port is
  worse than an unknown one: the app matches status against whoever
  holds the port, so it reports the project stopped while it is
  running.

  Same class as `project-o-vite-in-a-comment` — real text that is
  not a declaration — but `strip_comment` cannot reach it, because
  there is no comment marker on the line. The discriminator
  available is that the match sits inside a quoted string.

  Measured 2026-08-24 by diffing live-tree verdicts across
  LWSM-1183: exactly one project moved, and it moved to a wrong
  answer. The user chose to ship LWSM-1183 and build this next,
  ahead of LWSM-1184.
  Design constraint found while reading the rules, before any code
  was written — the obvious discriminator does not survive contact.

  "Skip a line that is entirely a quoted string" fixes RetroDB and
  BREAKS Node detection: a `package.json` line reading
  `"dev": "vite --port 3000"` is also a line that is entirely a
  quoted string, and rule 1 is what reads the port out of it. Any
  whole-line test therefore has to distinguish a string that is
  PROSE from a string that is a COMMAND LINE, which the shape of the
  line alone does not say.

  Two facts that bound the design, both read from `scanner.py`
  rather than recalled. `strip_comment` cannot help: there is no
  comment marker on the offending line, and the docstring explains
  that the stripper is deliberately NOT quote-aware, because a
  quote-aware character loop ate `http://localhost:3000` at the `//`
  and cost 766 µs against 64 µs. And `_scan_source` is line-major,
  so rule 1 on the prose line wins before `_python_framework` is
  ever consulted — which is why the Flask default (the right answer,
  5000) never gets a chance.

  Not yet decided: whether the discriminator is quote-state at the
  MATCH position, a language-aware check for `.py` (where an
  unspaced `PORT=5001` is shell syntax, not the Python form rule 2
  already handles), or something narrower.

  Verify any candidate by diffing live-tree verdicts across the
  change — 7 projects, all five launcher kinds — not by fixtures
  alone. Before: exactly one wrong (RetroDB 5001). The bar is
  RetroDB at 5000 or unknown, with the other six unmoved.
  Settled with the user (2026-08-24): the fix is OURS, and the
  sibling project is not asked to change. RetroDB's port handling is
  better than most of the tree — a dedicated `server_port.py` with a
  stated precedence chain, no literal at the bind site, and
  "unset" deliberately distinguished from "malformed". The number we
  mis-read sits in a help message telling the user how to move off a
  busy port, which is good behaviour. Asking every scanned project
  to keep port numbers out of its prose so our scanner is not
  confused inverts who serves whom. Do not reopen this as "RetroDB
  should reword its error".
  Resolved (2026-08-25): both rules now ask WHERE the declaration sits,
  not only what it looks like. A declaration begins at a line start,
  after a separator, or after a word that introduces one; prose ends in
  an ordinary word, and neither `or` nor `"error:` is one of those. Rule
  1 applies it to its two `PORT=` forms only, so `--port` and
  `localhost:` stay readable inside a quoted script value — which is
  what the design constraint above ruled out for a whole-line test.
  Rule 2 applies it to the key minus its last word, so `export const
  DEFAULT_PORT` still declares.

  The instrument found a SECOND instance of the same defect that no
  fixture had. MAME_Curator was reporting 1024, read out of
  `echo "error: PORT='${PORT}' ... expected an integer in 1024-65535."`
  — the lower bound of a validation range. That project declares no
  default on purpose (`PORT="${PORT:-}"`), so *unknown* is its truthful
  answer.

  Live-tree diff: two projects moved and both moved toward the truth —
  RetroDB from a wrong 5001 to Flask's 5000, MAME_Curator from a wrong
  1024 to unknown. Every other verdict unchanged. The filed bar said
  the other six would be unmoved; one of the six was wrong for this
  same reason and is now right.

  Narrow in one direction only: a declarator the set does not know
  costs a detection, and an undetected port is `None`, which this
  module already means as unknown. Two limits are stated rather than
  chased — a prose key carrying no punctuation (`the port = 5000`)
  still passes, and a declaration behind a statement the key swallows
  may now be missed.

  Ten mutants, ten killed, baseline green; four re-run against the
  final text after a formatting reshuffle. `global` was dropped from
  the declarator set on the way: `global PORT = 5000` is not valid
  Python, so no line could ever reach it. Spec § 4.6 amended to record
  what was built. `./scripts/local-ci.sh` green.
  **Layman:** RetroDB shows the wrong port because the scanner read a number out of an error message rather than a setting.
  Kind: fix.
  Source: in-session-2026-08-24.
  Lanes: scanner.

## P04 — Appearance and accessibility foundation

**Theme:** the visual and accessible foundation, laid **before**
the real UI is built on it. Moved ahead of the feature phases by
the user on 2026-08-03: the primary user reads with a screen
magnifier, so this is a design input, and
`docs/standards/coding.md § O8` forbids retrofitting it.

### 🖥 Platform

- ✅ [LWSM-1031] **P04: theme layer — six themes plus high-contrast.**
  Nine semantic tokens plus `is_dark`, expanded
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
  Resolved (2026-08-19): eight palettes ship. The six are transcribed from finbreak/src/finbreak/ui/theme.py -- transcribed rather than imported, because a public repo cannot depend on a path outside it -- plus high-contrast in light and dark. Theme gained the four state tokens ADR-0004 names and this file lacked (starting, wrong_port, foreign, blocked, failed), so all seven derived states plus state_unknown have a colour on every palette; four have no ProjectStatus to bind to until LWSM-1011 and are defined anyway, because the cost of a state token is tuning it against three surfaces on eight palettes and adding the states later would mean re-opening every one. Every state token was SOLVED for, not chosen: a fixed hue per meaning, lightness walked away from the palette's surfaces until the worst of window/base/alt_base clears the floor, then stopped -- the first draft walked from the far end and returned near-white for every hue on every dark palette, legible and meaningless, which is why test_the_state_tokens_are_distinguishable_from_the_body_text exists. Four divergences from finbreak, each recorded beside its value: ledger, parchment, mint and graphite tuned muted_text against window alone and sat at 4.10-4.26 against alt_base, retuned to 4.50-4.52 with the hue kept. Acceptance met -- the § T8 test is now parametrised theme x token x surface (8 x 11 x 3) and DERIVED from the registry, so a palette added to theme.py cannot arrive without coverage, and the two assistive palettes are held to 7:1 through a high_contrast flag on the theme itself. Switchable without a restart via Settings > Theme, and the choice survives one: settings.py is new and minimal (schema_version plus the theme id) on LWSM-1018's file, which that item grows. It never raises on read -- a preference nobody can parse has an obvious right answer, unlike a project list. Membership is NOT checked there (a core module may not import theme.py, § O1); theme_for_id owns the fallback. The LWSM-1005 light placeholder is retired, since keeping it would have made 'six themes' false. 894 green, up from 856; full gate green; every theme rendered offscreen and looked at. 27 mutants across four rounds, five survivors, all closed.

- ✅ [LWSM-1032] **P04: accessibility pass — magnifier-first.**
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
  Started 2026-08-19, after LWSM-1040 shipped and its dependency LWSM-1031
  landed. First move is an audit of the acceptance surface rather than
  code: 17 checks in total — `testing.md § T8`'s four plus every row of
  `design.md § Accessibility`'s table — and a survey of the existing
  suite shows several already hold and are already tested (contrast
  arithmetic across every theme with the 7:1 assistive floor, focus-ring
  contrast, announce-once, focus never stolen). Three need the FEATURE
  built before any check can pass: the in-app text-size control
  (100–200 %, which does not exist — `Settings` holds `theme` alone),
  feedback surfacing next to the control that raised it (notices go to
  the status bar today, which is what the promise rules out), and
  confirmation placement. No spec: § Review cadence's build-first
  default, and the one durable artifact is an additive `settings.json`
  field on a file LWSM-1018 already grows.
  Resolved (2026-08-19). All four `testing.md § T8` checks and every row of
  `design.md § Accessibility`'s check table land, with one exception named
  below rather than hidden. 956 green, gate green, 21 mutants run and 20
  dead — the survivor is recorded in the test that survived it.

  **Two rows were not merely untested.** The lens-view row was FALSE: a row's
  controls ran to x=641 against a 600 px budget, because Fusion gives a
  `QPushButton` an 80 px minimum whatever its label says, so four of them
  spent 344 px on four words needing half that. `_fit_buttons` sizes each
  from its own label; `customer-dashboard-frontend-v2` — known-issue-011's
  own fixture — now ends at 566 px, and that issue is resolved. The
  confirmation row was UNBUILDABLE: Qt centres a dialog on the parent's
  window whichever widget is passed (measured; a box parented to the last of
  four rows gives a rectangle identical to one parented to the window), and
  ADR-0007 forbids positioning our own window, so no code change could have
  satisfied it. The user chose to amend the design to the platform truth
  rather than drop the trust dialog's modality; known-issue-055 is resolved
  as a documentation defect.

  **The largest defect was in the feature this item had to build.** The
  in-app 100-200 % text-size control existed nowhere, and the day it was
  wired up it enlarged nothing the user reads: the window's style sheet
  makes QStyleSheetStyle resolve a font onto every descendant, so
  LWSM-1119's window-to-row fix carried the change one hop and stopped. At
  200 % the state column widened 53 → 103 px while every label and button
  stayed at 9 pt. Three existing tests reported that path covered, and all
  three assert a width the row DERIVES from its own font, which grows either
  way. `design.md § Look and feel` now records that a generated style sheet
  costs font inheritance.

  Feedback moved out of the status bar onto the row that raised it —
  `action_failed` carries `(path, message)` — as a second line, since the
  same section rules out horizontal sprawl. The label is created on demand
  and destroyed rather than hidden, because a hidden QLabel is still an
  unnamed child of the accessibility tree.

  **Rule-14 gate on `design.md`: three loops, 19 verified, 19 fixed, cap
  reached** (rows 5-7 of its loop log). Nine of the nineteen were
  pre-existing, including § Tokens claiming seven state tokens where
  `theme.py` ships eight, and § Components describing the row as "name,
  status dot, port" — the layout § Accessibility rules out. About half of
  each loop's findings landed on the previous loop's fixes, which is why the
  cap verdict recommends no fourth loop and LWSM-1157 files the split.

  **Closed against 17 of 18 rows.** The eighteenth — a confirmation raised
  from the tray shows the window first — was added BY the gate, because the
  tray can raise one with no window on screen and the section's own rule
  forbids a promise with no check. It is scoped to P09 in the table: there
  is no tray to drive yet, so the row is stated rather than run.

  **Still open and NOT part of this item:** `known-issue-013`'s `role=Border`
  half — `ProjectRow` is a bare `QFrame`, so its AT-SPI role is decorative.
  Its description half is resolved, having been a documentation defect: the
  design had widened `coding.md § O8` clause 1 to require a description
  unconditionally where the standard asks for one only when the name is not
  self-explanatory.

- ✅ [LWSM-1040] **P04: keyboard-first navigation.**
  Number keys
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
  Progress (2026-08-19): picked as the first P04 item after FP07 closed. Chosen over LWSM-1032 despite its lower filed priority, because LWSM-1032's acceptance includes design.md § Accessibility's keyboard-reachability row and this item's own bullet says it makes that check natural rather than a retrofit — so 1040 before 1032 is the cheaper order. LWSM-1031 (the dependency) shipped 2026-08-19.
  Open question (2026-08-19), put to the user and NOT yet answered: where the filter box lives. The proposal was a strip above the row list, mirroring how LWSM-1149 placed the Rescan button on its own right-aligned strip rather than stretching it full-width. **Whichever placement is chosen, it is chrome, and `_apply_default_geometry` must count it** — CLAUDE.md § Module map records that leaving the menu bar out of that calculation opened the window one bar too short, so a list that fits scrolled; two LWSM-1149 geometry tests die on that mutant. A fresh session should ask before building, not guess. No LWSM-1040 code exists yet; the item is 🚧 only because it was picked.
  Placement ANSWERED (user, 2026-08-19): the filter box SHARES the
  Rescan strip — filter left, Rescan right, one strip. Chosen over
  the proposed second strip because every row of chrome is a row the
  list does not get, and this window is read through a magnifier.
  The strip is unconditional now: the filter is there whether or not
  the window has anything to rescan.
  Progress (2026-08-19): all four behaviours shipped — `/` focuses
  the filter, typing narrows it (case-insensitive substring of the
  name), Escape clears it, and 1–9 focus the Nth row STILL ON SCREEN.
  Enter starts or stops the focused project. 12 tests, 916 green,
  no SKIPs, no tool drift.
  **`_apply_default_geometry` measures the STRIP, not the button** —
  the bullet's own warning, and the mutant dropping it kills
  `test_a_short_list_opens_with_every_row_visible`.
  Thirteen mutants run, thirteen dead — but two of them only after
  the FIXTURE was fixed, and that is the reusable part. The
  `casefold()`-on-the-name mutant survived `alpha/beta/betamax`, then
  survived `Alpha/BetaSite/MyBeta` as well, because `eta` sits inside
  `BetaSite` in lower case however the letters around it are cased.
  It dies only against `Alpha/BetaSite/MyBETA` filtered by `BeTa`,
  where the needle is in a third case again and the match at the end
  of a name also kills a `startswith` masquerading as a substring
  match. **An all-lowercase fixture cannot test case-insensitivity**;
  real project names are `LottoTracker` and
  `Ants_Projects_Hub_Website`, and the fixture now looks like them.
  Same family as the one-row-fixture and one-launcher-kind traps.
  NOT absorbed, and deliberately: LWSM-1032 still owns
  `testing.md § T8`'s four checks. The one accessibility test added
  here is the filter box's own accessible name, which `§ O8` requires
  per widget as it lands.
  Observed while building, filed nowhere yet: after `/` and a
  narrowing, the caret is still in the filter box, so reaching the
  list needs Tab — number keys type into the box, correctly. The app
  IS fully keyboard-operable, but "Enter in the filter jumps to the
  first remaining row" would make the narrow-then-act flow one
  keystroke. Out of this item's filed scope; raise it as its own
  bullet rather than widening this one.
  Resolved (2026-08-19): shipped in `d2b585d`, CI green. All four
  filed behaviours land — `/` focuses the filter, typing narrows the
  list, Escape clears it, 1–9 focus the Nth row still on screen, and
  Enter starts or stops the focused project. 12 tests, 916 green, no
  SKIPs, no tool drift; 13 mutants run and 13 dead.
  Closed against its FILED scope, not against
  `design.md § Accessibility`'s whole keyboard promise — LWSM-1032
  still owns `testing.md § T8`'s four checks, this item's bullet
  having said only that it makes them natural rather than a retrofit.

- ✅ [LWSM-1033] **P04: window geometry and Centre on screen.**
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
  Resolved (2026-08-21): shipped, with ONE deliberate reduction the user
  approved. Size, maximised state, position restore and Centre on screen all
  work; **capturing** the position under Wayland does not, and cannot — a
  client there is never told where it is, so Qt answers 0,0 forever. Measured
  against real KWin: the compositor reported the window at 640,480 while Qt
  reported 0,0, and 0,0 is a plausible position rather than an error. A
  Wayland session therefore records size and maximised state and leaves the
  stored coordinates alone, which is what KDE's own apps do; a position
  recorded under X11 or typed into the file by hand is still restored there.
  Closing that gap needs the app to own a D-Bus service for a KWin script to
  call back into — put to the user and declined in favour of the honest limit.

  New core module `placement.py` (no Qt at all), `settings.py` grows x/y/
  width/height/maximized, `mainwindow.py` gains showEvent/eventFilter/
  _restore_geometry/closeEvent/centre_on_screen and a View menu.
  1142 tests (was 1041), 20 mutants, 20 killed, ./scripts/local-ci.sh green.

  **Three of ADR-0007's mechanisms were wrong and only running the app found
  them** — the suite was green against every one, because its Wayland tests
  substitute a stand-in for the compositor. The one-tick delay after `show` is
  too early (Expose + one tick, 5/5); KWin's geometry write is authoritative so
  the script must carry the size (a 700x500 window came back at 239x216); and
  the decoration must be added inside the script from `c.clientGeometry`,
  because the window is not decorated yet when placement runs. ADR-0007 is
  amended with all four measurements — no gate, per § Review cadence, since the
  build was the review.

  **This is the class § Review cadence says to watch for, and it is NOT one.**
  A contract would not have caught any of it: ADR-0007 *was* the contract and
  stated the wrong mechanism confidently. What caught it was running the thing.

---

- ✅ [LWSM-1145] **P04: the rows do not line up, because each lays itself out on its own.**
  Seen by the user on the first populated window, and correct: with 7
  projects the status, name and port are variable-width and each
  `ProjectRow` sizes itself independently, so the four buttons land at a
  different x on every row. The eye has nothing to track down.
  The fix is shared column geometry — one width per column, taken from
  the widest cell — NOT a fixed pixel width per column, which breaks the
  moment a project has a long name or the font scales.
  Beware the trap `CLAUDE.md` already records: rows are created once and
  updated in place (LWSM-1131), so whatever carries the column widths
  must survive an update rather than being computed at construction.
  Acceptance: a window with rows of deliberately different name and port
  widths has every Start button at the same x.
  Dependencies: none.
  Resolved (2026-08-18): MainWindow._align_columns computes one width per column across every row — the widest cell winning — and ProjectRow.apply_column_widths adopts it. Re-run after every _sync_rows and after a language or font change, because all three change what a cell needs; NOT settled at construction, since rows are updated in place (LWSM-1131). natural_widths() is derived from the rendered text and the stored floors, never from minimumWidth(): apply_column_widths sets a fixed width, so reading it back would make the column monotonic — it would grow for a long-named project and never shrink when that project left. A mutant doing exactly that reddens test_a_column_shrinks_when_the_widest_project_leaves. Three tests, all on a THREE-row fixture with deliberately uneven names and ports (a one-row fixture cannot see this bug at all); all three redden when _align_columns is stubbed out. Verified against the user's real 7 projects offscreen: every Start button at the same x. 526 tests green, local-ci green.
  **Layman:** Every row positions its own text and buttons, so the Start button sits in a different place on every line. It should read as a table.
  Kind: fix.
  Source: user-report-2026-08-18.
  Lanes: ui.

- ✅ [LWSM-1146] **P04: a menu bar, with Settings as its first real entry.**
  The window currently has a single Rescan button and no other
  affordance, so there is nowhere for anything to go. A menu bar is the
  conventional place and costs little.
  **This item owns the BAR, not the dialog** — LWSM-1018 owns the
  settings dialog itself and is being pulled forward to sit beside it.
  Split so the bar can land first and give every later item somewhere to
  attach: themes (LWSM-1031), Centre on screen (LWSM-1033), logs
  (P08), quit-to-tray (P09).
  Keyboard access is LWSM-1040's and is not restated here, but the bar
  must not be built in a way that forecloses it.
  Dependencies: none.
  Resolved (2026-08-18): shipped as the bar only, as filed. `MainWindow._build_menus` adds a `&File` menu (Rescan when a scan context exists, then Quit on the platform's standard quit sequence) and a `&Settings` menu holding `&Preferences...`. The dialog stays LWSM-1018's and attaches through a new injected `open_settings` seam — the third of the same shape as `confirm` and `open_url` — so it lands without editing this method. Every label carries an `&` mnemonic, which is the item's "must not foreclose LWSM-1040" clause and `coding.md § O8` clause 2; labels are set in `_retranslate_menus`, so `LanguageChange` has one place to go. Two things the diff does not show. The bar counts as chrome in `_apply_default_geometry`: leave it out and the window opens one menu-bar height too short, so a list that fits scrolls — two LWSM-1149 geometry tests die on that mutant, verified. And Rescan became one control with two faces: written as two enable/disable sites, the menu entry stayed live while the button greyed, offering a second merge over the first. 7 tests added, and all 7 are mutation-verified — six mutants on the bar (menu entry not greyed with the button, `changeEvent` no longer retranslating it, Preferences unwired, a menu losing its mnemonic, Quit unwired, the Rescan entry added unconditionally) plus the geometry one above, each killing the test that claims it. 564 green, full gate green. Corrected 2026-08-18: this first said "8 tests", and the pushed commit message 1312c4e carries the same wrong count — 7 is the number, confirmed against the diff (63 → 70 in `test_mainwindow.py`).
  **Layman:** Add a normal menu bar along the top so there is somewhere obvious to find settings, rather than the window being one button.
  Kind: implement.
  Source: user-request-2026-08-18.
  Lanes: ui.

- ✅ [LWSM-1147] **P04: dark is the default theme, not follow-system.**
  LWSM-1031 ships six themes and resolves **follow-system** to midnight
  or ledger. The user has asked for **dark by default**, which is a
  different rule: follow-system on a light desktop opens light.
  So the default is `midnight`, and follow-system becomes a choice the
  user makes rather than the starting state.
  Filed separately rather than edited into LWSM-1031 because that item
  is already specified and cold-reviewed, and its acceptance (the § T8
  contrast test over every theme) is unaffected by which one is default.
  Dependencies: LWSM-1031.
  Resolved (2026-08-19, with LWSM-1031): DEFAULT_THEME is 'midnight' and Theme.default() returns it. Asserted on is_dark as well as on the id, so renaming the palette cannot quietly turn the app light. A mutant setting it to 'ledger' reddens test_the_default_theme_is_dark.
  **Layman:** The app should start dark unless you choose otherwise.
  Kind: implement.
  Source: user-request-2026-08-18.
  Lanes: ui, core.

- ✅ [LWSM-1148] **P04: save and reload a project-settings profile.**
  `projects.json` already persists the registry, and LWSM-1007 made
  that write atomic and gated. What does not exist is a way for the user
  to **name, export and re-import** a set — to keep a known-good
  configuration, move one between machines, or go back to one after a
  rescan changed things.
  Distinct from LWSM-1039 (backup), which protects against the app
  losing data. This is the user deliberately keeping a copy.
  The merge rules are the hard part and already exist: LWSM-1007
  § 4.3 decides detected-versus-user fields, and an import is a merge
  with a different source, not a file copy — importing must not silently
  discard a `port_override` the user set here.
  Dependencies: LWSM-1007.
  Progress (2026-08-21): started, build-first per CLAUDE.md § Review
  cadence — no spec. The format question that would have forced
  spec-first answers itself: a profile IS a `projects.json`, same
  `schema_version`, same writer, same parser, so export is
  `_encode` + `write_json_atomically` to a chosen path and import is
  `load_projects` on it. No new on-disk format, so nothing another
  item binds to and no migration.
  Resolved (2026-08-21): shipped as File → Export/Import profile, plus
  `registry.export_profile`, `merge_imported` and `_user_half_applied`.
  1041 tests (was 1013); `./scripts/local-ci.sh` green; 10 mutants, 10
  killed.

  **The format question the bullet implied never arose: a profile IS a
  `projects.json`.** Same `schema_version`, same writer, same parser, so
  export is `_encoded` + `write_json_atomically` to a chosen path and
  import is `load_projects` on it. No new on-disk format, nothing else
  binds to one, no migration — which is why this stayed build-first.

  **The merge rule.** Import is the exact mirror of the rescan merge: the
  USER half moves, the DETECTED half stays this machine's. Both are driven
  by `DETECTED_FIELDS` / `USER_FIELDS`, so LWSM-1007 INV-1 keeps each
  complete as fields are added.

  **How the `port_override` hazard the bullet named was actually closed.**
  Not by skipping default-valued fields — that makes export-then-import
  stop being the identity. The window refuses an import whose load
  reported ANY refusal, where the registry's own loader deliberately keeps
  a row that lost a field. The asymmetry is the cost: there, keying on
  `reasons` would disable persistence for a whole session (LWSM-1007
  § 4.3); here it is one refused button press with a reason. That
  guarantee is what lets `_user_half_applied` take the user half whole
  with no per-field qualifier, and both halves are pinned by tests.

  **Stated loss:** an import restores whole, so a user field the profile
  left unset is cleared. Deliberate, and pinned by
  `test_an_import_clears_a_user_field_the_profile_left_unset`.

  Verified against the real population (7 projects,
  /home/ants/.config/localwebservermanager/projects.json, read-only):
  export → import round-trips to 7 unchanged and byte-identical records.
  Perturbing two user fields and one detected port locally moved exactly
  the two user verdicts and left the detected drift alone.
  **Layman:** Let me save my list of projects and their settings to a file, and load it back later or on another machine.
  Kind: implement.
  Source: user-request-2026-08-18.
  Lanes: ui, core.

- ✅ [LWSM-1149] **P04: the window opens big enough to read, and the layout is overhauled.**
  The user's first populated window was ~790x520 for 7 rows, with the
  Rescan button stretched across the full width and no visual hierarchy.
  **Distinct from LWSM-1033**, which restores a REMEMBERED geometry —
  this is what happens when there is nothing remembered, which is every
  first run and the only impression a new user gets.
  Scope: a first-run default size that fits the columns without
  truncation, a sensible minimum below which the columns would collide,
  spacing and grouping that separate the row list from the window
  chrome, and Rescan moved off the full-width strip once LWSM-1146's
  menu bar gives it somewhere to live.
  NOT a re-theme — colour is LWSM-1031's.
  Dependencies: none.
  Resolved (2026-08-18): four parts. (1) The row list moved into a frameless QScrollArea. That was not in the filed scope and is the part that mattered most — without it the window's minimum height is every row it holds, so a user with twenty projects gets a window taller than the screen that cannot be shrunk, which is the opposite failure and worse. (2) MainWindow._apply_default_geometry sizes the opening window from the content and clamps it to 90 % of the available screen: height is chrome + min(rows, DEFAULT_VISIBLE_ROWS=8) row pitches, the floor is chrome + MIN_VISIBLE_ROWS=3, and the width reserves the scrollbar so a long list cannot take that room out of the last column. Counts of rows, never pixel constants (§ O7). It runs from _sync_rows, not only __init__, because a first run has no records and the rows arrive with the first scan — and it is applied ONCE, so a second scan does not resize a window the user has already sized by hand. (3) Rescan moved off the full-width strip into its own right-aligned row; the menu-bar half of that scope stays with LWSM-1146. (4) Outer margins and inter-row spacing set from the text metric. Six tests. Three of the first draft were vacuous and are recorded as such: deleting the whole geometry mechanism left them green, because Qt's default happened to satisfy them — 'a long list does not grow the window' passes trivially against a window that never grows at all. Replaced by one test pinning the short case AGAINST the long case (3 rows shorter than 8, 8 equal to 48, and the rest scrolls) plus a minimum-height test asserting three rows still fit. Both die when the mechanism is removed, as does the first-run test; the rescan and applied-once tests die on their own mutants. The WIDTH floor is deliberately not asserted: the columns are fixed-width so Qt's own layout minimum already forbids clipping one, and the assertion could not fail. 532 tests green, local-ci green. Verified offscreen against the user's real 7 projects and against 20.
  **Layman:** The window opens tiny and cramped. It should open at a sensible size and look like a proper application.
  Kind: implement.
  Source: user-request-2026-08-18.
  Lanes: ui.

- ✅ [LWSM-1156] **P04: Enter in the filter box jumps to the first remaining row.**
  Split out of LWSM-1040 (2026-08-19) rather than widening it: the
  observation was recorded on that bullet, put to the user at the close,
  and filed here on their say-so.

  After `/` and typing, the caret stays in the filter box, so reaching
  the narrowed list needs a Tab. The app IS fully keyboard-operable
  already — this is a keystroke saved, not a gap closed, which is why it
  was out of LWSM-1040's filed scope.

  Scope: Enter inside the filter `QLineEdit` focuses the first row still
  visible under the current filter. **Not** Enter anywhere else —
  `MainWindow.keyPressEvent`'s Enter already clicks the focused row's
  enabled button, and that meaning must not change. The two live in
  different widgets, so Qt's propagation separates them the same way it
  already separates a digit typed into the box from a digit typed
  anywhere else; no guard should be needed, and if one is, that is the
  signal the design is wrong.

  Edge case the test must name: an empty result set. Enter with no
  remaining rows does nothing and must not move focus or raise.
  Dependencies: LWSM-1040 (shipped).
  Resolved (2026-08-21): `returnPressed` on the filter box focuses the first
  row still visible. **The bullet's prediction held exactly** — the two Enters
  live in different widgets, a `QLineEdit` consumes Return and emits
  `returnPressed` so the key never reaches a row, and no guard was needed
  anywhere. The bullet said a guard would be the signal the design was wrong;
  none was written.

  Empty result set does nothing and does not move focus, as filed. Extracted
  `_visible_rows` because the number-key shortcut already built the same list
  and the `isHidden`-not-`isVisible` reasoning is load-bearing — two copies is
  two places for it to drift, and a mutation swapping them is only caught
  because the tests run against an unshown window.

  Reused LWSM-1040's `keyboard_window` / `shown_names` helpers; the
  digit-typed-into-the-box case already had a test up there and a second copy
  was dropped rather than written. Filtered to the SECOND of three rows, so a
  handler focusing row zero of the UNFILTERED list fails.

  1145 tests (was 1142). 4 mutants, 4 killed. ./scripts/local-ci.sh green.
  **Layman:** After typing a filter, one press of Enter should put you on the first matching project instead of needing Tab first.
  Kind: accessibility.
  Source: in-session-2026-08-19 (split out of LWSM-1040's close, user-approved).

- ✅ [LWSM-1157] **Split docs/design.md — it is 1223 lines and its gate keeps capping.**
  Filed by the rule-14 gate on 2026-08-19 rather than acted on, because
  splitting a contract document is a change to what other documents cite
  and is not a fix pass's call.

  The evidence is the loop log's rows 5-7. That run reached its cap of 3
  with every loop returning verified findings — 7, 6, 6 — and none of the
  three converged. Two things were true at once and both are recorded in
  row 7. Each loop found REAL pre-existing defects, including one (§
  Tokens claiming seven state tokens where `theme.py` ships eight) that
  three earlier loops of this same document had read past. And each
  loop's own fixes seeded about half the next loop's findings — 3 of 6 in
  loop 2, 3 of 6 in loop 3, a share that did not fall.

  `review-contract` § At the cap names the size signal for exactly this
  shape: two specs over 1000 lines took nine and eleven loops, and
  splitting before loop 1 is cheap where splitting at loop 8 wastes eight.
  At 1223 lines this document is past that mark, and the review's own
  reading is that two cold reads never reach parts of it.

  Suggested seams, in the order they look cleanest — § Accessibility (~200
  lines, self-contained, cited by `testing.md § T8` and by every
  accessibility item) and § Look and feel (~90 lines, the token contract).
  Both are cited from elsewhere by section name, so a split means updating
  those citations rather than rewriting content.

  **Do not re-run the gate on the whole document first.** Row 7's verdict
  is that a fourth loop starts against a document whose last three loops
  were each repairing the one before; the split is what changes that,
  not another pass.
  Resolved (2026-08-20): both suggested seams taken. `docs/design-look-and-feel.md` (111 lines) and `docs/design-accessibility.md` (219 lines) are their own documents; `design.md` is 1223 -> 912 lines. Content moved verbatim — byte accounting is exact (73,554 - 5,501 - 14,490 = 53,563, plus a 798-byte stub = 54,361), so no rule changed and rule 14's No branch applies.
  **The bullet's "§ Accessibility is self-contained" was not quite right**, and finding out is the only judgement call in the item: it cites § Tokens, not colours three times and § Tokens lives inside § Look and feel, so the two seams are mutually entangled. Split into two files anyway rather than one combined file — each is then independently reviewable, which is the point — and the four cross-references (plus two into § Components, one into § State management) became ordinary cross-document citations naming their file.
  Both `##` headings stay in `design.md` as pointer stubs. That is what keeps the ~15 dated ROADMAP records citing `design.md § Accessibility` resolving without rewriting the store's own render.
  42 citations updated across 8 files (LWSM-1005's spec, known-issues, audit-allowlist, ADR-0007, CLAUDE.md, three test modules). Keeping the `##` heading inside each new file means only the PATH moved, so every `§ Accessibility` citation still resolves.
  Ten test docstrings crossed ruff's 88-char limit on the longer path and were re-wrapped; the gate caught all ten and reasoning about the diff would not have.
  Verified: `doc_integrity` clean over all 39 docs, `./scripts/local-ci.sh` green at 957 passed with every tool matching its CI pin.
  Not done, and noted rather than actioned: `§ Detection rules` is 292 lines and is the next-largest self-contained contract in the file. Splitting it too would put `design.md` near 600. That is outside this bullet's filed scope and is the user's call.
  **Layman:** The design document has grown too big for anyone to review in one sitting, so it should be broken into a few smaller ones.
  Kind: doc.
  Source: in-session-2026-08-19 (review-contract cap verdict, LWSM-1032's gate).

- ✅ [LWSM-1158] **`test_completed_tasks_do_not_accumulate` is load-flaky, and its widened ceiling is still a GC-timing assertion.**
  Measured 2026-08-20. `tests/test_controller.py::test_completed_tasks_do_not_accumulate`
  failed twice under load — once inside the `pre-push` hook and once in a
  back-to-back run loop — reporting **46** and **182** live `_SnapshotTask`
  wrappers after 200 completed polls, against a ceiling of 20. It then passed
  8/8 in a quiet loop on the same tree, and 8/8 on the pre-split tree, so the
  suite is roughly 13 pass / 2 fail on this machine and the trigger is machine
  load rather than any code change.

  **It is not a leak, and the 182 is the tell that it is not measuring what it
  says.** The task emits `projects_changed` from *inside* `run()`; the pool
  deletes the task only once `run()` RETURNS. `qtbot.waitSignal` therefore
  returns while the task is still alive by construction, and under load the
  pool accumulates a backlog of tasks that have signalled but not yet unwound.
  182 of 200 is what a full backlog looks like — which is also, exactly, what
  the one-per-tick defect the test exists for looks like. **The test cannot
  distinguish its own defect from a slow machine**, and that is the defect in
  the test.

  The ceiling has already been widened once for this — from `<= 1` to
  `polls // 10` on 2026-08-14, with a comment explaining that `gc.collect()`
  does not free a wrapper the moment its C++ object goes. Widening it again is
  the wrong fix: the gap between "a handful pending" and "one per tick" is not
  a threshold problem, it is that the test never waits for the pool to drain.

  Scope: make the measurement wait for quiescence rather than for a signal —
  `QThreadPool.waitForDone()` on the controller's pool before `live()` is read,
  which is the same bounded-wait `controller.stop()` already owns. Then the
  count is taken in a state where a pending task is a genuine leak, and the
  ceiling can go back to something that discriminates by more than a factor of
  ten.

  **Do not simply raise the ceiling.** A ceiling above 182 would pass against
  the original one-per-tick defect at these poll counts, which is the whole
  behaviour this test locks.

  Acceptance: with the pool drained before the count, the test passes under
  induced load (run it against a busy machine, or with the suite in a tight
  loop) and still fails when `setAutoDelete(False)` is re-injected — both
  verified rather than reasoned about, per the § T9 note in `CLAUDE.md`.

  Priority: 2.
  Dependencies: none.
  Resolved (2026-08-20). Reproduced first, as the bullet asked: 5 of 6
  runs red under `nproc*2` busy loops, then 12 of 12 green after the fix,
  against 970 passing tests and a green gate.

  **The bullet's Scope line was wrong about the mechanism and its
  Acceptance line was right** — the same shape as LWSM-1155, and the
  reason `CLAUDE.md` says to run a prescribed mutation before trusting
  the bullet that prescribes it. Scope said to drain the pool with
  `waitForDone()` before reading `live()`. That was done, and the test
  still failed under load at **39** live tasks. The count was never
  measuring live tasks at all: PySide keeps a Python reference to every
  runnable handed to `QThreadPool.start()` — `gc.get_referrers` on a
  survivor returns a `list` and the `QThreadPool` itself — and purges
  those entries lazily. Measured 1, 26, 54 and 163 survivors across
  otherwise identical runs, with `shiboken6.isValid` reporting **0** live
  C++ objects every time. So the assertion tracked PySide's purge
  cadence, and a loaded machine was indistinguishable from the
  one-per-tick defect.

  The fix is `live()` counting only objects whose C++ side is still
  alive. The ceiling goes from `polls // 10` to **0** — not INV-12's one,
  because the drain has ended the window that invariant bounds.

  **The drain is kept and its mutant survives, which is recorded rather
  than papered over.** Deleting `controller.stop()` leaves the test green
  — 0 of 6 red under load, 0 of 3 quiet, at both ceilings. It stays on
  the § T9 distinction: a surviving mutant proves the race is hard to
  lose, not that there is none. Without it "zero" holds only because the
  last `run()` has always returned by the time the count is taken, which
  is the timing assumption this item exists to remove.

  Mutation: re-injecting `setAutoDelete(False)` reports **200 more live
  tasks after 200 completed polls** — the exact one-per-tick signature,
  so the original LWSM-1099 defect is still caught.

  Also closes **known-issue-035** ahead of its named owner LWSM-1011.
  That entry called it "a timing property of the pool rather than of the
  code under test", which was exactly right; it guessed the wrong side's
  reference.
  **Layman:** One test sometimes fails for reasons that have nothing to do with a bug, which will eventually redden a build for no reason.
  Kind: test.
  Source: in-session-2026-08-20 (hit twice while pushing LWSM-1157).
  Lanes: tests.

## P05 — Start, stop, restart (criterion 2)

**Theme:** the buttons. [ADR-0003](docs/decisions/0003-launch-via-project-scripts.md)
is the contract.

### 🎨 Features

- ✅ [LWSM-1009] **P05: Supervisor spawns and reaps process groups.**
  `subprocess.Popen(start_new_session=True)` with an
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
  Resolved 2026-08-14 (e559645): `src/lwsm/supervisor.py`, core, no Qt
  at all. Start is `Popen(start_new_session=True)` with an argv, `cwd` at the
  project, merged output to a per-project file; stop signals the process
  **group** and reaps it last. The acceptance case passes — a `start.sh`
  spawning a Python child that binds a port leaves nothing holding the port.
  **Two deviations from this bullet, both deliberate.** The `or the port is
  still bound` escalation is NOT implemented: ADR-0003 replaced it, because
  that `or` fires exactly when our child is already gone and something else
  holds the port, so it signalled a recycled PID. A bound port after a stop
  is reported as a warning on `StopOutcome`. And rotation copies-and-truncates
  rather than renaming, because the child holds a duplicate of our descriptor
  and a rename would leave it writing into an unlinked inode — which is also
  why the log is opened `O_RDWR` (`pread` on a write-only fd is `EBADF`).
  Twelve mechanisms mutated, twelve died.

- 📋 [LWSM-1028] **P05: service-managed projects driven through `systemctl`.**
  A project owned by a systemd **user unit** gets
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

- ✅ [LWSM-1010] **P05: start / stop / restart in the UI with the optimistic overlay.**
  Buttons wired through `ProjectController`,
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
  Blocked 2026-08-14, and the declared dependency list was incomplete.
  This bullet declares LWSM-1009 only, and LWSM-1009 shipped that day — but
  **`ProjectRecord` carries no launcher**, so Start has nothing to spawn.
  `registry.py`'s schema v1 reads `name`, `path`, `port` and `port_override`
  and nothing else; `argv` and `kind` are **LWSM-1007's** file-format fields
  (`docs/specs/LWSM-1007-registry-persistence.md § 4.1`, where `argv` is a
  member of `DETECTED_FIELDS`, and § 4.2's example record carries
  `"argv": ["npm", "run", "dev"]`). `Supervisor.start` takes an argv because
  there is nowhere else for one to come from.
  So **LWSM-1010 declares LWSM-1007 as well**, and this was found by building
  LWSM-1009 rather than by reading — the ordering that put start/stop ahead of
  the rest of P03b was right about LWSM-1009 and wrong about what follows it.
  The rejected shortcut, recorded so it is not re-proposed: deriving the argv
  by running `scanner.scan()` at Start time. It scans a *root* for candidates
  rather than one known project, the app's list comes from `projects.json`
  which has no argv to compare against, and it is a workaround for a missing
  field rather than the field (`coding.md § 1.2`).
  Resolved 2026-08-14 (d3e5673). Start / Stop / Restart per row, wired through
  `ProjectController` to LWSM-1009's `Supervisor`, with the bounded optimistic
  overlay. `ProjectStatus` gains `STARTING` and `STOPPING`; neither is derived,
  which is why `_classify` never returns one.
  **The overlay rule is the part that is easy to get wrong.** `design.md
  § State management` says both "discarded the moment a poll returns a derived
  state" and "a slow start keeps the overlay until a poll disagrees", and those
  cannot both be literal: a server that has not finished binding reads as
  *stopped*, so clearing on any derived state drops a `starting` overlay on the
  very next tick and the row flickers back. The overlay therefore settles on the
  state it was heading FOR. **`design.md` was not edited** — the two sentences
  are reconcilable and the code records which reading wins.
  Also: the overlay is set only on a spawn that actually happened; an
  unconfirmed launcher **asks** rather than failing (LWSM-1046's UI half, showing
  the resolved path and exact argv, defaulting to No); a restart is sequenced
  through the stop's completion; and a `running (foreign)` project reports that
  it cannot be stopped from here rather than pretending.
  Nine mechanisms mutated, nine died — after one inert mutation was caught and
  rewritten, which is the trap `CLAUDE.md` already records twice.

- ✅ [LWSM-1016] **P05: open in browser.**
  Opens
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
  Resolved 2026-08-14 (008cf8f). An Open button per row,
  `http://localhost:<bound port>/` built through `QUrl`. **Success criterion 2
  is now closed end to end**: a project can be started, seen to be running,
  opened in a browser and stopped.
  The port is read from the row the controller reports **at click time**, never
  cached when the button was created — ADR-0003 records a sibling project that
  shipped the other version and kept POSTing to a port the server had left.
  Enabled exactly while a port is observed bound, which today is `running`,
  including a server this manager did not start (ADR-0004 classifies from the
  socket table, not from ownership). Not while `starting`: there is no bound
  port yet.
  **Four of six mutants survived the first pass and every one was a real gap** —
  no test reached the overlay states, every fixture had one row so the
  loop-variable closure bug was invisible, one mutation had not applied cleanly,
  and `QUrl` vs an f-string is indistinguishable here because `port` is an
  `int` validated to 1-65535. That last one is now recorded in the docstring as
  consistency with `design.md § Custom project actions` rather than as a hole
  being closed; the live version of that rule is LWSM-1121's user-authored
  `open_url`.
  Corrected 2026-08-19 (LWSM-1141). **Two statements in this bullet are now
  wrong and are superseded rather than deleted**, because the record of what
  shipped is what makes the correction legible: "Enabled in all three running
  states, including `running (foreign)`", and the resolution note's "Enabled
  exactly while a port is observed bound, which today is `running`, including a
  server this manager did not start".

  Open is now enabled only for a server THIS manager started. ADR-0004:84-86
  carries the threat model and governs (user decision, 2026-08-15): `chdir()` is
  free, so any local process can bind a project's port, be classified `running`,
  and have this app send the user to it — localhost phishing with the app's
  credibility behind it. The ADR's own mitigation is a disclosure dialog, which
  needs a state model that can tell foreign from managed; restricting Open to
  the supervisor's running set is the interim, and LWSM-1154 carries the rest.

  Everything else here still holds, including the part that mattered most: the
  port is read from the row at CLICK time and never cached at build time.

- ✅ [LWSM-1055] **P05: a per-project browser choice for Open in browser.**
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
  Resolved (2026-08-24) by LWSM-1187, which was filed and built as a fresh
  user request without anyone noticing this bullet already existed. Recorded
  as the duplicate it is rather than closed quietly.

  **How it was missed, because the miss is the reusable part.** Phase 0's
  contract lookup ran `invariant_check`, which reads `docs/specs/` only and
  therefore cannot see a roadmap bullet. `task_priors` is the lookup that
  would have surfaced this one, and it was skipped on the grounds that the
  session was holding a contract it had just written itself -- which is
  exactly the case where the held contract is the LEAST likely to know what
  the roadmap already says.

  All three acceptance criteria are met, and the third was met only because
  this bullet was found. Two projects set to different browsers each open in
  the right one; a project with none set opens in the desktop default; and a
  browser since uninstalled falls back to the default **with a visible
  message** -- LWSM-1187 fell back silently, and the picker reading "Default
  browser" is not that message, because it is indistinguishable from a
  project nobody ever set one for.

  The two design constraints written here in August were reached
  independently and match: the list comes from the browsers the system
  reports rather than a free-text command, and the field is user-set only
  (`USER_FIELDS`), never populated by detection.

  Still open and untouched by this: **LWSM-1053**, which this bullet names.
  A sibling that opens its own browser at startup ignores the preference
  entirely, so that item is no longer cosmetic -- it now contradicts a
  setting the user deliberately chose.

---

## P06 — The full state model (criterion 3)

**Theme:** tell the truth in every case, including the awkward
ones. [ADR-0004](docs/decisions/0004-runtime-truth-from-probing.md)
is the contract.

### 🎨 Features

- 📋 [LWSM-1011] **P06: the seven-state classifier.**
  One
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

- 📋 [LWSM-1038] **P06: confirmed ports — detection learns from what actually happens.**
  The first time a project is observed
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

- 📋 [LWSM-1034] **P06: health check — bound is not the same as working.**
  An optional HTTP `GET` to `http://localhost:<bound
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

- 📋 [LWSM-1012] **P06: foreign-server adoption and guarded stop.**
  A server started outside the app shows as running and
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

- 📋 [LWSM-1054] **P06: cover the sibling that respawns itself detached.**
  project-e's settings page has a Restart button that
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

- 📋 [LWSM-1154] **P06: the foreign-server disclosure dialog Open still owes.**
  ADR-0004:84-86 requires that Open-in-browser on a `running (foreign)` row
  "carries the same disclosure the Stop path does: the holder's executable
  path, uid, cmdline and start time, shown before anything opens."

  LWSM-1141 shipped the INTERIM: Open is restricted to servers the supervisor
  started, which the running set answers exactly. That is safe and it is not
  what the ADR asks for — a legitimately foreign server the user does want to
  open is now unreachable from the app, with no explanation on the row.

  Blocked on a state model that can tell foreign from managed: `_classify`
  still returns three states (`RUNNING` / `STOPPED` / `UNKNOWN`), so there is
  nothing to trigger the dialog on. LWSM-1011's seven-state classifier is what
  unblocks it.

  Acceptance: a red test asserting that Open on a `running (foreign)` row
  shows the four disclosure fields BEFORE any URL is opened, and that
  declining opens nothing; plus one asserting a managed row still opens with
  no dialog. The `confirm` seam is the shape to reuse — it already exists for
  ADR-0003's trust gate and is injected for exactly this reason.
  Dependencies: LWSM-1011.
  **Layman:** When the app can tell a server it started from one it did not, Open should come back for foreign servers — behind a dialog that first shows you exactly what is holding that port.
  Kind: security.
  Source: in-session-2026-08-19 (LWSM-1141 residual).
  Lanes: ui, tests.

## P07 — Ports (criterion 4)

**Theme:** never launch into an occupied port, and make
reassignment stick. [ADR-0002](docs/decisions/0002-port-contract.md)
is the contract.

### 🎨 Features

- 📋 [LWSM-1013] **P07: the conflict warning UI.**
  When the
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

- 📋 [LWSM-1041] **P07: "what's using this port?" lookup.**
  A
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

- 📋 [LWSM-1037] **P07: suggest a free port.**
  When reassigning,
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

- 📋 [LWSM-1014] **P07: port override, validated and persisted.**
  Assign a different port from the UI; validated at
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

- 📋 [LWSM-1015] **P08: live log panel.**
  Tails the per-project
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

- 📋 [LWSM-1036] **P08: find the error in the log.**
  A **jump to
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

- 📋 [LWSM-1017] **P09: minimal system tray — show/hide and quit.**
  Closing the window hides to tray and leaves servers
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

- 📋 [LWSM-1029] **P09: custom per-project actions.**
  A
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

- 📋 [LWSM-1030] **P09: set `LWSM_MANAGED` so siblings suppress their own tray.**
  The manager sets `LWSM_MANAGED=1` in every
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

- 📋 [LWSM-1042] **P09: crash-loop guard.**
  Any path that starts
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

- 📋 [LWSM-1027] **P09: start-at-login, per project.**
  A
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

- ✅ [LWSM-1018] **P09: settings dialog.**
  Edits scan roots, poll
  interval, slow-start threshold, log-buffer size and tray behaviour, all
  persisted to `settings.json` with its own `schema_version`.
  Dependencies: LWSM-1007.
  **Layman:** A settings screen for the folders it scans and how
  often it checks.
  Kind: implement.
  Source: in-session-2026-08-03.
  Priority: 3.
  Lanes: ui, tests.
  Decision (2026-08-20, user). **This is a `P04` item, not P09** — commit
  under `P04:` / `LWSM-1018:`, despite the headline this bullet still
  carries. The headline is left as filed rather than rewritten, because
  `amend_headline` is refused on a store-backed project and the next
  render would revert a hand edit; read this note as the authority.

  **Tray behaviour is OUT of scope.** The filed scope names it, and there
  is no tray to configure — the tray is P09. Build the fields that exist
  today: scan roots, poll interval, slow-start threshold and log-buffer
  size. Tray configuration moves to P09 alongside the tray itself.

  Asked because the status header and this bullet disagreed on the phase,
  and the answer changes both the commit prefix and the scope. Not an
  open question any more; do not re-ask it.
  Resolved (2026-08-21). Shipped as THREE fields, not the four
  filed, and both absences were settled with the user rather than
  dropped quietly.

  Scan roots stay in the `scan-roots` file (LWSM-1144); the dialog
  edits that file in place. Copying them into settings.json would
  have bought a migration and a second owner for no user-visible
  gain, and LWSM-1144's own docstring already said this item owned
  the UI while that file was the setting.

  There is no slow-start threshold, and there cannot be one:
  ADR-0004 § Slowness is not failure deleted the 15-second
  `starting` deadline on 2026-08-03, on the measured evidence of a
  healthy project that takes about 40 seconds to bind. A setting
  for it would re-introduce the defect that ADR reversed.

  Poll interval and log cap live in settings.json and both apply
  WITHOUT a restart — QTimer.setInterval is honoured on a live
  timer, and rotate_if_needed re-reads Supervisor.max_log_bytes
  each poll. settings.py owns both defaults; controller and
  supervisor alias them, so the file's default and the code's
  default cannot drift.

  New module src/lwsm/settingsdialog.py, wired through the
  open_settings seam LWSM-1146 left for it, so mainwindow needed
  only two accessors. 1013 tests (was 971), local-ci.sh green.

  Ten mutants run, nine killed. The survivor was worth more than
  the kills: a redundant bottom-up sort in _remove_roots, inert
  because the row is looked up fresh on each pass. Removed, and
  the real stale-index defect shape is killed by the same test.

- 📋 [LWSM-1053] **P09: decide whether an unattended start may open a browser.**
  A sibling's launcher may open the user's browser on
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

- ✅ [LWSM-1185] **Hide a project from the list, with a View menu toggle to bring it back.**
  `ProjectRecord.hidden` already exists: parsed, range-checked,
  persisted, and carried through both merges as a USER field. Nothing
  reads it. So the storage half is done and has been for some time,
  and what is missing is a consumer — the same shape as a method with
  no production caller, one layer up.

  Decided with the user (2026-08-24): hiding removes the project from
  the list, and a **Show hidden** tick in the View menu brings hidden
  rows back so they can be unhidden. Nothing may become unrecoverable
  without editing the file by hand.

  Note for the test: `hidden` is a user field, so a rescan must
  preserve it. `USER_FIELDS` already covers that, and a test should
  say so rather than assume it.
  Resolved (2026-08-24): `RowView` carries `hidden`, the row owns a
  `hide_action` under Qt's `ActionsContextMenu` policy, and the View
  menu gained a checkable **Show hidden projects**. Filtering hides
  rows and never rebuilds them, so the stored flag and the live
  needle are two independent reasons to be off screen and neither
  can resurrect a row the other excluded (INV-13).

  The marker is rendered TEXT, not a colour: the announcement is
  built from the rendered cells so no accessibility-only string can
  drift, and colour alone carries no meaning to a screen reader.

  `ActionsContextMenu` was chosen over a `contextMenuEvent` of our
  own precisely because it leaves no wiring a test cannot reach —
  Qt renders `actions()`, and there is no `menu.exec()` to avoid.
  The tests drive the action out of `actions()` rather than the
  method it calls.

  Also extracted `_write_records` from `_apply_merge`. Hiding is
  the third writer, and the write gate, the `RegistryError` report
  and the `self._load` refresh are the same three rules each time —
  LWSM-1166 was that refresh being read from the wrong place, and a
  second copy would be a second place to repeat it.

  Mutants: eight against the window, one against the controller,
  all killed. One survivor on the first pass was a real pre-existing
  gap and is now closed — nothing checked that a SUCCESSFUL write
  stops the next identical rescan rewriting the file, which is the
  whole purpose of the refresh. Full gate green.
  Confirmed in the REAL APP by the user (2026-08-24): a project can
  be hidden from the row's context menu and brought back through
  View → Show hidden projects. Recorded because a green suite is not
  evidence for anything the desktop owns, and the suite was already
  green when this was still unverified.
  **Layman:** Lets you take a project you do not use off the list, and get it back when you want it.
  Kind: feature.
  Source: user-request-2026-08-24.
  Lanes: window, registry.

- ✅ [LWSM-1186] **Show the app version in the title bar.**
  The window title is a static translated string (`MainWindow._window_title`).
  `__version__` already reaches `app.setApplicationVersion` and `--version`, so
  the value is in hand and only the title omits it.

  Decided with the user (2026-08-24): show the version unconditionally,
  including the current `0.0.0`. A rule suppressing it below 0.1.0 would exist
  only to be deleted, and nobody would remember to delete it.

  Note for the test: the title is rebuilt on `LanguageChange`, so the version
  must survive a retranslate. Assert that, not only the initial title.
  Resolved (2026-08-24): `_window_title` returns
  `translate(_TR_CONTEXT, "Local Web Server Manager %1").replace("%1",
  __version__)`.

  **The version is INSIDE the translated string, not appended to it**, which
  `port_label`'s own comment and the existing translator test both require:
  a translation is data from outside the program, so `str.replace` rather
  than `str.format`, and a translator must be able to move the number.

  **The mutation run found a vacuous assertion in this item's own test and
  it was removed rather than kept.** The draft sent `LanguageChange` and
  re-asserted the title. With no translator installed a retranslate rebuilds
  the identical string, so that assertion held whether or not the rule did —
  M3, deleting `setWindowTitle` from `changeEvent`, left it green. What
  actually pins the version across a retranslate is
  `test_a_translator_installed_later_reaches_an_existing_row`, whose
  uppercasing translator makes the two titles differ; M3 dies there. The
  test now says so in its docstring, so the absence reads as a decision.

  Two existing assertions pinned the old contract (`"LOCAL WEB SERVER
  MANAGER"`) and were re-fixtured to the new one rather than loosened.
  Asserted against `__version__`, never the literal `0.0.0`, so the first
  release bumps the constant instead of reddening CI.

  Three mutants, three killed: no-op the `%1` substitution, drop the
  placeholder from the source string, and stop rebuilding the title on
  `LanguageChange`. 1171 green, local-ci green.
  **Layman:** The window's title bar tells you which version of the app you are running.
  Kind: feature.
  Source: user-request-2026-08-24.
  Lanes: window.

- ✅ [LWSM-1187] **Choose a preferred browser per project, from a dropdown in the row.**
  `_open_project` calls the injected `open_url` seam, defaulting to
  `QDesktopServices.openUrl` — always the desktop's default, the same for every
  project.

  Decided with the user (2026-08-24), in this order and each answer narrowing
  the next. The choice is PER PROJECT. It lives as a control in the ROW itself,
  beside the port and the buttons — not in Preferences, and not in the
  right-click menu LWSM-1185 just built. The list offered is the browsers
  already installed, read from the desktop's own registered handlers, and the
  user never types a command. That last part is the load-bearing one: a
  free-text command would be a new "run a binary named in a config file"
  surface, which is exactly what ADR-0003's trust model exists to gate. Reading
  the desktop's own handler list avoids the surface rather than gating it.

  Default stays the system browser for any project with nothing chosen.

  The stored field is a USER field, so `USER_FIELDS` must carry it or LWSM-1007
  INV-1 breaks and the next rescan wipes the choice.

  Six notes for the build, each of which has already cost this project a cycle
  in a neighbouring item.

  - The row's columns are aligned by `natural_widths` / `apply_column_widths` /
    `_align_columns`, a fixed 3-tuple today. A fourth column joins all three.
  - LWSM-1174 is open and says a long name already pushes the buttons out of
    reach unrecoverably. A new column must not make it worse — fixed width,
    never content-driven.
  - The row announcement is built from the rendered cell strings and gated on
    the accessible NAME (LWSM-1141). A combo box renders no cell string, so it
    needs an explicit accessible name or the announcement silently loses it.
  - `MIN_TARGET_PX` puts a 24 px floor under every clickable target, and
    LWSM-1032 says that floor belongs in the SOURCE, not only in an assertion.
  - Keyboard-first navigation (LWSM-1040) rests on Qt propagation rather than
    guards. A focused combo box consumes digits and arrow keys — check the
    row's Enter still clicks the enabled button.
  - Theme and language both re-render a row, so the combo's own strings need
    `_retranslate` and `apply_theme` like every other cell.
  Resolved (2026-08-24): a `QComboBox` per row, between the port and the
  buttons, backed by a new core module `browsers.py` (no Qt at all, like
  `placement.py`) and a `browser` USER field on `ProjectRecord`.

  **The list is the desktop's own registered `x-scheme-handler/http`
  handlers, and nothing here is ever executed as text.** That is the whole
  security argument and it is why this needed no trust gate: the entries
  offered are ones the session would already run for any clicked link, so a
  per-project browser adds no new surface. A free-text command would have
  needed ADR-0003's gate; reading the handler list avoids needing one.

  **Running the matcher over the REAL population found what no fixture
  would have.** 381 desktop entries on this machine, 3 selected, and one of
  them is a Flatpak whose `Exec` carries `--file-forwarding` and `@@u ... @@`
  markers. Those are not Desktop Entry field codes; `flatpak run` consumes
  them itself (checked in `man flatpak-run` rather than assumed), so passing
  them through with the URL between them is correct. Locked as a regression
  test.

  **It could not ship without LWSM-1174, and that is the finding worth
  keeping.** `design-accessibility.md` requires a row's whole set of
  controls to sit inside the ~600 px band a magnifier user reads through.
  Measured: 593 px with a 30-character name and no picker -- 7 px inside the
  limit -- and 677 px with the picker. The name column is what gave way; put
  to the user, who chose that over icon-only buttons or a second row.

  Ten mutants, ten killed, but only after three survived a first pass and
  each exposed a real weakness rather than a gap in the code. The signal
  blocker's test set the picker to the value it already held, and Qt emits
  nothing when the index does not move. The scheme refusal's test asserted
  `BrowserError` and passed with the guard deleted, because the spawn then
  fails and raises the same type -- it now asserts the process was never
  spawned. And the group-header test could not distinguish the mutant twice
  over, because `setdefault` protects any key `[Desktop Entry]` declares;
  the case with no backstop is a key that group OMITS.

  **Live run found a regression the suite could not**: every control's
  accessible name was built from the label, which is now elided, so a screen
  reader got "Start customer-dash...". The existing tree test's fixture name
  is too short for elided and full to differ. Fixed and pinned.

  conftest now pins `XDG_DATA_HOME`/`XDG_DATA_DIRS` at an empty directory,
  the fourth and fifth variables to earn it and for the third time the same
  argument: an unpinned test built its dropdown from whatever the author had
  installed. It also took the suite from 24.3 s to 17.7 s, because every
  window had been walking 381 files.
  1230 green, local-ci green.
  **Layman:** Each project can open in the browser you prefer for it, chosen from a dropdown on its own row.
  Kind: feature.
  Source: user-request-2026-08-24.
  Lanes: window, registry.

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

- 📋 [LWSM-1043] **P10: decide how updates reach users — research first.**
  The user already runs **OneUp**
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
  Progress (2026-08-24): the user asked for an auto-update feature and
  pointed at **finbreak** as a project that has already shipped one. Half
  the research this bullet asks for is therefore done; the OneUp half is
  NOT, and this bullet's warning still stands.

  **Option B -- build our own -- is now fully specified**, from a read of
  `/mnt/Games/Scripts/Linux/finbreak/` (FIBR-0054 Linux, FIBR-0131 Windows).
  Same stack: PySide6, frozen to an AppImage. Shape: `services/update.py`
  (policy: prefs, version grammar, asset picker, verify), `update_fetch.py`
  (the ONLY networked file -- https-only including on redirects, bundled
  certifi CA, byte cap, timeout), `update_key.py` (one baked-in Ed25519
  public key), `update_installer.py` (a Protocol seam with one
  implementation per package format, `detect_installer() -> None` making the
  whole feature inert for an unpackaged run), two `QThread` workers and a
  non-modal dialog. Checks `api.github.com/repos/<o>/<r>/releases/latest` on
  launch only -- no polling timer -- opt-in and OFF by default. Ed25519
  signature verification is mandatory before anything runs.

  **Its four hardest-won details, each a bug it shipped and fixed.** A
  frozen binary's OpenSSL looks for CA certificates where its BUILD host
  kept them, so the update check silently did nothing on any other distro --
  fixed by bundling certifi. `urlopen(context=...)` builds a throwaway
  opener with the DEFAULT redirect handler, so an https-only guard on the
  first request does not survive a 3xx to http. The verified bytes must be
  re-written to a fresh temp immediately before hand-off, or the file that
  is installed is not the file that was checked. And relaunch-after-install
  took **three** attempts on Linux: the working shape is a detached
  `/bin/sh` that waits for the old PID to die and then execs, with the
  loader variables restored from PyInstaller's `<VAR>_ORIG` -- otherwise the
  system shell inherits the app's private library path and dies before it
  can reopen anything.

  **The structural trap worth knowing before starting**: the version doing
  the relaunching is the one you are updating FROM, so every relaunch fix
  only takes effect from the NEXT update. finbreak told users this three
  separate times in its changelog.

  **Do not read any of this as a decision.** This bullet says the option
  most likely to be wrong is "build an updater", and that judgement is
  untouched -- what changed is that the cost of option B is now known
  rather than guessed. OneUp still has to be read, and it remains the
  cheaper answer if it fits.

  **Blocked on LWSM-1021 either way.** finbreak's updater is inert unless
  the app is a packaged artifact -- `detect_installer()` returns None for a
  `python -m` run -- and this project has no AppImage yet. There is nothing
  for an updater to replace until there is.

- 📋 [LWSM-1052] **P10: a local release script, run before CI is asked to build one.**
  `scripts/local-release.sh` builds and
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
  Filename collision, resolved (2026-08-18): `scripts/local-release.sh` NOW EXISTS and does a different job — LWSM-1151 shipped it as the release PREFLIGHT (cut-release Phase 0: recipe validity, version lockstep, pattern uniqueness, tag freedom, dated changelog section, roadmap agreement, CI cost). It contains no AppImage step and cannot, because LWSM-1021 has not built one. **Do NOT create a second script and do NOT overwrite that one.** This item's work becomes: ADD an AppImage build-and-smoke-test step to the existing `scripts/local-release.sh`, for the same reason this bullet already gives — one script is the source of truth, so two cannot drift. The bullet's other premise needs correcting too: it says "the release workflow calls it", and there IS no release workflow. CI fires on push and pull_request only, with no tag trigger and no release trigger, so nothing on GitHub checks a release at all; the script is the only gate a release gets rather than a local mirror of a remote one. That strengthens this item rather than weakening it — a packaging bug has nothing downstream to catch it. Dependency on LWSM-1021 is unchanged.

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

- ✅ [LWSM-1142] **Desktop entry and icon for a local install, ahead of the AppImage.**
  Lands the `.desktop` entry and icon half of LWSM-1021 early, against
  the development checkout rather than an AppImage. The two halves are
  separable: the entry and icon are useful the moment they exist, while
  the AppImage is blocked on LWSM-1017 and sits in P10.
  **LWSM-1021 keeps the AppImage and is NOT closed by this** — what it
  loses is only the obligation to author the entry and icon from
  nothing; it re-points `Exec` and `TryExec` at the bundle and reuses
  both files.
  Named reverse-DNS (`io.github.milnet01.LocalWebServerManager`) so the
  AppImage inherits the same identity and nothing has to be re-pinned.
  The icon is the app's own flat palette — `design.md § Visual
  language` forbids gradients and bevels, and an icon is not exempt.
  **`QGuiApplication.setDesktopFileName` is part of the deliverable,
  not decoration.** On Wayland the compositor matches a window to a
  launcher by `app_id`, which Qt derives from `argv[0]` unless told
  otherwise. Without it the pinned entry and the running window are two
  different things in the task manager, which is what a pin is for.
  Acceptance: `desktop-file-validate` clean; the entry starts the app
  from the launcher; the running window associates with the pinned icon
  rather than adding a second one.
  Dependencies: none.
  Resolved (2026-08-18): `packaging/` holds the icon and the entry,
  `scripts/install-desktop-entry.sh` installs both under
  `$XDG_DATA_HOME` with no root and no system paths touched.
  Verified on the live session rather than by inspection: the entry
  validates, `gio launch` on the INSTALLED file starts the app, the
  titlebar carries the icon, and the panel shows ONE entry with the
  running indicator — so `setDesktopFileName` did its job and the
  window merged with the pinned launcher instead of adding a second.
  **Two things measured that were open questions.** `QIcon.fromTheme`
  returns null under `QT_QPA_PLATFORM=offscreen` — the theme search
  paths are populated by the platform theme, so a test asserting the
  icon resolves would fail in CI for a reason that says nothing about
  the icon. Under the real session it resolves to the 128px SVG.
  And known-issues' note that a `.desktop` launch can leave
  `build_child_env` with no `PATH` does NOT bite here: the launched
  process received a full `PATH` including `/usr/bin`, so npm, node
  and python3 launchers still resolve. The gap is real but needs an
  environment this one is not.
  The Exec rewrite is why the install is a script: the repo entry
  carries `Exec=lwsm`, correct once installed, and a checkout keeps
  that script in `.venv/` which is deliberately not on `PATH` — so a
  verbatim copy would appear in the launcher and fail to start.
  **LWSM-1021 keeps the AppImage** and now re-points `Exec`/`TryExec`
  at the bundle rather than authoring these two files.
  518 tests green; local-ci green.
  **Layman:** Gives the app a proper icon and a launcher entry, so it can be pinned to the panel and started like any other application instead of from a terminal.
  Kind: package.
  Source: user-request-2026-08-18.
  Lanes: build, ui.

- ✅ [LWSM-1143] **The installer built an icon cache that hid every other application's icons.**
  `scripts/install-desktop-entry.sh` (LWSM-1142) ran
  `gtk-update-icon-cache -q -t -f` over `$XDG_DATA_HOME/icons/hicolor`.
  **That directory is shared** — every application installing a per-user
  icon writes into it — and on this machine it held **90 icons** belonging
  to other applications, with **no `index.theme`**.
  Generating a cache there does not merely speed lookup up, it CHANGES
  it: once `icon-theme.cache` exists it is authoritative for that
  directory, and anything it does not list stops resolving. The cache
  produced was **1,932 bytes over 90 icons**, so most of them vanished.
  **Reported by the user**: about seventeen pinned launchers went blank.
  Fixed by deleting the cache and restarting plasmashell; the launcher
  list itself was never touched (31 entries before and after).
  Three findings worth keeping.
  **The blast radius was other software.** Installing one application's
  icon must not be able to change how a different application's icon
  resolves, and a step that writes into a shared directory can.
  **A best-effort guard did not make it safe.** The call was already
  `|| true` and tool-guarded, which protects against the command
  *failing* — it succeeded, and succeeding was the damage.
  **It was invisible to every check that ran.** `desktop-file-validate`
  passed, `shellcheck` passed, the icon resolved, the entry launched, the
  pin worked. The verification covered this app's icon and never asked
  what happened to anything else in the directory it wrote to.
  The step is removed rather than guarded: with no cache present the icon
  resolves from the file, so nothing was gained by it. Re-running the
  installer no longer creates one, verified, and six theme icons
  including three belonging to other applications still resolve.
  Dependencies: none.
  **Layman:** Installing this app's icon made most of the icons pinned to the user's taskbar disappear. Fixed, and the step that caused it removed.
  Kind: fix.
  Source: user-report-2026-08-18.
  Lanes: build.

- ✅ [LWSM-1144] **Where to scan is read from a config file, not hardcoded to ~/projects.**
  `default_scan_roots()` returned `(~/projects,)` and nothing could
  change it. **That is the whole reason the app looked unfinished.**
  Every part behind it works — the user's tree scanned to 7 projects
  with ports and launchers on the first try, and the window renders
  status, port and Start/Stop/Restart/Open per row — but pointed at a
  directory that does not exist it finds nothing and shows an empty
  window, with no indication that the LOCATION is the problem.
  Now read from `$XDG_CONFIG_HOME/localwebservermanager/scan-roots`,
  one directory per line, `#` comments and blank lines ignored, `~`
  expanded, order preserved. Until LWSM-1018's settings dialog exists,
  that file IS the setting; the dialog will write it.
  **An empty or comments-only file falls back rather than scanning
  nowhere**, because the two are indistinguishable to whoever wrote the
  file and silently scanning nothing is the exact failure this fixes.
  **A pre-existing test caught a real crash in the first version.**
  `default_projects_path()` raises `RegistryError` — NOT `OSError` —
  when there is no home directory, so the first handler missed it and
  `test_starts_even_when_there_is_no_home_directory` went red. Without
  that test a machine with no home would have died at startup, before
  there was any window to report it in.
  Dependencies: none.
  **Layman:** The app was only ever looking in one folder that most people do not have, so it always came up empty. Now you can tell it where your projects actually are.
  Kind: implement.
  Source: user-report-2026-08-18.
  Lanes: core, tests.

- 📋 [LWSM-1152] **Cut 0.1.0 once P04 closes — the first tagged release.**
  Decided with the user 2026-08-18. Nothing has ever been released: the
  version is 0.0.0 in all four files, there is no version tag (P02/P03
  tags are phase markers), no GitHub release, and every entry sits in
  CHANGELOG's `[Unreleased]`.

  **Why 0.1.0 and why after P04 rather than now.** As of today the app
  installs a desktop entry, finds projects and starts/stops/restarts
  them — a usable tool, and enough entries to make a substantial first
  release. P04 (menu bar, themes, settings) is the difference between
  "works" and "looks finished", and it is the next work anyway. Cutting
  after it means the first impression is the finished-looking one.
  Rejected: staying at 0.0.0 indefinitely (a lot of shipped work
  invisible to anyone not reading commits), and cutting immediately
  (the release path has never run, and a mid-P04 release would be
  followed by another within days).

  **The blocking list is already known** — `./scripts/local-release.sh
  0.1.0` reports exactly one blocker today: no dated `## [0.1.0]`
  section. Everything else is clear, and the recipe is proven to apply
  (dry-bump verified, post_check green on the bumped tree).

  Order when P04 closes:
  1. Move `[Unreleased]` into a dated `## [0.1.0] — YYYY-MM-DD`
     (`changelog-format.md § 4.3` step 1; `cut-release` refuses to
     author it, deliberately).
  2. `./scripts/local-release.sh 0.1.0 --dry-bump` — expect READY.
  3. `cut-release 0.1.0`.

  Dependencies: P04 (LWSM-1146, LWSM-1031, LWSM-1147, LWSM-1018,
  LWSM-1148). NOT dependent on LWSM-1021/LWSM-1052 — an AppImage is a
  distribution channel and 0.1.0 is a source/tag release; do not let
  packaging block the version.
  Confirmed (2026-08-19): the user was asked directly whether to re-gate this — 69 entries sit unreleased and nothing has ever shipped — and chose to HOLD as filed. 0.1.0 stays gated on P04 closing. The reasoning was that the app is not yet keyboard- or magnifier-usable, which is P04's whole purpose, so shipping first means a first release the primary user cannot drive. **Do not re-open this as though the user had gone quiet** — the question was put and answered. What would change it is P04 closing, not the changelog growing further.
  **Layman:** Publish a first proper version once the appearance work is done, so people get something with a real version number instead of 0.0.0.
  Kind: release.
  Source: user-decision-2026-08-18.
  Lanes: release.

- 📋 [LWSM-1188] **Define what 1.0.0 means, and hold the line on it.**
  Nothing in this repository defined 1.0.0 before this bullet. Checked
  2026-08-24 across every markdown file: the only match is a generic example
  inside `roadmap-format.md`. LWSM-1152 defines 0.1.0 and stops there, so
  "what gets us to 1.0?" had no answer anyone could read.

  **The definition, agreed with the user 2026-08-24: 1.0.0 is the five
  success criteria delivered end to end, plus the security fold-in, plus a
  packaged download.** The criteria are not invented here -- the roadmap
  already labels five phases `criterion 1` .. `criterion 5`, from
  `discovery.md`, and they are the app's own statement of what it is for.

  In scope, with the open count on the day this was written:

  - criterion 1, find projects (P03b) -- 5
  - criterion 2, start / stop / restart (P05) -- 1
  - criterion 3, the full state model (P06) -- 6
  - criterion 4, ports (P07) -- 4
  - criterion 5, logs (P08) -- 2
  - the security fold-in (FP01) -- 3
  - packaging, so there is something to download (P10) -- 5

  Deliberately OUT, and this is the half that makes the bullet worth
  having. P09's shell work -- tray, restore-session, custom actions,
  start-at-login, crash-loop guard -- is 7 open items of genuine value that
  nobody needs in order to use the app for what it is for. DS01's debt and
  the older fold-ins are another 9. Both go to 1.1. A 1.0 that waits for
  every open item is a 1.0 that never ships, and this project has 57 open
  items and has never released anything.

  **The counts are a snapshot, not a contract.** What is fixed is the
  membership rule -- the five criteria, security, packaging -- so a bullet
  filed into P06 tomorrow is in scope by construction and needs no
  renegotiation here.

  Order: 0.1.0 first (LWSM-1152, gated on P04 closing, which is gated on
  FP08). This is the milestone after it, not a replacement for it.

  Watch for the failure this bullet exists to prevent: scope creeping in
  because an item is nearly done, or because it sits next to one that is in
  scope. The test is the membership rule above, never how finished
  something feels.
  Dependencies: LWSM-1152, LWSM-1021.
  **Layman:** Write down what "finished enough to call it version 1" means, so it is a target rather than a feeling.
  Kind: release.
  Source: user-decision-2026-08-24.
  Lanes: release, docs.

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

- ✅ [LWSM-1057] **DS01: two measurements of the pre-scrub commit count disagree.**
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
  Resolved (2026-08-15): **the sweep's first branch is the right one — both were
  true when written, and neither figure is changed.** Measured:
  `git rev-list --count 4ef2781^` is **24** and `git rev-list --count 9dcabc9^`
  is **26**. `4ef2781` (2026-08-03 15:37) is the commit that authored the FP01
  bullet saying 24; `9dcabc9` (16:36) is the scrub, whose own note says 26. Two
  commits — `4ef2781` and `c428e7a` — landed in the intervening 59 minutes. So
  the counts differ because the tree grew between them, not because either is
  wrong, and the fix is a date on each rather than a rewrite. The Layman line
  above is left as filed, and is the thing this bullet disproves: it says "the
  real number looks like 26", which assumed a single right answer existed.
  Both call sites now carry their moment (`ROADMAP.md` § FP01 intro and
  LWSM-1045's body); `docs/journal/P01.md:57` is a dated past-tense record and
  is deliberately untouched, per the same frozen-record rule FP02 applied to
  LWSM-1026's resolution note.
  **Worth keeping:** a sweep that refuses to adjudicate a dated finding was
  right to refuse. Had it "corrected" 24 to 26 it would have destroyed the
  evidence that the tree moved, which is the only thing that explains the
  disagreement.

- ✅ [LWSM-1058] **DS01: decide whether contract-landed-only items are 🚧 or 📋.**
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
  Resolved (2026-08-15, user decision): **no new vocabulary — split them by what
  is actually true, and the sweep's own premise had gone stale.** It says
  "LWSM-1046 … LWSM-1050 are all 🚧"; by 2026-08-15 that was wrong for two of the
  five, in opposite directions. Final state, each verified against the tree
  before flipping rather than read off the bullet:
  - **LWSM-1046 stays 🚧** — the core half shipped in `supervisor.py` with
  LWSM-1009; the UI half is genuinely open. 🚧 is accurate.
  - **LWSM-1047 stays 🚧** — same shape: every signal goes through a captured
  handle, the foreign path is open.
  - **LWSM-1048 was already ✅** and needed nothing.
  - **LWSM-1049 → 📋.** Contract only; its own body says implementation lands
  with LWSM-1011, which has not started.
  - **LWSM-1050 → ✅.** The implementation shipped with LWSM-1006 on
  2026-08-12 and the bullet was never flipped. All five clauses verified
  present in `scanner.py` first.
  **The lesson is the one worth keeping:** the sweep left this alone because it
  is "a question about the roadmap's own vocabulary", and the answer turned out
  to need no vocabulary at all — it needed somebody to read five bullets against
  the code. Doing that found one item three days overdue for a ✅ and one
  claiming work nobody was doing. A status nobody re-derives drifts in both
  directions, not just the optimistic one.

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
  Progress (2026-08-15): **re-confirmed by the user and scheduled with P10
  packaging.** All three are still undone — neither `SECURITY.md` nor
  `CODE_OF_CONDUCT.md` exists at the repo root, and ADR-0007 still carries all
  four unresolvable citations (`docs/decisions/0007-window-geometry-and-centering.md`
  lines 24, 34, 99 and 116). The question was put to the user as though the
  three lived only in a journal entry; **they do not — this bullet is exactly
  the item DS01 filed to prevent that**, and it did its job. Recorded because
  the near-miss is the useful part: a filed item nobody works looks identical to
  an unfiled one from any angle except a grep, and a session that greps for the
  *artefact* (`SECURITY.md`) rather than the *item* will re-file it. Nothing
  was duplicated.
  **One correction to the bullet body:** it says these are "in no roadmap
  item", which stopped being true the moment this bullet was written. Left as
  filed — it is a dated record of the state that justified filing.

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

- 📋 [LWSM-1161] **`write_json_atomically` now writes a file that is not JSON.**
  LWSM-1018's `save_scan_roots` writes the plain-text `scan-roots`
  file through `configfile.write_json_atomically`. Reusing it was
  the right call and is not in question: every line in that
  function was written after a measured defect (a FIFO that
  blocked forever, a symlink destroyed by `os.replace`, a
  `mkdir(parents=True)` leaving parents at the umask default, a
  600 MB read peaking at 1214 MB RSS), so a second, weaker atomic
  writer is exactly what `coding.md § 1.3` forbids.

  What is wrong is only the NAME. It takes bytes and knows nothing
  about JSON; three callers now use it and one of them writes text.
  `coding.md § 1.4`'s six-month test is the argument — a reader
  who trusts the name will not look for it in a text-file path.

  Scope: rename to `write_atomically`, update the three call sites
  (`registry.save_projects`, `settings.save`,
  `__main__.save_scan_roots`) and the two docs that cite it by
  name (CLAUDE.md's module map entry for `configfile.py`, and the
  `configfile.py` docstring). Deliberately NOT done inside
  LWSM-1018: it touches files that item had no other reason to
  open, which is the orthogonal edit `coding.md § 1.7` rules out.

  Picked up by § Standing quality passes at the next phase close,
  which asks precisely this question — what does a name now lie
  about.
  **Layman:** Rename a helper whose name stopped being true, so the next reader is not misled.
  Kind: refactor.
  Source: in-session-2026-08-21 (noted while shipping LWSM-1018).

- ✅ [LWSM-1189] **Two supervisor tests leave a real `sleep 30` running on the developer's machine.**
  Measured 2026-08-24, and it is the exact check `CLAUDE.md`'s own trap tells
  you to run: "the count before and after a full suite must be equal". It is
  not. `pytest tests/test_supervisor.py` leaves **two** live processes, every
  run:

  - `test_a_live_child_has_not_exited` -- cwd
    `/tmp/pytest-of-ants/.../test_a_live_child_has_not_exit0/demo-project`
  - `test_a_lowered_log_cap_rotates...` -- same shape

  Both launch `write_launcher(project, "sleep 30\n")` and neither stops what
  it started. They are reparented to init and outlive the run with their
  pytest tmpdirs already deleted, which is precisely the state the 2026-08-14
  note describes ("five orphans ... still holding their ports 2.5 hours and
  ~85 test runs later").

  **Pre-existing, and confirmed so** rather than assumed: the same two survive
  with the LWSM-1167 working tree stashed. Filed rather than fixed in that
  item's commit, because it is orthogonal to it (`coding.md § 1.3`/`§ 1.7`).

  The `supervisor` fixture already does the right thing -- it stops everything
  in `sup.running()` before closing -- so the fix is almost certainly to route
  these two through it rather than to add a second teardown.

  **Do not fix this by shortening the sleep.** A shorter sleep makes the
  orphan expire on its own and the check go quiet, which hides the defect
  instead of closing it; the launcher outliving the test is the thing being
  tested for.

  Worth pairing with a guard so it cannot regress: a session-scoped fixture
  that counts matching processes before and after and fails the run on a
  difference would make this class self-reporting, which is what the trap note
  has been asking a human to do by hand since 2026-08-14.
  Progress (2026-08-25): a THIRD leaker, found while shipping LWSM-1169.
  An orphaned `/bin/sh ./start.sh` was still holding on hours after its run;
  `/proc/<pid>/cwd` named the tmpdir of
  `test_a_stop_during_the_stop_sequence_is_still_idempotent`, so that test
  leaks one too and the bullet's list of two is short. Reading
  `/proc/<pid>/cwd` is what makes a stray attributable to a named test — a
  `pgrep` count alone says only that something leaked. The two tests added
  for LWSM-1169 leak nothing: measured before and after, the count was
  unchanged.
  Resolved (2026-09-02). Closed by LWSM-1204 rather than by the fix this
  bullet proposed, and the diagnosis here was the thing that was wrong:
  the tests were blamed ("neither stops what it started") when the defect
  was in `Supervisor.stop` itself. It enumerated the process group ONCE,
  before the first SIGTERM, so a `sleep` forked around the stop was in no
  list and was never signalled. Routing those two tests through the
  fixture would have hidden a production defect behind a test change -
  the fixture already calls `stop()`, and `stop()` was what leaked.
  Measured against the parent commit, attributed by /proc cwd rather than
  by pgrep: WITHOUT the fix, 2 strays, and they are exactly the two tests
  named here (`test_a_live_child_has_not_exited`,
  `test_a_lowered_log_cap_rotates`); WITH it, 0. The third leaker recorded
  in the 2026-08-25 progress note showed 0 in both runs.
  The guard this bullet asked for is IN: a session-scoped autouse fixture
  in `conftest.py` that fails the run and names the offender. It matches
  by CWD under the run's own temp directory, never by command line - a
  `pgrep sleep` cannot tell this project's orphan from another program's,
  and on this machine it does find both. PROVEN to fire rather than
  assumed: run against the pre-fix supervisor it failed the suite and
  named both tests by their tmpdir. No changelog entry - the leak was on
  the developer's machine, not in the shipped app; LWSM-1204 carries the
  user-facing half.
  **Layman:** Running the tests leaves two stray background processes behind every time, which build up until you notice and kill them.
  Kind: test.
  Source: in-session-2026-08-24.
  Lanes: tests.

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

- ✅ [LWSM-1067] **Settle where the version number lives.**
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
  Resolved (2026-08-18): brought forward from P10 because `cut-release --check` stopped at Phase 0a on the missing recipe — the bullet already said "earlier if a /bump recipe lands first", and this is that. **The open question is decided: the four literals STAY, and `importlib.metadata.version()` is rejected.** Two reasons, and the first is specific to the release path. An editable install caches its metadata, so between bumping `pyproject.toml` and re-running `uv sync` that call still reports the OLD version — and `cut-release` Phase 2 tests the bumped tree in exactly that window, so the derived value would be stale at the one moment it decides anything. Second, README.md and ROADMAP.md state the version as PROSE, which nothing can derive at run time, so a recipe is required whatever `__init__.py` does: deriving takes four files to three, never to one. A literal is always current with the file on disk; `scripts/check-version-drift.sh` is what makes four of them safe. Shipped: that script (pyproject.toml is the source of truth, the other three checked against it), `.claude/bump.json` (all four files, `tag: v{NEW}`, `post_check` = the script), and a `Version lockstep` step in `local-ci.sh` so drift fails TODAY'S push rather than surfacing later as a stopped release — one script, two callers, so they cannot disagree. Four contract tests in `tests/test_ci_contract.py` assert the recipe and the drift check cover the same files, that `post_check` is wired, that the gate runs it, and that no historical marker is in `files[]`. **Two things the recipe deliberately excludes.** `CHANGELOG.md`, because its dated section is authored (`bump-recipe.md § Notes` forbids listing a file a todo authors). And `docs/decisions/0002-port-contract.md`, which contains `0.0.0.0` — a BIND ADDRESS that a grep for the current version would have swept in; every entry was read before being listed, which is the precise failure that reference warns about. **Also normalised the ROADMAP line** from `**Current version:** 0.0.0 (scaffolded 2026-08-03).` to drop the parenthetical: bumping it would have produced "0.1.0 (scaffolded 2026-08-03)", claiming 0.1.0 was scaffolded in August, and the pattern is now stable across every future bump. Verified by running Phase 1a for real against a throwaway 9.9.9 — each of the four patterns matched EXACTLY once, post_check went green on the bumped tree, then reverted. 551 tests green.
  Process note (2026-08-18): the recipe's ROADMAP pattern is anchored on the blockquote prefix — `> **Current version:** {OLD}` — not on the bare string. Without the `> ` the pattern matched TWICE the moment this bullet's own resolution note quoted the line verbatim, so the dry run refused with "matched 2x, expected 1". A bump pattern that prose in the same file can duplicate is not specific enough, and a roadmap is a file that quotes itself by design. `bump-recipe.md § Notes` asks for enough surrounding text that the pattern "could only ever match the field"; this is what "enough" means when the file is a roadmap.

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

- 💭 [LWSM-1023] **Support more kinds of web server.**
  Detection
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

- 💭 [LWSM-1024] **macOS build.**
  Feasible in principle — macOS is
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

- 💭 [LWSM-1025] **Windows build.**
  Recorded with its reasoning so
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

- 💭 [LWSM-1044] **Startup ordering between projects — considered and declined.**
  Recorded so it is not re-proposed as a fresh
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

- 💭 [LWSM-1020] **Unix-socket servers.**
  ADR-0004 probes TCP
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
