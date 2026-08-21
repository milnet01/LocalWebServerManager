"""LWSM-1005 INV-8, INV-8b — the core/UI split and the no-colours rule.

Both rules in `docs/standards/coding.md` are enforced by reading source rather
than by importing it: importing the module would only prove it does not reach
QtWidgets on the one path the import happens to take.

The import check parses the AST rather than grepping for the string. A
substring search reported every module here as a violation on its first run —
each one *documents* the rule in its docstring, and a docstring mentioning
QtWidgets is the opposite of a module importing it.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src" / "lwsm"

# A new core module is added here in the commit that creates it
# (`coding.md § O1`). `scanner.py` is the first to test that; `applog.py` was
# absent from this list while the criterion covered it, so the rule and its
# check disagreed and the check is the one that runs (LWSM-1006 § 4.7).
CORE_MODULES = [
    "applog.py",
    "configfile.py",
    "controller.py",
    "ports.py",
    "registry.py",
    "scanner.py",
    "settings.py",
    "supervisor.py",
]

# The complement of core, named explicitly rather than derived from
# `coding.md § O1` as it was once worded: that was a two-way split excluding
# only the two UI modules, so anything deriving from it pulled in
# `__main__.py`, which imports QtWidgets **by design** — and would redden
# `test_core_never_imports_qtwidgets` on the day the derivation landed.
NON_CORE_MODULES = {
    "mainwindow.py",
    "settingsdialog.py",
    "theme.py",
    "__main__.py",
    "__init__.py",
}

# theme.py is the token DEFINITION site, so the palette's values necessarily
# live there. § O7's rule is about widget code, and this allowlist is explicit
# rather than the pattern happening to miss it.
COLOUR_EXEMPT = {"theme.py"}
WIDGET_MODULES = ["mainwindow.py"]

# Named constants are colours too: `Qt.GlobalColor.red` and
# `QColorConstants.Red` both pin a value the theme is supposed to own, and both
# sailed past the hex-and-QColor pattern (LWSM-1111).
COLOUR_LITERAL = re.compile(
    r"#[0-9a-fA-F]{3,8}\b"
    r"|QColor\s*\("
    r"|Qt\.GlobalColor\.\w+"
    r"|QColorConstants\.[\w.]+"
)
PINNED_FONT = re.compile(r"QFont\s*\(\s*[\"']")


def strip_comments(source: str) -> str:
    """Source with comments removed and string literals untouched.

    This used to blank only lines whose first non-space character is `#`, so a
    **trailing** comment mentioning a hex value was reported as a colour
    literal — the check contradicting its own comment about comments
    (LWSM-1111). Splitting every line on `#` is not the fix either: it would
    cut a `#` inside a string. Tokenising is what tells the two apart.
    """
    lines = source.splitlines()
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            row, column = token.start
            lines[row - 1] = lines[row - 1][:column]
    return "\n".join(lines)


def imported_names(module: str) -> set[str]:
    """Every module name this file imports, at any nesting depth.

    Walks the tree rather than reading only top-level statements, so an import
    tucked inside a function or a `try` is caught too.
    """
    tree = ast.parse((SRC / module).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


@pytest.mark.parametrize("module", CORE_MODULES)
def test_core_never_imports_qtwidgets(module: str) -> None:
    offenders = {name for name in imported_names(module) if "QtWidgets" in name}
    assert not offenders, (
        f"{module} is a core module: a QtWidgets import is what makes it "
        f"need a display — found {sorted(offenders)}"
    )


def test_the_core_module_list_matches_the_criterion() -> None:
    """A source-invariant test (`testing.md § 3.6`): the list above is what
    actually enforces § O1, so a sixth core module that never reaches it is a
    `QtWidgets` import passing every gate — which is how `applog.py` came to be
    missing from it in the first place."""
    on_disk = {path.name for path in SRC.glob("*.py")}

    assert on_disk - NON_CORE_MODULES == set(CORE_MODULES)


def test_the_import_check_can_actually_fail(tmp_path: Path) -> None:
    """Guards the check itself.

    An AST walk that found nothing would pass every module silently, which is
    indistinguishable from a clean tree. This proves the detector fires.
    """
    offender = tmp_path / "offender.py"
    offender.write_text("from PySide6.QtWidgets import QLabel\n", encoding="utf-8")
    tree = ast.parse(offender.read_text(encoding="utf-8"))
    found = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert any("QtWidgets" in name for name in found)


@pytest.mark.parametrize("module", WIDGET_MODULES)
def test_no_colour_literals_in_widget_code(module: str) -> None:
    assert module not in COLOUR_EXEMPT
    source = (SRC / module).read_text(encoding="utf-8")
    # A hex value quoted in a comment explaining the rule is not a breach of it.
    found = COLOUR_LITERAL.findall(strip_comments(source))
    assert not found, f"{module} names a colour instead of a theme token: {found}"


@pytest.mark.parametrize(
    "snippet",
    [
        'self._pen = QColor("#ff0000")',
        "self._pen = QColor(255, 0, 0)",
        "painter.setPen(Qt.GlobalColor.red)",
        "painter.setPen(QColorConstants.Red)",
    ],
    ids=["hex", "rgb", "globalcolor", "colorconstants"],
)
def test_the_colour_check_can_actually_fail(snippet: str) -> None:
    """The two named-constant forms passed the detector unchallenged, so a
    widget could pin a colour and INV-8b would report green (LWSM-1111)."""
    assert COLOUR_LITERAL.search(strip_comments(snippet)), snippet


def test_a_hex_value_in_a_trailing_comment_is_not_a_breach() -> None:
    """The detector's own comment said comments are stripped; only whole-line
    ones were, so this line was reported as a colour literal (LWSM-1111)."""
    source = "width = 1  # the accent token is #2f6feb in the default palette\n"
    assert not COLOUR_LITERAL.search(strip_comments(source))


def test_a_hash_inside_a_string_is_not_mistaken_for_a_comment() -> None:
    """The other half of the same trade-off: splitting on `#` would truncate
    this line and hide a real breach behind it."""
    source = 'label.setText("#1")  # a caption\nself._pen = QColor("#ff0000")\n'
    assert COLOUR_LITERAL.search(strip_comments(source))


@pytest.mark.parametrize("module", WIDGET_MODULES)
def test_no_pinned_font_family_in_widget_code(module: str) -> None:
    source = (SRC / module).read_text(encoding="utf-8")
    assert not PINNED_FONT.search(source), (
        f"{module} pins a font family; § O7 says ask for the system font"
    )


def test_the_exempt_module_is_the_one_that_holds_the_colours() -> None:
    # Guards the allowlist itself: if theme.py ever stops holding the palette,
    # the exemption is protecting nothing and should go.
    source = (SRC / "theme.py").read_text(encoding="utf-8")
    assert COLOUR_LITERAL.search(source), "theme.py is meant to be the colour site"


def test_registry_never_imports_the_scanner() -> None:
    """LWSM-1007 § 4.1 — the dependency direction is `scanner` → `registry`.

    `scanner.py` imports `DECLARED_PORT_RANGE` and now `LauncherKind` from
    `registry.py`, so a runtime `from lwsm.scanner import ...` added here closes
    a cycle and **the package stops importing at all**, on both entry orders:

        python3 -c "import lwsm.registry"
          ImportError: cannot import name 'DECLARED_PORT_RANGE' from partially
          initialized module 'lwsm.registry'
        python3 -c "import lwsm.scanner"
          ImportError: cannot import name 'LauncherKind' from partially
          initialized module 'lwsm.scanner'

    An AST assertion rather than the obvious form — importing each module first
    in a fresh interpreter. That spawns a process, so it would carry the
    `integration` marker and be skipped by `local-ci.sh --fast`, which is the
    run a developer is most likely to be doing. This is in-process, is the
    invariant the cycle actually violates, and sits beside the other structural
    rules that are enforced by parsing rather than grepping.
    """
    assert "lwsm.scanner" not in imported_names("registry.py")
