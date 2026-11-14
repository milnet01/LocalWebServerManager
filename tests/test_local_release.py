"""`scripts/local-release.sh` — the only gate that runs before a release.

The release workflow attaches the AppImage only after a release is published.
This file had
no tests at all until LWSM-1265, which is why the defect it locks — a failed
query reported as a clean answer — could sit in the one script whose whole
purpose is to refuse a release that is not ready.

The functions are executed rather than read, for `test_ci_contract`'s reason:
what is under test is which verdict a given state produces, and reading the
text can only say which verdicts exist.
"""

from __future__ import annotations

import json
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


def _git_failing_on(binaries: Path, subcommand: str) -> None:
    """Put a `git` in `binaries` that fails `subcommand` and runs the rest.

    It prints nothing and exits non-zero, as git does when it cannot read the
    repository — the shape that reads as an empty answer if only the output is
    examined.
    """
    real = shutil.which("git")
    assert real, "git is not on PATH"
    shim = binaries / "git"
    shim.write_text(
        f'#!/bin/sh\n[ "$1" = {subcommand} ] && exit 128\nexec {real} "$@"\n'
    )
    shim.chmod(0o755)


def _tag_status(
    repo: Path, tag: str, gh: str, tmp_path: Path, *, git_fails: str | None = None
) -> list[str]:
    """Run the script's OWN `tag_status()` and return the verdicts it emitted.

    `block`, `skip` and `ok` are stubbed to print, so the test reads the
    decision rather than the formatting. `git_fails` names a git subcommand
    that fails.
    """
    body = re.search(r"^tag_status\(\) \{.*?^\}$", RELEASE.read_text(), re.S | re.M)
    assert body, "the release script has no tag_status() to run"

    # PATH is narrowed to this directory so the function finds the `gh` this
    # test chose. `bash` has to be in it as well as `git`: the stub's shebang is
    # `env bash`, which searches PATH, and a stub that cannot start exits 127 —
    # which the function reads as "no such release", passing the test for a
    # reason unrelated to what it claims to measure.
    binaries = tmp_path / f"bin-{gh}"
    binaries.mkdir(parents=True)
    for tool in ("git", "bash"):
        found = shutil.which(tool)
        assert found, f"{tool} is not on PATH"
        if tool == "git" and git_fails:
            _git_failing_on(binaries, git_fails)
        else:
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


@pytest.mark.parametrize("gh", ["broken", "absent"])
def test_a_repository_with_no_remote_can_still_read_as_free(tmp_path, gh) -> None:
    """LWSM-1490: with no `origin` there is no remote tag AND no release to
    collide with — releases.md § 4 calls that a legitimate state. The function
    said so for the tag but still asked `gh`, which cannot reach a repository
    that has no remote, so the verdict was a SKIP there forever.
    """
    repo = tmp_path / "work"
    _run("git", "init", "-q", "work", cwd=tmp_path)

    verdicts = _tag_status(repo, "v9.9.9", gh, tmp_path)

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


def test_a_failed_local_tag_query_is_a_skip_and_never_an_all_clear(
    tmp_path,
) -> None:
    """`git tag -l` that failed printed nothing, which read as "no local tag"
    (2026-10-08 review, L10-L3) — LWSM-1265's defect on the local half.
    """
    repo = _repo_with_remote(tmp_path, reachable=True)

    verdicts = _tag_status(repo, "v9.9.9", "clean", tmp_path, git_fails="tag")

    assert any(v.startswith("SKIP") for v in verdicts), verdicts
    assert not any(v.startswith("OK") for v in verdicts), verdicts


def _tree_state(repo: Path, tmp_path: Path, *, git_fails: str | None) -> list[str]:
    """Run the script's OWN `tree_state()`; return its verdicts and TREE_CLEAN."""
    body = re.search(r"^tree_state\(\) \{.*?^\}$", RELEASE.read_text(), re.S | re.M)
    assert body, "the release script has no tree_state() to run"

    binaries = tmp_path / "bin-tree"
    binaries.mkdir()
    for tool in ("bash", "sed"):
        found = shutil.which(tool)
        assert found, f"{tool} is not on PATH"
        (binaries / tool).symlink_to(found)
    if git_fails:
        _git_failing_on(binaries, git_fails)
    else:
        found = shutil.which("git")
        assert found, "git is not on PATH"
        (binaries / "git").symlink_to(found)

    script = (
        "set -Eeuo pipefail\n"
        'block() { printf "BLOCK %s\\n" "$1"; }\n'
        'skip()  { printf "SKIP %s\\n" "$1"; }\n'
        'ok()    { printf "OK %s\\n" "$1"; }\n'
        f"{body.group(0)}\n"
        "tree_state\n"
        'printf "TREE_CLEAN=%s\\n" "$TREE_CLEAN"'
    )
    bash = shutil.which("bash")
    assert bash, "bash is not on PATH"
    done = subprocess.run(
        [bash, "-c", script],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PATH": str(binaries)},
    )
    assert done.returncode == 0, f"tree_state() failed: {done.stderr}"
    return done.stdout.splitlines()


def test_a_failed_status_query_never_reads_as_a_clean_tree(tmp_path) -> None:
    """`git status --porcelain` that failed printed nothing, which read as a
    clean tree (2026-10-08 review, L10-L3). TREE_CLEAN=1 is what lets
    `--dry-bump` try the bump on HEAD as the tree you have, so a wrong
    "clean" there tests a tree you would not release.
    """
    repo = _repo_with_remote(tmp_path, reachable=True)

    lines = _tree_state(repo, tmp_path, git_fails="status")

    assert "TREE_CLEAN=0" in lines, lines
    assert not any(v.startswith("OK") for v in lines), lines


def test_a_clean_tree_still_reads_as_clean(tmp_path) -> None:
    """The other half: a tree_state() that never said clean would pass above."""
    repo = _repo_with_remote(tmp_path, reachable=True)

    lines = _tree_state(repo, tmp_path, git_fails=None)

    assert lines == ["OK clean", "TREE_CLEAN=1"], lines


# --- LWSM-1264: the dry bump has to unwind from anywhere ----------------------


def _bump_repo(
    tmp_path: Path, *, missing_third: bool = False, post_check: str = ""
) -> Path:
    """Two version-bearing files and a recipe naming both, in that order.

    `missing_third` adds a recipe path that is not in the repository, so the
    write loop fails on its third file. `post_check` goes into the recipe.
    """
    work = tmp_path / "bump"
    work.mkdir()
    _run("git", "init", "-q", ".", cwd=work)
    (work / "first.txt").write_text('version = "0.1.0"\n')
    (work / "second.txt").write_text('version = "0.1.0"\n')
    entry = (
        '{{"path": "{}", "pattern": "version = \\"{{OLD}}\\"",'
        ' "replace": "version = \\"{{NEW}}\\""}}'
    )
    names = ["first.txt", "second.txt"] + (["missing.txt"] if missing_third else [])
    (work / "recipe.json").write_text(
        '{"version_source": "first.txt", "version_pattern": "x", "files": ['
        + ", ".join(entry.format(n) for n in names)
        + "], "
        + f'"post_check": {json.dumps(post_check)}'
        + "}"
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
    return work


def _worktrees(repo: Path) -> list[str]:
    listing = _run("git", "worktree", "list", "--porcelain", cwd=repo)
    return [line for line in listing.splitlines() if line.startswith("worktree ")]


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


def test_a_write_that_fails_part_way_leaves_nothing_behind(tmp_path) -> None:
    """The write loop runs under the ERR trap (LWSM-1264).

    A failure on the third file leaves through `fail`, so cleanup placed
    after the loop never runs. Armed on EXIT before the first write, it
    unwinds from anywhere: no half-bumped file, and no worktree left over.
    """
    repo = _bump_repo(tmp_path, missing_third=True)

    done = _dry_bump(repo)

    assert done.returncode != 0, "a missing recipe path was not reported at all"
    assert (repo / "first.txt").read_text() == 'version = "0.1.0"\n', (
        "the user's tree was bumped"
    )
    assert len(_worktrees(repo)) == 1, "the dry-bump worktree was left behind"


def test_a_successful_dry_bump_checks_the_bump_and_leaves_the_tree_alone(
    tmp_path,
) -> None:
    """The normal path: post_check sees the bumped files, the user's do not.

    The post_check greps its own working directory for the new version, so
    this fails if the bump and the check ran in different trees.
    """
    repo = _bump_repo(tmp_path, post_check="grep -q 0.2.0 first.txt second.txt")

    done = _dry_bump(repo)

    assert done.returncode == 0, done.stderr
    assert "bumped first.txt" in done.stdout, done.stdout
    assert "OK post_check passed on the bumped tree" in done.stdout, done.stdout
    for name in ("first.txt", "second.txt"):
        assert (repo / name).read_text() == 'version = "0.1.0"\n', name
    assert len(_worktrees(repo)) == 1, "the dry-bump worktree was left behind"


def test_a_save_made_during_the_dry_bump_is_kept(tmp_path) -> None:
    """LWSM-1510: another session's write during the dry bump survives it.

    The dry bump used to write the user's tree and `git checkout --` the
    recipe paths afterwards. ROADMAP.md is one of them, and a roadmap_log
    render landing in that window was discarded. The post_check here stands
    in for that session, writing a recipe path in the user's tree.
    """
    saved = tmp_path / "bump" / "second.txt"
    repo = _bump_repo(tmp_path, post_check=f"echo saved > {saved}")

    done = _dry_bump(repo)

    assert done.returncode == 0, done.stderr
    assert saved.read_text() == "saved\n", "the other session's save was discarded"


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


def test_a_decision_record_link_is_not_a_roadmap_prefix(tmp_path) -> None:
    """LWSM-1535. The roadmap's prose links `[ADR-0003](...)`, so ADR became a
    prefix and a changelog bullet naming ADR-0003 was a "cited as shipped but
    not ✅" BLOCKER. Only an item line issues a prefix.

    Dies on taking prefixes from every bracketed token.
    """
    changelog = (
        "## [0.1.0] — 2026-10-01\n\n"
        "- **Signed updates** (LWSM-1234), as ADR-0003 decided.\n"
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/roadmap").mkdir()
    (tmp_path / "docs/roadmap/old.md").write_text(
        "**Theme:** the buttons. [ADR-0003](docs/decisions/0003.md)\n",
        encoding="utf-8",
    )
    assert _cited_ids(tmp_path, changelog) == ["LWSM-1234"]


def _item_line(tmp_path: Path, roadmap: str) -> str:
    """Run the script's OWN `item_line()` for LWSM-7 over `roadmap`."""
    (tmp_path / "ROADMAP.md").write_text(roadmap, encoding="utf-8")
    bash = shutil.which("bash")
    assert bash, "bash is not on PATH"
    done = subprocess.run(
        [bash, "-c", f"{_function(RELEASE, 'item_line')}\nitem_line LWSM-7"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout


def test_the_item_line_is_found_past_a_prose_mention_of_the_id(tmp_path) -> None:
    """LWSM-1535. `grep -m1 -F "[ID]"` returned the first line naming the id,
    which may be another item's prose: a 📋 item read as ✅ when that prose
    carried the mark, and a ✅ item read as unshipped when it did not.

    Dies on matching any line that merely holds `[LWSM-7]`.
    """
    roadmap = (
        "- ✅ [LWSM-3] **Other.** Needed [LWSM-7] first, which is still\n"
        "  open. See also - ✅ [LWSM-7] in prose.\n"
        "- 📋 [LWSM-7] **The open item.**\n"
    )
    assert "📋" in _item_line(tmp_path, roadmap)
    assert "✅" not in _item_line(tmp_path, roadmap)


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


# --- LWSM-1347: the CI tool pins against their latest releases ---------------


def _pin_status(tmp_path: Path, answer: str | None, pinned: str = "1.2.3") -> list[str]:
    """Run the script's OWN `pin_status()` against a `gh` answering `answer`
    as the latest tag (None: a gh that fails), in a tree pinning `pinned`."""
    body = re.search(r"^pin_status\(\) \{.*?^\}$", RELEASE.read_text(), re.S | re.M)
    assert body, "the release script has no pin_status() to run"
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/ci-tools.env").write_text(f"TOOL_VERSION={pinned}\n")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    for tool in ("bash", "sed"):
        found = shutil.which(tool)
        assert found, f"{tool} is not on PATH"
        (binaries / tool).symlink_to(found)
    stub = binaries / "gh"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        + (f"echo {answer}\n" if answer is not None else "exit 1\n")
    )
    stub.chmod(0o755)
    script = (
        "set -Eeuo pipefail\n"
        'warn() { printf "WARN %s\\n" "$1"; }\n'
        'skip() { printf "SKIP %s\\n" "$1"; }\n'
        'ok()   { printf "OK %s\\n" "$1"; }\n'
        f"{body.group(0)}\n"
        'pin_status "$1" "$2"'
    )
    bash = shutil.which("bash")
    assert bash, "bash is not on PATH"
    done = subprocess.run(
        [bash, "-c", script, "_", "TOOL_VERSION", "owner/tool"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PATH": str(binaries)},
    )
    assert done.returncode == 0, f"pin_status() failed: {done.stderr}"
    return done.stdout.splitlines()


def test_a_pin_at_the_latest_release_is_ok(tmp_path) -> None:
    """A `v` prefix on the tag is not a difference: shellcheck tags `v0.11.0`
    and pins `0.11.0`."""
    (line,) = _pin_status(tmp_path, "v1.2.3")
    assert line.startswith("OK ")


def test_a_pin_behind_its_latest_release_warns(tmp_path) -> None:
    """LWSM-1347: a warning naming both versions, never a blocker."""
    (line,) = _pin_status(tmp_path, "1.2.13")
    assert (
        line
        == "WARN TOOL_VERSION is pinned at 1.2.3; owner/tool's latest release is 1.2.13"
    )


def test_a_failed_lookup_is_a_skip_and_never_up_to_date(tmp_path) -> None:
    """The script's one rule: "not checked" must not read as "clear"."""
    (line,) = _pin_status(tmp_path, None)
    assert line.startswith("SKIP ")


def test_every_pin_in_the_tools_file_is_checked() -> None:
    """A pin added to scripts/ci-tools.env without a TOOL_REPOS row would never
    be checked, silently. SHA256 lines pin an artifact, not a version."""
    pinned = set(
        re.findall(
            r"^(\w+_VERSION)=", (REPO / "scripts/ci-tools.env").read_text(), re.M
        )
    )
    checked = set(re.findall(r'^\s+"(\w+_VERSION) ', RELEASE.read_text(), re.M))
    assert pinned and pinned == checked


# --- LWSM-1052: the AppImage builds and starts before anything is tagged -----


def _appimage_status(
    tmp_path: Path,
    *,
    runner: str | None,
    build_exit: int,
    uv: bool = True,
    info_exit: int = 0,
) -> list[str]:
    """Run the script's OWN `appimage_status()` in a tree whose
    `scripts/build-appimage.sh` exits `build_exit`, with `runner` (podman,
    docker, or None for neither) the only container tool on PATH. `uv` says
    whether a `uv` is on PATH too; `info_exit` is what `<runner> info` exits
    (non-zero is a daemon that is not running)."""
    body = re.search(
        r"^appimage_status\(\) \{.*?^\}$", RELEASE.read_text(), re.S | re.M
    )
    assert body, "the release script has no appimage_status() to run"
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/build-appimage.sh").write_text(f"exit {build_exit}\n")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    bash = shutil.which("bash")
    assert bash, "bash is not on PATH"
    (binaries / "bash").symlink_to(bash)
    if runner:
        stub = binaries / runner
        stub.write_text(f'#!/bin/sh\n[ "$1" = info ] && exit {info_exit}\nexit 0\n')
        stub.chmod(0o755)
    if uv:
        uv_stub = binaries / "uv"
        uv_stub.write_text("#!/bin/sh\nexit 0\n")
        uv_stub.chmod(0o755)
    script = (
        "set -Eeuo pipefail\n"
        'block() { printf "BLOCK %s\\n" "$1"; }\n'
        'skip()  { printf "SKIP %s\\n" "$1"; }\n'
        'ok()    { printf "OK %s\\n" "$1"; }\n'
        f"{body.group(0)}\n"
        "appimage_status"
    )
    done = subprocess.run(
        [bash, "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PATH": str(binaries)},
    )
    assert done.returncode == 0, f"appimage_status() failed: {done.stderr}"
    return done.stdout.splitlines()


@pytest.mark.parametrize("runner", ["podman", "docker"])
def test_an_appimage_that_builds_and_starts_is_ok(tmp_path, runner) -> None:
    (line,) = _appimage_status(tmp_path, runner=runner, build_exit=0)
    assert line.startswith("OK ")


def test_an_appimage_that_fails_blocks_the_release(tmp_path) -> None:
    """The point of LWSM-1052: a broken AppImage stops the release here, not
    in the release workflow after the tag and release are public."""
    (line,) = _appimage_status(tmp_path, runner="podman", build_exit=1)
    assert line.startswith("BLOCK ")


def test_no_container_runner_is_a_skip_and_never_ok(tmp_path) -> None:
    """The script's one rule: "not checked" must not read as "clear". The
    build is not attempted, so its stub's exit code does not matter."""
    (line,) = _appimage_status(tmp_path, runner=None, build_exit=0)
    assert line.startswith("SKIP ")


def test_a_missing_uv_is_a_skip_and_never_a_blocked_appimage(tmp_path) -> None:
    """LWSM-1547. No `uv` means the build could not run, which is not the same
    as a build that failed. The build's stub would exit 1, so a BLOCK here
    means the script tried it anyway."""
    (line,) = _appimage_status(tmp_path, runner="podman", build_exit=1, uv=False)
    assert line.startswith("SKIP ")


@pytest.mark.parametrize("runner", ["podman", "docker"])
def test_a_container_runner_that_cannot_run_is_a_skip(tmp_path, runner) -> None:
    """LWSM-1547. A stopped docker daemon is installed but cannot build; the
    check could not run, so it is a SKIP, not a BLOCK."""
    (line,) = _appimage_status(tmp_path, runner=runner, build_exit=1, info_exit=1)
    assert line.startswith("SKIP ")


# --- LWSM-1545: the AppImage build's lock and file ownership -----------------

BUILD = REPO / "scripts/build-appimage.sh"
IN_CONTAINER = REPO / "scripts/_appimage-build.sh"


def _function(script: Path, name: str) -> str:
    body = re.search(rf"^{name}\(\) \{{.*?^\}}$", script.read_text(), re.S | re.M)
    assert body, f"{script.name} has no {name}() to run"
    return body.group(0)


def _take_lock(lock: Path) -> subprocess.CompletedProcess[str]:
    """Run the script's OWN `take_build_lock()`, giving up after two seconds.

    Exit 124 is `timeout`'s: the function was still waiting.
    """
    bash = shutil.which("bash")
    timeout = shutil.which("timeout")
    assert bash and timeout, "bash and timeout are needed"
    script = f'{_function(BUILD, "take_build_lock")}\ntake_build_lock "$1"'
    return subprocess.run(
        [timeout, "2", bash, "-c", script, "_", str(lock)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_a_second_build_waits_for_the_first(tmp_path) -> None:
    """LWSM-1545. Two builds share dist/.appimage-build, the smoke image tag and
    the output file, so the second must wait and say so.

    Dies on removing the flock, or on taking it non-blocking and carrying on.
    """
    import fcntl

    lock = tmp_path / "build.lock"
    with lock.open("w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        waiting = _take_lock(lock)
    assert waiting.returncode == 124, waiting.stderr
    assert "waiting" in waiting.stderr
    free = _take_lock(lock)
    assert free.returncode == 0, free.stderr
    assert free.stderr == ""


def test_a_build_hands_its_files_back_to_the_user_who_ran_it(tmp_path) -> None:
    """LWSM-1545. Under rootful docker the container's root owns what it
    writes. The function must give /work and the AppImage the owner of the
    bind-mounted /work, which is the host user's under docker and root's (a
    no-op) under rootless podman. A stand-in `chown` records its arguments.

    Dies on dropping the chown, on chowning the wrong paths, or on taking the
    owner from anywhere but the mount.
    """
    work = tmp_path / "work"
    out = tmp_path / "out"
    work.mkdir()
    out.mkdir()
    (out / "x.AppImage").write_text("")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    record = tmp_path / "chown.args"
    (binaries / "chown").write_text(f'#!/bin/sh\necho "$@" >> {record}\n')
    (binaries / "chown").chmod(0o755)
    bash = shutil.which("bash")
    stat = shutil.which("stat")
    assert bash and stat, "bash and stat are needed"
    (binaries / "stat").symlink_to(stat)
    script = (
        f"{_function(IN_CONTAINER, 'hand_back_ownership')}\n"
        'hand_back_ownership "$1" "$2" "$3"'
    )
    subprocess.run(
        [bash, "-c", script, "_", str(work), str(out), "x.AppImage"],
        check=True,
        env={**os.environ, "PATH": f"{binaries}:/usr/bin"},
    )
    uid_gid = f"{os.getuid()}:{os.getgid()}"
    args = record.read_text().split()
    assert args[:2] == ["-R", uid_gid], args
    assert str(work) in args and str(out / "x.AppImage") in args, args


def test_the_container_script_hands_ownership_back_even_when_it_fails() -> None:
    """The function is useless unless it runs on every exit, so it is trapped."""
    text = IN_CONTAINER.read_text()
    assert re.search(r"^trap .*hand_back_ownership.* EXIT$", text, re.M), text


# --- LWSM-1548: the release signing key stops a release it cannot sign -------


def _signing_key_status(tmp_path: Path, *, uv_exit: int | None) -> list[str]:
    """Run the script's OWN `signing_key_status()` with a stub `uv` that exits
    `uv_exit`, or no `uv` at all for None."""
    body = re.search(
        r"^signing_key_status\(\) \{.*?^\}$", RELEASE.read_text(), re.S | re.M
    )
    assert body, "the release script has no signing_key_status() to run"
    binaries = tmp_path / "bin"
    binaries.mkdir()
    bash = shutil.which("bash")
    assert bash, "bash is not on PATH"
    (binaries / "bash").symlink_to(bash)
    if uv_exit is not None:
        stub = binaries / "uv"
        stub.write_text(f"#!/bin/sh\nexit {uv_exit}\n")
        stub.chmod(0o755)
    script = (
        "set -Eeuo pipefail\n"
        'block() { printf "BLOCK %s\\n" "$1"; }\n'
        'skip()  { printf "SKIP %s\\n" "$1"; }\n'
        'ok()    { printf "OK %s\\n" "$1"; }\n'
        f"{body.group(0)}\n"
        "signing_key_status"
    )
    done = subprocess.run(
        [bash, "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PATH": str(binaries)},
    )
    assert done.returncode == 0, f"signing_key_status() failed: {done.stderr}"
    return done.stdout.splitlines()


@pytest.mark.parametrize(
    ("uv_exit", "verdict"),
    [(0, "OK "), (1, "BLOCK "), (None, "SKIP ")],
    ids=["matches", "missing-or-wrong", "no-uv"],
)
def test_the_signing_key_check_blocks_a_release_it_cannot_sign(
    tmp_path, uv_exit, verdict
) -> None:
    (line,) = _signing_key_status(tmp_path, uv_exit=uv_exit)
    assert line.startswith(verdict)


# --- LWSM-1544: the smoke checks the display plugins and both Debians --------

SMOKE = REPO / "scripts/_appimage-smoke.sh"


def _check_plugins(tmp_path: Path, *, ldd_says: str, plugins: bool = True):
    """Run the smoke script's OWN `check_platform_plugins()` over a fake bundle
    whose stand-in `ldd` prints `ldd_says` for every plugin."""
    bundle = tmp_path / "squashfs-root/usr/lib/lwsm/_internal/PySide6/Qt"
    (bundle / "plugins/platforms").mkdir(parents=True)
    (bundle / "lib").mkdir()
    if plugins:
        (bundle / "plugins/platforms/libqxcb.so").write_text("")
        (bundle / "plugins/platforms/libqwayland-generic.so").write_text("")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    (binaries / "ldd").write_text(f"#!/bin/sh\ncat <<'EOF'\n{ldd_says}\nEOF\n")
    (binaries / "ldd").chmod(0o755)
    bash = shutil.which("bash")
    assert bash, "bash is not on PATH"
    script = (
        'fail() { echo "FAIL $*" >&2; exit 1; }\n'
        f"{_function(SMOKE, 'check_platform_plugins')}\n"
        'check_platform_plugins "$1"'
    )
    return subprocess.run(
        [bash, "-c", script, "_", str(tmp_path / "squashfs-root")],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PATH": f"{binaries}:{os.environ['PATH']}"},
    )


def test_a_platform_plugin_with_a_missing_library_fails_the_smoke(tmp_path) -> None:
    """LWSM-1544. The offscreen launch never loads libqxcb or libqwayland, so
    their libraries are checked with `ldd`.

    Dies on dropping the `not found` match, or on ignoring ldd's verdict.
    """
    done = _check_plugins(
        tmp_path,
        ldd_says="\tlibxkbcommon-x11.so.0 => not found\n\tlibc.so.6 => /lib/libc.so.6",
    )
    assert done.returncode == 1, done.stdout
    assert "libxkbcommon-x11.so.0" in done.stderr
    assert "libqxcb.so" in done.stderr


def test_platform_plugins_that_resolve_pass(tmp_path) -> None:
    done = _check_plugins(tmp_path, ldd_says="\tlibc.so.6 => /lib/libc.so.6")
    assert done.returncode == 0, done.stderr
    assert "platform plugins OK" in done.stdout


def test_a_bundle_with_no_platform_plugin_fails_the_smoke(tmp_path) -> None:
    """A check that finds nothing to check must not pass."""
    done = _check_plugins(tmp_path, ldd_says="", plugins=False)
    assert done.returncode == 1, done.stdout


def test_the_smoke_runs_the_plugin_check_after_the_launch() -> None:
    """The function is useless unless it is called, on the extracted bundle."""
    text = SMOKE.read_text()
    call = text.index('check_platform_plugins "$EXTRACT')
    assert call > text.index('echo "smoke: launch OK'), (
        "the check runs before the launch"
    )
    assert "--appimage-extract" in text


def test_the_smoke_image_carries_the_two_host_libraries() -> None:
    """The xcb and wayland plugins are otherwise left to the host by design."""
    text = BUILD.read_text()
    assert "libxkbcommon-x11-0" in text
    assert "libwayland-cursor0" in text


def _smoke_on(tmp_path: Path, release: str, base: str) -> list[str]:
    """Run the build script's OWN `smoke_on()` with a stand-in container
    runner; return what the runner was asked, one call per line, with the
    Dockerfile it was fed."""
    binaries = tmp_path / "bin"
    binaries.mkdir(parents=True)
    record = tmp_path / "runner.log"
    (binaries / "runner").write_text(
        f'#!/bin/sh\necho "$@" >> {record}\n'
        f'[ "$1" = build ] && cat >> {record}\nexit 0\n'
    )
    (binaries / "runner").chmod(0o755)
    bash = shutil.which("bash")
    assert bash, "bash is not on PATH"
    script = (
        "set -euo pipefail\n"
        f"RUNNER={binaries}/runner WORK=/w DIST=/d ROOT=/r\n"
        "APPIMAGE=a.AppImage VERSION=1\n"
        'SMOKE_PACKAGES="pkg-a pkg-b"\n'
        f"{_function(BUILD, 'smoke_on')}\n"
        'smoke_on "$1" "$2"'
    )
    subprocess.run([bash, "-c", script, "_", release, base], check=True)
    return record.read_text().splitlines()


def test_each_debian_gets_its_own_image_and_its_own_smoke_run(tmp_path) -> None:
    """LWSM-1544. Two releases must not share a tag, and the image a release is
    built from must be the one its smoke runs in.

    Dies on a shared tag, or on running the smoke in the other image.
    """
    seen = {}
    for release, base in (("13", "base@sha256:13"), ("12", "base@sha256:12")):
        calls = _smoke_on(tmp_path / release, release, base)
        build = next(c for c in calls if c.startswith("build "))
        run = next(c for c in calls if c.startswith("run "))
        tag = build.split("-t ")[1].split()[0]
        assert tag.endswith(f":{release}"), build
        assert f"FROM {base}" in calls, calls
        assert "pkg-a pkg-b" in "\n".join(calls)
        assert f" {tag} bash /scripts/_appimage-smoke.sh /artifact/a.AppImage 1" in run
        seen[release] = tag
    assert seen["13"] != seen["12"]


def test_both_debians_are_smoked_from_digest_pins() -> None:
    """The README promises Debian 12; the smoke covers it and Debian 13, each
    pinned by digest."""
    text = BUILD.read_text()
    pins = {
        m.group(1): m.group(2)
        for m in re.finditer(
            r'^SMOKE_BASE_(\d+)="docker\.io/library/debian@(sha256:[0-9a-f]{64})"$',
            text,
            re.M,
        )
    }
    assert set(pins) == {"13", "12"}, pins
    assert len(set(pins.values())) == 2
    assert re.search(r'^smoke_on 13 "\$SMOKE_BASE_13"$', text, re.M)
    assert re.search(r'^smoke_on 12 "\$SMOKE_BASE_12"$', text, re.M)
