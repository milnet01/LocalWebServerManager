"""LWSM-1034 INV-1, INV-2 — `health.ask` reports what a real server answers.

Every server binds port 0 and is asked for what it got
(`docs/standards/testing-overrides.md § T3`), and each is shut down in teardown
(`§ T5`).
"""

from __future__ import annotations

import http.server
import socket
import threading
from collections.abc import Iterator

import pytest

from lwsm.health import ask


class _Server(http.server.ThreadingHTTPServer):
    """Records each request target, and answers it from `answers`."""

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Recorder)
        self.seen: list[str] = []
        self.answers = {"/ok": 200, "/broken": 500, "/moved": 302}


class _Recorder(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        assert isinstance(self.server, _Server)
        self.server.seen.append(self.path)
        code = self.server.answers.get(self.path, 200)
        self.send_response(code)
        if code == 302:
            # Somewhere that answers nothing: a client that followed this would
            # report no answer instead of the 302.
            self.send_header("Location", "http://localhost:1/")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture
def server() -> Iterator[_Server]:
    httpd = _Server()
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _port(httpd: _Server) -> int:
    return httpd.server_address[1]


@pytest.mark.integration
@pytest.mark.parametrize(("page", "code"), [("/ok", 200), ("/broken", 500)])
def test_the_status_code_is_what_the_server_sent(server, page, code) -> None:
    """INV-1 of LWSM-1034: a 500 is an answer, not an error."""
    assert ask(_port(server), page) == code


@pytest.mark.integration
def test_a_redirect_is_reported_and_not_followed(server) -> None:
    """INV-1 of LWSM-1034: following the 302 would reach port 1 and report None."""
    assert ask(_port(server), "/moved") == 302
    assert server.seen == ["/moved"]


@pytest.mark.integration
def test_a_closed_port_is_no_answer() -> None:
    """INV-1 of LWSM-1034: a refused connection."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    assert ask(port, "/") is None


@pytest.fixture
def raw_server() -> Iterator[tuple[int, list[bytes]]]:
    """A socket server whose single reply is set by the test; None means silence."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    replies: list[bytes] = []
    held: list[socket.socket] = []
    done = threading.Event()

    def serve() -> None:
        try:
            conn, _ = sock.accept()
        except OSError:
            return
        held.append(conn)
        conn.recv(4096)
        if replies:
            conn.sendall(replies[0])
            conn.close()
        else:
            done.wait(5)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield sock.getsockname()[1], replies
    finally:
        done.set()
        for conn in held:
            conn.close()
        sock.close()
        thread.join(timeout=5)


@pytest.mark.integration
def test_a_server_that_never_replies_is_no_answer(raw_server) -> None:
    """INV-1 of LWSM-1034: a timeout is `OSError`, and caught."""
    port, _replies = raw_server
    assert ask(port, "/", timeout=0.2) is None


@pytest.mark.integration
def test_a_reply_that_is_not_http_is_no_answer(raw_server) -> None:
    """INV-1 of LWSM-1034: `BadStatusLine` is an `HTTPException`, and caught."""
    port, replies = raw_server
    replies.append(b"hello\r\n")
    assert ask(port, "/", timeout=2) is None


@pytest.mark.integration
def test_the_page_cannot_move_the_request_off_localhost(server) -> None:
    """INV-2 of LWSM-1034: built as a URL and parsed, this path would make
    `example.invalid` the host. As a request target it reaches the local
    server unchanged."""
    assert ask(_port(server), "@example.invalid/") == 200
    assert server.seen == ["@example.invalid/"]
