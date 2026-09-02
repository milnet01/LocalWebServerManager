"""The local gate and the GitHub run must stay the same run.

Two properties, and neither is enforceable by a comment — both were stated as
comments in `ci.yml` and `local-ci.sh` already, and both were violated anyway:

1. **The workflow adds no checks.** It prepares a machine and calls
   `scripts/local-ci.sh`. A check step added here and not to the script is one
   a developer cannot run before pushing, which is the whole failure the split
   exists to prevent.
2. **Both sides install the same tool versions.** This is the one that
   actually bit. On 2026-08-18 every push went red on two SC2015 findings while
   `./scripts/local-ci.sh` was green: the runner's apt shipped shellcheck 0.9,
   the developer had 0.11.0, and 0.11 relaxed SC2015 for `command -v` guards.
   The *steps* matched exactly. The tools did not, and nothing compared them.

Parsed with regexes rather than PyYAML on purpose: PyYAML is not a dependency
of this project, and `local-ci.sh` records why it must not become one just to
let a check read a file (a gate that fails because the gate is broken is worse
than one that admits it did not run).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from test_docs import GOVERNED

REPO = Path(__file__).resolve().parents[1]
WORKFLOW = REPO / ".github/workflows/ci.yml"
TOOLS_ENV = REPO / "scripts/ci-tools.env"
LOCAL_CI = REPO / "scripts/local-ci.sh"

# Every `run:` step the workflow is allowed to have, by name. Preparing a
# machine is legitimate; checking the project is not. Adding a name here is
# meant to be uncomfortable — if the new step CHECKS anything, it belongs in
# scripts/local-ci.sh instead, and this list is the place that argument gets
# had.
PREPARATION_STEPS = frozenset(
    {
        "Install uv",
        "Install Python",
        "Install Qt runtime libraries",
        "Install shellcheck, actionlint and yamllint",
    }
)

# The one step that is allowed to run the project's own checks, and the exact
# command it is allowed to run.
GATE_STEP = "Run the gate"
GATE_COMMAND = "./scripts/local-ci.sh"


def pins() -> dict[str, str]:
    """`KEY=value` out of ci-tools.env, ignoring comments and blanks."""
    found = {}
    for line in TOOLS_ENV.read_text().splitlines():
        match = re.fullmatch(r"([A-Z][A-Z0-9_]*)=(\S+)", line.strip())
        if match:
            found[match.group(1)] = match.group(2)
    return found


def test_the_pin_file_declares_every_tool_the_gate_verifies() -> None:
    """The two sides of the pin, in one assertion.

    A pin nothing reads is decoration, and a `check_version` call against an
    undefined variable would abort the gate under `set -u` — after the tests
    have already passed, which is the worst place to find out.
    """
    declared = set(pins())
    verified = set(re.findall(r'check_version \w+ "\$(\w+)"', LOCAL_CI.read_text()))

    assert verified, "local-ci.sh verifies no tool versions at all"
    assert verified == declared, (
        f"ci-tools.env declares {sorted(declared)} but local-ci.sh verifies "
        f"{sorted(verified)}"
    )


@pytest.mark.parametrize(
    ("key", "pattern"),
    [
        # Each is the literal way the workflow's install step names that
        # version. They must interpolate the pin, never restate the number:
        # a hard-coded "0.11.0" here would pass today and rot silently.
        ("SHELLCHECK_VERSION", r"shellcheck-v\$\{SHELLCHECK_VERSION\}"),
        ("YAMLLINT_VERSION", r"yamllint==\$\{YAMLLINT_VERSION\}"),
        ("ACTIONLINT_VERSION", r"actionlint@v\$\{ACTIONLINT_VERSION\}"),
    ],
)
def test_the_workflow_installs_the_pinned_version(key: str, pattern: str) -> None:
    """The workflow must take its versions FROM the pin file, not repeat them.

    Interpolation is the property under test, not equality: two literals that
    happen to match today are two literals, and the next bump moves one.
    """
    text = WORKFLOW.read_text()

    assert key in pins(), f"{key} is not declared in scripts/ci-tools.env"
    assert re.search(pattern, text), (
        f"the workflow does not install {key} by interpolating the pin; "
        f"expected something matching {pattern!r}"
    )
    assert ". scripts/ci-tools.env" in text, (
        "the workflow interpolates the pins without sourcing ci-tools.env"
    )


def test_the_workflow_installs_the_pinned_uv() -> None:
    """uv is pinned by literal, not by interpolation, and this test is why that
    is still a link rather than a coincidence.

    `setup-uv` takes its version as a `uses:` input, and a `uses:` input cannot
    read a shell variable — so the workflow has to repeat the number. Asserting
    equality here is what stops the two copies parting. uv decides which
    interpreter resolves and which pytest runs, so it matters more than the
    three linters put together.
    """
    pinned = pins()["UV_VERSION"]

    assert f'version: "{pinned}"' in WORKFLOW.read_text(), (
        f"ci-tools.env pins uv {pinned}, which the workflow does not install"
    )


def test_the_workflow_runs_no_check_of_its_own() -> None:
    """`ci.yml` prepares a machine and hands over. It does not check anything.

    A check added here and not to `scripts/local-ci.sh` cannot be run before a
    push, which is precisely what having a local gate is for.
    """
    named_steps = re.findall(r"^      - name: (.+)$", WORKFLOW.read_text(), re.M)

    assert GATE_STEP in named_steps, "the workflow never runs the gate"
    unexpected = [s for s in named_steps if s not in PREPARATION_STEPS | {GATE_STEP}]
    assert not unexpected, (
        f"ci.yml grew step(s) the local gate does not have: {unexpected}. "
        f"If they CHECK anything, move them into scripts/local-ci.sh; if they "
        f"only prepare the machine, add them to PREPARATION_STEPS here."
    )


def test_the_gate_step_runs_the_script_and_nothing_else() -> None:
    """The handover itself. A `run:` block that did more than call the script
    would be a check the developer cannot reproduce, however short."""
    text = WORKFLOW.read_text()
    tail = text[text.index(f"- name: {GATE_STEP}") :]
    commands = [
        line.strip()
        for line in tail.splitlines()
        if line.strip() and not line.strip().startswith(("#", "-", "env:", "name:"))
    ]

    assert GATE_COMMAND in " ".join(commands), "the gate step does not call the script"
    extra = [c for c in commands if not re.fullmatch(r"(run: )?[\w:./-]+ ?\d*", c)]
    assert not extra, f"the gate step does more than call the script: {extra}"


# --- the hook that makes "run the gate before pushing" more than a convention -

HOOK = REPO / ".githooks/pre-push"


def test_the_pre_push_hook_exists_and_is_executable() -> None:
    """`core.hooksPath` is per-clone and cannot be committed, so what is
    checkable is that the file a clone points AT is present and runnable.

    A hook that is not executable is silently ignored by git — no error, no
    output, and the push it was meant to gate goes through looking normal.
    """
    assert HOOK.is_file(), "the pre-push hook is missing"
    assert HOOK.read_text().startswith("#!"), "the hook has no shebang"
    assert HOOK.stat().st_mode & 0o111, (
        "the pre-push hook is not executable; git ignores it silently"
    )


def test_the_hook_runs_the_same_gate_and_does_not_shortcut_it() -> None:
    """`--fast` drops the integration tests, so a hook using it would pass a
    push that GitHub then fails — reintroducing the split this whole
    arrangement exists to close."""
    # The INVOCATION, not the file: the hook's comments explain why --fast is
    # wrong here, and a naive scan of the whole text fails on its own
    # reasoning. The first version of this test did exactly that.
    invocations = [
        line.strip()
        for line in HOOK.read_text().splitlines()
        if GATE_COMMAND in line and not line.strip().startswith("#")
    ]

    assert invocations, "the hook does not run the gate"
    for call in invocations:
        assert "--fast" not in call, f"the hook runs a reduced gate: {call}"


def test_the_hook_exempts_docs_but_never_the_gate_s_own_inputs() -> None:
    """The exemption is by path, and these three directories decide what the
    gate CHECKS — scripts/ holds the gate itself, .github/ is what actionlint
    reads, and src/tests are the suite. Exempting any of them would let a
    change to the checker skip the check."""
    text = HOOK.read_text()
    case_body = text[text.index("case $path in") : text.index("esac")]

    assert "docs/*" in case_body, "docs/ is not exempt, so the exemption is dead"
    for never in ("scripts/", ".github/", "src/", "tests/"):
        assert never not in case_body, (
            f"{never} appears in the docs-only exemption; a change there must "
            f"always run the gate"
        )


def _hook_says_docs_only(paths: list[str]) -> bool:
    """Run the hook's OWN `docs_only()` over `paths`, and report its verdict.

    Executing the function rather than scanning its text, for the reason
    `test_layering.py` parses an AST rather than grepping. The sibling test
    above reads the case arms as *strings*, and a string can only say which
    patterns are present — never which arm a given path lands in. That gap is
    what shipped on 2026-08-19: `CLAUDE.md` matched the exemption's `*.md`, the
    push skipped the gate, and every assertion in that test still held.
    """
    body = re.search(r"^docs_only\(\) \{.*?^\}$", HOOK.read_text(), re.S | re.M)
    assert body, "the hook has no docs_only() to run"

    done = subprocess.run(
        ["bash", "-c", f"{body.group(0)}\ndocs_only"],
        input="".join(f"{path}\n" for path in paths),
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode in (0, 1), (
        f"docs_only() neither accepted nor refused: {done.returncode} {done.stderr}"
    )
    return done.returncode == 0


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is not installed")
def test_contributing_does_not_contradict_the_gate_it_describes() -> None:
    """The instructions a contributor follows must match what the hook does.

    Step 5 told contributors that "a green run locally is a green run in CI"
    and that "a docs-only change is exempt", full stop. Both are false: a hand
    run treats a missing tool and a version mismatch as warnings and still
    prints "Local CI passed", and the exemption has a carve-out for exactly
    the markdown the suite asserts against. A contributor editing a standard
    followed that sentence, skipped the gate and reddened CI — the measured
    2026-08-19 incident, re-enabled by the documentation (LWSM-1208).

    Asserted against `GOVERNED` for the sibling test's reason: naming the
    three files here would be a second copy of a list that can grow, and a
    standard added to `test_docs.py` alone would leave this green.
    """
    text = (REPO / "CONTRIBUTING.md").read_text(encoding="utf-8")

    # The COMMAND, not the setting's name. Two mutants proved the looser form
    # worthless: `core.hooksPath` also appears in the sentence explaining it,
    # and `docs/standards/` appears in steps 2 to 4, so both assertions passed
    # against a doc with the instruction and the carve-out removed.
    assert "git config core.hooksPath .githooks" in text, (
        "the enforcement mechanism is never given as a command, so the gate is "
        "left to a habit a contributor has to remember"
    )
    assert "LWSM_REQUIRE_ALL_TOOLS" in text, (
        "the doc does not say a hand run is more forgiving than CI, which is "
        "what the flag exists to make true"
    )

    # Scoped to the exemption's own paragraph. Elsewhere in the file these
    # paths are cited for what they SAY, which is a different claim.
    marker = "docs-only change is exempt"
    assert marker in text, "the exemption is not described at all"
    carve_out = text[text.index(marker) :]
    for path in GOVERNED:
        name = path.relative_to(REPO).as_posix()
        stem = "docs/standards/" if name.startswith("docs/standards/") else name
        assert stem in carve_out, (
            f"{name} always runs the gate and CONTRIBUTING.md does not say so "
            "where it describes the exemption"
        )


def test_the_hook_never_exempts_a_markdown_file_the_suite_asserts_against() -> None:
    """A file the gate READS is a gate input, whatever its extension.

    `test_docs.py` asserts against `CLAUDE.md`, `README.md` and every standard,
    so an edit to one of them can redden the suite — which is precisely what
    happened on 2026-08-19. The push was markdown-only, the hook exempted it on
    that basis, and GitHub found a prose count `documentation.md § 1.5` forbids.
    The hook's own comment already made this argument for `scripts/` and
    `.github/`; nobody had made it for prose.

    `GOVERNED` is IMPORTED rather than restated. A copy of that list here is a
    second place to update, and a standard added to `test_docs.py` alone would
    leave this test green while the file it governs pushes ungated.
    """
    assert GOVERNED, "test_docs governs nothing, so this test proves nothing"

    for path in GOVERNED:
        relative = path.relative_to(REPO).as_posix()
        assert not _hook_says_docs_only([relative]), (
            f"a push touching only {relative} skips the gate, but test_docs.py "
            f"asserts against it — so the check that would have caught the edit "
            f"is the one the edit skips"
        )

    # The other half, deliberately in the SAME test: a `docs_only()` that
    # exempted nothing would satisfy the loop above while silently deleting the
    # exemption, and every push would pay the full gate. Neither half holds
    # alone — the lesson LWSM-1149's vacuous geometry tests cost.
    assert _hook_says_docs_only(["docs/design.md"]), (
        "ordinary prose no longer takes the docs-only exemption"
    )

    # And a mixed push is not docs-only, however much of it is prose.
    assert not _hook_says_docs_only(["docs/design.md", "CLAUDE.md"]), (
        "a push carrying one governed file among many exempt ones skips the gate"
    )


def _hook_verdict(tmp_path: Path, changed: str) -> str:
    """Run the REAL hook in a throwaway clone whose gate is a stub, pushing one
    commit that touches `changed`, and return everything the run printed.

    Executing the hook rather than scanning it, for the reason
    `_hook_says_docs_only` gives above: a scrape can say a variable appears
    somewhere in the file, never that the gate was invoked *under* it.

    The stub records its environment and exits. A real gate would take fifteen
    seconds and answer nothing this test is asking.
    """
    repo = tmp_path / "clone"
    (repo / "scripts").mkdir(parents=True)
    (repo / ".githooks").mkdir()
    shutil.copy(HOOK, repo / ".githooks/pre-push")

    gate = repo / "scripts/local-ci.sh"
    gate.write_text(
        "#!/usr/bin/env bash\n"
        'printf "GATE-RAN REQUIRE=%s\\n" "${LWSM_REQUIRE_ALL_TOOLS:-unset}"\n'
    )
    gate.chmod(0o755)

    def git(*args: str) -> str:
        done = subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "-c",
                "user.email=t@example.invalid",
                "-c",
                "user.name=test",
                *args,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return done.stdout.strip()

    git("init", "-q", "-b", "main")
    (repo / "seed.txt").write_text("seed\n")
    git("add", "-A")
    git("commit", "-qm", "seed")
    base = git("rev-parse", "HEAD")

    target = repo / changed
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("changed\n")
    git("add", "-A")
    git("commit", "-qm", "change")
    head = git("rev-parse", "HEAD")

    # Cleared, not inherited. CI sets LWSM_REQUIRE_ALL_TOOLS=1 for the whole
    # gate step, so pytest itself runs under it — a stub that merely inherited
    # the variable would report REQUIRE=1 on the runner whatever the hook did,
    # and this test would pass on GitHub while the defect it names shipped.
    env = {k: v for k, v in os.environ.items() if k != "LWSM_REQUIRE_ALL_TOOLS"}

    done = subprocess.run(
        ["bash", str(repo / ".githooks/pre-push"), "origin", "url"],
        cwd=repo,
        env=env,
        input=f"refs/heads/main {head} refs/heads/main {base}\n",
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, f"the hook refused the push: {done.stderr}"
    return done.stdout + done.stderr


def test_the_hook_runs_the_gate_under_the_same_environment_as_github(
    tmp_path: Path,
) -> None:
    """A SKIP and a TOOL DRIFT are fatal on the runner and a warning locally,
    so the hook must invoke the gate the way the workflow does.

    That asymmetry is right for a developer running `./scripts/local-ci.sh` by
    hand — a missing linter must not stop them testing their own change. It is
    wrong at the one moment the local run is standing in for CI. Measured
    2026-08-21 with actionlint off PATH: the same tree exited 0 through the
    hook and 1 under the workflow's environment, so the push went out and
    GitHub failed it. The hook already makes exactly this argument for
    `--fast`, one line down, and stopped short of the environment.

    Both halves in ONE test on purpose: a hook that ran the gate on every push
    would satisfy the first assertion while deleting the exemption, and a hook
    that ran it on none would satisfy the second while deleting the gate.
    Neither holds alone — the lesson LWSM-1149's vacuous geometry tests cost.
    """
    ran = _hook_verdict(tmp_path / "code", "src/lwsm/thing.py")
    assert "GATE-RAN" in ran, f"the hook never ran the gate at all: {ran}"
    assert "REQUIRE=1" in ran, (
        "the hook runs the gate WITHOUT LWSM_REQUIRE_ALL_TOOLS=1, so a skipped "
        "check or a drifted tool passes a push that GitHub then fails — the "
        f"split this file exists to close: {ran}"
    )

    skipped = _hook_verdict(tmp_path / "docs", "docs/design.md")
    assert "GATE-RAN" not in skipped, (
        f"a docs-only push now pays the full gate, so the exemption is dead: {skipped}"
    )


# --- the comparison itself ----------------------------------------------------


def check_version_harness(pinned: str, found: str) -> int:
    """Run `local-ci.sh`'s own `check_version` in isolation, and return how many
    tools it recorded as drifted.

    The function is extracted from the script rather than reimplemented here:
    a copy of the comparison would pass while the real one was broken, which is
    the whole failure mode this file exists to catch one level up.
    """
    import subprocess
    import textwrap

    text = LOCAL_CI.read_text()
    start = text.index("check_version() {")
    end = text.index("\n}\n", start) + len("\n}\n")
    function = text[start:end]

    script = textwrap.dedent("""\
        DRIFTED=(); YELLOW=''; RESET=''
        {function}
        check_version toolname '{pinned}' '{found}' >/dev/null
        printf '%s' "${{#DRIFTED[@]}}"
    """).format(function=function, pinned=pinned, found=found)

    return int(
        subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True, check=True
        ).stdout
    )


@pytest.mark.parametrize(
    ("pinned", "found", "drifts", "why"),
    [
        ("1.7.12", "1.7.12", 0, "identical"),
        # The case that cost a red build. `go install …@v1.7.12` compiles the
        # tag in, so that binary says "v1.7.12"; the release binary says
        # "1.7.12". Same version, and reporting it as drift is a false alarm
        # that makes the whole check untrustworthy.
        ("1.7.12", "v1.7.12", 0, "a leading v is spelling, not version"),
        ("v1.7.12", "1.7.12", 0, "and the same the other way round"),
        ("0.11.0", "0.9.0", 1, "a real difference must still be caught"),
        ("1.7.12", "1.7.2", 1, "and a near miss is a difference"),
    ],
)
def test_a_leading_v_is_not_drift_but_a_different_number_is(
    pinned: str, found: str, drifts: int, why: str
) -> None:
    assert check_version_harness(pinned, found) == drifts, why


# --- the release recipe and the drift check must cover the same files ---------

RECIPE = REPO / ".claude/bump.json"
DRIFT = REPO / "scripts/check-version-drift.sh"


def recipe() -> dict:
    import json

    return json.loads(RECIPE.read_text())


def test_every_file_the_recipe_bumps_is_a_file_the_drift_check_reads() -> None:
    """The two halves of LWSM-1067, and neither works alone.

    A file the recipe bumps but the check does not read can be left at the old
    version silently — `post_check` is the recipe's only mechanical proof it
    finished, and it cannot prove anything about a file it never opens. A file
    the check reads but the recipe does not bump is the mirror: it fails every
    release and has to be edited by hand, which is what the recipe exists to
    stop.
    """
    bumped = {entry["path"] for entry in recipe()["files"]}
    text = DRIFT.read_text()
    # The source of truth is read directly rather than through `expect`, so it
    # is named separately here.
    # The label is always quoted and may contain spaces, so it is matched as a
    # quoted run rather than as \S+ — which swallowed half of
    # `"README current version"` and reported the path as "current".
    read = set(re.findall(r'^expect "[^"]*" (\S+)', text, re.M))
    read.add(recipe()["version_source"])

    assert bumped == read, (
        f"the recipe bumps {sorted(bumped)} but the drift check reads {sorted(read)}"
    )


def test_the_recipe_post_check_is_the_drift_script() -> None:
    """`post_check` is the release's only mechanical proof the bump landed
    everywhere. A recipe without one rests on a human re-reading the file
    list — the check that passes right up until it matters."""
    assert "check-version-drift.sh" in recipe().get("post_check", ""), (
        "the recipe's post_check does not run the drift script"
    )


def test_the_gate_runs_the_drift_check_too() -> None:
    """Not only at release time. A drift introduced today should fail today's
    push, rather than surfacing weeks later as a stopped release."""
    assert "check-version-drift.sh" in LOCAL_CI.read_text(), (
        "scripts/local-ci.sh does not run the version lockstep check"
    )


def test_the_recipe_does_not_bump_a_historical_marker() -> None:
    """bump-recipe.md § Notes: a CHANGELOG heading for a shipped release states
    what happened once, and bumping it makes it false. The same argument bars
    the bind address `0.0.0.0` in ADR-0002, which a grep for the current
    version would otherwise have swept into the list."""
    bumped = {entry["path"] for entry in recipe()["files"]}

    assert "CHANGELOG.md" not in bumped, "the recipe would rewrite release history"
    assert not any("decisions" in path for path in bumped), (
        "an ADR is a dated record, not a version-bearing file"
    )


# --- the gate reads the working tree; CI reads the committed one -------------


@pytest.mark.parametrize(
    "path",
    [WORKFLOW, TOOLS_ENV, LOCAL_CI, HOOK, RECIPE, DRIFT],
    ids=lambda p: p.name,
)
def test_every_file_the_gate_depends_on_is_committed(path) -> None:
    """The third instance of one class in a day, and the cheapest to prevent.

    `scripts/local-ci.sh` reads the WORKING TREE; the runner reads the
    COMMITTED tree. A file that exists locally and is not committed makes the
    two different runs while looking like one — the same shape as the
    shellcheck version drift, arriving through git instead of through apt.

    `.claude/bump.json` landed under `.gitignore`'s `.claude/*` rule, so three
    tests here passed locally and failed on the runner with FileNotFoundError.
    Nothing local could have caught that, because locally the file is right
    there. This test is what makes the absence visible on the machine that
    can still fix it cheaply.
    """
    import subprocess

    rel = path.relative_to(REPO)
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(rel)],
        cwd=REPO,
        capture_output=True,
    )

    assert tracked.returncode == 0, (
        f"{rel} is read by the gate but is not tracked by git — CI will not "
        f"see it. Check .gitignore."
    )
