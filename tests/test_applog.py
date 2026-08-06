"""Application log — LWSM-1026.

Contract: `docs/design.md § Observability` — an app-level log at
`$XDG_STATE_HOME/localwebservermanager/app.log` (falling back to `~/.local/state`
when that variable is unset), INFO by default, rotating at 1 MB with 5 kept,
recording every spawn, signal, port-probe result and config write.

These tests name what the design promises, not what the implementation does
(testing.md § 2). None of them touches the real state directory: T1 forbids it,
and a test that writes to `~/.local/state` on a developer's machine is a side
effect wearing a test's clothes.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

from lwsm import applog


def _our_handlers() -> list[RotatingFileHandler]:
    """Narrow to our own handler type, so an unrelated handler on the `lwsm`
    logger cannot mask a duplicate.

    (Not, as an earlier version of this comment claimed, because pytest
    attaches handlers here — verified 2026-08-03: pytest's `LogCaptureHandler`
    goes on the ROOT logger, and `lwsm` has none of its own.)
    """
    return [
        h for h in applog.get_logger().handlers if isinstance(h, RotatingFileHandler)
    ]


@pytest.fixture(autouse=True)
def _reset_logging():
    """Undo configure_logging between tests.

    Logging is process-global, so without this the first test to configure a
    handler leaks it into every later test and the assertions start passing for
    the wrong reason. `propagate` is restored too: leaving it False would make
    every later module's `caplog` assertions on an `lwsm.*` logger see nothing
    — which fails mysteriously, or passes for the wrong reason when the
    assertion is about absence.
    """
    logger = logging.getLogger(applog.LOGGER_NAME)
    propagate = logger.propagate
    yield
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
    logger.setLevel(logging.NOTSET)
    logger.propagate = propagate


def test_log_file_lands_in_the_state_dir_it_was_given(tmp_path: Path):
    """The state directory is injected, never derived inside the function.

    This is what makes T1 satisfiable at all: a module that computes
    `~/.local/state/...` internally cannot be tested without writing there.
    """
    applog.configure_logging(state_dir=tmp_path)

    assert (tmp_path / "app.log").exists(), (
        f"contents of {tmp_path}: {list(tmp_path.iterdir())}"
    )


def test_default_state_dir_follows_the_xdg_spec(monkeypatch, tmp_path: Path):
    """Honours an absolute XDG_STATE_HOME; ignores a relative one; falls back
    to ~/.local/state when unset.

    `HOME` is redirected so the fallback branch asserts a literal rather than
    re-deriving the implementation's own expression (testing.md § 9), and so
    the test does not depend on the ambient environment having a home at all.
    """
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert applog.default_state_dir() == tmp_path / "localwebservermanager"

    # The XDG spec says a relative value must be ignored, not resolved.
    monkeypatch.setenv("XDG_STATE_HOME", "relative/path")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert applog.default_state_dir() == (
        tmp_path / ".local" / "state" / "localwebservermanager"
    ), "a relative XDG_STATE_HOME must be ignored in favour of the default"

    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    assert applog.default_state_dir() == (
        tmp_path / ".local" / "state" / "localwebservermanager"
    )


def test_get_logger_does_not_double_the_package_prefix():
    """Modules pass `__name__`, which already starts with `lwsm.`.

    Without this, every module in the package logs as `lwsm.lwsm.<module>` —
    which still reaches the file, so nothing looks broken, while the log names
    its own modules wrongly and per-subsystem level control targets a logger
    nothing writes to.
    """
    assert applog.get_logger("lwsm.applog").name == "lwsm.applog"
    assert applog.get_logger("scanner").name == "lwsm.scanner"
    assert applog.get_logger().name == "lwsm"


def test_idempotent_through_a_symlinked_state_dir(tmp_path: Path):
    """The duplicate-handler guard must survive a symlinked path component.

    `FileHandler.baseFilename` is `abspath` (symlinks intact) while
    `Path.resolve()` follows them, so comparing the two made the guard miss and
    wrote every line twice. A symlinked `~/.local/state` is common with dotfile
    managers, and `tmp_path` alone never reproduces it.
    """
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)

    applog.configure_logging(state_dir=link)
    applog.configure_logging(state_dir=link)
    applog.get_logger().info("once")

    assert len(_our_handlers()) == 1, "symlinked path defeated the idempotence guard"
    lines = (real / "app.log").read_text().strip().splitlines()
    assert len(lines) == 1, f"line written {len(lines)}x: {lines}"


def test_reconfiguring_elsewhere_replaces_the_handler(tmp_path: Path):
    """A second call with a different directory must not leave the first open.

    Otherwise the logger fans every record out to both files and the returned
    path — documented as "the path being written to" — is only half true.
    """
    first = tmp_path / "first"
    second = tmp_path / "second"
    applog.configure_logging(state_dir=first)
    applog.configure_logging(state_dir=second)
    applog.get_logger().info("only in second")

    assert len(_our_handlers()) == 1
    assert "only in second" in (second / "app.log").read_text()
    assert "only in second" not in (first / "app.log").read_text()


def test_state_dir_and_log_are_not_world_readable(tmp_path: Path):
    """The log records the user's whole project inventory and layout.

    `.gitignore` treats that as private — writing it 0644 under the default
    umask would contradict the project's own posture, and `coding.md § 7` asks
    for 0600 on anything config-like.
    """
    state = tmp_path / "state"
    applog.configure_logging(state_dir=state)

    dir_mode = state.stat().st_mode & 0o777
    file_mode = (state / "app.log").stat().st_mode & 0o777
    assert dir_mode == 0o700, f"state dir is {oct(dir_mode)}, want 0o700"
    assert file_mode == 0o600, f"app.log is {oct(file_mode)}, want 0o600"


def test_refuses_to_write_through_a_planted_symlink(tmp_path: Path):
    """A symlink at app.log would redirect the log into any file we own.

    Attacker-chosen content (a managed server's own output reaches this log
    indirectly) appended into an arbitrary file is the impact; `O_NOFOLLOW`
    turns it into an error instead. Verified as live behaviour before the fix.
    """
    state = tmp_path / "state"
    state.mkdir()
    victim = tmp_path / "victim.txt"
    victim.write_text("original\n")
    (state / "app.log").symlink_to(victim)

    with pytest.raises(OSError):
        applog.configure_logging(state_dir=state)

    assert victim.read_text() == "original\n", "log was written through the symlink"


def test_default_level_is_info_and_info_is_written(tmp_path: Path):
    applog.configure_logging(state_dir=tmp_path)
    applog.get_logger().info("a spawn happened")

    assert "a spawn happened" in (tmp_path / "app.log").read_text()


def test_debug_is_suppressed_at_the_default_level(tmp_path: Path):
    """ "INFO by default" is a claim about what is EXCLUDED as much as included.

    Paired with a positive control: a bare "DEBUG is absent" assertion also
    holds when the handler was never attached, the formatter is broken, or the
    level is CRITICAL — it is a negative with nothing proving the logger is
    alive.
    """
    applog.configure_logging(state_dir=tmp_path)
    applog.get_logger().debug("noisy internal detail")
    applog.get_logger().info("kept")

    text = (tmp_path / "app.log").read_text()
    assert "kept" in text, f"INFO was dropped too — the logger is dead: {text!r}"
    assert "noisy internal detail" not in text, f"DEBUG leaked through: {text!r}"


def test_level_is_overridable(tmp_path: Path):
    applog.configure_logging(state_dir=tmp_path, level=logging.DEBUG)
    applog.get_logger().debug("wanted this time")

    assert "wanted this time" in (tmp_path / "app.log").read_text()


def test_rotation_is_1mb_with_5_backups(tmp_path: Path):
    """The design states both numbers, so both are pinned here.

    Asserted against the handler rather than by writing a megabyte of log
    lines: the behaviour under test is the configuration, and a test that
    writes 5 MB to prove it would be slow for no extra confidence.
    """
    applog.configure_logging(state_dir=tmp_path)
    handlers = _our_handlers()

    assert len(handlers) == 1, "exactly one file handler, or lines get duplicated"
    handler = handlers[0]
    assert handler.maxBytes == 1024 * 1024
    assert handler.backupCount == 5


def test_configure_is_idempotent(tmp_path: Path):
    """Called twice, it must not stack a second handler.

    Every line would otherwise appear twice in the file — the kind of defect
    that looks like a logging bug and is actually a setup bug.
    """
    applog.configure_logging(state_dir=tmp_path)
    applog.configure_logging(state_dir=tmp_path)

    assert len(_our_handlers()) == 1


def test_creates_a_missing_state_dir(tmp_path: Path):
    """First run on a clean machine has no state directory at all."""
    nested = tmp_path / "not" / "yet" / "there"
    applog.configure_logging(state_dir=nested)

    assert (nested / "app.log").exists()


def test_each_line_carries_a_timestamp_and_a_level(tmp_path: Path):
    """ "Why did it say that?" needs when and how bad, not just what."""
    applog.configure_logging(state_dir=tmp_path)
    applog.get_logger().warning("port 5000 held by another user's process")

    line = (tmp_path / "app.log").read_text().splitlines()[0]
    assert "WARNING" in line, f"no level in: {line!r}"
    assert "port 5000 held by another user's process" in line, (
        f"no message in: {line!r}"
    )
    # ISO-ish date at the head of the line: 2026-08-03 ...
    # Split, so a failure names which half broke — a compound `and` reports
    # only `assert False` and never shows the line.
    assert line[:4].isdigit(), f"no 4-digit year at line start: {line!r}"
    assert line[4] == "-", f"no ISO date separator at position 4: {line!r}"
