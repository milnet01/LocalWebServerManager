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

- ****Projects started by npm, Python or Node now actually start** (LWSM-1132)**
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

- ****Approving an npm or Node project no longer approves whatever it is later changed to run** (LWSM-1140)**
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

