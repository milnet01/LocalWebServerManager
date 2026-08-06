"""LWSM-1005 INV-9, INV-3b — the probe reports what is actually listening.

Ports come from binding 0 and asking the socket, never a literal
(`docs/standards/testing.md § T3`), and every socket is closed in teardown
(`§ T5`).
"""

from __future__ import annotations

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
