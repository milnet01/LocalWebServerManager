# dependencies.md loop log — moved from docs/standards/dependencies.md on 2026-10-02 when that file was replaced (LWSM-1326)

## Cold-eyes loop log

| Loop | Date | Lanes | C | H | M | L | Outcome |
|---|---|---|---|---|---|---|---|
| 1 | 2026-08-03 | 1 (general-purpose, genre pinned `standard`) | 1 | 3 | 5 | 4 | All 13 verified and fixed. The CRITICAL was a **live bug in the CI gate**, not only in this document — see below. |

**Loop 1.** The CRITICAL is the finding this gate exists for: the enforcement
table credited `uv sync --frozen` with catching a lockfile that disagrees with
`pyproject.toml`. Verified empirically rather than from the help text — with
`pyproject.toml` at `psutil==7.1.0` and `uv.lock` at `7.2.2`, `--frozen` exited
**0** and left the lock untouched, so the entire run would have tested the old
version; `--locked` exited **1**. So `scripts/local-ci.sh` was fixed as well as
this table. A "What checks this" row claiming a check that does not happen is
worse than an honest **nothing**, because it is trusted.

Three findings were the document contradicting the project it governs: it had
no entry in `docs/standards/README.md` or `CLAUDE.md` (an unrouted standard is
an unread one); its blanket "pin exactly" rule condemned this repo's own
`actions/checkout@v7`, since the pin *unit* differs by ecosystem; and it
duplicated a version-specific fact that ADR-0003 already owns. Two fixes landed
outside this file as a result — `actionlint@latest` in the workflow became a
pinned `@v1.7.12`, and `.github/dependabot.yml` gained the `pip` ecosystem that
had been sitting commented out, which had silently left the project with **no**
automated staleness signal at all.
