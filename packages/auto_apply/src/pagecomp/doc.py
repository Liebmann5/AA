"""Columnar document (CT-T-004, CT-DS-002).

One immutable struct-of-arrays tree for every way a page can be read:
serialized HTML (``from_html``), the protocol's pierced DOM
(``from_cdp``: open and closed shadow roots, same-process iframes), or a
stored capture (``pagecomp.capture``). Tools see only this.

Layout. Nodes are stored in **pre-order**, so the subtree of node ``i`` is
the contiguous index range ``[i, end[i])``. That gives O(1) ancestor tests
(``a < b < end[a]``), O(1) subtree size, and disjointness of two subtrees by
two comparisons, which the record tools lean on.

Node kinds: ``ELEMENT``, ``TEXT``, ``SHADOW`` (a shadow root, child of its
host, ``mode`` attribute ``open``/``closed``), ``FRAME`` (an iframe's
document, child of the iframe element, ``url`` attribute), ``ROOT`` (index 0).
``scope[i]`` is the nearest ``ROOT``/``SHADOW``/``FRAME`` ancestor-or-self:
element ids, ``label[for]`` and ``aria-labelledby`` resolve inside one scope,
as they do in a browser.

Caps (05 section 14) are enforced here, never in engines, and every cap that
fires is recorded in ``truncations`` so a truncated page can be told apart
from a small one: node cap ``N``, depth cap, frame depth, inline-script
bytes, per-text-node characters.

Memory. Per node: 9 ``array('i')``/``array('B')`` slots ≈ 33 bytes, plus
interned strings and attributes. Measured figures are in
``tests/test_doc_memory.py`` (CT-NFR-005 target: ≤ 100 B/node Python side).
"""

from __future__ import annotations

import hashlib
import urllib.parse
from array import array
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

from pagecomp.text import collapse

ELEMENT, TEXT, SHADOW, FRAME, ROOT = 0, 1, 2, 3, 4
KIND_NAMES = {ELEMENT: "element", TEXT: "text", SHADOW: "shadow", FRAME: "frame", ROOT: "root"}

VOID = frozenset(
    "area base br col embed hr img input link meta param source track wbr".split()
)
#: Elements whose text is not page text.
NON_TEXT = frozenset({"script", "style", "template", "noscript", "head", "title"})
#: Elements whose boundaries do not separate words.
INLINE = frozenset(
    "a abbr b bdi bdo cite code data dfn em i kbd label mark q s samp small span "
    "strong sub sup time u var font nobr".split()
)

_P_CLOSERS = frozenset(
    "address article aside blockquote details dialog div dl fieldset figcaption figure "
    "footer form h1 h2 h3 h4 h5 h6 header hgroup hr main menu nav ol p pre section "
    "table ul".split()
)
_P_SCOPE = frozenset({"button", "table", "td", "th", "caption", "html", "template", "object"})


@dataclass(frozen=True)
class Truncation:
    kind: str     # "nodes" | "depth" | "frame-depth" | "script-bytes" | "text"
    limit: int
    count: int    # how many times or how much it cut


#: Frame read states. Anything but ``read`` means the frame's content is
#: absent from the ``Doc`` and the reason is recorded, never silent.
FRAME_READ = "read"
FRAME_CROSS_ORIGIN_UNREAD = "cross-origin-unread"
FRAME_DETACHED = "detached"
FRAME_NAVIGATED = "navigated-during-read"
FRAME_CAP = "frame-cap"
FRAME_DEPTH_CAP = "frame-depth-cap"
FRAME_TIMEOUT = "timeout"
FRAME_EMPTY = "not-loaded"   # lazy frame not yet loaded, or no document
FRAME_STATES = frozenset({FRAME_READ, FRAME_CROSS_ORIGIN_UNREAD, FRAME_DETACHED,
                          FRAME_NAVIGATED, FRAME_CAP, FRAME_DEPTH_CAP, FRAME_TIMEOUT,
                          FRAME_EMPTY})


def origin_of(url: str) -> str:
    """RFC 6454 serialised origin, or ``"null"`` for opaque ones."""
    try:
        parts = urllib.parse.urlsplit(url or "")
    except ValueError:
        return "null"
    if parts.scheme in ("http", "https", "ws", "wss", "ftp") and parts.hostname:
        default = {"http": 80, "https": 443, "ws": 80, "wss": 443, "ftp": 21}[parts.scheme]
        try:
            port = parts.port
        except ValueError:
            return "null"
        host = parts.hostname
        return f"{parts.scheme}://{host}" + (f":{port}" if port and port != default else "")
    return "null"


@dataclass(frozen=True)
class FrameInfo:
    """One ``<iframe>``/``<frame>`` element and what became of its document."""

    element: int        # node index of the iframe element
    document: int       # node index of the FRAME node, -1 when not read
    url: str
    origin: str
    same_origin: bool   # with the top document (srcdoc/about:blank inherit; sandbox → opaque)
    sandboxed: bool
    state: str          # one of FRAME_STATES
    frame_id: str = ""


class Layout:
    """Per-node geometry and computed visibility from ``DOMSnapshot``.

    Arrays are indexed by ``Doc`` node index. ``has_box`` is 0 for a node
    with no layout object (``display:none``, not rendered, or ``display:
    contents`` wrappers, whose children still have boxes).
    """

    __slots__ = ("x", "y", "w", "h", "paint", "has_box", "style", "viewport")
    DISPLAY_NONE, VIS_HIDDEN, OPACITY_ZERO, CONTENTS = 1, 2, 4, 8

    def __init__(self, n: int, viewport: tuple[float, float] = (0.0, 0.0)) -> None:
        self.x = array("f", bytes(4 * n))
        self.y = array("f", bytes(4 * n))
        self.w = array("f", bytes(4 * n))
        self.h = array("f", bytes(4 * n))
        self.paint = array("i", bytes(4 * n))
        self.has_box = array("B", bytes(n))
        self.style = array("B", bytes(n))
        self.viewport = viewport

    def digest(self) -> str:
        h = hashlib.sha256()
        for flags in (self.has_box, self.style):
            h.update(flags.tobytes())
        # Rounded to whole pixels: sub-pixel jitter is not a content change.
        for coords in (self.x, self.y, self.w, self.h):
            h.update(array("i", (int(v) for v in coords)).tobytes())
        return h.hexdigest()


@dataclass(frozen=True)
class DocLimits:
    max_nodes: int = 30_000
    max_depth: int = 256
    max_frame_depth: int = 3
    max_script_chars: int = 65_536        # per inline script kept
    max_script_total: int = 2_000_000     # all inline scripts kept
    max_text_chars: int = 20_000          # per text node
    max_bytes: int = 8_000_000            # characters of text and attribute values
    max_attr_chars: int = 65_536          # per attribute value (a data: URI style is not page data)
    max_attrs: int = 256                  # attributes kept per element
    max_input_chars: int = 8_000_000      # serialized HTML read (the largest real capture is 2.5 M)


class _Builder:
    """Append-only pre-order builder shared by both parsers."""

    def __init__(self, limits: DocLimits) -> None:
        self.limits = limits
        self.kind = array("B")
        self.tag = array("i")
        self.parent = array("i")
        self.depth = array("i")
        self.attr_start = array("i")
        self.attr_len = array("i")
        self.text = array("i")
        self.attr_name = array("i")
        self.attr_value = array("i")
        self.strings: list[str] = []
        self._intern: dict[str, int] = {}
        self.truncated: dict[str, list[int]] = {}
        self.full = False
        self.dropped = 0        # elements read but not kept (past the depth cap)
        self.script_total = 0
        self.bytes = 0
        self.frames: list[FrameInfo] = []
        self.slots: dict[int, int] = {}
        self.layout: Layout | None = None

    def s(self, value: str) -> int:
        idx = self._intern.get(value)
        if idx is None:
            idx = len(self.strings)
            self._intern[value] = idx
            self.strings.append(value)
        return idx

    def cut(self, kind: str, limit: int, amount: int = 1) -> None:
        entry = self.truncated.setdefault(kind, [limit, 0])
        entry[1] += amount

    def add(
        self,
        kind: int,
        parent: int,
        depth: int,
        tag: str = "",
        attrs: list[tuple[str, str]] | None = None,
        text: str | None = None,
        text_cap: int | None = None,
    ) -> int:
        if len(self.kind) >= self.limits.max_nodes:
            if not self.full:
                self.full = True
            self.cut("nodes", self.limits.max_nodes)
            return -1
        cap_a = self.limits.max_attr_chars
        if attrs is not None and len(attrs) > self.limits.max_attrs:
            self.cut("attrs", self.limits.max_attrs, len(attrs) - self.limits.max_attrs)
            attrs = attrs[: self.limits.max_attrs]
        # Every attribute costs at least one unit, so empty names are not free.
        cost = len(tag) + sum(max(1, len(k) + min(len(v or ""), cap_a)) for k, v in (attrs or ())) \
            + (len(text) if text is not None else 0)
        if self.bytes + cost > self.limits.max_bytes:
            self.full = True
            self.cut("bytes", self.limits.max_bytes)
            return -1
        self.bytes += cost
        idx = len(self.kind)
        self.kind.append(kind)
        self.tag.append(self.s(tag) if tag else -1)
        self.parent.append(parent)
        self.depth.append(depth)
        self.attr_start.append(len(self.attr_name))
        n = 0
        for name, value in attrs or ():
            v = value if value is not None else ""
            if len(v) > self.limits.max_attr_chars:
                self.cut("attr-chars", self.limits.max_attr_chars)
                v = v[: self.limits.max_attr_chars]
            self.attr_name.append(self.s(name))
            self.attr_value.append(self.s(v))
            n += 1
        self.attr_len.append(n)
        if text is not None:
            # Script and style text is capped by the caller at
            # max_script_chars; every other text node at max_text_chars.
            cap = self.limits.max_text_chars if text_cap is None else text_cap
            if len(text) > cap:
                self.cut("text", cap)
                text = text[:cap]
            self.text.append(self.s(text))
        else:
            self.text.append(-1)
        return idx

    def finish(self, source: str, url: str) -> "Doc":
        n = len(self.kind)
        end = array("i", range(1, n + 1))
        # Pre-order: walk backwards, extend each parent's end over its child.
        for i in range(n - 1, 0, -1):
            p = self.parent[i]
            if p >= 0 and end[i] > end[p]:
                end[p] = end[i]
        scope = array("i", [0]) * n
        for i in range(n):
            k = self.kind[i]
            if k in (ROOT, SHADOW, FRAME):
                scope[i] = i
            else:
                p = self.parent[i]
                scope[i] = scope[p] if p >= 0 else 0
        truncs = tuple(
            Truncation(kind, limit, count) for kind, (limit, count) in sorted(self.truncated.items())
        )
        return Doc(
            kind=self.kind, tag=self.tag, parent=self.parent, depth=self.depth,
            end=end, scope=scope, attr_start=self.attr_start, attr_len=self.attr_len,
            attr_name=self.attr_name, attr_value=self.attr_value, text=self.text,
            strings=tuple(self.strings), truncations=truncs, source=source, url=url,
            frames=tuple(self.frames), slots=dict(self.slots), layout=self.layout,
        )


class Doc:
    """The immutable columnar tree. Use ``view(i)`` for readable access."""

    __slots__ = (
        "kind", "tag", "parent", "depth", "end", "scope", "attr_start", "attr_len",
        "attr_name", "attr_value", "text", "strings", "truncations", "source", "url",
        "frames", "slots", "layout", "_hash", "_ids", "_tag_ids", "_children", "_names",
    )

    _OPTIONAL: Mapping[str, Any] = {"frames": (), "slots": {}, "layout": None}

    # Declared for type checkers; values are set in ``__init__`` (``__slots__``).
    kind: array
    tag: array
    parent: array
    depth: array
    end: array
    scope: array
    attr_start: array
    attr_len: array
    attr_name: array
    attr_value: array
    text: array
    strings: tuple[str, ...]
    truncations: tuple[Truncation, ...]
    source: str
    url: str
    frames: tuple[FrameInfo, ...]
    slots: dict[int, int]
    layout: Layout | None
    _hash: str
    _ids: dict[tuple[int, str], int] | None
    _tag_ids: Mapping[str, tuple[int, ...]] | None
    _children: Any
    _names: dict[tuple[int, int], str]

    def __init__(self, **kw: Any) -> None:
        for name in self.__slots__:
            if not name.startswith("_"):
                if name in self._OPTIONAL and name not in kw:
                    object.__setattr__(self, name, self._OPTIONAL[name])
                else:
                    object.__setattr__(self, name, kw[name])
        object.__setattr__(self, "_hash", "")
        object.__setattr__(self, "_ids", None)
        object.__setattr__(self, "_tag_ids", None)
        object.__setattr__(self, "_children", None)
        object.__setattr__(self, "_names", {})

    def __setattr__(self, name: str, value: Any) -> None:  # immutability
        raise AttributeError("Doc is immutable")

    def __len__(self) -> int:
        return len(self.kind)

    # -- identity -------------------------------------------------------
    @property
    def structure_hash(self) -> str:
        """Hash of the tree alone: layout excluded (settle, diff)."""
        h = hashlib.sha256()
        for arr in (self.kind, self.tag, self.parent, self.attr_name,
                    self.attr_value, self.text):
            h.update(arr.tobytes())
        for s in self.strings:
            h.update(s.encode("utf-8", "surrogatepass"))
            h.update(b"\x00")
        return h.hexdigest()

    @property
    def content_hash(self) -> str:
        """Tree plus layout digest: a layout reading never shares a cache
        entry with a markup-only reading of the same tree (visibility differs)."""
        if not self._hash:
            h = hashlib.sha256()
            if self.layout is not None:
                h.update(b"layout:" + self.layout.digest().encode())
            for arr in (self.kind, self.tag, self.parent, self.attr_name,
                        self.attr_value, self.text):
                h.update(arr.tobytes())
            for s in self.strings:
                h.update(s.encode("utf-8", "surrogatepass"))
                h.update(b"\x00")
            object.__setattr__(self, "_hash", h.hexdigest())
        return self._hash

    # -- node facts -----------------------------------------------------
    def tag_name(self, i: int) -> str:
        t = self.tag[i]
        return self.strings[t] if t >= 0 else ""

    def is_element(self, i: int) -> bool:
        return self.kind[i] == ELEMENT

    def own_text(self, i: int) -> str:
        t = self.text[i]
        return self.strings[t] if t >= 0 else ""

    def attrs(self, i: int) -> dict[str, str]:
        s, n = self.attr_start[i], self.attr_len[i]
        out: dict[str, str] = {}
        for j in range(s, s + n):
            out.setdefault(self.strings[self.attr_name[j]], self.strings[self.attr_value[j]])
        return out

    def attr(self, i: int, name: str, default: str | None = None) -> str | None:
        s, n = self.attr_start[i], self.attr_len[i]
        for j in range(s, s + n):
            if self.strings[self.attr_name[j]] == name:
                return self.strings[self.attr_value[j]]
        return default

    def has_attr(self, i: int, name: str) -> bool:
        return self.attr(i, name) is not None

    # -- structure ------------------------------------------------------
    def children(self, i: int) -> Iterator[int]:
        """Direct children in document order (O(size of subtree) skip-walk)."""
        j, stop = i + 1, self.end[i]
        while j < stop:
            yield j
            j = self.end[j]

    def element_children(self, i: int) -> list[int]:
        return [j for j in self.children(i) if self.kind[j] == ELEMENT]

    def is_ancestor(self, a: int, b: int) -> bool:
        """True when ``a`` is a proper ancestor of ``b``."""
        return a < b < self.end[a]

    def ancestors(self, i: int, limit: int = 10_000) -> Iterator[int]:
        p = self.parent[i]
        while p >= 0 and limit > 0:
            yield p
            p = self.parent[p]
            limit -= 1

    def subtree(self, i: int) -> range:
        return range(i, self.end[i])

    def size(self, i: int) -> int:
        return self.end[i] - i

    def lift(self, i: int, levels: int) -> int:
        """The ancestor ``levels`` up, or -1 past the root."""
        for _ in range(levels):
            i = self.parent[i]
            if i < 0:
                return -1
        return i

    def elements(self, tag: str | None = None) -> Iterator[int]:
        if tag is None:
            return (i for i in range(len(self.kind)) if self.kind[i] == ELEMENT)
        return iter(self._tag_index().get(tag, ()))

    def _tag_index(self) -> Mapping[str, tuple[int, ...]]:
        if self._tag_ids is None:
            idx: dict[str, list[int]] = {}
            for i in range(len(self.kind)):
                if self.kind[i] == ELEMENT:
                    idx.setdefault(self.strings[self.tag[i]], []).append(i)
            object.__setattr__(self, "_tag_ids", {k: tuple(v) for k, v in idx.items()})
        return self._tag_ids  # type: ignore[return-value]

    def by_id(self, scope: int, element_id: str) -> int:
        """First element with this id in tree order inside ``scope``, or -1."""
        if self._ids is None:
            ids: dict[tuple[int, str], int] = {}
            for i in range(len(self.kind)):
                if self.kind[i] == ELEMENT:
                    v = self.attr(i, "id")
                    if v:
                        ids.setdefault((self.scope[i], v), i)
            object.__setattr__(self, "_ids", ids)
        return self._ids.get((scope, element_id), -1)  # type: ignore[union-attr]

    def in_inert(self, i: int) -> bool:
        """Inside ``<template>`` content or a ``NON_TEXT`` container."""
        for a in self.ancestors(i, 128):
            if self.kind[a] == ELEMENT and self.strings[self.tag[a]] in ("template", "script", "style", "noscript"):
                return True
        return False

    # -- text -----------------------------------------------------------
    def text_content(self, i: int, cap: int = 256, visual: bool = False) -> tuple[str, bool]:
        """Full-subtree text (defect 4 rule), word-separated at block edges.

        Returns ``(text, truncated)``. Skips ``NON_TEXT`` and ``hidden``
        subtrees. ``aria-hidden="true"`` subtrees are skipped for names
        (``visual=False``) and kept for what a person sees (``visual=True``):
        MUI renders the required asterisk as ``<span aria-hidden> *</span>``.
        """
        parts: list[str] = []
        total = 0
        closes: list[int] = []      # ends of open block elements: a word break on leaving
        j, stop = i, self.end[i]
        while j < stop:
            while closes and j >= closes[-1]:
                closes.pop()
                parts.append(" ")
            k = self.kind[j]
            if k == TEXT:
                t = self.strings[self.text[j]]
                parts.append(t)
                total += len(t)
                if total > cap * 4:
                    break
                j += 1
                continue
            if k == ELEMENT:
                name = self.strings[self.tag[j]]
                if j != i and (
                    name in NON_TEXT
                    or self.has_attr(j, "hidden")
                    or (not visual and self.attr(j, "aria-hidden") == "true")
                ):
                    j = self.end[j]
                    continue
                if name not in INLINE:
                    parts.append(" ")
                    closes.append(self.end[j])
                if name == "img":
                    alt = self.attr(j, "alt")
                    if alt:
                        parts.append(f" {alt} ")
            j += 1
        text = collapse("".join(parts))
        if len(text) > cap:
            return text[:cap], True
        return text, False

    def idref_text(self, i: int, attr: str, cap: int = 256) -> str:
        """Text of the elements named by an IDREF list attribute, in scope."""
        value = self.attr(i, attr)
        if not value:
            return ""
        out = []
        for ref in value.split():
            j = self.by_id(self.scope[i], ref)
            if j >= 0:
                own = self.attr(j, "aria-label")
                out.append(own if own else self.text_content(j, cap)[0])
        return collapse(" ".join(out))[:cap]

    def accessible_name(self, i: int, cap: int = 256) -> str:
        """Memoised per node: the Doc is immutable, and several tools ask for
        the same names (bounded by the node count)."""
        k = (i, cap)
        got = self._names.get(k)
        if got is None:
            got = self._accessible_name(i, cap)
            self._names[k] = got
        return got

    def _accessible_name(self, i: int, cap: int = 256) -> str:
        """A bounded Accessible Name Computation (steps 2B, 2C, 2D, 2F, 2I).

        Not the full algorithm: ``label`` association for controls is the
        pairing tool's job (CT-T-011), so this returns the element's own
        name sources only.
        """
        name = self.idref_text(i, "aria-labelledby", cap)
        if name:
            return name
        label = self.attr(i, "aria-label")
        if label and label.strip():
            return collapse(label)[:cap]
        tag = self.tag_name(i)
        if tag == "img":
            return collapse(self.attr(i, "alt") or "")[:cap]
        if tag in ("input", "select", "textarea"):
            return ""
        text = self.text_content(i, cap)[0]
        if text:
            return text
        return collapse(self.attr(i, "title") or "")[:cap]

    def view(self, i: int) -> "NodeView":
        return NodeView(self, i)


@dataclass(frozen=True)
class NodeView:
    """Readable access at the edges; hot loops use indexes (05 section 3)."""

    doc: Doc
    i: int

    @property
    def tag(self) -> str:
        return self.doc.tag_name(self.i)

    @property
    def kind(self) -> str:
        return KIND_NAMES[self.doc.kind[self.i]]

    @property
    def attrs(self) -> dict[str, str]:
        return self.doc.attrs(self.i)

    def attr(self, name: str, default: str | None = None) -> str | None:
        return self.doc.attr(self.i, name, default)

    @property
    def text(self) -> str:
        return self.doc.text_content(self.i)[0]

    @property
    def parent(self) -> "NodeView | None":
        p = self.doc.parent[self.i]
        return NodeView(self.doc, p) if p >= 0 else None

    def children(self) -> list["NodeView"]:
        return [NodeView(self.doc, j) for j in self.doc.children(self.i)]

    def __repr__(self) -> str:
        return f"<{self.kind} {self.tag or ''}#{self.i}>"


# ---------------------------------------------------------------------------
# From serialized HTML
# ---------------------------------------------------------------------------


_TEMPLATE_CLOSERS = frozenset({"#shadow-root", "template"})


class _OpenStack:
    """The parser's stack of open elements, with a count of open tag names.

    Implied closes ("a <div> closes an open <p>") and stray end tags would
    otherwise scan the whole stack on every tag: O(nodes x depth). The
    counts answer "is any such element open?" in O(1); the scan only runs
    when one is. The list is private and only ``append``, ``pop`` and
    ``truncate`` change it, so the counts cannot drift from it.
    """

    __slots__ = ("_items", "open")

    def __init__(self, first: tuple[int, str]) -> None:
        self._items: list[tuple[int, str]] = [first]
        self.open: dict[str, int] = {first[1]: 1}

    def __len__(self) -> int:
        return len(self._items)

    def __getitem__(self, pos: int) -> tuple[int, str]:
        return self._items[pos]

    def names(self) -> list[str]:
        return [name for _, name in self._items]

    def append(self, item: tuple[int, str]) -> None:
        self._items.append(item)
        self.open[item[1]] = self.open.get(item[1], 0) + 1

    def pop(self) -> tuple[int, str]:
        item = self._items.pop()
        self.open[item[1]] -= 1
        return item

    def truncate(self, pos: int) -> None:
        for _, name in self._items[pos:]:
            self.open[name] -= 1
        del self._items[pos:]

    def any_open(self, names: Iterable[str]) -> bool:
        return any(self.open.get(n, 0) > 0 for n in names)


class _HTMLTree(HTMLParser):
    def __init__(self, b: _Builder, root: int, depth0: int, frame_depth: int) -> None:
        super().__init__(convert_charrefs=True)
        self.b = b
        # stack entries: (node index, tag name, kind)
        self.stack = _OpenStack((root, "#root"))
        self.depth0 = depth0
        self.frame_depth = frame_depth
        self.overflow: dict[str, int] = {}
        self.pending_text: list[str] = []
        self.in_script: str | None = None

    # -- helpers --------------------------------------------------------
    def _flush(self) -> None:
        if not self.pending_text:
            return
        raw = "".join(self.pending_text)
        self.pending_text = []
        if self.b.full:
            return
        parent, ptag = self.stack[-1]
        if ptag in ("script", "style"):
            keep = raw
            lim = self.b.limits
            if len(keep) > lim.max_script_chars:
                self.b.cut("script-bytes", lim.max_script_chars, len(keep) - lim.max_script_chars)
                keep = keep[: lim.max_script_chars]
            if self.b.script_total + len(keep) > lim.max_script_total:
                self.b.cut("script-bytes", lim.max_script_total, len(keep))
                return
            self.b.script_total += len(keep)
            self.b.add(TEXT, parent, self._depth(), text=keep, text_cap=lim.max_script_chars)
            return
        raw = _precut(self.b, raw)
        if not raw.strip():
            # Whitespace still separates words between inline elements.
            self.b.add(TEXT, parent, self._depth(), text=" ")
            return
        self.b.add(TEXT, parent, self._depth(), text=_squash(raw))

    def _depth(self) -> int:
        return self.depth0 + len(self.stack) - 1

    def _close_to(self, names: frozenset[str] | set[str], barrier: frozenset[str]) -> None:
        if not self.stack.any_open(names):
            return
        for pos in range(len(self.stack) - 1, 0, -1):
            tag = self.stack[pos][1]
            if tag in names:
                self.stack.truncate(pos)
                return
            if tag in barrier or tag == "#shadow-root":
                return

    def _implied_closes(self, tag: str) -> None:
        if tag in _P_CLOSERS:
            self._close_to(frozenset({"p"}), _P_SCOPE)
        if tag == "li":
            self._close_to(frozenset({"li"}), frozenset({"ul", "ol", "menu"}) | _P_SCOPE)
        elif tag in ("dt", "dd"):
            self._close_to(frozenset({"dt", "dd"}), frozenset({"dl"}) | _P_SCOPE)
        elif tag == "option":
            self._close_to(frozenset({"option"}), frozenset({"select", "datalist", "optgroup"}))
        elif tag == "optgroup":
            self._close_to(frozenset({"option", "optgroup"}), frozenset({"select"}))
        elif tag == "tr":
            self._close_to(frozenset({"tr"}), frozenset({"table", "tbody", "thead", "tfoot"}))
        elif tag in ("td", "th"):
            self._close_to(frozenset({"td", "th"}), frozenset({"tr", "table"}))
        elif tag in ("thead", "tbody", "tfoot"):
            self._close_to(frozenset({"thead", "tbody", "tfoot"}), frozenset({"table"}))

    # -- parser callbacks -----------------------------------------------
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._flush()
        if self.b.full:
            raise _Full
        tag = tag.lower()
        cap = self.b.limits.max_attrs
        pairs = [(k, v or "") for k, v in attrs[:cap]]
        if len(attrs) > cap:
            self.b.cut("attrs", cap, len(attrs) - cap)
        self._implied_closes(tag)
        parent = self.stack[-1][0]
        depth = self._depth()
        if depth >= self.b.limits.max_depth and tag not in VOID:
            # Before the shadow-root case too: a declarative shadow root is a
            # level like any other (it used to land one level past the cap).
            self.b.cut("depth", self.b.limits.max_depth)
            self.overflow[tag] = self.overflow.get(tag, 0) + 1
            # Dropped elements cost parsing time too: they count against the
            # node cap, so a page of endless nesting stops like a huge one.
            self.b.dropped += 1
            if len(self.b.kind) + self.b.dropped >= self.b.limits.max_nodes:
                self.b.full = True
                self.b.cut("nodes", self.b.limits.max_nodes)
            return
        if tag == "template":
            mode = next((v for k, v in pairs if k in ("shadowrootmode", "shadowroot")), None)
            if mode and self.stack[-1][1] not in ("#root", "#shadow-root"):
                idx = self.b.add(SHADOW, parent, depth, tag="#shadow-root",
                                 attrs=[("mode", mode.lower())])
                if idx >= 0:
                    self.stack.append((idx, "#shadow-root"))
                return
        idx = self.b.add(ELEMENT, parent, depth, tag=tag, attrs=pairs)
        if idx < 0:
            return
        if tag == "iframe":
            srcdoc = next((v for k, v in pairs if k == "srcdoc"), None)
            if srcdoc:
                self._frame(idx, srcdoc, depth + 1)
        if tag not in VOID:
            self.stack.append((idx, tag))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # XHTML-style <div/>: HTML ignores the slash on non-void elements,
        # but treating it as empty is the safer reading of generated markup.
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID and len(self.stack) > 1 and self.stack[-1][1] == tag.lower():
            self.stack.pop()

    def _frame(self, iframe: int, html: str, depth: int) -> None:
        if self.frame_depth + 1 > self.b.limits.max_frame_depth:
            self.b.cut("frame-depth", self.b.limits.max_frame_depth)
            return
        froot = self.b.add(FRAME, iframe, depth, tag="#document", attrs=[("url", "about:srcdoc")])
        if froot < 0:
            return
        sub = _HTMLTree(self.b, froot, depth + 1, self.frame_depth + 1)
        _feed_bounded(sub, self.b, html)
        sub._flush()

    def handle_endtag(self, tag: str) -> None:
        self._flush()
        if self.b.full:
            raise _Full
        tag = tag.lower()
        if self.overflow.get(tag):
            self.overflow[tag] -= 1
            return
        if tag == "template":
            if not self.stack.any_open(_TEMPLATE_CLOSERS):
                return
            for pos in range(len(self.stack) - 1, 0, -1):
                if self.stack[pos][1] in _TEMPLATE_CLOSERS:
                    self.stack.truncate(pos)
                    return
                if self.stack[pos][1] == "#shadow-root":
                    return
            return
        if not self.stack.any_open((tag,)):
            return  # a stray end tag: nothing of that name is open
        for pos in range(len(self.stack) - 1, 0, -1):
            name = self.stack[pos][1]
            if name == tag:
                self.stack.truncate(pos)
                return
            if name == "#shadow-root":
                return  # never close across a shadow boundary

    def handle_data(self, data: str) -> None:
        if self.b.full:
            raise _Full
        self.pending_text.append(data)

    def close(self) -> None:
        super().close()
        self._flush()


def _precut(b: _Builder, raw: str) -> str:
    """Cut a text node before whitespace is collapsed, so collapsing never
    runs over more than a bounded amount (4x the kept length allows for
    whitespace that collapsing removes). Recorded as ``text``."""
    keep = 4 * b.limits.max_text_chars
    if len(raw) > keep:
        b.cut("text", b.limits.max_text_chars)
        return raw[:keep]
    return raw


def _squash(raw: str) -> str:
    """Collapse whitespace but keep one edge space as a word separator."""
    inner = collapse(raw)
    lead = " " if raw[:1].isspace() else ""
    tail = " " if raw[-1:].isspace() else ""
    return f"{lead}{inner}{tail}"


def from_html(html: str, url: str = "", limits: DocLimits | None = None) -> Doc:
    """Parse serialized HTML. Never raises on malformed markup."""
    b = _Builder(limits or DocLimits())
    root = b.add(ROOT, -1, 0, tag="#document", attrs=[("url", url)])
    parser = _HTMLTree(b, root, 1, 0)
    _feed_bounded(parser, b, html or "")
    return b.finish("html", url)


class _Full(Exception):
    """Raised from a parser callback once the builder is full, to stop
    ``html.parser`` at once: tokenizing the rest is work with no result."""


def _feed_bounded(parser: _HTMLTree, b: _Builder, html: str) -> None:
    """Feed serialized HTML within ``max_input_chars``, in one call (feeding
    in chunks makes some ``html.parser`` versions rescan a tag that spans
    chunks: quadratic), stopping as soon as the builder is full. Both cuts
    are recorded as ``input-chars``."""
    lim = b.limits.max_input_chars
    if len(html) > lim:
        b.cut("input-chars", lim, len(html) - lim)
        html = html[:lim]
    try:
        parser.feed(html)
        parser.close()
    except _Full:
        b.cut("input-chars", lim)
    except Exception:  # html.parser can raise on pathological input
        b.cut("parse-error", 0)
        parser._flush()


# ---------------------------------------------------------------------------
# From the Chrome DevTools Protocol pierced DOM (DOM.getDocument depth=-1, pierce)
# ---------------------------------------------------------------------------


def from_cdp(root: Mapping[str, Any], url: str = "", limits: DocLimits | None = None,
             include_user_agent_shadow: bool = False,
             extra_truncations: Mapping[str, tuple[int, int]] | None = None) -> Doc:
    """Build from a pierced protocol DOM (see ``_cdp_build``)."""
    b, _backend, doc_url = _cdp_build(root, url, limits, include_user_agent_shadow,
                                      extra_truncations)
    return b.finish("cdp-dom", doc_url)


#: Chrome's DOM agent sends at most 10,000 characters of a text node's value
#: and appends U+2026 (Blink ``InspectorDOMAgent``: ``maxTextSize = 10000``);
#: measured in the owner captures (48 such nodes, 27 pages). Such a node is
#: recorded as a ``cdp-text`` cut, so a long JSON-LD block or script read
#: this way is known to be incomplete, never silently malformed.
_CDP_TEXT_CAP = 10_000


def _cdp_build(root: Mapping[str, Any], url: str, limits: DocLimits | None,
               include_user_agent_shadow: bool,
               extra_truncations: Mapping[str, tuple[int, int]] | None,
               ) -> tuple[_Builder, dict[int, int], str]:
    """Build from a ``DOM.getDocument(depth=-1, pierce=true)`` result.

    Order per element: shadow roots, then an iframe's ``contentDocument``,
    then light children. Slot distribution is not applied: light children
    stay under their host; the slot each one is assigned to is recorded in
    ``Doc.slots`` (child index → ``<slot>`` index) from the protocol's
    ``assignedSlot`` / ``distributedNodes`` back-references. User-agent
    shadow roots (the browser's own input internals) are skipped by default.

    Frames. Every ``<iframe>``/``<frame>`` element yields one ``FrameInfo``
    with its URL, origin, same-origin flag and read state. An adapter that
    could not read a frame marks the iframe's JSON node with
    ``"frameState"`` (one of ``FRAME_STATES``); the builder records it.
    A FRAME node carries ``url``, ``origin`` and ``same-origin`` attributes.

    ``extra_truncations`` lets an adapter report cuts it made before the
    payload reached here (script-walk caps), so none is silent.

    Never raises on malformed payloads: wrong types are skipped and counted
    as ``malformed``.
    """
    lim = limits or DocLimits()
    b = _Builder(lim)
    node: Any = root.get("root", root) if isinstance(root, Mapping) else {}
    if not isinstance(node, Mapping):
        node = {}
        b.cut("malformed", 0)
    doc_url = url or str(node.get("documentURL") or node.get("baseURL") or "")
    top_origin = origin_of(doc_url)
    top = b.add(ROOT, -1, 0, tag="#document", attrs=[("url", doc_url)])
    backend: dict[int, int] = {}
    pending_slots: list[tuple[int, int]] = []   # (node idx, slot backend id)
    distributed: list[tuple[int, int]] = []     # (slot idx, node backend id)
    # stack items: (json node, parent index, depth, frame depth, frame origin)
    stack: list[tuple[Any, int, int, int, str]] = []

    def push_children(n: Mapping[str, Any], parent: int, depth: int, fd: int, org: str) -> None:
        kids: list[Any] = []
        for key in ("shadowRoots", "children"):
            v = n.get(key)
            if isinstance(v, list):
                if key == "children":
                    cd = n.get("contentDocument")
                    if isinstance(cd, Mapping):
                        kids.append(cd)
                kids.extend(v)
        if not isinstance(n.get("children"), list):
            cd = n.get("contentDocument")
            if isinstance(cd, Mapping):
                kids.append(cd)
        for k in reversed(kids):
            stack.append((k, parent, depth, fd, org))

    if top >= 0:
        push_children(node, top, 1, 0, top_origin)
    while stack:
        n, parent, depth, fd, org = stack.pop()
        if b.full:
            b.cut("nodes" if len(b.kind) >= lim.max_nodes else "bytes",
                  lim.max_nodes if len(b.kind) >= lim.max_nodes else lim.max_bytes)
            continue
        if not isinstance(n, Mapping):
            b.cut("malformed", 0)
            continue
        nt = n.get("nodeType")
        if nt == 1:
            if depth >= lim.max_depth:
                b.cut("depth", lim.max_depth)
                continue
            raw = n.get("attributes") or []
            if not isinstance(raw, list):
                raw = []
            n_pairs = len(raw) // 2
            if n_pairs > lim.max_attrs:
                b.cut("attrs", lim.max_attrs, n_pairs - lim.max_attrs)
                n_pairs = lim.max_attrs
            pairs = [(str(raw[2 * k]).lower(), str(raw[2 * k + 1])) for k in range(n_pairs)]
            tag = str(n.get("localName") or n.get("nodeName") or "").lower()
            idx = b.add(ELEMENT, parent, depth, tag=tag, attrs=pairs)
            if idx < 0:
                continue
            bid = n.get("backendNodeId")
            if isinstance(bid, int):
                backend[bid] = idx
            slot = n.get("assignedSlot")
            if isinstance(slot, Mapping) and isinstance(slot.get("backendNodeId"), int):
                pending_slots.append((idx, slot["backendNodeId"]))
            for d in n.get("distributedNodes") or ():
                if isinstance(d, Mapping) and isinstance(d.get("backendNodeId"), int):
                    distributed.append((idx, d["backendNodeId"]))
            if tag in ("iframe", "frame"):
                _frame_info(b, n, idx, pairs, org, top_origin, fd, lim)
            if tag != "template":
                push_children(n, idx, depth + 1, fd, org)
        elif nt == 3:
            value = str(n.get("nodeValue") or "")
            ptag = b.strings[b.tag[parent]] if b.tag[parent] >= 0 else ""
            if ptag in ("script", "style"):
                if len(value) > lim.max_script_chars:
                    b.cut("script-bytes", lim.max_script_chars, len(value) - lim.max_script_chars)
                    value = value[: lim.max_script_chars]
                if b.script_total + len(value) > lim.max_script_total:
                    b.cut("script-bytes", lim.max_script_total, len(value))
                    continue
                b.script_total += len(value)
                if len(value) == _CDP_TEXT_CAP + 1 and value.endswith("\u2026"):
                    b.cut("cdp-text", _CDP_TEXT_CAP)
                tidx = b.add(TEXT, parent, depth, text=value, text_cap=lim.max_script_chars)
            elif value.strip():
                if len(value) == _CDP_TEXT_CAP + 1 and value.endswith("\u2026"):
                    b.cut("cdp-text", _CDP_TEXT_CAP)
                tidx = b.add(TEXT, parent, depth, text=_squash(_precut(b, value)))
            elif value:
                tidx = b.add(TEXT, parent, depth, text=" ")
            else:
                continue
            bid = n.get("backendNodeId")
            if tidx >= 0 and isinstance(bid, int):
                backend[bid] = tidx
                slot = n.get("assignedSlot")
                if isinstance(slot, Mapping) and isinstance(slot.get("backendNodeId"), int):
                    pending_slots.append((tidx, slot["backendNodeId"]))
        elif nt == 11:
            mode = str(n.get("shadowRootType") or "open").lower()
            if mode == "user-agent" and not include_user_agent_shadow:
                continue
            if depth >= lim.max_depth:
                # A shadow root is a level too: without this, shadow roots
                # nested in shadow roots (a malformed payload) had no depth cap.
                b.cut("depth", lim.max_depth)
                continue
            attrs = [("mode", mode)]
            if n.get("unseen"):
                attrs.append(("unseen", "1"))
            idx = b.add(SHADOW, parent, depth, tag="#shadow-root", attrs=attrs)
            if idx >= 0:
                push_children(n, idx, depth + 1, fd, org)
        elif nt == 9:
            if fd + 1 > lim.max_frame_depth:
                b.cut("frame-depth", lim.max_frame_depth)
                _mark_frame(b, parent, FRAME_DEPTH_CAP, -1)
                continue
            furl = str(n.get("documentURL") or n.get("baseURL") or "")
            info = _frame_for(b, parent)
            forg = info.origin if info is not None else origin_of(furl)
            same = info.same_origin if info is not None else forg == top_origin
            idx = b.add(FRAME, parent, depth, tag="#document",
                        attrs=[("url", furl), ("origin", forg),
                               ("same-origin", "1" if same else "0")])
            if idx >= 0:
                _mark_frame(b, parent, FRAME_READ, idx, furl)
                push_children(n, idx, depth + 1, fd + 1, forg)
        # 8 comment, 10 doctype, 7 PI: not page content.
    for idx, sid in pending_slots:
        if sid in backend:
            b.slots[idx] = backend[sid]
    for sidx, nid in distributed:
        if nid in backend:
            b.slots.setdefault(backend[nid], sidx)
    for kind, (limit, count) in (extra_truncations or {}).items():
        b.cut(str(kind), int(limit), int(count))
    return b, backend, doc_url


def _frame_info(b: _Builder, n: Mapping[str, Any], idx: int, pairs: list[tuple[str, str]],
                org: str, top_origin: str, fd: int, lim: DocLimits) -> None:
    attrs = dict(pairs)
    src = attrs.get("src", "")
    cd = n.get("contentDocument")
    furl = ""
    if isinstance(cd, Mapping):
        furl = str(cd.get("documentURL") or "")
    furl = furl or str(n.get("frameURL") or "") or ("about:srcdoc" if "srcdoc" in attrs else src)
    sandbox = "sandbox" in attrs
    allow_same = "allow-same-origin" in attrs.get("sandbox", "").split()
    if sandbox and not allow_same:
        forg = "null"
    elif "srcdoc" in attrs or furl == "" or furl.startswith("about:"):
        forg = org   # srcdoc and about:blank inherit their parent's origin
    elif furl.startswith("data:"):
        forg = "null"
    else:
        forg = origin_of(furl)
    same = forg != "null" and forg == top_origin
    state = str(n.get("frameState") or "")
    if state not in FRAME_STATES:
        state = FRAME_EMPTY
    b.frames.append(FrameInfo(idx, -1, furl, forg, same, sandbox, state,
                              str(n.get("frameId") or "")))
    if state not in (FRAME_EMPTY, FRAME_READ):
        b.cut(f"frame-{state}", 0)


def _frame_for(b: _Builder, element: int) -> FrameInfo | None:
    for f in reversed(b.frames):
        if f.element == element:
            return f
    return None


def _mark_frame(b: _Builder, element: int, state: str, document: int, url: str = "") -> None:
    for k in range(len(b.frames) - 1, -1, -1):
        f = b.frames[k]
        if f.element == element:
            b.frames[k] = FrameInfo(f.element, document, url or f.url, f.origin, f.same_origin,
                                    f.sandboxed, state, f.frame_id)
            return


# ---------------------------------------------------------------------------
# From DOMSnapshot.captureSnapshot (layout: bounds, paint order, computed style)
# ---------------------------------------------------------------------------

#: The computed styles ``from_snapshot`` expects, in this order, unless told otherwise.
SNAPSHOT_STYLES: tuple[str, ...] = ("display", "visibility", "opacity")


def _snap_str(strings: list[Any], i: Any) -> str:
    if isinstance(i, int) and 0 <= i < len(strings):
        return str(strings[i])
    return ""


def _rare(d: Any) -> dict[int, Any]:
    if not isinstance(d, Mapping):
        return {}
    idx, val = d.get("index") or [], d.get("value") or []
    if isinstance(val, list) and isinstance(idx, list):
        return {int(k): v for k, v in zip(idx, val) if isinstance(k, int)}
    if isinstance(idx, list):  # RareBooleanData has only an index list
        return {int(k): True for k in idx if isinstance(k, int)}
    return {}


def snapshot_to_tree(snapshot: Mapping[str, Any], max_nodes: int = 2_000_000) -> dict[str, Any]:
    """Re-shape a ``DOMSnapshot.captureSnapshot`` result into the nested
    ``DOM.getDocument`` form, so one builder serves both. Iterative, bounded
    by ``max_nodes`` (the rest is dropped and reported as ``snapshot-nodes``)."""
    strings = snapshot.get("strings") if isinstance(snapshot, Mapping) else None
    docs = snapshot.get("documents") if isinstance(snapshot, Mapping) else None
    if not isinstance(strings, list) or not isinstance(docs, list) or not docs:
        return {"nodeType": 9, "children": [], "malformed": True}
    built: list[dict[str, Any]] = []
    budget = max_nodes
    dropped = 0
    for d in docs:
        nodes = d.get("nodes") if isinstance(d, Mapping) else None
        if not isinstance(nodes, Mapping):
            built.append({"nodeType": 9, "children": []})
            continue
        parent = nodes.get("parentIndex") or []
        ntype = nodes.get("nodeType") or []
        name = nodes.get("nodeName") or []
        value = nodes.get("nodeValue") or []
        attrs = nodes.get("attributes") or []
        bids = nodes.get("backendNodeId") or []
        shadow = _rare(nodes.get("shadowRootType"))
        content = _rare(nodes.get("contentDocumentIndex"))
        n = min(len(parent), len(ntype))
        if n > budget:
            dropped += n - budget
            n = budget
        budget -= n
        objs: list[dict[str, Any]] = []
        for i in range(n):
            t = ntype[i]
            o: dict[str, Any] = {"nodeType": t, "children": []}
            if i < len(bids):
                o["backendNodeId"] = bids[i]
            if t == 1:
                o["localName"] = _snap_str(strings, name[i] if i < len(name) else -1).lower()
                raw = attrs[i] if i < len(attrs) and isinstance(attrs[i], list) else []
                o["attributes"] = [_snap_str(strings, x) for x in raw]
            elif t == 3:
                o["nodeValue"] = _snap_str(strings, value[i] if i < len(value) else -1)
            elif t == 11:
                o["shadowRootType"] = _snap_str(strings, shadow.get(i, -1)) or "open"
            elif t == 9:
                o["documentURL"] = _snap_str(strings, d.get("documentURL", -1))
                o["frameId"] = _snap_str(strings, d.get("frameId", -1))
            if i in content:
                o["_content"] = content[i]
            objs.append(o)
        for i in range(n):
            p = parent[i]
            if isinstance(p, int) and 0 <= p < n and p != i:
                key = "shadowRoots" if objs[i]["nodeType"] == 11 else "children"
                objs[p].setdefault(key, []).append(objs[i])
        built.append(objs[0] if objs else {"nodeType": 9, "children": []})
    # Graft each frame's document under its iframe (by document index; acyclic:
    # a document can be grafted once).
    used: set[int] = {0}
    stack: list[dict[str, Any]] = [built[0]]
    while stack:
        o = stack.pop()
        ci = o.pop("_content", None)
        if isinstance(ci, int) and 0 < ci < len(built) and ci not in used:
            used.add(ci)
            o["contentDocument"] = built[ci]
        stack.extend(o.get("children", ()))
        stack.extend(o.get("shadowRoots", ()))
        cd = o.get("contentDocument")
        if isinstance(cd, dict):
            stack.append(cd)
    top = built[0]
    if dropped:
        top["snapshotDropped"] = dropped
    return top


def from_snapshot(snapshot: Mapping[str, Any], url: str = "", limits: DocLimits | None = None,
                  dom: Mapping[str, Any] | None = None,
                  styles: tuple[str, ...] = SNAPSHOT_STYLES,
                  viewport: tuple[float, float] = (0.0, 0.0),
                  extra_truncations: Mapping[str, tuple[int, int]] | None = None) -> Doc:
    """Build a ``Doc`` with ``layout`` from ``DOMSnapshot.captureSnapshot``
    called with ``computedStyles=list(styles)`` (and ``includePaintOrder``).

    Geometry is in CSS pixels of the top document. A node absent from every
    ``layout.nodeIndex`` has no box. Never raises on malformed input.

    **The snapshot flattens shadow DOM** (measured, Chromium via Playwright:
    no shadow-root nodes, shadow content inlined in composed order). Pass
    the pierced ``DOM.getDocument`` result as ``dom`` and the tree comes from
    it, with layout joined by ``backendNodeId``; without ``dom`` the tree is
    the flattened one and ``source`` is ``cdp-snapshot-flat`` (shadow
    boundaries, hence ``label[for]`` scopes, are not known).
    """
    lim = limits or DocLimits()
    extra = dict(extra_truncations or {})
    if dom is not None:
        tree: Mapping[str, Any] = dom
        source = "cdp-dom+snapshot"
    else:
        flat = snapshot_to_tree(snapshot, max_nodes=lim.max_nodes * 4)
        if flat.get("snapshotDropped"):
            extra["snapshot-nodes"] = (lim.max_nodes * 4, int(flat["snapshotDropped"]))
        tree = flat
        source = "cdp-snapshot-flat"
    b, backend, doc_url = _cdp_build(tree, url, lim, False, extra)
    layout = Layout(len(b.kind), viewport)
    strings = snapshot.get("strings") if isinstance(snapshot, Mapping) else None
    docs = snapshot.get("documents") if isinstance(snapshot, Mapping) else None
    if isinstance(strings, list) and isinstance(docs, list):
        si = {name: k for k, name in enumerate(styles)}
        for d in docs:
            if not isinstance(d, Mapping):
                continue
            nodes = d.get("nodes") or {}
            bids = nodes.get("backendNodeId") or [] if isinstance(nodes, Mapping) else []
            lay = d.get("layout") or {}
            if not isinstance(lay, Mapping):
                continue
            nidx = lay.get("nodeIndex") or []
            bounds = lay.get("bounds") or []
            st = lay.get("styles") or []
            paint = lay.get("paintOrders") or []
            for k, ni in enumerate(nidx):
                if not isinstance(ni, int) or not (0 <= ni < len(bids)):
                    continue
                j = backend.get(bids[ni], -1)
                if j < 0:
                    continue
                layout.has_box[j] = 1
                bx = bounds[k] if k < len(bounds) else None
                if isinstance(bx, list) and len(bx) >= 4:
                    try:
                        layout.x[j], layout.y[j], layout.w[j], layout.h[j] = (
                            float(bx[0]), float(bx[1]), float(bx[2]), float(bx[3]))
                    except (TypeError, ValueError):
                        pass
                if k < len(paint) and isinstance(paint[k], int):
                    layout.paint[j] = paint[k]
                sv = st[k] if k < len(st) and isinstance(st[k], list) else []
                flags = 0
                if "display" in si and si["display"] < len(sv):
                    disp = _snap_str(strings, sv[si["display"]])
                    if disp == "none":
                        flags |= Layout.DISPLAY_NONE
                    elif disp == "contents":
                        flags |= Layout.CONTENTS
                if "visibility" in si and si["visibility"] < len(sv):
                    if _snap_str(strings, sv[si["visibility"]]) in ("hidden", "collapse"):
                        flags |= Layout.VIS_HIDDEN
                if "opacity" in si and si["opacity"] < len(sv):
                    try:
                        if float(_snap_str(strings, sv[si["opacity"]]) or "1") <= 0.01:
                            flags |= Layout.OPACITY_ZERO
                    except ValueError:
                        pass
                layout.style[j] = flags
    b.layout = layout
    return b.finish(source, doc_url)
