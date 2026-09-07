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


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_every_translate_call_names_its_context_as_a_literal(path: Path) -> None:
    """One regressed call site is invisible to the tests above (LWSM-1304).

    They ask whether extraction works at all and which contexts came back —
    neither notices one string out of eighty going missing, which a mutant
    routing a single call through a variable confirmed. Parsed rather than
    grepped, for `test_layering.py`'s reason: the property is what the argument
    IS, and a substring search cannot tell a literal from a name.
    """
    offenders = [
        (node.lineno, ast.unparse(node.args[0]))
        for node in _translate_calls(path)
        if not node.args or not isinstance(node.args[0], ast.Constant)
    ]

    assert not offenders, (
        f"{path.name}: lupdate skips a call whose context is not a literal, so "
        f"these strings would silently stop being extractable: {offenders}"
    )
