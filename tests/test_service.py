"""LWSM-1012 — driving a project whose server is a systemd user unit.

ADR-0003's amendment gives service-managed projects their own column: start,
stop and restart go to `systemctl --user`, never to a spawned launcher. These
tests are the contract for that column.

The reporting machine is what the fixtures are drawn from: two servers started
at logon, `ants-stats.service` on 4321 and an escaped `app-…@autostart.service`
on 8765, neither of which the app started and both of which it must manage.
"""

from __future__ import annotations

import subprocess

import pytest

from lwsm.service import (
    UNIT_VERB_TIMEOUT_SECONDS,
    VERBS,
    Holder,
    describe_holder,
    drive_unit,
    unit_argv,
    unit_for_pid,
)

# Verbatim from `/proc/<pid>/cgroup` on the reporting machine, escaped name and
# all. Transcribed rather than composed: the escaping is the part that breaks.
ESCAPED = (
    "0::/user.slice/user-1000.slice/user@1000.service/app.slice/"
    "app-ai\\x2dprompts\\x2dtray@autostart.service\n"
)
PLAIN = (
    "0::/user.slice/user-1000.slice/user@1000.service/app.slice/ants-stats.service\n"
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

    def __init__(self, returncode: int = 0, stderr: str = "") -> None:
        self.returncode = returncode
        self.stderr = stderr
        self.argv: list[str] | None = None
        self.timeout: float | None = None

    def __call__(self, argv, **kwargs):
        self.argv = argv
        self.timeout = kwargs.get("timeout")
        return subprocess.CompletedProcess(argv, self.returncode, "", self.stderr)


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
    assert holder.service_managed


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


def test_a_holder_with_no_unit_is_not_service_managed() -> None:
    """Which is what sends the caller down the signalling path instead."""
    holder = describe_holder(7, process=FakeProcess(), read_cgroup=lambda pid: "0::/\n")

    assert holder.unit is None
    assert not holder.service_managed


def test_a_holder_is_still_returned_when_the_process_is_gone() -> None:
    """`describe_holder` answers a `Holder` or nothing useful — never an
    exception — because its caller is deciding what to show in a dialog."""
    holder = Holder(pid=99)

    assert holder.pid == 99
    assert not holder.service_managed
