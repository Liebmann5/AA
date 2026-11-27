"""PageObservation (CT-T-002, CT-DS-001): one frozen reading of a page.

An observation is *what was seen*, not *when*: its ``content_hash`` covers
the URL, title and document, never the epoch. Two readings of an unchanged
page therefore share analysis results (the cache keys on content), while a
consumer still learns from the epoch whether a finding is current
(CT-INV-003). This closes the stale-cache hole of an epoch-keyed cache: a
page that changed without an action we observed (a timer, a push update)
has a different hash, so nothing computed on the old content is reused.

The ``epoch`` counter belongs to the caller (the engine increments it on
every action that can change the page: click, type, navigate, window event,
human pause). The library never increments it itself.
"""

from __future__ import annotations

import dataclasses
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from pagecomp.doc import (
    Doc,
    DocLimits,
    FrameInfo,
    Truncation,
    from_cdp,
    from_html,
    from_snapshot,
)

#: Capability names (05 section 5). An adapter declares what it provided.
SNAPSHOT_HTML = "SNAPSHOT_HTML"
SHADOW_PIERCING = "SHADOW_PIERCING"
IFRAME_TRAVERSAL = "IFRAME_TRAVERSAL"
SNAPSHOT_LAYOUT = "SNAPSHOT_LAYOUT"
AX_TREE = "AX_TREE"
#: Gap capabilities: declared when an adapter knows it could NOT see something.
CLOSED_SHADOW_UNSEEN = "CLOSED_SHADOW_UNSEEN"
CROSS_ORIGIN_UNSEEN = "CROSS_ORIGIN_UNSEEN"

#: Read flags: facts about how the read went (never exceptions).
FLAG_STALE = "stale"                      # the page changed during the read
FLAG_NAVIGATED = "navigated"              # document replaced during the read
FLAG_SPA_NAVIGATED = "spa-navigated"      # same document, URL changed (pushState)
FLAG_SCRIPT_DEADLINE = "script-deadline"  # the in-page walk hit its deadline
FLAG_WALL_TIME = "wall-time"              # the adapter's wall-time budget ran out
FLAG_FRAME_DETACHED = "frame-detached"
FLAG_FRAME_NAVIGATED = "frame-navigated"
FLAG_PARTIAL = "partial"                  # some content is missing; see truncations


@dataclass(frozen=True)
class PageObservation:
    url: str
    title: str
    doc: Doc
    epoch: int = 0
    requested_url: str | None = None
    capabilities: frozenset[str] = frozenset()
    environment: Mapping[str, Any] = field(default_factory=dict)
    query: str | None = None  # the search words that led here, if any
    read_flags: frozenset[str] = frozenset()
    timings: Mapping[str, float] = field(default_factory=dict)  # adapter-measured, never hashed
    adapter: str = ""

    @property
    def frames(self) -> tuple[FrameInfo, ...]:
        return self.doc.frames

    @property
    def stale(self) -> bool:
        return FLAG_STALE in self.read_flags

    @property
    def complete(self) -> bool:
        """No cap fired and nothing was flagged: the read is the whole page."""
        return not self.doc.truncations and not (self.read_flags - {FLAG_SPA_NAVIGATED})

    @property
    def truncations(self) -> tuple[Truncation, ...]:
        return self.doc.truncations

    @property
    def content_hash(self) -> str:
        h = hashlib.sha256()
        h.update(self.url.encode("utf-8", "surrogatepass") + b"\x00")
        h.update(self.title.encode("utf-8", "surrogatepass") + b"\x00")
        h.update((self.requested_url or "").encode("utf-8", "surrogatepass") + b"\x00")
        h.update((self.query or "").encode("utf-8", "surrogatepass") + b"\x00")
        h.update(self.doc.content_hash.encode())
        return h.hexdigest()[:32]

    def at_epoch(self, epoch: int) -> "PageObservation":
        return dataclasses.replace(self, epoch=epoch)


def observe_html(html: str, *, url: str, title: str = "", epoch: int = 0,
                 requested_url: str | None = None, query: str | None = None,
                 limits: DocLimits | None = None,
                 environment: Mapping[str, Any] | None = None) -> PageObservation:
    """Observation from serialized HTML (no shadow content unless declarative)."""
    doc = from_html(html, url, limits)
    return PageObservation(url, title, doc, epoch, requested_url,
                           frozenset({SNAPSHOT_HTML}), dict(environment or {}), query)


def observe_cdp(dom: Mapping[str, Any], *, url: str, title: str = "", epoch: int = 0,
                requested_url: str | None = None, query: str | None = None,
                limits: DocLimits | None = None,
                environment: Mapping[str, Any] | None = None) -> PageObservation:
    """Observation from a pierced protocol DOM: shadow roots and frames included."""
    doc = from_cdp(dom, url, limits)
    caps = frozenset({SNAPSHOT_HTML, SHADOW_PIERCING, IFRAME_TRAVERSAL})
    return PageObservation(url, title, doc, epoch, requested_url, caps,
                           dict(environment or {}), query)


def observe_snapshot(snapshot: Mapping[str, Any], *, url: str, dom: Mapping[str, Any] | None = None,
                     title: str = "", epoch: int = 0, requested_url: str | None = None,
                     query: str | None = None, limits: DocLimits | None = None,
                     environment: Mapping[str, Any] | None = None,
                     viewport: tuple[float, float] = (0.0, 0.0)) -> PageObservation:
    """Observation with layout: ``DOMSnapshot`` boxes and computed style,
    joined onto the pierced DOM when ``dom`` is given."""
    doc = from_snapshot(snapshot, url, limits, dom=dom, viewport=viewport)
    caps = {SNAPSHOT_HTML, SNAPSHOT_LAYOUT}
    if dom is not None:
        caps |= {SHADOW_PIERCING, IFRAME_TRAVERSAL}
    return PageObservation(url, title, doc, epoch, requested_url, frozenset(caps),
                           dict(environment or {}), query)
