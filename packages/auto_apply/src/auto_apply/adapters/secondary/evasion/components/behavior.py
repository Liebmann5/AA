# File: adapters/evasion/components/behavior.py

import logging
import math
import random
import time

from auto_apply.domain.exceptions import ApplicationError
from auto_apply.domain.ports.browser_port import BrowserInterface, ElementInterface

logger = logging.getLogger(__name__)

def parabolic_delay(peak_time=0.15, randomness=0.3):
    """Generates a natural-seeming delay."""
    x = random.uniform(-1, 1)
    base_delay = (-x**2 + 1) * peak_time
    random_factor = random.uniform(1 - randomness, 1 + randomness)
    return abs(base_delay * random_factor)

def _generate_bezier_curve(start, end, control_points):
    """Generates points along a Bezier curve for smooth mouse movements."""
    points = []
    n = len(control_points) + 1
    for step in range(101):  # noqa: PLW2901 — t is intentionally reused as float
        t = step / 100
        x = (1 - t)**n * start[0] + (t**n * end[0])
        y = (1 - t)**n * start[1] + (t**n * end[1])

        for i in range(1, n):
            binomial_coeff = math.comb(n, i)
            term = binomial_coeff * ((1 - t)**(n - i)) * (t**i)
            x += term * control_points[i - 1][0]
            y += term * control_points[i - 1][1]
        points.append((int(x), int(y)))
    return points

def human_like_typing(element: ElementInterface, text: str):
    """Types text with variable, human-like delays into any element adapter."""
    for char in text:
        element.send_keys(char)
        time.sleep(parabolic_delay())

def human_like_mouse_move(browser: BrowserInterface, start_element: ElementInterface, end_element: ElementInterface):  # noqa: E501
    """
    Simulates a human-like, curved mouse movement from a starting point
    to a target element, using only generic interface methods.
    """
    browser.move_mouse_to_element(start_element)
    start_point = start_element.get_location()

    end_loc = end_element.get_location()
    end_size = end_element.get_size()
    end_point = (end_loc[0] + end_size[0] // 2, end_loc[1] + end_size[1] // 2)

    control1 = (start_point[0] + random.randint(-50, 50), start_point[1] + random.randint(50, 150))  # noqa: E501
    control2 = (end_point[0] + random.randint(-150, -50), end_point[1] + random.randint(-50, 50))  # noqa: E501

    curve = _generate_bezier_curve(start_point, end_point, [control1, control2])

    current_pos = start_point
    for point in curve:
        move_x = point[0] - current_pos[0]
        move_y = point[1] - current_pos[1]
        browser.move_mouse_by_offset(move_x, move_y)
        current_pos = point
        time.sleep(random.uniform(0.005, 0.015))

def _is_element_a_honeypot(browser: BrowserInterface, element: ElementInterface) -> bool:  # noqa: E501
    """Performs checks to determine if an element is a trap for bots."""
    #!
    # script = """
    # var elem = arguments[0];
    # if (window.getComputedStyle(elem).display === 'none') { return false; }
    # if (elem.offsetWidth === 0 || elem.offsetHeight === 0) { return false; }
    # var box = elem.getBoundingClientRect();
    # var cx = box.left + box.width / 2;
    # var cy = box.top + box.height / 2;
    # var e = document.elementFromPoint(cx, cy);
    # for (; e; e = e.parentElement) {
    #     if (e === elem) { return true; }
    # }
    # return false;
    # """
    # try:
    #     return not browser.execute_script(script, element)
    # except Exception as e:
    #     logger.warning(f"Honeypot check failed with an error, assuming it's a trap: {e}")  # noqa: E501
    #     return True
    # This check is currently too aggressive and is causing false positives.
    # We will temporarily disable it to focus on the core application logic.
    # We can re-introduce a more refined version later.
    logger.warning("Honeypot detection is temporarily disabled for debugging.")
    return False

def human_like_click(browser: BrowserInterface, element: ElementInterface):
    """
    Performs a highly realistic click on any element adapter, including
    hesitation and overshoot, using the generic interface methods.
    """
    if _is_element_a_honeypot(browser, element):
        raise ApplicationError("Element is suspected to be a honeypot trap.")

    browser.move_mouse_to_element(element, offset_x=random.randint(-10, 10), offset_y=random.randint(-10, 10))  # noqa: E501
    time.sleep(parabolic_delay(peak_time=0.3))

    browser.move_mouse_to_element(element)
    time.sleep(parabolic_delay(peak_time=0.1))

    element.click()
    logger.debug("Performed advanced human-like click via generic interface.")

def human_like_scroll(browser: BrowserInterface, element: ElementInterface):
    """Scrolls to an element using a series of smaller, more natural scrolls."""
    element.get_location()[1]
    for _ in range(random.randint(3, 7)):
        browser.scroll_by_offset(0, random.randint(50, 150))
        time.sleep(parabolic_delay(peak_time=0.2))
    browser.move_mouse_to_element(element)

def human_like_page_scan(browser: BrowserInterface, max_scrolls: int = 20) -> None:
    """Simulates a human scanning a page from top to bottom.

    This function scrolls down in random increments with reading pauses.
    It is superior to `window.scrollTo(0, bottom)` because:
    1. It triggers 'OnScroll' events that lazy-load images/jobs.
    2. It passes behavioral biometric checks (mouse wheel emulation).
    3. It handles 'Infinite Scroll' by detecting if the page grew.

    Args:
        browser (BrowserInterface): The active browser.
        max_scrolls (int): Safety limit to prevent infinite loops on endless pages.
    """
    logger.debug("Starting human-like page scan...")

    browser.execute_script("return document.body.scrollHeight")

    for _ in range(max_scrolls):
        # 1. Random Scroll Amount (roughly one screen view or less)
        scroll_amount = random.randint(300, 700)

        # 2. Perform the scroll using the mouse wheel logic (smoother)
        # Note: We scroll Y, X is 0.
        browser.scroll_by_offset(0, scroll_amount)

        # 3. Reading Pause (Parabolic delay is perfect here)
        time.sleep(parabolic_delay(peak_time=1.0, randomness=0.5))

        # 4. Check for 'Infinite Scroll' expansion
        new_height = browser.execute_script("return document.body.scrollHeight")

        # If we are near the bottom, logic to break
        current_y = browser.execute_script("return window.scrollY + window.innerHeight")

        if current_y >= new_height:
            # We hit the bottom. Wait to see if more content loads (Network latency)
            logger.debug("Hit bottom. Waiting for potential lazy load...")
            time.sleep(2.0)

            # Check height again
            updated_height = browser.execute_script("return document.body.scrollHeight")
            if updated_height == new_height:
                logger.debug("Page did not expand. Scan complete.")
                break
            else:
                logger.debug("Page expanded (Infinite Scroll). Continuing scan.")

        # 5. Occasional "Micro-Reverse" (Simulates re-reading something)
        if random.random() > 0.85:
            browser.scroll_by_offset(0, -random.randint(50, 150))
            time.sleep(0.5)

def simulate_idle_time(browser: BrowserInterface, min_seconds: float = 1.0, max_seconds: float = 4.0):  # noqa: E501
    """Simulates a user being idle on a page, performing small, random mouse 'fidgets'."""  # noqa: E501
    logger.debug("Simulating idle time...")
    end_time = time.time() + random.uniform(min_seconds, max_seconds)

    while time.time() < end_time:
        browser.perform_mouse_fidget()
        time.sleep(random.uniform(0.2, 0.6))
