"""Documentation invariants that a reader cannot see and a linter does not check.

A source-invariant test in the sense of `testing-overrides.md § T10`, pointed at prose
instead of at a module: it reads files and fails on the *shape of a past
defect*, and it is exempt from § 2.1 and § 3.1 on that basis.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# The sets that keep growing, and the word each is counted by. A prose count of
# any of them is true when written and expires on the next addition.
COUNTED_NOUNS = ("standards", "modules", "phases", "specs")

NUMBER_WORDS = "one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve"

PROSE_COUNT = re.compile(
    rf"\b({NUMBER_WORDS})\s+({'|'.join(COUNTED_NOUNS)})\b",
    re.IGNORECASE,
)

# Where the rule applies: the standards themselves plus the files that
# orient a reader. Deliberately not the whole tree — ROADMAP, CHANGELOG and the
# journal are append-only records of what was true on a date, which
# `documentation-overrides.md § DOC1` keeps rather than deletes.
GOVERNED = [
    *sorted((ROOT / "docs" / "standards").glob("*.md")),
    ROOT / "CLAUDE.md",
    # CLAUDE.md's detail, moved out to keep the always-loaded file small.
    *sorted((ROOT / "docs" / "claude").glob("*.md")),
    ROOT / "README.md",
]

# The design documents that name theme ids a reader then types into the app.
# Not GOVERNED: the prose-count rule is about standards, and these hold counts
# of their own on purpose (LWSM-1299).
THEME_DOCS = [
    ROOT / "docs" / "design-look-and-feel.md",
    ROOT / "docs" / "design-accessibility.md",
]

# Every markdown file this module asserts against. The pre-push hook must never
# exempt one of them, and `test_ci_contract.py` imports this to say so.
ASSERTED = [*GOVERNED, *THEME_DOCS]


def offending_lines(path: Path) -> list[str]:
    """Prose counts in `path`, excluding the two forms that legitimately hold one.

    Excluded:

    - **Table rows** (`|`-prefixed). A cold-eyes loop log records what a past
      review found, quoting the stale wording verbatim; that is the evidence,
      not the defect.
    - **Lines already dated.** A measurement anchored to a date is a claim about
      a past run, which `documentation-overrides.md § DOC1` explicitly keeps — it grows
      older, it does not become false.
    - **Quoted spans.** Naming a bad form is not committing it. Without this the
      first thing the check reports is `documentation-overrides.md § DOC1`'s own list of
      examples — which is the trap `testing-overrides.md § T10` names ("the comment
      explaining a past defect usually contains the defect's own shape"), hit
      on the first run of this test.
    """
    dated = re.compile(r"\b20\d\d-\d\d-\d\d\b")
    quoted = re.compile(r"[\"“][^\"”]*[\"”]|`[^`]*`")

    def prose(line: str) -> bool:
        stripped = line.strip()
        return (
            bool(stripped) and not stripped.startswith("|") and not dated.search(line)
        )

    label = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
    lines = path.read_text(encoding="utf-8").splitlines()
    hits = []
    for index, line in enumerate(lines):
        if not prose(line):
            continue
        # Prose is hard-wrapped, so a count may end one line and its noun start
        # the next (LWSM-1350). Each prose line is read with the next prose line
        # joined on; a hit inside the next line alone is that line's to report.
        following = lines[index + 1] if index + 1 < len(lines) else ""
        joined = line
        if prose(following):
            joined = f"{line} {following.strip()}"
        own = PROSE_COUNT.search(quoted.sub("", line))
        spans_the_wrap = (
            joined is not line
            and PROSE_COUNT.search(quoted.sub("", joined))
            and not PROSE_COUNT.search(quoted.sub("", following))
        )
        if own or spans_the_wrap:
            hits.append(f"{label}:{index + 1}: {line.strip()}")
    return hits


@pytest.mark.parametrize("path", GOVERNED, ids=lambda p: p.name)
def test_no_prose_count_of_a_growing_set(path: Path) -> None:
    """`documentation-overrides.md § DOC1` — the list is the count; prose beside it
    rots.

    This project has fixed the same drift twice. On 2026-08-06 the README said
    "four standards" against five and "eight phases" against ten. On 2026-08-07
    a cold-eyes gate found seven more sites — and the first repair had
    substituted "four" for "three", i.e. a fresh wrong number for a stale one,
    which is why the rule is *drop the count* rather than *keep it current*.

    Second occurrence of one shape across seven call sites is exactly
    `coding-overrides.md § O9`'s threshold for making the sweep a test rather than a
    habit.
    """
    if not path.exists():  # pragma: no cover - README is not optional today
        pytest.skip(f"{path} does not exist")

    hits = offending_lines(path)

    assert hits == [], (
        "a prose count of a set that grows goes stale on the next addition; "
        "name the list and link it instead (documentation-overrides.md § DOC1):\n  "
        + "\n  ".join(hits)
    )


THEME_ID = re.compile(r"`([a-z]+-(?:light|dark))`")
THEME_ROW = re.compile(r"^\| \*\*([a-z-]+)\*\*", re.MULTILINE)


def test_the_design_documents_name_the_theme_ids_the_code_ships() -> None:
    """LWSM-1299. The docs once named `contrast-light` and `contrast-dark`, which
    no theme is called (LWSM-1245). Nothing failed: `theme_for_id` falls back
    to the default, so a reader following the docs got Midnight with no error.

    The table is held to `THEMES` in both directions, so a renamed theme, an
    added one and a deleted one all fail. A theme id quoted in prose is held
    one way: it must name a theme.
    """
    from lwsm.theme import THEMES

    table = THEME_ROW.findall(THEME_DOCS[0].read_text(encoding="utf-8"))
    assert sorted(table) == sorted(THEMES), (
        "design-look-and-feel.md's theme table does not list the themes "
        "theme.THEMES ships"
    )

    for path in THEME_DOCS:
        named = THEME_ID.findall(path.read_text(encoding="utf-8"))
        unknown = sorted(set(named) - set(THEMES))
        assert unknown == [], (
            f"{path.name} names theme ids that do not exist: {unknown}"
        )


def test_a_count_wrapped_across_two_lines_is_still_found(tmp_path: Path) -> None:
    """LWSM-1350. Prose here is hard-wrapped, and the standards README read
    "the four" / "standards docs" on two lines, so a per-line match never saw
    it. A count split by a wrap is the same count."""
    doc = tmp_path / "doc.md"
    doc.write_text("Links to `docs/`, including the four\n   standards docs.\n")

    assert len(offending_lines(doc)) == 1


def test_a_wrap_into_a_table_row_is_not_joined(tmp_path: Path) -> None:
    """The join keeps the per-line exclusions: a number word ending a prose
    line is not joined to a table row below it."""
    doc = tmp_path / "doc.md"
    doc.write_text("It found four\n| standards | row |\n")

    assert offending_lines(doc) == []
