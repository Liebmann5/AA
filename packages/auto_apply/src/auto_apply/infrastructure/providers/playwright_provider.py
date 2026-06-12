"""PlaywrightProvider — creates Playwright Page instances.

Implements DriverProvider for the Playwright framework.  All playwright imports
are deferred inside create(); the module is importable even when playwright is
not installed.

Supported config keys for create():
    browser_type    str   — 'chromium', 'firefox', 'webkit' (default 'chromium')
    headless        bool  — run without a visible window (default True)
    profile_path    str   — path to a Chromium user-data dir for persistent context
    proxy           str   — 'host:port' proxy string (optional)
    width           int   — viewport width  (default 1920)
    height          int   — viewport height (default 1080)

Resource lifecycle:
    create() attaches three handles to the returned Page object so that both
    the adapter and cleanup() can reach them:
        page._pw_playwright — the sync_playwright handle (must be stopped last)
        page._pw_browser    — the Browser (or BrowserContext for persistent_context)
        page._pw_context    — the BrowserContext

    On partial cascade failure (after create() but before the adapter is ready),
    cleanup() closes context, browser, and playwright in three independent
    try/except blocks so one failure cannot prevent the others.
"""

import importlib.util
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class PlaywrightProvider:
    """DriverProvider that creates Playwright Page instances.

    Checks for playwright availability once at construction time.  If playwright
    is not installed, available returns False and DriverRegistry will skip
    registration with a logged warning — no crash.
    """

    _missing_warned: set = set()

    def __init__(self) -> None:
        self._available: bool = importlib.util.find_spec("playwright") is not None

    @property
    def name(self) -> str:
        """Canonical framework identifier."""
        return "playwright"

    @property
    def available(self) -> bool:
        """True if the playwright package is importable."""
        return self._available

    def supports(self, browser_type: str) -> bool:
        """Return True for browsers that Playwright bundles internally."""
        return browser_type.lower() in {"chromium", "firefox", "webkit"}

    def create(self, config: dict) -> Any:
        """Start Playwright, launch a browser, and return a configured Page.

        Three handles are attached to the page before it is returned:
            page._pw_playwright, page._pw_browser, page._pw_context

        For the persistent-context case (profile_path + chromium), the
        BrowserContext is stored as both _pw_browser and _pw_context because
        it is the top-level lifecycle object (no separate Browser handle).

        Raises:
            RuntimeError: If Playwright cannot be launched.
        """
        try:
            from playwright.sync_api import sync_playwright  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError("playwright package is not installed") from exc

        browser_type = config.get("browser_type", "chromium").lower()

        # ----- idempotency guard: warn once per missing binary ----------------
        if browser_type not in PlaywrightProvider._missing_warned:
            with sync_playwright() as temp_pw:
                browser_map = {
                    "chromium": temp_pw.chromium,
                    "chrome":   temp_pw.chromium,
                    "firefox":  temp_pw.firefox,
                    "webkit":   temp_pw.webkit,
                    "safari":   temp_pw.webkit,
                }
                launcher = browser_map.get(browser_type, temp_pw.chromium)
                executable = launcher.executable_path
                if not Path(executable).exists():
                    PlaywrightProvider._missing_warned.add(browser_type)
                    logger.warning(
                        "Playwright binary not found for %s at %s. Skipping.",
                        browser_type,
                        executable,
                    )
                    raise RuntimeError(
                        f"Playwright binary for {browser_type} is not installed."
                    )
        # ----------------------------------------------------------------------

        headless = bool(config.get("headless", True))
        profile_path: str | None = config.get("profile_path")
        proxy: str | None = config.get("proxy")
        width = int(config.get("width", 1920))
        height = int(config.get("height", 1080))

        pw = sync_playwright().start()
        try:
            page = self._launch(pw, browser_type, headless, profile_path, proxy, width, height)
        except Exception as exc:
            try:
                pw.stop()
            except Exception:
                pass
            raise RuntimeError(f"PlaywrightProvider failed for {browser_type!r}: {exc}") from exc

        return page

    def cleanup(self, driver: Any) -> None:
        """Close context, browser, and stop the playwright handle.

        Each step runs in its own try/except so a failure in one does not
        prevent the remaining steps from executing.
        """
        try:
            driver._pw_context.close()
        except Exception as exc:
            logger.warning("PlaywrightProvider.cleanup: context.close() raised %s", exc)

        try:
            if driver._pw_browser is not None:
                driver._pw_browser.close()
        except Exception as exc:
            logger.warning("PlaywrightProvider.cleanup: browser.close() raised %s", exc)

        try:
            driver._pw_playwright.stop()
        except Exception as exc:
            logger.warning("PlaywrightProvider.cleanup: playwright.stop() raised %s", exc)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _launch(
        self,
        pw: Any,
        browser_type: str,
        headless: bool,
        profile_path: str | None,
        proxy: str | None,
        width: int,
        height: int,
    ) -> Any:
        """Select the correct browser launcher and build the page."""
        browser_map = {
            "chromium": pw.chromium,
            "chrome":   pw.chromium,
            "firefox":  pw.firefox,
            "webkit":   pw.webkit,
            "safari":   pw.webkit,
        }
        launcher = browser_map.get(browser_type, pw.chromium)
        is_chromium = browser_type in {"chromium", "chrome"}
        launch_args = self._build_launch_args(headless, is_chromium, proxy)
        viewport = {"width": width, "height": height}

        if profile_path and is_chromium:
            return self._launch_persistent(pw, launcher, profile_path, headless, launch_args, viewport)

        browser = launcher.launch(headless=headless, args=launch_args)
        context = browser.new_context(viewport=viewport)
        page = context.new_page()
        page._pw_playwright = pw
        page._pw_browser = browser
        page._pw_context = context
        return page

    def _launch_persistent(
        self,
        pw: Any,
        launcher: Any,
        profile_path: str,
        headless: bool,
        launch_args: list[str],
        viewport: dict,
    ) -> Any:
        """Launch a persistent Chromium context backed by a user-data directory.

        The BrowserContext is stored as both _pw_browser and _pw_context because
        it is the sole lifecycle object; calling .close() on it tears down the
        whole session.
        """
        context = launcher.launch_persistent_context(
            user_data_dir=profile_path,
            headless=headless,
            args=launch_args,
            viewport=viewport,
        )
        page = context.new_page()
        page._pw_playwright = pw
        page._pw_browser = context
        page._pw_context = context
        return page

    def _build_launch_args(
        self, headless: bool, is_chromium: bool, proxy: str | None
    ) -> list[str]:
        """Build the list of browser launch arguments."""
        args: list[str] = []
        if is_chromium:
            args.extend([
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ])
            if self._is_in_container():
                args.append("--no-zygote")
        if proxy:
            args.append(f"--proxy-server={proxy}")
        return args

    @staticmethod
    def _is_in_container() -> bool:
        """Detect Docker / containerd / Kubernetes / Podman environments."""
        if os.path.exists("/.dockerenv"):
            return True
        try:
            with open("/proc/1/cgroup") as fh:
                content = fh.read()
            if any(t in content for t in ("docker", "containerd", "kubepods", "lxc")):
                return True
        except OSError:
            pass
        return os.environ.get("CONTAINER", "").lower() in {"true", "1", "yes", "docker"}