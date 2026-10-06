# RETIRED FROM: packages/auto_apply/src/auto_apply/application/services/page_action/service.py
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

from auto_apply.domain.models.motion import (
    MotionCapabilities,
    MotionKind,
    MotionPlan,
    PointerTick,
    WheelTick,
)
from auto_apply.domain.models.motion_profile import MotionConfig
from auto_apply.domain.ports.browser_port import BrowserInterface, ElementInterface
from auto_apply.domain.ports.interaction_primitives_port import DomReadinessPort
from auto_apply.domain.services import motion_model
from auto_apply.domain.services.challenge_assessment import CHALLENGE_WIDGET_MARKERS
from auto_apply.domain.types import (  # FIXED: was `from core.types import Keys, Locator`  # noqa: E501
    Keys,
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
        rung:    Which ladder rung produced the outcome ("" when not a
            ladder operation): "probe" | "pointer" | "keyboard" | "native" |
            "js" | "wheel" | "js-scroll" | "none".
        effect:  Observed page effect after the action, for callers that
            decide retries: "navigation" | "dom-change" | "none" | "".
    """
    __slots__ = ("success", "reason", "element", "rung", "effect")

    def __init__(
        self,
        success: bool,
        reason: str = "ok",
        element: ElementInterface | None = None,
        rung: str = "",
        effect: str = "",
    ) -> None:
        self.success = success
        self.reason  = reason
        self.element = element
        self.rung    = rung
        self.effect  = effect

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
        pointer_rng: random.Random | None = None,
        wheel_rng: random.Random | None = None,
        readiness: DomReadinessPort | None = None,
    ) -> None:
        self._browser = browser
        self._rng = rng if rng is not None else random.Random()
        # Separate seeded streams for pointer and wheel planning, so pacing
        # draws cannot shift the motion streams (reproducibility).
        self._pointer_rng = pointer_rng if pointer_rng is not None else self._rng
        self._wheel_rng = wheel_rng if wheel_rng is not None else self._rng
        # Optional DOM-stability readiness (D5): when injected, feed settles
        # are measured, not slept. composition_root passes the shared
        # DOMObserver; None keeps the configured fixed wait.
        self._readiness = readiness

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

        # Motion: one typed, validated profile drives every pointer/wheel
        # behaviour. This replaces the old `_fingerprint` gate, which
        # conflated browser stealth with pointer motion: low-resource mode
        # forced enable_fingerprint_spoofing off and thereby switched ALL
        # mouse motion off — a pacing decision silently defeating stealth.
        # The flag still governs browser fingerprinting elsewhere; it no
        # longer reaches this tool.
        self._motion: MotionConfig = MotionConfig.from_mapping(cfg)
        # Virtual cursor: the last viewport-CSS-px position this tool moved
        # the pointer to. None until the first planned move.
        self._cursor: tuple[int, int] | None = None
        self._last_viewport: tuple[int, int] | None = None
        # Capability gaps already logged (once per gap per session).
        self._logged_caps: set[str] = set()

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
            "macro=[%.1f–%.1fs] motion_profile=%s",
            self._micro_peak_ms,
            self._macro_min_s, self._macro_max_s,
            self._motion.profile.name,
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
                self._cursor = None   # New document: stored positions are meaningless.
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
            self._cursor = None
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
            self._cursor = None
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

    #: One-round-trip target probe: geometry, reachability, challenge
    #: ancestry and the scrollable-ancestor chain. All geometry is viewport
    #: CSS pixels; same-origin iframe offsets accumulate into `frame`, and
    #: the ancestor walks cross open shadow roots via getRootNode().host
    #: (D9). Panes carry a wheel origin whose elementFromPoint belongs to
    #: that pane and not to a deeper scroller (D4), on both axes (D9).
    #: arguments[0] = element; arguments[1] = challenge marker substrings.
    _PROBE_SCRIPT = """
    var elem = arguments[0];
    var markers = arguments[1] || [];
    function up(el) {
        if (!el) { return null; }
        if (el.parentElement) { return el.parentElement; }
        var root = el.getRootNode ? el.getRootNode() : null;
        return (root && root.host) ? root.host : null;
    }
    var se = document.scrollingElement || document.body || document.documentElement;
    var vw = window.innerWidth, vh = window.innerHeight;
    if (!elem || elem.isConnected !== true) { return {verdict: 'stale'}; }
    if (window.getComputedStyle(elem).display === 'none') { return {verdict: 'hidden'}; }
    if (elem.offsetWidth === 0 || elem.offsetHeight === 0) { return {verdict: 'hidden'}; }
    for (var c = elem; c; c = up(c)) {
        var ca = ((c.getAttribute('class') || '') + ' ' +
                  (c.getAttribute('id') || '') + ' ' +
                  (c.getAttribute('name') || '')).toLowerCase();
        for (var m = 0; m < markers.length; m++) {
            if (ca.indexOf(markers[m]) !== -1) { return {verdict: 'challenge'}; }
        }
    }
    var box = elem.getBoundingClientRect();
    var fx = 0, fy = 0, frameBroken = false, win = window;
    while (win && win !== win.parent) {
        try {
            var fe = win.frameElement;
            if (!fe) { break; }
            var fr = fe.getBoundingClientRect();
            fx += fr.left; fy += fr.top;
            win = win.parent;
        } catch (e) { frameBroken = true; break; }
    }
    var result = {
        verdict: 'ok',
        tag: (elem.tagName || '').toLowerCase(),
        role: (elem.getAttribute('role') || '').toLowerCase(),
        input_type: (elem.getAttribute('type') || '').toLowerCase(),
        box: {x: box.left, y: box.top, w: box.width, h: box.height},
        frame: {x: fx, y: fy, broken: frameBroken},
        viewport: {w: vw, h: vh},
        docHeight: se ? se.scrollHeight : 0,
        scrollY: window.scrollY,
        dpr: window.devicePixelRatio || 1,
        panes: []
    };
    var cx = box.left + box.width / 2;
    var cy = box.top + box.height / 2;
    if (cx < 0 || cy < 0 || cx > vw || cy > vh) {
        result.verdict = 'offscreen';
    } else {
        var top = document.elementFromPoint(cx, cy);
        if (!top) {
            result.verdict = 'offscreen';
        } else {
            var found = false;
            for (var e = top; e; e = up(e)) {
                if (e === elem) { found = true; break; }
            }
            if (!found) {
                for (var a = elem; a; a = up(a)) {
                    if (a === top) { found = true; break; }
                }
            }
            if (!found) { result.verdict = 'occluded:' + (top.tagName || '?').toLowerCase(); }
        }
    }
    function isScroller(el) {
        var o = window.getComputedStyle(el);
        return ((o.overflowY === 'auto' || o.overflowY === 'scroll') && el.scrollHeight > el.clientHeight + 1)
            || ((o.overflowX === 'auto' || o.overflowX === 'scroll') && el.scrollWidth > el.clientWidth + 1);
    }
    function belongsToPane(hit, pane) {
        for (var e = hit; e; e = up(e)) {
            if (e === pane) { return true; }
            if (isScroller(e)) { return false; }
        }
        return false;
    }
    function paneOrigin(pane, pb) {
        var cands = [[0.5, 0.5], [0.33, 0.33], [0.67, 0.33], [0.33, 0.67], [0.67, 0.67]];
        for (var i = 0; i < cands.length; i++) {
            var px = pb.left + pb.width * cands[i][0];
            var py = pb.top + pb.height * cands[i][1];
            if (px < 0 || py < 0 || px > vw || py > vh) { continue; }
            var hit = document.elementFromPoint(px, py);
            if (hit && belongsToPane(hit, pane)) { return {x: px, y: py}; }
        }
        return null;
    }
    for (var p = up(elem); p; p = up(p)) {
        if (isScroller(p)) {
            var pb = p.getBoundingClientRect();
            var origin = paneOrigin(p, pb);
            result.panes.push({
                x: pb.left, y: pb.top, w: pb.width, h: pb.height,
                top: p.scrollTop, max: p.scrollHeight - p.clientHeight,
                left: p.scrollLeft, maxX: p.scrollWidth - p.clientWidth,
                ox: origin ? origin.x : null, oy: origin ? origin.y : null
            });
        }
    }
    if (se) {
        result.panes.push({
            x: 0, y: 0, w: vw, h: vh,
            top: se.scrollTop, max: se.scrollHeight - vh,
            left: se.scrollLeft, maxX: se.scrollWidth - vw,
            ox: Math.round(vw / 2), oy: Math.round(vh / 2)
        });
    }
    return result;
    """

    #: One round trip: [scrollHeight, scrollTop] of the document's real
    #: scroller (document.scrollingElement, not always body — D9).
    _ROOT_SCROLL_READ = (
        "var se = document.scrollingElement || document.body;"
        "return se ? [se.scrollHeight, se.scrollTop] : [0, 0];"
    )

    def _probe(self, element: ElementInterface) -> dict | None:
        """Runs the one-round-trip target probe. None means undetermined —
        and undetermined proceeds, exactly as the old guard required."""
        try:
            raw = self._browser.execute_script(
                self._PROBE_SCRIPT, element, list(CHALLENGE_WIDGET_MARKERS)
            )
        except Exception as exc:
            logger.debug("target probe failed, proceeding | %s", exc)
            return None
        if not isinstance(raw, dict):
            return None
        vp = raw.get("viewport")
        if isinstance(vp, dict) and vp.get("w") and vp.get("h"):
            self._last_viewport = (int(vp["w"]), int(vp["h"]))
            dpr = raw.get("dpr")
            if dpr and "dpr" not in self._logged_caps:
                # One-time diagnostic: display scaling + viewport, for the
                # live-run measurement of W3C coordinates under 125-150% scaling.
                self._logged_caps.add("dpr")
                logger.debug(
                    "motion | viewport=%sx%s dpr=%s",
                    vp["w"], vp["h"], dpr,
                )
        return raw

    @staticmethod
    def _verdict_outcome(verdict: str) -> tuple[bool | None, str]:
        """Maps a probe verdict to the guard's three outcomes.

        ``None`` (undetermined) proceeds — refusing to click because we
        could not look is how a guard becomes worse than no guard.
        """
        if verdict == "ok":
            return True, "reachable"
        if verdict == "challenge":
            return False, "challenge"
        if verdict == "offscreen" or not verdict:
            return None, "outside the viewport"
        return False, verdict

    def _click_target_reachable(self, element: ElementInterface) -> tuple[bool | None, str]:
        """Judges whether a click will land on the intended element.

        Three outcomes: True (topmost), False (covered/hidden/challenge),
        None (undetermined — proceeds). Thin wrapper over the probe, kept
        for the guard's pinned contract.
        """
        probe = self._probe(element)
        if probe is None:
            return None, "probe failed"
        return self._verdict_outcome(str(probe.get("verdict") or ""))

    def _viewport_from_probe(self, probe: dict | None) -> tuple[int, int] | None:
        vp = (probe or {}).get("viewport")
        if isinstance(vp, dict) and vp.get("w") and vp.get("h"):
            return (int(vp["w"]), int(vp["h"]))
        return self._last_viewport

    @staticmethod
    def _inside_viewport(point: tuple[int, int], viewport: tuple[int, int]) -> bool:
        x, y = point
        return 0 <= x < viewport[0] and 0 <= y < viewport[1]

    def _capabilities(self) -> MotionCapabilities:
        try:
            caps = self._browser.motion_capabilities
        except Exception:
            return MotionCapabilities()
        if not isinstance(caps, MotionCapabilities):
            return MotionCapabilities()
        return caps

    def _note_capability_gap(self, gap: str) -> None:
        """Loud degradation, once per gap per session."""
        if gap not in self._logged_caps:
            self._logged_caps.add(gap)
            logger.info(
                "motion | capability unavailable on this driver: %s — degrading loudly",
                gap,
            )

    def _effect_snapshot(self) -> tuple[str, int, str]:
        """(url, body length, focused-element signature) in one round trip.

        LIMIT, stated honestly: ``effect="none"`` means none of these cheap
        channels changed. It cannot rule out a handler that leaves no such
        trace (silent XHR, analytics) — it is a floor, not a verdict.
        """
        try:
            raw = self._browser.execute_script(
                "var ae = document.activeElement;"
                "return [location.href,"
                " document.body ? document.body.innerHTML.length : 0,"
                " ae ? (ae.tagName || '') + '#' + (ae.id || '') : ''];"
            )
            if isinstance(raw, (list, tuple)) and len(raw) == 3:
                return (str(raw[0]), int(raw[1] or 0), str(raw[2]))
        except Exception:
            pass
        return ("", 0, "")

    def _observe_effect(self, before: tuple[str, int, str]) -> str:
        after = self._effect_snapshot()
        if after[0] != before[0]:
            return "navigation"
        if after[1] != before[1]:
            return "dom-change"
        if after[2] != before[2]:
            return "focus-change"
        return "none"

    def _attachment_check(self, element: ElementInterface) -> ActionResult | None:
        """Fail-fast staleness gate. Returns a refusal for a stale element,
        None when the element is attached (or the check itself could not
        answer — a failed CHECK must not block the ladder).

        Both drivers fail fast here: Selenium raises a stale-reference error
        immediately; Playwright's handle resolution is bounded at 2s (D6,
        was 3 x 30s down the ladder).
        """
        try:
            attached = self._browser.execute_script(
                "return arguments[0] && arguments[0].isConnected === true;",
                element,
            )
        except Exception as exc:
            return ActionResult(
                False, reason=f"stale: {type(exc).__name__}", rung="probe"
            )
        if attached is False:
            return ActionResult(False, reason="stale", rung="probe")
        return None

    @staticmethod
    def _absolute_box(probe: dict | None) -> dict | None:
        """The probe box in TOP-LEVEL viewport coordinates (frame offsets
        accumulated by the probe are applied here)."""
        box = (probe or {}).get("box")
        if not isinstance(box, dict):
            return None
        frame = (probe or {}).get("frame") or {}
        fx, fy = frame.get("x", 0), frame.get("y", 0)
        if not fx and not fy:
            return box
        return {"x": box["x"] + fx, "y": box["y"] + fy, "w": box["w"], "h": box["h"]}

    @staticmethod
    def _pane_origin(pane: dict) -> tuple[int, int]:
        ox, oy = pane.get("ox"), pane.get("oy")
        if ox is None or oy is None:
            return (
                int(pane.get("x", 0) + pane.get("w", 0) / 2),
                int(pane.get("y", 0) + pane.get("h", 0) / 2),
            )
        return (int(ox), int(oy))

    def _approach_path(self, origin: tuple[int, int]) -> tuple[PointerTick, ...]:
        """Planned pointer path to a wheel origin. A real wheel scrolls
        whatever is under the cursor (D4), so the cursor travels to the
        origin first; empty when it is already there or no viewport is known.
        """
        if self._last_viewport is None:
            return ()
        start = self._cursor or (
            self._last_viewport[0] // 2, self._last_viewport[1] // 2
        )
        if start == origin:
            return ()
        return motion_model.plan_pointer_move(
            start, origin, 24.0, self._last_viewport,
            self._motion.profile, self._pointer_rng,
        )

    @staticmethod
    def _match_pane_offsets(probe: dict | None, pane: dict) -> tuple[float, float] | None:
        for p in (probe or {}).get("panes") or []:
            if (
                abs(p.get("x", 0) - pane.get("x", 0)) < 2
                and abs(p.get("y", 0) - pane.get("y", 0)) < 2
                and abs(p.get("w", 0) - pane.get("w", 0)) < 2
            ):
                return (float(p.get("top", 0)), float(p.get("left", 0)))
        return None

    def _await_feed_settle(self) -> None:
        """Wait for the feed to react: measured DOM stability when a
        readiness port is injected, else the configured fixed wait
        (``infinite_scroll_settle_s`` is the upper bound either way)."""
        if self._readiness is not None:
            try:
                self._readiness.wait_for_dom_stable(
                    timeout=self._infinite_scroll_settle_s
                )
                return
            except Exception:
                pass
        time.sleep(self._infinite_scroll_settle_s)

    def click(self, element: ElementInterface, *, irreversible: bool = False) -> ActionResult:
        """Performs a click through the ladder:

            probe → trusted pointer click at a sampled, off-centre point →
            keyboard activation (role-gated) → native driver click →
            (config permitting, never on irreversible actions) JS click.

        Irreversible clicks (form submits) are FAIL-CLOSED: a rung that
        raises after it may have acted stops the ladder instead of risking
        a second submission, and the synthetic-JS rung is never offered.

        Args:
            element: The ElementInterface to click.
            irreversible: True when the click cannot be undone.

        Returns:
            ActionResult naming the rung that landed (or refused) and, on
            the pointer rung, the observed page effect.
        """
        stale = self._attachment_check(element)
        if stale is not None:
            return stale

        probe = self._probe(element)
        verdict = str((probe or {}).get("verdict") or "")

        if verdict in ("stale", "challenge"):
            if verdict == "challenge":
                logger.warning("click refused: target is inside a challenge widget")
            return ActionResult(
                False, reason=f"click target not reachable: {verdict}", rung="probe"
            )

        if self._occlusion_guard and verdict not in ("", "ok"):
            reachable, detail = self._verdict_outcome(verdict)
            if reachable is False:
                # Most occlusion is a sticky header or a banner that a
                # scroll resolves, so look again before refusing.
                self.scroll_to(element)
                probe = self._probe(element)
                verdict = str((probe or {}).get("verdict") or "")
                if verdict in ("stale", "challenge"):
                    return ActionResult(
                        False, reason=f"click target not reachable: {verdict}", rung="probe"
                    )
                reachable, detail = self._verdict_outcome(verdict)
            if reachable is False:
                logger.warning(
                    "click refused: target is not clickable (%s)", detail
                )
                return ActionResult(
                    False, reason=f"click target not reachable: {detail}", rung="probe"
                )

        if verdict == "offscreen":
            # Below the fold used to proceed unmeasured; now it scrolls first.
            self.scroll_to(element)
            probe = self._probe(element)
            verdict = str((probe or {}).get("verdict") or "")
            if verdict in ("stale", "challenge"):
                return ActionResult(
                    False, reason=f"click target not reachable: {verdict}", rung="probe"
                )
            # D10: a scroll changes what is topmost (Google One Tap over
            # LinkedIn's Apply is measured) — the guard runs again on the
            # new geometry before any rung acts.
            if self._occlusion_guard and verdict not in ("", "ok"):
                reachable, detail = self._verdict_outcome(verdict)
                if reachable is False:
                    logger.warning(
                        "click refused after scroll: target is not clickable (%s)",
                        detail,
                    )
                    return ActionResult(
                        False, reason=f"click target not reachable: {detail}", rung="probe"
                    )

        # ── Rung 1: trusted pointer click at a sampled, off-centre point ──
        caps = self._capabilities()
        box = self._absolute_box(probe)
        viewport = self._viewport_from_probe(probe)
        if (probe or {}).get("frameBroken"):
            # Cross-origin frame: box offsets could not be accumulated, so
            # pointer coordinates would land in the wrong place (D9). The
            # keyboard/native rungs act in the driver's frame context and
            # remain valid.
            self._note_capability_gap("cross-origin frame geometry — pointer rung skipped")
        elif (
            isinstance(box, dict)
            and box.get("w") and box.get("h")
            and viewport is not None
            and caps.trusted_pointer
        ):
            if caps.native_humanization:
                # The driver humanises on its own (e.g. camoufox); stacking a
                # second humaniser would double every movement.
                self._note_capability_gap("native humanization — tool motion skipped")
            else:
                try:
                    landing = motion_model.sample_landing_point(
                        (box["x"], box["y"], box["w"], box["h"]),
                        self._motion.profile,
                        self._pointer_rng,
                    )
                    if not self._inside_viewport(landing, viewport):
                        raise ValueError("landing outside viewport")
                    start = self._cursor or (viewport[0] // 2, viewport[1] // 2)
                    plan = motion_model.plan_click(
                        start, landing, box["w"], viewport,
                        self._motion.profile, self._pointer_rng,
                    )
                    before = self._effect_snapshot()
                    self._browser.execute_motion(plan)
                    self._cursor = landing
                    self._settle_pause()
                    return ActionResult(
                        True, element=element, rung="pointer",
                        effect=self._observe_effect(before),
                    )
                except Exception as exc:
                    logger.warning("pointer click rung failed | %s", exc)
                    if irreversible:
                        return ActionResult(
                            False,
                            reason=f"irreversible click aborted after a rung raised: {exc}",
                            rung="pointer",
                        )
        elif not caps.trusted_pointer:
            self._note_capability_gap("trusted pointer input")

        # ── Rung 2: role-correct keyboard activation (D3, measured live) ──
        # Enter on a text-entry control SUBMITS the enclosing form; Enter on
        # a checkbox submits too and never toggles. So: text entry = focus
        # only (focus IS the click), toggles = Space verified by a state
        # change, buttons/links = Enter.
        tag = str((probe or {}).get("tag") or "")
        role = str((probe or {}).get("role") or "")
        input_type = str((probe or {}).get("input_type") or "")
        is_toggle = (
            tag == "input" and input_type in ("checkbox", "radio")
        ) or role in ("checkbox", "radio")
        is_text_entry = tag == "textarea" or (
            tag == "input" and input_type in self._TEXT_ENTRY_TYPES
        )

        if is_text_entry:
            try:
                self._browser.execute_script("arguments[0].focus();", element)
                self._settle_pause()
                return ActionResult(True, element=element, rung="keyboard", effect="focus")
            except Exception as exc:
                logger.warning("keyboard focus rung failed | %s", exc)
                if irreversible:
                    return ActionResult(
                        False,
                        reason=f"irreversible click aborted after a rung raised: {exc}",
                        rung="keyboard",
                    )
        elif is_toggle:
            try:
                was_checked = bool(self._browser.execute_script(
                    "return !!arguments[0].checked;", element
                ))
                self._browser.execute_script("arguments[0].focus();", element)
                element.send_keys(Keys.SPACE)
                is_checked = bool(self._browser.execute_script(
                    "return !!arguments[0].checked;", element
                ))
                if is_checked != was_checked:
                    self._settle_pause()
                    return ActionResult(True, element=element, rung="keyboard")
                logger.warning(
                    "keyboard toggle left the state unchanged — descending the ladder"
                )
            except Exception as exc:
                logger.warning("keyboard toggle rung failed | %s", exc)
                if irreversible:
                    return ActionResult(
                        False,
                        reason=f"irreversible click aborted after a rung raised: {exc}",
                        rung="keyboard",
                    )
        elif tag in ("a", "button", "select", "summary") or role in (
            "button", "link", "menuitem", "tab",
        ):
            try:
                self._browser.execute_script("arguments[0].focus();", element)
                element.send_keys(Keys.ENTER)
                self._settle_pause()
                return ActionResult(True, element=element, rung="keyboard")
            except Exception as exc:
                logger.warning("keyboard activation rung failed | %s", exc)
                if irreversible:
                    return ActionResult(
                        False,
                        reason=f"irreversible click aborted after a rung raised: {exc}",
                        rung="keyboard",
                    )

        # ── Rung 3: the driver's native element click (exact centre) ──
        try:
            element.click()
            self._settle_pause()
            return ActionResult(True, element=element, rung="native")
        except Exception as exc:
            logger.warning("native click rung failed | %s", exc)
            if irreversible:
                return ActionResult(False, reason=str(exc), rung="native")

        # ── Rung 4: synthetic JS click — untrusted, last resort, config-gated ──
        if self._motion.allow_js_click:
            logger.warning("click falling back to a synthetic JS click (untrusted event)")
            try:
                self._browser.execute_script("arguments[0].click();", element)
                self._settle_pause()
                return ActionResult(True, element=element, rung="js")
            except Exception as exc:
                return ActionResult(False, reason=str(exc), rung="js")
        return ActionResult(False, reason="all click rungs exhausted", rung="none")

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

    def hover(self, element: ElementInterface) -> ActionResult:
        """Moves the pointer over an element without pressing.

        A planned path ending at a sampled off-centre point; falls back to
        the port's direct move when trusted pointer input is unavailable.
        """
        stale = self._attachment_check(element)
        if stale is not None:
            return stale

        probe = self._probe(element)
        if str((probe or {}).get("verdict") or "") == "offscreen":
            self.scroll_to(element)
            probe = self._probe(element)
        box = self._absolute_box(probe)
        viewport = self._viewport_from_probe(probe)
        caps = self._capabilities()
        if (
            isinstance(box, dict)
            and box.get("w") and box.get("h")
            and viewport is not None
            and caps.trusted_pointer
            and not caps.native_humanization
            and not (probe or {}).get("frameBroken")
        ):
            try:
                landing = motion_model.sample_landing_point(
                    (box["x"], box["y"], box["w"], box["h"]),
                    self._motion.profile, self._pointer_rng,
                )
                start = self._cursor or (viewport[0] // 2, viewport[1] // 2)
                ticks = motion_model.plan_pointer_move(
                    start, landing, box["w"], viewport,
                    self._motion.profile, self._pointer_rng,
                )
                self._browser.execute_motion(
                    MotionPlan(kind=MotionKind.MOVE, pointer_ticks=ticks)
                )
                self._cursor = landing
                self._settle_pause()
                return ActionResult(True, element=element, rung="pointer")
            except Exception as exc:
                logger.warning("hover pointer rung failed | %s", exc)
        try:
            self._browser.move_mouse_to_element(element)
            self._settle_pause()
            return ActionResult(True, element=element, rung="native")
        except Exception as exc:
            return ActionResult(False, reason=str(exc), rung="native")

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

    #: Input types where focus IS the click — Enter would submit the form.
    _TEXT_ENTRY_TYPES = frozenset({
        "text", "email", "tel", "url", "number", "password", "search",
        "date", "datetime-local", "month", "week", "time",
    })

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
        """Scrolls an element into view. Alias of scroll_into_view, kept for
        the existing call sites (occlusion guard, handlers).

        The old implementation scrolled PAST the target: after centring via
        smooth scrollIntoView it scrolled further down by a coordinate read
        while the animation was still running — and document-relative on
        Selenium but viewport-relative on Playwright, so the overshoot
        differed by driver. All geometry now comes from the probe's single
        viewport-CSS-px frame.
        """
        return self.scroll_into_view(element)

    _SCROLL_INTO_VIEW_MAX_STEPS: int = 12

    def scroll_into_view(self, element: ElementInterface) -> ActionResult:
        """Scrolls panes (innermost first) with real wheel input until the
        element's box centre sits inside the viewport.

        Progress is verified by MEASURED offset change each step, which
        tolerates scroll-jacking, smooth-scroll and scroll-snap; a recorded
        instant JS scroll is the fallback when wheel input is unavailable
        or makes no progress.
        """
        last_rung = "already-visible"
        for _ in range(self._SCROLL_INTO_VIEW_MAX_STEPS):
            probe = self._probe(element)
            if probe is None:
                return ActionResult(False, reason="scroll probe failed", rung="probe")
            box = probe.get("box")
            viewport = self._viewport_from_probe(probe)
            if not isinstance(box, dict) or viewport is None:
                return ActionResult(False, reason="scroll probe failed", rung="probe")
            if self._box_inside_viewport(box, viewport):
                return ActionResult(True, element=element, rung=last_rung)
            dx_needed = (box["x"] + box["w"] / 2.0) - viewport[0] / 2.0
            dy_needed = (box["y"] + box["h"] / 2.0) - viewport[1] / 2.0
            if not self._wheel_toward(element, probe, dx_needed, dy_needed):
                break
            last_rung = "wheel"
        try:
            self._browser.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});", element
            )
            probe = self._probe(element)
            box = (probe or {}).get("box")
            viewport = self._viewport_from_probe(probe)
            if isinstance(box, dict) and viewport is not None and self._box_inside_viewport(box, viewport):
                logger.info("scroll_into_view used the instant JS fallback")
                return ActionResult(True, element=element, rung="js-scroll")
        except Exception as exc:
            return ActionResult(False, reason=str(exc), rung="js-scroll")
        return ActionResult(
            False, reason="target could not be scrolled into view", rung=last_rung
        )

    @staticmethod
    def _box_inside_viewport(box: dict, viewport: tuple[int, int]) -> bool:
        cx = box["x"] + box["w"] / 2.0
        cy = box["y"] + box["h"] / 2.0
        return 0 <= cx < viewport[0] and 0 <= cy < viewport[1]

    def _wheel_toward(self, element: ElementInterface, probe: dict, dx_needed: float, dy_needed: float) -> bool:
        """One wheel step toward the target through the innermost pane that
        can move in the needed direction (whichever axis needs more). The
        pointer moves to the pane's own origin first (D4), and progress is
        the MEASURED offset change on the scrolled axis. True iff something
        moved; False means 'try the fallback'."""
        caps = self._capabilities()
        if not caps.wheel:
            self._note_capability_gap("wheel input")
            return False
        horizontal = abs(dx_needed) > abs(dy_needed)
        needed = dx_needed if horizontal else dy_needed
        direction = 1 if needed > 0 else -1
        for pane in probe.get("panes") or []:
            if horizontal:
                pos = float(pane.get("left", 0))
                limit = float(pane.get("maxX", 0))
                extent = float(pane.get("w", 400))
            else:
                pos = float(pane.get("top", 0))
                limit = float(pane.get("max", 0))
                extent = float(pane.get("h", 400))
            room = (limit - pos) if direction > 0 else pos
            if room <= 0:
                continue
            step = direction * min(abs(needed), extent * 0.8, room)
            base_ticks = motion_model.plan_wheel(
                int(step), self._motion.profile, self._wheel_rng
            )
            if not base_ticks:
                continue
            if horizontal:
                ticks = tuple(
                    WheelTick(dx=t.dy, dy=0, dt_ms=t.dt_ms) for t in base_ticks
                )
            else:
                ticks = base_ticks
            origin = self._pane_origin(pane)
            path = self._approach_path(origin)
            try:
                self._browser.execute_motion(
                    MotionPlan(
                        kind=MotionKind.WHEEL,
                        pointer_ticks=path,
                        wheel_ticks=ticks,
                        wheel_origin=origin,
                    )
                )
                if path:
                    self._cursor = origin
            except Exception as exc:
                logger.warning("wheel rung failed | %s", exc)
                return False
            after = self._match_pane_offsets(self._probe(element), pane)
            if after is not None:
                new_pos = after[1] if horizontal else after[0]
                if abs(new_pos - pos) > 0.5:
                    return True
            # No movement in this pane — try the next ancestor.
        return False

    def scroll_container(self, element: ElementInterface, dy: int) -> int:
        """Scrolls the nearest scrollable ancestor of *element* by up to
        |dy| CSS pixels of wheel input (the AD-1 primitive).

        Returns the MEASURED offset change — 0 when nothing moved, no pane
        could scroll, or the driver cannot do wheel input (logged once).
        """
        probe = self._probe(element)
        if probe is None:
            return 0
        caps = self._capabilities()
        if not caps.wheel:
            self._note_capability_gap("wheel input")
            return 0
        direction = 1 if dy > 0 else -1
        for pane in probe.get("panes") or []:
            top = float(pane.get("top", 0))
            max_top = float(pane.get("max", 0))
            room = (max_top - top) if direction > 0 else top
            if room <= 0:
                continue
            step = direction * min(abs(dy), room)
            ticks = motion_model.plan_wheel(
                int(step), self._motion.profile, self._wheel_rng
            )
            if not ticks:
                return 0
            origin = self._pane_origin(pane)
            path = self._approach_path(origin)
            try:
                self._browser.execute_motion(
                    MotionPlan(
                        kind=MotionKind.WHEEL,
                        pointer_ticks=path,
                        wheel_ticks=ticks,
                        wheel_origin=origin,
                    )
                )
                if path:
                    self._cursor = origin
            except Exception as exc:
                logger.warning("scroll_container wheel failed | %s", exc)
                return 0
            after = self._match_pane_offsets(self._probe(element), pane)
            return int(after[0] - top) if after is not None else 0
        return 0

    def scroll_to_bottom(self) -> bool:
        """One measured scroll step toward the feed bottom.

        CONTRACT (D5): True = the step made progress — the document's real
        scroller (document.scrollingElement) moved OR the document grew.
        False = measured end: no movement and no growth. The caller's loop
        stops only on False or on its own caps, so a page that is merely
        taller than one viewport no longer reads as 'end of feed' — the
        regression that stopped discovery after one screenful.

        The wheel acts over the WINDOW pane's own origin (a point whose
        topmost element belongs to that pane, not to a nested scroller —
        D4), reached on a planned pointer path. The settle is measured DOM
        stability when a readiness port is injected, else the configured
        ``infinite_scroll_settle_s`` wait (the upper bound either way).
        The caller still owns the loop and the dry-scroll guard.

        Returns:
            True on progress, False at the measured end or on error (a
            scroll probe must never abort discovery).
        """
        try:
            before = self._browser.execute_script(self._ROOT_SCROLL_READ)
            caps = self._capabilities()
            if caps.wheel:
                # 1366x768 is the smallest target screen in the design
                # brief; used only when no probe has measured a viewport yet.
                viewport = self._last_viewport or (1366, 768)
                origin: tuple[int, int] = (viewport[0] // 2, viewport[1] // 2)
                body = self.find(Locator.TAG_NAME, "body")
                if body is not None:
                    body_probe = self._probe(body)
                    panes = (body_probe or {}).get("panes") or []
                    if panes:
                        origin = self._pane_origin(panes[-1])
                ticks = motion_model.plan_wheel(
                    int(viewport[1] * 0.9), self._motion.profile, self._wheel_rng
                )
                path = self._approach_path(origin)
                self._browser.execute_motion(
                    MotionPlan(
                        kind=MotionKind.WHEEL,
                        pointer_ticks=path,
                        wheel_ticks=ticks,
                        wheel_origin=origin,
                    )
                )
                if path:
                    self._cursor = origin
            else:
                self._note_capability_gap(
                    "wheel input — using the recorded instant-scroll fallback"
                )
                self._browser.execute_script(
                    "window.scrollTo(0, document.body.scrollHeight);"
                )
            self._await_feed_settle()
            after = self._browser.execute_script(self._ROOT_SCROLL_READ)
            moved = after[1] != before[1]
            grew = after[0] > before[0]
            return bool(moved or grew)
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

        if self._motion.profile.fidget_moves_max:
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
        """Sleeps for `duration` seconds with PLANNED pointer micro-movements.

        Replaces the adapter fidget (a ±5px wiggle on Selenium, a full-page
        teleport on Playwright) with the motion model's tremor-and-return.
        Skipped entirely until a probe has measured a viewport.
        """
        profile = self._motion.profile
        end = time.monotonic() + duration
        while time.monotonic() < end:
            if profile.fidget_moves_max and self._last_viewport is not None:
                current = self._cursor or (
                    self._last_viewport[0] // 2, self._last_viewport[1] // 2
                )
                plan = motion_model.plan_fidget(
                    current, self._last_viewport, profile, self._pointer_rng
                )
                if plan.pointer_ticks:
                    try:
                        self._browser.execute_motion(plan)
                        self._cursor = (
                            plan.pointer_ticks[-1].x, plan.pointer_ticks[-1].y
                        )
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
            f"motion_profile={self._motion.profile.name})"
        )