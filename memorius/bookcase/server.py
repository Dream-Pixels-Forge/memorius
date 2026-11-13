"""Loopback static server for the bookcase page.

Serves the package's ``bookcase/`` directory with the CSP from
:mod:`memorius.bookcase.csp`, no directory listing, and a bounded worker
pool so a burst of connections cannot exhaust threads.
"""

from __future__ import annotations

import concurrent.futures
import http.server
from functools import partial
from pathlib import Path

from .csp import SECURITY_HEADERS


class BookcaseRequestHandler(http.server.SimpleHTTPRequestHandler):
    """Static handler: security headers on every response, no listings."""

    def end_headers(self) -> None:
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        super().end_headers()

    def list_directory(self, path):
        self.send_error(403, "Directory listing disabled")


class BoundedThreadingHTTPServer(http.server.ThreadingHTTPServer):
    """Thread-per-connection with a hard cap on concurrent workers."""

    daemon_threads = True
    request_queue_size = 50
    max_workers = 50

    def __init__(self, *args, **kwargs):
        self._thread_pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=self.max_workers, thread_name_prefix="bookcase-static"
        )
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        self._thread_pool.submit(super().process_request, request, client_address)

    def server_close(self):
        self._thread_pool.shutdown(wait=False)
        super().server_close()


def serve(directory: str | Path, port: int) -> BoundedThreadingHTTPServer:
    """Bind (not start) the bookcase server on loopback. Port 0 picks one."""
    handler = partial(BookcaseRequestHandler, directory=str(directory))
    return BoundedThreadingHTTPServer(("127.0.0.1", port), handler)
