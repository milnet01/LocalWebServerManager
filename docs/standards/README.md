# Project Standards

Five short, focused standards that govern how this project is
written, tested, documented, committed, and kept up to date. Each
standard is v1 and self-contained; cross-references between them
are explicit.

| Standard | Covers |
|----------|--------|
| [coding.md](coding.md) | Code style, language idioms, error handling, comments, naming, security. Governs `Kind: implement / fix / refactor / audit-fix / review-fix` work. |
| [documentation.md](documentation.md) | README / CLAUDE.md / SECURITY.md structure, API contracts, screenshots, markdown style. Governs `Kind: doc / doc-fix` work. |
| [testing.md](testing.md) | TDD policy, test types, spec-first authoring, INV numbering, coverage, anti-patterns. Governs `Kind: test` work + the regression-test follow-through for `fix / audit-fix / review-fix`. |
| [commits.md](commits.md) | The `<ID>: <description>` mandate, hygiene, branching, push policy, release commits. Governs every commit. |
| [dependencies.md](dependencies.md) | Version policy for packages, GitHub Actions, runner images and the Python runtime: latest by default, the pin unit per ecosystem, and the exception register that makes a held-back pin retestable rather than permanent. Governs `Kind: chore` dependency work and any change touching a pin. **Canonical for version policy** — `coding.md § 1.5` defers to it. |

Sub-specs extracted from `documentation.md` for token efficiency:

| Sub-spec | Covers |
|----------|--------|
| [roadmap-format.md](roadmap-format.md) | Detailed `ROADMAP.md` and `CHANGELOG.md` format spec — file-header marker, status / theme emojis, stable IDs (`PROJ-NNNN`), insertion semantics, `Kind:` / `Source:` taxonomy, current-work signaling, fold-in subsections, anti-patterns. Read when authoring either file or any tooling that consumes them. |
| [spec-format.md](spec-format.md) | Detailed `docs/specs/` and `docs/plans/` format spec — required sections, invariant rules (test surface + breaking input, never renumber), citation grounding, the size gate, the review gate, `spec_query` parseability. Read §0 before writing a spec; the rest is reference. Governs `documentation.md § 10`. |

Fill-in-the-blanks starting points, copied by `/write-spec`:

| Skeleton | For |
|----------|-----|
| [spec-skeleton.md](spec-skeleton.md) | a new spec — every section pre-numbered with its authoring prompt inline |
| [plan-skeleton.md](plan-skeleton.md) | a new build plan |

## How they fit together

The five standards plus `ROADMAP.md` form a closed loop:

1. **ROADMAP item** declares an `[ID]`, `Kind:`, and `Source:`
   (per [roadmap-format § 3](roadmap-format.md)).
2. **Implementation** follows the standard for that Kind:
   - `implement` / `fix` / `refactor` → [coding.md](coding.md)
   - `chore` touching a version pin → [dependencies.md](dependencies.md)
   - `doc` / `doc-fix` → [documentation.md](documentation.md)
   - `test` → [testing.md](testing.md)
   - `chore` / `release` → [commits.md](commits.md) §5
3. **Tests** follow [testing.md](testing.md) — TDD by default.
4. **Commit** uses `<ID>: <description>` per
   [commits.md](commits.md) §1.1.
5. **CHANGELOG** entry under `[Unreleased]` cites the ID per
   [roadmap-format § 4.2](roadmap-format.md).
6. **Release** flips the ROADMAP bullet from 🚧 to ✅, moves the
   `[Unreleased]` entry to a dated section per
   [roadmap-format § 4.3](roadmap-format.md).

Every step has a single owner and a single source of truth — no
rules buried in commit messages, no conventions inferred from
existing code, no "ask the original author".

## Adopting these standards in another project

Copy every file in this folder verbatim into your project's
`docs/standards/` directory. They're intentionally
project-agnostic: language-specific notes are guidance rather
than mandates, and project-specific rules (specific module
boundaries, specific build commands) live in `CLAUDE.md` at the
repo root.

Any project-specific tweaks to a standard should be added as a
new section at the bottom of the relevant file, prefixed with
`## <Project> overrides`.

## Versioning

Each standard carries a v1 marker in its first-line HTML
comment:

```html
<!-- ants-coding-standards: 1 -->
```

Future revisions increment the version number. Backwards-
incompatible changes (renaming a section, removing a Kind value,
adding a required field) require a major version bump. Additive
changes stay on the current version.
