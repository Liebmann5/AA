import functools
import logging
import threading
import time

from auto_apply.domain.config import LOG_DIR
from auto_apply.domain.ports.browser_port import BrowserInterface, ElementInterface

logger = logging.getLogger(__name__)

class PageLoadError(Exception):
    pass

class AuthWallError(Exception):
    pass

class ResilientDriver(BrowserInterface):
    """A Decorator/Wrapper that adds enterprise-grade resilience to any browser adapter.

    Capabilities:
    1. Automatic Popup Dismissal (Interruption Handling).
    2. Deep DOM Search (Recursive Iframe traversal).
    3. Tab Management (Focus control).
    4. Health Checks (404/Login detection).
    5. Context manager support (forwarded to wrapped driver).
    """

    def __init__(self, driver: BrowserInterface):
        # Serializes command dispatch to the wrapped (non-thread-safe) driver.
        # Two threads touch this driver: the main agent loop (navigation, SERP
        # scrolling, form filling) and the BrowserHealthMonitor probe. A single
        # Selenium driver shares one urllib3 connection pool with maxsize=1, so
        # two concurrent commands overflow it ("Connection pool is full,
        # discarding connection: localhost") and are unsafe besides — WebDriver
        # is not thread-safe. The lock makes command dispatch mutually
        # exclusive. It is reentrant (RLock) so a public method that internally
        # issues further commands on the same thread does not self-deadlock.
        self._command_lock = threading.RLock()
        self._driver = driver
        self._main_window = getattr(driver, 'current_window_handle', None)

    def __enter__(self):
        if hasattr(self._driver, '__enter__'):
            self._driver.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if hasattr(self._driver, '__exit__'):
            return self._driver.__exit__(exc_type, exc_val, exc_tb)
        return False

    # ------------------------------------------------------------------
    # BrowserInterface abstract properties
    # ------------------------------------------------------------------

    @property
    def framework_name(self) -> str:
        return self._driver.framework_name

    @property
    def title(self) -> str:
        return self._driver.title

    @property
    def page_source(self) -> str:
        return self._driver.page_source

    @property
    def current_url(self) -> str:
        return self._driver.current_url

    # ------------------------------------------------------------------
    # BrowserInterface abstract methods – navigation
    # ------------------------------------------------------------------

    def get(self, url: str) -> None:
        with self._command_lock:
            try:
                # Suppress noisy log for about:blank navigation (P1-16)
                if url != "about:blank":
                    logger.info("Navigating to: %s", url)
                self._driver.get(url)
                self._wait_for_ready_state()
                title = self._driver.title.lower()
                current_url = self._driver.current_url.lower()
                if "404" in title or "not found" in title:
                    raise PageLoadError(f"Page not found: {url}")
                if "login" in current_url and "login" not in url.lower():
                    if "sign in" in title or "log in" in title:
                        raise AuthWallError(f"Redirected to Auth Wall: {current_url}")
            except Exception as e:
                logger.error("Navigation failed: %s", e)
                self.save_screenshot(str(LOG_DIR / f"error_nav_{int(time.time())}.png"))
                raise e

    def back(self) -> None:
        with self._command_lock:
            self._driver.back()

    def close(self) -> None:
        with self._command_lock:
            self._driver.close()

    # ------------------------------------------------------------------
    # BrowserInterface abstract methods – element location
    # ------------------------------------------------------------------

    def find_element(self, by: str, selector: str) -> ElementInterface | None:
        with self._command_lock:
            try:
                el = self._driver.find_element(by, selector)
                if el:
                    return el
            except Exception:
                pass
            found = self._search_frames_recursive(by, selector)
            if found:
                return found
            self._driver.switch_to_default_content()
            return None

    def find_elements(self, by: str, selector: str) -> list[ElementInterface]:
        with self._command_lock:
            return self._driver.find_elements(by, selector)

    def wait_for_element(self, by: str, selector: str, timeout: int = 10) -> ElementInterface | None:
        with self._command_lock:
            return self._driver.wait_for_element(by, selector, timeout=timeout)

    # ------------------------------------------------------------------
    # BrowserInterface abstract methods – scripting & context
    # ------------------------------------------------------------------

    def execute_script(self, script: str, *args) -> object:
        with self._command_lock:
            return self._driver.execute_script(script, *args)

    def switch_to_iframe(self, iframe_element: ElementInterface) -> None:
        with self._command_lock:
            self._driver.switch_to_iframe(iframe_element)

    def switch_to_default_content(self) -> None:
        with self._command_lock:
            self._driver.switch_to_default_content()

    # ------------------------------------------------------------------
    # BrowserInterface abstract methods – cookies
    # ------------------------------------------------------------------

    def get_cookies(self) -> list[dict]:
        with self._command_lock:
            return self._driver.get_cookies()

    def add_cookie(self, cookie: dict) -> None:
        with self._command_lock:
            self._driver.add_cookie(cookie)

    # ------------------------------------------------------------------
    # BrowserInterface abstract methods – mouse & scroll
    # ------------------------------------------------------------------

    def scroll_by_offset(self, x: int, y: int) -> None:
        with self._command_lock:
            self._driver.scroll_by_offset(x, y)

    def move_mouse_by_offset(self, x: int, y: int) -> None:
        with self._command_lock:
            self._driver.move_mouse_by_offset(x, y)

    def move_mouse_to_element(self, element: ElementInterface, offset_x: int = 0, offset_y: int = 0) -> None:
        with self._command_lock:
            self._driver.move_mouse_to_element(element, offset_x, offset_y)

    def perform_mouse_fidget(self) -> None:
        with self._command_lock:
            self._driver.perform_mouse_fidget()

    # ------------------------------------------------------------------
    # BrowserInterface abstract methods – screenshots
    # ------------------------------------------------------------------

    def save_screenshot(self, filepath: str) -> None:
        with self._command_lock:
            self._driver.save_screenshot(filepath)

    # ------------------------------------------------------------------
    # Additional public helpers (not part of BrowserInterface)
    # ------------------------------------------------------------------

    def click(self, element: ElementInterface) -> None:
        """Robust click with popover handling and JS fallback."""
        with self._command_lock:
            max_retries = 3
            for i in range(max_retries):
                try:
                    element.click()
                    return
                except Exception as e:
                    msg = str(e).lower()
                    if "intercepted" in msg or "obscured" in msg:
                        logger.warning("Click intercepted. Attempting to clear obstructions...")
                        if self._handle_interruptions():
                            time.sleep(0.5)
                            continue
                    if i == max_retries - 1:
                        logger.info("Standard click failed. Using JS Fallback.")
                        self._driver.execute_script("arguments[0].click();", element)
                        return
                    time.sleep(1)

    def is_alive(self) -> bool:
        """Health-check probe; intentionally lock‑free to avoid deadlock with health monitor.

        Uses ``execute_script('return 1')`` for both Selenium and Playwright
        adapters — the lightest possible command that exercises the active session.
        """
        driver = self._driver
        if driver is None:
            return False
        try:
            _ = driver.execute_script("return 1")
            return True
        except Exception:
            return False

    def try_acquire_command_lock(self) -> bool:
        """Non‑blocking acquire for health probing."""
        return self._command_lock.acquire(blocking=False)

    def release_command_lock(self) -> None:
        """Release lock previously taken via try_acquire_command_lock."""
        try:
            self._command_lock.release()
        except RuntimeError:
            pass

    # ------------------------------------------------------------------
    # Dynamic fallback for adapter‑specific methods (e.g. get_raw_driver)
    # ------------------------------------------------------------------

    def __getattr__(self, name):
        """Forward unknown attributes to the wrapped driver under command lock."""
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)

        driver = self.__dict__.get("_driver")
        if driver is None:
            raise AttributeError(name)

        lock = self.__dict__.get("_command_lock")
        if lock is None:
            return getattr(driver, name)

        with lock:
            attr = getattr(driver, name)

        if callable(attr):
            @functools.wraps(attr)
            def _locked_call(*args, **kwargs):
                with lock:
                    try:
                        return attr(*args, **kwargs)
                    except Exception as e:
                        if "target window already closed" in str(e).lower() or "invalid session id" in str(e).lower():
                            logger.debug("Driver operation aborted: Browser was closed (%s)", name)
                            raise PageLoadError("Browser session was closed.")
            return _locked_call
        return attr

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _wait_for_ready_state(self):
        for _ in range(20):
            try:
                state = self._driver.execute_script("return document.readyState")
                if state == "complete":
                    return
            except Exception:
                pass
            time.sleep(0.5)

    def _handle_interruptions(self) -> bool:
        heuristics = [
            "button[id*='cookie'][id*='accept']",
            "button[class*='cookie'][class*='accept']",
            "div[class*='modal'] button[class*='close']",
            "button[aria-label='Close']"
        ]
        for selector in heuristics:
            try:
                elements = self._driver.find_elements("css selector", selector)
                for btn in elements:
                    if btn.get_size()[0] > 0:
                        self._driver.execute_script("arguments[0].click();", btn)
                        return True
            except Exception:
                continue
        return False

    def _search_frames_recursive(self, by, selector, depth=0) -> ElementInterface | None:
        if depth > 2:
            return None
        frames = self._driver.find_elements("tag name", "iframe")
        for frame in frames:
            try:
                self._driver.switch_to_iframe(frame)
                el = self._driver.find_element(by, selector)
                if el:
                    return el
                found = self._search_frames_recursive(by, selector, depth + 1)
                if found:
                    return found
                self._driver.switch_to_default_content()
            except Exception:
                self._driver.switch_to_default_content()
        return None