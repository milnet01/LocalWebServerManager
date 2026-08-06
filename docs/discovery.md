# LocalWebServerManager — Discovery (Phase A)

> **Status:** Approved by the user on 2026-08-03.
> **Phase:** A — Discovery.
> **Output:** problem, users, success criteria, tech stack,
> out of scope.
> **Gate:** user explicitly approves this document before
> Phase B starts.


## Problem

Seven of the projects under `<scan root>/` run a
local web server, each started a different way and each on its
own port. There is no single place to see which are running,
stop one, or find out what has claimed a port. Today that means
remembering seven launch commands, keeping a terminal open per
server, and running `ss -tlnp` by hand when something says the
address is already in use.

The inventory below was produced by scanning the projects
directory on 2026-08-03. Projects are referred to by neutral
label — the mapping to real directories is author-private, in
`docs/private/inventory.md`, because a public repository should
not publish a list of the services running on its author's
machine (LWSM-1045). Two of the seven were already running at
scan time with no indication anywhere on the desktop, which is
the problem in one sentence.

| Project | Launcher | Port | Runtime | Already env-configurable? |
|---------|----------|------|---------|---------------------------|
| `project-a` | `node serve.mjs` | 4321 (`serve.mjs:25`) | Node | yes — `PROJECT_A_PORT` |
| `project-b` | `python3 serve.py` | 4322 (`serve.py:28`) | Python (static) | yes — `PROJECT_B_PORT` |
| `project-c` | `python3 server.py` | 8765 (`server.py:20`) | Python | no |
| `project-d` | `./start.sh` | 5000 (saved setting) | Python / Flask | no — saved in `settings_manager.py` |
| `project-e` | `./run.sh` → `launcher.py` | 5002 (`config.py:96`) | Python / Flask | yes — `PROJECT_E_PORT` |
| `project-f` | `./start.sh` | 5005 (`start.sh:10`, again at `app.py:888`) | Python / Flask | no |
| `project-g` | `./run.sh` | 8080 (`run.sh:87`) | Python | **yes — already honours `PORT`** |

Verified by reading each launcher on 2026-08-03. Two corrections
worth recording, because both were wrong in the first draft of
this document and were caught by the Phase D review:
`project-g`'s root `run.sh` starts a **Python backend on
8080** (its `run.sh` execs a Python entry point with `--port "${PORT}"`) — the
Vite dev server on 5173 lives in `frontend/` and is a different
server, out of scope unless the user asks for it; and
`project-e`'s launcher execs `launcher.py`, not `app.py`, with
its port two hops away in `config.py`.

**Four of the seven already take a port from the environment**,
which makes the port contract (ADR-0002) a smaller change than
first assumed — for `project-g` it is already satisfied but
for the missing invalid-value check.

The count is a snapshot, not a fixed set — new projects appear
in that directory regularly, which is why re-scanning is a
first-class feature rather than a one-off setup step.

## Users

1. **A solo developer who keeps a dozen side projects in one
   folder** and works on two or three of them in any given week
   — needs to start the one they're working on, stop the ones
   they aren't, and know at a glance which servers are eating a
   port. **They are partially sighted and read the screen with a
   magnifier** (user, 2026-08-03), so "at a glance" means legible
   under a lens: state spelled out in words, related information
   close enough to read without panning, and nothing that
   depends on spotting a small coloured dot.

The primary user is the author, on one machine (openSUSE
Tumbleweed / KDE). The project is published publicly and is
intended to be useful to others (user, 2026-08-03), which raises
the bar on packaging and on supporting server types beyond the
seven here — but the magnifier constraint above is a design
input, not an accommodation added at the end.

## Success criteria

Each is demonstrable by doing, not by reading code.

1. **Zero-config first run.** Launching the app on a machine
   with no config file produces a list containing all seven
   projects above, each with its launcher and port correctly
   detected, without the user typing anything.
2. **Round-trip control.** Any listed project can be started,
   observed to be reachable in a browser at its port, restarted,
   and stopped again — all from the app window, with the status
   dot reflecting each transition within 2 seconds.
3. **Truthful status across app restarts.** A server started
   outside the app (from a terminal) shows as running; a server
   started by the app and then killed externally shows as
   stopped. Closing and reopening the app does not lose or
   invent state.
4. **Port conflicts are caught before launch.** Starting a
   project whose port is already taken produces a clear warning
   naming what holds the port, and the port can be reassigned so
   the change persists across app restarts.
5. **Failures are visible without a terminal.** When a server
   exits on startup, its output is readable in the app's log
   panel — the user never has to re-run the command in a
   terminal to find out why it died.

## Tech stack

| Layer | Choice | Why | Runner-up |
|-------|--------|-----|-----------|
| Language | Python 3.13 | Already the dominant language in the sibling projects and installed system-wide; the user can read and tweak the result. | Rust — faster and single-binary, but a new language in this folder. |
| Framework | PySide6 6.11 (Qt 6) | Installed already, used across 74 files in sibling projects, and native-looking on KDE Plasma. | Tauri — smaller binary, but an HTML UI that won't match the desktop. |
| Process control | Python `subprocess` + a reader thread per server | Servers must be stopped as a whole process group or the port stays held; this is the only option in this stack that can do it. **Superseded the Phase A pick of Qt's `QProcess`** — verified 2026-08-03 that PySide6 6.11 does not expose `setChildProcessModifier`, so a `QProcess` child cannot be put in its own session. See [ADR-0003](decisions/0003-launch-via-project-scripts.md). | `QProcess` driving `setsid --wait` — works, but the group has to be re-derived through `psutil` on every stop. |
| Port inspection | `psutil` | Cross-checks "who holds this port" and "is this PID still alive" without shelling out to `ss`. | Parsing `ss -tlnp` output — fragile and Linux-format-specific. |
| Build / package | `uv` + `pyproject.toml` | Fast, lockfile-backed, and matches the newer sibling projects (`perch`, `finbreak`, `project-g`). | `pip` + `requirements.txt` — simpler, no lockfile. |
| Test runner | `pytest` + `pytest-qt` | `pytest-qt` is the standard way to drive Qt widgets and signals in tests. | `unittest` — no Qt event-loop support. |
| Linter / formatter | `ruff` (lint + format) | One tool for both jobs, already used across sibling projects. | `black` + `flake8` — two tools, slower. |
| CI | GitHub Actions | Free for public repos; matches the user's existing tooling. | GitLab CI / Buildkite |
| License | MIT | Permissive; matches scaffold and stated intent. | Apache-2.0 |

## Feature set (agreed in discovery)

Confirmed as in-scope for the project as a whole. Sequencing
across phases is decided in Phase C, not here.

- **Project discovery** — scan the configured roots (default
  `~/projects`, asked on first run), detect which projects run a
  server and how, and
  present the result for confirmation. The detected list is then
  **saved**, so the user's edits (rename, hide, port override)
  survive. A **Rescan** button re-runs detection on demand and
  reports what is new, missing, or changed, without discarding
  those edits.
- **Start / stop / restart with live status** — a per-project
  status indicator, uptime, and the controlling buttons.
- **Port conflict detection and reassignment** — warn when a
  port is already held, name the holder, and let the user assign
  a different port that persists.
- **Live log window per project** — the server's output
  streamed into a panel, per project.
- **Open in browser** — one click to `http://localhost:<port>`,
  using the port actually bound.
- **System tray** — start/stop and status without opening the
  main window.
- **Custom per-project actions** — a user-authored list of extra
  buttons per project (open a file, open a URL, run a command).
  Added 2026-08-03 for a specific reason: the tray applets being
  retired carry actions beyond start/stop/open — project-c has
  two *open a file in my editor* actions, another has a
  *refresh my data now* command — and a replacement that loses them is a
  downgrade. One mechanism covers all three and anything future.
- **Tray suppression in managed projects** — the manager sets
  `LWSM_MANAGED=1` on what it launches, and a sibling that sees
  it hides its own tray icon
  ([ADR-0006](decisions/0006-managed-mode-signalling.md)).
- **Start at login, per project** — added by the user on
  2026-08-03 with a purpose: together with open-in-browser it
  makes the **per-project tray icons redundant**. Two of the five
  entries in `~/.config/autostart/` are per-server trays whose
  only real job is starting their server at login; this app
  absorbs that, and they can be deleted. Without it, replacing
  those trays would cost a manual start every morning — a
  downgrade dressed up as consolidation.

**Launch mechanism:** the manager runs each project's *own*
existing launcher (`start.sh`, `run.sh`, `serve.py`,
`serve.mjs`, `npm run dev`). No sibling project has to change,
and each project's own setup logic (virtualenv creation,
dependency install) still runs.

**Port reassignment — resolved direction (user, 2026-08-03).**
Port reassignment and "use the project's own script" pull
against each other, because several launchers hard-code their
port (e.g. `project-f`'s `app.py:888` passes `port=5005`
literally). The manager cannot change a port it does not
control. Rather than work around this, **the sibling projects
will be updated to accept an externally-supplied port**; the
user will run that change in each project's own Claude Code
session, using a prompt this project supplies.

Two consequences:

- Phase B must define a **port contract** — the precise
  environment variable and precedence rules a compliant
  launcher honours — and write it as an ADR. That contract is
  what the per-project prompt asks each sibling to implement.
- The manager must still behave correctly against a
  **non-compliant** project, because adoption is gradual and
  never guaranteed: it detects that the requested port was not
  taken up and says so plainly, rather than reporting a
  reassignment that did not happen.

## Out of scope

Considered and deliberately excluded:

- **Serving anything itself.** This app launches other people's
  servers; it is not a web server, reverse proxy, or PHP/MySQL
  stack manager. No Apache, no nginx, no XAMPP-style bundle.
- **Hostnames and HTTPS.** No `wedding.test` vanity domains, no
  `/etc/hosts` editing, no local certificate authority. Ports on
  `localhost` are enough.
- **Remote or network-exposed management.** Single machine,
  single user, local sockets only. No management from a phone,
  no LAN-exposed control surface.
- **Editing sibling projects.** The manager reads their files
  and runs their scripts; it never rewrites their source, their
  config, or their launchers.
- **Deployment or hosting.** Nothing about getting these sites
  onto the internet.
- **Windows support.** Revisited 2026-08-03 (see *Distribution*):
  the supervisor is built on POSIX process groups and signals,
  which Windows has no equivalent of, so this is a rewrite of the
  layer the app most depends on rather than a packaging job. Kept
  out of scope, and recorded as a considered roadmap item rather
  than a silent omission.

## Distribution

- **Distribution:** public GitHub — `github.com/milnet01/LocalWebServerManager`.
- **Release artefacts:** a **self-contained AppImage** for Linux,
  published per release. Self-contained means a user downloads
  one file and runs it — no `pip install`, no Python version to
  match, no PySide6 to fetch. Added by the user on 2026-08-03,
  along with the intent that **other people find this useful**,
  which raises the bar on the two items below.
- **macOS:** worth doing, and cheap relative to Windows — macOS
  is POSIX, so process groups, signals and the launcher shapes
  all carry over, and PySide6 ships wheels for it. **One thing
  must be verified before committing:** on macOS, enumerating
  other processes' listening sockets may require elevated
  privileges, which would undermine ADR-0004's whole approach.
  That is a research task, not an assumption — it is a
  considered roadmap item, not a promise.
- **Windows:** deliberately **not** promised. The supervisor
  rests on POSIX process groups (`os.killpg`, `start_new_session`)
  and `SIGTERM`; Windows has neither, and the equivalent (Job
  Objects, `CTRL_BREAK_EVENT`) is a rewrite of the layer
  everything else depends on. Launcher detection would also need
  a `.bat` / `.ps1` vocabulary. Recorded as considered so the
  reasoning survives, and revisited only if real demand appears.
- **Reason:** stated project intent (see `CLAUDE.md` § "Licence
  and visibility"). The repo does not exist yet; it is created
  once P01 has something worth showing, and creating it needs
  explicit authorisation at the time.

Because the repo is public, the GitHub-public optional templates
(`CONTRIBUTING.md`, `.github/dependabot.yml`, issue templates, PR
template) are activated during this phase, and the free-CI-minutes
rule in the global `~/.claude/CLAUDE.md` § 6 applies once a remote
exists — pushes need no batching gate.

Everything in this tree becomes world-readable on publication,
including this document and the project inventory above.

## Sign-off

- [x] Problem captured.
- [x] Users captured (1–3 personae).
- [x] Success criteria captured (3–5 measurable outcomes).
- [x] Tech stack chosen with one-sentence reasoning each.
- [x] Out-of-scope list captured (or explicitly empty).
- [x] Distribution chosen (and optionals activated if applicable).
- [x] **User has approved this document.** Date: 2026-08-03.

Once approved, proceed to Phase B — `docs/design.md`.
