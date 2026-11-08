"""Replay adapter (CT-T-022): observations from stored captures.

Reads a capture folder layout (``<root>/<kind>/
<stamp_host>/``): ``meta.json`` plus ``dom_pierced.json.gz`` (preferred:
shadow roots and frames) or ``page.html.gz``. The capture's own page
verdict (AA's, at capture time) is returned alongside for comparison, never
used as an input.
"""

from __future__ import annotations

import gzip
import json
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pagecomp.doc import DocLimits
from pagecomp.observation import PageObservation, observe_cdp, observe_html


@dataclass(frozen=True)
class Capture:
    path: Path
    kind: str
    meta: dict[str, Any]
    observation: PageObservation
    source: str  # "cdp-dom" | "html"


def _query_from_url(url: str) -> str | None:
    try:
        qs = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    except ValueError:
        return None
    for k in ("q", "query", "keywords", "search", "p", "k"):
        if qs.get(k):
            return qs[k][0]
    return None


def load(path: str | Path, *, prefer_dom: bool = True, limits: DocLimits | None = None) -> Capture:
    p = Path(path)
    meta = json.loads((p / "meta.json").read_text(encoding="utf-8"))
    url = meta.get("url", "")
    title = meta.get("title", "")
    env = {"environment": meta.get("environment", ""), "browser": meta.get("browser_version", ""),
           "viewport": tuple(meta.get("viewport") or ())}
    dom_file = p / "dom_pierced.json.gz"
    query = _query_from_url(url)
    if prefer_dom and dom_file.exists():
        with gzip.open(dom_file, "rt", encoding="utf-8") as fh:
            dom = json.load(fh)
        obs = observe_cdp(dom, url=url, title=title, limits=limits, environment=env, query=query)
        source = "cdp-dom"
    else:
        with gzip.open(p / "page.html.gz", "rt", encoding="utf-8", errors="replace") as fh:
            html = fh.read()
        obs = observe_html(html, url=url, title=title, limits=limits, environment=env, query=query)
        source = "html"
    return Capture(p, p.parent.name, meta, obs, source)


def iter_captures(root: str | Path) -> list[Path]:
    return sorted(d for d in Path(root).glob("*/*") if (d / "meta.json").exists())
