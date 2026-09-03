"""Browser-side card activation: relocate, click, and read what the click reveals.

This is the only stage that touches the live browser, and it runs strictly
*after* the harvest's scroll loop — never inside it. The outcome of a click
is classified, not assumed:

* top-level navigation -> the new location IS the destination;
* revealed anchors     -> passed through the same fail-closed classifier as
                          static anchors (an ad revealed by a click is still
                          an ad);
* nothing              -> an honest empty outcome.

Relocation uses only the identity attribute learned from the page itself —
no hardcoded selectors anywhere.
"""

from __future__ import annotations

import logging
import time
import urllib.parse
from dataclasses import dataclass

from auto_apply.domain.ports.page_understanding_port import (
    JobUrlCandidate,
    JobUrlRejection,
)
from auto_apply.domain.services.url_evidence import (
    canonical_url,
    evaluate_candidates,
)

logger = logging.getLogger(__name__)

ANCHORS_JS = """
return [...document.querySelectorAll('a[href]')].map(a => ({
    href: a.href,
    text: (a.innerText || a.textContent || '').trim().slice(0, 120)
}));
"""


@dataclass(frozen=True)
class ActivationOutcome:
    """What one click produced. Empty fields are honest outcomes."""

    candidates: tuple[JobUrlCandidate, ...] = ()
    rejections: tuple[JobUrlRejection, ...] = ()
    revealed_count: int = 0
    navigated: bool = False
    error: str = ""


class CardActivator:
    """Relocates a card in the live DOM and activates it.

    Args:
        browser: The live browser (BrowserInterface-shaped).
        readiness: Optional DomReadinessPort; used to wait for the panel or
            navigation to settle. When absent, a fixed settle is used.
        settle_seconds: Fixed wait when no readiness port is available.
    """

    def __init__(self, browser, readiness=None, settle_seconds: float = 2.0) -> None:
        self._browser = browser
        self._readiness = readiness
        self._settle_seconds = float(settle_seconds)

    def activate(
        self,
        *,
        identity_attribute: str,
        identity_value: str,
        title: str,
        serp_host: str,
        page_url: str,
    ) -> ActivationOutcome:
        """Relocate by learned identity, click, and classify the outcome."""
        element, error = self._relocate(identity_attribute, identity_value)
        if element is None:
            return ActivationOutcome(error=error)

        before = self._anchor_snapshot()
        try:
            element.click()
        except Exception as exc:
            return ActivationOutcome(error=f"click failed: {exc}")

        self._wait_for_settle()
        after = self._anchor_snapshot()

        current_url = self._current_url()
        if current_url and _without_fragment(current_url) != _without_fragment(page_url):
            nav = JobUrlCandidate(
                url=current_url,
                original_url=current_url,
                anchor_text=title,
                source="navigation",
                score=2.0,
                title_overlap=1.0,
                method="top-level navigation",
                apply_intent=False,
                pending_redirect=False,
                canonical_url=canonical_url(current_url, page_url),
            )
            return ActivationOutcome(
                candidates=(nav,), navigated=True, revealed_count=1
            )

        revealed = _fresh_anchors(before, after, page_url)
        if not revealed:
            return ActivationOutcome(revealed_count=0)

        candidates, rejections = evaluate_candidates(
            revealed, title=title, serp_host=serp_host, base_url=page_url
        )
        return ActivationOutcome(
            candidates=candidates,
            rejections=rejections,
            revealed_count=len(revealed),
        )

    def _relocate(self, name: str, value: str):
        """Find the live element carrying the learned identity attribute."""
        if not name or not value:
            return None, "no learned identity attribute on this card"
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        selector = f'[{name}="{escaped}"]'
        try:
            found = self._browser.find_elements("css selector", selector)
        except Exception as exc:
            return None, f"relocation failed for {selector}: {exc}"
        if len(found) != 1:
            return None, (
                f"identity {selector} matches {len(found)} live elements; "
                f"aborting rather than guessing"
            )
        return found[0], ""

    def _wait_for_settle(self) -> None:
        if self._readiness is not None:
            try:
                self._readiness.wait_for_dom_stable()
                return
            except Exception:
                pass
        time.sleep(self._settle_seconds)

    def _anchor_snapshot(self) -> list[dict[str, str]]:
        try:
            raw = self._browser.execute_script(ANCHORS_JS)
        except Exception:
            return []
        if not isinstance(raw, list):
            return []
        snapshot: list[dict[str, str]] = []
        for anchor in raw:
            if not isinstance(anchor, dict):
                continue
            href = str(anchor.get("href") or "")
            if href:
                snapshot.append({"href": href, "text": str(anchor.get("text") or "")})
        return snapshot

    def _current_url(self) -> str:
        try:
            return str(getattr(self._browser, "current_url", "") or "")
        except Exception:
            return ""


def _without_fragment(url: str) -> str:
    return urllib.parse.urlsplit(url)._replace(fragment="").geturl()


def _fresh_anchors(
    before: list[dict[str, str]],
    after: list[dict[str, str]],
    base_url: str,
) -> list[dict[str, str]]:
    """Anchors present after the click that were absent before it."""
    before_keys = {
        canonical_url(a["href"], base_url) for a in before if a.get("href")
    }
    fresh: list[dict[str, str]] = []
    for anchor in after:
        href = anchor.get("href", "")
        if href and canonical_url(href, base_url) not in before_keys:
            fresh.append({"href": href, "text": anchor.get("text", ""), "source": "revealed"})
    return fresh
