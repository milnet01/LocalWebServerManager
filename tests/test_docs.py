"""Documentation invariants that a reader cannot see and a linter does not check.

A source-invariant test in the sense of `testing.md § 3.6`, pointed at prose
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

# Where the rule applies: the standards themselves plus the two files that
# orient a reader. Deliberately not the whole tree — ROADMAP, CHANGELOG and the
# journal are append-only records of what was true on a date, which
# `documentation.md § 1.5` keeps rather than deletes.
GOVERNED = [
    *sorted((ROOT / "docs" / "standards").glob("*.md")),
    ROOT / "CLAUDE.md",
    ROOT / "README.md",
]


def offending_lines(path: Path) -> list[str]:
    """Prose counts in `path`, excluding the two forms that legitimately hold one.

    Excluded:

    - **Table rows** (`|`-prefixed). A cold-eyes loop log records what a past
      review found, quoting the stale wording verbatim; that is the evidence,
      not the defect.
    - **Lines already dated.** A measurement anchored to a date is a claim about
      a past run, which `documentation.md § 1.5` explicitly keeps — it grows
      older, it does not become false.
    - **Quoted spans.** Naming a bad form is not committing it. Without this the
      first thing the check reports is `documentation.md § 1.5`'s own list of
      examples — which is the trap `testing.md § 3.6` names ("the comment
      explaining a past defect usually contains the defect's own shape"), hit
      on the first run of this test.
    """
    dated = re.compile(r"\b20\d\d-\d\d-\d\d\b")
    quoted = re.compile(r"[\"“][^\"”]*[\"”]|`[^`]*`")
    hits = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("|") or dated.search(line):
            continue
        if PROSE_COUNT.search(quoted.sub("", line)):
            hits.append(f"{path.relative_to(ROOT)}:{number}: {stripped}")
    return hits


@pytest.mark.parametrize("path", GOVERNED, ids=lambda p: p.name)
def test_no_prose_count_of_a_growing_set(path: Path) -> None:
    """`documentation.md § 1.5` — the list is the count; prose beside it rots.

    This project has fixed the same drift twice. On 2026-08-06 the README said
    "four standards" against five and "eight phases" against ten. On 2026-08-07
    a cold-eyes gate found seven more sites — and the first repair had
    substituted "four" for "three", i.e. a fresh wrong number for a stale one,
    which is why the rule is *drop the count* rather than *keep it current*.

    Second occurrence of one shape across seven call sites is exactly
    `coding.md § 1.6`'s threshold for making the sweep a test rather than a
    habit.
    """
    if not path.exists():  # pragma: no cover - README is not optional today
        pytest.skip(f"{path} does not exist")

    hits = offending_lines(path)

    assert hits == [], (
        "a prose count of a set that grows goes stale on the next addition; "
        "name the list and link it instead (documentation.md § 1.5):\n  "
        + "\n  ".join(hits)
    )
