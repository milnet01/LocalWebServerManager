"""Entry point — the `lwsm` console script and `python -m lwsm`.

Contract: `CLAUDE.md § Module map` — `main()` handles `--version`, configures
logging, and prints where it is logging to. No GUI until P02.

These tests cover the two properties a bare `if "--version" in args` cannot
give: an unrecognised option must be refused rather than ignored, and a log
directory the app cannot use must not stop it starting. Both came out of the
2026-08-06 review.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from lwsm import __version__, applog
from lwsm.__main__ import main


@pytest.fixture(autouse=True)
def _reset_logging():
    """Same process-global reset as `test_applog.py`.

    `main()` configures the real logger, so without this the first test here
    leaks a handler into every later one.
    """
    logger = logging.getLogger(applog.LOGGER_NAME)
    propagate = logger.propagate
    yield
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
    logger.setLevel(logging.NOTSET)
    logger.propagate = propagate


def test_version_is_reported_and_exits_clean(capsys):
    """`--version` is a documented surface, so it is pinned.

    `argparse`'s `action="version"` raises `SystemExit(0)` rather than
    returning, which is the conventional behaviour and what a shell `&&` chain
    expects.
    """
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_an_unknown_option_is_refused(capsys):
    """A membership test accepted anything it did not recognise.

    Before the fix, `main(["--versoin", "--help", "junk"])` printed the startup
    banner and returned 0 — so a typo'd flag looked like it had been honoured,
    and `--help` did not exist at all. Verified 2026-08-06.
    """
    with pytest.raises(SystemExit) as exit_info:
        main(["--versoin"])

    assert exit_info.value.code == 2, "an unusable argument list must not be a success"
    assert "usage" in capsys.readouterr().err.lower()


def test_starts_even_when_the_state_directory_is_unusable(
    monkeypatch, capsys, tmp_path: Path
):
    """A diagnostic log that cannot be written is a reason to warn, not to die.

    `configure_logging` raises `OSError` for a read-only filesystem, a full
    disk, an unwritable `~/.local/state` — and, since the 2026-08-06 hardening,
    for every hostile filesystem state it now refuses. Uncaught, that turned a
    log-integrity attack into a total-outage one: reproduced as an unhandled
    traceback and exit 1. Here the state path's parent is a regular file, so
    `mkdir` cannot succeed.
    """
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory\n")
    monkeypatch.setenv("XDG_STATE_HOME", str(blocker))

    assert main([]) == 0, "an unusable log directory must not stop the app starting"

    captured = capsys.readouterr()
    assert "log" in captured.err.lower(), (
        f"the failure was not reported to the user: {captured.err!r}"
    )
