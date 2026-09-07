"""`scripts/local-release.sh` — the only gate a release gets.

CI here fires on `push` and `pull_request` only, so nothing on GitHub ever
checks a release. This file had no tests at all until LWSM-1265, which is why
the defect it locks — a failed query reported as a clean answer — could sit in
the one script whose whole purpose is to refuse a release that is not ready.

The functions are executed rather than read, for `test_ci_contract`'s reason:
what is under test is which verdict a given state produces, and reading the
text can only say which verdicts exist.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
RELEASE = REPO / "scripts/local-release.sh"


def _run(*argv: str, cwd: Path) -> str:
    return subprocess.run(
        argv, cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


def _gh_stub(behaviour: str) -> str:
    """A `gh` that answers as a real one would in the named state.

    `release view` exits non-zero for an absent release AND for a gh that
    cannot reach anything, which is the ambiguity the code has to resolve — so
    a stub is the only way to drive both sides of it.
    """
    return (
        "#!/usr/bin/env bash\n"
        f'case "$*:{behaviour}" in\n'
        "  'release view '*':published') exit 0 ;;\n"
        "  'release view '*':clean') exit 1 ;;\n"
        "  'release list '*':clean') exit 0 ;;\n"
        "  *) exit 1 ;;\n"
        "esac\n"
    )


def _tag_status(repo: Path, tag: str, gh: str, tmp_path: Path) -> list[str]:
    """Run the script's OWN `tag_status()` and return the verdicts it emitted.

    `block`, `skip` and `ok` are stubbed to print, so the test reads the
    decision rather than the formatting.
    """
    body = re.search(r"^tag_status\(\) \{.*?^\}$", RELEASE.read_text(), re.S | re.M)
    assert body, "the release script has no tag_status() to run"

    # PATH is narrowed to this directory so the function finds the `gh` this
    # test chose. `bash` has to be in it as well as `git`: the stub's shebang is
    # `env bash`, which searches PATH, and a stub that cannot start exits 127 —
    # which the function reads as "no such release", passing the test for a
    # reason unrelated to what it claims to measure.
    binaries = tmp_path / f"bin-{gh}"
    binaries.mkdir(exist_ok=True)
    for tool in ("git", "bash"):
        found = shutil.which(tool)
        assert found, f"{tool} is not on PATH"
        (binaries / tool).symlink_to(found)
    if gh != "absent":
        stub = binaries / "gh"
        stub.write_text(_gh_stub(gh))
        stub.chmod(0o755)

    script = (
        "set -Eeuo pipefail\n"
        'block() { printf "BLOCK %s\\n" "$1"; }\n'
        'skip()  { printf "SKIP %s\\n" "$1"; }\n'
        'ok()    { printf "OK %s\\n" "$1"; }\n'
        f"{body.group(0)}\n"
        'tag_status "$1"'
    )
    # bash by absolute path: PATH below holds only the shims, and the point of
    # that is to control which `gh` the function finds, not which shell runs it.
    bash = shutil.which("bash")
    assert bash, "bash is not on PATH"
    done = subprocess.run(
        [bash, "-c", script, "_", tag],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PATH": str(binaries)},
    )
    assert done.returncode == 0, f"tag_status() failed: {done.stderr}"
    return done.stdout.splitlines()


def _repo_with_remote(tmp_path: Path, *, reachable: bool) -> Path:
    _run("git", "init", "-q", "--bare", "origin.git", cwd=tmp_path)
    work = tmp_path / "work"
    _run("git", "init", "-q", "work", cwd=tmp_path)
    _run(
        "git",
        "-c",
        "user.email=t@t",
        "-c",
        "user.name=t",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "first",
        cwd=work,
    )
    target = "origin.git" if reachable else "no-such-remote.git"
    _run("git", "remote", "add", "origin", str(tmp_path / target), cwd=work)
    return work


pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None, reason="bash is not installed"
)


def test_an_unreachable_remote_is_a_skip_and_never_an_all_clear(tmp_path) -> None:
    """A query that failed has not answered (LWSM-1265).

    `git ls-remote` against a remote it cannot reach prints nothing and exits
    non-zero — indistinguishable from "no such tag" if only the output is read.
    The verdict may then say the version is free, which is the one thing this
    script's own rule forbids: a check that did not run must not print like one
    that came back clean.
    """
    repo = _repo_with_remote(tmp_path, reachable=False)

    verdicts = _tag_status(repo, "v9.9.9", "clean", tmp_path)

    assert any(v.startswith("SKIP") for v in verdicts), verdicts
    assert not any(v.startswith("OK") for v in verdicts), verdicts


def test_a_gh_that_cannot_reach_the_repository_is_a_skip(tmp_path) -> None:
    """`release view` fails for an absent release and a broken gh alike."""
    repo = _repo_with_remote(tmp_path, reachable=True)

    verdicts = _tag_status(repo, "v9.9.9", "broken", tmp_path)

    assert any("release existence" in v and v.startswith("SKIP") for v in verdicts), (
        verdicts
    )
    assert not any(v.startswith("OK") for v in verdicts), verdicts


def test_every_question_answered_and_nothing_found_reads_as_free(tmp_path) -> None:
    """The other half, deliberately here: the all-clear must still be reachable.

    Without this, a `tag_status` that skipped unconditionally would satisfy
    both tests above.
    """
    repo = _repo_with_remote(tmp_path, reachable=True)

    verdicts = _tag_status(repo, "v9.9.9", "clean", tmp_path)

    assert verdicts == [
        "OK v9.9.9 is free — no local tag, no remote tag, no release"
    ], verdicts


def test_a_tag_that_exists_blocks(tmp_path) -> None:
    """The check's actual job, so a refusal to answer cannot stand in for it."""
    repo = _repo_with_remote(tmp_path, reachable=True)
    _run("git", "tag", "v9.9.9", cwd=repo)

    verdicts = _tag_status(repo, "v9.9.9", "clean", tmp_path)

    assert any(v.startswith("BLOCK") for v in verdicts), verdicts
    assert not any(v.startswith("OK") for v in verdicts), verdicts
