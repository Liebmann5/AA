"""Single point of entry for all browser interaction in domain engines.

This module provides PageActionService — the layer between every domain engine
(Discovery, Vetting, Applications) and the raw BrowserInterface/ElementInterface
adapters. All navigation, element interaction, and human-timing logic lives here.

Why This Exists (The DRY Problem):
    Before this service, each domain engine maintained its own version of:
      - safe_navigate()       — 3 near-identical copies across discovery providers
      - human_like_click()    — imported as a free function into every call site
      - parabolic_delay()     — scattered across 6+ files with no shared config
      - clear-and-type logic  — ad hoc in every form-filling component

    Every timing change required hunting down every call site. No single place
    controlled the human-behavior envelope. PageActionService fixes that.

Adapter Contract — What This Service May and May Not Assume:
    This service interacts ONLY through BrowserInterface and ElementInterface.
    It never:
      - Imports from selenium, playwright, or any adapter module
      - Checks framework_name to branch behavior (that is the adapter's job)
      - Uses raw Unicode key codes (\ue009, etc.) — those are Selenium-only
      - Assumes any method beyond what BrowserInterface/ElementInterface define

    All keyboard constants come from domain.types.Keys. All locator constants
    come from domain.types.Locator. Neither is redeclared here.

Two-Timescale Human Behavior Model:
    Bot detection systems (PerimeterX, DataDome, Akamai) use ML models trained
    on timing distributions. They flag uniform behavior at any speed — a session
    that is consistently fast is obviously a bot; a session that is consistently
    slow is also suspicious and triggers session-timeout re-challenges.

    What defeats these systems is variance at *human-consistent timescales*.
    Real human behavior has two distinct rhythm layers:

    MICRO timing — intra-task: keystrokes, cursor moves within a field, hover.
        Fast: peak ~80ms, high entropy. This is finger-movement time.

    MACRO timing — inter-task: after navigation, after a form page transition,
        between filling unrelated fields. Slow: 1.5–5.0s. This is reading time.

    PageActionService models both explicitly. `_micro_delay()` governs everything
    within a single interaction. `macro_pause()` governs transitions between
    tasks. Domain engines call `macro_pause()` explicitly at task boundaries.

Configuration:
    All timing parameters come from CapabilitiesRegistry.get_all_effective_config(),
    which has already applied low-resource overrides. The service reads the
    resolved values at construction; low-resource mode simply widens the delays
    and disables mouse-movement fingerprinting automatically.

Usage:
    Domain engines receive PageActionService at construction:

    >>> class DiscoveryEngine:
    ...     def __init__(self, page_action: PageActionService, ...):
    ...         self.page = page_action
    ...
    ...     def run(self):
    ...         if self.page.navigate("https://linkedin.com/jobs"):
    ...             self.page.macro_pause()
    ...             cards = self.page.find_all(Locator.CSS_SELECTOR, ".job-card")
"""

import logging
import random
import time
from typing import Callable

from auto_apply.domain.ports.browser_port import BrowserInterface, ElementInterface
from auto_apply.domain.types import (  # FIXED: was `from core.types import Keys, Locator`  # noqa: E501
    Locator,
)

from auto_apply.domain.ports.registry_port import RegistryPort

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Result Type
# ─────────────────────────────────────────────────────────────────────────────

class ActionResult:
    """Typed result from every PageActionService operation.

    Evaluates as bool (True = success) for concise `if page.click(btn):` usage,
    while also carrying `reason` for diagnostic logging on failure.

    Attributes:
        success: True if the operation completed as intended.
        reason:  Human-readable description of why it failed, or "ok".
        element: The element acted on, if the operation produced one.
    """
    __slots__ = ("success", "reason", "element")

    def __init__(
        self,
        success: bool,
        reason: str = "ok",
        element: ElementInterface | None = None,
    ) -> None:
        self.success = success
        self.reason  = reason
        self.element = element

    def __bool__(self) -> bool:
        return self.success

    def __repr__(self) -> str:
        return f"ActionResult(success={self.success}, reason={self.reason!r})"


# ─────────────────────────────────────────────────────────────────────────────
# Page Action Service
# ─────────────────────────────────────────────────────────────────────────────

class PageActionService:
    """Unified browser interaction API for all domain engines.

    Owns all human-timing, element location, and interaction logic.
    Speaks only through BrowserInterface and ElementInterface — never
    touches adapter internals.

    Args:
        browser: The active BrowserInterface (Selenium or Playwright adapter).
        registry: The session CapabilitiesRegistry. Timing config is read
            from its resolved effective_config at construction time.
        rng: Optional seeded random.Random for deterministic behaviour.
            If None, a fresh unseeded random.Random() is used.

    Example:
        >>> page = PageActionService(browser=driver, registry=registry)
        >>> if page.navigate("https://greenhouse.io/jobs/12345"):
        ...     page.macro_pause()
        ...     btn = page.wait_for(Locator.CSS_SELECTOR, "button.apply-btn")
        ...     if btn:
        ...         page.click(btn)
    """

    def __init__(
        self,
        browser: BrowserInterface,
        registry: RegistryPort,
        rng: random.Random | None = None,
    ) -> None:
        self._browser = browser
        self._rng = rng if rng is not None else random.Random()

        # Resolved from registry — already low-resource-adjusted.
        cfg = registry.get_all_effective_config()

        # MICRO timing: intra-task delays (keystrokes, between micro-actions).
        self._micro_peak_ms: float = float(cfg.get("micro_timing_peak_ms", 80.0))

        # MACRO timing: inter-task pauses (post-navigation, between form pages).
        self._macro_min_s:   float = float(cfg.get("macro_pause_min_s", 1.5))
        self._macro_max_s:   float = float(cfg.get("macro_pause_max_s", 4.5))

        # Post-action settle: after clicks, scrolls, selects — within a task.
        self._settle_min_s:  float = float(cfg.get("settle_min_s", 0.3))
        self._settle_max_s:  float = float(cfg.get("settle_max_s", 1.2))

        # Action-pacing FLOOR. The registry raises min_action_delay_ms in
        # low-resource mode (e.g. 500ms -> 800ms); it is the minimum time that
        # should elapse between actions. It floors the settle pause (the
        # between-actions rhythm) so a weak machine is genuinely paced slower —
        # macro pauses are already well above it and micro (keystroke) timing is
        # a different rhythm, so this is the floor's single, correct consumer.
        self._min_action_delay_s: float = max(
            0.0, float(cfg.get("min_action_delay_ms", 500)) / 1000.0
        )

        # One-time warmup: a human opens the browser and orients before their
        # first navigation. Firing the first request the instant the driver is
        # ready is a bot signal (it contributed to the immediate CAPTCHA on
        # Google). navigate() performs a single warmup pause before the first
        # load. This is one factor, not a silver bullet, and is fully
        # config-driven (macro range + the floor above) so it can be measured.
        self._warmed_up: bool = False

        # Feature flags — determined by hardware and admin policy.
        self._human_timing:  bool = bool(cfg.get("enable_human_timing",        True))
        self._fingerprint:   bool = bool(cfg.get("enable_fingerprint_spoofing", True))

        # NAVIGATION resilience: bounded retry count for failed page loads.
        # This is a navigation *policy* (how many attempts before giving up),
        # not a human-timing value. See navigate() and its traversal-graph note.
        self._navigation_retries: int = max(1, int(cfg.get("navigation_retries", 3)))
        self._infinite_scroll_settle_s: float = float(
            cfg.get("infinite_scroll_settle_s", 2.0)
        )
        self._occlusion_guard: bool = bool(cfg.get("occlusion_guard", True))

        logger.debug(
            "PageActionService ready | micro_peak=%.0fms "
            "macro=[%.1f–%.1fs] fingerprint=%s",
            self._micro_peak_ms,
            self._macro_min_s, self._macro_max_s,
            self._fingerprint,
        )

    # =========================================================================
    # NAVIGATION
    # =========================================================================

    def navigate(
        self,
        url: str,
        *,
        next_candidate: "Callable[[str, int], str | None] | None" = None,
    ) -> ActionResult:
        """Navigates to a URL, retrying up to ``navigation_retries`` times.

        A failed load is retried, bounded by the resolved ``navigation_retries``
        config value, so a genuinely dead URL is abandoned instead of hanging
        the session — the "give up after N tries" limit. A successful load
        returns immediately (a single attempt); the count is a ceiling, not a
        quota.

        The settle pause is a MACRO pause — it models the time a human spends
        visually orienting to a newly loaded page before acting. Domain engines
        should NOT add their own sleep after calling this.

        Args:
            url: The fully qualified URL to load.
            next_candidate: [TRAVERSAL-GRAPH SEAM — see NOTE below] Optional
                callable ``(failed_target, attempt_number) -> next_target |
                None``. Its return value becomes the target for the next
                attempt; returning ``None`` gives up early. When omitted
                (today's default) every retry re-attempts the SAME url.

        Returns:
            ActionResult. success=True if a load completed without exception;
            on failure, reason holds the last error encountered.

        NOTE — Application Traversal Graph integration (planned, not yet built):
            ``navigation_retries`` is meant to bound a *search* for a working
            target, not blind repetition of one URL. ``next_candidate`` is the
            single seam for that search, and it is deliberately the only thing
            the future graph needs to touch:

              * This loop already bounds attempts at ``navigation_retries`` and
                reports give-up cleanly, so the graph never has to own the
                budget or the stop condition.
              * When the graph lands, the composition root injects a
                ``next_candidate`` backed by a graph walk: on each failed
                attempt it returns the next candidate link/path/url. No change
                to this method's control flow is required — only the injected
                callable. Keep this seam and its signature intact.

            Until then, leaving ``next_candidate=None`` preserves today's
            behaviour exactly (retry the same url), so wiring the graph later is
            purely additive.

        Example:
            >>> if not page.navigate("https://lever.co/company/job-abc"):
            ...     return  # Navigation failed after retries; abort this job
        """
        attempts = max(1, self._navigation_retries)
        target = url
        last_reason = "navigation not attempted"
        # Warm up once before the very first load of the session (CAPTCHA
        # mitigation). No-op on every subsequent navigation.
        self.warmup_pause()
        for attempt in range(1, attempts + 1):
            try:
                logger.debug("navigate | attempt=%d/%d url=%s", attempt, attempts, target)
                self._browser.get(target)
                self.macro_pause()   # Simulate reading the freshly loaded page.
                return ActionResult(True)
            except Exception as exc:
                last_reason = str(exc)
                logger.warning(
                    "navigate failed | attempt=%d/%d url=%s error=%s",
                    attempt, attempts, target, exc,
                )
                if attempt < attempts:
                    # TRAVERSAL-GRAPH SEAM: choose the next target to try. Today
                    # this repeats the same url; the graph will supply the next
                    # candidate here. See the NOTE in this method's docstring.
                    if next_candidate is not None:
                        proposed = next_candidate(target, attempt)
                        if proposed is None:
                            break
                        target = proposed
                    self._settle_pause()   # brief backoff before retrying
        return ActionResult(False, reason=last_reason)


    def navigate_back(self) -> ActionResult:
        """Navigates back one step using the interface's back() method.

        Returns:
            ActionResult indicating whether the navigation succeeded.
        """
        try:
            self._browser.back()
            self.macro_pause()
            return ActionResult(True)
        except Exception as exc:
            logger.warning("navigate_back failed | %s", exc)
            return ActionResult(False, reason=str(exc))

    def navigate_to_blank(self) -> ActionResult:
        """Loads about:blank to reset browser state between strategy attempts.

        Used by the orchestrator before BrowserCascade retries with a
        different navigation strategy — ensures no stale DOM, event handlers,
        or origin-bound state bleeds into the next attempt.

        Returns:
            ActionResult indicating whether the blank load succeeded.
        """
        try:
            self._browser.get("about:blank")
            self._settle_pause()
            return ActionResult(True)
        except Exception as exc:
            logger.warning("navigate_to_blank failed | %s", exc)
            return ActionResult(False, reason=str(exc))

    def current_url(self) -> str:
        """Returns the current page URL, or an empty string on failure."""
        try:
            return self._browser.current_url or ""
        except Exception:
            return ""

    def page_title(self) -> str:
        """Returns the current page title, or an empty string on failure."""
        try:
            return self._browser.title or ""
        except Exception:
            return ""

    def page_source(self) -> str:
        """Returns the full page HTML source, or an empty string on failure."""
        try:
            return self._browser.page_source or ""
        except Exception:
            return ""

    # =========================================================================
    # ELEMENT LOCATION
    # =========================================================================

    def find(self, by: str, selector: str) -> ElementInterface | None:
        """Returns the first matching element, or None if not found.

        Args:
            by: Locator strategy constant from domain.types.Locator.
            selector: The selector string.

        Returns:
            ElementInterface or None.

        Example:
            >>> btn = page.find(Locator.CSS_SELECTOR, "button.submit-app")
        """
        try:
            return self._browser.find_element(by, selector)
        except Exception:
            return None

    def find_all(self, by: str, selector: str) -> list[ElementInterface]:
        """Returns all matching elements, or an empty list if none found.

        Args:
            by: Locator strategy constant from domain.types.Locator.
            selector: The selector string.

        Returns:
            List of ElementInterface. Never raises.

        Example:
            >>> cards = page.find_all(Locator.CSS_SELECTOR, ".job-card-list li")
        """
        try:
            return self._browser.find_elements(by, selector) or []
        except Exception:
            return []

    def wait_for(
        self,
        by: str,
        selector: str,
        timeout: int = 10,
    ) -> ElementInterface | None:
        """Delegates to the browser adapter's wait_for_element implementation.

        Args:
            by: Locator strategy constant.
            selector: The selector string.
            timeout: Maximum seconds to wait. Default 10.

        Returns:
            The element if found within timeout, or None.
        """
        try:
            return self._browser.wait_for_element(by, selector, timeout=timeout)
        except Exception:
            return None

    def wait_for_any(
        self,
        candidates: list[tuple[str, str]],
        timeout: int = 10,
    ) -> tuple[int, ElementInterface] | None:
        """Polls until any one of several (by, selector) pairs matches.

        Args:
            candidates: List of (by, selector) tuples to check in order.
            timeout: Maximum seconds to wait total.

        Returns:
            (index, element) for the first matching candidate, or None.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for idx, (by, sel) in enumerate(candidates):
                el = self.find(by, sel)
                if el is not None:
                    return (idx, el)
            time.sleep(0.4)
        return None

    def is_present(self, by: str, selector: str) -> bool:
        """Returns True if at least one matching element exists in the DOM."""
        return self.find(by, selector) is not None

    # =========================================================================
    # CLICK
    # =========================================================================

    #: Classifies a click target. Returns one of:
    #:   "ok"            - the target (or a descendant) is topmost at its centre
    #:   "hidden"        - display:none or zero-sized: a classic honeypot shape
    #:   "occluded:<tag>" - something unrelated is on top of it
    #:   "offscreen"     - outside the viewport, so elementFromPoint cannot judge
    _REACHABILITY_SCRIPT = """
    var elem = arguments[0];
    if (window.getComputedStyle(elem).display === 'none') { return 'hidden'; }
    if (elem.offsetWidth === 0 || elem.offsetHeight === 0) { return 'hidden'; }
    var box = elem.getBoundingClientRect();
    var cx = box.left + box.width / 2;
    var cy = box.top + box.height / 2;
    if (cx < 0 || cy < 0 || cx > window.innerWidth || cy > window.innerHeight) {
        return 'offscreen';
    }
    var top = document.elementFromPoint(cx, cy);
    if (!top) { return 'offscreen'; }
    for (var e = top; e; e = e.parentElement) {
        if (e === elem) { return 'ok'; }
    }
    for (var a = elem; a; a = a.parentElement) {
        if (a === top) { return 'ok'; }
    }
    return 'occluded:' + (top.tagName || '?').toLowerCase();
    """

    def _click_target_reachable(self, element: ElementInterface) -> tuple[bool | None, str]:
        """Judges whether a click will land on the intended element.

        Three outcomes, and the third is the important one:

        * ``True``  - the target, or something inside it, is topmost.
        * ``False`` - something unrelated covers it, or it is hidden/zero-sized
          (the classic honeypot shape).
        * ``None``  - undetermined: the element is outside the viewport, or the
          probe failed. **Undetermined proceeds.** The predecessor of this check
          treated every error as a trap and was disabled for being "too
          aggressive"; refusing to click because we could not look is how a
          guard becomes worse than no guard.

        Args:
            element: The element about to be clicked.

        Returns:
            ``(verdict, detail)`` where verdict is True/False/None.
        """
        try:
            verdict = self._browser.execute_script(
                self._REACHABILITY_SCRIPT, element
            )
        except Exception as exc:
            logger.debug("occlusion probe failed, proceeding | %s", exc)
            return None, "probe failed"

        if verdict == "ok":
            return True, "reachable"
        if verdict == "offscreen" or not verdict:
            return None, "outside the viewport"
        return False, str(verdict)

    def click(self, element: ElementInterface) -> ActionResult:
        """Performs a human-like click on an element.

        With fingerprint spoofing enabled:
            1. Move mouse to element with slight random offset (overshoot).
            2. Micro-pause.
            3. Re-center mouse on element.
            4. Micro-pause (hesitation before committing).
            5. Click.
            6. Settle pause.

        Without fingerprint spoofing (low-resource or admin-disabled):
            1. Click directly.
            2. Settle pause.

        Args:
            element: The ElementInterface to click.

        Returns:
            ActionResult. success=True if the click completed.
        """
        if self._occlusion_guard:
            reachable, detail = self._click_target_reachable(element)
            if reachable is False:
                # Most occlusion is a sticky header or a banner that a
                # scroll resolves, so look again before refusing.
                self.scroll_to(element)
                reachable, detail = self._click_target_reachable(element)
            if reachable is False:
                logger.warning(
                    "click refused: target is not clickable (%s)", detail
                )
                return ActionResult(
                    False, reason=f"click target not reachable: {detail}"
                )

        try:
            if self._fingerprint:
                self._browser.move_mouse_to_element(
                    element,
                    offset_x=self._rng.randint(-9, 9),
                    offset_y=self._rng.randint(-9, 9),
                )
                time.sleep(self._micro_delay(peak_ms=250))
                self._browser.move_mouse_to_element(element)
                time.sleep(self._micro_delay(peak_ms=70))

            element.click()
            self._settle_pause()
            return ActionResult(True, element=element)

        except Exception as exc:
            logger.warning("click failed | %s", exc)
            return ActionResult(False, reason=str(exc))

    def click_by(self, by: str, selector: str) -> ActionResult:
        """Convenience: finds an element and clicks it in one call.

        Args:
            by: Locator strategy constant.
            selector: The selector string.

        Returns:
            ActionResult. success=False if element not found or click failed.
        """
        element = self.find(by, selector)
        if element is None:
            return ActionResult(False, reason=f"element not found: {selector!r}")
        return self.click(element)

    # =========================================================================
    # TEXT INPUT
    # =========================================================================

    def type_text(self, element: ElementInterface, text: str) -> ActionResult:
        """Types text into a focused element character by character.

        Args:
            element: The input or textarea element to type into.
            text: The string to type. May include Keys.ENTER, Keys.TAB, etc.

        Returns:
            ActionResult. success=True if all text was typed.
        """
        try:
            self.click(element)
            for char in text:
                element.send_keys(char)
                if self._human_timing:
                    time.sleep(self._micro_delay(
                        peak_ms=self._micro_peak_ms,
                        randomness=0.45,
                    ))
            self._settle_pause()
            return ActionResult(True)
        except Exception as exc:
            logger.warning("type_text failed | %s", exc)
            return ActionResult(False, reason=str(exc))

    def clear_and_type(self, element: ElementInterface, text: str) -> ActionResult:
        """Clears an input field and types new text.

        Args:
            element: The input element to clear and refill.
            text: The new value to type.

        Returns:
            ActionResult. success=True if clear and type both completed.
        """
        try:
            self._browser.execute_script(
                "arguments[0].value = ''; "
                "arguments[0].dispatchEvent(new Event('input', {bubbles: true})); "
                "arguments[0].dispatchEvent(new Event('change', {bubbles: true}));",
                element,
            )
            time.sleep(self._micro_delay(peak_ms=100))
            return self.type_text(element, text)
        except Exception as exc:
            logger.warning("clear_and_type failed | %s", exc)
            return ActionResult(False, reason=str(exc))

    # =========================================================================
    # SELECT / CHECKBOX
    # =========================================================================

    def select_option(
        self,
        select_element: ElementInterface,
        *,
        by_value: str | None = None,
        by_text:  str | None = None,
        by_index: int | None = None,
    ) -> ActionResult:
        """Selects an option in a <select> dropdown element.

        Exactly one keyword argument must be provided.

        Args:
            select_element: The <select> ElementInterface.
            by_value: Match by the option's 'value' attribute.
            by_text:  Match by the option's visible text content.
            by_index: Select by 0-based position in the option list.

        Returns:
            ActionResult. success=True if the option was selected.
        """
        provided = sum(x is not None for x in (by_value, by_text, by_index))
        if provided != 1:
            raise ValueError(
                "select_option requires exactly one of: by_value, by_text, by_index"
            )

        try:
            options = select_element.find_elements(Locator.TAG_NAME, "option")

            if options:
                for i, opt in enumerate(options):
                    match = (
                        (by_value is not None and opt.get_attribute("value") == by_value)  # noqa: E501
                        or (by_text  is not None and opt.text.strip() == by_text.strip())  # noqa: E501
                        or (by_index is not None and i == by_index)
                    )
                    if match:
                        opt.click()
                        self._settle_pause()
                        return ActionResult(True)

                available = [opt.text.strip() for opt in options[:10]]
                logger.warning(
                    "select_option: no match | "
                    "by_value=%r by_text=%r by_index=%r available=%s",
                    by_value, by_text, by_index, available,
                )

            if by_value is not None:
                self._browser.execute_script(
                    "var s=arguments[0],v=arguments[1];"
                    "for(var i=0;i<s.options.length;i++){"
                    "  if(s.options[i].value===v){"
                    "    s.selectedIndex=i;"
                    "    s.dispatchEvent(new Event('change',{bubbles:true}));"
                    "    break;"
                    "  }"
                    "}",
                    select_element, by_value,
                )
                self._settle_pause()
                return ActionResult(True)

            if by_text is not None:
                self._browser.execute_script(
                    "var s=arguments[0],t=arguments[1].trim();"
                    "for(var i=0;i<s.options.length;i++){"
                    "  if(s.options[i].text.trim()===t){"
                    "    s.selectedIndex=i;"
                    "    s.dispatchEvent(new Event('change',{bubbles:true}));"
                    "    break;"
                    "  }"
                    "}",
                    select_element, by_text,
                )
                self._settle_pause()
                return ActionResult(True)

            if by_index is not None:
                self._browser.execute_script(
                    "var s=arguments[0];"
                    "s.selectedIndex=arguments[1];"
                    "s.dispatchEvent(new Event('change',{bubbles:true}));",
                    select_element, by_index,
                )
                self._settle_pause()
                return ActionResult(True)

        except Exception as exc:
            logger.warning("select_option failed | %s", exc)
            return ActionResult(False, reason=str(exc))

        return ActionResult(False, reason="select_option: no strategy succeeded")

    def check_checkbox(
        self,
        element: ElementInterface,
        desired: bool = True,
    ) -> ActionResult:
        """Sets a checkbox to the desired checked state.

        Args:
            element: The checkbox input ElementInterface.
            desired: True to check, False to uncheck. Default True.

        Returns:
            ActionResult. success=True if the state is now as desired.
        """
        try:
            is_checked = self._browser.execute_script(
                "return arguments[0].checked;", element
            )
            if bool(is_checked) != desired:
                return self.click(element)
            return ActionResult(True)
        except Exception as exc:
            logger.warning("check_checkbox failed | %s", exc)
            return ActionResult(False, reason=str(exc))

    # =========================================================================
    # SCROLL
    # =========================================================================

    def scroll_to(self, element: ElementInterface) -> ActionResult:
        """Scrolls an element into view with a human-like approach.

        Args:
            element: The element to bring into view.

        Returns:
            ActionResult. success=True if scrolling completed.
        """
        try:
            self._browser.execute_script(
                "arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});",
                element,
            )

            if self._fingerprint:
                loc = element.get_location()
                if loc:
                    target_y = loc[1]
                    steps = self._rng.randint(3, 6)
                    increment = max(1, target_y // max(1, steps))
                    for _ in range(steps):
                        self._browser.scroll_by_offset(0, increment)
                        time.sleep(self._micro_delay(peak_ms=140))

            self._settle_pause()
            return ActionResult(True)
        except Exception as exc:
            logger.warning("scroll_to failed | %s", exc)
            return ActionResult(False, reason=str(exc))

    def scroll_to_bottom(self) -> bool:
        """Scrolls to the bottom once and reports whether the page grew.

        The single-step primitive behind infinite scroll. It is deliberately
        ONE step: the caller owns the loop, because the loop is where the
        dry-scroll guard and the result cap live — the guard that stopped a
        live run scrolling Google for four minutes re-mining the same six jobs.

        The settle after scrolling comes from ``infinite_scroll_settle_s``
        (default 2.0, today's literal), so lazy-loaded content has time to
        arrive without a magic number in the caller.

        Returns:
            True if the document grew (new content loaded), False at the
            bottom of the feed or on error.
        """
        try:
            before = self._browser.execute_script(
                "return document.body.scrollHeight"
            )
            self._browser.execute_script(
                "window.scrollTo(0, document.body.scrollHeight);"
            )
            time.sleep(self._infinite_scroll_settle_s)
            after = self._browser.execute_script(
                "return document.body.scrollHeight"
            )
            return bool(after > before)
        except Exception as exc:
            logger.warning("scroll_to_bottom failed | %s", exc)
            return False

    def scroll_page(self, max_scrolls: int = 20) -> int:
        """Performs a full-page scan with infinite-scroll detection.

        Args:
            max_scrolls: Maximum scroll iterations. Safety ceiling. Default 20.

        Returns:
            The number of scroll steps actually performed.
        """
        steps = 0
        try:
            for _ in range(max_scrolls):
                self._browser.scroll_by_offset(0, self._rng.randint(280, 680))
                steps += 1

                pause = (
                    self._micro_delay(peak_ms=900, randomness=0.5)
                    if self._human_timing else 0.25
                )
                time.sleep(pause)

                current_y   = self._browser.execute_script(
                    "return window.scrollY + window.innerHeight"
                )
                page_height = self._browser.execute_script(
                    "return document.body.scrollHeight"
                )

                if current_y >= page_height:
                    time.sleep(2.0)
                    new_height = self._browser.execute_script(
                        "return document.body.scrollHeight"
                    )
                    if new_height <= page_height:
                        logger.debug("scroll_page: bottom reached | steps=%d", steps)
                        break

                if self._rng.random() > 0.82:
                    self._browser.scroll_by_offset(0, -self._rng.randint(60, 180))
                    time.sleep(self._micro_delay(peak_ms=400))

        except Exception as exc:
            logger.warning("scroll_page error | %s", exc)

        return steps

    # =========================================================================
    # TIMING — PUBLIC
    # =========================================================================

    def settle(self) -> None:
        """Short post-action pause — the tool's public pacing primitive.

        Every caller that needs "wait a beat after acting" uses this instead of
        its own sleep, so the duration stays config-driven (floored by
        ``min_action_delay_ms``, widened in low-resource mode) and seeded in one
        place. Internally identical to the settle applied after the tool's own
        click/type/scroll operations.
        """
        self._settle_pause()

    def macro_pause(
        self,
        min_s: float | None = None,
        max_s: float | None = None,
    ) -> None:
        """Simulates a human reading/thinking pause between tasks.

        Domain engines call this explicitly at task boundaries:
        - After navigation (reading the loaded page)
        - After a form page transition (reading the new step)
        - After captcha resolves (re-orienting before continuing)
        - Before submitting (final review pause)

        Args:
            min_s: Override minimum seconds. Uses registry value if None.
            max_s: Override maximum seconds. Uses registry value if None.
        """
        lo = min_s if min_s is not None else self._macro_min_s
        hi = max_s if max_s is not None else self._macro_max_s

        if not self._human_timing:
            time.sleep(lo)
            return

        if self._rng.random() < 0.70:
            duration = self._rng.uniform(lo, lo + (hi - lo) * 0.5)
        else:
            duration = self._rng.uniform(lo + (hi - lo) * 0.4, hi)

        if self._fingerprint:
            self._idle_with_fidgets(duration)
        else:
            time.sleep(duration)

    # =========================================================================
    # TIMING — INTERNAL
    # =========================================================================

    def _micro_delay(self, peak_ms: float = 80.0, randomness: float = 0.35) -> float:
        """Returns a parabolic intra-task delay in seconds."""
        if not self._human_timing:
            return max(0.02, (peak_ms / 1000.0) * 0.4)

        x = self._rng.uniform(-1.0, 1.0)
        base = (-x * x + 1.0) * (peak_ms / 1000.0)
        factor = self._rng.uniform(1.0 - randomness, 1.0 + randomness)
        return max(0.01, abs(base * factor))

    def _settle_pause(self) -> None:
        """Short post-action pause within a task, floored by min_action_delay_ms.

        The floor (low-resource-clamped by the registry) is the minimum time
        between actions, so it raises the settle range's lower bound; the upper
        bound is widened to match if the floor exceeds it, keeping lo <= hi.
        """
        lo = max(self._settle_min_s, self._min_action_delay_s)
        hi = max(self._settle_max_s, lo)
        if not self._human_timing:
            time.sleep(lo)
            return
        time.sleep(self._rng.uniform(lo, hi))

    def warmup_pause(self) -> None:
        """One-time pause before the first navigation of the session.

        Models a human orienting before acting. Uses the MACRO range (no new
        timing knobs) but floored by min_action_delay_ms, jittered via the
        seeded rng, and gated by enable_human_timing. Idempotent per instance:
        after the first call it is a no-op. Called by navigate(); callers do not
        invoke it directly.
        """
        if self._warmed_up:
            return
        self._warmed_up = True
        lo = max(self._macro_min_s, self._min_action_delay_s)
        hi = max(self._macro_max_s, lo)
        if not self._human_timing:
            time.sleep(lo)
            return
        time.sleep(self._rng.uniform(lo, hi))

    def _idle_with_fidgets(self, duration: float) -> None:
        """Sleeps for `duration` seconds with random mouse micro-movements."""
        end = time.monotonic() + duration
        while time.monotonic() < end:
            try:
                self._browser.perform_mouse_fidget()
            except Exception:
                pass
            time.sleep(self._rng.uniform(0.2, 0.7))

    # =========================================================================
    # ESCAPE HATCH
    # =========================================================================

    def execute_script(self, script: str, *args) -> object | None:
        """Executes JavaScript via the adapter's execute_script.

        Provided as a controlled escape hatch for domain-specific situations
        where no higher-level service method is sufficient. Prefer the
        higher-level methods and use this sparingly.

        Args:
            script: The JavaScript code to run.
            *args:  Arguments passed as arguments[0], arguments[1], etc.

        Returns:
            The script's return value, or None on failure.
        """
        try:
            return self._browser.execute_script(script, *args)
        except Exception as exc:
            logger.warning("execute_script failed | %s", exc)
            return None

    # =========================================================================
    # DIAGNOSTICS
    # =========================================================================

    def __repr__(self) -> str:
        return (
            f"PageActionService("
            f"micro_peak={self._micro_peak_ms:.0f}ms, "
            f"macro=[{self._macro_min_s:.1f}–{self._macro_max_s:.1f}s], "
            f"fingerprint={self._fingerprint})"
        )