import logging
import math
import random
import time
from typing import Optional

from auto_apply.domain.exceptions import ApplicationError
from auto_apply.domain.ports.browser_port import BrowserInterface, ElementInterface

logger = logging.getLogger(__name__)


def parabolic_delay(
    peak_time: float = 0.15,
    randomness: float = 0.3,
    rng: Optional[random.Random] = None,
) -> float:
    """Generates a natural-seeming delay.

    Args:
        peak_time: Base peak time in seconds.
        randomness: Fraction of randomness around the peak.
        rng: Optional seeded random.Random for reproducibility.

    Returns:
        A non‑negative delay in seconds.
    """
    _rng = rng if rng is not None else random.Random()
    x = _rng.uniform(-1, 1)
    base_delay = (-(x * x) + 1) * peak_time
    random_factor = _rng.uniform(1 - randomness, 1 + randomness)
    return abs(base_delay * random_factor)


def _generate_bezier_curve(
    start: tuple[int, int],
    end: tuple[int, int],
    control_points: list[tuple[int, int]],
    rng: Optional[random.Random] = None,
) -> list[tuple[int, int]]:
    """Generates points along a Bezier curve for smooth mouse movements."""
    _rng = rng if rng is not None else random.Random()
    points: list[tuple[int, int]] = []
    n = len(control_points) + 1
    for step in range(101):
        t = step / 100.0
        x = (1 - t) ** n * start[0] + (t ** n) * end[0]
        y = (1 - t) ** n * start[1] + (t ** n) * end[1]

        for i in range(1, n):
            binomial_coeff = math.comb(n, i)
            term = binomial_coeff * ((1 - t) ** (n - i)) * (t ** i)
            x += term * control_points[i - 1][0]
            y += term * control_points[i - 1][1]
        points.append((int(x), int(y)))
    return points


def human_like_typing(
    element: ElementInterface,
    text: str,
    rng: Optional[random.Random] = None,
) -> None:
    """Types text with variable, human-like delays into any element adapter."""
    for char in text:
        element.send_keys(char)
        time.sleep(parabolic_delay(rng=rng))


def human_like_mouse_move(
    browser: BrowserInterface,
    start_element: ElementInterface,
    end_element: ElementInterface,
    rng: Optional[random.Random] = None,
) -> None:
    """Simulates a human-like, curved mouse movement using generic interface methods."""
    _rng = rng if rng is not None else random.Random()

    browser.move_mouse_to_element(start_element)
    start_point = start_element.get_location()

    end_loc = end_element.get_location()
    end_size = end_element.get_size()
    end_point = (end_loc[0] + end_size[0] // 2, end_loc[1] + end_size[1] // 2)

    control1 = (
        start_point[0] + _rng.randint(-50, 50),
        start_point[1] + _rng.randint(50, 150),
    )
    control2 = (
        end_point[0] + _rng.randint(-150, -50),
        end_point[1] + _rng.randint(-50, 50),
    )

    curve = _generate_bezier_curve(start_point, end_point, [control1, control2], rng=_rng)

    current_pos = start_point
    for point in curve:
        move_x = point[0] - current_pos[0]
        move_y = point[1] - current_pos[1]
        browser.move_mouse_by_offset(move_x, move_y)
        current_pos = point
        time.sleep(_rng.uniform(0.005, 0.015))


def _is_element_a_honeypot(browser: BrowserInterface, element: ElementInterface) -> bool:  # noqa: E501
    """Performs checks to determine if an element is a trap for bots."""
    #TODO: Revisit!!
    script = """
    var elem = arguments[0];
    if (window.getComputedStyle(elem).display === 'none') { return false; }
    if (elem.offsetWidth === 0 || elem.offsetHeight === 0) { return false; }
    var box = elem.getBoundingClientRect();
    var cx = box.left + box.width / 2;
    var cy = box.top + box.height / 2;
    var e = document.elementFromPoint(cx, cy);
    for (; e; e = e.parentElement) {
        if (e === elem) { return true; }
    }
    return false;
    """
    try:
        return not browser.execute_script(script, element)
    except Exception as e:
        logger.warning(f"Honeypot check failed with an error, assuming it's a trap: {e}")  # noqa: E501
        return True
    # This check is currently too aggressive and is causing false positives.
    # We will temporarily disable it to focus on the core application logic.
    # We can re-introduce a more refined version later.
    # logger.warning("Honeypot detection is temporarily disabled for debugging.")
    # return False

def human_like_click(
    browser: BrowserInterface,
    element: ElementInterface,
    rng: Optional[random.Random] = None,
) -> None:
    """
    Performs a highly realistic click on any element adapter, including
    hesitation and overshoot, using the generic interface methods.
    """
    _rng = rng if rng is not None else random.Random()

    if _is_element_a_honeypot(browser, element):
        raise ApplicationError("Element is suspected to be a honeypot trap.")

    browser.move_mouse_to_element(
        element,
        offset_x=_rng.randint(-10, 10),
        offset_y=_rng.randint(-10, 10),
    )
    time.sleep(parabolic_delay(peak_time=0.3, rng=_rng))

    browser.move_mouse_to_element(element)
    time.sleep(parabolic_delay(peak_time=0.1, rng=_rng))

    element.click()
    logger.debug("Performed advanced human-like click via generic interface.")


def human_like_scroll(
    browser: BrowserInterface,
    element: ElementInterface,
    rng: Optional[random.Random] = None,
) -> None:
    """Scrolls to an element using a series of smaller, more natural scrolls."""
    _rng = rng if rng is not None else random.Random()

    for _ in range(_rng.randint(3, 7)):
        browser.scroll_by_offset(0, _rng.randint(50, 150))
        time.sleep(parabolic_delay(peak_time=0.2, rng=_rng))
    browser.move_mouse_to_element(element)


def human_like_page_scan(
    browser: BrowserInterface,
    max_scrolls: int = 6,
    rng: Optional[random.Random] = None,
) -> None:
    """Simulates a human scanning a page from top to bottom.

    This function scrolls down in random increments with reading pauses.
    It is superior to `window.scrollTo(0, bottom)` because:
    1. It triggers 'OnScroll' events that lazy-load images/jobs.
    2. It passes behavioral biometric checks (mouse wheel emulation).
    3. It handles 'Infinite Scroll' by detecting if the page grew.

    Args:
        browser: The active browser.
        max_scrolls: Safety limit to prevent infinite loops on endless pages.
        rng: Optional seeded random.Random for reproducibility.
    """
    _rng = rng if rng is not None else random.Random()
    logger.debug("Starting human-like page scan...")

    browser.execute_script("return document.body.scrollHeight")

    for _ in range(max_scrolls):
        scroll_amount = _rng.randint(250, 500)
        browser.scroll_by_offset(0, scroll_amount)
        time.sleep(parabolic_delay(peak_time=0.6, randomness=0.5, rng=_rng))

        new_height = browser.execute_script("return document.body.scrollHeight")
        current_y = browser.execute_script("return window.scrollY + window.innerHeight")

        if current_y >= new_height:
            logger.debug("Hit bottom. Waiting for potential lazy load...")
            time.sleep(2.0)
            updated_height = browser.execute_script("return document.body.scrollHeight")
            if updated_height == new_height:
                logger.debug("Page did not expand. Scan complete.")
                break
            else:
                logger.debug("Page expanded (Infinite Scroll). Continuing scan.")

        if _rng.random() > 0.85:
            browser.scroll_by_offset(0, -_rng.randint(50, 150))
            time.sleep(0.5)


def simulate_idle_time(
    browser: BrowserInterface,
    min_seconds: float = 1.0,
    max_seconds: float = 4.0,
    rng: Optional[random.Random] = None,
) -> None:
    """Simulates a user being idle on a page, performing small, random mouse 'fidgets'."""
    _rng = rng if rng is not None else random.Random()
    logger.debug("Simulating idle time...")
    end_time = time.time() + _rng.uniform(min_seconds, max_seconds)

    while time.time() < end_time:
        browser.perform_mouse_fidget()
        time.sleep(_rng.uniform(0.2, 0.6))