"""The user's own choices, read from a hand-editable JSON file.

Core module — may import QtCore, never QtWidgets (`docs/standards/coding.md
§ O1`). No Qt at all, like `ports.py` and `scanner.py`.

**LWSM-1031 opens this file; LWSM-1018 grows it.** That item owns the settings
dialog and names scan roots, poll interval, slow-start threshold, log-buffer
size and tray behaviour as its fields. This one adds the single field the theme
layer needs and the `schema_version` LWSM-1018's contract already promises, so
what lands later is a field per row rather than a file format.

**A bad settings file must never cost the user a window.** That is the one rule
that separates this module from `registry.py`: a project list nobody can parse
is a refusal the user has to see, because the alternative is inventing projects
(ADR-0005). A *preference* nobody can parse has an obvious right answer — the
default — so `load()` returns a `Settings` on every path and never raises. Every
refusal is still reported, in `reasons`, because silence and a clean file must
not read the same (`controller._flush_repeated_error`'s rule).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from pathlib import Path

from lwsm.configfile import (
    MAX_REASON_CHARS,
    ConfigFileError,
    quoted,
    read_bounded,
    write_json_atomically,
)
from lwsm.registry import default_projects_path

SCHEMA_VERSION = 1

# The theme id is stored as an opaque string and is NOT checked against the
# theme registry here. `theme.py` holds the palettes and imports QtGui, so a
# core module may not import it (`coding.md § O1`, enforced by
# `tests/test_layering.py`) — but the split is worth having on its own terms:
# this module owns whether the file's SHAPE is usable, and `theme.theme_for_id`
# owns whether an id names something that exists. An id for a theme a later
# build removes is then a theme problem, resolved where the themes are.
DEFAULT_THEME = "midnight"

# A theme id is a short identifier. The bound is on the stored string because
# the file is hand-editable: without it a 50 MB `"theme"` value is read, held
# and written back, which is the class `registry.MAX_REASON_CHARS` closes for
# reasons and nothing closed for values.
MAX_THEME_ID_CHARS = 64

# And an identifier is not free text. Every id `theme.py` ships matches this,
# so the charset costs nothing and closes the case a bounded non-empty string
# still lets through: `"theme": "a\nb"` is stored, written back, and reaches a
# `log.warning` and the status bar, where the newline forges what reads as a
# second record. `configfile.quoted` escapes that at the point of USE and this
# refuses it at the point of ENTRY — LWSM-1078's lesson is that only the
# second one bounds what gets persisted.
THEME_ID_CHARSET = re.compile(r"\A[A-Za-z0-9_-]+\Z")

# The in-app text-size control's range (LWSM-1032), as a PERCENTAGE of the
# desktop's own font rather than a point size of our own. `design.md §
# Accessibility` is explicit that the control multiplies the desktop's setting
# and does not replace it, so 100 means "whatever the desktop already said" and
# a machine whose font is already large stays large.
MIN_TEXT_SCALE = 100
MAX_TEXT_SCALE = 200

# The same bound `registry.MAX_REASONS` exists for, at the size this file is.
# A settings file has a fixed, small set of fields, so anything past a handful
# of complaints is a hostile file rather than a typo.
MAX_REASONS = 20


class SettingsError(ConfigFileError):
    """The file could not be *written*. There is no read-side failure."""


@dataclass(frozen=True)
class Settings:
    """What the user chose. Defaults are what a first run gets."""

    theme: str = DEFAULT_THEME
    # A percentage, 100-200. See MIN_TEXT_SCALE on why it is not a point size.
    text_scale: int = MIN_TEXT_SCALE


@dataclass(frozen=True)
class LoadResult:
    """`settings` is always usable; `reasons` says what was ignored to get it.

    The same shape as `registry.LoadResult` minus `rows_refused`, which has no
    analogue here: this file holds fields, not rows, so there is nothing a
    refusal can drop that would make a later write lose data.
    """

    settings: Settings
    reasons: list[str]


def default_settings_path() -> Path:
    """`settings.json` beside `projects.json`, in the same XDG config dir.

    Derived from `registry.default_projects_path()` rather than recomputing the
    XDG rule, so the two files cannot end up in different directories when one
    of them is fixed — and so `$XDG_CONFIG_HOME` unset, or set to a relative
    path, resolves the same way for both (`coding.md § O3`).
    """
    return default_projects_path().with_name("settings.json")


def _theme_or_reason(value: object) -> tuple[str | None, str | None]:
    """A theme id is a bounded identifier. Whose id it is, is not asked.

    `type(v) is not str` follows `registry._is_int`'s convention, but the
    reasoning there does NOT carry over and it is worth saying so: that check
    exists because `isinstance(True, int)` is True, and there is no analogous
    bool-shaped str. Measured — swapping this one for `isinstance` kills no
    test, because JSON cannot produce a str subclass. It is here for
    consistency across the two loaders, not for a defect it closes.

    The charset is the check that does work; `THEME_ID_CHARSET` says why.
    """
    if value is None:
        return None, None
    if type(value) is not str:
        return None, f"theme: {quoted(value)} is not a string; using the default"
    if len(value) > MAX_THEME_ID_CHARS or not THEME_ID_CHARSET.match(value):
        return None, f"theme: {quoted(value)} is not a usable id; using the default"
    return value, None


def _scale_or_reason(value: object) -> tuple[int | None, str | None]:
    """A text scale is a whole percentage inside `MIN`..`MAX` (LWSM-1032).

    `type(value) is not int` rather than `isinstance`, and here the reasoning
    DOES carry over from `registry._is_int` where `_theme_or_reason`'s did not:
    `isinstance(True, int)` is True, `json.loads` produces a real `bool` for
    `true`, and this file is hand-editable — so `"text_scale": true` would
    otherwise be read as 1, fail the range check, and reach the user as a
    complaint about a number nobody wrote.

    A float is refused rather than rounded. JSON has one number type, so
    `150.0` is what a generator emits for an integral value and rounding it
    would be defensible — but a value this module cannot round-trip byte for
    byte is one the next `save()` silently rewrites, and a settings file that
    changes under a user who edited it is worse than one that says no.
    """
    if value is None:
        return None, None
    if type(value) is not int:
        return None, (
            f"text_scale: {quoted(value)} is not a whole percentage; using the default"
        )
    if not MIN_TEXT_SCALE <= value <= MAX_TEXT_SCALE:
        return None, (
            f"text_scale: {quoted(value)} is outside "
            f"{MIN_TEXT_SCALE}-{MAX_TEXT_SCALE}; using the default"
        )
    return value, None


def load(path: Path) -> LoadResult:
    """Read `path`, or return the defaults and say why.

    Never raises. Every `except` here has a measured cause behind it in
    `registry.load_projects`, and the difference is only what happens next:
    there a `RegistryError` reaches the user as an empty window with a reason,
    here the same condition reaches them as the default theme and a log line.
    """
    reasons: list[str] = []
    try:
        raw = read_bounded(path)
    except FileNotFoundError:
        # First run. Not a refusal, so it earns no reason — a clean machine
        # must not report a problem it does not have.
        return LoadResult(Settings(), reasons)
    except OSError as exc:
        return LoadResult(
            Settings(),
            [f"{quoted(str(path))}: cannot be read ({exc.strerror or exc})"],
        )

    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        # `str(exc)` is quoted for the same reason every other reason is: it
        # interpolates a fragment of the hostile file, newlines included.
        return LoadResult(
            Settings(), [f"{quoted(str(path))}: is not valid JSON ({quoted(str(exc))})"]
        )

    if not isinstance(document, dict):
        return LoadResult(
            Settings(),
            [f"{quoted(str(path))}: is {type(document).__name__}, not an object"],
        )

    version = document.get("schema_version")
    if version != SCHEMA_VERSION:
        # ADR-0005 forbids partially parsing a file whose version we do not
        # know, and that reasoning does not weaken for preferences: a v2 file
        # may have re-used a key. Defaults, and say so.
        return LoadResult(
            Settings(),
            [
                f"{quoted(str(path))}: schema_version is {quoted(version)}, "
                f"not {SCHEMA_VERSION}; using defaults"
            ],
        )

    settings = Settings()
    theme, reason = _theme_or_reason(document.get("theme"))
    if reason is not None:
        reasons.append(reason)
    if theme is not None:
        settings = replace(settings, theme=theme)

    # Each field is read on its own and refused on its own: a file with one
    # unusable value keeps every other, the shape `registry` already has where
    # a bad port loses the field and not the row.
    scale, reason = _scale_or_reason(document.get("text_scale"))
    if reason is not None:
        reasons.append(reason)
    if scale is not None:
        settings = replace(settings, text_scale=scale)

    return LoadResult(settings, reasons[:MAX_REASONS])


def save(path: Path, settings: Settings) -> None:
    """Write atomically, or raise `SettingsError` naming why it refused.

    There is no read-only gate of `registry.save_projects`' kind, and the
    asymmetry is deliberate: that gate exists so a session which refused rows
    cannot write a file missing them, and a refusal here drops no data — an
    unreadable field was replaced by its default, and writing the default back
    is what the user asked for by changing a setting.
    """
    payload = {
        "schema_version": SCHEMA_VERSION,
        "theme": settings.theme,
        # Written even at its default. A key that appears only when it
        # differs is one the next reader has to guess about, and this file
        # is meant to be hand-editable.
        "text_scale": settings.text_scale,
    }
    try:
        text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        data = text.encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise SettingsError(
            f"{quoted(str(path))}: cannot be serialised "
            f"({type(exc).__name__}: {quoted(str(exc))})"
        ) from exc

    try:
        write_json_atomically(path, data, prefix=".settings-")
    except ConfigFileError as exc:
        raise SettingsError(str(exc)[:MAX_REASON_CHARS]) from exc
