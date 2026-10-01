"""The scan-roots file: which directories a Rescan walks.

Core module — no Qt at all, like `configfile.py` (`docs/standards/coding.md
§ O1`). Moved out of `__main__.py` (LWSM-1359), which owned this file's format
while its module-map entry named none of it, and whose reader and writer each
spelled out which lines are directories. That rule is `_is_root_line` now.

One directory per line; blank lines and lines whose first non-space character
is `#` are comments. The file sits beside `projects.json`.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from lwsm.configfile import ConfigFileError, read_bounded, write_json_atomically
from lwsm.registry import RegistryError, default_projects_path


def _is_root_line(line: str) -> bool:
    """A line naming a directory, as opposed to a blank or a comment.

    The one statement of the rule. The reader and the writer each carried a
    copy, and the writer's copy decides which lines are the header it keeps,
    so a change to one alone would move header lines into the root list.
    """
    return bool(line.strip()) and not line.lstrip().startswith("#")


SCAN_ROOTS_FILENAME = "scan-roots"
"""The file that lists the directories to scan, beside `projects.json`."""


SCAN_ROOTS_HEADER = (
    "# Directories to scan for projects, one per line.\n"
    "# Blank lines and lines starting with # are ignored.\n"
)
"""What a file this app wrote says about itself, when the user wrote nothing."""


def scan_roots_path(config: Path | None = None) -> Path:
    """The one expression for where the scan-roots file lives.

    Extracted so the reader below and `save_scan_roots` cannot end up pointing
    at different files — the rule `settings.default_settings_path` follows for
    the same reason, and the failure it prevents is a dialog that appears to
    save and a scan that keeps using the old list.

    Raises whatever `default_projects_path` raises; both callers handle it,
    differently, which is why it is not caught here.
    """
    if config is not None:
        return config
    return default_projects_path().parent / SCAN_ROOTS_FILENAME


def save_scan_roots(roots: Sequence[Path], config: Path | None = None) -> None:
    """Write the scan-roots file, keeping what the user wrote at the top.

    **Only the LEADING comment block survives** — every comment and blank line
    before the first directory. Comments interleaved between directories are
    not kept, and that is a stated loss rather than an oversight: keeping one
    would mean deciding which surviving directory it belonged to, and a comment
    silently re-attached to the wrong line is worse than one that is gone.
    LWSM-1144 put comments in this file so it "can explain itself", and a
    header is what that means in practice.

    Atomic, through the same writer `projects.json` and `settings.json` use, so
    a third config file cannot grow a third and subtly different write path.
    (`write_json_atomically` takes bytes; only its name is about JSON.)

    Raises `ConfigFileError` — or whatever `scan_roots_path` raises — when there
    is nowhere to write, for `save_field`'s reason: a change that silently will
    not be remembered is worse than one that says so. It raises for a second
    reason since LWSM-1178: an EXISTING file that cannot be read is refused
    rather than overwritten, and `_leading_comment_block` carries that gate
    because it is the one place this path is read before the write. And for a
    third since LWSM-1179: a root this line-based format cannot represent is
    refused rather than silently altered.
    """
    for root in roots:
        # Refused before anything is read or written, so the previous list
        # survives (LWSM-1179). One path per line, and the reader strips each
        # line: a name ending in whitespace comes back pointing somewhere else,
        # and one holding a newline comes back as TWO roots, the second of them
        # relative. Refused here rather than stripped at the chooser — the
        # chooser is not the only way a root reaches this function, and a strip
        # would change the directory the user picked without saying so.
        text = str(root)
        if text != text.strip() or "\n" in text:
            raise ConfigFileError(
                f"{root!r}: a scan root cannot start or end with whitespace, "
                "or contain a line break"
            )

    path = scan_roots_path(config)
    body = "".join(f"{root}\n" for root in roots)
    data = (_leading_comment_block(path) + body).encode("utf-8")
    write_json_atomically(path, data, prefix=".scan-roots-")


def _leading_comment_block(path: Path) -> str:
    """The file's own header, or ours when there is no file to lose.

    A file that is PRESENT and cannot be read RAISES rather than falling back
    (LWSM-1178), which is what makes `save_scan_roots` refuse. The caller is
    about to overwrite this path, and the roots it was handed came from
    `default_scan_roots`, which fell back on the same input — so a fallback
    header here writes the default list over the user's, header and all.
    Measured before the fix: a two-line header and six roots became ours and
    `~/projects`. It is LWSM-1163's answer on the third config file.

    Only `FileNotFoundError` is absence, and absence stays writable: a first
    run has nothing to lose and must be able to save (LWSM-1163's split).
    A `UnicodeDecodeError` is converted because it is not an `OSError`, and
    `build_window`'s handler catches that — unconverted it would escape as a
    bare traceback rather than a message the user can act on.

    Read through `read_bounded` rather than `Path.read_text`: this runs against
    a path the user controls, and that helper is where the FIFO-blocks-forever
    and the read-600 MB-into-memory cases are already closed.

    `utf-8-sig` for `registry.load_projects`' reason, and this is the second
    consumer LWSM-1182 found decoding plain `utf-8`. A BOM does not fail to
    decode here — `U+FEFF` is a perfectly good character — it survives into
    the first line, where `lstrip()` does not remove it because it is not
    whitespace. So `﻿# my header` is not a comment, the loop breaks
    immediately, and the user's entire header is replaced by ours on the next
    save. Measured, not reasoned.
    """
    try:
        text = read_bounded(path).decode("utf-8-sig")
    except FileNotFoundError:
        return SCAN_ROOTS_HEADER
    except UnicodeDecodeError as exc:
        raise ConfigFileError(f"{path}: is not valid UTF-8 ({exc.reason})") from exc

    kept: list[str] = []
    for line in text.splitlines():
        if _is_root_line(line):
            break
        kept.append(line)
    return "".join(f"{line}\n" for line in kept) or SCAN_ROOTS_HEADER


def scan_root_fallback() -> tuple[Path, ...]:
    """Where a scan looks when the file names nowhere.

    One expression, because two callers depend on agreeing: the reader below
    resolves an empty file to this, and the settings dialog has to apply the
    same answer in memory. They did not agree — clearing every root scanned
    nothing for the rest of the session and silently went back to this on the
    next launch, re-adding the projects the user cleared the list to exclude
    (LWSM-1213).

    The file format has no way to say "scan nothing", so "empty means the
    default" is what it means; making the running session agree is the honest
    half of that. Expressing "nowhere" would be a format change and a
    different item.
    """
    try:
        return (Path.home() / "projects",)
    except RuntimeError:
        # No home directory. INV-15's machine: the app still opens.
        return ()


def default_scan_roots(config: Path | None = None) -> tuple[Path, ...]:
    """The directories to scan, read from a config file, else `~/projects`.

    A function rather than a module constant so it is not evaluated at import
    time, which is the shape `default_projects_path` already takes and the
    reason `build_window` resolves paths inside its own handler. A home
    directory that cannot be resolved yields no roots rather than raising: a
    machine with nowhere to scan should still open a window.

    **Why a file and not just `~/projects` (LWSM-1144).** The hardcoded default
    is right for nobody but its author: a machine that keeps its projects
    anywhere else scans a directory that does not exist, finds nothing, and
    shows an empty window with no indication that the *location* is the
    problem. That is not a missing feature — every part of the app behind it
    works — so the cheapest thing that makes it usable is a way to say where to
    look. **This file is still the setting now that the dialog exists**
    (LWSM-1018): the dialog edits it through `save_scan_roots` rather than
    copying the roots into `settings.json`, so there is one owner and no
    migration. Settled with the user 2026-08-21.

    Format is one directory per line. Blank lines and lines whose first
    non-space character is `#` are ignored, so the file can explain itself.
    `~` is expanded. Order is kept, because it is the order the scan walks.

    A file that cannot be read is treated as absent rather than fatal: this
    runs before the window exists, and a config the user cannot fix without a
    window is a worse failure than scanning the default.

    Read through `read_bounded` for `_leading_comment_block`'s reason, which
    reads this same path twelve lines above: a FIFO here blocked forever with
    no window, no error and no log line, and the `except` below never fired
    because nothing was raised (LWSM-1173, measured). The size cap is
    load-bearing too and not just memory — every line becomes a directory the
    scan then walks. `utf-8-sig` because two readers of one file must agree on
    the decode; under plain `utf-8` a BOM left the user's own header a scan
    root (LWSM-1182's class, on the reader that sweep did not reach).
    """
    fallback = scan_root_fallback()

    if config is None:
        try:
            config = scan_roots_path()
        except (OSError, RuntimeError, RegistryError):
            # `RegistryError` is the one that actually fires, and it is not an
            # OSError: `default_projects_path` has wrapped "there is no home
            # directory" since LWSM-1026, and a machine with no home must still
            # open a window (INV-15) rather than dying here, before there is
            # anything to report the failure in.
            return fallback

    try:
        text = read_bounded(config).decode("utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return fallback

    roots = tuple(
        Path(line.strip()).expanduser()
        for line in text.splitlines()
        if _is_root_line(line)
    )
    # An empty or comments-only file means "nothing was configured", not "scan
    # nowhere" — the second is indistinguishable from the first to whoever
    # wrote it, and silently scanning nothing is the failure this exists to fix.
    return roots or fallback
