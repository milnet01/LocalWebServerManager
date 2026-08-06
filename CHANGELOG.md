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

### Security

- The application log is written 0600 in a 0700 directory and refuses
  to write through a symlink (`O_NOFOLLOW`).
- The setuptools build backend is pinned and constrained; it executes
  at build time and was outside the lockfile.
- CI actions pinned to commit SHAs, and the checkout no longer leaves
  the job token in the workspace.

<!-- No release has been cut yet. The scaffold is not a release; the
first version appears above as `## [0.X.0] — YYYY-MM-DD` once there
is a shipped artefact a user could install. -->

