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
        # AccessDenied subclasses psutil.Error, which is the whole surface
        # PortProbe catches.
        raise psutil.AccessDenied()

    monkeypatch.setattr(psutil, "net_connections", denied)
    with pytest.raises(ProbeError):
        PortProbe().snapshot()
