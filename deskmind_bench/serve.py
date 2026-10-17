"""A task's pages over http, for the length of one run.

A browser driven by script does not open a local page. DeskMind Hands loads a staged page into a Safari window of the
run's own with AppleScript ``set URL``, and Safari answers that with success for a ``file://`` page but never loads it
(checked live, 10-17). ``open -a Safari <file>`` is no way round it: it opens the file in a tab of the front window,
which can be the user's (hands#44, deskmind#73). So a task that shows a page in a browser serves it over http instead.

A task names the folder of its workspace to serve (``serve: "$WS"``). The runner starts the server before staging
and stops it when the run ends, however it ends -- the way it constructs and closes the dynamic tasks' injector
(``deskmind_bench.dyn.inject``)::

    server = serve_task(task, workspace)        # None for a task that serves nothing
    env = server.env if server else {}          # {"SERVE_URL": "http://127.0.0.1:<port>"} for the staging commands
    try:
        ...                                     # stage, run
    finally:
        if server:
            server.close()                      # the server stops and its port is free again

Staging reads the address as ``$SERVE_URL``. A task can fall back to its file where a runner serves nothing:
``open -a Safari "${SERVE_URL:-$WS}/page.html"``.

The server listens on 127.0.0.1 only, on a port the system picks as free, and serves files from the named folder and
nothing outside it. It runs in a daemon thread of the runner's own process, like the gym's (hands/tools/gym/server.py),
so no process outlives the run. Nothing here is graded and nothing is read back.
"""

from __future__ import annotations

import os
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

#: The variable staging commands read the server's address from: scheme, host and port, no trailing slash.
URL_VAR = "SERVE_URL"


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):   # the run's trace says what matters; a request log on stderr does not
        pass

    def end_headers(self):
        # A page is fixture data: what the run sees is the workspace's copy, never one a browser kept from an earlier run
        # on the same port.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


class PageServer:
    """Serves the folder ``root`` at http://127.0.0.1:<free port>/ until ``close()``."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise ValueError(f"nothing to serve: {self.root} is not a folder")
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(_Quiet, directory=str(self.root)))
        self._httpd.daemon_threads = True
        self.port: int = self._httpd.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self._httpd.serve_forever, name=f"serve-{self.port}", daemon=True)
        self._thread.start()
        self._closed = False

    @property
    def env(self) -> dict[str, str]:
        """What the staging commands need to reach the server."""
        return {URL_VAR: self.url}

    def close(self) -> None:
        """Stop serving and free the port. Safe to call more than once."""
        if self._closed:
            return
        self._closed = True
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)

    def __enter__(self) -> "PageServer":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def served_root(serve: str, ws: str | Path) -> Path:
    """The folder a task's ``serve`` names, which must be the workspace or a folder inside it (the sandbox rule)."""
    ws = Path(ws).resolve()
    raw = serve.replace("${WS}", str(ws)).replace("$WS", str(ws))
    root = Path(raw) if os.path.isabs(raw) else ws / raw
    root = root.resolve()
    if root != ws and ws not in root.parents:
        raise ValueError(f"serve must name the workspace or a folder in it, not {serve!r}")
    return root


def serve_task(task, ws: str | Path) -> PageServer | None:
    """The server for ``task``'s ``serve`` folder in the workspace ``ws``, started; None when the task serves nothing."""
    serve = getattr(task, "serve", None)
    if not serve:
        return None
    return PageServer(served_root(serve, ws))
