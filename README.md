# LocalWebServerManager

> A KDE desktop app that finds the projects on your machine that
> run a local web server, and lets you start, stop and watch them
> from one window.

[![Status](https://img.shields.io/badge/status-pre--alpha-orange)]()
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

Current version: **0.0.0** — see [CHANGELOG](CHANGELOG.md) for shipped
work, [ROADMAP](ROADMAP.md) for what's coming, and
[docs/standards/](docs/standards/) for the five shareable v1
standards (coding · documentation · testing · commits ·
dependencies) the project follows.

## What it's for

If you keep several web projects in one folder, each starts a
different way, on a different port, and nothing tells you which
are running. When this project was scoped, two of the author's
seven local servers were quietly running and nothing on screen
said so.

This app scans your projects folder, works out how each project
starts and which port it wants, and gives you one window with a
row per project: a status light, a Start/Stop button, its live
output, and a link to open it in your browser. It runs each
project's own start script and never edits your projects.

## Status

**Pre-alpha — the design is settled and the build has started.
There is no usable application yet.**

Done: the problem and success criteria
([discovery](docs/discovery.md)); the architecture and its seven
decision records ([design](docs/design.md),
[decisions](docs/decisions/)); the ten-phase build order
([ROADMAP](ROADMAP.md)); and **P01 — build tooling**, which is the
packaging, linting, test harness, CI and application log. The
design document has been through four independent review passes.

Not done: everything you would actually use. `src/` today holds an
entry point and a logger. The first window with a live project row
arrives in P02, and the Start/Stop buttons in P05.

**If you want to watch or contribute**, the honest place to start
is [ROADMAP.md](ROADMAP.md) — every item has a stable ID, stated
acceptance criteria and its dependencies, so what is real and what
is intended are never mixed up. See
[CONTRIBUTING.md](CONTRIBUTING.md).

## Features

Nothing has shipped yet, and this section lists shipped
capability rather than intent — so it stays empty until P02
delivers the first working slice. What is *planned*, in build
order, is in the [ROADMAP](ROADMAP.md).

## Requirements

- **Linux, targeting KDE Plasma.** Remembering and restoring the
  window's position needs KWin, because under Wayland an
  application may not place its own window — on other desktops
  that one feature degrades to "opens at the remembered size,
  wherever the compositor puts it" (ADR-0007). Everything else is
  ordinary Qt and portable across Linux desktops. macOS and
  Windows are assessed rather than promised — Windows in
  particular has no process groups, which is the mechanism the
  whole start/stop design rests on (ADR-0003). See LWSM-1024 and
  LWSM-1025.
- **Python 3.13+**, and [uv](https://docs.astral.sh/uv/).

## Install

There is nothing to install for end users yet — no release, no
package, no AppImage. That is P10.

To work on it:

```bash
git clone https://github.com/milnet01/LocalWebServerManager.git
cd LocalWebServerManager
uv sync                 # resolves from the committed uv.lock
./scripts/local-ci.sh   # lint, format, tests, entry points — the full gate
```

`scripts/local-ci.sh` is the single source of truth for CI: the
GitHub Actions workflow prepares a machine and then calls it, so a
check cannot exist in CI that you are unable to run first.

## Quickstart

(filled out at P02, once there is a window to open.)

## Documentation

- [ROADMAP](ROADMAP.md) — what's planned, with stable IDs.
- [CHANGELOG](CHANGELOG.md) — what's shipped, Keep-a-Changelog
  format with an `[Unreleased]` block at the top.
- [docs/discovery.md](docs/discovery.md) — Phase A output:
  problem, users, success criteria, tech stack, out of scope.
- [docs/decisions/0002-port-contract.md](docs/decisions/0002-port-contract.md)
  — the change each managed project needs so its port can be set
  from outside.
- [docs/design.md](docs/design.md) — Phase B output: architecture
  diagram, components, data flow.
- [docs/decisions/](docs/decisions/) — Architecture Decision
  Records. Why we chose X over Y.
- [docs/glossary.md](docs/glossary.md) — domain terms used in
  code and docs.
- [docs/known-issues.md](docs/known-issues.md) — findings
  deferred because they're blocked by an unbuilt feature.
- [docs/audit-allowlist.md](docs/audit-allowlist.md) —
  project-specific false-positive memory for `/audit` and
  `/code-quality-review`.
- [docs/ideas.md](docs/ideas.md) — mid-flight ideas pending a
  decision on where they belong.
- [docs/standards/](docs/standards/) — coding, documentation,
  testing, commits, dependencies.
- [.claude/workflow.md](.claude/workflow.md) — live workflow
  state and rules.

## License

[MIT](LICENSE).
