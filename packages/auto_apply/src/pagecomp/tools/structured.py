"""Structured data (CT-T-017): JSON-LD ``JobPosting`` objects.

Reads every ``<script type="application/ld+json">`` (in any scope: shadow
roots and frames included), tolerates ``@graph``, lists, nested ``@type``
lists and the trailing-comma / HTML-comment debris real pages carry, and
returns typed postings. Microdata (``itemtype=.../JobPosting``) is counted
as evidence only in v0.1.

Never raises: malformed blocks are counted and skipped.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from pagecomp.doc import TEXT
from pagecomp.registry import ToolSpec
from pagecomp.results import Evidence, Ok

_TRAILING_COMMA = re.compile(r",\s*([}\]])")


@dataclass(frozen=True)
class Posting:
    title: str
    organization: str
    locations: tuple[str, ...]
    date_posted: str
    valid_through: str
    employment_type: tuple[str, ...]
    remote: bool
    direct_apply: bool | None
    url: str
    identifier: str
    salary: str
    description: str = ""   # plain text, tags removed, at most DESCRIPTION_CHARS


@dataclass(frozen=True)
class Structured:
    postings: tuple[Posting, ...]
    blocks: int
    malformed: int
    microdata_postings: int


def _types(obj: Mapping[str, Any]) -> set[str]:
    t = obj.get("@type")
    if isinstance(t, str):
        return {t.split("/")[-1]}
    if isinstance(t, list):
        return {str(x).split("/")[-1] for x in t}
    return set()


def _walk(obj: Any, depth: int = 0) -> Iterator[Mapping[str, Any]]:
    if depth > 6:
        return
    if isinstance(obj, list):
        for x in obj[:200]:
            yield from _walk(x, depth + 1)
    elif isinstance(obj, dict):
        if "JobPosting" in _types(obj):
            yield obj
        for k in ("@graph", "mainEntity", "itemListElement", "item"):
            if k in obj:
                yield from _walk(obj[k], depth + 1)


def _s(v: Any) -> str:
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, dict):
        return _s(v.get("name") or v.get("@id") or v.get("value") or "")
    if isinstance(v, list) and v:
        return _s(v[0])
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return str(v)
    return ""


def _place(v: Any) -> list[str]:
    out: list[str] = []
    items = v if isinstance(v, list) else [v]
    for it in items[:50]:
        if isinstance(it, dict):
            addr = it.get("address", it)
            if isinstance(addr, dict):
                parts = [_s(addr.get(k)) for k in
                         ("addressLocality", "addressRegion", "addressCountry")]
                text = ", ".join(p for p in parts if p)
                if text:
                    out.append(text)
            elif isinstance(addr, str) and addr.strip():
                out.append(addr.strip())
        elif isinstance(it, str) and it.strip():
            out.append(it.strip())
    return out


def _salary(v: Any) -> str:
    if not isinstance(v, dict):
        return _s(v)
    cur = _s(v.get("currency"))
    val = v.get("value")
    if isinstance(val, dict):
        lo, hi = _s(val.get("minValue")), _s(val.get("maxValue"))
        unit = _s(val.get("unitText"))
        amount = f"{lo}-{hi}" if lo and hi else (lo or hi or _s(val.get("value")))
        return " ".join(x for x in (cur, amount, unit) if x)
    return " ".join(x for x in (cur, _s(val)) if x)


#: Characters of a posting's description kept (the same cap as a text node).
DESCRIPTION_CHARS = 20_000
_TAG = re.compile(r"<[^<>]{0,2000}>")
_WS = re.compile(r"\s+")


def _description(v: Any) -> str:
    """schema.org ``description`` is often HTML, sometimes HTML-escaped
    HTML (``&lt;p&gt;``): unescape, drop tags, unescape again, collapse.
    Bounded: at most 8x the kept length is ever processed."""
    if not isinstance(v, str):
        return ""
    t = html.unescape(v[: 8 * DESCRIPTION_CHARS])
    t = html.unescape(_TAG.sub(" ", t))
    return _WS.sub(" ", t).strip()[:DESCRIPTION_CHARS]


def posting_from(obj: Mapping[str, Any]) -> Posting:
    et = obj.get("employmentType")
    ets = tuple(str(x) for x in et) if isinstance(et, list) else ((str(et),) if et else ())
    da = obj.get("directApply")
    return Posting(
        title=_s(obj.get("title") or obj.get("name")),
        organization=_s(obj.get("hiringOrganization")),
        locations=tuple(_place(obj.get("jobLocation"))),
        date_posted=_s(obj.get("datePosted")),
        valid_through=_s(obj.get("validThrough")),
        employment_type=ets,
        remote=_s(obj.get("jobLocationType")).upper() == "TELECOMMUTE",
        direct_apply=da if isinstance(da, bool) else None,
        url=_s(obj.get("url")),
        identifier=_s(obj.get("identifier")),
        salary=_salary(obj.get("baseSalary")),
        description=_description(obj.get("description")),
    )


def parse_block(raw: str) -> Any:
    raw = raw.strip()
    if raw.startswith("<!--"):
        raw = raw[4:]
    if raw.endswith("-->"):
        raw = raw[:-3]
    try:
        return json.loads(raw)
    except ValueError:
        return json.loads(_TRAILING_COMMA.sub(r"\1", raw))


def _run(q: Any, params: Mapping[str, Any]) -> Ok[Structured]:
    doc = q.doc
    postings: list[Posting] = []
    blocks = malformed = 0
    for i in doc.elements("script"):
        if (doc.attr(i, "type") or "").strip().lower() != "application/ld+json":
            continue
        blocks += 1
        raw = "".join(doc.own_text(j) for j in doc.children(i) if doc.kind[j] == TEXT)
        q.tick(len(raw) // 64 + 1)
        try:
            data = parse_block(raw)
        except ValueError:
            malformed += 1
            continue
        for obj in _walk(data):
            postings.append(posting_from(obj))
    micro = sum(1 for i in doc.elements()
                if (doc.attr(i, "itemtype") or "").rstrip("/").endswith("JobPosting"))
    ev: list[Evidence] = []
    if malformed:
        ev.append(Evidence("malformed-json-ld", f"{malformed} of {blocks} blocks"))
    if micro:
        ev.append(Evidence("microdata-jobposting", f"{micro} itemscopes (not parsed in v0.1)"))
    return Ok(Structured(tuple(postings), blocks, malformed, micro), evidence=tuple(ev))


TOOL = ToolSpec(id="structured", ct_id="CT-T-017", version="0.2.0", run=_run,
                summary="JSON-LD JobPosting")
