"""Non-HTML source channels (05 s9 Source Channel seam; S9): RSS, Atom, sitemaps.

Pure parsers over text the caller fetched (the library never fetches).
Hardened for hostile input:

* a size cap (``max_bytes``) before parsing;
* any ``<!DOCTYPE`` or ``<!ENTITY`` declaration is refused, which closes
  entity-expansion ("billion laughs") and external-entity attacks without a
  third-party parser;
* item caps; malformed input returns an empty, flagged result, never raises.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

_DECL = re.compile(r"<!\s*(DOCTYPE|ENTITY)", re.I)


@dataclass(frozen=True)
class FeedItem:
    title: str
    link: str
    published: str
    updated: str
    guid: str
    summary: str


@dataclass(frozen=True)
class ChannelResult:
    kind: str                     # rss | atom | sitemap | sitemapindex | unknown
    items: tuple[FeedItem, ...]
    flags: tuple[str, ...]        # refused-declaration | too-large | malformed | items-cut


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _text(el: ET.Element | None, cap: int = 2000) -> str:
    if el is None:
        return ""
    return " ".join("".join(el.itertext()).split())[:cap]


def _child(el: ET.Element, name: str) -> ET.Element | None:
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


def parse_channel(text: str, *, max_bytes: int = 5_000_000, max_items: int = 5000) -> ChannelResult:
    if len(text) > max_bytes:
        return ChannelResult("unknown", (), ("too-large",))
    if _DECL.search(text[:65536]) or _DECL.search(text):
        return ChannelResult("unknown", (), ("refused-declaration",))
    try:
        root = ET.fromstring(text.strip())
    except ET.ParseError:
        return ChannelResult("unknown", (), ("malformed",))
    kind = _local(root.tag)
    items: list[FeedItem] = []
    flags: list[str] = []
    if kind == "rss" or kind == "rdf":
        chan = _child(root, "channel")
        source = list(chan if chan is not None else root)
        source += [e for e in root if _local(e.tag) == "item"]   # RSS 1.0 items are siblings
        for it in source:
            if _local(it.tag) != "item":
                continue
            items.append(FeedItem(_text(_child(it, "title")), _text(_child(it, "link")),
                                  _text(_child(it, "pubdate")) or _text(_child(it, "date")), "",
                                  _text(_child(it, "guid")), _text(_child(it, "description"))))
        kind = "rss"
    elif kind == "feed":
        for it in root:
            if _local(it.tag) != "entry":
                continue
            link = ""
            for c in it:
                if _local(c.tag) == "link" and c.get("rel", "alternate") == "alternate":
                    link = c.get("href", "")
                    break
            items.append(FeedItem(_text(_child(it, "title")), link, _text(_child(it, "published")),
                                  _text(_child(it, "updated")), _text(_child(it, "id")),
                                  _text(_child(it, "summary")) or _text(_child(it, "content"))))
        kind = "atom"
    elif kind in ("urlset", "sitemapindex"):
        tag = "url" if kind == "urlset" else "sitemap"
        for it in root:
            if _local(it.tag) != tag:
                continue
            items.append(FeedItem("", _text(_child(it, "loc")), "", _text(_child(it, "lastmod")), "", ""))
        kind = "sitemap" if kind == "urlset" else "sitemapindex"
    else:
        return ChannelResult("unknown", (), ("malformed",))
    if len(items) > max_items:
        items = items[:max_items]
        flags.append("items-cut")
    return ChannelResult(kind, tuple(items), tuple(flags))


def robots_sitemaps(robots_txt: str) -> tuple[str, ...]:
    """``Sitemap:`` lines of a robots.txt the caller already fetched for policy."""
    out = []
    for line in robots_txt.splitlines()[:5000]:
        k, _, v = line.partition(":")
        if k.strip().lower() == "sitemap" and v.strip():
            out.append(v.strip())
    return tuple(out)
