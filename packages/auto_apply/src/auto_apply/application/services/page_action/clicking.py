"""Clicker — the click ladder and hover.

The ladder, unchanged in shape, with G2's pane-clip branch added:

    probe → trusted pointer click at a sampled, off-centre point →
    keyboard activation (role-gated) → native driver click →
    (config permitting, never on irreversible actions) JS click.

Irreversible clicks (form submits, per Nick's rule also account creation and
account login) are FAIL-CLOSED: a rung that raises after it may have acted
stops the ladder instead of risking a second submission, and the synthetic-JS
rung is never offered.

The keyboard rung is role-correct (D3, measured live): Enter on a text-entry
control SUBMITS the enclosing form; Enter on a checkbox submits too and never
toggles. So: text entry = focus only (focus IS the click), toggles = Space
verified by a state change, buttons/links = Enter.
"""
from __future__ import annotations

import logging

from auto_apply.application.services.page_action.pacing import Pacing
from auto_apply.application.services.page_action.probe import TargetProbe
from auto_apply.application.services.page_action.result import ActionResult
from auto_apply.application.services.page_action.scrolling import Scroller
from auto_apply.application.services.page_action.state import PageActionContext
from auto_apply.domain.models.motion import MotionKind, MotionPlan
from auto_apply.domain.services import motion_model
from auto_apply.domain.ports.browser_port import ElementInterface
from auto_apply.domain.types import Keys

logger = logging.getLogger(__name__)

#: Input types where focus IS the click — Enter would submit the form.
_TEXT_ENTRY_TYPES = frozenset({
    "text", "email", "tel", "url", "number", "password", "search",
    "date", "datetime-local", "month", "week", "time",
})


class Clicker:
    """Clicks and hovers through the ladder. Owns no scrolling or pacing."""

    def __init__(
        self,
        state: PageActionContext,
        probe: TargetProbe,
        pacing: Pacing,
        scroller: Scroller,
    ) -> None:
        self._state = state
        self._probe = probe
        self._pacing = pacing
        self._scroller = scroller

    def click(self, element: ElementInterface, *, irreversible: bool = False) -> ActionResult:
        """Performs a click through the ladder, recording the outcome rung.

        Every click — landed or refused — is counted in the session tally
        exactly once (here, at the ladder's single exit), so the
        SessionReport can show how AA actually clicked.
        """
        result = self._click_ladder(element, irreversible=irreversible)
        self._state.tally.record_click(result.rung, result.success)
        return result

    def _click_ladder(self, element: ElementInterface, *, irreversible: bool = False) -> ActionResult:
        """The ladder itself. Returns the ActionResult; the public ``click``
        records it.

        Args:
            element: The ElementInterface to click.
            irreversible: True when the click cannot be undone.

        Returns:
            ActionResult naming the rung that landed (or refused) and, on
            the pointer rung, the observed page effect.
        """
        stale = self._probe.attachment_check(element)
        if stale is not None:
            return stale

        probe = self._probe.run(element)
        verdict = str((probe or {}).get("verdict") or "")

        if verdict in ("stale", "challenge"):
            if verdict == "challenge":
                logger.warning("click refused: target is inside a challenge widget")
            return ActionResult(
                False, reason=f"click target not reachable: {verdict}", rung="probe"
            )

        if verdict in ("offscreen", "pane-clip"):
            # Below the fold, or clipped by its own scroll pane (G2): scroll
            # first — the scroller is pane-aware — then re-judge on the new
            # geometry before any rung acts (D10: a scroll changes what is
            # topmost).
            self._scroller.scroll_to(element)
            probe = self._probe.run(element)
            verdict = str((probe or {}).get("verdict") or "")
            if verdict in ("stale", "challenge"):
                return ActionResult(
                    False, reason=f"click target not reachable: {verdict}", rung="probe"
                )
            if verdict == "pane-clip":
                # Still clipped after scrolling: a pointer click would land
                # on whatever is on top of it inside the pane. Refusing is
                # guard-independent — this is a wrong-element click, not a
                # maybe-occluded one.
                logger.warning(
                    "click refused: target is clipped by its scroll pane"
                )
                return ActionResult(
                    False,
                    reason="click target not reachable: clipped by its scroll pane",
                    rung="probe",
                )

        if self._state.occlusion_guard and verdict not in ("", "ok"):
            reachable, detail = TargetProbe.verdict_outcome(verdict)
            if reachable is False:
                # Most occlusion is a sticky header or a banner that a
                # scroll resolves, so look again before refusing.
                self._scroller.scroll_to(element)
                probe = self._probe.run(element)
                verdict = str((probe or {}).get("verdict") or "")
                if verdict in ("stale", "challenge"):
                    return ActionResult(
                        False, reason=f"click target not reachable: {verdict}", rung="probe"
                    )
                reachable, detail = TargetProbe.verdict_outcome(verdict)
            if reachable is False:
                logger.warning(
                    "click refused: target is not clickable (%s)", detail
                )
                return ActionResult(
                    False, reason=f"click target not reachable: {detail}", rung="probe"
                )

        # ── Rung 1: trusted pointer click at a sampled, off-centre point ──
        caps = self._probe.capabilities()
        box = TargetProbe.clickable_box(probe)
        viewport = self._probe.viewport_from_probe(probe)
        if (probe or {}).get("frameBroken"):
            # Cross-origin frame: box offsets could not be accumulated, so
            # pointer coordinates would land in the wrong place (D9). The
            # keyboard/native rungs act in the driver's frame context and
            # remain valid.
            self._probe.note_capability_gap("cross-origin frame geometry — pointer rung skipped")
        elif (
            isinstance(box, dict)
            and box.get("w") and box.get("h")
            and viewport is not None
            and caps.trusted_pointer
        ):
            if caps.native_humanization:
                # The driver humanises on its own (e.g. camoufox); stacking a
                # second humaniser would double every movement.
                self._probe.note_capability_gap("native humanization — tool motion skipped")
            else:
                try:
                    landing = motion_model.sample_landing_point(
                        (box["x"], box["y"], box["w"], box["h"]),
                        self._state.motion.profile,
                        self._state.pointer_rng,
                    )
                    if not TargetProbe.inside_viewport(landing, viewport):
                        raise ValueError("landing outside viewport")
                    start = self._state.cursor or (viewport[0] // 2, viewport[1] // 2)
                    plan = motion_model.plan_click(
                        start, landing, box["w"], viewport,
                        self._state.motion.profile, self._state.pointer_rng,
                    )
                    before = self._probe.effect_snapshot()
                    self._state.browser.execute_motion(plan)
                    self._state.cursor = landing
                    self._pacing.settle_pause()
                    return ActionResult(
                        True, element=element, rung="pointer",
                        effect=self._probe.observe_effect(before),
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
            self._probe.note_capability_gap("trusted pointer input")

        # ── Rung 2: role-correct keyboard activation (D3, measured live) ──
        tag = str((probe or {}).get("tag") or "")
        role = str((probe or {}).get("role") or "")
        input_type = str((probe or {}).get("input_type") or "")
        is_toggle = (
            tag == "input" and input_type in ("checkbox", "radio")
        ) or role in ("checkbox", "radio")
        is_text_entry = tag == "textarea" or (
            tag == "input" and input_type in _TEXT_ENTRY_TYPES
        )

        if is_text_entry:
            try:
                self._state.browser.execute_script("arguments[0].focus();", element)
                self._pacing.settle_pause()
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
                was_checked = bool(self._state.browser.execute_script(
                    "return !!arguments[0].checked;", element
                ))
                self._state.browser.execute_script("arguments[0].focus();", element)
                element.send_keys(Keys.SPACE)
                is_checked = bool(self._state.browser.execute_script(
                    "return !!arguments[0].checked;", element
                ))
                if is_checked != was_checked:
                    self._pacing.settle_pause()
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
                self._state.browser.execute_script("arguments[0].focus();", element)
                element.send_keys(Keys.ENTER)
                self._pacing.settle_pause()
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
            self._pacing.settle_pause()
            return ActionResult(True, element=element, rung="native")
        except Exception as exc:
            logger.warning("native click rung failed | %s", exc)
            if irreversible:
                return ActionResult(False, reason=str(exc), rung="native")

        # ── Rung 4: synthetic JS click — untrusted, last resort, config-gated ──
        if self._state.motion.allow_js_click:
            logger.warning("click falling back to a synthetic JS click (untrusted event)")
            try:
                self._state.browser.execute_script("arguments[0].click();", element)
                self._pacing.settle_pause()
                return ActionResult(True, element=element, rung="js")
            except Exception as exc:
                return ActionResult(False, reason=str(exc), rung="js")
        return ActionResult(False, reason="all click rungs exhausted", rung="none")

    def click_by(self, by: str, selector: str) -> ActionResult:
        """Convenience: finds an element and clicks it in one call."""
        try:
            element = self._state.browser.find_element(by, selector)
        except Exception:
            element = None
        if element is None:
            return ActionResult(False, reason=f"element not found: {selector!r}")
        return self.click(element)

    def hover(self, element: ElementInterface) -> ActionResult:
        """Moves the pointer over an element without pressing.

        A planned path ending at a sampled off-centre point; falls back to
        the port's direct move when trusted pointer input is unavailable.
        """
        stale = self._probe.attachment_check(element)
        if stale is not None:
            return stale

        probe = self._probe.run(element)
        if str((probe or {}).get("verdict") or "") in ("offscreen", "pane-clip"):
            self._scroller.scroll_to(element)
            probe = self._probe.run(element)
        box = TargetProbe.clickable_box(probe)
        viewport = self._probe.viewport_from_probe(probe)
        caps = self._probe.capabilities()
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
                    self._state.motion.profile, self._state.pointer_rng,
                )
                start = self._state.cursor or (viewport[0] // 2, viewport[1] // 2)
                ticks = motion_model.plan_pointer_move(
                    start, landing, box["w"], viewport,
                    self._state.motion.profile, self._state.pointer_rng,
                )
                self._state.browser.execute_motion(
                    MotionPlan(kind=MotionKind.MOVE, pointer_ticks=ticks)
                )
                self._state.cursor = landing
                self._pacing.settle_pause()
                return ActionResult(True, element=element, rung="pointer")
            except Exception as exc:
                logger.warning("hover pointer rung failed | %s", exc)
        try:
            self._state.browser.move_mouse_to_element(element)
            self._pacing.settle_pause()
            return ActionResult(True, element=element, rung="native")
        except Exception as exc:
            return ActionResult(False, reason=str(exc), rung="native")
