"""Shared real-browser fixtures for the result-list pins (slice S1).

Only a real browser runs AA's extraction script, so these pins load cleaned
page fixtures into headless Chrome and run the unchanged discovery perception
path over them. A machine without Chrome or Selenium skips them cleanly.

The driver is located in two tries: Selenium's default lookup, then Selenium
Manager with the driver on ``PATH`` ignored. The second try exists because a
stale ``chromedriver`` on ``PATH`` (one major version behind the browser) makes
the first fail on an otherwise working machine.
"""

from __future__ import annotations

import http.server
import socketserver
import threading
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _options():
    from selenium.webdriver.chrome.options import Options

    opts = Options()
    for arg in (
        "--headless=new",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--window-size=1280,900",
        "--blink-settings=imagesEnabled=false",
    ):
        opts.add_argument(arg)
    return opts


def _start_chrome():
    from selenium import webdriver

    try:
        return webdriver.Chrome(options=_options())
    except Exception as first:  # noqa: BLE001 - try the managed driver next
        try:
            from selenium.webdriver.chrome.service import Service
            from selenium.webdriver.common.selenium_manager import SeleniumManager

            paths = SeleniumManager().binary_paths(
                ["--browser", "chrome", "--skip-driver-in-path"]
            )
            return webdriver.Chrome(
                service=Service(executable_path=paths["driver_path"]),
                options=_options(),
            )
        except Exception as second:  # noqa: BLE001
            pytest.skip(f"Chrome not available ({first!r}; {second!r})")


@pytest.fixture(scope="module")
def chrome():
    try:
        import selenium  # noqa: F401
    except ImportError:
        pytest.skip("Selenium not installed")
    driver = _start_chrome()
    yield driver
    try:
        driver.quit()
    except Exception:  # noqa: BLE001
        pass


class _Pages:
    def __init__(self) -> None:
        self.pages: dict[str, bytes] = {}


@pytest.fixture(scope="module")
def page_server():
    """Serve in-memory pages and the fixture directory on 127.0.0.1."""
    store = _Pages()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - stdlib name
            path = self.path.split("?", 1)[0]
            body = store.pages.get(path)
            if body is None:
                candidate = FIXTURE_DIR / path.lstrip("/")
                if candidate.is_file() and candidate.parent == FIXTURE_DIR:
                    body = candidate.read_bytes()
            if body is None:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    base = f"http://{host}:{port}"

    def load(driver, path: str, html: str | None = None) -> None:
        if html is not None:
            store.pages[path] = html.encode("utf-8")
        driver.get(base + path)

    yield load
    server.shutdown()
    thread.join(timeout=5)
