"""LWSM-1005 INV-9, INV-3b — the probe reports what is actually listening.

Ports come from binding 0 and asking the socket, never a literal
(`docs/standards/testing.md § T3`), and every socket is closed in teardown
(`§ T5`).
"""

from __future__ import annotations

import os
import socket
from collections.abc import Iterator

import psutil
import pytest

from lwsm.ports import PortProbe, ProbeError


@pytest.fixture
def listening_socket() -> Iterator[tuple[socket.socket, int]]:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    try:
        yield sock, sock.getsockname()[1]
    finally:
        sock.close()


@pytest.mark.integration
def test_snapshot_follows_a_real_socket(
    listening_socket: tuple[socket.socket, int],
) -> None:
    sock, port = listening_socket
    probe = PortProbe()

    assert probe.snapshot().is_bound(port), "a listening socket must be seen"

    sock.close()
    assert not probe.snapshot().is_bound(port), "a closed socket must not be seen"


@pytest.mark.integration
def test_a_connected_socket_is_not_listening(
    listening_socket: tuple[socket.socket, int],
) -> None:
    """The status filter is what stops an outbound connection's ephemeral port
    reading as a running server."""
    server, port = listening_socket
    client = socket.create_connection(("127.0.0.1", port))
    accepted, _ = server.accept()
    try:
        ephemeral = client.getsockname()[1]
        assert not PortProbe().snapshot().is_bound(ephemeral)
    finally:
        accepted.close()
        client.close()


def test_one_net_connections_call_per_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def counted(**kwargs: object) -> list:
        calls.append(kwargs)
        return []

    monkeypatch.setattr(psutil, "net_connections", counted)
    PortProbe().snapshot()

    assert len(calls) == 1, "one read per snapshot, never one per address family"


class FakeConn:
    """One row of what `psutil.net_connections` returns."""

    def __init__(self, status, laddr, pid=None) -> None:
        self.status = status
        self.laddr = laddr
        self.pid = pid


# The IPv4 wildcard, named once. Ruff's S104 fires on the literal, which is
# right where something BINDS to it and wrong here: these fixtures describe
# what psutil REPORTED, and nothing in this file opens a socket.
WILDCARD_V4 = "0.0.0.0"  # noqa: S104


class FakeAddr:
    def __init__(self, port: int, ip: str = "127.0.0.1") -> None:
        self.port = port
        self.ip = ip


def test_only_listening_sockets_with_an_address_are_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both of `snapshot()`'s filters were untested (LWSM-1111).

    Dropping `and conn.laddr` passed the **entire** suite; dropping the
    `CONN_LISTEN` filter passed everything except one `integration` test — so
    under `--fast`, which is what runs before most pushes, neither was covered
    at all. One fake connection list closes both, with no socket bound.
    """
    monkeypatch.setattr(
        psutil,
        "net_connections",
        lambda **_: [
            FakeConn(psutil.CONN_LISTEN, FakeAddr(5005)),
            # Established, not listening: a browser talking to someone else's
            # server must not make that port read as one of ours.
            FakeConn(psutil.CONN_ESTABLISHED, FakeAddr(6006)),
            # Listening but with no local address — the field is typed as
            # possibly empty, and `.port` on it would take the poll down.
            FakeConn(psutil.CONN_LISTEN, None),
        ],
    )

    snapshot = PortProbe().snapshot()

    assert snapshot.listening == frozenset({5005})


def test_malformed_psutil_output_is_still_a_probe_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§ 4.2 promises ONE exception type out of this method.

    The comprehension sat outside the `try`, so a row whose `laddr` is not an
    address raised a bare `AttributeError` from `snapshot()` rather than a
    `ProbeError` (LWSM-1111). `_SnapshotTask.run()`'s catch-all mitigated it;
    the contract is still the contract.
    """
    monkeypatch.setattr(
        psutil,
        "net_connections",
        lambda **_: [FakeConn(psutil.CONN_LISTEN, "not-an-address")],
    )

    with pytest.raises(ProbeError):
        PortProbe().snapshot()


def test_psutil_error_becomes_a_probe_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(**_: object) -> list:
        # AccessDenied subclasses psutil.Error, so it needs no separate clause.
        raise psutil.AccessDenied()

    monkeypatch.setattr(psutil, "net_connections", denied)
    with pytest.raises(ProbeError):
        PortProbe().snapshot()


# LWSM-1069: psutil.Error is NOT the whole surface. psutil's own
# _pslinux.process_inet parses /proc/net/tcp unguarded, so a malformed line
# raises a bare RuntimeError; hidepid, an LSM or a /proc-less container raise
# OSError. Neither subclasses psutil.Error, so both used to escape snapshot()
# as themselves and reach a poll loop that catches only ProbeError.
@pytest.mark.parametrize(
    "raised",
    [
        RuntimeError("malformed /proc/net/tcp line"),
        OSError("/proc is not mounted"),
        ValueError("invalid literal for int()"),
    ],
    ids=["runtime", "os", "value"],
)
def test_any_read_failure_becomes_a_probe_error(
    monkeypatch: pytest.MonkeyPatch, raised: Exception
) -> None:
    assert not isinstance(raised, psutil.Error), "the point is that it is not one"

    def exploding(**_: object) -> list:
        raise raised

    monkeypatch.setattr(psutil, "net_connections", exploding)
    with pytest.raises(ProbeError) as caught:
        PortProbe().snapshot()

    # The original survives as the cause, so the app log can name what really
    # went wrong rather than only that the read failed.
    assert caught.value.__cause__ is raised


# --- LWSM-1167: the snapshot names who holds each port ------------------------


@pytest.mark.integration
def test_the_real_socket_table_names_our_own_pid_for_a_port_we_bind(
    listening_socket: tuple[socket.socket, int],
) -> None:
    """The holder plumbing, against the kernel rather than against a fake.

    Every other holder test here builds `PortSnapshot` from fake connection
    rows, so the whole mechanism could be wired end to end through fakes and
    still be wrong about what `psutil.net_connections` actually returns for a
    real socket. This is the one test that would notice, and LWSM-1167's own
    bullet asks for it by name.
    """
    _sock, port = listening_socket

    snapshot = PortProbe().snapshot()

    assert snapshot.is_bound(port)
    assert snapshot.holder(port) == os.getpid()


def test_a_listening_socket_with_no_pid_is_bound_but_has_no_holder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """psutil reports no pid for another user's socket unless we are root.

    The gap must stay a gap. Reporting the port as bound while admitting we
    cannot name its holder is what lets the managed test refuse it; inventing a
    holder, or dropping the port from `listening`, would each be a claim the
    kernel did not make.
    """
    monkeypatch.setattr(
        psutil,
        "net_connections",
        lambda **_: [FakeConn(psutil.CONN_LISTEN, FakeAddr(5005), pid=None)],
    )

    snapshot = PortProbe().snapshot()

    assert snapshot.is_bound(5005)
    assert snapshot.holder(5005) is None


def test_a_dual_stack_pair_reports_the_one_process_that_holds_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A port normally carries two listening sockets, IPv4 and IPv6.

    They belong to ONE process, so the two rows carry one pid and the answer
    cannot depend on the order psutil returns them in -- which is not a
    documented order.
    """
    monkeypatch.setattr(
        psutil,
        "net_connections",
        lambda **_: [
            FakeConn(psutil.CONN_LISTEN, FakeAddr(5005, WILDCARD_V4), pid=111),
            FakeConn(psutil.CONN_LISTEN, FakeAddr(5005, "::"), pid=111),
        ],
    )

    assert PortProbe().snapshot().holder(5005) == 111


def test_two_processes_on_one_port_leave_it_without_a_holder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """This replaces a test that pinned first-one-wins across two pids.

    That test's docstring described the dual-stack pair above, and its fixture
    gave the two rows DIFFERENT pids -- which is a different situation and one
    the kernel does allow, on two loopback addresses. First-one-wins there
    makes the answer depend on psutil's return order, which is exactly the
    order-dependence the docstring said it was preventing (LWSM-1232).

    None is the safe direction ADR-0004 already takes for a holder the kernel
    will not name: we cannot say which of the two `localhost` reaches, so we
    do not say.
    """
    monkeypatch.setattr(
        psutil,
        "net_connections",
        lambda **_: [
            FakeConn(psutil.CONN_LISTEN, FakeAddr(5005, "127.0.0.1"), pid=111),
            FakeConn(psutil.CONN_LISTEN, FakeAddr(5005, "::1"), pid=222),
        ],
    )

    snapshot = PortProbe().snapshot()
    assert snapshot.is_bound(5005)
    assert snapshot.holder(5005) is None


def test_a_listener_on_a_lan_address_is_bound_but_does_not_answer_localhost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two questions, and one answer served both wrongly (LWSM-1232).

    A process on 192.168.1.5:5005 does not answer `http://localhost:5005/`,
    so an unrelated project reading `running` from it offers an Open that
    reaches nothing. But the port IS taken as far as binding goes, so the
    supervisor's pre-flight must still see it -- which is why `listening`
    keeps every address and the localhost question is asked separately.
    """
    monkeypatch.setattr(
        psutil,
        "net_connections",
        lambda **_: [
            FakeConn(psutil.CONN_LISTEN, FakeAddr(5005, "192.168.1.5"), pid=111),
        ],
    )

    snapshot = PortProbe().snapshot()
    assert snapshot.is_bound(5005), "the port cannot be bound again"
    assert not snapshot.answers_localhost(5005)
    assert snapshot.holder(5005) is None, "not reachable, so not ours"


@pytest.mark.parametrize("ip", ["127.0.0.1", "127.0.1.9", WILDCARD_V4, "::", "::1"])
def test_a_loopback_or_wildcard_listener_answers_localhost(
    monkeypatch: pytest.MonkeyPatch, ip: str
) -> None:
    """Every address `localhost` can arrive on, including the whole 127/8
    block and both wildcards. One fixture per member, because the code
    branches on a closed set."""
    monkeypatch.setattr(
        psutil,
        "net_connections",
        lambda **_: [FakeConn(psutil.CONN_LISTEN, FakeAddr(5005, ip), pid=111)],
    )

    assert PortProbe().snapshot().answers_localhost(5005)


def test_a_snapshot_carrying_no_addresses_answers_the_old_way() -> None:
    """`local` defaults to None, which means "this snapshot was built without
    address information" -- every test fake that predates LWSM-1232. It answers
    from `listening`, so a fake stays as expressive as it was."""
    from lwsm.ports import PortSnapshot

    assert PortSnapshot(frozenset({5005})).answers_localhost(5005)
    assert not PortSnapshot(frozenset({5005})).answers_localhost(6006)


def test_a_holder_is_not_reported_for_a_port_nobody_holds() -> None:
    from lwsm.ports import PortSnapshot

    assert PortSnapshot(frozenset({5005})).holder(5005) is None
