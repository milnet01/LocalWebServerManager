# Project Standards

This project follows the shared standards in `~/.claude/standards/`, read in
place rather than copied (LWSM-1326). **Those files are on the author's
machine and not in this repository.** Each file here holds only where this
project differs from one of them, with one line of why per rule. A
contributor reads these files and `CONTRIBUTING.md`.

A bare name in a citation — `coding.md § 1.3`, `testing.md § 1` — means the
shared file of that name. A label with a letter — `§ O1`, `§ T9`, `§ R1` —
lives in the overrides file below.

The table below is the list; no prose in this folder states its length.

| Overrides | Shared standard | Governs |
|-----------|-----------------|---------|
| [coding-overrides.md](coding-overrides.md) | `coding.md`, `languages/python.md`, `languages/qt.md` | `Kind: implement / fix / refactor / audit-fix / review-fix` work |
| [testing-overrides.md](testing-overrides.md) | `testing.md`, `languages/python.md` | `Kind: test`, and the regression test every fix owes |
| [documentation-overrides.md](documentation-overrides.md) | `documentation.md` | `Kind: doc / doc-fix` |
| [commits-overrides.md](commits-overrides.md) | `commits.md`, `local-gate.md` | every commit and push |
| [dependencies-overrides.md](dependencies-overrides.md) | `dependencies.md` | any change touching a version pin; holds the hold register |
| [spec-format-overrides.md](spec-format-overrides.md) | `spec-format.md` | `docs/specs/` and `docs/plans/` |
| [roadmap-format-overrides.md](roadmap-format-overrides.md) | `roadmap-format.md`, `changelog-format.md` | `ROADMAP.md` and `CHANGELOG.md` |
| [versioning-overrides.md](versioning-overrides.md) | `versioning.md` | this project's breaking surfaces, and what would make it `1.0` |

Specs and plans start from the shared skeletons in
`~/.claude/standards/skeletons/`, which `/write-spec` copies.

The review records of the files these replaced are in `docs/reviews/`.
