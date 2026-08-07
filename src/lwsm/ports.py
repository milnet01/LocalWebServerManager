"""Socket-table inspection: the only place that knows how ports are looked at.

Core module — no Qt at all, not even QtCore (`docs/standards/coding.md § O1`).
Contract: `docs/specs/LWSM-1005-vertical-slice.md § 4.2`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import psutil


class ProbeError(Exception):
    """The socket table could not be read.

    One exception type for the poll loop to handle, so a partial or failed
    read never reaches a caller looking like an empty one (INV-4b).
    """


@dataclass(frozen=True)
class PortSnapshot:
    """One socket-table reading: every TCP port something is listening on."""

    listening: frozenset[int]

    def is_bound(self, port: int) -> bool:
        return port in self.listening


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
            return PortSnapshot(
                frozenset(
                    conn.laddr.port
                    for conn in connections
                    if conn.status == psutil.CONN_LISTEN and conn.laddr
                )
            )
        except Exception as exc:
            raise ProbeError(
                f"could not read the socket table: {type(exc).__name__}: {exc}"
            ) from exc
