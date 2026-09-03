"""Socket-table inspection: the only place that knows how ports are looked at.

Core module — no Qt at all, not even QtCore (`docs/standards/coding.md § O1`).
Contract: `docs/specs/LWSM-1005-vertical-slice.md § 4.2`.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

import psutil


def _answers_localhost(ip: str) -> bool:
    """Would a connection to `localhost` arrive on a socket bound to `ip`?

    Loopback (the whole 127/8 block, and `::1`) or a wildcard, which accepts
    on every interface including loopback. A LAN address answers the machine's
    own name and not `localhost`, which is the URL Open builds (LWSM-1232).

    An address the stdlib cannot parse answers False. That direction is the
    conservative one for the caller that matters: the row reads `stopped`
    rather than offering an Open that reaches nothing.
    """
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    # `::ffff:127.0.0.1` is a v6 object whose loopback test is False, because
    # `::1` is the v6 loopback. The embedded v4 address is what it answers on.
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        address = mapped
    return address.is_loopback or address.is_unspecified


class ProbeError(Exception):
    """The socket table could not be read.

    One exception type for the poll loop to handle, so a partial or failed
    read never reaches a caller looking like an empty one (INV-4b).
    """


@dataclass(frozen=True)
class PortSnapshot:
    """One socket-table reading: every listening TCP port, and who holds it.

    ADR-0004 names two questions this must answer -- *what holds the effective
    port?* as well as *is anything listening?* -- and only the second was ever
    implemented, which is what made `RowView.managed` untrue (LWSM-1167).

    `holders` is deliberately PARTIAL, and its gaps are load-bearing.
    `psutil.net_connections` reports no pid for a socket owned by another user
    unless we are root, so a port can be in `listening` and absent from
    `holders`. ADR-0004 makes that the safe direction: a holder we cannot name
    is not ours, so the project reads as not-managed rather than as managed on
    a stranger's evidence.
    """

    # EVERY listening port, on any address. That is the right answer for
    # "can this port be bound?", which is what the supervisor's pre-flight
    # asks: a LAN-only listener still takes the port from a server that wants
    # to bind the wildcard.
    listening: frozenset[int]
    # Defaulted so every existing fake probe keeps constructing, and so the
    # default is "we do not know who holds this" rather than a claim.
    holders: Mapping[int, int] = field(default_factory=dict)
    # The subset of `listening` that a connection to `localhost` would reach.
    # `None` means this snapshot was built with no address information -- every
    # fake that predates LWSM-1232 -- and answers from `listening`, so a fake
    # stays exactly as expressive as it was.
    local: frozenset[int] | None = None

    def is_bound(self, port: int) -> bool:
        """Is anything listening on `port`, on any address?

        The binding question. NOT the question a project's status asks -- see
        `answers_localhost`, which the two were sharing wrongly (LWSM-1232).
        """
        return port in self.listening

    def answers_localhost(self, port: int) -> bool:
        """Would `http://localhost:<port>/` reach something?

        The status question, and the one Open is gated behind. A process on
        192.168.1.5:5000 made an unrelated project read `running` and offered
        an Open that reached nothing.
        """
        if self.local is None:
            return port in self.listening
        return port in self.local

    def holder(self, port: int) -> int | None:
        """The pid listening on `port`, or None.

        None covers two different facts on purpose -- nothing is listening, and
        something is listening that the kernel will not name for us. Neither is
        evidence that the port is ours, which is the only question the caller
        asks, so they need not be told apart here.
        """
        return self.holders.get(port)


class SupportsSnapshot(Protocol):
    """What `ProjectController` needs from a probe.

    Declared so the fakes injected by INV-3, INV-11, INV-12 and INV-16 are the
    contract rather than a duck-typing workaround the annotation contradicts.
    """

    def snapshot(self) -> PortSnapshot: ...


class PortProbe:
    """The real probe. One socket-table read per call, never one per project."""

    def snapshot(self) -> PortSnapshot:
        try:
            connections = psutil.net_connections(kind="tcp")
        except Exception as exc:
            # Deliberately wider than psutil.Error, which is NOT the whole
            # surface (LWSM-1069): psutil's own _pslinux.process_inet parses
            # /proc/net/tcp unguarded, so a malformed line raises a bare
            # RuntimeError, and hidepid, an LSM or a /proc-less container raise
            # OSError — neither of which subclasses psutil.Error. This method's
            # contract is one exception type for the poll loop to handle, so
            # anything the read raises becomes a ProbeError, with the original
            # kept as __cause__ so the log can name it.
            raise ProbeError(
                f"could not read the socket table: {type(exc).__name__}: {exc}"
            ) from exc

        # Inside the try as well, and not only the call: the comprehension
        # touches `conn.status` and `conn.laddr.port` on objects psutil built,
        # so malformed output raised a bare AttributeError from here — not the
        # ProbeError § 4.2 promises as this method's one exception type
        # (LWSM-1111). `run()`'s catch-all masked it; the contract is still the
        # contract, and it costs one line.
        #
        # The laddr guard is belt-and-braces: no listening entry has a falsy
        # laddr on this machine, but the field is typed as possibly empty and an
        # AttributeError mid-tick would take the poll down.
        try:
            listening: set[int] = set()
            local: set[int] = set()
            # Every pid seen holding a port on an address `localhost` reaches.
            # A set rather than one pid, because "two processes" and "one
            # process on two sockets" have to be told apart below.
            claimants: dict[int, set[int]] = {}
            for conn in connections:
                if conn.status != psutil.CONN_LISTEN or not conn.laddr:
                    continue
                port = conn.laddr.port
                listening.add(port)
                if not _answers_localhost(conn.laddr.ip):
                    continue
                local.add(port)
                if conn.pid is not None:
                    claimants.setdefault(port, set()).add(conn.pid)
            # A port normally carries two listening sockets, IPv4 and IPv6,
            # belonging to one process -- one pid, no ambiguity. Two DIFFERENT
            # pids on one port is possible on two loopback addresses, and there
            # nothing here can say which one `localhost` reaches. Taking the
            # first made the answer depend on psutil's undocumented return
            # order (LWSM-1232); no answer is ADR-0004's safe direction, the
            # same one already taken for a holder the kernel will not name.
            holders = {
                port: next(iter(pids))
                for port, pids in claimants.items()
                if len(pids) == 1
            }
            return PortSnapshot(frozenset(listening), holders, frozenset(local))
        except Exception as exc:
            raise ProbeError(
                f"could not read the socket table: {type(exc).__name__}: {exc}"
            ) from exc
