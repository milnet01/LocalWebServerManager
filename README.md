# LocalWebServerManager

> A KDE desktop app that finds the projects on your machine that
> run a local web server, and lets you start, stop and watch them
> from one window.

[![Status](https://img.shields.io/badge/status-pre--alpha-orange)]()
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

Nothing is released yet — see [CHANGELOG](CHANGELOG.md) for shipped
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

**Early days, but it runs.** You can open the window today, see
your projects with a live status light, and start, stop, restart
and open them in a browser. There is no installer or download
yet, so you run it from a copy of the source (see **Install**).

Current version: **0.0.0** — nothing has been released, so
nothing is promised to keep working from one day to the next.
(That exact line is what `scripts/check-version-drift.sh`
matches on; `cut-release` rewrites it, never edit it by hand.)

**What works now**

- **It finds your projects for you.** Point it at the folder your
  projects live in and it works out which ones run a web server,
  how each one starts, and which port each one wants.
- **One window, one row per project.** A coloured light and the
  word `running`, `stopped` or `unknown` — the word is always
  there, so the colour is never the only thing telling you.
- **Start, Stop and Restart buttons**, on every row. It runs your
  project's own start script and never changes a single file in
  your project.
- **An Open button** that opens the running site in your browser.
  It is offered only for servers this app started itself — if
  something else is sitting on that port, the app will not send
  you to a page it cannot vouch for.
- **A Rescan button** that goes and looks again, folding in new
  projects without losing anything you changed by hand.
- **Eight colour themes**, including two high-contrast ones, and
  it starts dark. Your choice is remembered.
- **Built to be readable.** Text scales with your system setting,
  and **Settings > Text size** takes it further — 100 % to 200 %,
  on top of whatever your desktop already asked for, and
  remembered. The keyboard focus outline is visible, colours are
  checked against a contrast standard, and screen readers are told
  when a project changes state — once, not once a second. When
  something fails, the message appears under the project it is
  about rather than in the corner of the window.
- **Drive it from the keyboard.** `/` jumps to a filter box and
  narrows the list as you type, Escape clears it, the number keys
  jump to a project, and Enter starts or stops the one you are on.
- **A log per project**, written to a private file and capped in
  size so a chatty server cannot fill your disk.

**What is not there yet**

- No **Settings window** — where to look for projects is a plain
  text file for now (see **Quickstart**).
- No **live output panel** inside the app. The logs are on disk
  and you read them with your own tools.
- No **system tray icon**, no **start on login**, no
  **"what is using this port?"** help, and no **downloadable
  package** — those are later phases.

Every one of those has a stable ID and stated acceptance criteria
in [ROADMAP.md](ROADMAP.md), so what is real and what is merely
intended are never mixed up. If you want to contribute, start
there and with [CONTRIBUTING.md](CONTRIBUTING.md).

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

There is no download, package or AppImage yet — that is the last
phase of the build. For now you run it from a copy of the source.

```bash
git clone https://github.com/milnet01/LocalWebServerManager.git
cd LocalWebServerManager
uv sync                 # installs everything it needs, exact versions
uv run lwsm             # open the window
```

To put it in your application launcher, so you can start it like
any other app and pin it to your panel:

```bash
./scripts/install-desktop-entry.sh
```

That writes only inside your own home folder and needs no
password.

### Quickstart

1. **Tell it where your projects are.** Create the file
   `~/.config/localwebservermanager/scan-roots` and put one
   folder per line:

   ```
   # one directory per line; blank lines and #comments are ignored
   ~/projects
   ~/work/websites
   ```

   Without that file it looks in `~/projects`.

2. **Run `uv run lwsm`.** The window opens and lists what it
   found, with a status light per project.

3. **Press Start on a row.** The first time you start a given
   project, the app shows you exactly what it is about to run and
   asks you to confirm — it will not run a script on your behalf
   that you have not seen. Approve it once and it remembers, and
   it asks again if that script later changes.

4. **Press Open** to open the running site in your browser, and
   **Stop** when you are done. Closing the app deliberately
   leaves your servers running; it is a manager, not an owner.

5. **Press Rescan** after you add a new project, to pick it up
   without restarting.

Your project list lives in
`~/.config/localwebservermanager/projects.json` and the per-project
logs in `~/.local/state/localwebservermanager/logs/`.

### For contributors

```bash
uv sync --extra dev                   # dev tools too
git config core.hooksPath .githooks   # run the gate before every push
./scripts/local-ci.sh                 # lint, format, tests — the full gate
```

`scripts/local-ci.sh` is the single source of truth for CI: the
GitHub Actions workflow prepares a machine and then calls it, so a
check cannot exist in CI that you are unable to run first.

The tools it runs are pinned in `scripts/ci-tools.env`, which the
workflow reads too — so both sides run the same shellcheck, yamllint,
actionlint and uv. If yours differ the gate says so and tells you the
run no longer predicts GitHub. Bump a version there and the workflow
follows; `tests/test_ci_contract.py` fails if the two ever part.

The `core.hooksPath` line above installs a `pre-push` hook that runs
the gate for you. A docs-only push skips it.

Before cutting a release, `./scripts/local-release.sh` reports
whether one is safe to cut. It changes nothing.

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
  project-specific false-positive memory for the static-analysis
  and code-review passes.
- [docs/ideas.md](docs/ideas.md) — mid-flight ideas pending a
  decision on where they belong.
- [docs/standards/](docs/standards/) — coding, documentation,
  testing, commits, dependencies.
- [.claude/workflow.md](.claude/workflow.md) — live workflow
  state and rules.

## License

[MIT](LICENSE).
