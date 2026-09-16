"""SeleniumProvider — creates Selenium WebDriver instances.

Implements DriverProvider for the Selenium framework.  All selenium imports
are deferred to the moment a driver is actually created; the module is
importable even when selenium is not installed.

Supported config keys for create():
    browser_type            str   — 'chrome', 'chromium', 'firefox', 'edge', 'safari'
    headless                bool  — run without a visible window (default False)
    profile_path            str   — path to a browser user-data directory (optional)
    proxy                   str   — 'host:port' proxy string (optional)
    width                   int   — viewport / window width  (default 1920)
    height                  int   — viewport / window height (default 1080)
    use_undetected_chromedriver bool — try uc.Chrome first (default False)
    user_agent              str   — fixed UA string (optional)
    rotate_user_agent       bool  — pick a random UA from the built-in list

Portable-mode environment variables (set by launch_portable.bat / .sh):
    AA_CHROMEDRIVER_PATH     — path to portable ChromeDriver binary
    USER_DATA_DIR            — persistent browser profile directory on the drive
    AA_BROWSER_BINARY_PATH   — path to portable Chromium binary (Chromium
                               launches only; the portable launcher's candidate
                               list is Chrome-only, and geckodriver must never
                               be handed a Chromium path)
    AA_FIREFOX_BINARY_PATH   — path to a Firefox binary (Firefox launches only)

Snap-installed Firefox (Ubuntu's default packaging) is a special case:
geckodriver rejects the /usr/bin/firefox wrapper with "binary is not a
Firefox executable".  When no explicit binary is configured, the provider
resolves the real in-snap executable automatically and points geckodriver's
--profile-root at a directory under the user's home, which snap confinement
can read.  If that resolution fails, set AA_FIREFOX_BINARY_PATH to the real
in-snap executable; a Firefox-shaped AA_BROWSER_BINARY_PATH is accepted as a
fallback.  Detection is filesystem-existence only — AA never carries a list
of distributions it recognises and never shells out to `snap`.
"""

import importlib.util
import logging
import os
import random
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_USER_AGENTS: list[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
]

# Canonical locations of the real executable inside a snap-installed Firefox.
# snapd mounts snaps at /snap on Ubuntu and at /var/lib/snapd/snap on most
# other distributions; checking both covers every distro without a distro list.
_SNAP_FIREFOX_CANDIDATES: tuple[str, ...] = (
    "/snap/firefox/current/usr/lib/firefox/firefox",
    "/var/lib/snapd/snap/firefox/current/usr/lib/firefox/firefox",
)

# Wrapper links whose presence indicates a snap Firefox install.  GeckoDriver
# rejects these with "binary is not a Firefox executable" — they must be
# resolved through to the in-snap executable above.
_SNAP_FIREFOX_LINKS: tuple[str, ...] = (
    "/snap/bin/firefox",
    "/var/lib/snapd/snap/bin/firefox",
)


class SeleniumProvider:
    """DriverProvider that creates Selenium WebDriver instances.

    Checks for selenium availability once at construction time.  If selenium
    is not installed, available returns False and DriverRegistry will skip
    registration with a logged warning — no crash.
    """

    def __init__(self, rng: random.Random | None = None) -> None:
        self._available: bool = importlib.util.find_spec("selenium") is not None
        self._rng = rng if rng is not None else random.Random()

    @property
    def name(self) -> str:
        """Canonical framework identifier."""
        return "selenium"

    @property
    def available(self) -> bool:
        """True if the selenium package is importable."""
        return self._available

    def supports(self, browser_type: str) -> bool:
        """Return True for all OS-installed browsers that Selenium can drive."""
        return browser_type.lower() in {"chrome", "chromium", "firefox", "edge", "safari"}

    def create(self, config: dict) -> Any:
        """Launch and return a Selenium WebDriver.

        Extracts all launch configuration from *config*, builds the appropriate
        Options object, and returns the raw driver.  Window size is enforced
        both via launch flags and via set_window_size() after creation.

        Raises:
            RuntimeError: If the driver cannot be started.
        """
        browser_type = config.get("browser_type", "chrome").lower()
        headless = bool(config.get("headless", False))
        profile_path: str | None = config.get("profile_path")
        proxy: str | None = config.get("proxy")
        width = int(config.get("width", 1920))
        height = int(config.get("height", 1080))
        use_uc = bool(config.get("use_undetected_chromedriver", False))

        try:
            if browser_type in ("chrome", "chromium"):
                driver = self._create_chrome(
                    headless, profile_path, proxy, width, height, use_uc, config
                )
            elif browser_type == "firefox":
                driver = self._create_firefox(
                    headless, profile_path, proxy, width, height, config
                )
            elif browser_type == "edge":
                driver = self._create_edge(headless, profile_path, proxy, width, height)
            elif browser_type == "safari":
                driver = self._create_safari(headless, proxy)
            else:
                raise ValueError(f"Unsupported browser_type for Selenium: {browser_type!r}")
        except Exception as exc:
            raise RuntimeError(
                f"SeleniumProvider could not start {browser_type!r}: {exc}"
            ) from exc

        try:
            driver.set_window_size(width, height)
        except Exception:
            pass

        self._register_process(driver)
        return driver

    def cleanup(self, driver: Any) -> None:
        """Quit the WebDriver, releasing its browser process."""
        try:
            driver.quit()
        except Exception as exc:
            logger.warning("SeleniumProvider.cleanup: quit() raised %s", exc)

    # ─────────────────────────────────────────────────────────────────────────
    # Portable-mode env var helpers
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _get_browser_binary_path(config: dict) -> str | None:
        """Resolve the path to the Chrome/Chromium binary.

        Priority:
            1. ``AA_BROWSER_BINARY_PATH`` env var (set by portable launcher)
            2. ``config["browser_binary_path"]`` (from runtime_defaults.yaml)
            3. ``None`` (let Selenium auto-detect from ``PATH``)
        """
        env_binary = os.environ.get("AA_BROWSER_BINARY_PATH")
        if env_binary:
            p = Path(env_binary)
            if p.exists():
                logger.info(
                    "SeleniumProvider: using portable browser binary: %s", p
                )
                return str(p)
            logger.warning(
                "AA_BROWSER_BINARY_PATH set but file not found: %s "
                "— falling back to system browser",
                env_binary,
            )

        config_binary = config.get("browser_binary_path")
        if config_binary:
            return str(config_binary)

        return None

    @staticmethod
    def _get_firefox_binary_path(config: dict) -> str | None:
        """Resolve the path to the Firefox binary.

        Priority:
            1. ``AA_FIREFOX_BINARY_PATH`` env var (Firefox-specific escape hatch)
            2. ``config["firefox_binary_path"]``
            3. ``AA_BROWSER_BINARY_PATH`` env var, ONLY when its basename names
               a Firefox executable — the generic variable is Chromium-scoped
               by convention (the portable launcher's candidate list is
               Chrome-only) and must never hand a Chromium path to geckodriver
            4. ``None`` (caller falls through to snap detection / PATH)

        A set-but-missing path warns and falls through, matching the shape of
        the Chrome resolver's env-var warning.  All checks are filesystem
        existence and filename shape only — never an execution.
        """
        env_fx = os.environ.get("AA_FIREFOX_BINARY_PATH")
        if env_fx:
            p = Path(env_fx)
            if p.exists():
                logger.info(
                    "SeleniumProvider: using Firefox binary from "
                    "AA_FIREFOX_BINARY_PATH: %s",
                    p,
                )
                return str(p)
            logger.warning(
                "AA_FIREFOX_BINARY_PATH set but file not found: %s "
                "— falling back to snap detection / system Firefox",
                env_fx,
            )

        config_fx = config.get("firefox_binary_path")
        if config_fx:
            if Path(config_fx).exists():
                return str(config_fx)
            logger.warning(
                "config['firefox_binary_path'] set but file not found: %s "
                "— falling back to snap detection / system Firefox",
                config_fx,
            )

        generic = os.environ.get("AA_BROWSER_BINARY_PATH")
        if generic:
            if "firefox" in Path(generic).name.lower():
                p = Path(generic)
                if p.exists():
                    logger.info(
                        "SeleniumProvider: using Firefox binary from "
                        "AA_BROWSER_BINARY_PATH: %s",
                        p,
                    )
                    return str(p)
                logger.warning(
                    "AA_BROWSER_BINARY_PATH names a Firefox path that does "
                    "not exist: %s — falling back",
                    generic,
                )
            else:
                logger.debug(
                    "AA_BROWSER_BINARY_PATH (%s) is not Firefox-shaped — "
                    "ignoring it for the Firefox launch",
                    generic,
                )

        return None

    @staticmethod
    def _get_browser_profile_path(config: dict) -> str | None:
        """Resolve the Chromium user-data-dir path.

        Priority:
            1. ``USER_DATA_DIR`` env var (set by portable launcher — points to drive)
            2. ``BROWSER_PROFILE_DIR`` from ``domain/config`` (computed from data dir)
            3. ``config["browser_profile_path"]``
            4. ``None`` (use ephemeral profile per session)
        """
        env_profile = os.environ.get("USER_DATA_DIR")
        if env_profile:
            return env_profile

        try:
            from auto_apply.domain.config import BROWSER_PROFILE_DIR  # noqa: PLC0415

            return str(BROWSER_PROFILE_DIR)
        except Exception:
            pass

        config_profile = config.get("browser_profile_path")
        if config_profile:
            return str(config_profile)

        return None

    @staticmethod
    def _get_chromedriver_path(config: dict) -> str | None:
        """Resolve the ChromeDriver binary path.

        In portable mode, ChromeDriver lives next to the app executable.
        ``AA_CHROMEDRIVER_PATH`` env var is set by the portable launcher.

        Priority:
            1. ``AA_CHROMEDRIVER_PATH`` env var
            2. ``config["chromedriver_path"]``
            3. ``None`` (let Selenium auto-detect)
        """
        env_driver = os.environ.get("AA_CHROMEDRIVER_PATH")
        if env_driver:
            p = Path(env_driver)
            if p.exists():
                logger.info(
                    "SeleniumProvider: using portable ChromeDriver: %s", p
                )
                return str(p)
            logger.warning(
                "AA_CHROMEDRIVER_PATH set but file not found: %s "
                "— falling back to auto-detection",
                env_driver,
            )

        config_driver = config.get("chromedriver_path")
        if config_driver:
            return str(config_driver)

        return None

    # ─────────────────────────────────────────────────────────────────────────
    # Snap Firefox detection (filesystem checks only — never shells out)
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _detect_snap_firefox() -> str | None:
        """Return the real executable inside a snap-installed Firefox, or None.

        Detection is filesystem-existence only: AA never string-matches a
        distro name and never shells out to ``snap``.  Both of snapd's
        canonical mount points are checked (/snap on Ubuntu,
        /var/lib/snapd/snap on most other distributions), so any distro is
        covered without an allow-list.
        """
        for candidate in _SNAP_FIREFOX_CANDIDATES:
            p = Path(candidate)
            if p.is_file() and os.access(p, os.X_OK):
                return str(p)
        return None

    @staticmethod
    def _snap_firefox_present() -> bool:
        """True when a snap Firefox wrapper link exists on this machine.

        Used to decide whether a launch failure is the known snap-wrapper
        failure ("binary is not a Firefox executable") so the error can name
        the real cause and the remedy instead of repeating geckodriver.
        """
        return any(Path(link).exists() for link in _SNAP_FIREFOX_LINKS)

    # ── Per-browser constructors ──────────────────────────────────────────────

    def _create_chrome(
        self,
        headless: bool,
        profile_path: str | None,
        proxy: str | None,
        width: int,
        height: int,
        use_uc: bool,
        config: dict,
    ) -> Any:
        """Construct a Chrome driver, preferring undetected_chromedriver when requested."""
        if use_uc:
            try:
                import undetected_chromedriver as uc  # noqa: PLC0415

                opts = uc.ChromeOptions()
                self._apply_common_chromium_flags(
                    opts, headless, width, height, profile_path, config
                )
                if proxy:
                    opts.add_argument(f"--proxy-server={proxy}")
                if self._is_in_container():
                    opts.add_argument("--no-zygote")
                return uc.Chrome(options=opts)
            except ImportError:
                logger.warning(
                    "SeleniumProvider: undetected_chromedriver not installed "
                    "— falling back to standard Chrome"
                )

        from selenium.webdriver import ChromeOptions  # noqa: PLC0415
        from selenium import webdriver  # noqa: PLC0415
        from selenium.webdriver.chrome.service import Service  # noqa: PLC0415

        opts = ChromeOptions()
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)
        ua = self._get_user_agent(config)
        opts.add_argument(f"user-agent={ua}")
        self._apply_common_chromium_flags(
            opts, headless, width, height, profile_path, config
        )
        if proxy:
            opts.add_argument(f"--proxy-server={proxy}")
        if self._is_in_container():
            opts.add_argument("--no-zygote")

        # ── Portable browser binary ─────────────────────────────────────
        binary_path = self._get_browser_binary_path(config)
        if binary_path:
            opts.binary_location = binary_path

        # ── Portable ChromeDriver ───────────────────────────────────────
        driver_path = self._get_chromedriver_path(config)
        service = Service(executable_path=driver_path) if driver_path else Service()

        return webdriver.Chrome(service=service, options=opts)

    def _create_firefox(
        self,
        headless: bool,
        profile_path: str | None,
        proxy: str | None,
        width: int,
        height: int,
        config: dict,
    ) -> Any:
        """Construct a Firefox driver with fingerprinting-resistance preferences.

        Handles snap-installed Firefox (Ubuntu's default): resolves the real
        in-snap executable when no explicit binary is configured, and points
        geckodriver's --profile-root at a directory under the user's home,
        which snap confinement can read.  Binary resolution is Firefox-scoped:
        a Chromium-scoped AA_BROWSER_BINARY_PATH is never inherited.
        """
        from selenium.webdriver import FirefoxOptions  # noqa: PLC0415
        from selenium import webdriver  # noqa: PLC0415

        opts = FirefoxOptions()
        opts.add_argument(f"--width={width}")
        opts.add_argument(f"--height={height}")
        if headless:
            opts.add_argument("--headless")

        opts.set_preference("dom.webdriver.enabled", False)
        opts.set_preference("useAutomationExtension", False)
        opts.set_preference("privacy.resistFingerprinting", True)
        opts.set_preference("privacy.trackingprotection.enabled", True)
        opts.set_preference("media.peerconnection.enabled", False)
        opts.set_preference("general.useragent.override", self._get_user_agent(config))

        # Resolve the browser's Accept-Language from the SAME normaliser the
        # i18n service uses (domain.services.locale_normalization). This was
        # previously a second answering site via locale.getdefaultlocale() —
        # an API deprecated since 3.11 and removed in 3.15 — and it produced
        # different answers from i18n.detect_locale on the same machine.
        import locale as _locale  # noqa: PLC0415

        from auto_apply.domain.services.locale_normalization import (  # noqa: PLC0415
            normalize_locale,
        )

        locale_str = "en-US"
        try:
            normalised = normalize_locale(_locale.getlocale()[0])
            if normalised is not None:
                lang, country = normalised
                locale_str = f"{lang}-{country}" if country else lang
        except Exception:
            pass
        lang_prefix = locale_str.split("-")[0]
        accept_lang = f"{locale_str},{lang_prefix};q=0.9,en-US;q=0.8,en;q=0.7"
        opts.set_preference("intl.accept_languages", accept_lang)

        if proxy:
            try:
                host, port_str = proxy.split(":", 1)
                port = int(port_str)
                opts.set_preference("network.proxy.type", 1)
                opts.set_preference("network.proxy.http", host)
                opts.set_preference("network.proxy.http_port", port)
                opts.set_preference("network.proxy.ssl", host)
                opts.set_preference("network.proxy.ssl_port", port)
                opts.set_preference("network.proxy.socks_remote_dns", True)
            except Exception as exc:
                logger.warning(
                    "SeleniumProvider: could not parse proxy %r: %s", proxy, exc
                )

        if profile_path:
            from selenium.webdriver.firefox.firefox_profile import (  # noqa: PLC0415
                FirefoxProfile,
            )

            opts.profile = FirefoxProfile(profile_path)

        # ── Resolve the real Firefox binary ─────────────────────────────────
        # Precedence:
        #   1. AA_FIREFOX_BINARY_PATH env var / config key (Firefox-specific)
        #   2. a Firefox-shaped AA_BROWSER_BINARY_PATH (never a Chromium path)
        #   3. a snap-installed Firefox's in-snap executable (Linux only)
        #   4. None — let Selenium Manager / geckodriver pick from PATH
        binary_path = self._get_firefox_binary_path(config)
        snap_in_use = False
        service = None

        if binary_path is None and sys.platform.startswith("linux"):
            snap_binary = self._detect_snap_firefox()
            if snap_binary is not None:
                binary_path = snap_binary
            elif self._snap_firefox_present():
                raise RuntimeError(
                    "Firefox is installed as a snap, but the real in-snap "
                    "executable could not be found at any of "
                    f"{list(_SNAP_FIREFOX_CANDIDATES)}. GeckoDriver cannot "
                    "drive the /snap/bin/firefox wrapper. Set "
                    "AA_FIREFOX_BINARY_PATH to the real executable, e.g. "
                    "AA_FIREFOX_BINARY_PATH="
                    "/snap/firefox/current/usr/lib/firefox/firefox "
                    "(a Firefox-shaped AA_BROWSER_BINARY_PATH is also "
                    "accepted), or install a deb build of Firefox instead."
                )

        if binary_path:
            opts.binary_location = binary_path
            logger.info("SeleniumProvider: Firefox binary: %s", binary_path)
            snap_in_use = (
                "/snap/firefox/" in binary_path
                or binary_path in _SNAP_FIREFOX_CANDIDATES
            )

        if snap_in_use:
            # Snap confinement: the snap cannot read geckodriver's default
            # temp profile directory (its /tmp is a private namespace), so the
            # service needs --profile-root somewhere under the user's home.
            from selenium.webdriver.firefox.service import (  # noqa: PLC0415
                Service as FirefoxService,
            )

            profile_root = Path.home() / ".auto_apply" / "gecko-profile-root"
            if not profile_root.is_dir():
                profile_root.mkdir(parents=True, exist_ok=True)
                logger.info(
                    "SeleniumProvider: created geckodriver profile root for "
                    "snap Firefox: %s",
                    profile_root,
                )
            service = FirefoxService(
                service_args=["--profile-root", str(profile_root)]
            )

        try:
            if service is not None:
                return webdriver.Firefox(service=service, options=opts)
            return webdriver.Firefox(options=opts)
        except Exception as exc:
            if snap_in_use or self._snap_firefox_present():
                raise RuntimeError(
                    f"Snap-confined Firefox could not start ({exc}). A snap "
                    "Firefox requires geckodriver under /snap/bin and a "
                    "--profile-root inside your home directory. If this "
                    "persists, set AA_FIREFOX_BINARY_PATH to the real in-snap "
                    "executable (/snap/firefox/current/usr/lib/firefox/firefox) "
                    "or install a deb build of Firefox."
                ) from exc
            raise

    def _create_edge(
        self,
        headless: bool,
        profile_path: str | None,
        proxy: str | None,
        width: int,
        height: int,
    ) -> Any:
        """Construct a Microsoft Edge driver."""
        from selenium.webdriver import EdgeOptions  # noqa: PLC0415
        from selenium import webdriver  # noqa: PLC0415

        opts = EdgeOptions()
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        self._apply_common_chromium_flags(
            opts, headless, width, height, profile_path, {}
        )
        if proxy:
            opts.add_argument(f"--proxy-server={proxy}")
        if self._is_in_container():
            opts.add_argument("--no-zygote")
        return webdriver.Edge(options=opts)

    def _create_safari(self, headless: bool, proxy: str | None) -> Any:
        """Construct a Safari driver (macOS only; headless and proxy are no-ops)."""
        from selenium.webdriver import SafariOptions  # noqa: PLC0415
        from selenium import webdriver  # noqa: PLC0415

        opts = SafariOptions()
        opts.set_capability("safari:automaticInspection", True)
        if headless:
            logger.warning(
                "SeleniumProvider: Safari does not support headless mode "
                "— browser will be visible"
            )
        if proxy:
            logger.warning(
                "SeleniumProvider: Safari ignores proxy options "
                "— using macOS system proxy settings"
            )
        return webdriver.Safari(options=opts)

    # ── Shared helpers ────────────────────────────────────────────────────────

    def _apply_common_chromium_flags(
        self,
        opts: Any,
        headless: bool,
        width: int,
        height: int,
        profile_path: str | None,
        config: dict,
    ) -> None:
        """Apply the base Chromium flags shared by Chrome, Edge, and uc.Chrome.

        These flags are required for reliable operation on library/CI machines
        (no sandbox, no /dev/shm, no GPU rendering).

        The profile_path parameter may be overridden by the portable-mode env
        var helper; callers should pass the result of _get_browser_profile_path
        rather than a raw config value.
        """
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument(f"--window-size={width},{height}")
        opts.add_argument("--disable-setuid-sandbox")
        opts.add_argument("--disable-extensions")
        opts.add_argument("--disable-infobars")
        opts.add_argument("--disable-notifications")
        if headless:
            opts.add_argument("--headless=new")

        resolved_profile = self._get_browser_profile_path(config)
        if resolved_profile:
            opts.add_argument(f"--user-data-dir={resolved_profile}")
        elif profile_path:
            opts.add_argument(f"--user-data-dir={profile_path}")

    def _get_user_agent(self, config: dict) -> str:
        """Return a UA string based on config keys rotate_user_agent / user_agent."""
        if config.get("rotate_user_agent"):
            return self._rng.choice(_USER_AGENTS)
        return config.get("user_agent") or _USER_AGENTS[0]

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
        return os.environ.get("CONTAINER", "").lower() in {
            "true", "1", "yes", "docker"
        }

    @staticmethod
    def _register_process(driver: Any) -> None:
        """Register the browser PID with ProcessManager for clean-up on exit."""
        try:
            from auto_apply.adapters.secondary.os.process import (  # noqa: PLC0415
                ProcessManager,
            )

            pid = getattr(driver, "browser_pid", None)
            if not pid and hasattr(driver, "service"):
                pid = driver.service.process.pid
            if pid:
                ProcessManager.register(pid)
                logger.debug(
                    "SeleniumProvider: registered browser PID %s", pid
                )
        except Exception as exc:
            logger.warning(
                "SeleniumProvider: could not register browser PID: %s", exc
            )
