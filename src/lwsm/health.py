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
# Interim replies skipped before the call gives up with no answer. Each read
# is still under the per-socket timeout, and the whole call under the deadline.
MAX_INTERIM_REPLIES = 10

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
    reply that is not HTTP (`HTTPException`), a server sending more than
    `MAX_INTERIM_REPLIES` interim replies, and a call still unanswered at
    `deadline`, whose socket is shut down so the blocked read returns. Anything
    else is a defect and propagates, so the caller can log it.
    """
    connection = http.client.HTTPConnection("localhost", port, timeout=timeout)
    fired = threading.Event()
    cutoff = threading.Timer(deadline, _shut_down, args=(connection, fired))
    cutoff.daemon = True
    cutoff.start()
    try:
        connection.connect()
        if fired.is_set():
            # The deadline passed during name lookup or connect, when there
            # was no socket yet to shut down (LWSM-1456).
            return None
        connection.request(
            "GET", path, headers={"User-Agent": _USER_AGENT, "Connection": "close"}
        )
        # The status line is the answer; the body is never read.
        return _final_status(connection.getresponse())
    except (OSError, http.client.HTTPException):
        return None
    finally:
        cutoff.cancel()
        connection.close()


def _final_status(response: http.client.HTTPResponse) -> int | None:
    """The first status that is not interim, read off the same stream.

    `http.client` skips only `100 Continue`, so a `103 Early Hints`
    (RFC 8297) would be reported as the answer (LWSM-1458). A 1xx has no
    body, so the next status line follows its headers at once; a new
    `HTTPResponse` over the same buffered reader parses it, since a second
    `makefile` would lose what the first has already buffered. 101 is left
    as the answer: it ends HTTP on the connection, so nothing follows it.

    Each interim reply hands its reader on (`fp = None`): a reply that is
    closed or collected closes its reader, and the next reply reads from it.
    """
    for _ in range(MAX_INTERIM_REPLIES):
        status = response.status
        if not 100 <= status < 200 or status == 101:
            return status
        stream = response.fp
        response.fp = None  # type: ignore[assignment]  # None: how the stdlib marks it closed
        response = http.client.HTTPResponse(_SameStream(stream), method="GET")  # type: ignore[arg-type]
        response.begin()
    return None


class _SameStream:
    """Hands `HTTPResponse` the reader it already has instead of a new one."""

    def __init__(self, stream: object) -> None:
        self._stream = stream

    def makefile(self, _mode: str) -> object:
        return self._stream


def _shut_down(connection: http.client.HTTPConnection, fired: threading.Event) -> None:
    """Unblock a read past the deadline. `shutdown`, not `close`: a read
    blocked in another thread returns at once only on a shutdown. `fired`
    tells `ask` the deadline passed, for a connect that had no socket yet."""
    fired.set()
    sock = connection.sock
    if sock is None:
        return
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass  # already closed or never connected: nothing is waiting
