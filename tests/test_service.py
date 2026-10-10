"""LWSM-1012 — driving a project whose server is a systemd user unit.

ADR-0003's amendment gives service-managed projects their own column: start,
stop and restart go to `systemctl --user`, never to a spawned launcher. These
tests are the contract for that column.

The reporting machine is what the fixtures are drawn from: two servers started
at logon, `ants-stats.service` on 4321 and an escaped `app-…@autostart.service`
on 8765, neither of which the app started and both of which it must manage.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from lwsm import service
from lwsm.service import (
    UNIT_VERB_TIMEOUT_SECONDS,
    VERBS,
    Holder,
    describe_holder,
    drive_unit,
    unit_argv,
    unit_belongs_to,
    unit_for_pid,
    unit_state,
)

# Taken at import, before `conftest.reloads` replaces the module attribute for
# every test, so the real reload can still be tested against a fake runner.
REAL_RELOAD = service.reload_user_manager
REAL_SEEN = service.drop_in_seen

# Verbatim from `/proc/<pid>/cgroup` on the reporting machine, escaped name and
# all, except the uid: only OUR user manager's units are ours to drive
# (review-code 2026-10-08 L05-L1), so the fixture is in the running user's.
# Transcribed rather than composed: the escaping is the part that breaks.
UID = os.getuid()
ESCAPED = (
    f"0::/user.slice/user-{UID}.slice/user@{UID}.service/app.slice/"
    "app-ai\\x2dprompts\\x2dtray@autostart.service\n"
)
PLAIN = (
    f"0::/user.slice/user-{UID}.slice/user@{UID}.service/app.slice/ants-stats.service\n"
)


# --- reading a unit off a process ---------------------------------------------


def test_a_logon_started_server_is_named_by_its_cgroup() -> None:
    """The registry cannot answer this and the kernel can.

    `ProjectRecord.unit` is None for every project on the reporting machine, so
    an adoption built on a registry lookup would have adopted nothing.
    """
    assert unit_for_pid(1290, read_cgroup=lambda pid: PLAIN) == "ants-stats.service"


def test_the_escaped_form_is_returned_because_systemctl_takes_no_other() -> None:
    """`systemctl` accepts only the escaped name, so unescaping here would
    produce a string that names the right unit and drives nothing."""
    unit = unit_for_pid(1844, read_cgroup=lambda pid: ESCAPED)
    assert unit == "app-ai\\x2dprompts\\x2dtray@autostart.service"


def test_the_session_manager_is_never_returned_as_a_unit() -> None:
    """Stopping `user@1000.service` logs the user out.

    A process directly under the session manager names no server, so this is
    refused at the read rather than left for a caller to notice.
    """
    raw = "0::/user.slice/user-1000.slice/user@1000.service\n"
    assert unit_for_pid(1, read_cgroup=lambda pid: raw) is None


def test_another_users_service_is_not_ours_to_drive() -> None:
    """review-code 2026-10-08 L05-L1. `/proc/<pid>/cgroup` is readable by
    everyone, and the pattern matched any uid's user manager, so a port held
    by another user's `foo.service` named `foo.service` -- and `systemctl
    --user` then drove OUR `foo.service`, a different unit.

    Dies on matching `user@<any uid>`.
    """
    other = UID + 1
    raw = (
        f"0::/user.slice/user-{other}.slice/user@{other}.service/app.slice/"
        "foo.service\n"
    )
    assert unit_for_pid(77, read_cgroup=lambda pid: raw) is None


def test_a_scope_is_not_a_service() -> None:
    """A process started from a shell lands in a `.scope`, which has no stop
    verb worth offering — it is not a unit anyone configured."""
    raw = "0::/user.slice/user-1000.slice/user@1000.service/app.slice/session-2.scope\n"
    assert unit_for_pid(9, read_cgroup=lambda pid: raw) is None


def test_a_process_that_has_already_exited_answers_none_rather_than_raising() -> None:
    """The socket read and this call are separate moments."""

    def gone(pid: int) -> str:
        raise FileNotFoundError(f"/proc/{pid}/cgroup")

    assert unit_for_pid(4242, read_cgroup=gone) is None


# --- the argv, which is where the security rules live -------------------------


def test_the_unit_name_is_separated_from_the_options() -> None:
    """ADR-0003's `--`. Built here rather than at each call site so a caller
    cannot ship one without it."""
    assert unit_argv("stop", "ants-stats.service") == [
        "systemctl",
        "--user",
        "stop",
        "--",
        "ants-stats.service",
    ]


@pytest.mark.parametrize("verb", ["disable", "mask", "kill", "daemon-reload", ""])
def test_only_the_three_verbs_can_be_driven(verb: str) -> None:
    """`disable` is the one that matters: the whole request was to manage these
    servers WITHOUT losing their start at logon, and a module that cannot
    express the verb cannot regress that in a later edit."""
    assert verb not in VERBS
    with pytest.raises(ValueError):
        unit_argv(verb, "ants-stats.service")


@pytest.mark.parametrize(
    "unit",
    [
        "--host=evil.service",
        "-M container.service",
        "user@1000.service",
        "init.scope",
        "not a unit name",
        "",
    ],
)
def test_a_name_that_redirects_or_destroys_is_refused(unit: str) -> None:
    """`--host=` and `-M` redirect which manager is driven; the session units
    end the login session. None can reach an argv."""
    with pytest.raises(ValueError):
        unit_argv("stop", unit)


# --- driving one verb ---------------------------------------------------------


class FakeRun:
    """Records the argv it was handed and returns a chosen result."""

    def __init__(self, returncode: int = 0, stderr: str = "", stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.argv: list[str] | None = None
        self.timeout: float | None = None

    def __call__(self, argv, **kwargs):
        self.argv = argv
        self.timeout = kwargs.get("timeout")
        return subprocess.CompletedProcess(
            argv, self.returncode, self.stdout, self.stderr
        )


def test_a_stop_drives_systemctl_and_never_a_signal() -> None:
    """ADR-0003 forbids signalling a bare PID; naming the unit is what makes it
    unnecessary, since systemd resolves the name in the caller's own session."""
    run = FakeRun()
    outcome = drive_unit("stop", "ants-stats.service", run=run)

    assert outcome.ok
    assert run.argv == ["systemctl", "--user", "stop", "--", "ants-stats.service"]
    assert run.timeout == UNIT_VERB_TIMEOUT_SECONDS


def test_a_refused_verb_reports_and_does_not_run_anything() -> None:
    """The guard fires before the runner, so a rejected name cannot reach a
    subprocess at all."""
    run = FakeRun()
    outcome = drive_unit("disable", "ants-stats.service", run=run)

    assert not outcome.ok
    assert run.argv is None


def test_systemd_s_own_message_is_reported_and_bounded() -> None:
    """Foreign text reaching a widget is what `MAX_REASON_CHARS` is for, and the
    bound is applied here so no caller can forget it."""
    from lwsm.configfile import MAX_REASON_CHARS

    run = FakeRun(returncode=1, stderr="Failed to stop: " + "x" * 500)
    outcome = drive_unit("stop", "ants-stats.service", run=run)

    assert not outcome.ok
    assert "Failed to stop" in outcome.reason
    assert len(outcome.reason) <= MAX_REASON_CHARS


def test_only_systemd_s_own_non_zero_answer_is_a_rejection() -> None:
    """L05-M3: a rejection means no start is in progress, so the caller may
    remove the drop-in. A timeout is no answer at all: systemd may still be
    starting the unit."""

    def slow(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, UNIT_VERB_TIMEOUT_SECONDS)

    refused = drive_unit("start", "a.service", run=FakeRun(returncode=1))
    timed_out = drive_unit("start", "a.service", run=slow)
    worked = drive_unit("start", "a.service", run=FakeRun())

    assert (refused.ok, refused.rejected) == (False, True)
    assert (timed_out.ok, timed_out.rejected) == (False, False)
    assert worked.rejected is False


def test_a_failure_with_no_message_still_says_something() -> None:
    """An empty reason renders as a dialog explaining nothing."""
    outcome = drive_unit("stop", "ants-stats.service", run=FakeRun(returncode=1))

    assert not outcome.ok
    assert outcome.reason


def test_a_missing_systemctl_is_reported_rather_than_raised() -> None:
    """The caller is a button. PySide6 swallows an exception raised inside a
    slot, so raising here would lose the message entirely (`CLAUDE.md`)."""

    def absent(argv, **kwargs):
        raise FileNotFoundError("systemctl")

    outcome = drive_unit("stop", "ants-stats.service", run=absent)

    assert not outcome.ok
    assert "not installed" in outcome.reason


def test_a_stop_that_outlasts_the_budget_is_reported_not_retried() -> None:
    """Re-issuing a stop already in progress achieves nothing."""

    def slow(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, UNIT_VERB_TIMEOUT_SECONDS)

    outcome = drive_unit("stop", "ants-stats.service", run=slow)

    assert not outcome.ok
    assert "did not finish" in outcome.reason


# --- the disclosure ADR-0004 requires -----------------------------------------


class FakeProcess:
    """A `psutil.Process`-shaped holder, with per-field refusals."""

    def __init__(self, *, deny: frozenset[str] = frozenset()) -> None:
        self._deny = deny

    def _check(self, name: str) -> None:
        if name in self._deny:
            raise PermissionError(name)

    def exe(self) -> str:
        self._check("exe")
        return "/usr/bin/node24"

    def uids(self):
        self._check("uids")
        return type("Uids", (), {"real": 1000})()

    def cmdline(self) -> list[str]:
        self._check("cmdline")
        return ["/usr/bin/node", "serve.mjs"]

    def create_time(self) -> float:
        self._check("create_time")
        return 1788718035.0


def test_the_disclosure_carries_the_four_fields_the_adr_names() -> None:
    """ADR-0004: "the holder's executable path, uid, cmdline and start time,
    shown before anything opens"."""
    holder = describe_holder(1290, process=FakeProcess(), read_cgroup=lambda pid: PLAIN)

    assert holder.exe == "/usr/bin/node24"
    assert holder.uid == 1000
    assert holder.cmdline == "/usr/bin/node serve.mjs"
    assert holder.started == 1788718035.0
    assert holder.unit == "ants-stats.service"


def test_one_refused_field_does_not_cost_the_whole_disclosure() -> None:
    """A holder owned by another user answers some questions and refuses others.
    Losing every field to one `AccessDenied` would leave the dialog emptier than
    the facts warrant, which is the opposite of disclosure."""
    holder = describe_holder(
        1290,
        process=FakeProcess(deny=frozenset({"exe", "cmdline"})),
        read_cgroup=lambda pid: PLAIN,
    )

    assert holder.exe is None
    assert holder.cmdline == ""
    assert holder.uid == 1000
    assert holder.unit == "ants-stats.service"


def test_a_holder_with_no_unit_has_none() -> None:
    """Which is what sends the caller down the signalling path instead."""
    holder = describe_holder(7, process=FakeProcess(), read_cgroup=lambda pid: "0::/\n")

    assert holder.unit is None


def test_a_holder_is_still_returned_when_the_process_is_gone() -> None:
    """`describe_holder` answers a `Holder` or nothing useful — never an
    exception — because its caller is deciding what to show in a dialog."""
    holder = Holder(pid=99)

    assert holder.pid == 99
    assert holder.unit is None


def test_a_system_service_is_never_named_as_a_user_unit() -> None:
    """review-code 2026-10-01 L3-L5: a holder under `/system.slice/` named
    `foo.service`, which was then driven with `--user` — harmless unless a user
    unit of the same name exists, when a different unit is stopped. Only a
    unit under a user manager (`user@<uid>.service/`) is ours to drive."""
    raw = "0::/system.slice/nginx.service\n"
    assert unit_for_pid(5, read_cgroup=lambda pid: raw) is None


def test_systemctl_stderr_that_is_not_utf8_is_a_reason_not_an_exception() -> None:
    """L3-L4: `text=True` decodes strictly, and a `UnicodeDecodeError` is a
    `ValueError` — against "Never raises to the caller"."""

    def run(argv, **kwargs):
        return subprocess.run(["sh", "-c", "printf 'bad \\377' >&2; exit 1"], **kwargs)

    outcome = drive_unit("stop", "ants-stats.service", run=run)

    assert not outcome.ok
    assert outcome.reason.startswith("bad")


# --- reading a unit's state (L6-M3) -------------------------------------------


def test_a_failed_unit_reports_its_state_despite_the_nonzero_exit() -> None:
    """`is-active` exits 3 for every state but `active`, so stdout is the
    answer — reading the exit code would make `failed` look unreadable."""
    run = FakeRun(returncode=3, stdout="failed\n")

    assert unit_state("ants-stats.service", run=run) == "failed"
    assert run.argv == ["systemctl", "--user", "is-active", "--", "ants-stats.service"]


def test_an_unreadable_state_is_none_never_a_guess() -> None:
    def absent(argv, **kwargs):
        raise FileNotFoundError("systemctl")

    assert unit_state("ants-stats.service", run=absent) is None
    assert unit_state("ants-stats.service", run=FakeRun(stdout="")) is None


def test_the_session_manager_is_never_queried() -> None:
    run = FakeRun(stdout="active")
    assert unit_state("user@1000.service", run=run) is None
    assert run.argv is None


# --------------------------------------------------------------------------
# LWSM-1028 — the drop-in
# --------------------------------------------------------------------------


def test_the_drop_in_lives_under_the_user_unit_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    assert service.drop_in_path("a.service") == (
        tmp_path / "systemd" / "user" / "a.service.d" / "50-lwsm-port.conf"
    )


def test_a_hostile_unit_name_gets_no_drop_in() -> None:
    with pytest.raises(ValueError):
        service.drop_in_path("-M.service")
    with pytest.raises(ValueError):
        service.drop_in_path("user@1000.service")
    assert not service.set_drop_in("../x.service", 4321).ok


def test_the_drop_in_carries_port_and_managed_and_no_port_when_unknown() -> None:
    assert service.drop_in_text(4321) == (
        "[Service]\nEnvironment=PORT=4321\nEnvironment=LWSM_MANAGED=1\n"
    )
    assert service.drop_in_text(None) == "[Service]\nEnvironment=LWSM_MANAGED=1\n"


def test_every_set_reloads_even_with_the_same_bytes(reloads) -> None:
    """review-code 2026-10-08 L05-M1. Unchanged bytes used to skip the reload,
    assuming systemd had loaded them. It had not, where the first Start's
    reload failed: the next Start found the bytes in place, skipped the
    reload, and the unit started without its drop-in, on its own port --
    ADR-0002's silent no-op. So every set reloads; a Start is rare and a
    reload is cheap next to starting a server on the wrong port.

    Until 2026-10-08 this test asserted the skip.
    """
    first = service.set_drop_in("a.service", 4321)
    second = service.set_drop_in("a.service", 4321)
    third = service.set_drop_in("a.service", 5000)

    assert first.ok and second.ok and third.ok
    assert reloads == ["daemon-reload", "daemon-reload", "daemon-reload"]
    assert "PORT=5000" in service.drop_in_path("a.service").read_text(encoding="utf-8")


def test_clearing_removes_only_our_file_and_reloads(reloads) -> None:
    service.set_drop_in("a.service", 4321)
    theirs = service.drop_in_path("a.service").parent / "10-theirs.conf"
    theirs.write_text("[Service]\n", encoding="utf-8")
    reloads.clear()

    assert service.clear_drop_in("a.service").ok
    assert not service.drop_in_path("a.service").exists()
    assert theirs.exists()
    assert reloads == ["daemon-reload"]


def test_a_drop_in_systemd_does_not_read_stops_the_start(reloads, monkeypatch) -> None:
    """review-code 2026-10-08 L05-L3. The folder comes from THIS app's
    `XDG_CONFIG_HOME`, and systemd reads its user manager's. Set only in a
    shell profile, the two differ: the drop-in lands where systemd never
    looks, every step reports success, and the unit starts on its own port.
    So after the reload systemd is asked which drop-ins it read.

    Dies on not asking.
    """
    monkeypatch.setattr(service, "drop_in_seen", lambda unit, path: False)

    outcome = service.set_drop_in("a.service", 4321)

    assert not outcome.ok
    assert "XDG_CONFIG_HOME" in outcome.reason


def test_drop_in_seen_reads_systemds_own_list() -> None:
    """Through a fake runner only, like the reload."""
    path = Path("/home/u/.config/systemd/user/a.service.d/50-lwsm-port.conf")
    listed = f"/etc/systemd/user/a.service.d/10.conf {path}\n"

    assert REAL_SEEN("a.service", path, run=FakeRun(stdout=listed)) is True
    assert REAL_SEEN("a.service", path, run=FakeRun(stdout="\n")) is False
    assert REAL_SEEN("a.service", path, run=FakeRun(returncode=1)) is None


def test_clearing_with_nothing_to_remove_does_not_reload(reloads) -> None:
    assert service.clear_drop_in("a.service").ok
    assert reloads == []


def test_reload_reports_rather_than_raises() -> None:
    """Through a fake runner only: this one must never reach real systemd."""
    real = REAL_RELOAD

    def absent(*args, **kwargs):
        raise FileNotFoundError("systemctl")

    assert real(run=FakeRun(returncode=0)).ok
    failed = real(run=FakeRun(returncode=1))
    assert not failed.ok and failed.reason
    assert real(run=absent).reason == "systemctl is not installed"


# --- does an adopted unit belong to the row? (review-code 2026-10-01 L3-M4) ---

# The shapes measured on the reporting machine, 2026-10-02: an XDG-autostart
# unit's file is generated under /run/user, never inside a project.
GENERATED = "/run/user/1000/systemd/generator.late/app-x@autostart.service"


def _exec_start(argv: str) -> str:
    path = argv.split()[0]
    return f"{{ path={path} ; argv[]={argv} ; ignore_errors=no ; pid=0 }}"


def _reader(props: dict[str, str]):
    def read(unit: str, names: object, timeout: float) -> dict[str, str]:
        return props

    return read


def test_a_unit_whose_command_runs_a_file_in_the_project_belongs(tmp_path) -> None:
    """The ants-stats-tray shape: working directory is home, and only the
    command line names the project."""
    (tmp_path / "tray").mkdir()
    (tmp_path / "tray" / "stats.py").write_text("", encoding="utf-8")
    props = {
        "FragmentPath": GENERATED,
        "WorkingDirectory": "!/home/ants",
        "ExecStart": _exec_start(f"/usr/bin/python3 {tmp_path}/tray/stats.py"),
    }
    assert unit_belongs_to("a.service", tmp_path, properties=_reader(props))


def test_a_unit_whose_folder_is_the_project_belongs(tmp_path) -> None:
    """The ai-prompts-tray shape: `!`-prefixed working directory."""
    props = {
        "FragmentPath": GENERATED,
        "WorkingDirectory": f"!{tmp_path}",
        "ExecStart": _exec_start("/usr/bin/python3 tray.py"),
    }
    assert unit_belongs_to("a.service", tmp_path, properties=_reader(props))


def test_an_ide_holding_a_terminal_server_does_not_belong(
    tmp_path, monkeypatch
) -> None:
    """The finding's case. Our own cwd is inside the project, so a relative
    token resolved against it would bind the IDE — the reason only absolute
    paths can anchor."""
    monkeypatch.chdir(tmp_path)
    props = {
        "FragmentPath": GENERATED,
        "WorkingDirectory": "!/home/ants",
        "ExecStart": _exec_start("/usr/bin/ide --open serve.mjs"),
    }
    assert unit_belongs_to("ide.service", tmp_path, properties=_reader(props)) is False


def test_an_editor_opening_the_project_folder_does_not_belong(tmp_path) -> None:
    """Only a file the unit runs anchors it. An autostarted editor handed the
    project's directory names a path inside it without being its server."""
    props = {
        "FragmentPath": GENERATED,
        "WorkingDirectory": "!/home/ants",
        "ExecStart": _exec_start(f"/usr/bin/kate {tmp_path}"),
    }
    assert unit_belongs_to("kate.service", tmp_path, properties=_reader(props)) is False


def test_a_sibling_sharing_the_project_s_name_prefix_does_not_belong(
    tmp_path,
) -> None:
    project = tmp_path / "site"
    sibling = tmp_path / "site-old"
    project.mkdir()
    sibling.mkdir()
    props = {
        "FragmentPath": GENERATED,
        "WorkingDirectory": f"!{sibling}",
        "ExecStart": _exec_start(f"/usr/bin/node {sibling}/serve.mjs"),
    }
    assert unit_belongs_to("b.service", project, properties=_reader(props)) is False


def test_a_command_path_behind_a_locked_folder_is_no_evidence(tmp_path) -> None:
    """review-code 2026-10-08 L05-M2. `Path.is_file()` re-raises `EACCES` on
    Python 3.13 (`docs/claude/traps.md`, the pathlib trap), and this function
    runs inside the poll's classification, where an escaping exception is
    swallowed and the tick's statuses are lost — every second, since nothing
    is cached on an exception. A file we cannot see proves nothing, so the
    token anchors nothing.

    Dies on removing the guard around `is_file()`.
    """
    locked = tmp_path / "locked"
    locked.mkdir()
    props = {
        "FragmentPath": GENERATED,
        "WorkingDirectory": "!/home/ants",
        "ExecStart": _exec_start(f"/usr/bin/python3 {locked}/serve.py"),
    }
    locked.chmod(0)
    try:
        if os.access(locked, os.X_OK):
            pytest.skip("running with privileges that ignore the mode bits")
        assert (
            unit_belongs_to("a.service", tmp_path, properties=_reader(props)) is False
        )
    finally:
        locked.chmod(0o700)


def test_an_unreadable_unit_answers_none_rather_than_a_verdict(tmp_path) -> None:
    def broken(unit: str, names: object, timeout: float) -> dict[str, str]:
        raise OSError("systemctl failed")

    assert unit_belongs_to("a.service", tmp_path, properties=broken) is None
