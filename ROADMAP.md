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

- 📋 [LWSM-1005] **P02: one hand-written project renders a live
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
  as specified, including framework defaults, plus the extra
  sources robustness demands: `.env`, systemd `Environment=` /
  `ExecStart`, `docker-compose.yml` `ports:`, and a README
  `localhost:NNNN` at lowest confidence. Every value carries
  **its provenance** and a confidence of *detected* or *unknown*;
  conflicting sources are reported rather than silently resolved.
  Acceptance: against a fixture tree mirroring the seven real
  projects, each is found with the right launcher and port or an
  honest *unknown*, `node_modules` is never descended, and the
  fixture tree is the **regression corpus every future
  mis-detection gets added to**.
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

---

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
