# Changelog

All notable changes to LocalWebServerManager are documented in this
file.

The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Sections use the standard categories — **Added** for new
features, **Changed** for changes in existing behavior,
**Deprecated** for soon-to-be-removed features, **Removed**
for now-removed features, **Fixed** for bug fixes, and
**Security** for security-relevant changes.

The `[Unreleased]` block is required at the top, always —
even if empty. The Roadmap dialog reads it for current-work
signaling per
[`docs/standards/roadmap-format.md § 3.6.2`](docs/standards/roadmap-format.md).

## [Unreleased]

### Added

- **Pick which browser each project opens in** (LWSM-1187)
  Every project's row has a browser dropdown beside its port. Leave it on
  "Default browser" and Open behaves as before; pick Firefox for one
  project and Chrome for another and each opens where you chose. The list
  is the browsers already installed on your machine, so there is no
  command to type. If you later uninstall a browser you had picked, that
  project quietly falls back to your default and remembers the choice in
  case you install it again.

- **The title bar now tells you which version you are running** (LWSM-1186)
  The window is titled "Local Web Server Manager 0.0.0" rather than just
  the name, so the running version is visible without opening a menu.
  The number is part of the translatable text, so a translation can move
  it rather than having it welded to the end.

- **Hide a project you do not use, and show it again from the View menu** (LWSM-1185)
  Right-click a project (or press the Menu key on it) for "Hide this
  project". Hidden projects leave the list and the choice is saved.
  View → Show hidden projects brings them back, each marked "(hidden)"
  so you can tell which and unhide it. Nothing becomes unrecoverable
  without editing the file by hand.

- **Enter in the filter box jumps to the first matching project** (LWSM-1156)
  Type `/`, type part of a project's name, press Enter — you land on the
  first project that matches, instead of having to press Tab first. Enter on
  a project still starts or stops it, as before.

- **The window reopens at the size you left it, and a Centre on screen action** (LWSM-1033)
  Size and maximised state are remembered between runs, and **View → Centre
  on screen** puts the window back in the middle. Position is remembered too
  on X11. Under Wayland the desktop never tells an application where its own
  window is, so a position cannot be recorded there — the size still is, and
  a position already in the file is still restored. The values are plain
  numbers in `settings.json`, so a window you cannot reach can be fixed by
  editing the file.

- **Save and reload a project-settings profile** (LWSM-1148)
  File → Export profile writes your project list and your settings to a
  file you name; Import profile reads one back. An import is a merge, not
  a replacement: your own names, port overrides and notes come back from
  the profile, while what this machine detected — the launcher, the
  declared port — stays as this machine found it. A project the profile
  does not mention is left alone. A profile that cannot be read in full
  is refused with a reason rather than restored in part.

- **A Preferences dialog for the folders to scan, how often to check, and how much log to keep** (LWSM-1018)
  Reachable from Settings → Preferences. All three take effect
  immediately — no restart. The folder list is still the
  `scan-roots` file you could already edit by hand, and saving
  keeps any comments you wrote at the top of it.

- **Make the text bigger from inside the app — Settings > Text size, 100 % to 200 %, remembered between runs (LWSM-1032)**
  Five steps, applied to the desktop's own font rather than replacing
  it, so a machine already set to large text stays large and gets
  larger. The choice is stored beside the theme in settings.json.

- **Drive the whole list from the keyboard, and filter it down to what you are looking for** (LWSM-1040)
  Press `/` to jump to the filter box and type part of a project's
  name — upper or lower case, anywhere in the name — and the list
  narrows to what matches. Escape clears it and brings everything
  back. Number keys 1 to 9 jump straight to a project, counting the
  ones you can actually see rather than the ones behind the filter,
  and Enter starts the project you are on, or stops it if it is
  already running. The filter box shares the row with Rescan rather
  than taking a line of its own, so the list keeps its height.

- **A settings.json beside projects.json, holding the theme choice so it survives a restart** (LWSM-1031)
  A settings file that cannot be read never costs you a window: the
  app falls back to the defaults and says what it ignored.

- **Six colour themes plus high contrast in light and dark, switchable from Settings > Theme without a restart** (LWSM-1031)
  The six are adopted from finbreak. Every colour is checked by
  arithmetic against every background it can land on, and the two
  high-contrast palettes are held to a stricter standard than the
  rest, so adding a theme that is hard to read is a failing build.

- **A menu bar, so there is somewhere obvious to find settings.** (LWSM-1146)
  The window was one Rescan button with nowhere to put anything
  else. It now opens with a File menu (Rescan, Quit) and a
  Settings menu whose Preferences entry is where the settings
  dialog will attach. Both menus are reachable from the keyboard,
  and both follow a language change.

- **A runnable release preflight, so a release stops on this machine rather than half-way through.** (LWSM-1151)
  scripts/local-release.sh reports whether a release would stop, and
  where, without changing anything — the recipe, the version lockstep,
  the tag, the dated changelog section, and whether the roadmap agrees
  the cited work shipped. Nothing on GitHub checks a release, so this is
  the only gate one gets.

- **Release machinery: one place to change the version, and a check that all four files agree** (LWSM-1067)
  The version number is written in four files by hand. There is now a
  release recipe that bumps all four together and a check that fails the
  build if they ever disagree — so a release cannot ship with the
  version updated in some places and not others. Nothing user-visible
  changes yet; this is the groundwork for the first tagged release.

- **An Open button that opens the running site in your browser** (LWSM-1016)
  Opens the port the server is actually listening on, read at the
  moment you click rather than remembered from earlier — so it still
  opens the right thing after a project moves ports. Available for any
  server that is running, including one you started yourself outside
  the app.

- **Start, Stop and Restart buttons on every project — the app can now actually run your servers** (LWSM-1010)
  The buttons respond the instant you click them: a project shows
  "starting" or "stopping" straight away rather than waiting up to a
  second for the next check, and the real status takes over as soon as
  it is known. The first time you start a project the app shows you
  exactly what it is about to run — the full path and the exact
  command — and asks; it asks again if that script changes. Stopping a
  project stops the helper processes it started too.

- **A Rescan button that finds your projects and folds them into the list without losing anything you changed** (LWSM-1131)
  Rescan looks through your projects folder, adds anything new,
  updates what it can see, and tells you in one line what changed —
  "Rescan: 2 new, 1 changed". Names you have typed, ports you have
  overridden and notes you have written are never overwritten. A
  project it can no longer find is flagged rather than deleted, and
  a port it could not read this time keeps the value it had rather
  than being blanked. The scan runs in the background, so the window
  stays responsive while it works.

- **The project list can now be saved, and it remembers how each project is started** (LWSM-1007)
  `projects.json` now holds the launcher command, the launcher kind,
  a systemd unit name, per-project notes, and flags for hiding a
  project or starting it at login — as well as the name and port it
  already held. Saving is atomic, so a crash or a full disk can
  never leave a half-written list, and the app refuses to write over
  a file it could not fully read: a typo you can still fix by hand
  is never overwritten by a fresh one.

- **Start and stop actually work: the Supervisor spawns each project in its own process group and reaps the whole tree** (LWSM-1009)
  Stopping a project now stops the helper processes its start script
  spawned, so the port is genuinely released rather than left held by
  something nobody can see. Launched projects are given only the
  handful of environment variables they need — never your SSH agent,
  API keys or cloud credentials (LWSM-1048) — and a project's start
  script is refused outright if it points outside the project or if
  another account on the machine can rewrite it (LWSM-1046, core
  half). Each project's output goes to its own log file, capped at
  5 MB with one rotation.

- **Four scanner behaviours the spec calls load-bearing now have tests that fail when they break** (LWSM-1125)
  Each was correct in the shipping code and protected by nothing: the timeout signal not being confusable with a file error (LWSM-1125), the package.json dependency block staying out of the port rules (LWSM-1126), a start script without the run permission falling through to the next rule (LWSM-1127), and the filename a port was read from being cleaned before it is shown (LWSM-1129). Every one was watched failing against a deliberate break.

- **Detect projects, their launchers and their declared ports** (LWSM-1006)
  Point the app at a folder of projects and it works out, for each
  one, how that project starts and which port it wants — reading the
  launcher the project already has rather than asking you to write
  anything down. Where nothing in the project says which port, it
  says *unknown* instead of guessing, and every port it does find is
  labelled with the rule and the file it came from.

- **A window that shows each project's live status** (LWSM-1005)
  `lwsm` now opens a window listing the projects named in
  `~/.config/localwebservermanager/projects.json`, written by hand for
  now. Each row states — as a word, a glyph and a colour — whether
  anything is listening on that project's port: `running`, `stopped`,
  or `unknown` where the project names no port. The label follows the
  live socket table within 2 seconds of a server starting or stopping,
  and is re-derived on every start rather than remembered.

  Rows are keyboard-focusable and carry an accessible name built from
  what is on screen, so a screen reader announces "running, project-a,
  port 5005". The glyph is decorative and left out of it. Colours come
  from theme tokens rather than being written into the widgets.

  A malformed `projects.json` is refused with a named reason rather
  than half-read; a single bad record is skipped and reported in the
  status bar while the rest still load; and a mistyped port loses the
  port, not the project. The socket table is read on a background
  worker, so a slow lookup cannot freeze the window.

- The `lwsm` console script and `python -m lwsm`, with a
  `--version` flag. No interface yet — it configures logging,
  reports where it is logging to, and exits 0. CI asserts the
  entry point actually resolves, because a console script can
  name a module that does not exist while the build stays green.
- Build tooling: uv + exact pins, ruff, pytest + pytest-qt, and a
  GitHub Actions workflow that calls `scripts/local-ci.sh` rather
  than restating its steps, so the local gate and CI cannot drift.
- Application log at `$XDG_STATE_HOME/localwebservermanager/app.log`,
  INFO by default, rotating at 1 MB with 5 kept (LWSM-1026).
- `docs/standards/dependencies.md` — version policy: latest by
  default, with an exception register that makes a held-back pin
  retestable instead of permanent.

### Changed

- **Split `docs/design.md` — the look-and-feel and accessibility contracts are their own documents** (LWSM-1157)
  The design document had reached 1223 lines and its review gate kept
  capping without settling. `docs/design-look-and-feel.md` and
  `docs/design-accessibility.md` now hold the theme/token contract and
  the accessibility contract; `design.md` keeps everything else and is
  912 lines. Content moved verbatim — no rule changed. Both headings
  stay behind as pointers so older citations still land.

- **When an action fails, the message appears under the project it is about instead of in the status bar (LWSM-1032)**
  A message in the corner of the window is invisible to someone whose
  magnifier is on a button. It clears itself as soon as the project's
  state moves on, so it can never contradict what the row says.

- **The app now starts dark** (LWSM-1147)
  Following the desktop's own light/dark setting would open light on a
  light desktop, which is not what was asked for, so it is a choice
  rather than the starting state.

- **The window opens at a size that fits the list, and the list scrolls** (LWSM-1149)
  The opening size is measured from the content and clamped to the
  screen — eight rows before the list starts scrolling, three as the
  floor — rather than left to Qt's ~790x520 default with the rows
  crushed against the window chrome. The row list now sits in a scroll
  area, so twenty projects no longer force a window taller than the
  screen that cannot be shrunk. Rescan moved off the full-width strip
  into a right-aligned control of its own, and the margins and gaps
  come from the text metric.

- **Groundwork for translation, and stricter internal checks (LWSM-1080, LWSM-1081)**
  The words in the window can now be translated, which none of them could
  before. No translations ship yet — this is about not making that harder
  later. A type-checking tool also found four small mistakes that nothing in
  the build was looking for; those are fixed.

- **Colours meet the readability standard the project set itself (LWSM-1075, LWSM-1077)**
  The colour used for "unknown" was very slightly too faint against the window
  to meet the contrast standard, in the palette a first run gets. It has been
  darkened, and every colour is now checked by arithmetic rather than by eye,
  so a future palette that fails is a failing build. The colour rules also
  moved into the one place meant to own them.

- **`scripts/local-ci.sh` parses all its arguments, and honours NO_COLOR**
  Only `$1` was examined, so `--fst` ran the full gate silently. Unknown
  arguments exit 2 with usage, `--help` works, a failing step is named
  rather than exiting bare, and escape codes are suppressed when stdout is
  not a terminal.

- **CI fails when a check could not run, and pins the toolchain it runs with**
  The workflow sets `LWSM_REQUIRE_ALL_TOOLS=1`, so a SKIP is fatal on the
  machine that is supposed to hold every tool; locally it stays a warning.
  `setup-uv` is pinned rather than resolving whatever uv is newest at run
  time, `.python-version` is committed so both machines resolve the same
  interpreter, `yamllint` is installed rather than assumed from the runner
  image, and the job has a 15-minute timeout in place of the 6-hour
  default.

### Fixed

- **A very long project name no longer pushes the buttons off the window** (LWSM-1174)
  A single project with a long folder name used to stretch the name column
  for every row, pushing Start, Stop and Open past the edge of the window
  with no scrollbar and no way to get them back. Long names are now
  shortened with an ellipsis; the full name is in the tooltip and is still
  read out in full by a screen reader.

- **A refused registry write is retried by the next rescan** (LWSM-1166)
  The write gate compared the merge against the controller's in-memory
  set, which `_apply_merge` had already updated unconditionally — so a
  save that was refused once reported "no changes" from then on while
  nothing ever reached the disk. It now compares against the load, which
  is refreshed only when a write succeeds.

- **A project whose server crashes can be started again** (LWSM-1165)
  If a project's server exited on its own — a missing dependency, a typo in
  its start script, an ordinary crash — the app kept treating that project
  as one it was still managing. Start refused, and Stop and Restart were
  both greyed out, so there was no way back short of restarting the app.
  The app now notices within a second and hands the project back. A start
  script that launches a server and then exits itself is unaffected: that
  server is still running, so the project stays under management and Stop
  still works.

- **Config files edited in an editor that adds a byte-order mark now work** (LWSM-1182)
  Some editors put an invisible marker at the start of a file they save.
  The project list already tolerated it; `settings.json` and the
  `scan-roots` file did not. In `settings.json` that meant none of your
  choices were kept, with a message pointing at a character you cannot see;
  in `scan-roots` it silently replaced your own comments with ours. Both now
  accept the marker like the project list always has.

- **A malformed settings file can no longer stop the app opening** (LWSM-1164)
  One particular shape of broken `settings.json` — thousands of nested
  brackets — crashed the app on startup instead of being ignored, every
  launch, until the file was deleted by hand. It is now reported like any
  other unreadable settings file: the app opens with its defaults and says
  what it could not read.

- **A typo in the settings file no longer wipes your settings** (LWSM-1163)
  If you hand-edited `settings.json` and made a small mistake — a stray
  comma, say — the app fell back to its defaults, as it should. But the next
  time it saved anything, closing the window included, it wrote those
  defaults out over your file: theme, text size, poll interval and log cap
  all reset, and the text you could have fixed gone with them. The app now
  refuses to save over a settings file it could not read, and says so in
  the status bar, so the file stays there for you to correct.

- **The pre-push hook gated the working tree, not the commits being pushed.** (LWSM-1160)
  The check before a push tested the files as they sit on disk, which is not what GitHub receives.

- **The pre-push hook ran the gate in a developer's environment, not the runner's.** (LWSM-1159)
  The check that runs before you push now refuses a push when one of its tools is missing or the wrong version, instead of just warning — which is what GitHub does, so the two now agree.

- **The task-accumulation test no longer fails on a busy machine.** (LWSM-1158)
  It counted Python objects rather than live ones. PySide holds a
  reference to every task handed to the thread pool and releases those
  lazily, so a loaded machine left up to 163 of 200 behind and looked
  exactly like the leak the test guards. It now counts only tasks whose
  underlying C++ object is still alive, and the allowance drops from 20
  to 0.

- **The scanner finds a port that lives in a file the launcher imports** (LWSM-1155)
  A project whose launcher keeps its port one import away — `serve.mjs`
  importing `./lib/port.mjs` — showed as "port unknown". The scanner
  followed a launcher that *runs* another file and not one that *imports*
  one, and for Node and Python launchers it followed nothing at all.
  Relative imports only, still exactly one hop, and every existing safety
  constraint unchanged.

- **A project's whole row, controls included, now fits in one magnifier view (LWSM-1032)**
  Buttons took a fixed width whatever their label said, so a row for a
  long-named project ran past the width a magnifier shows at once and
  reading one row meant panning across it.

- **Text-size changes now enlarge the text, not just the space around it (LWSM-1032)**
  The columns widened at 200 % while every word, button and the filter
  box stayed at their original size — so the one setting the app offers
  for readability did nothing readable. Three existing tests reported
  this working, because all three measured the column rather than the
  letters.

- **The pre-push gate no longer exempts the markdown its own test suite asserts against**
  `CLAUDE.md`, `README.md` and every file under `docs/standards/` are read
  by `tests/test_docs.py`, so an edit to one can redden the suite — but the
  hook classified a markdown-only push as docs-only and skipped the gate.
  A prose count `documentation.md § 1.5` forbids therefore reached GitHub
  and failed CI on 5f1891f. The carve-out list is imported from
  `test_docs.GOVERNED` rather than copied, and the contract test now RUNS
  `docs_only()` instead of scanning its case arms as strings — the
  predecessor's every assertion held while the escape went through.

- **Quitting while a rescan is running no longer saves over your project list** (LWSM-1139)
  A scan that finished after you closed the window still wrote its result,
  on the way out. It is now discarded, and a scan that will not finish no
  longer holds the app open indefinitely either.

- **A chatty project can no longer fill your disk** (LWSM-1136)
  Each project's log was supposed to be capped at 5 MB with one rollover,
  and nothing was actually applying the cap. It is now applied once a
  second, per running project.

- **Double-clicking Start no longer launches two copies of a server** (LWSM-1137)
  The check that says "this one is already running" was made before the
  work that starts it, so two clicks in quick succession could both get
  through — and the app then forgot about the first server while it was
  still holding the port.

- **Stopping a project twice at once can no longer close another project's file** (LWSM-1138)
  Two overlapping stops both released the same log file, and the second
  release could land on a file belonging to something else entirely.

- **The local gate and the GitHub run install the same tools, and a hook runs it before every push.** (LWSM-1150)
  The gate now pins its tool versions in scripts/ci-tools.env, which the
  workflow reads too, and reports any tool that differs as TOOL DRIFT. A
  pre-push hook runs the gate automatically, skipping a docs-only push.
  Local shellcheck 0.11.0 against the runner's 0.9 was why five
  consecutive pushes went red on a green local run.

- **P04: the rows do not line up, because each lays itself out on its own.** (LWSM-1145)
  Every row positions its own text and buttons, so the Start button sits in a different place on every line. It should read as a table.

- **Projects started by npm, Python or Node now actually start** (LWSM-1132)
  Only projects launched by a shell script worked. Anything the scanner
  detected as `npm run dev`, `python3 serve.py` or `node serve.mjs` refused
  to start, with a message that blamed your project for it. The app looked
  for a file called `npm` inside your project instead of using the one
  installed on your machine.

- **A note saying "switch to vite later" is no longer read as a Vite project** (LWSM-1130)
  Rule 3's framework evidence now reads the comment-stripped script value, as the port rules already did, so a commented-out plan cannot hand a project the wrong default port.

- **A folder whose name is not valid text no longer makes its log entry vanish** (LWSM-1128)
  The name is now cleaned before it is shown or stored, so it can be written out as text.

- **A launcher whose command ends in a redirect or a config path has its port found again** (LWSM-1123)
  `exec python3 app.py >> /var/log/app.log` is an ordinary start script; the port scan gave up at the trailing token instead of reading the rest of the line.

- **One unreadable or hostile project directory no longer blanks the whole scan** (LWSM-1122)
  A directory the app may not enter — root-owned, another user's, or `chmod 000` — made the scan return nothing at all instead of skipping that one project. Measured before the fix: 20 healthy projects came back as 0.

- **The core/UI layering check now covers every module the rule names** (LWSM-1006)
  `applog.py` was covered by the rule and missing from the check, and
  the rule itself was worded in a way that would have failed on the
  entry point. Both corrected, and a new test derives the list from
  the rule so the two cannot drift apart again.

- **Quitting is no longer delayed by a port check that never finishes** (LWSM-1117)
  A port check that hangs could keep the process alive indefinitely. That was
  already handled for the app itself, but not for anything else that uses the
  same machinery — including the test suite, which paid a hidden 2.6 seconds on
  every run. Measured while fixing it: against a check that genuinely never
  returns, the wait was not slow but unbounded — a probe process had to be killed
  after three minutes.

- **Turning up the system text size now resizes rows already on screen** (LWSM-1119)
  Changing the application font did nothing to rows that were already displayed;
  only rows created afterwards picked it up. For a partially-sighted user the
  text-size setting is the one most likely to be changed, and it was the one
  route that did not work.

- **Colour themes now reach the text, not just the window frame** (LWSM-1118)
  The theme's colours were applied to the window and discarded before they
  reached the rows inside it. The default light theme hid this by luck — the
  fallback colour happened to have better contrast — but a dark theme rendered
  project names and ports at 1.25:1 against a 4.5:1 readability floor, which is
  effectively invisible. Found before any dark theme shipped.

- **The app starts on a machine with no home directory instead of crashing** (LWSM-1116)
  Where no home directory can be resolved — rare, but real in a stripped
  container — the app died with a traceback and no window, instead of falling
  back to printing its log to the terminal as it was designed to. The same fix
  found a second half nobody had reported: the guard protecting the project-list
  path was being evaluated outside the code that catches it, so it had never
  been able to do anything.

- **A broken project file can no longer wipe your log or stall the window** (LWSM-1114)
  Two limits were missing from `projects.json` handling. One field —
  `schema_version` — was never length-limited, so a large value in it produced a
  single log record over a megabyte and forced the log to roll over, destroying
  the history you are told to consult. And nothing bounded how *many* problems
  were reported: a maximally broken file produced 524,271 of them, 28.7 MB of
  log, and 8.7 seconds of no window at all before the app appeared. Now at most
  100 problems are reported, with a line saying how many more there were, and
  every value is length-limited. Measured after: 101 problems, 5 KB, one
  millisecond. (LWSM-1115)

- **Two more pieces of text can be translated, and switching language reaches rows already on screen** (LWSM-1107)

- **A project removed from the list no longer stays drawn on screen** (LWSM-1106)
  It was left visible on top of the row that moved up into its place.

- **Pointing the app at a folder instead of a settings file no longer uses up a system resource** (LWSM-1104)

- **The status dot is no longer sliced in half at large text sizes** (LWSM-1101)
  The space reserved for it was measured once at startup and never again,
  so at 200 % text the dot needed 14 pixels and had 13 — exactly the
  setting the people who rely on it are using.

- **Closing the window cannot let one last status update through** (LWSM-1098)
  A status message already on its way was still delivered after shutdown.

- **Quitting is no longer held up by a stuck port lookup** (LWSM-1100)
  The shutdown wait was bounded but only moved: the process still waited
  for the stuck lookup at the very end. Measured at 4.16 s to exit behind
  a 4 s probe. The app now ends without waiting for work it has already
  given up on.

- **The app no longer leaks memory while it watches** (LWSM-1099)
  One internal task and one signal object were kept for the life of the
  process on every one-second poll — about 210 MB a day, in a program
  meant to stay open. Measured at 200 retained objects after 200 polls.

- **Screen readers are told what changed, and not told what did not (LWSM-1071, LWSM-1076)**
  The little status dot was read aloud as "black circle", which a note in the
  code claimed could not happen. It is now drawn rather than labelled, so it
  stays on screen and out of the screen reader. Separately, a status change
  was never announced at all; it now is, exactly once, and unchanged rows stay
  quiet.

- **Keyboard focus is visible, and the row no longer spreads across the window (LWSM-1070, LWSM-1074)**
  Moving around the window with the keyboard showed nothing at all — the
  focused and unfocused window were pixel-for-pixel identical. There is now a
  visible ring, and it grows with the text size. Widening the window used to
  fling a project's name and its port to opposite edges, so reading one row
  meant sweeping a magnifier across the screen; the row now stays together.

- **A damaged or hostile settings file can no longer hang or crash startup (LWSM-1072, LWSM-1082)**
  A booby-trapped `projects.json` — a named pipe, a device, an enormous file,
  a 5000-digit port or deeply nested brackets — could hang the app on startup
  or kill it with no window at all. All of them now open an empty window that
  tells you what is wrong, which is what was always intended. A file saved
  with a byte-order mark by an editor is also accepted rather than refused for
  a reason that pointed nowhere.

- **The status display no longer freezes silently (LWSM-1069, LWSM-1073, LWSM-1079)**
  If the part that checks which ports are busy hit an unexpected error, the
  app quietly stopped checking for good — the window kept showing whatever it
  last saw, with no warning, no error and nothing in the log. It now keeps
  checking, and says what went wrong. Closing the app is also reliable now: a
  last message could arrive after the window had gone, and a stuck lookup
  could stop the app quitting at all. And a fault that repeats is written to
  the log once with a count, instead of once a second until it has scrubbed
  away everything else.

- **A rapid second push to main no longer leaves the first commit ungated**
  `cancel-in-progress` applied to pushes as well as pull requests, and
  nothing ever returns to a cancelled run. It is now limited to pull
  requests, where only the head commit is ever merged.

- **A missing `actionlint` no longer reports a clean local-CI pass**
  `actionlint` and `yamllint` shared one flag, so when `actionlint` was
  absent and `yamllint` present, yamllint set the flag and suppressed the
  actionlint skip as well — the gate printed "Local CI passed." with zero
  SKIPs and exit 0. Reproduced with stub executables on `PATH`. Each tool
  now has its own guard and its own skip. `actionlint` is the likeliest to
  be missing, having no distro package.

- **The state directory's parents are created 0700, not just its leaf**
  `mkdir(parents=True, mode=0o700)` applies the mode to the final
  component only, leaving every intermediate at the umask default.

- **`lwsm` rejects an unrecognised option instead of ignoring it**
  `--version` was a membership test over the argument list, so
  `lwsm --versoin` printed the startup banner and exited 0, and there was
  no `--help` at all. An `argparse` parser now exits 2 with usage.

- **A log file deleted underneath the app is reopened instead of silently lost**
  logrotate, `systemd-tmpfiles` and a user tidying `~/.local/state` all
  do this. The idempotence guard compared only the path, so it reused a
  handler holding an unlinked inode and every later record went where no
  name could reach it. It now compares the inode too.

- **The app starts even when it cannot write its log**
  Any `OSError` from log setup — a read-only filesystem, a full disk, an
  unwritable state directory, or one of the hostile states the hard-link
  and FIFO hardening under **Security** now refuses — killed the process
  with a traceback. It warns on stderr and carries on. Without this, that
  hardening would have turned a log-integrity attack into a total-outage
  one.

### Security

- **A start script pointing outside its project is now refused** (LWSM-1162)
  A project could point its start script at a file somewhere else on the
  disk. The app showed you the harmless-looking name, ran the other file,
  and never asked again — even if that other file was rewritten afterwards.
  That launcher is now refused outright, so it never reaches the "do you
  trust this?" dialog at all.

- **Open in browser is offered only for servers this app started** (LWSM-1141)
  Anything on your machine can sit on a project's port, and the app would
  then show that row as running and offer to open it in your browser. It
  cannot tell you what is actually there yet, so it no longer sends you to a
  page it cannot vouch for. Servers the app started itself are unaffected.

- **Approving an npm or Node project no longer approves whatever it is later changed to run** (LWSM-1140)
  Approving a project to run binds that approval to what it actually runs.
  For an `npm run dev` project that is the `dev` command inside
  `package.json`, and for a Python or Node project it is the script file.
  Change either and the app asks you again, instead of silently reusing the
  old approval — which matters because installing a package can rewrite
  that command without you seeing it.

- **The last rejection message built from a foreign filename is escaped and length-bounded** (LWSM-1124)
  A folder with a strange name could push invisible control characters into the app log and the status bar, and past the 120-character bound its seven sibling messages keep.

- **Every file the scanner reads is read under a bound** (LWSM-1050)
  The scanner reads files inside other people's project folders, so
  none of it is trusted: a size cap and a line cap per file, a
  deadline checked per line, a refusal of anything that is not an
  ordinary file, a refusal of symlinks at both the folder and the
  file level, and a containment check so a launcher cannot point the
  scanner at something outside its own project.

- **Two entries for the same folder can no longer both load** (LWSM-1103)
  A path written with two slashes at the front counted as a different
  folder from the same path with one, so the same project could appear
  twice.

- **A hand-edited project file cannot flood the status bar or the log** (LWSM-1102)
  A long value in a project's port field produced a 200,000-character
  message, which would have pushed the app's own history out of the log
  the user is told to consult. Long values in the name and folder path
  were already capped; the cap now covers every field, and caps the
  escaped text rather than the raw text.

- **The tool that installs dependencies is updated for a published advisory (LWSM-1083, LWSM-1064)**
  `uv` is moved from 0.11.7 to 0.12.2, both on this machine and in CI.
  The old version is affected by GHSA-4gg8-gxpx-9rph, where a malicious
  package could place an executable outside the intended environment. The
  lockfile is unchanged, so no dependency moved.

- **A project name in the settings file can no longer forge log lines (LWSM-1078)**
  A name in `projects.json` was copied into the app's messages and log exactly
  as written, so one containing a line break could fake what looked like a
  separate log entry, and a very long one could flood the status bar. Names are
  now escaped and shortened. Two entries pointing at the same folder by
  different routes are also caught, and a name containing a stray zero byte is
  refused instead of loaded.

- **The application log now refuses a hard link and a FIFO, not just a symlink**
  `O_NOFOLLOW` closed only part of the hole it was added for. A hard
  link is not a symlink, so linking `app.log` to any file the user owns
  still fed it every log record; and `O_NOFOLLOW` does not reject a
  FIFO, where `O_WRONLY` blocks until a reader appears, so a named pipe
  planted at `app.log` hung startup forever with no error and no log
  line. Both were reproduced against the shipped code. The handler now
  interrogates the opened descriptor instead of trusting the path: a
  regular file, exactly one link, owned by us.

- The application log is written 0600 in a 0700 directory and refuses
  to write through a symlink (`O_NOFOLLOW`).
- The setuptools build backend is pinned and constrained; it executes
  at build time and was outside the lockfile.
- CI actions pinned to commit SHAs, and the checkout no longer leaves
  the job token in the workspace.

<!-- No release has been cut yet. The scaffold is not a release; the
first version appears above as `## [0.X.0] — YYYY-MM-DD` once there
is a shipped artefact a user could install. -->

