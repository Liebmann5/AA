"""DetectorSampleSource — the saved block-detector disagreement pages (item 5a).

ApplicationsWorkflow saves a page to USER_DATA_DIR/detector_samples/ when its
quick block scan said "blocked" and its weighted check said "not blocked",
with a header comment naming the URL, context and capture time. Each saved
page is one item of the ``block-pages`` study.

Item ids are a digest of the file's bytes, so a label stays attached to its
page however the file is renamed or moved.

Viewing is made safe: the saved page is a stranger's HTML. prepare_view()
writes a copy with every script, frame, refresh and base tag removed and a
Content-Security-Policy that blocks all network loads, so opening it in a
browser contacts no site and runs no code. What remains is the page's text
and layout — enough to say what a person would have faced.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import urlsplit

from auto_apply.domain.models.annotation import Item

__all__ = ["DetectorSampleSource", "safe_view_html"]

_HEADER = re.compile(
    r"<!--\s*detector-sample\s*\|\s*url:\s*(?P<url>\S*)\s*"
    r"context:\s*(?P<context>[^|]*?)\s*\|.*?captured:\s*(?P<captured>\S+)",
    re.S,
)

_STRIP = (
    re.compile(r"<script\b.*?</script\s*>", re.I | re.S),
    re.compile(r"<script\b[^>]*/?>", re.I),
    re.compile(r"<noscript\b.*?</noscript\s*>", re.I | re.S),
    re.compile(r"<iframe\b.*?</iframe\s*>", re.I | re.S),
    re.compile(r"<iframe\b[^>]*/?>", re.I),
    re.compile(r"<(?:object|embed)\b.*?>", re.I | re.S),
    re.compile(r"<base\b[^>]*>", re.I),
    re.compile(r"<meta\b[^>]*http-equiv\s*=\s*[\"']?refresh[^>]*>", re.I),
    re.compile(r"\son[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.I),
)

_GUARD = (
    '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
    "img-src data:; style-src 'unsafe-inline'; font-src data:\">\n"
    '<div style="position:sticky;top:0;z-index:2147483647;background:#fff3cd;'
    'color:#000;font:14px sans-serif;padding:6px 10px;border-bottom:1px solid #000">'
    "AA saved copy &mdash; scripts and remote content are blocked. "
    "Judge what a person would have faced on this page.</div>\n"
)


def safe_view_html(raw: bytes) -> bytes:
    """A copy of saved HTML that runs no code and contacts no site."""
    text = raw.decode("utf-8", errors="replace")
    for pattern in _STRIP:
        text = pattern.sub("", text)
    return (_GUARD + text).encode("utf-8")


class DetectorSampleSource:
    """ItemSourcePort for the ``block-pages`` study."""

    study_id = "block-pages"

    def __init__(self, samples_dir: Path, view_dir: Path) -> None:
        self._samples_dir = samples_dir
        self._view_dir = view_dir
        self._files: dict[str, Path] = {}

    def items(self) -> list[Item]:
        if not self._samples_dir.is_dir():
            return []
        items: list[Item] = []
        for path in sorted(self._samples_dir.glob("*.html")):
            try:
                raw = path.read_bytes()
            except OSError:
                continue
            item_id = hashlib.sha256(raw).hexdigest()[:16]
            self._files[item_id] = path
            head = raw[:2048].decode("utf-8", errors="replace")
            match = _HEADER.search(head)
            url = match.group("url") if match else ""
            context = match.group("context").strip() if match else ""
            captured = match.group("captured") if match else ""
            host = urlsplit(url).hostname or "unknown site"
            items.append(
                Item(
                    study_id=self.study_id,
                    item_id=item_id,
                    title=f"{host} — saved {captured or path.stem}",
                    display=tuple(
                        (k, v)
                        for k, v in (
                            ("site", host),
                            ("saved", captured),
                            ("file", path.name),
                        )
                        if v
                    ),
                    aa_facts=(
                        ("quick_scan", "BLOCKED"),
                        ("weighted_check", "NOT BLOCKED"),
                        ("context", context),
                    ),
                    open_path=str(path),
                )
            )
        return items

    def prepare_view(self, item: Item) -> Path | None:
        path = self._files.get(item.item_id)
        if path is None:
            self.items()
            path = self._files.get(item.item_id)
        if path is None or not path.is_file():
            return None
        self._view_dir.mkdir(parents=True, exist_ok=True)
        view = self._view_dir / f"{item.item_id}.html"
        view.write_bytes(safe_view_html(path.read_bytes()))
        return view
