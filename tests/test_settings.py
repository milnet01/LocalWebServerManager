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
from dataclasses import replace
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


@pytest.mark.parametrize(
    ("body", "why"),
    [
        ('{"schema_version": 1, "theme": "emerald",}', "a JSON typo"),
        ("[1, 2, 3]", "a non-object root"),
        ('{"schema_version": 2, "theme": "emerald"}', "an unknown schema_version"),
    ],
)
def test_a_refused_document_says_so_and_not_only_why(
    tmp_path: Path, body: str, why: str
) -> None:
    """The analogue of `registry.rows_refused` (LWSM-1163).

    `load()` is total, so a whole-document refusal and a first run both come
    back as `Settings()` — and the difference matters enormously to a WRITER,
    because writing the defaults back over the first is data loss and over the
    second is correct. A reason string cannot carry that: `reasons` is also
    non-empty when a single field was refused, where writing IS correct.
    """
    path = tmp_path / "settings.json"
    path.write_text(body, encoding="utf-8")

    result = settings.load(path)
    assert result.settings == Settings(), why
    assert result.reasons, why
    assert result.document_refused is True, why


@pytest.mark.parametrize(
    ("body", "why"),
    [
        ("", "a missing file"),
        ('{"schema_version": 1, "theme": "emerald"}', "a clean file"),
        ('{"schema_version": 1, "text_scale": 9999}', "one refused field"),
    ],
)
def test_a_document_that_was_read_is_not_reported_as_refused(
    tmp_path: Path, body: str, why: str
) -> None:
    """The other half, and the half that keeps the flag from being useless.

    A first run has nothing to lose and must still be writable, and a file
    whose SHAPE was fine keeps every field it could parse — so writing the
    default back over the one it could not is what the user asked for.
    """
    path = tmp_path / "settings.json"
    if body:
        path.write_text(body, encoding="utf-8")

    assert settings.load(path).document_refused is False, why


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
    assert result.document_refused is True, (
        "an unreadable file must not be written back as defaults (LWSM-1163)"
    )


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
    assert result.document_refused is True, (
        "an unreadable file must not be written back as defaults (LWSM-1163)"
    )


def test_a_deeply_nested_document_is_a_reason_and_not_a_crash(tmp_path: Path) -> None:
    """`RecursionError` is not a `ValueError`, so it escaped by itself.

    LWSM-1164, and LWSM-1116's shape exactly: the guard exists next door and
    is missing here. `registry.py` catches `(ValueError, RecursionError)` with
    a comment saying why — `RecursionError` -> `RuntimeError` -> `Exception`,
    so it needs naming whatever `except ValueError` would catch — and
    `settings.load()` named only `(UnicodeDecodeError, ValueError)`.

    40 KB, well inside `MAX_FILE_BYTES`, so the size cap never sees it. It
    propagated out of `build_window`, whose `try` catches only `RegistryError`,
    and out of `main()`: the app died with a traceback and no window, every
    launch, until someone deleted the file by hand. Three passages promised
    this could not happen — `load()`'s docstring, the module docstring, and
    `build_window`'s comment.
    """
    path = tmp_path / "settings.json"
    path.write_text("[" * 20_000 + "]" * 20_000, encoding="utf-8")

    result = settings.load(path)

    assert result.settings == Settings()
    assert result.reasons
    assert result.document_refused is True


def test_an_oversized_file_is_refused_rather_than_read(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(b"x" * ((1 << 20) + 1))

    result = settings.load(path)

    assert result.settings == Settings()
    assert "cannot be read" in result.reasons[0]
    assert result.document_refused is True, (
        "an unreadable file must not be written back as defaults (LWSM-1163)"
    )


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
    assert document == {
        "schema_version": settings.SCHEMA_VERSION,
        "theme": "graphite",
        # Every field, written even at its default (LWSM-1032). A key that
        # appears only when it differs is one a hand-editor has to guess about.
        # This is the one place the whole document shape is asserted, so a
        # field added without a decision about that lands here as a failure.
        "text_scale": 100,
        # LWSM-1018's two. Scan roots are deliberately NOT here: they stay in
        # the `scan-roots` file (LWSM-1144), and this assertion is what would
        # catch someone quietly copying them in.
        "poll_interval_ms": 1000,
        "log_max_mib": 5,
        # LWSM-1033's five, and the decision this assertion demands is
        # ADR-0007: plain integers and a boolean, never a `saveGeometry()`
        # blob, so a user who cannot reach the window can fix it by editing
        # the file. `null` until the window has been closed once — there is no
        # position a window has never been at, and 0 is a real coordinate.
        "x": None,
        "y": None,
        "width": None,
        "height": None,
        "maximized": False,
    }


# --- LWSM-1032: the text-size setting -----------------------------------------


def test_the_text_scale_defaults_to_a_hundred_percent(tmp_path: Path) -> None:
    """A first run must not be magnified. The control multiplies the desktop's
    own font (`design-accessibility.md § Accessibility`), so 100 % means "whatever the
    desktop already said" rather than a size of our choosing."""
    assert Settings().text_scale == 100
    assert settings.load(tmp_path / "absent.json").settings.text_scale == 100


def test_a_stored_text_scale_survives_the_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"

    settings.save(path, Settings(theme="graphite", text_scale=175))

    result = settings.load(path)
    assert result.reasons == []
    assert result.settings == Settings(theme="graphite", text_scale=175)


@pytest.mark.parametrize(
    "stored",
    [
        99,  # below the floor
        201,  # above the ceiling
        0,
        -100,
        "150",  # the shape a hand-editor most plausibly writes
        150.0,  # JSON has one number type and a float is not an int here
        True,  # `isinstance(True, int)` is True, and the file is hand-editable
        None,
        [150],
    ],
)
def test_an_unusable_text_scale_falls_back_and_says_so(tmp_path: Path, stored) -> None:
    """The whole file is still usable — `load()` never raises — but the user is
    told which field was ignored.

    `None` is in the list deliberately, and it is the one that is NOT a
    refusal: `_theme_or_reason` treats a missing key and an explicit `null`
    alike, and this field follows it rather than inventing a second rule.
    """
    path = write(
        tmp_path / "settings.json", {"schema_version": 1, "text_scale": stored}
    )

    result = settings.load(path)

    assert result.settings.text_scale == 100
    if stored is None:
        assert result.reasons == [], "an absent field is not a complaint"
    else:
        assert len(result.reasons) == 1
        assert "text_scale" in result.reasons[0]


def test_a_bad_text_scale_does_not_cost_the_theme(tmp_path: Path) -> None:
    """The two fields are independent. A file with one unusable field must keep
    the other — the shape `registry`'s "a bad port loses the field, not the
    row" already has, one file along."""
    path = write(
        tmp_path / "settings.json",
        {"schema_version": 1, "theme": "graphite", "text_scale": 5000},
    )

    result = settings.load(path)

    assert result.settings.theme == "graphite"
    assert result.settings.text_scale == 100
    assert len(result.reasons) == 1


# --- LWSM-1018's two numbers --------------------------------------------------
#
# Parametrised over BOTH fields rather than written once for one of them. The
# code branches on a closed set of bounded integers, and CLAUDE.md's
# one-row-fixture trap is explicit that a closed set needs a fixture per member:
# a helper that read the wrong bound for one field would otherwise pass.

BOUNDED = [
    ("poll_interval_ms", settings.MIN_POLL_INTERVAL_MS, settings.MAX_POLL_INTERVAL_MS),
    ("log_max_mib", settings.MIN_LOG_MAX_MIB, settings.MAX_LOG_MAX_MIB),
    # LWSM-1033's four. Two bounds, not one: a coordinate may be negative,
    # because a second monitor to the left of the primary one is at a negative
    # x, and a size may not. Listed here rather than given tests of their own
    # for the reason the comment above gives — a helper reading the wrong
    # bound for one field passes every test written for another.
    ("x", settings.MIN_WINDOW_COORD, settings.MAX_WINDOW_COORD),
    ("y", settings.MIN_WINDOW_COORD, settings.MAX_WINDOW_COORD),
    ("width", settings.MIN_WINDOW_PX, settings.MAX_WINDOW_PX),
    ("height", settings.MIN_WINDOW_PX, settings.MAX_WINDOW_PX),
]


@pytest.mark.parametrize(("field", "low", "high"), BOUNDED)
def test_a_bounded_number_survives_a_round_trip(
    tmp_path: Path, field: str, low: int, high: int
) -> None:
    """Saved, re-read, and the same value comes back with no complaint."""
    path = tmp_path / "settings.json"
    chosen = high - 1

    settings.save(path, replace(Settings(), **{field: chosen}))
    result = settings.load(path)

    assert getattr(result.settings, field) == chosen
    assert result.reasons == []


@pytest.mark.parametrize(("field", "low", "high"), BOUNDED)
@pytest.mark.parametrize("offset", [-1, 1], ids=["below", "above"])
def test_a_number_outside_its_range_is_refused_with_a_reason(
    tmp_path: Path, field: str, low: int, high: int, offset: int
) -> None:
    """Both ends, because a one-sided bound is a bound nobody checked.

    Dies on widening either comparison in `_bounded_int_or_reason` to `<`/`>`.
    """
    out_of_range = low - 1 if offset < 0 else high + 1
    path = write(
        tmp_path / "settings.json",
        {
            "schema_version": settings.SCHEMA_VERSION,
            field: out_of_range,
        },
    )

    result = settings.load(path)

    assert getattr(result.settings, field) == getattr(Settings(), field)
    assert any(field in reason and "outside" in reason for reason in result.reasons), (
        f"{field}={out_of_range} was defaulted with no reason saying why"
    )


@pytest.mark.parametrize(("field", "low", "high"), BOUNDED)
@pytest.mark.parametrize("value", [True, 1.5, "1000", None, [], {}], ids=str)
def test_a_number_that_is_not_a_whole_number_is_refused(
    tmp_path: Path, field: str, low: int, high: int, value: object
) -> None:
    """`True` and `1.5` are the two that matter, and both are live cases.

    `isinstance(True, int)` is True and `json.loads` produces a real `bool`, so
    without the `type(...) is int` check `true` reads as 1 — inside no range
    here, but the complaint the user would get names a number nobody wrote. A
    float is refused rather than rounded, because a value `save()` cannot
    round-trip is one it would silently rewrite under a user who hand-edited it.

    `None` is the exception and is asserted as such: a missing key and an
    explicit `null` both mean "not set", so neither earns a reason.
    """
    path = write(
        tmp_path / "settings.json",
        {
            "schema_version": settings.SCHEMA_VERSION,
            field: value,
        },
    )

    result = settings.load(path)

    assert getattr(result.settings, field) == getattr(Settings(), field)
    if value is None:
        assert result.reasons == [], "an explicit null is not a refusal"
    else:
        assert any(field in reason for reason in result.reasons)


@pytest.mark.parametrize(("field", "low", "high"), BOUNDED)
def test_a_bad_field_keeps_every_other_field(
    tmp_path: Path, field: str, low: int, high: int
) -> None:
    """One unusable value must not drag the rest back to their defaults.

    This is `registry`'s rule — a bad port loses the field, not the row —
    applied to the settings file. Dies on any `return LoadResult(Settings(), ...)`
    added to the per-field loop.
    """
    document: dict[str, object] = {
        "schema_version": settings.SCHEMA_VERSION,
        "theme": "graphite",
        "text_scale": 150,
        field: "not a number",
    }
    for name, name_low, _ in BOUNDED:
        if name != field:
            document[name] = name_low
    path = write(tmp_path / "settings.json", document)

    result = settings.load(path)

    assert result.settings.theme == "graphite", "a bad number lost the theme"
    assert result.settings.text_scale == 150, "a bad number lost the text scale"
    for name, name_low, _ in BOUNDED:
        if name != field:
            assert getattr(result.settings, name) == name_low, (
                f"a bad {field} lost {name}"
            )
    assert len(result.reasons) == 1, result.reasons


# --- LWSM-1033: `maximized`, the file's one boolean ---------------------------


@pytest.mark.parametrize("stored", [1, 0, "true", "yes", 1.0, None, [], {}], ids=str)
def test_a_maximised_flag_that_is_not_a_boolean_is_refused(
    tmp_path: Path, stored: object
) -> None:
    """`1` is the case that matters, and it is the mirror of the bool-as-int
    check the numbers make.

    A hand-editor writing `1` for "yes" is entirely plausible — this file is
    meant to be edited — and accepting it would mean `0` and `1` round-tripping
    back out as `false` and `true`. A settings file that changes under a user
    who edited it is the objection `_bounded_int_or_reason` already makes about
    rounding a float, applied to the other type.

    `None` is in the list and is the one value that is NOT a complaint: an
    absent key is a first run, not a refusal, which is why the assertion below
    is about the value rather than about the reason.
    """
    path = write(
        tmp_path / "settings.json",
        {"schema_version": settings.SCHEMA_VERSION, "maximized": stored},
    )

    result = settings.load(path)

    assert result.settings.maximized is False
    if stored is not None:
        assert any("maximized" in reason for reason in result.reasons), (
            f"maximized={stored!r} was defaulted with no reason saying why"
        )
    else:
        assert result.reasons == []


@pytest.mark.parametrize("stored", [True, False], ids=str)
def test_a_real_boolean_survives_the_round_trip(tmp_path: Path, stored: bool) -> None:
    """Both values, because a check that only ever sees `True` cannot tell a
    working flag from one hardcoded to the value it was given."""
    path = tmp_path / "settings.json"

    settings.save(path, replace(Settings(), maximized=stored))
    result = settings.load(path)

    assert result.settings.maximized is stored
    assert result.reasons == []
