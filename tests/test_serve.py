"""A task's page served over http for the length of a run (deskmind_bench/serve.py; hands#44, deskmind#73).

    python -m unittest tests.test_serve -v

No browser and no desktop: the staging command's address is expanded the way a runner's shell does it and fetched.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from deskmind_bench.serve import URL_VAR, PageServer, served_root, serve_task   # noqa: E402
from deskmind_bench.task import load_set, load_task                             # noqa: E402

G03 = REPO / "tasks" / "diag" / "G03-safari-extract.yaml"
#: A staging command that opens something in a browser: `open [-g] -a <browser> <what>` or `open [-g] -b <bundle> <what>`.
BROWSER_OPEN = re.compile(r'^\s*open\s+(?:-g\s+)?(?:-a\s+(?:"(?P<qa>[^"]+)"|(?P<a>\S+))|-b\s+(?P<b>\S+))\s+(?P<what>.+)$')
BROWSERS = {"safari", "google chrome", "chrome", "microsoft edge", "brave browser", "firefox", "arc",
            "com.apple.safari", "com.google.chrome", "com.microsoft.edgemac", "com.brave.browser",
            "org.mozilla.firefox", "company.thebrowser.browser"}


def all_tasks():
    for d in sorted((REPO / "tasks").iterdir()):
        if d.is_dir() and any(d.glob("*.yaml")):
            yield from load_set(REPO / "tasks", d.name)


def browser_opens(task):
    """(command, what it opens) for each staging command of `task` that opens something in a browser."""
    for cmd in task.stage:
        m = BROWSER_OPEN.match(cmd)
        if m and (m.group("qa") or m.group("a") or m.group("b") or "").lower() in BROWSERS:
            yield cmd, m.group("what").strip()


def _sh_expand(arg: str, ws: Path, env: dict[str, str]) -> str:
    """A staging command's argument as /bin/sh expands it in the workspace, as a runner does (no $SERVE_URL but `env`'s)."""
    base = {k: v for k, v in os.environ.items() if k != URL_VAR}
    return subprocess.run(["/bin/sh", "-c", f'printf "%s" "{arg}"'], capture_output=True, text=True, check=True,
                          cwd=ws, env={**base, "WS": str(ws), **env}).stdout


def port_free(port: int) -> bool:
    """Whether a new server could listen on `port` (as http.server's would: with SO_REUSEADDR, so the closed
    connections' TIME_WAIT does not count; a listener still open does)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
        return True


class G03Staging(unittest.TestCase):
    def setUp(self):
        self.task = load_task(G03)
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.ws = self.tmp / "ws"
        shutil.copytree(REPO / "fixtures" / self.task.fixture, self.ws)

    def test_serves_the_workspace(self):
        self.assertEqual(self.task.serve, "$WS")
        self.assertEqual(served_root(self.task.serve, self.ws), self.ws.resolve())

    def test_the_staged_page_is_the_served_one(self):
        (( _, what),) = list(browser_opens(self.task))
        with serve_task(self.task, self.ws) as server:
            url = _sh_expand(shlex.split(what)[0], self.ws, server.env)
            self.assertEqual(url, f"{server.url}/page.html")
            self.assertRegex(url, r"^http://127\.0\.0\.1:\d+/page\.html$")
            with urllib.request.urlopen(url, timeout=5) as r:
                self.assertEqual(r.read(), (self.ws / "page.html").read_bytes())

    def test_without_a_server_it_is_the_file(self):
        """A runner that does not read `serve` opens the file, as before."""
        (( _, what),) = list(browser_opens(self.task))
        self.assertEqual(_sh_expand(shlex.split(what)[0], self.ws, {}), f"{self.ws}/page.html")

    def test_goal_gold_and_sentinels_unchanged(self):
        t = self.task
        self.assertIn("inventory.csv", t.goal)
        self.assertEqual(t.sentinels, ["$WS/keep/reference.txt", "$WS/page.html"])
        self.assertEqual([c.name for c in t.checkpoints], ["any_row", "all_three", "sorted_by_stock"])
        self.assertEqual(t.checkpoints[2].check["file_text_equals"]["value"],
                         "编号,名称,库存\nSKU-9032,不锈钢法兰,17\nSKU-4417,密封垫圈,238\nSKU-1185,液压接头,460")


class EveryBrowserPage(unittest.TestCase):
    def test_no_task_stages_a_local_file_in_a_browser(self):
        """A page staged in a browser is served: Safari driven by script never loads a file:// page (hands#44)."""
        found = 0
        for task in all_tasks():
            for cmd, what in browser_opens(task):
                found += 1
                with self.subTest(task=task.id, cmd=cmd):
                    remote = re.match(r'^"?https?://', what) and "127.0.0.1" not in what and "localhost" not in what
                    if remote:
                        continue
                    self.assertIsNotNone(task.serve, "a local page in a browser needs `serve`")
                    self.assertIn(URL_VAR, what, "and its staging opens it at $SERVE_URL")
        self.assertGreaterEqual(found, 1)   # G03, at least: the check is not vacuous

    def test_other_tasks_serve_nothing(self):
        for task in all_tasks():
            if task.id != "G03-safari-extract":
                self.assertIsNone(serve_task(task, REPO), task.id)


class PageServerTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        (self.root / "page.html").write_text("<p>库存</p>", encoding="utf-8")

    def test_local_only_and_the_port_freed_on_close(self):
        server = PageServer(self.root)
        try:
            self.assertEqual(server._httpd.server_address[0], "127.0.0.1")
            self.assertFalse(port_free(server.port))
            with urllib.request.urlopen(f"{server.url}/page.html", timeout=5) as r:
                self.assertEqual(r.read().decode(), "<p>库存</p>")
                self.assertEqual(r.headers["Cache-Control"], "no-store")
        finally:
            server.close()
        server.close()   # twice is fine
        self.assertFalse(server._thread.is_alive())
        self.assertTrue(port_free(server.port))
        with self.assertRaises(urllib.error.URLError):
            urllib.request.urlopen(f"{server.url}/page.html", timeout=2)

    def test_two_runs_two_ports(self):
        with PageServer(self.root) as a, PageServer(self.root) as b:
            self.assertNotEqual(a.port, b.port)

    def test_nothing_outside_the_folder(self):
        (self.root / "site").mkdir()
        (self.root / "secret.txt").write_text("no")
        with PageServer(self.root / "site") as server:
            for path in ("/../secret.txt", "/%2e%2e/secret.txt"):
                with self.subTest(path=path), self.assertRaises(urllib.error.HTTPError) as e:
                    urllib.request.urlopen(f"{server.url}{path}", timeout=5)
                self.assertEqual(e.exception.code, 404)

    def test_serve_stays_in_the_workspace(self):
        ws = self.root
        (ws / "pages").mkdir()
        self.assertEqual(served_root("$WS/pages", ws), (ws / "pages").resolve())
        self.assertEqual(served_root("pages", ws), (ws / "pages").resolve())
        for bad in ("$WS/..", "/tmp", "../x", "$WS/pages/../.."):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                served_root(bad, ws)


if __name__ == "__main__":
    unittest.main()
