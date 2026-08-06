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

