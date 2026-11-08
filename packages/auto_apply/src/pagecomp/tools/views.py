"""Views (CT-T-028, 05 s16): every alternate view a page advertises.

From one observation: ``link rel=canonical`` (same or other host),
``rel=alternate`` feeds (RSS/Atom), mobile and language alternates,
``rel=amphtml``, print links, ``og:url``, embedded frames that carry a form
or board of their own (own URL), JSON-LD ``JobPosting`` (fields without a
page load), and whether this page is a **guest view** (a sign-in overlay or
"sign in to see more" over a partial description: useful, supported, never
worked around; owner ruling). The record key follows 05 s16: canonical URL,
else the posting's identifier, else (host, normalised title, location).

Vendor APIs are not discovered from pages (they come from AA's catalog), and
the ``Sitemap:`` lines of robots.txt are read by ``channels.robots_sitemaps``.
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pagecomp.doc import ELEMENT, FRAME
from pagecomp.links import canonical_url, hosts_related
from pagecomp.registry import ToolSpec
from pagecomp.results import Evidence, Ok
from pagecomp.text import key

FIELDS = ("title", "company", "location", "pay", "date_posted", "valid_through", "apply_target",
          "description")


@dataclass(frozen=True)
class View:
    kind: str          # page_guest | page_signed_in | page | embedded | own_url | jsonld | feed | amp
                       # | mobile | print | mirror | lang
    locator: str       # URL (or "#jsonld" for in-page data)
    access: str        # public | needs_sign_in | unknown
    requests: int      # requests to read it (0 for in-page data)
    footprint: int     # 0 none (already loaded) .. 3 full browser load with scripts
    fields: tuple[str, ...]
    evidence: str


@dataclass(frozen=True)
class ViewMap:
    record_key: str
    views: tuple[View, ...]
    guest: bool


def _abs(href: str, base: str) -> str:
    try:
        return urllib.parse.urljoin(base, href) if base else href
    except ValueError:
        return href


def _run(q: Any, params: Mapping[str, Any]) -> Ok[ViewMap]:
    doc = q.doc
    url = q.obs.url
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    structured = q.maybe("structured")
    verdict = q.maybe("verdict")
    text = q.maybe("pagetext")
    q.tick(len(doc))
    views: list[View] = []
    canonical = ""
    seen: set[tuple[str, str]] = set()

    def add(v: View) -> None:
        k = (v.kind, v.locator)
        if k not in seen:
            seen.add(k)
            views.append(v)

    for i in doc.elements("link"):
        rel = set((doc.attr(i, "rel") or "").lower().split())
        href = _abs(doc.attr(i, "href") or "", url)
        if not href:
            continue
        typ = (doc.attr(i, "type") or "").lower()
        if "canonical" in rel:
            canonical = canonical_url(href)
            if not hosts_related(urllib.parse.urlsplit(href).hostname or "", host):
                add(View("mirror", href, "unknown", 1, 3, (), "rel=canonical on another host"))
        if "alternate" in rel and ("rss" in typ or "atom" in typ):
            add(View("feed", href, "unknown", 1, 1, ("title", "apply_target", "date_posted"),
                     f"rel=alternate {typ}"))
        elif "alternate" in rel and doc.attr(i, "hreflang"):
            add(View("lang", href, "unknown", 1, 3, (), f"hreflang={doc.attr(i, 'hreflang')}"))
        elif "alternate" in rel and "handheld" in (doc.attr(i, "media") or "").lower():
            add(View("mobile", href, "unknown", 1, 2, (), "rel=alternate media=handheld"))
        if "amphtml" in rel:
            add(View("amp", href, "unknown", 1, 2, FIELDS[:4], "rel=amphtml"))
    for i in doc.elements("meta"):
        if (doc.attr(i, "property") or "").lower() == "og:url" and doc.attr(i, "content"):
            og = canonical_url(_abs(doc.attr(i, "content") or "", url))
            if not canonical:
                canonical = og
    for i in doc.elements("a"):
        name = key(doc.accessible_name(i))
        href = doc.attr(i, "href") or ""
        if name in ("print", "print this job", "printer friendly", "print job") or "print=" in href:
            add(View("print", _abs(href, url), "unknown", 1, 1, FIELDS, "print link"))
    forms = q.maybe("forms")
    for f in doc.frames if hasattr(doc, "frames") else ():
        if f.url and f.url.startswith("http") and not hosts_related(urllib.parse.urlsplit(f.url).hostname or "", host):
            carries_form = forms is not None and any(
                c.in_frame and f.document >= 0 and doc.is_ancestor(f.document, c.node) for c in forms.controls)
            add(View("embedded" if carries_form else "own_url", f.url, "unknown", 1, 3,
                     ("apply_target",) if carries_form else (), "cross-origin frame with its own URL"))
    if not views or all(v.kind != "embedded" for v in views):
        for i in range(len(doc)):
            if doc.kind[i] == ELEMENT and doc.tag_name(i) == "iframe":
                src = _abs(doc.attr(i, "src") or "", url)
                if src.startswith("http") and not hosts_related(urllib.parse.urlsplit(src).hostname or "", host):
                    has_doc = any(doc.kind[c] == FRAME for c in doc.children(i))
                    if not has_doc and any(t in src for t in ("form", "apply", "job", "board", "career")):
                        add(View("own_url", src, "unknown", 1, 3, (), "iframe src (frame not read)"))
    if structured is not None and structured.postings:
        p = structured.postings[0]
        got = [f for f, v in (("title", p.title), ("company", p.organization), ("location", p.locations),
                              ("pay", p.salary), ("date_posted", p.date_posted),
                              ("valid_through", p.valid_through), ("apply_target", p.url),
                              ("description", p.description)) if v]
        add(View("jsonld", "#jsonld", "public", 0, 0, tuple(got), "JSON-LD JobPosting"))
    # A guest view: a sign-in overlay over the page, or the page saying the
    # rest is behind sign-in. (A login *wall* is no view at all: the verdict
    # handles it.)
    guest = False
    if verdict is not None and not verdict.login_wall:
        partial = text is not None and any(s in text.folded for s in (
            "sign in to see", "sign in to view", "join to see", "log in to see", "join now to see"))
        guest = "login" in verdict.overlays or partial
    page_kind = "page_guest" if guest else "page"
    add(View(page_kind, url, "public", 0, 0, FIELDS if not guest else FIELDS[:4],
             "this page" + (" (guest view: partial fields)" if guest else "")))
    if canonical and canonical != canonical_url(url):
        add(View("own_url", canonical, "unknown", 1, 3, FIELDS, "rel=canonical / og:url"))
    record_key = canonical or ""
    if not record_key and structured is not None and structured.postings:
        p = structured.postings[0]
        record_key = (canonical_url(p.url) if p.url else
                      (f"id:{host}:{p.identifier}" if p.identifier else ""))
    if not record_key and structured is not None and structured.postings:
        p = structured.postings[0]
        record_key = f"tl:{host}:{key(p.title)}:{key(p.locations[0]) if p.locations else ''}"
    if not record_key:
        record_key = canonical_url(url)
    ev = tuple(Evidence(v.kind, v.evidence) for v in views)
    return Ok(ViewMap(record_key, tuple(views), guest), evidence=ev)


TOOL = ToolSpec(id="views", ct_id="CT-T-028", version="0.2.0", run=_run,
                needs=("structured", "verdict", "pagetext", "forms"),
                summary="alternate views of this page's record")
