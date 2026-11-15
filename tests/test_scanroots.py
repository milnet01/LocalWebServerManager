"""LWSM-1562 — the scan-roots file reader's unreadable-file path."""

from __future__ import annotations

from pathlib import Path

import pytest

from lwsm import scanroots


def test_an_unreadable_scan_roots_file_is_logged_and_the_fallback_used(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """LWSM-1178's policy stands: an unreadable file never costs the window and
    scans the fallback. It must not be silent, though: a later save refuses
    with an error the user could tie to nothing seen before (04.6)."""
    config = tmp_path / "scan-roots"
    config.write_bytes(b"\xff\xfe not utf-8 \xff")

    with caplog.at_level("WARNING", logger="lwsm.scanroots"):
        roots = scanroots.default_scan_roots(config)

    assert roots == scanroots.scan_root_fallback()
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1, f"warnings: {warnings!r}"
    assert "scan-roots" in warnings[0]


def test_a_missing_scan_roots_file_is_not_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """No file is the first run, and nothing is wrong."""
    with caplog.at_level("WARNING", logger="lwsm.scanroots"):
        roots = scanroots.default_scan_roots(tmp_path / "scan-roots")

    assert roots == scanroots.scan_root_fallback()
    assert not caplog.records
