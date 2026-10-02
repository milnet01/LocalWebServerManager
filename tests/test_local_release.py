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


# --- LWSM-1264: the dry bump has to unwind from anywhere ----------------------


def _bump_repo(tmp_path: Path, *, second_writable: bool) -> Path:
    """Two version-bearing files and a recipe naming both, in that order."""
    work = tmp_path / "bump"
    work.mkdir()
    _run("git", "init", "-q", ".", cwd=work)
    (work / "first.txt").write_text('version = "0.1.0"\n')
    (work / "second.txt").write_text('version = "0.1.0"\n')
    (work / "recipe.json").write_text(
        '{"version_source": "first.txt", "version_pattern": "x", "files": ['
        '{"path": "first.txt", "pattern": "version = \\"{OLD}\\"",'
        ' "replace": "version = \\"{NEW}\\""},'
        '{"path": "second.txt", "pattern": "version = \\"{OLD}\\"",'
        ' "replace": "version = \\"{NEW}\\""}]}'
    )
    _run("git", "add", "-A", cwd=work)
    _run(
        "git",
        "-c",
        "user.email=t@t",
        "-c",
        "user.name=t",
        "commit",
        "-q",
        "-m",
        "first",
        cwd=work,
    )
    if not second_writable:
        (work / "second.txt").chmod(0o444)
    return work


def _dry_bump(repo: Path) -> subprocess.CompletedProcess[str]:
    body = re.search(r"^dry_bump\(\) \{.*?^\}$", RELEASE.read_text(), re.S | re.M)
    assert body, "the release script has no dry_bump() to run"

    bash = shutil.which("bash")
    assert bash, "bash is not on PATH"
    script = (
        "set -Eeuo pipefail\n"
        'fail() { printf "FAILED %s\\n" "$1" >&2; exit 1; }\n'
        "trap 'fail \"dry bump\"' ERR\n"
        'block() { printf "BLOCK %s\\n" "$1"; }\n'
        'skip()  { printf "SKIP %s\\n" "$1"; }\n'
        'ok()    { printf "OK %s\\n" "$1"; }\n'
        f"{body.group(0)}\n"
        "dry_bump 0.1.0 0.2.0 recipe.json"
    )
    return subprocess.run(
        [bash, "-c", script], cwd=repo, capture_output=True, text=True, check=False
    )


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores the read-only bit")
def test_a_write_that_fails_part_way_still_puts_the_tree_back(tmp_path) -> None:
    """The write loop runs under the ERR trap (LWSM-1264).

    A failure on the second of two files leaves through `fail`, so a revert
    placed after the loop never runs and the first file stays bumped — a
    half-applied version, which is the one state a dry run must never leave
    behind. Armed on EXIT before the first write, it unwinds from anywhere.
    """
    repo = _bump_repo(tmp_path, second_writable=False)

    done = _dry_bump(repo)

    assert done.returncode != 0, "an unwritable file was not reported at all"
    assert (repo / "first.txt").read_text() == 'version = "0.1.0"\n', (
        "the tree was left half-bumped"
    )


def test_a_successful_dry_bump_reverts_and_says_so(tmp_path) -> None:
    """The other half: the normal path must still revert and report.

    Without this, a `dry_bump` that failed before writing anything would
    satisfy the test above.
    """
    repo = _bump_repo(tmp_path, second_writable=True)

    done = _dry_bump(repo)

    assert done.returncode == 0, done.stderr
    assert "bumped first.txt" in done.stdout, done.stdout
    assert "OK reverted 2 file(s) to 0.1.0" in done.stdout, done.stdout
    for name in ("first.txt", "second.txt"):
        assert (repo / name).read_text() == 'version = "0.1.0"\n', name


# --- LWSM-1268: the trigger list and the sentence about it -------------------


WORKFLOW_PUSH_ONLY = """\
name: CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
jobs:
  gate:
    runs-on: ubuntu-latest
"""

WORKFLOW_WITH_TAGS = """\
name: CI
on:
  push:
    branches: [main]
    tags: ['v*']
jobs:
  gate:
    runs-on: ubuntu-latest
"""

WORKFLOW_JOB_NAMED_RELEASE = """\
name: CI
on:
  push:
    branches: [main]
jobs:
  release:
    runs-on: ubuntu-latest
"""


def _release_triggers(tmp_path: Path, workflow: str) -> str:
    body = re.search(
        r"^release_triggers\(\) \{.*?^\}$", RELEASE.read_text(), re.S | re.M
    )
    assert body, "the release script has no release_triggers() to run"

    workflows = tmp_path / "workflows"
    workflows.mkdir(exist_ok=True)
    (workflows / "ci.yml").write_text(workflow)

    bash = shutil.which("bash")
    assert bash, "bash is not on PATH"
    done = subprocess.run(
        [
            bash,
            "-c",
            f'set -Eeuo pipefail\n{body.group(0)}\nrelease_triggers "$1"',
            "_",
            str(workflows),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


def test_a_job_named_release_is_not_a_release_trigger(tmp_path) -> None:
    """`^\\s+release:` matches a JOB called release (LWSM-1268).

    A job may legitimately be named that, and reading it as a trigger tells the
    author a release will cost a CI run it will not cost. Only the `on:` block
    answers the question being asked.
    """
    assert "release" not in _release_triggers(tmp_path, WORKFLOW_JOB_NAMED_RELEASE)


def test_a_tag_trigger_is_reported_once_it_exists(tmp_path) -> None:
    """The count and the sentence were unrelated: adding a `tags:` trigger
    moved the number and left the words saying there was no tag trigger."""
    assert "tag push" in _release_triggers(tmp_path, WORKFLOW_WITH_TAGS)


def test_a_push_only_workflow_declares_no_tag_or_release_trigger(tmp_path) -> None:
    """This project's own shape, so the reassuring sentence is still earned."""
    triggers = _release_triggers(tmp_path, WORKFLOW_PUSH_ONLY)

    assert "branch push" in triggers
    assert "tag push" not in triggers
    assert "release published" not in triggers


def test_a_one_line_on_is_read(tmp_path) -> None:
    """`on: [push, release]` was skipped outright by the block reader, so the
    script said "no tag trigger" about a workflow that has both (2026-10-01
    review, L7-L3).

    Dies on dropping the one-line branch of the `on:` reader.
    """
    triggers = _release_triggers(
        tmp_path, "name: CI\non: [push, release]\njobs:\n  a:\n    runs-on: x\n"
    )
    assert "tag push" in triggers
    assert "release published" in triggers


def test_a_push_with_no_filter_fires_on_tags(tmp_path) -> None:
    """A bare `push:` runs for every branch and every tag, and a `branches:`
    under `pull_request:` filters nothing on push (L7-L3).

    Dies on reading filters from the whole `on:` block instead of `push:`'s.
    """
    workflow = """\
name: CI
on:
  push:
  pull_request:
    branches: [main]
jobs:
  gate:
    runs-on: ubuntu-latest
"""
    assert "tag push" in _release_triggers(tmp_path, workflow)


def _cited_ids(tmp_path: Path, changelog: str, *, env: dict | None = None) -> list[str]:
    body = re.search(r"^cited_ids\(\) \{.*?^\}$", RELEASE.read_text(), re.S | re.M)
    assert body, "the release script has no cited_ids() to run"
    (tmp_path / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    (tmp_path / "ROADMAP.md").write_text(
        "- ✅ [LWSM-1234] **Shipped.**\n", encoding="utf-8"
    )
    bash = shutil.which("bash")
    assert bash, "bash is not on PATH"
    done = subprocess.run(
        [bash, "-c", f"set -Eeuo pipefail\n{body.group(0)}\ncited_ids 0.1.0"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout.split()


def test_only_this_roadmap_s_ids_count_as_shipping_claims(tmp_path) -> None:
    """Any ID-shaped token counted, so an advisory id or `UTF-8` on a bullet
    each became a "cited as shipped but in no roadmap" BLOCKER (L7-M5).
    Continuation prose stays a cross-reference.

    Dies on matching ID-shaped tokens without the roadmap's prefixes.
    """
    changelog = (
        "## [0.1.0] — 2026-10-01\n\n"
        "- **Fixed a thing** (LWSM-1234), see GHSA-4gg8-xxxx and UTF-8.\n"
        "  Also relates to LWSM-9999.\n"
    )
    assert _cited_ids(tmp_path, changelog) == ["LWSM-1234"]


def test_the_em_dash_heading_is_found_under_the_c_locale(tmp_path) -> None:
    """`[—-]` matched the three-byte em dash as one character only under a
    UTF-8 locale; under `LC_ALL=C` the dated section was not found (L7-L2).

    Dies on going back to a bracket expression.
    """
    import os

    changelog = "## [0.1.0] — 2026-10-01\n\n- **Fixed** (LWSM-1234)\n"
    env = {**os.environ, "LC_ALL": "C"}
    assert _cited_ids(tmp_path, changelog, env=env) == ["LWSM-1234"]


# --- LWSM-1284: what the argument loop admits ---------------------------------


@pytest.mark.parametrize(
    "arg",
    ["1.2.3'+__import__('os').getcwd()+'", "1.2.3|.*", "1x.2.3", "1.2.3-beta"],
)
def test_a_version_that_is_not_one_is_refused_before_anything_runs(arg) -> None:
    """The old `[0-9]*.[0-9]*.[0-9]*` glob admitted each of these, and the
    first then reached Python source through string interpolation. The loop
    refuses before any check runs, so this touches nothing."""
    result = subprocess.run(
        ["bash", str(RELEASE), arg], cwd=REPO, capture_output=True, text=True
    )
    assert result.returncode == 2, result.stderr
    assert "unknown argument" in result.stderr


@pytest.mark.parametrize("arg", ["0.2.0-rc.1", "1.0.0-rc.12"])
def test_a_release_candidate_is_refused_with_its_reason(arg) -> None:
    """LWSM-1355, decided by the user 2026-10-01: refuse `-rc.N` until a
    pre-release is wanted. The loop used to admit it, and the version recipe
    and `check-version-drift.sh` read `X.Y.Z` only, so the post-check then
    reported "no version found" and a pre-release could never pass."""
    result = subprocess.run(
        ["bash", str(RELEASE), arg], cwd=REPO, capture_output=True, text=True
    )
    assert result.returncode == 2, result.stderr
    assert "release candidates are not supported" in result.stderr
    assert "unknown argument" not in result.stderr


def test_a_missing_python_is_named_rather_than_blamed_on_the_recipe(tmp_path) -> None:
    """Every check reads the recipe through python3, so its absence surfaced as
    "recipe is not in the dialect cut-release reads"."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("bash", "dirname", "git"):
        (bin_dir / tool).symlink_to(shutil.which(tool))
    result = subprocess.run(
        [str(bin_dir / "bash"), str(RELEASE)],
        cwd=REPO,
        capture_output=True,
        text=True,
        env={"PATH": str(bin_dir)},
    )
    assert result.returncode == 2, result.stderr
    assert "python3 is not on PATH" in result.stderr
