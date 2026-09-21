"""The strings this app promises a translator are ones the extractor can see.

`QCoreApplication.translate()` calls are only worth anything if `lupdate` can
find them, and nothing else in the gate asks whether it can — ruff, the type
checker and every runtime test pass on a call the extractor silently ignores.
Written after `pyside6-lupdate` reported "Found 0 source text(s)" for a module
holding dozens of them (LWSM-1304).

The extractor is PySide6's own, so it is present wherever the app's runtime
dependency is, CI included — and it is the same tool a translator would run.
"""

from __future__ import annotations

import ast
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SOURCES = [
    REPO / "src" / "lwsm" / "mainwindow.py",
    REPO / "src" / "lwsm" / "settingsdialog.py",
]


@pytest.fixture(scope="module")
def extracted(tmp_path_factory) -> dict[str, set[str]]:
    """Every source string lupdate finds, keyed by the context it found it in."""
    out = tmp_path_factory.mktemp("ts") / "lwsm.ts"
    done = subprocess.run(
        ["pyside6-lupdate", *[str(p) for p in SOURCES], "-ts", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr or done.stdout
    assert out.exists(), done.stdout

    found: dict[str, set[str]] = {}

    # and this file was generated seconds ago by lupdate from this repo's own
    # sources into a tmp directory. Adding `defusedxml` as a dependency to read
    # our own output would be the larger change.
    for context in ET.parse(out).getroot().iter("context"):  # noqa: S314
        name = context.findtext("name") or ""
        for message in context.iter("message"):
            found.setdefault(name, set()).add(message.findtext("source") or "")
    return found


def test_the_extractor_finds_strings_at_all(extracted) -> None:
    """The one that was false (LWSM-1304).

    A variable as the CONTEXT argument makes lupdate skip the call entirely —
    measured against a probe where the only difference was a literal. So every
    translate() call in these modules was invisible, and no other check noticed
    because they all pass on a call nobody can extract.
    """
    assert extracted, "pyside6-lupdate found no translatable string in any module"


def test_each_module_uses_exactly_one_context(extracted) -> None:
    """§ 4.4's one-context-per-file rule, asked of the EXTRACTOR.

    `test_every_translated_string_uses_one_context` in test_mainwindow.py asks
    it of a running window, so it can only see strings that window happens to
    produce — a stray context on a rescan-only message survived it. lupdate
    reads every call in the file whether or not anything runs it.

    It is also what now holds the rule the `_TR_CONTEXT` constant used to hold
    by construction (LWSM-1304).
    """
    assert set(extracted) == {"ProjectRow", "SettingsDialog"}, sorted(extracted)


def _translate_calls(path: Path) -> list[ast.Call]:
    """Every `QCoreApplication.translate(...)` call in `path`."""
    return [
        node
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "translate"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "QCoreApplication"
    ]


def test_the_walk_sees_a_planted_offence(tmp_path: Path) -> None:
    """The guard below reports nothing on a clean tree, and on a broken walk.

    `_translate_calls` matches one spelling — an attribute named `translate` on
    a bare `QCoreApplication`. A refactor to `QtCore.QCoreApplication.translate`
    or a wrapper, or an `ast.parse` that raises, makes it match nothing, and a
    check that finds no offenders is exactly what a clean tree looks like. So
    the walk is asked to find one that is definitely there.

    Contributed by the finbreak session, 2026-09-21, which hit this class
    independently and had the leg this file was missing. It also measured the
    shape checked here as one of four rather than three: a call routed through
    a helper extracts nothing while reading as a literal at every call site.
    That shape is absent here — no function in `src/lwsm/` passes a parameter
    to `translate()` — so this file does not test for it. Add the case with the
    wrapper, not before it.
    """
    planted = tmp_path / "planted.py"
    planted.write_text(
        "from PySide6.QtCore import QCoreApplication\n"
        "\n"
        "def f(source: str) -> str:\n"
        '    return QCoreApplication.translate("Ctx", source)\n',
        encoding="utf-8",
    )

    calls = _translate_calls(planted)
    assert len(calls) == 1, f"the walk found no translate() call to judge: {calls}"

    offenders = [
        index for index in (0, 1) if not isinstance(calls[0].args[index], ast.Constant)
    ]
    assert offenders == [1], (
        "the walk must flag a non-literal source argument; it reported "
        f"{offenders} for a call whose source is a parameter"
    )


def _offences(call: ast.Call) -> list[str]:
    """Why lupdate would skip `call`, or an empty list if it would not.

    The single place the rule lives, so the probes below measure the guard
    rather than a copy of it that can drift away from the guard.

    Two offences, and the second is not a special case of the first. A
    non-literal argument is the shape the review found. Too FEW positional
    arguments is the shape a keyword call takes — `translate("Ctx",
    sourceText=...)` presents an empty positional list, so an index-based
    check examines nothing and reports clean. It is an offence even when the
    keyword's value is a literal, because lupdate reads position, not name.
    """
    offences = [
        f"argument {index} is not a literal: {ast.unparse(call.args[index])}"
        for index in (0, 1)
        if len(call.args) > index and not isinstance(call.args[index], ast.Constant)
    ]
    if len(call.args) < 2:
        offences.append(
            f"only {len(call.args)} positional argument(s); lupdate reads "
            f"position, so a keyword argument is invisible to it"
        )
    return offences


# Call shapes lupdate cannot read, each of which must reach an offender list.
# A keyword argument is the one that reads as innocent: `sourceText="hello"` is
# a literal, and lupdate still extracts nothing, so accepting it because the
# value is a literal would encode a false allowance. Contributed by the
# finbreak session, 2026-09-21, which measured its own walk skipping all three
# — it bound-checked the positional list and never read `node.keywords`, so a
# keyword call was not examined at all.
INVISIBLE_SHAPES = [
    'QCoreApplication.translate("Ctx", var)',
    'QCoreApplication.translate("Ctx", sourceText=var)',
    "QCoreApplication.translate(context=CTX, sourceText=var)",
    'QCoreApplication.translate("Ctx", sourceText="hello")',
]


@pytest.mark.parametrize("expression", INVISIBLE_SHAPES)
def test_an_unextractable_shape_reaches_an_offender_list(
    tmp_path: Path, expression: str
) -> None:
    """Arity is its own offender, so a keyword call cannot pass quietly.

    The literal check indexes the positional arguments. A call that passes
    them by keyword has an empty positional list, so every index is skipped
    and a walk that only checks literals examines nothing — which is why the
    arity assertion is a separate list rather than a `continue`. Deleting it
    lets the last three of these through.
    """
    probe = tmp_path / "probe.py"
    probe.write_text(f"def f(var, CTX):\n    return {expression}\n", encoding="utf-8")

    calls = _translate_calls(probe)
    assert len(calls) == 1, f"the walk did not find the call to judge: {calls}"

    assert _offences(calls[0]), (
        f"lupdate extracts nothing from {expression!r}, and the guard raised "
        f"no offence against it"
    )


def test_a_clean_call_raises_nothing(tmp_path: Path) -> None:
    """The reverse of the case above, or the guard could pass by always failing.

    Four shapes that must be caught prove nothing on their own — a check
    hard-coded to object satisfies every one of them. This is the case that
    must come back empty.
    """
    probe = tmp_path / "clean.py"
    probe.write_text(
        'def f():\n    return QCoreApplication.translate("Ctx", "hello")\n',
        encoding="utf-8",
    )

    calls = _translate_calls(probe)
    assert len(calls) == 1
    assert _offences(calls[0]) == []


# Every fragment LWSM-1252 and LWSM-1258 recovered, with the context it belongs
# to. Named here rather than counted, so a fragment that stops being extracted
# fails under its own id instead of moving a total.
RECOVERED = [
    ("ProjectRow", "%1 new"),
    ("ProjectRow", "%1 changed"),
    ("ProjectRow", "%1 port no longer detected"),
    ("ProjectRow", "%1 override differs"),
    ("ProjectRow", "%1 duplicate"),
    ("ProjectRow", "%1 missing"),
    ("ProjectRow", "%1 is hidden"),
    ("ProjectRow", "%1 is shown again"),
    ("ProjectRow", "Start %1"),
    ("ProjectRow", "Stop %1"),
    ("ProjectRow", "Restart %1"),
    ("ProjectRow", "Open %1 in a browser"),
]


@pytest.mark.parametrize(("context", "source"), RECOVERED, ids=lambda v: v)
def test_a_recovered_fragment_is_extractable(extracted, context, source) -> None:
    """The strings LWSM-1252 and LWSM-1258 made visible to a translator.

    Asked of the EXTRACTOR, not of the AST, because that is the property the
    user gets: `test_every_translate_call_passes_literals_for_context_and_source`
    below holds the shape, and this holds the outcome. Both are wanted — a
    future call could satisfy the shape and still be dropped for a reason
    neither of us has met yet.

    Split across three defects that read as one: a loop variable in
    `_merge_parts` and again in the accessible-name loop (LWSM-1252), and a
    conditional inside the call in `set_project_hidden` (LWSM-1258).
    """
    assert source in extracted.get(context, set()), (
        f"lupdate did not extract {source!r} under {context!r}; "
        f"it is a user-visible string no translator can reach"
    )


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_every_translate_call_passes_literals_for_context_and_source(
    path: Path,
) -> None:
    """One regressed call site is invisible to the tests above (LWSM-1304).

    They ask whether extraction works at all and which contexts came back —
    neither notices one string going missing, which a mutant routing a single
    call through a variable confirmed. Parsed rather than grepped, for
    `test_layering.py`'s reason: the property is what the argument IS, and a
    substring search cannot tell a literal from a name.

    **Both arguments, since LWSM-1252/1258 closed the class.** The context
    argument was the whole check while `_TR_CONTEXT` was the only known way to
    lose a string. The source argument fails identically and did, three times
    in one file — twice through a loop variable and once through a conditional
    written inside the call. Checking one and not the other left half the
    defect uncovered, and no linter reports either.
    """
    offenders = [
        (node.lineno, offence)
        for node in _translate_calls(path)
        for offence in _offences(node)
    ]

    assert not offenders, (
        f"{path.name}: lupdate would skip these calls, so their strings are "
        f"not extractable and no translator can reach them: {offenders}"
    )
