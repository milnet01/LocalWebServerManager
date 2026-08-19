"""LWSM-1031 — settings.json, the file the theme choice survives a restart in.

The rule this file exists to hold is the one that separates `settings.py` from
`registry.py`: **a bad settings file must never cost the user a window.** Every
test below that feeds `load()` something hostile asserts two things — the
defaults came back, and a reason says why — because returning the defaults
silently is the same failure as raising.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from lwsm import settings
from lwsm.configfile import ConfigFileError
from lwsm.settings import Settings, SettingsError


def write(path: Path, document: object) -> Path:
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


# --- where the file lives -----------------------------------------------------


def test_settings_sits_beside_projects_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """Derived from `registry.default_projects_path`, never recomputed, so the
    two files cannot land in different directories when one is fixed."""
    monkeypatch.setenv("XDG_CONFIG_HOME", "/xdg")

    from lwsm.registry import default_projects_path

    assert settings.default_settings_path() == Path(
        "/xdg/localwebservermanager/settings.json"
    )
    assert settings.default_settings_path().parent == default_projects_path().parent


# --- load: never raises, always says why --------------------------------------


def test_a_missing_file_is_the_defaults_and_is_not_a_complaint(tmp_path: Path) -> None:
    """First run. A clean machine must not report a problem it does not have,
    which is why this is the one refusal-free path that returns defaults."""
    result = settings.load(tmp_path / "settings.json")

    assert result.settings == Settings()
    assert result.reasons == []


@pytest.mark.parametrize(
    ("document", "fragment"),
    [
        ({"schema_version": 1, "theme": 7}, "is not a string"),
        ({"schema_version": 1, "theme": True}, "is not a string"),
        ({"schema_version": 1, "theme": ""}, "is not a usable id"),
        ({"schema_version": 1, "theme": "x" * 65}, "is not a usable id"),
        ({"schema_version": 2, "theme": "emerald"}, "schema_version"),
        ({"schema_version": None, "theme": "emerald"}, "schema_version"),
        ([1, 2, 3], "not an object"),
    ],
)
def test_a_hostile_field_yields_the_default_and_a_reason(
    tmp_path: Path, document: object, fragment: str
) -> None:
    """`type(v) is not str` rather than `isinstance`, so `"theme": true` is
    refused — `isinstance(True, int)` is the reason `registry._is_int` exists
    and the same hand-edited file reaches here.

    The schema_version rows are ADR-0005's rule applied to preferences: a v2
    file may have re-used a key, so a version we do not know is not partially
    parsed.
    """
    path = write(tmp_path / "settings.json", document)

    result = settings.load(path)

    assert result.settings == Settings()
    assert len(result.reasons) == 1
    assert fragment in result.reasons[0]


def test_a_file_that_is_not_json_yields_the_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(b"{not json at all")

    result = settings.load(path)

    assert result.settings == Settings()
    assert "is not valid JSON" in result.reasons[0]


def test_a_reason_cannot_forge_a_second_log_record(tmp_path: Path) -> None:
    """Every reason interpolates a fragment of a hand-edited file, so it goes
    through `configfile.quoted` — which escapes a newline (LWSM-1078). A
    rejection reason reaches both the app log and the status bar.
    """
    path = write(tmp_path / "settings.json", {"schema_version": 1, "theme": "a\nb"})

    result = settings.load(path)

    assert result.reasons
    assert "\n" not in result.reasons[0]


def test_a_fifo_at_the_path_does_not_hang_the_load(tmp_path: Path) -> None:
    """`configfile.read_bounded` opens O_NONBLOCK and refuses a non-regular
    file. Without it `Path.read_bytes()` blocks forever — no window, no error,
    no log line (LWSM-1104, measured on projects.json)."""
    path = tmp_path / "settings.json"
    os.mkfifo(path)

    result = settings.load(path)

    assert result.settings == Settings()
    assert "cannot be read" in result.reasons[0]


def test_a_directory_at_the_path_is_a_reason_and_not_a_first_run(
    tmp_path: Path,
) -> None:
    """The two default-returning paths must stay distinguishable.

    A missing file is first run and earns no reason; anything else that cannot
    be read earns one. Folding the second into the first is a one-word edit
    (`except (FileNotFoundError, IsADirectoryError)`) that no other test here
    could see — it survived the mutation probe, which is why this exists.
    """
    path = tmp_path / "settings.json"
    path.mkdir()

    result = settings.load(path)

    assert result.settings == Settings()
    assert result.reasons, "a path that cannot be read must not read as a first run"
    assert "cannot be read" in result.reasons[0]


def test_an_oversized_file_is_refused_rather_than_read(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(b"x" * ((1 << 20) + 1))

    result = settings.load(path)

    assert result.settings == Settings()
    assert "cannot be read" in result.reasons[0]


def test_a_good_file_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"

    settings.save(path, Settings(theme="emerald"))

    result = settings.load(path)
    assert result.settings.theme == "emerald"
    assert result.reasons == []


def test_an_unknown_theme_id_is_stored_and_not_second_guessed(
    tmp_path: Path,
) -> None:
    """Membership is `theme.theme_for_id`'s question, not this module's — a
    core module may not import the theme layer (`coding.md § O1`). This test
    pins that split: the id is carried through, shape-checked only.
    """
    path = write(
        tmp_path / "settings.json", {"schema_version": 1, "theme": "solarized"}
    )

    result = settings.load(path)

    assert result.settings.theme == "solarized"
    assert result.reasons == []


# --- save ---------------------------------------------------------------------


def test_the_file_is_written_at_0600_in_a_0700_directory(tmp_path: Path) -> None:
    """The mode comes from `mkstemp` and `prepare_config_dir`, not from the
    umask — `Path.write_text` creates at `0666 & ~umask`, which is how a config
    file gets a mode nobody chose."""
    path = tmp_path / "cfg" / "settings.json"

    settings.save(path, Settings(theme="ledger"))

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_a_symlink_at_the_target_is_refused_rather_than_destroyed(
    tmp_path: Path,
) -> None:
    """`os.replace` replaces the *symlink*, not its target, so the user's
    deliberate indirection becomes a plain file. Measured on Python 3.13 for
    projects.json; `settings.json` reaches the same writer."""
    real = tmp_path / "real.json"
    real.write_text("{}", encoding="utf-8")
    link = tmp_path / "settings.json"
    link.symlink_to(real)

    with pytest.raises(SettingsError, match="symlink"):
        settings.save(link, Settings(theme="mint"))

    assert link.is_symlink()
    assert real.read_text(encoding="utf-8") == "{}"


def test_a_write_failure_raises_settings_error_not_config_file_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`SettingsError` subclasses `ConfigFileError`, so a caller catching the
    narrow type must actually receive the narrow type — the same conversion
    `registry.save_projects` makes and for the same reason."""

    def refuse(*args: object, **kwargs: object) -> None:
        raise ConfigFileError("could not be written (read-only file system)")

    monkeypatch.setattr(settings, "write_json_atomically", refuse)

    with pytest.raises(SettingsError, match="read-only"):
        settings.save(tmp_path / "settings.json", Settings())


def test_the_saved_document_carries_its_schema_version(tmp_path: Path) -> None:
    """LWSM-1018 grows this file with its own fields. Without the version, the
    day it changes shape there is nothing to branch on."""
    path = tmp_path / "settings.json"

    settings.save(path, Settings(theme="graphite"))

    document = json.loads(path.read_text(encoding="utf-8"))
    assert document == {"schema_version": settings.SCHEMA_VERSION, "theme": "graphite"}
