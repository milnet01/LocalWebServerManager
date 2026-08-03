# LocalWebServerManager

> A KDE desktop app that finds the projects on your machine that
> run a local web server, and lets you start, stop and watch them
> from one window.

[![Status](https://img.shields.io/badge/status-pre--alpha-orange)]()
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

Current version: **0.0.0** — see [CHANGELOG](CHANGELOG.md) for shipped
work, [ROADMAP](ROADMAP.md) for what's coming, and
[docs/standards/](docs/standards/) for the four shareable v1
standards (coding · documentation · testing · commits) the project
follows.

## What it's for

If you keep several web projects in one folder, each starts a
different way, on a different port, and nothing tells you which
are running. Two servers were live on this machine when the
project was scoped, with nothing on screen to say so.

This app scans your projects folder, works out how each project
starts and which port it wants, and gives you one window with a
row per project: a status light, a Start/Stop button, its live
output, and a link to open it in your browser. It runs each
project's own start script and never edits your projects.

## Status

**Pre-alpha — design complete, no code yet.** Phases A–C of the
[Ants App-Build](https://github.com/milnet01) workflow are done
and signed off: the problem and success criteria
([discovery](docs/discovery.md)), the architecture and its seven
decision records ([design](docs/design.md),
[decisions](docs/decisions/)), and the eight-phase build order
([ROADMAP](ROADMAP.md)). P01 — build tooling — is next.

**To begin (or resume) work:** open a terminal in this directory
and run `claude`. Once Claude Code is running, type `let's start
discovery` for a fresh project, or `continue` to resume in
progress. Claude will summarise current state back to you before
doing any work — confirm or correct that summary; never let
Claude resume work without it.

## Features

Nothing has shipped yet, and this section lists shipped
capability rather than intent — so it stays empty until P02
delivers the first working slice. What is *planned*, in build
order, is in the [ROADMAP](ROADMAP.md).

## Install

(filled out at P01 — Bootstrap, once tech stack is chosen)

## Quickstart

(filled out at P02 — Vertical slice)

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
  user-decision on placement (created on first use).
- [docs/standards/](docs/standards/) — coding, documentation,
  testing, commits.
- [.claude/workflow.md](.claude/workflow.md) — live workflow
  state and rules.

## License

[MIT](LICENSE).
