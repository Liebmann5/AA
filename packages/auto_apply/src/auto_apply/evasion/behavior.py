import logging
import random
import time
import math
from ..core.browser_interface import BrowserInterface, ElementInterface
from ..exceptions import ApplicationError

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
    for t in range(101):
        t /= 100
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

def human_like_mouse_move(browser: BrowserInterface, start_element: ElementInterface, end_element: ElementInterface):
    """
    Simulates a human-like, curved mouse movement from a starting point
    to a target element, using only generic interface methods.
    """
    browser.move_mouse_to_element(start_element)
    start_point = start_element.get_location()

    end_loc = end_element.get_location()
    end_size = end_element.get_size()
    end_point = (end_loc[0] + end_size[0] // 2, end_loc[1] + end_size[1] // 2)

    control1 = (start_point[0] + random.randint(-50, 50), start_point[1] + random.randint(50, 150))
    control2 = (end_point[0] + random.randint(-150, -50), end_point[1] + random.randint(-50, 50))

    curve = _generate_bezier_curve(start_point, end_point, [control1, control2])

    current_pos = start_point
    for point in curve:
        move_x = point[0] - current_pos[0]
        move_y = point[1] - current_pos[1]
        browser.move_mouse_by_offset(move_x, move_y)
        current_pos = point
        time.sleep(random.uniform(0.005, 0.015))

def _is_element_a_honeypot(browser: BrowserInterface, element: ElementInterface) -> bool:
    """Performs checks to determine if an element is a trap for bots."""
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
        logger.warning(f"Honeypot check failed with an error, assuming it's a trap: {e}")
        return True

def human_like_click(browser: BrowserInterface, element: ElementInterface):
    """
    Performs a highly realistic click on any element adapter, including
    hesitation and overshoot, using the generic interface methods.
    """
    if _is_element_a_honeypot(browser, element):
        raise ApplicationError(f"Element is suspected to be a honeypot trap.")

    browser.move_mouse_to_element(element, offset_x=random.randint(-10, 10), offset_y=random.randint(-10, 10))
    time.sleep(parabolic_delay(peak_time=0.3))

    browser.move_mouse_to_element(element)
    time.sleep(parabolic_delay(peak_time=0.1))

    element.click()
    logger.debug("Performed advanced human-like click via generic interface.")

def human_like_scroll(browser: BrowserInterface, element: ElementInterface):
    """Scrolls to an element using a series of smaller, more natural scrolls."""
    target_y = element.get_location()[1]
    for _ in range(random.randint(3, 7)):
        browser.scroll_by_offset(0, random.randint(50, 150))
        time.sleep(parabolic_delay(peak_time=0.2))
    browser.move_mouse_to_element(element)


def simulate_idle_time(browser: BrowserInterface, min_seconds: float = 1.0, max_seconds: float = 4.0):
    """Simulates a user being idle on a page, performing small, random mouse 'fidgets'."""
    logger.debug("Simulating idle time...")
    end_time = time.time() + random.uniform(min_seconds, max_seconds)

    while time.time() < end_time:
        browser.perform_mouse_fidget()
        time.sleep(random.uniform(0.2, 0.6))