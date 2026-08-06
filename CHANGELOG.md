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

