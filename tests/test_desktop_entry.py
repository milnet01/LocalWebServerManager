"""LWSM-1209 — the desktop entry the installer actually writes.

`scripts/install-desktop-entry.sh` rewrites `Exec=` and `TryExec=` with the
resolved path to the executable. Both keys are built from a path the user
chose, so both are attacker-adjacent in the ordinary sense: nobody is attacking
anybody, but a directory name is not a shell-safe token and a checkout under
`~/My Projects` is completely normal.

Driven by RUNNING the script, never by reading it. The failure being pinned is
what lands in the file, and `desktop-file-validate` passes the broken form —
so a test that asserted the script's text would have agreed with the defect.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "install-desktop-entry.sh"
APP_ID = "io.github.milnet01.LocalWebServerManager"


def install(tmp_path: Path, exec_name: str) -> str:
    """Run the installer for an executable at `exec_name`, return the entry."""
    target = tmp_path / exec_name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    target.chmod(0o755)

    data_home = tmp_path / "data"
    subprocess.run(
        [str(SCRIPT), str(target)],
        cwd=REPO,
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
            "XDG_DATA_HOME": str(data_home),
        },
        check=True,
        capture_output=True,
    )
    entry = data_home / "applications" / f"{APP_ID}.desktop"
    return entry.read_text(encoding="utf-8")


def unescape_exec(value: str) -> str:
    """Decode a quoted Exec argument back to the path it names.

    The spec applies two layers and so does this, in reverse: the string-value
    rule first (`\\\\` is one backslash), then the quoting rule (a backslash
    escapes the next reserved character). A literal backslash is therefore
    FOUR in the file, which is what the spec says and what
    `desktop-file-validate` enforces.

    Written out rather than approximated by stripping backslashes: that
    shortcut cannot tell a path containing a backslash from one that does not,
    which is exactly the case it would be asked about.
    """
    if value.startswith('"') and value.endswith('"'):
        value = value[1:-1]
    out: list[str] = []
    index = 0
    for _layer in range(2):
        out, index = [], 0
        while index < len(value):
            char = value[index]
            if char == "\\" and index + 1 < len(value):
                out.append(value[index + 1])
                index += 2
            else:
                out.append(char)
                index += 1
        value = "".join(out)
    return value


def field(entry: str, key: str) -> str:
    for line in entry.splitlines():
        if line.startswith(f"{key}="):
            return line[len(key) + 1 :]
    raise AssertionError(f"no {key}= line in the entry")


@pytest.mark.integration
@pytest.mark.parametrize(
    "exec_name",
    [
        "plain/lwsm",
        "My Projects/lwsm",
        "a&b/lwsm",
        "pipe|x/lwsm",
        'quote"d/lwsm',
        "back\\slash/lwsm",
        "dollar$x/lwsm",
    ],
)
def test_the_entry_names_the_executable_that_was_installed(
    tmp_path: Path, exec_name: str
) -> None:
    """Whatever the directory is called, both keys must name the real file.

    Two separate defects produced the same symptom — an entry that appears in
    the launcher and will not start, which is the exact failure the script's
    own header says it prevents (LWSM-1209).

    `Exec=` went in unquoted, so `~/My Projects/...` became two argv words. And
    the path was interpolated into a sed REPLACEMENT, where `&` expands to the
    whole match and `|` closes the s-command: measured, `a&b` produced
    `Exec=/tmp/.../aExec=lwsmb/lwsm` and `pipe|x` made sed exit non-zero.
    """
    entry = install(tmp_path, exec_name)
    expected = str(tmp_path / exec_name)

    # TryExec is a PATH, not a command line, so the spec wants it unquoted and
    # unescaped — it is compared against the filesystem, not parsed.
    assert field(entry, "TryExec") == expected

    assert unescape_exec(field(entry, "Exec")) == expected, (
        f"Exec decodes to something other than the installed path: "
        f"{field(entry, 'Exec')!r}"
    )


@pytest.mark.integration
def test_a_path_with_a_space_is_one_argument_to_the_launcher(tmp_path: Path) -> None:
    """The Desktop Entry Spec's quoting rule, and the reason it exists.

    An unquoted `Exec` is split on whitespace, so a checkout under
    `~/My Projects` yields a launcher that tries to run `/home/u/My` with
    `Projects/...` as its argument. `desktop-file-validate` PASSES that file,
    which is why this asserts the quoting rather than trusting the validator.
    """
    entry = install(tmp_path, "My Projects/lwsm")

    exec_field = field(entry, "Exec")
    assert exec_field.startswith('"') and exec_field.endswith('"'), (
        f"Exec is not quoted, so the launcher splits it: {exec_field!r}"
    )


@pytest.mark.integration
@pytest.mark.skipif(
    shutil.which("desktop-file-validate") is None,
    reason="desktop-file-validate is not installed",
)
def test_the_written_entry_still_validates(tmp_path: Path) -> None:
    """The quoting must not buy correctness at the cost of a valid file."""
    install(tmp_path, "My Projects/lwsm")
