"""LWSM-1246 — the derivation tool must not print a failure as a success.

`scripts/derive_state_tokens.py` solves each state token's lightness against
the palette's three surfaces and prints the result for pasting into
`theme.py`. When no lightness cleared the floor it printed the closest
candidate in the *identical* format to a passing one, did not count it, ended
with "# 0 shortfall(s)" and exited 0.

That is this project's own recorded class, in its most expensive form: a tool
that analysed nothing looks exactly like a tool that found nothing — and here
the output is meant to be copied into the source.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import re
from pathlib import Path

import pytest

from lwsm.theme import Theme

ROOT = Path(__file__).resolve().parent.parent


def load_script():
    """Import the script by path — `scripts/` is not on `sys.path`."""
    path = ROOT / "scripts" / "derive_state_tokens.py"
    spec = importlib.util.spec_from_file_location("derive_state_tokens", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def unsolvable_theme() -> Theme:
    """A palette whose three surfaces span the range, so no hue can clear 7:1.

    Reachable rather than contrived, which is the bullet's point: the floor is
    taken against the WORST of the three surfaces, so any palette with both a
    near-black and a near-white surface makes the constraint unsatisfiable.
    """
    base = Theme.default()
    return dataclasses.replace(
        base,
        window="#000000",
        base="#ffffff",
        alt_base="#808080",
        high_contrast=True,
    )


def test_solve_reports_that_it_did_not_clear_the_floor() -> None:
    """The solver must say so, rather than returning its closest miss silently."""
    module = load_script()

    _value, _ratio, cleared = module.solve(
        0.33, 0.5, ["#000000", "#ffffff", "#808080"], 7.0, dark=True
    )

    assert cleared is False


def test_solve_still_reports_a_value_it_did_clear() -> None:
    """The passing path is unchanged, and says so."""
    module = load_script()

    value, ratio, cleared = module.solve(0.33, 0.5, ["#000000"], 3.0, dark=True)

    assert cleared is True
    assert value.startswith("#")
    assert ratio >= 3.0


def test_an_unsolvable_palette_is_counted_and_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """The WIRING, which is what actually bit: solve knowing is worth nothing
    if `main` prints the miss like a hit and returns 0 regardless.

    Dies on printing the value without the shortfall line, on not counting it,
    and on the unconditional `return 0`.
    """
    module = load_script()
    monkeypatch.setattr(module, "THEMES", {"unsolvable": unsolvable_theme()})

    status = module.main()
    out = capsys.readouterr().out

    assert status != 0, "a run that could not solve a token reported success"

    # Asserted on the message the new branch alone prints, not on the word
    # SHORTFALL. This fixture is hostile enough that the pre-existing
    # text/accent checks also fire, so the generic assertion passed against a
    # mutant that had removed the state-token branch entirely — a test green
    # for a reason unrelated to what it names.
    missed = out.count("cleared nothing")
    assert missed > 0, "a token that cleared no lightness was not reported as one"

    # And the pasteable form is NOT emitted for it: the whole hazard is that
    # this output is copied into `theme.py`.
    for token in module.STATES:
        if f"{token} cleared nothing" in out:
            assert f'{token}="' not in out, (
                f"{token} failed the floor and was still printed ready to paste"
            )

    total = re.search(r"# (\d+) shortfall", out)
    assert total is not None, out


def reported_total(module, capsys) -> int:
    module.main()
    out = capsys.readouterr().out
    found = re.search(r"# (\d+) shortfall", out)
    assert found is not None, out
    return int(found.group(1))


def test_each_unsolved_token_adds_one_to_the_count(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """Counted, not merely printed — measured as a DIFFERENCE.

    A plain `total >= misses` assertion could not see a mutant that dropped
    the increment, because this fixture is hostile enough that the
    text/muted_text/attention and accent checks fire on their own and pad the
    total past any threshold. Isolating the state-token contribution is not
    possible by choosing a gentler palette either: the floor is taken against
    the WORST of three surfaces, so any palette where a hue cannot be solved
    is one where the text tokens cannot be either.

    So the count is measured twice over the same palette with a different
    number of STATES, and the difference is attributable to nothing else.
    """
    module = load_script()
    monkeypatch.setattr(module, "THEMES", {"unsolvable": unsolvable_theme()})
    every = dict(module.STATES)
    assert len(every) > 1, "precondition: the difference needs more than one"

    monkeypatch.setattr(module, "STATES", dict(list(every.items())[:1]))
    with_one = reported_total(module, capsys)

    monkeypatch.setattr(module, "STATES", every)
    with_all = reported_total(module, capsys)

    assert with_all - with_one == len(every) - 1, (
        "an unsolved token was reported but left out of the count"
    )
