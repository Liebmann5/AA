"""Concrete execution strategies for browser interaction.

Two implementations of the ExecutionStrategy protocol:

- StealthHumanStrategy  — human-like mouse paths, parabolic keystroke delays,
  and jittered inter-action pauses.  Use when bot-detection is a concern.
- InstantHeadlessStrategy — direct driver calls, no delays, no mouse curves.
  Use for headless CI, fast replay sessions, or any context where evasion is
  unnecessary.

Both classes satisfy the ExecutionStrategy Protocol defined in human_like_adapter
via structural subtyping — no explicit inheritance required.
"""

import logging
import random
import time

from auto_apply.adapters.secondary.evasion.components import behavior
from auto_apply.domain.ports.browser_port import BrowserInterface, ElementInterface

logger = logging.getLogger(__name__)


class StealthHumanStrategy:
    """Executes interactions with human-like timing, mouse paths, and jitter.

    All clicks travel a Bezier-curved mouse path with overshoot and hesitation.
    Keystrokes are paced with parabolic delays between characters.
    Inter-action pauses include ±20 % random jitter around the base delay.

    This strategy is mandatory for live browser sessions on job boards that
    deploy behavioural biometric checks (e.g. LinkedIn, Greenhouse, Workday).

    Args:
        base_inter_action_delay: Seconds between plan steps before jitter is
            applied.  Defaults to 0.5 s; minimum enforced at 0.1 s.
    """

    DEFAULT_INTER_ACTION_DELAY: float = 0.5

    def __init__(self, base_inter_action_delay: float = DEFAULT_INTER_ACTION_DELAY) -> None:
        self._base_delay = max(base_inter_action_delay, 0.1)

    def click(self, browser: BrowserInterface, element: ElementInterface) -> None:
        """Clicks via a curved mouse path with pre-click hesitation.

        Delegates to behavior.human_like_click, which moves the mouse in two
        passes (overshoot then correct) and injects parabolic pauses before
        the final click event.

        Args:
            browser: Active browser driver needed for low-level mouse actions.
            element: Target DOM element to click.
        """
        behavior.human_like_click(browser, element)

    def type_text(self, element: ElementInterface, text: str) -> None:
        """Types text character-by-character with parabolic inter-key delays.

        Args:
            element: Target input element.
            text: String to type.
        """
        behavior.human_like_typing(element, text)

    def hover(self, browser: BrowserInterface, element: ElementInterface) -> None:
        """Moves the mouse to the element with a small random offset and pause.

        Args:
            browser: Active browser driver.
            element: Element to hover over.
        """
        browser.move_mouse_to_element(
            element,
            offset_x=random.randint(-8, 8),
            offset_y=random.randint(-8, 8),
        )
        time.sleep(behavior.parabolic_delay(peak_time=0.15, randomness=0.3))

    def inter_action_delay(self) -> None:
        """Pauses between plan steps with ±20 % random jitter.

        Jitter prevents the constant-interval signature that bot detectors
        flag as machine-generated timing.
        """
        jitter = random.uniform(0.8, 1.2)
        time.sleep(self._base_delay * jitter)


class InstantHeadlessStrategy:
    """Executes interactions as fast as the driver allows — no delays, no curves.

    Suitable for:
    - Headless CI pipelines verifying form logic.
    - Fast-replay test sessions against a local dev ATS.
    - Any context where anti-bot evasion is not required.

    Every method issues the minimal driver call and returns immediately.
    """

    def click(self, browser: BrowserInterface, element: ElementInterface) -> None:
        """Clicks the element directly without mouse movement.

        Args:
            browser: Unused in this strategy; accepted for interface parity.
            element: Target DOM element to click.
        """
        element.click()

    def type_text(self, element: ElementInterface, text: str) -> None:
        """Sends the complete text string in a single driver call.

        Args:
            element: Target input element.
            text: String to type.
        """
        element.send_keys(text)

    def hover(self, browser: BrowserInterface, element: ElementInterface) -> None:
        """Moves the mouse to the element in one direct call, no pause.

        Args:
            browser: Active browser driver.
            element: Element to hover over.
        """
        browser.move_mouse_to_element(element)

    def inter_action_delay(self) -> None:
        """No-op — headless sessions apply no inter-action pause."""
