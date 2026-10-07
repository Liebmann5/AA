"""PageActionService — the single point of entry for all browser interaction.

This is the FACADE every caller uses; nothing about its public surface
changed when the implementation was split (call 2). The concerns live in
sibling modules, each owning its piece exactly once:

    result.py     — ActionResult, the shared currency
    state.py      — PageActionContext, the one shared state object
    probe.py      — TargetProbe: geometry, reachability, panes, frames, effect
    pacing.py     — Pacing: settle, macro pause, warmup, idle fidgets
    scrolling.py  — Scroller: into view (pane-aware), container, feed, reveal
    clicking.py   — Clicker: the click ladder and hover
    text_input.py — Typer: text entry, select and checkbox values

The facade keeps only what is genuinely its own: navigation (with bounded
retries and the one-time warmup), element location, the public timing
primitives, and one-line delegation for everything else. The boundary is
pinned by tests/architecture/test_page_action_boundary.py.

Adapter Contract — What This Service May and May Not Assume:
    Interacts ONLY through BrowserInterface and ElementInterface. It never
    imports from selenium/playwright, never branches on framework_name,
    never uses raw Unicode key codes, and never assumes a method beyond the
    ports. Keyboard constants come from domain.types.Keys; locator constants
    from domain.types.Locator.

Two-Timescale Human Behavior Model (see pacing.py):
    MICRO timing — intra-task: keystrokes, cursor moves within a field.
    MACRO timing — inter-task: after navigation, between form pages.
    Variance at human-consistent timescales is what defeats timing-ML bot
    detection; uniform speed at ANY rate is the bot signature.

Configuration:
    All timing parameters come from the registry's resolved effective config
    (already low-resource-adjusted) via the shared context. Deterministic
    mode: pass seeded RNGs; the composition root allocates the namespaces.

Usage:
    >>> page = PageActionService(browser=driver, registry=registry)
    >>> if page.navigate("https://greenhouse.io/jobs/12345"):
    ...     page.macro_pause()
    ...     btn = page.wait_for(Locator.CSS_SELECTOR, "button.apply-btn")
    ...     if btn:
    ...         page.click(btn)
"""

import logging
import random
import time
from typing import Callable

from auto_apply.application.services.page_action.clicking import Clicker
from auto_apply.application.services.page_action.pacing import Pacing
from auto_apply.application.services.page_action.probe import (
    PROBE_SCRIPT,
    TargetProbe,
)
from auto_apply.application.services.page_action.result import ActionResult
from auto_apply.application.services.page_action.scrolling import Scroller
from auto_apply.application.services.page_action.state import PageActionContext
from auto_apply.application.services.page_action.text_input import Typer
from auto_apply.domain.ports.browser_port import BrowserInterface, ElementInterface
from auto_apply.domain.ports.interaction_primitives_port import DomReadinessPort
from auto_apply.domain.ports.registry_port import RegistryPort

__all__ = ["ActionResult", "PageActionService"]

logger = logging.getLogger(__name__)


class PageActionService:
    """Unified browser interaction API for all domain engines — the facade.

    Args:
        browser: The active BrowserInterface (Selenium or Playwright adapter).
        registry: The session CapabilitiesRegistry. Timing config is read
            from its resolved effective_config at construction time.
        rng: Optional seeded random.Random for deterministic behaviour.
        pointer_rng: Optional seeded stream for pointer planning.
        wheel_rng: Optional seeded stream for wheel planning.
        readiness: Optional DomReadinessPort; when injected, feed settles
            are measured, not slept. The composition root wires the shared
            DOMObserver here.
    """

    #: Re-exported so the guard's pinned contract can inspect the probe
    #: script without importing the probe module.
    _PROBE_SCRIPT = PROBE_SCRIPT

    def __init__(
        self,
        browser: BrowserInterface,
        registry: RegistryPort,
        rng: random.Random | None = None,
        pointer_rng: random.Random | None = None,
        wheel_rng: random.Random | None = None,
        readiness: DomReadinessPort | None = None,
    ) -> None:
        self._browser = browser
        self._state = PageActionContext(
            browser=browser,
            cfg=registry.get_all_effective_config(),
            rng=rng,
            pointer_rng=pointer_rng,
            wheel_rng=wheel_rng,
            readiness=readiness,
        )
        self._probe = TargetProbe(self._state)
        self._pacing = Pacing(self._state)
        self._scroller = Scroller(self._state, self._probe, self._pacing)
        self._clicker = Clicker(self._state, self._probe, self._pacing, self._scroller)
        self._typer = Typer(self._state, self._pacing, self._clicker)

        logger.debug(
            "PageActionService ready | micro_peak=%.0fms "
            "macro=[%.1f–%.1fs] motion_profile=%s",
            self._state.micro_peak_ms,
            self._state.macro_min_s, self._state.macro_max_s,
            self._state.motion.profile.name,
        )

    # ── Test-compatible views of the shared session state ────────────────

    @property
    def _cursor(self) -> tuple[int, int] | None:
        return self._state.cursor

    @_cursor.setter
    def _cursor(self, value: tuple[int, int] | None) -> None:
        self._state.cursor = value

    @property
    def _last_viewport(self) -> tuple[int, int] | None:
        return self._state.last_viewport

    @_last_viewport.setter
    def _last_viewport(self, value: tuple[int, int] | None) -> None:
        self._state.last_viewport = value

    # =========================================================================
    # NAVIGATION (the facade's own concern)
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
        the session — the count is a ceiling, not a quota. The settle pause is
        a MACRO pause (a human visually orienting to a freshly loaded page);
        domain engines should NOT add their own sleep after calling this.

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
            single seam for that search: when the graph lands, the composition
            root injects a callable backed by a graph walk, and no change to
            this method's control flow is required. Keep this seam and its
            signature intact; leaving it None preserves today's behaviour, so
            wiring the graph later is purely additive.
        """
        attempts = max(1, self._state.navigation_retries)
        target = url
        last_reason = "navigation not attempted"
        # Warm up once before the very first load of the session (CAPTCHA
        # mitigation). No-op on every subsequent navigation.
        self.warmup_pause()
        for attempt in range(1, attempts + 1):
            try:
                logger.debug("navigate | attempt=%d/%d url=%s", attempt, attempts, target)
                self._browser.get(target)
                self._state.cursor = None   # New document: stored positions are meaningless.
                self._pacing.macro_pause()  # Simulate reading the freshly loaded page.
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
                    # candidate here.
                    if next_candidate is not None:
                        proposed = next_candidate(target, attempt)
                        if proposed is None:
                            break
                        target = proposed
                    self._pacing.settle_pause()   # brief backoff before retrying
        return ActionResult(False, reason=last_reason)

    def navigate_back(self) -> ActionResult:
        """Navigates back one step using the interface's back() method."""
        try:
            self._browser.back()
            self._state.cursor = None
            self._pacing.macro_pause()
            return ActionResult(True)
        except Exception as exc:
            logger.warning("navigate_back failed | %s", exc)
            return ActionResult(False, reason=str(exc))

    def navigate_to_blank(self) -> ActionResult:
        """Loads about:blank to reset browser state between strategy attempts."""
        try:
            self._browser.get("about:blank")
            self._state.cursor = None
            self._pacing.settle_pause()
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
    # ELEMENT LOCATION (the facade's own concern)
    # =========================================================================

    def find(self, by: str, selector: str) -> ElementInterface | None:
        """Returns the first matching element, or None if not found."""
        try:
            return self._browser.find_element(by, selector)
        except Exception:
            return None

    def find_all(self, by: str, selector: str) -> list[ElementInterface]:
        """Returns all matching elements, or an empty list. Never raises."""
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
        """Delegates to the browser adapter's wait_for_element implementation."""
        try:
            return self._browser.wait_for_element(by, selector, timeout=timeout)
        except Exception:
            return None

    def wait_for_any(
        self,
        candidates: list[tuple[str, str]],
        timeout: int = 10,
    ) -> tuple[int, ElementInterface] | None:
        """Polls until any one of several (by, selector) pairs matches."""
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
    # CLICK / HOVER — delegated to the clicker
    # =========================================================================

    def click(self, element: ElementInterface, *, irreversible: bool = False) -> ActionResult:
        """Clicks through the ladder (probe → pointer → keyboard → native →
        config-gated JS). Irreversible clicks are fail-closed."""
        return self._clicker.click(element, irreversible=irreversible)

    def click_by(self, by: str, selector: str) -> ActionResult:
        """Convenience: finds an element and clicks it in one call."""
        return self._clicker.click_by(by, selector)

    def hover(self, element: ElementInterface) -> ActionResult:
        """Moves the pointer over an element without pressing."""
        return self._clicker.hover(element)

    # =========================================================================
    # TEXT INPUT / FORM CONTROLS — delegated to the typer
    # =========================================================================

    def type_text(self, element: ElementInterface, text: str) -> ActionResult:
        """Types text character by character with the keystroke rhythm."""
        return self._typer.type_text(element, text)

    def clear_and_type(self, element: ElementInterface, text: str) -> ActionResult:
        """Clears an input field and types new text."""
        return self._typer.clear_and_type(element, text)

    def select_option(
        self,
        select_element: ElementInterface,
        *,
        by_value: str | None = None,
        by_text: str | None = None,
        by_index: int | None = None,
    ) -> ActionResult:
        """Sets a native <select>'s value (exactly one keyword argument)."""
        return self._typer.select_option(
            select_element, by_value=by_value, by_text=by_text, by_index=by_index
        )

    def check_checkbox(
        self,
        element: ElementInterface,
        desired: bool = True,
    ) -> ActionResult:
        """Sets a checkbox to the desired checked state."""
        return self._typer.check_checkbox(element, desired)

    # =========================================================================
    # SCROLL — delegated to the scroller
    # =========================================================================

    def scroll_to(self, element: ElementInterface) -> ActionResult:
        """Scrolls an element into view (alias of scroll_into_view)."""
        return self._scroller.scroll_to(element)

    def scroll_into_view(self, element: ElementInterface) -> ActionResult:
        """Scrolls panes until the element's centre is in the visible region."""
        return self._scroller.scroll_into_view(element)

    def scroll_container(self, element: ElementInterface, dy: int) -> int:
        """Scrolls the nearest scrollable ancestor; returns measured delta."""
        return self._scroller.scroll_container(element, dy)

    def scroll_to_bottom(self) -> bool:
        """One measured scroll step toward the feed bottom."""
        return self._scroller.scroll_to_bottom()

    def reveal_page(self, max_steps: int = 8) -> int:
        """Wheel-scan down so lazy content renders, then return to the top.

        Bounded by ``max_steps``; never raises. Called by the Applications
        engine before form analysis so sections below the fold actually exist
        in the DOM when they are analysed.
        """
        return self._scroller.reveal_page(max_steps)

    # =========================================================================
    # TIMING — PUBLIC (delegated to pacing)
    # =========================================================================

    def settle(self) -> None:
        """The tool's public pacing primitive: a short post-action pause,
        config-driven (floored by ``min_action_delay_ms``) and seeded."""
        self._pacing.settle_pause()

    def macro_pause(
        self,
        min_s: float | None = None,
        max_s: float | None = None,
    ) -> None:
        """A human reading/thinking pause between tasks (registry values
        unless overridden)."""
        self._pacing.macro_pause(min_s, max_s)

    def warmup_pause(self) -> None:
        """One-time pause before the first navigation of the session.
        Idempotent; navigate() calls it, callers do not need to."""
        self._pacing.warmup_pause()

    # =========================================================================
    # The guard's pinned contract (kept on the facade)
    # =========================================================================

    def _click_target_reachable(self, element: ElementInterface) -> tuple[bool | None, str]:
        """Three outcomes: True (topmost), False (covered/hidden/challenge/
        clipped), None (undetermined — proceeds)."""
        probe = self._probe.run(element)
        if probe is None:
            return None, "probe failed"
        return TargetProbe.verdict_outcome(str(probe.get("verdict") or ""))

    # =========================================================================
    # ESCAPE HATCH
    # =========================================================================

    def execute_script(self, script: str, *args) -> object | None:
        """Executes JavaScript via the adapter's execute_script.

        A controlled escape hatch for domain-specific situations where no
        higher-level service method is sufficient. Use sparingly.
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
            f"micro_peak={self._state.micro_peak_ms:.0f}ms, "
            f"macro=[{self._state.macro_min_s:.1f}–{self._state.macro_max_s:.1f}s], "
            f"motion_profile={self._state.motion.profile.name})"
        )
