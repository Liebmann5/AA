"""VerifiedPageAdvancer — one verified page advance, nothing else.

The ladder (each rung tried only after the one above fails to VERIFY):

    1. URL template   — the page number lives in the URL (pure data from
                        engine YAML; cheapest and most deterministic).
    2. rel=next       — the standards-based link relation.
    3. structural     — the control after the current-page marker
                        (aria-current / aria-selected / active class), or an
                        arrow glyph after it, inside a pagination container.
    4. numbered       — the link whose number is current+1.
    5. load-more      — a button after the feed, verified by GROWTH.
    6. scroll growth  — the interaction tool's measured feed scroll.

Language-agnostic by construction: no English word lists anywhere. Controls
are found inside nav/pagination containers with carousel/slider exclusions;
"current page" comes from aria-current and friends, "next" from structure
and position. The one acknowledged limit: the load-more rung matches
English tokens in class/id ATTRIBUTES (developer-facing, English on most
localized sites) — it is the weakest rung, growth-verified, and bounded to
a single candidate per page.

Every advance is verified by a page fingerprint — (url, anchor count, first
href, last href, scrollHeight) — polled within a bounded budget (the
readiness port when injected). Template and control rungs verify by RESULT-
LIST identity (first/last hrefs): a URL change AA caused itself is no
evidence (measured: a page that ignored the parameter was harvested twice
as "page 2"). Load-more and scroll rungs verify by growth. advanced=True
always means verified=True; "we clicked and nothing provably changed" is a
stop with a reason, never a re-mine of the old page wearing a new number.

The scans return DATA plus a generated root-positional XPath per candidate,
never a DOM node: Playwright's evaluate cannot return one (measured: the
element arrives as the string 'ref: <Node>'), and every control rung died
on AA's default framework. Candidates are re-found through find_element —
read-only, no marker attributes, nothing for the page to observe.
"""
from __future__ import annotations

import logging
import time

from auto_apply.domain.models.page_advance import (
    AdvanceMethod,
    AdvanceOutcome,
    StopReason,
    UrlPageTemplate,
)
from auto_apply.domain.ports.page_advance_port import PageAdvancePort
from auto_apply.domain.services.url_templating import next_page_url
from auto_apply.domain.types import Locator

logger = logging.getLogger(__name__)

_FINGERPRINT_JS = """
var a = [...document.querySelectorAll('a[href]')].map(x => x.href);
var se = document.scrollingElement || document.body;
return [location.href, a.length, a[0] || '', a[a.length-1] || '',
        se ? se.scrollHeight : 0];
"""

_XPATH_BUILDER_JS = """
function xp(el) {
    if (!el || !el.tagName) { return ''; }
    var parts = [];
    for (var e = el; e && e.tagName && e.tagName.toLowerCase() !== 'html';
         e = e.parentElement) {
        var tag = e.tagName.toLowerCase();
        var i = 1;
        for (var s = e.previousElementSibling; s;
             s = s.previousElementSibling) {
            if (s.tagName === e.tagName) { i++; }
        }
        parts.unshift(tag + '[' + i + ']');
    }
    return '/html/' + parts.join('/');
}
"""

_CANDIDATES_JS = (
    _XPATH_BUILDER_JS
    + """
var out = [];
var push = function (el, kind, score) {
    if (!el) { return; }
    var r = el.getBoundingClientRect();
    var cs = window.getComputedStyle(el);
    if (r.width <= 0 || r.height <= 0 || cs.display === 'none' ||
        cs.visibility === 'hidden') { return; }
    for (var e = el; e; e = e.parentElement) {
        var s = String(e.className || '') + ' ' + (e.id || '');
        if (/carousel|slider|slideshow|swiper|gallery/i.test(s)) { return; }
    }
    out.push({xpath: xp(el), kind: kind, score: score,
              text: (el.textContent || '').trim().slice(0, 40)});
};
document.querySelectorAll('a[rel], area[rel]').forEach(function (el) {
    var rel = (el.getAttribute('rel') || '').toLowerCase().split(/\\s+/);
    if (rel.indexOf('next') !== -1) { push(el, 'rel-next', 100); }
});
document.querySelectorAll(
    'nav, [role="navigation"], [class*="pag" i], [id*="pag" i]'
).forEach(function (box) {
    var current = box.querySelector(
        '[aria-current], [aria-selected="true"], .active, .selected');
    if (!current) { return; }
    var sib = current.nextElementSibling;
    if (sib) {
        var a = sib.matches('a, button') ? sib : sib.querySelector('a, button');
        if (a) { push(a, 'after-current', 80); }
    }
    var n = parseInt((current.textContent || '').trim(), 10);
    var cr = current.getBoundingClientRect();
    box.querySelectorAll('a, button').forEach(function (b) {
        var t = (b.textContent || '').trim();
        if (!isNaN(n) && parseInt(t, 10) === n + 1) { push(b, 'numbered', 70); }
        if (/^(›|»|→|>|▸|►|⟩|➜|➡)$/.test(t) ||
            /chevron|arrow/i.test(String(b.className || ''))) {
            var br = b.getBoundingClientRect();
            if (br.left >= cr.left) { push(b, 'arrow', 60); }
        }
    });
});
var seen = [];
var uniq = [];
out.forEach(function (c) {
    var i = seen.indexOf(c.xpath);
    if (i === -1) { seen.push(c.xpath); uniq.push(c); }
    else if (c.score > uniq[i].score) { uniq[i] = c; }
});
uniq.sort(function (a, b) { return b.score - a.score; });
return uniq.slice(0, 6).map(function (c) {
    return {kind: c.kind, score: c.score, text: c.text, xpath: c.xpath};
});
"""
)

_LOAD_MORE_JS = (
    _XPATH_BUILDER_JS
    + """
var out = [];
document.querySelectorAll(
    'button, [role="button"], input[type="button"]'
).forEach(function (b) {
    if (out.length >= 1) { return; }
    var r = b.getBoundingClientRect();
    var cs = window.getComputedStyle(b);
    if (r.width <= 0 || r.height <= 0 || cs.display === 'none' ||
        cs.visibility === 'hidden') { return; }
    var ci = (String(b.className || '') + ' ' + (b.id || '')).toLowerCase();
    if (!/more|load|pagin|next|show/.test(ci)) { return; }
    for (var e = b; e; e = e.parentElement) {
        var tag = (e.tagName || '').toLowerCase();
        if (tag === 'nav' || tag === 'header' || tag === 'footer') { return; }
        var s = String(e.className || '') + ' ' + (e.id || '');
        if (/carousel|slider|slideshow|swiper|gallery/i.test(s)) { return; }
    }
    // "After the feed" means below the link mass's midpoint, not below a
    // fixed share of the document: scrollHeight is never below the
    // viewport, so the old 25%-of-document rule dropped every short page's
    // button (measured on real Chrome through Selenium).
    var ys = [];
    document.querySelectorAll('a[href]').forEach(function (a) {
        ys.push(a.getBoundingClientRect().top + window.scrollY);
    });
    if (ys.length) {
        var minY = Math.min.apply(null, ys);
        var maxY = Math.max.apply(null, ys);
        if (r.top + window.scrollY < (minY + maxY) / 2) { return; }
    }
    out.push({kind: 'load-more', score: 40,
              text: (b.textContent || '').trim().slice(0, 40), xpath: xp(b)});
});
return out;
"""
)

_KIND_TO_METHOD = {
    "rel-next": AdvanceMethod.REL_NEXT,
    "after-current": AdvanceMethod.STRUCTURAL,
    "arrow": AdvanceMethod.STRUCTURAL,
    "numbered": AdvanceMethod.NUMBERED,
}

_MAX_CLICK_ATTEMPTS = 4


class VerifiedPageAdvancer(PageAdvancePort):
    """One stateless-per-query verified page advancer.

    Args:
        browser: BrowserInterface — snapshot taker and (last resort) navigator.
        page_action: PageActionPrimitives — every click travels the ladder.
            None means click rungs are honestly skipped (template and scroll
            rungs still work).
        navigator: PageNavigationPort for the template rung; defaults to
            page_action (PageActionService implements both ports). Without
            either, ``browser.get`` is used directly.
        readiness: Optional DomReadinessPort — the change wait is measured
            when present, polled otherwise.
        url_template: Optional UrlPageTemplate (engine YAML); None falls
            through to structural rungs.
        scroll: Optional zero-arg callable returning bool — the tool's
            measured scroll_to_bottom. None disables the scroll rung.
        change_timeout_s: Bound on proving the page changed.
        engine: Engine name, for logs and future selector scoping.
    """

    def __init__(
        self,
        *,
        browser,
        page_action=None,
        navigator=None,
        readiness=None,
        url_template: UrlPageTemplate | None = None,
        scroll=None,
        change_timeout_s: float = 4.0,
        engine: str = "",
    ) -> None:
        self._browser = browser
        self._page_action = page_action
        self._navigator = navigator if navigator is not None else page_action
        self._readiness = readiness
        self._template = url_template
        self._scroll = scroll
        self._change_timeout = max(0.5, float(change_timeout_s))
        self._engine = engine
        self._page_number = 1

    def advance(self) -> AdvanceOutcome:
        """One verified step forward. Never raises; never claims unverified."""
        if self._browser is None:
            return AdvanceOutcome(False, stop_reason=StopReason.NO_BROWSER)
        before = self._fingerprint()
        if before is None:
            return AdvanceOutcome(
                False, stop_reason=StopReason.ERROR, detail="fingerprint failed"
            )
        clicked = False

        # Rung 1 — URL template.
        if self._template is not None:
            target = next_page_url(
                self._template, self._current_url(), self._page_number + 1
            )
            if target and self._navigate(target):
                # AA set the URL itself, so a URL change proves NOTHING —
                # only a changed result list (first/last identities)
                # verifies a template advance.
                if self._await_change(before, verification="list") is not None:
                    self._page_number += 1
                    return AdvanceOutcome(
                        True, method=AdvanceMethod.TEMPLATE, verified=True
                    )
                logger.debug(
                    "PageAdvancer[%s]: template advance unverified — "
                    "falling through to control rungs",
                    self._engine or "?",
                )

        # Rungs 2–4 — rel=next, structural, numbered (score order IS the ladder).
        attempts = 0
        for candidate in self._candidates():
            method = _KIND_TO_METHOD.get(str(candidate.get("kind") or ""))
            if method is None or attempts >= _MAX_CLICK_ATTEMPTS:
                continue
            element = self._resolve(candidate)
            if element is None:
                continue
            attempts += 1
            if not self._click(element):
                continue
            clicked = True
            if self._await_change(before, verification="list") is not None:
                self._page_number += 1
                return AdvanceOutcome(True, method=method, verified=True)

        # Rung 5 — load-more, verified by growth.
        for candidate in self._load_more_candidates()[:1]:
            element = self._resolve(candidate)
            if element is None:
                continue
            if not self._click(element):
                continue
            clicked = True
            if self._await_change(before, verification="growth") is not None:
                return AdvanceOutcome(
                    True, method=AdvanceMethod.LOAD_MORE, verified=True
                )

        # Rung 6 — scroll growth (the measured feed primitive).
        if callable(self._scroll):
            try:
                moved = bool(self._scroll())
            except Exception as exc:
                logger.debug("PageAdvancer: scroll rung failed: %s", exc)
                moved = False
            if moved and self._await_change(before, verification="growth") is not None:
                return AdvanceOutcome(
                    True, method=AdvanceMethod.SCROLL_GROWTH, verified=True
                )

        return AdvanceOutcome(
            False,
            stop_reason=StopReason.NO_CHANGE if clicked else StopReason.NO_NEXT,
        )

    # ── collaborators ────────────────────────────────────────────────────

    def _click(self, element) -> bool:
        if self._page_action is None:
            return False
        try:
            return bool(self._page_action.click(element))
        except Exception as exc:
            logger.debug("PageAdvancer: control click failed: %s", exc)
            return False

    def _navigate(self, url: str) -> bool:
        navigator = self._navigator
        if navigator is not None and callable(getattr(navigator, "navigate", None)):
            try:
                return bool(navigator.navigate(url))
            except Exception as exc:
                logger.debug("PageAdvancer: template navigation failed: %s", exc)
                return False
        try:
            self._browser.get(url)
            return True
        except Exception as exc:
            logger.debug("PageAdvancer: template navigation failed: %s", exc)
            return False

    def _current_url(self) -> str:
        try:
            return str(getattr(self._browser, "current_url", "") or "")
        except Exception:
            return ""

    def _candidates(self) -> list[dict]:
        try:
            raw = self._browser.execute_script(_CANDIDATES_JS)
        except Exception as exc:
            logger.debug("PageAdvancer: candidate scan failed: %s", exc)
            return []
        return [c for c in raw if isinstance(c, dict)] if isinstance(raw, list) else []

    def _load_more_candidates(self) -> list[dict]:
        try:
            raw = self._browser.execute_script(_LOAD_MORE_JS)
        except Exception as exc:
            logger.debug("PageAdvancer: load-more scan failed: %s", exc)
            return []
        return [c for c in raw if isinstance(c, dict)] if isinstance(raw, list) else []

    def _resolve(self, candidate: dict):
        """Re-find a scanned candidate through the port.

        Playwright cannot return a DOM node from page.evaluate (measured:
        the element arrives as the string ``'ref: <Node>'``), so the scans
        return a generated root-positional XPath and the element is
        re-found through find_element. Read-only by design: a marker
        attribute would be a page mutation the site can observe. None
        means the DOM moved under us — the candidate is skipped, honestly.
        """
        xpath = str(candidate.get("xpath") or "")
        if not xpath:
            return None
        try:
            return self._browser.find_element(Locator.XPATH, xpath)
        except Exception as exc:
            logger.debug("PageAdvancer: re-find failed for %s: %s", xpath, exc)
            return None

    # ── verification ─────────────────────────────────────────────────────

    def _fingerprint(self) -> tuple | None:
        try:
            result = self._browser.execute_script(_FINGERPRINT_JS)
        except Exception:
            return None
        if isinstance(result, (list, tuple)) and len(result) == 5:
            return tuple(result)
        return None

    @staticmethod
    def _differs(before: tuple, now: tuple, verification: str) -> bool:
        if verification == "growth":
            return now[1] > before[1] or now[4] > before[4]
        # "list" — first/last result identities. The only proof that means
        # anything when AA itself navigated (a URL change it caused is no
        # evidence) or clicked a control.
        return now[2] != before[2] or now[3] != before[3]

    def _await_change(self, before: tuple, *, verification: str) -> tuple | None:
        """The fingerprint after the page provably changed, or None.

        ``verification`` names the proof: "list" (first/last result
        identities changed — template and control rungs) or "growth" (the
        feed grew — load-more and scroll rungs). Measured via the readiness
        port when injected; otherwise polled, bounded by change_timeout_s
        either way.
        """
        if self._readiness is not None:
            try:
                self._readiness.wait_for_dom_stable(timeout=self._change_timeout)
            except Exception:
                pass
            now = self._fingerprint()
            if now is not None and self._differs(before, now, verification):
                return now
            return None
        deadline = time.monotonic() + self._change_timeout
        while time.monotonic() < deadline:
            now = self._fingerprint()
            if now is not None and self._differs(before, now, verification):
                return now
            time.sleep(0.15)
        return None
