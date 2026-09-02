"""`appearance.high_contrast` — the desktop's contrast preference (LWSM-1244).

Core and Qt-free, so every test here runs with no display and no
`QApplication`. The subprocess is injected rather than run: the answer must
not depend on whether the machine running the suite happens to have a settings
portal, which is the ambient dependency `conftest.py` pins `XDG_SESSION_TYPE`
to keep out.

The reply bodies below are copied from a real `dbus-send --print-reply`
against this machine's portal on 2026-09-02, not invented, because the parse
is the thing under test.
"""

from __future__ import annotations

import subprocess

import pytest

from lwsm import appearance

# Measured. The value nests in two variants, which is why the parse looks for
# `uint32` by name instead of taking a fixed field.
REPLY_NO_PREFERENCE = (
    b"method return time=1788356542.172474 sender=:1.37 -> "
    b"destination=:1.4579 serial=7021 reply_serial=2\n"
    b"   variant       variant          uint32 0\n"
)
REPLY_HIGH_CONTRAST = REPLY_NO_PREFERENCE.replace(b"uint32 0", b"uint32 1")


def fake_run(stdout=b"", returncode=0, stderr=b"", record=None):
    """A `subprocess.run` that answers without spawning anything."""

    def run(argv, **kwargs):
        if record is not None:
            record.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, returncode, stdout, stderr)

    return run


def present(_name: str) -> str:
    return "/usr/bin/dbus-send"


def absent(_name: str) -> None:
    return None


def test_a_high_contrast_desktop_is_reported_as_one() -> None:
    assert (
        appearance.high_contrast(run=fake_run(REPLY_HIGH_CONTRAST), which=present)
        is True
    )


def test_no_stated_preference_is_not_a_preference() -> None:
    """The portal's own 0, which is what an ordinary desktop answers."""
    assert (
        appearance.high_contrast(run=fake_run(REPLY_NO_PREFERENCE), which=present)
        is False
    )


def test_a_value_this_build_does_not_know_is_not_read_as_high_contrast() -> None:
    """A third contrast level added to the spec later must not silently mean
    yes here. Only the documented 1 does."""
    reply = REPLY_NO_PREFERENCE.replace(b"uint32 0", b"uint32 7")
    assert appearance.high_contrast(run=fake_run(reply), which=present) is False


def test_the_portal_is_asked_with_an_argument_vector_and_a_bound() -> None:
    """`coding.md § O4`: a vector, never a shell string — the namespace and key
    reach `dbus-send` as separate arguments, so neither can be read as syntax.
    And the call is bounded, because it runs on the GUI thread."""
    calls: list[tuple] = []
    appearance.high_contrast(
        run=fake_run(REPLY_NO_PREFERENCE, record=calls), which=present
    )

    ((argv, kwargs),) = calls
    assert isinstance(argv, list)
    assert argv[0] == "dbus-send"
    assert f"string:{appearance.PORTAL_NAMESPACE}" in argv
    assert f"string:{appearance.PORTAL_CONTRAST_KEY}" in argv
    assert kwargs["timeout"] == appearance.DBUS_TIMEOUT_S


def test_a_desktop_without_dbus_send_is_asked_nothing_at_all() -> None:
    """Not merely False: the subprocess must not be attempted, because the
    missing tool is the answer and a spawn that fails costs the GUI thread the
    same wait as one that succeeds."""

    def run(argv, **kwargs):
        raise AssertionError("dbus-send was invoked despite being absent")

    assert appearance.high_contrast(run=run, which=absent) is False


@pytest.mark.parametrize(
    "boom",
    [
        subprocess.TimeoutExpired(cmd="dbus-send", timeout=3.0),
        OSError("no session bus"),
        ValueError("bad argument"),
    ],
    ids=["timeout", "oserror", "valueerror"],
)
def test_a_failed_call_reports_no_preference_rather_than_raising(boom) -> None:
    """This runs while the window is being built. A traceback out of a startup
    path costs the user the app; not knowing their contrast preference costs
    them one menu click."""

    def run(argv, **kwargs):
        raise boom

    assert appearance.high_contrast(run=run, which=present) is False


def test_a_portal_that_declines_is_not_read_as_high_contrast() -> None:
    """Every desktop with no settings portal answers this way, so it is the
    ordinary case rather than an error."""
    assert (
        appearance.high_contrast(
            run=fake_run(b"", returncode=1, stderr=b"ServiceUnknown"),
            which=present,
        )
        is False
    )


def test_a_reply_carrying_no_number_is_not_read_as_high_contrast() -> None:
    """A success status is not a parsed answer. `dbus-send` has been measured
    on this project exiting 0 for a call that did nothing at all (LWSM-1170),
    so the value has to be found rather than assumed present."""
    assert (
        appearance.high_contrast(
            run=fake_run(b"method return time=1 sender=:1.1\n"), which=present
        )
        is False
    )
