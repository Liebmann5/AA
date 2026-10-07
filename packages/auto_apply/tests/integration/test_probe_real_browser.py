"""Real-browser pins for the target probe and pane-aware scrolling (C2).

Only a real browser can pin JavaScript. Three pages, served locally:

    /clip    — a button clipped inside a short scroll pane, the page body
               under its viewport centre. Pre-fix the probe judged it
               clickable (an ancestor was on top) and the tool clicked the
               BACKGROUND and reported success. Measured on real Chrome
               after the call-2 fix: the pane scrolls, the click lands on
               the button, the window does not move.
    /columns — a left-column target far below the fold: the axis choice
               must be a vertical WHEEL, never the instant JS fallback.
    /shadow  — a button inside an OPEN shadow root: the probe's ancestor
               walk crosses via getRootNode().host.

Skipped cleanly without Selenium/Chrome, in the style of
tests/integration/test_form_filling.py.
"""
from __future__ import annotations

import http.server
import socketserver
import threading
from types import SimpleNamespace

import pytest

from auto_apply.adapters.secondary.navigation.page_advancer import VerifiedPageAdvancer
from auto_apply.domain.models.page_advance import UrlPageTemplate

_PAGES = {
    "/clip": (
        "<html><body style='margin:0'>"
        "<div id='pane' style='position:fixed;top:100px;left:100px;width:300px;"
        "height:80px;overflow:auto;background:#eee'>"
        "<div style='height:120px'></div>"
        "<button id='clipBtn' style='height:30px' "
        "onclick=\"window.__hit=(window.__hit||0)+1\">go</button>"
        "<div style='height:300px'></div></div>"
        "<div style='height:1600px'></div></body></html>"
    ),
    "/columns": (
        "<html><body style='margin:0'>"
        "<div style='position:absolute;left:0;top:0;width:200px;height:3000px;"
        "background:#eef'></div>"
        "<div style='margin-left:220px;height:3000px'></div>"
        "<button id='deep' style='position:absolute;left:20px;top:2500px'>go</button>"
        "</body></html>"
    ),
    "/shadow": (
        "<html><body><div id='host'></div><script>"
        "var r=document.getElementById('host').attachShadow({mode:'open'});"
        "var b=document.createElement('button');b.id='shbtn';b.textContent='go';"
        "b.onclick=function(){window.__sh=(window.__sh||0)+1;};"
        "r.appendChild(b);</script></body></html>"
    ),
    "/m": (
        "<html><body><div id='f'><a href='/j1'>J1</a></div>"
        "<button id='loadMoreBtn' onclick=\"var f=document.getElementById('f');"
        "for(var i=2;i<5;i++){var a=document.createElement('a');a.href='/j'+i;"
        "a.textContent='J'+i;f.appendChild(a);}\">x</button></body></html>"
    ),
    "/t": "<html><body><a href='/j1'>J1</a><br><a href='/j2'>J2</a></body></html>",
    "/w1": "<html><body><a href='/w-a'>Alpha</a><br><a href='/w-b'>Beta</a></body></html>",
    "/w2": "<html><body><a href='/w-c'>Gamma</a><br><a href='/w-d'>Delta</a></body></html>",
}


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path == "/w":
            path = "/w2" if "p=2" in query else "/w1"
        body = _PAGES.get(path)
        if body is None:
            self.send_error(404)
            return
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def probe_server_url():
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    yield f"http://{host}:{port}"
    server.shutdown()
    thread.join(timeout=5)


_CFG = {
    "enable_human_timing": False,
    "settle_min_s": 0.0,
    "settle_max_s": 0.0,
    "macro_pause_min_s": 0.0,
    "macro_pause_max_s": 0.0,
    "min_action_delay_ms": 0,
    "occlusion_guard": True,
    "navigation_retries": 1,
    "scroll_settle_timeout_s": 0.6,
    "infinite_scroll_settle_s": 0.5,
}


def _tool(driver):
    from auto_apply.adapters.secondary.browser.selenium_adapter import SeleniumAdapter
    from auto_apply.application.services.page_action.service import PageActionService

    registry = SimpleNamespace(get_all_effective_config=lambda: dict(_CFG))
    return PageActionService(browser=SeleniumAdapter(driver), registry=registry)


@pytest.mark.browser
class TestProbeOnRealChrome:
    @pytest.fixture(scope="class")
    def driver(self):
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
        except ImportError:
            pytest.skip("Selenium not installed")
        opts = Options()
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--window-size=1000,800")
        try:
            driver = webdriver.Chrome(options=opts)
        except Exception as exc:
            pytest.skip(f"Cannot create Chrome driver: {exc}")
        yield driver
        try:
            driver.quit()
        except Exception:
            pass

    def test_a_button_clipped_by_its_pane_is_scrolled_then_clicked(
        self, driver, probe_server_url
    ):
        """TEETH against the pre-fix probe (background misclick); GUARD for
        the committed fix: pane scrolls, click lands, window never moves."""
        driver.get(f"{probe_server_url}/clip")
        tool = _tool(driver)
        button = tool.find("css selector", "#clipBtn")
        assert button is not None

        result = tool.click(button)

        assert bool(result) is True, f"click refused: {result.reason}"
        assert driver.execute_script("return window.__hit || 0") == 1
        assert driver.execute_script(
            "return document.getElementById('pane').scrollTop"
        ) > 0
        assert driver.execute_script("return window.scrollY") == 0

    def test_a_left_column_target_scrolls_vertically_by_wheel(
        self, driver, probe_server_url
    ):
        """The G1 case on a real page: dx is already visible, so the wheel
        must be vertical and the rung must be 'wheel', never 'js-scroll'."""
        driver.get(f"{probe_server_url}/columns")
        tool = _tool(driver)
        button = tool.find("css selector", "#deep")
        assert button is not None

        result = tool.scroll_into_view(button)

        assert bool(result) is True, f"scroll failed: {result.reason}"
        assert result.rung == "wheel"
        assert driver.execute_script("return window.scrollY") > 0
        assert driver.execute_script("return window.scrollX") == 0

    def test_a_button_in_an_open_shadow_root_is_clicked(
        self, driver, probe_server_url
    ):
        """The probe's ancestor walk crosses an open shadow boundary via
        getRootNode().host; without that, the verdict is a false occlusion."""
        driver.get(f"{probe_server_url}/shadow")
        tool = _tool(driver)
        button = driver.execute_script(
            "return document.getElementById('host').shadowRoot"
            ".querySelector('button')"
        )
        assert button is not None

        result = tool.click(button)

        assert bool(result) is True, f"click refused: {result.reason}"
        assert driver.execute_script("return window.__sh || 0") == 1


@pytest.mark.browser
class TestAdvancerOnRealChrome:
    """The advancer itself, on the two drivers AA ships.

    Playwright is first in framework_order, so a rung that only works on
    Selenium is a rung that does not work for most installs (P1). The
    template cases pin P3: a page that ignores its parameter must NOT be
    claimed as an advance.
    """

    @pytest.fixture(scope="class")
    def driver(self):
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
        except ImportError:
            pytest.skip("Selenium not installed")
        opts = Options()
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--window-size=1000,800")
        try:
            driver = webdriver.Chrome(options=opts)
        except Exception as exc:
            pytest.skip(f"Cannot create Chrome driver: {exc}")
        yield driver
        try:
            driver.quit()
        except Exception:
            pass

    def _advancer(self, driver, **kwargs):
        tool = _tool(driver)
        kwargs.setdefault("change_timeout_s", 4.0)
        return VerifiedPageAdvancer(
            browser=tool._browser, page_action=tool, **kwargs
        )

    def test_load_more_on_a_short_page_is_found_and_growth_verified(
        self, driver, probe_server_url
    ):
        """TEETH (P2, measured on Windows Chrome): scrollHeight is never
        below the viewport, so the 25%-of-document rule dropped every short
        page's button."""
        driver.get(f"{probe_server_url}/m")
        outcome = self._advancer(driver).advance()
        assert outcome.advanced and outcome.method == "load-more", outcome.stop_reason
        assert driver.execute_script(
            "return document.querySelectorAll('a[href]').length"
        ) >= 4

    def test_a_template_advance_is_refused_when_the_page_ignores_the_parameter(
        self, driver, probe_server_url
    ):
        """TEETH (P3, measured on the first probe): /t?p=2 serves /t again —
        the rung must not claim a page it cannot prove changed."""
        driver.get(f"{probe_server_url}/t")
        outcome = self._advancer(
            driver, url_template=UrlPageTemplate(param="p", first=1, step=1)
        ).advance()
        assert outcome.advanced is False

    def test_a_template_advance_is_verified_when_the_page_answers(
        self, driver, probe_server_url
    ):
        """GUARD: the positive leg — a working parameter advances by URL
        template, verified by result-list identity."""
        driver.get(f"{probe_server_url}/w")
        outcome = self._advancer(
            driver, url_template=UrlPageTemplate(param="p", first=1, step=1)
        ).advance()
        assert outcome.advanced and outcome.method == "url-template"
        assert "p=2" in driver.current_url
