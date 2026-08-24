"""Socket-table inspection: the only place that knows how ports are looked at.

Core module — no Qt at all, not even QtCore (`docs/standards/coding.md § O1`).
Contract: `docs/specs/LWSM-1005-vertical-slice.md § 4.2`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

import psutil


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

    listening: frozenset[int]
    # Defaulted so every existing fake probe keeps constructing, and so the
    # default is "we do not know who holds this" rather than a claim.
    holders: Mapping[int, int] = field(default_factory=dict)

    def is_bound(self, port: int) -> bool:
        return port in self.listening

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
            holders: dict[int, int] = {}
            for conn in connections:
                if conn.status != psutil.CONN_LISTEN or not conn.laddr:
                    continue
                port = conn.laddr.port
                listening.add(port)
                if conn.pid is not None:
                    # One port can carry two listening sockets -- an IPv4 and an
                    # IPv6 -- and in practice both belong to the same process.
                    # First one wins rather than last, so the answer does not
                    # depend on the order psutil happens to return them in.
                    holders.setdefault(port, conn.pid)
            return PortSnapshot(frozenset(listening), holders)
        except Exception as exc:
            raise ProbeError(
                f"could not read the socket table: {type(exc).__name__}: {exc}"
            ) from exc
