"""
A dedicated module for generating hardened, secure, and production-ready
Selenium Options objects for various browsers.
"""
import sys
from selenium.webdriver import ChromeOptions, FirefoxOptions, EdgeOptions, SafariOptions
import undetected_chromedriver as uc

from ..config import settings

def get_chrome_options(proxy: str = None) -> uc.ChromeOptions:
    """Returns a hardened ChromeOptions object for undetected_chromedriver."""
    options = uc.ChromeOptions()

    options.add_argument("--window-size=1920,1080")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-notifications")
    if proxy:
        options.add_argument(f'--proxy-server=http://{proxy}')
    return options

def get_firefox_options(proxy: str = None) -> FirefoxOptions:
    """Returns a hardened, production-ready FirefoxOptions object."""
    options = FirefoxOptions()

    options.add_argument("--width=1920")
    options.add_argument("--height=1080")

    options.set_preference("media.navigator.enabled", False)
    options.set_preference("dom.webdriver.enabled", False)
    options.set_preference('useAutomationExtension', False)
    options.set_preference("general.useragent.override", settings.scraping.user_agent)
    options.set_preference("intl.accept_languages", "en-US, en")
    options.set_preference("toolkit.telemetry.enabled", False)
    options.set_preference("datareporting.healthreport.uploadEnabled", False)
    options.set_preference("datareporting.policy.dataSubmissionEnabled", False)
    options.set_preference("app.shield.optoutstudies.enabled", False)
    options.set_preference("media.peerconnection.enabled", False)
    options.set_preference("dom.webnotifications.enabled", False)
    options.set_preference("permissions.default.shortcuts", 2) 
    options.set_preference("extensions.enabledScopes", 0)
    options.set_preference("browser.toolbars.bookmarks.visibilty", "never")
    options.set_preference("signon.rememberSignons", False)
    options.set_preference("places.history.enabled", False)

    if proxy:
        host, port = proxy.split(":")
        options.set_preference('network.proxy.type', 1)
        options.set_preference('network.proxy.http', host)
        options.set_preference('network.proxy.http_port', int(port))
        options.set_preference('network.proxy.ssl', host)
        options.set_preference('network.proxy.ssl_port', int(port))
        options.set_preference('network.proxy.socks_remote_dns', True)
        options.set_preference("intl.accept_languages", "en-US, en")
        options.set_preference("privacy.spoof.timezone.ip_fallback", True)
    return options

def get_edge_options(proxy: str = None) -> EdgeOptions:
    """Returns a hardened EdgeOptions object."""
    options = EdgeOptions()

    options.use_chromium = True

    options.add_argument("--headless")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-notifications")
    options.add_argument(f"user-agent={settings.scraping.user_agent}")

    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    if proxy:
        options.add_argument(f'--proxy-server=http://{proxy}')
    return options

def get_safari_options(proxy: str = None) -> SafariOptions:
    """Returns a SafariOptions object."""
    if sys.platform != "darwin":
        return None
    options = SafariOptions()
    return options