"""Asking a running site for one page: the only place this app makes a request.

Core module — no Qt at all, not even QtCore (`docs/standards/coding-overrides.md § O1`).
Contract: `docs/specs/LWSM-1034-health-check.md § 4.1`.
"""

from __future__ import annotations

import http.client
import socket
import threading

from lwsm import __version__

# Per socket operation: `http.client` applies it to the connect and to each
# read, so a server trickling its status line resets it with every byte.
HEALTH_TIMEOUT_SECONDS = 2.0
# For the whole call. Without it four trickling servers held all four health
# threads for as long as they liked (review-code 2026-10-08 L02-L5).
HEALTH_DEADLINE_SECONDS = 5.0

_USER_AGENT = f"LocalWebServerManager/{__version__} health check"


def ask(
    port: int,
    path: str,
    *,
    timeout: float = HEALTH_TIMEOUT_SECONDS,
    deadline: float = HEALTH_DEADLINE_SECONDS,
) -> int | None:
    """GET `path` from localhost:`port`. The status code, or None for no answer.

    `http.client`, not `urllib`: it follows no redirect, so a 302 is reported
    rather than obeyed and the request cannot leave `localhost:<port>`; and a
    4xx or 5xx is an answer, where `urlopen` raises. `path` is the request
    target only, so it cannot change the host — the registry has already
    refused anything not shaped like a path (`registry.health_path_ok`).

    None covers a refused or reset connection, a timeout (all `OSError`), a
    reply that is not HTTP (`HTTPException`) and a call still unanswered at
    `deadline`, whose socket is shut down so the blocked read returns. Anything
    else is a defect and propagates, so the caller can log it.
    """
    connection = http.client.HTTPConnection("localhost", port, timeout=timeout)
    cutoff = threading.Timer(deadline, _shut_down, args=(connection,))
    cutoff.daemon = True
    cutoff.start()
    try:
        connection.request(
            "GET", path, headers={"User-Agent": _USER_AGENT, "Connection": "close"}
        )
        # The status line is the answer; the body is never read.
        return connection.getresponse().status
    except (OSError, http.client.HTTPException):
        return None
    finally:
        cutoff.cancel()
        connection.close()


def _shut_down(connection: http.client.HTTPConnection) -> None:
    """Unblock a read past the deadline. `shutdown`, not `close`: a read
    blocked in another thread returns at once only on a shutdown."""
    sock = connection.sock
    if sock is None:
        return
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass  # already closed or never connected: nothing is waiting
