# LocalWebServerManager — Glossary

Domain-specific and workflow-specific terms used in code,
docs, and commits. If a term appears in `discovery.md`,
`design.md`, or any spec and a reader six months from now
might be confused, add it here.

The starter entries below cover terminology used by the
`app-workflow` skill itself; project-specific terms get added
during Phases B and C.

| Term | Definition |
|------|------------|
| **ADR** | Architecture Decision Record — a one-page note explaining a non-obvious design choice, the alternatives considered, and the reasoning. Lives in `docs/decisions/`. |
| **Discovery (Phase A)** | The conversational opening phase: Claude asks one question at a time about the problem, the people who'll use the result, and what "success" looks like. Output: `docs/discovery.md`. |
| **Vertical slice (P02)** | The smallest possible end-to-end feature that touches every layer (input → logic → storage → output → test). The point isn't user value; it's making integration pain surface before more code lands on top. |
| **Mermaid** | A tiny text-based diagram language. GitHub and most markdown viewers render it automatically — no separate tool to install. Used for architecture/flow diagrams in `design.md`. |
| **TDD** | Test-driven development. Write the failing test first, watch it fail for the right reason, then write the smallest code that makes it pass. If the test passes before code is written, the test isn't checking what you thought. |
| **Triage** | The process of sorting findings into three buckets: actionable (folds into a fix-pass), blocked-by-dependency (logs to `known-issues.md`), false-positive (logs to `audit-allowlist.md`). |
| **Lane** | A named subsystem owner (e.g. `build`, `ui`, `tests`, `docs`). Used in roadmap items so parallel subagents can find the right files; per `docs/standards/roadmap-format.md § 3.6.4`. |
| **Kind** | A roadmap-bullet metadata field declaring the work type (`implement`, `fix`, `refactor`, `audit-fix`, `review-fix`, `doc`, `doc-fix`, `test`, `chore`, `release`). Drives which standard governs the work; per `docs/standards/roadmap-format.md § 3.6.3`. |
| **Source** | A roadmap-bullet metadata field naming where the item came from (`audit`, `code-quality-review`, `debt-sweep`, `user`, `planned`); per `docs/standards/roadmap-format.md § 3.6.3`. |
| **Fix-pass (`FP##`)** | A roadmap item generated automatically after `/audit` + `/code-quality-review` to track findings as a single batched piece of work that runs through the full 9-step loop. |
| **Convergence checkpoint** | The fix-pass count (default 5) at which Claude pauses to ask whether to keep iterating, accept remaining findings into known-issues, or rethink design. Configurable in `.claude/workflow.md` § 1. |
| **Debt-sweep (`DS##`)** | A scan for cumulative drift introduced over multiple phases, run by `/debt-sweep`. Default cadence: as part of `/release` before the version bump. |

## Project terms

Added during Phase B (2026-08-03).

| Term | Definition |
|------|------------|
| **Declared port** | The port a project's own source or launcher hard-codes — what it uses when nothing overrides it. Detected by the Scanner; refreshed on every rescan. |
| **Effective port** | The port the manager will actually use: the user's **port override** if one is set, otherwise the declared port. This is the value pre-flighted and passed as `PORT`; per [ADR-0005](decisions/0005-registry-and-rescan.md). |
| **Foreign server** | A server the manager can see listening but did not itself start — typically launched from a terminal. Shown as running and labelled; stoppable only after a confirmation; per [ADR-0004](decisions/0004-runtime-truth-from-probing.md). |
| **Launcher** | The script or command a sibling project already uses to start its own server (`./start.sh`, `python3 serve.py`, `npm run dev`). The manager runs it; it never rewrites it. |
| **Port contract** | The agreement that a launcher reads the `PORT` environment variable and binds it, falling back to its own default when `PORT` is absent. Defined in [ADR-0002](decisions/0002-port-contract.md); adopted per sibling project. |
| **Pre-flight check** | The manager's test, before spawning anything, that the effective port is actually free — and, if not, naming what holds it. |
| **Process group** | The family of processes a launcher spawns (a `start.sh` and the Python server underneath it). Stopping signals the whole group, otherwise the real server survives and keeps the port; per [ADR-0003](decisions/0003-launch-via-project-scripts.md). |
| **Optimistic overlay** | The brief, expiring mark the app puts on a project the moment you press Start or Stop, so the button responds instantly instead of waiting for the next status check. Discarded as soon as a real check disagrees; per `docs/design.md § State management`. |
| **Project state** | One of seven values a project shows at any moment: **stopped**, **starting**, **running (managed)** (we started it), **running (wrong port)** (it ignored the port we asked for), **running (foreign)** (someone else started it), **port blocked** (something unrelated holds its port), **failed**. Defined in [ADR-0004](decisions/0004-runtime-truth-from-probing.md). |
| **Registry** | The saved list of known projects and the user's edits to them (`~/.config/localwebservermanager/projects.json`). Holds intent; a rescan refreshes detected facts around it without overwriting it. |
| **Scan root** | A folder the app looks inside for projects. Defaults to `~/projects`, asked on first run; the list is editable in settings. |
| **Sibling project** | Any other project under a scan root — the things this app manages. The manager reads them and runs their scripts, and never writes into them. |

## Conventions

- **Bold the term** in its first use in this file.
- **One-line definition.** If a term needs more, link from the
  glossary entry to an ADR or design-doc subsection.
- **Append-only.** When a term is renamed, add the new term and
  mark the old one as `(retired in vX.Y.Z, see "<new name>")`.
- **Sort alphabetically** after the workflow-vocabulary block
  above. Helps lookup.
- **Link external sources** for terms with a canonical external
  definition (RFC, W3C spec, vendor docs).
