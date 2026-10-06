"""TargetProbe — geometry, reachability, panes, frames, and page effects.

One round trip answers: where the target is, whether anything is on top of
it, whether it sits inside a challenge widget, which panes can scroll to it,
and what the viewport looks like. The click ladder and the scroller both
judge from this one probe; nothing else in AA runs elementFromPoint.

Verdict vocabulary (three-plus-one outcomes, and undetermined proceeds):
    "ok"         — topmost at the centre point is the target (or wraps it)
    "occluded:X" — something else is on top (a banner, a sticky header)
    "pane-clip"  — the topmost element sits inside one of the target's OWN
                   scrolling ancestors: the target is clipped by that pane's
                   overflow. The remedy is to scroll the pane, not to refuse
                   (G2 — measured live: job-list columns on LinkedIn/Indeed).
    "offscreen"  — the centre lies outside the window viewport
    "hidden"     — display:none or zero size
    "stale"      — detached from the document
    "challenge"  — inside a challenge widget (refused, always)
"""
from __future__ import annotations

import logging

from auto_apply.application.services.page_action.result import ActionResult
from auto_apply.application.services.page_action.state import PageActionContext
from auto_apply.domain.models.motion import MotionCapabilities
from auto_apply.domain.ports.browser_port import ElementInterface
from auto_apply.domain.services.challenge_assessment import CHALLENGE_WIDGET_MARKERS

logger = logging.getLogger(__name__)

#: One-round-trip target probe: geometry, reachability, challenge
#: ancestry and the scrollable-ancestor chain. All geometry is viewport
#: CSS pixels; same-origin iframe offsets accumulate into `frame`, and
#: the ancestor walks cross open shadow roots via getRootNode().host
#: (D9). Panes carry a wheel origin whose elementFromPoint belongs to
#: that pane and not to a deeper scroller (D4), on both axes (D9).
#: arguments[0] = element; arguments[1] = challenge marker substrings.
PROBE_SCRIPT = """
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
            if (found) {
                for (var s = up(elem); s && s !== top; s = up(s)) {
                    if (!isScroller(s)) { continue; }
                    var sr = s.getBoundingClientRect();
                    if (cx < sr.left || cx >= sr.right || cy < sr.top || cy >= sr.bottom) {
                        found = false; break;
                    }
                }
            }
        }
        if (!found) {
            // D12: if the topmost element sits inside one of the target's
            // OWN scrolling ancestors, the target is clipped by that pane's
            // overflow, not covered by an overlay — the remedy is to scroll
            // the pane, not to refuse the click (G2, measured live).
            var clipped = false;
            for (var t = top; t && !clipped; t = up(t)) {
                if (isScroller(t)) {
                    for (var a2 = elem; a2; a2 = up(a2)) {
                        if (a2 === t) { clipped = true; break; }
                    }
                }
            }
            result.verdict = clipped
                ? 'pane-clip'
                : 'occluded:' + (top.tagName || '?').toLowerCase();
        }
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
ROOT_SCROLL_READ = (
    "var se = document.scrollingElement || document.body;"
    "return se ? [se.scrollHeight, se.scrollTop] : [0, 0];"
)


class TargetProbe:
    """Runs the probe and judges its answers. Owns no clicking or scrolling."""

    def __init__(self, state: PageActionContext) -> None:
        self._state = state

    def run(self, element: ElementInterface) -> dict | None:
        """The one-round-trip probe. None means undetermined — and
        undetermined proceeds, exactly as the old guard required."""
        try:
            raw = self._state.browser.execute_script(
                PROBE_SCRIPT, element, list(CHALLENGE_WIDGET_MARKERS)
            )
        except Exception as exc:
            logger.debug("target probe failed, proceeding | %s", exc)
            return None
        if not isinstance(raw, dict):
            return None
        vp = raw.get("viewport")
        if isinstance(vp, dict) and vp.get("w") and vp.get("h"):
            self._state.last_viewport = (int(vp["w"]), int(vp["h"]))
            dpr = raw.get("dpr")
            if dpr and "dpr" not in self._state.logged_caps:
                # One-time diagnostic: display scaling + viewport, for the
                # live-run measurement of W3C coordinates under 125-150% scaling.
                self._state.logged_caps.add("dpr")
                logger.debug(
                    "motion | viewport=%sx%s dpr=%s",
                    vp["w"], vp["h"], dpr,
                )
        return raw

    @staticmethod
    def verdict_outcome(verdict: str) -> tuple[bool | None, str]:
        """Maps a probe verdict to the guard's three outcomes.

        ``None`` (undetermined) proceeds — refusing to click because we
        could not look is how a guard becomes worse than no guard.
        ``pane-clip`` is a refusal verdict: the click ladder scrolls first
        and only refuses when the clip persists (see Clicker.click).
        """
        if verdict == "ok":
            return True, "reachable"
        if verdict == "challenge":
            return False, "challenge"
        if verdict == "pane-clip":
            return False, "clipped by its scroll pane"
        if verdict == "offscreen" or not verdict:
            return None, "outside the viewport"
        return False, verdict

    def viewport_from_probe(self, probe: dict | None) -> tuple[int, int] | None:
        vp = (probe or {}).get("viewport")
        if isinstance(vp, dict) and vp.get("w") and vp.get("h"):
            return (int(vp["w"]), int(vp["h"]))
        return self._state.last_viewport

    @staticmethod
    def inside_viewport(point: tuple[int, int], viewport: tuple[int, int]) -> bool:
        x, y = point
        return 0 <= x < viewport[0] and 0 <= y < viewport[1]

    @staticmethod
    def absolute_box(probe: dict | None) -> dict | None:
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
    def pane_origin(pane: dict) -> tuple[int, int]:
        ox, oy = pane.get("ox"), pane.get("oy")
        if ox is None or oy is None:
            return (
                int(pane.get("x", 0) + pane.get("w", 0) / 2),
                int(pane.get("y", 0) + pane.get("h", 0) / 2),
            )
        return (int(ox), int(oy))

    @staticmethod
    def match_pane_offsets(probe: dict | None, pane: dict) -> tuple[float, float] | None:
        for p in (probe or {}).get("panes") or []:
            if (
                abs(p.get("x", 0) - pane.get("x", 0)) < 2
                and abs(p.get("y", 0) - pane.get("y", 0)) < 2
                and abs(p.get("w", 0) - pane.get("w", 0)) < 2
            ):
                return (float(p.get("top", 0)), float(p.get("left", 0)))
        return None

    @staticmethod
    def axis_need(lo: float, hi: float, region_lo: float, region_len: float) -> float:
        """Signed scroll needed on ONE axis; 0 when the box is already (even
        partly) visible on that axis.

        G1, measured live: judging need from the box's distance to the
        viewport CENTRE sent vertical scrolls to the JS fallback whenever a
        target sat further from the centre column than below the fold. An
        axis needs a scroll only when the target lies outside the visible
        range on that axis.
        """
        if hi > region_lo and lo < region_lo + region_len:
            return 0.0
        return (lo + hi) / 2.0 - (region_lo + region_len / 2.0)

    @staticmethod
    def visible_region(probe: dict | None) -> tuple[float, float, float, float]:
        """The region the target must sit in to be truly visible: the window
        viewport intersected with every scrolling ancestor's client rect
        (G2 — a target inside the window but clipped by its pane's overflow
        is NOT visible). The probe's own window entry equals the viewport,
        so intersecting with it is a no-op. Returns (x, y, w, h); w or h of
        0 means fully clipped.
        """
        vp = (probe or {}).get("viewport") or {}
        x, y = 0.0, 0.0
        w, h = float(vp.get("w", 0) or 0), float(vp.get("h", 0) or 0)
        for pane in (probe or {}).get("panes") or []:
            px = float(pane.get("x", 0) or 0)
            py = float(pane.get("y", 0) or 0)
            pw = float(pane.get("w", 0) or 0)
            ph = float(pane.get("h", 0) or 0)
            if pw <= 0 or ph <= 0:
                continue
            nx, ny = max(x, px), max(y, py)
            nx2, ny2 = min(x + w, px + pw), min(y + h, py + ph)
            if nx2 <= nx or ny2 <= ny:
                return (nx, ny, 0.0, 0.0)
            x, y, w, h = nx, ny, nx2 - nx, ny2 - ny
        return (x, y, w, h)

    def capabilities(self) -> MotionCapabilities:
        try:
            caps = self._state.browser.motion_capabilities
        except Exception:
            return MotionCapabilities()
        if not isinstance(caps, MotionCapabilities):
            return MotionCapabilities()
        return caps

    def note_capability_gap(self, gap: str) -> None:
        """Loud degradation, once per gap per session."""
        if gap not in self._state.logged_caps:
            self._state.logged_caps.add(gap)
            logger.info(
                "motion | capability unavailable on this driver: %s — degrading loudly",
                gap,
            )

    def effect_snapshot(self) -> tuple[str, int, str]:
        """(url, body length, focused-element signature) in one round trip.

        LIMIT, stated honestly: ``effect="none"`` means none of these cheap
        channels changed. It cannot rule out a handler that leaves no such
        trace (silent XHR, analytics) — it is a floor, not a verdict.
        """
        try:
            raw = self._state.browser.execute_script(
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

    def observe_effect(self, before: tuple[str, int, str]) -> str:
        after = self.effect_snapshot()
        if after[0] != before[0]:
            return "navigation"
        if after[1] != before[1]:
            return "dom-change"
        if after[2] != before[2]:
            return "focus-change"
        return "none"

    def attachment_check(self, element: ElementInterface) -> ActionResult | None:
        """Fail-fast staleness gate. Returns a refusal for a stale element,
        None when the element is attached (or the check itself could not
        answer — a failed CHECK must not block the ladder).

        Both drivers fail fast here: Selenium raises a stale-reference error
        immediately; Playwright's handle resolution is bounded at the
        configured timeout (D6, was 3 x 30s down the ladder).
        """
        try:
            attached = self._state.browser.execute_script(
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
