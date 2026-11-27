"""Controls (CT-T-027, 05 section 15): filters, sort, toolbars, chips, pagination, search.

``(Doc, regions, piece vocabulary) -> [ControlBinding]``. Pure, ``O(n)``.
The toolkit never operates a control: a binding says what the control is,
which search piece it serves and how it applies; the engine hands an
``ActionRequest`` to the interaction layer and checks the effect with
``pagecomp.effect`` (ALG-027).

Widget kinds (WAI-ARIA Authoring Practices patterns): ``select``,
``checkbox_group``, ``radio_group``, ``switch``, ``menu_button``,
``listbox``, ``slider``, ``range``, ``chip``, ``link_set`` (pagination),
``toolbar``, ``text`` (a search box or a location box).

Pieces: ``keywords``, ``location``, ``date_posted``, ``remote``,
``salary``, ``sort``, ``easy_apply``, ``job_type``, ``experience``,
``page_size``, ``page_next``, ``page_number``, ``load_more``,
``facet:<name>`` for a named group outside the vocabulary, or ``unknown``.
An ``unknown`` control is recorded and never operated (unknown-unknown rule,
12 s2). The vocabulary is English and lives in ``PIECE_WORDS``: it adds
evidence; structure (``role=switch``, a ``rel=next`` link, a search form)
decides where it can.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pagecomp.doc import ELEMENT, Doc
from pagecomp.params import ParamSpec
from pagecomp.registry import ToolSpec
from pagecomp.results import Evidence, Ok
from pagecomp.text import collapse, key, token_set
from pagecomp.tools.verdict import CONSENT_MARKERS

PIECE_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("sort", ("sort", "sort by", "order by")),
    ("easy_apply", ("easy apply", "easily apply", "quick apply", "1-click apply", "apply on company site")),
    ("date_posted", ("date posted", "posted", "past 24 hours", "past week", "past month",
                     "last 7 days", "last 24 hours", "any time", "last 3 days", "date")),
    ("remote", ("remote", "work from home", "hybrid", "on-site", "onsite", "in-office",
                "workplace", "work type", "location type")),
    ("salary", ("salary", "pay", "compensation", "wage", "$")),
    ("sort", ("relevance", "newest", "most recent", "most relevant")),
    ("job_type", ("job type", "full-time", "full time", "part-time", "part time", "contract",
                  "internship", "temporary", "employment type")),
    ("experience", ("experience", "experience level", "seniority", "entry level", "mid-senior",
                    "senior level", "career level")),
    ("page_size", ("per page", "results per page", "show 25", "show 50", "items per page")),
    ("location", ("location", "city", "distance", "radius", "miles", "km", "within")),
)
_NEXT = frozenset({"next", "older"})
_NEXT_OK = frozenset({"next", "older", "page", "results", "go", "to", "jobs", "posts", ">", "›", "»", "→"})
_LOAD_MORE = ("load more", "show more", "see more jobs", "more jobs", "view more")
_APPLY_FILTERS = frozenset({"apply", "show", "results", "done", "update", "search", "filter"})
_REMOVE = re.compile(r"\b(remove|clear|delete|dismiss)\b|^\s*[×x✕]\s*$", re.I)
_NUM = re.compile(r"^\s*\d{1,4}\s*$")
_SEARCH_NAMES = frozenset({"q", "query", "search", "keywords", "keyword", "kw", "k", "searchterm",
                           "what", "title", "term"})
_LOC_NAMES = frozenset({"l", "location", "where", "loc", "city", "near", "geo"})


@dataclass(frozen=True)
class ControlBinding:
    node: int
    control_key: str
    widget_kind: str
    piece: str
    name: str                      # accessible name / group label
    options: tuple[str, ...]
    current: tuple[str, ...]       # what the page shows as selected now (defaults included)
    apply_mode: str                # instant | apply_button | drawer
    region: str                    # toolbar | facet_sidebar | chip_bar | pagination | search | form | page
    confidence: float
    evidence: tuple[str, ...]
    href: str = ""                 # for link-style controls (pagination)
    minimum: str = ""
    maximum: str = ""


@dataclass(frozen=True)
class Controls:
    bindings: tuple[ControlBinding, ...]

    def by_piece(self, piece: str) -> tuple[ControlBinding, ...]:
        return tuple(b for b in self.bindings if b.piece == piece)


def control_key(doc: Doc, i: int, name: str) -> str:
    """Path of tag:index-among-same-tag-siblings, plus the name: stable for
    one epoch, readable in a trace."""
    parts: list[str] = []
    cur = i
    while cur > 0 and len(parts) < 24:
        p = doc.parent[cur]
        if p < 0:
            break
        tag = doc.tag_name(cur) or "#"
        idx = sum(1 for c in doc.children(p) if c < cur and doc.tag_name(c) == tag)
        parts.append(f"{tag}:{idx}")
        cur = p
    return "/".join(reversed(parts)) + "|" + key(name)[:60]


def piece_for(text: str, options: tuple[str, ...] = ()) -> tuple[str, str]:
    """(piece, evidence) from a name and its options; vocabulary evidence."""
    blob = key(" ".join((text,) + options[:30]))
    for piece, words in PIECE_WORDS:
        for w in words:
            if (w == "$" and "$" in blob) or (w != "$" and re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", blob)):
                return piece, f"vocabulary:{w}"
    return "unknown", ""


def _region(doc: Doc, i: int, checkbox_dense: set[int]) -> str:
    for a in [i, *doc.ancestors(i, 40)]:
        if doc.kind[a] != ELEMENT:
            continue
        role = (doc.attr(a, "role") or "").lower()
        tag = doc.tag_name(a)
        label = key(doc.attr(a, "aria-label") or "")
        if role == "toolbar":
            return "toolbar"
        if role == "search" or (tag == "form" and "search" in (doc.attr(a, "action") or "").lower()):
            return "search"
        if (tag == "nav" or role == "navigation") and ("pag" in label or "page" in label):
            return "pagination"
        if tag == "aside" or role == "complementary" or a in checkbox_dense:
            return "facet_sidebar"
    return "page"


def _label_of(doc: Doc, i: int) -> str:
    name = doc.accessible_name(i)
    if name:
        return name
    iid = doc.attr(i, "id")
    if iid:
        for lab in doc.elements("label"):
            if doc.attr(lab, "for") == iid and doc.scope[lab] == doc.scope[i]:
                return doc.text_content(lab, 120)[0]
    for a in doc.ancestors(i, 4):
        if doc.tag_name(a) == "label":
            return doc.text_content(a, 120)[0]
    return collapse(doc.attr(i, "placeholder") or doc.attr(i, "title") or doc.attr(i, "name") or "")


def _group_label(doc: Doc, nodes: list[int]) -> str:
    anc = nodes[0]
    for x in nodes[1:]:
        while anc > 0 and not doc.is_ancestor(anc, x):
            anc = doc.parent[anc]
    for a in [anc, *doc.ancestors(anc, 4)]:
        if doc.kind[a] != ELEMENT:
            break
        if doc.tag_name(a) == "fieldset":
            for c in doc.children(a):
                if doc.tag_name(c) == "legend":
                    return doc.text_content(c, 120)[0]
        lab = doc.idref_text(a, "aria-labelledby", 120) or collapse(doc.attr(a, "aria-label") or "")
        if lab:
            return lab
        # a heading or button right before the group (facet sidebars)
        p = doc.parent[a]
        if p >= 0:
            prev = [c for c in doc.children(p) if c < a and doc.kind[c] == ELEMENT]
            if prev:
                t = doc.text_content(prev[-1], 120)[0]
                if t and len(t) <= 60:
                    return t
    return ""


def _apply_mode(doc: Doc, i: int, vis: Any) -> tuple[str, str]:
    hidden_container = vis is not None and vis.hidden(i)
    for a in doc.ancestors(i, 12):
        if doc.kind[a] != ELEMENT:
            break
        if (doc.attr(a, "role") or "") == "dialog" or doc.tag_name(a) == "dialog" or hidden_container:
            return "drawer", "inside a dialog or hidden panel"
        if doc.tag_name(a) == "form" and (doc.attr(a, "role") or "") != "search":
            for b in range(a, doc.end[a]):
                if doc.kind[b] == ELEMENT and (doc.tag_name(b) == "button" or
                                                (doc.attr(b, "type") or "").lower() == "submit"):
                    if token_set(doc.accessible_name(b) or doc.attr(b, "value") or "") & _APPLY_FILTERS:
                        return "apply_button", "an apply/show-results button in its form"
            return "apply_button", "inside a form"
    return "instant", ""


def _in_consent(doc: Doc, i: int) -> bool:
    for a in doc.ancestors(i, 40):
        if doc.kind[a] != ELEMENT:
            continue
        blob = f"{doc.attr(a, 'id') or ''} {doc.attr(a, 'class') or ''} {doc.attr(a, 'aria-label') or ''}".lower()
        if any(m in blob for m in CONSENT_MARKERS):
            return True
    return False


def find_controls(doc: Doc, vis: Any, forms: Any, p: Mapping[str, Any], tick: Any) -> Controls:
    n = len(doc)
    tick(n)
    shown = (lambda i: not (vis is not None and vis.hidden(i)))
    max_opts = int(p["max_options"])
    out: list[ControlBinding] = []
    app_roots = []
    if forms is not None:
        app_roots = [f.root for f in forms.forms if f.purpose == "application"]

    def in_app_form(i: int) -> bool:
        return any(r == i or doc.is_ancestor(r, i) for r in app_roots)

    # Containers dense with checkboxes are facet sidebars.
    boxes = [i for i in doc.elements("input") if (doc.attr(i, "type") or "").lower() == "checkbox"]
    dense: set[int] = set()
    for b in boxes:
        a = doc.lift(b, 4)
        if a > 0 and sum(1 for x in boxes if doc.is_ancestor(a, x)) >= 4:
            dense.add(a)
    claimed: set[int] = set()

    def emit(node: int, kind: str, name: str, options: tuple[str, ...], current: tuple[str, ...],
             ev: list[str], piece: str | None = None, href: str = "", lo: str = "", hi: str = "",
             region: str | None = None) -> None:
        if _in_consent(doc, node):
            return   # a consent manager's own controls are not search controls
        if piece is None:
            piece, pev = piece_for(name, options)
            if pev:
                ev.append(pev)
        mode, mev = _apply_mode(doc, node, vis)
        if mev:
            ev.append(mev)
        reg = region or _region(doc, node, dense)
        conf = 0.9 if piece != "unknown" else 0.4
        out.append(ControlBinding(node, control_key(doc, node, name), kind, piece, name[:120],
                                  options[:max_opts], current, mode, reg, conf, tuple(ev), href, lo, hi))

    # Search boxes (search-purpose forms and role=search): keywords / location.
    for i in doc.elements("input"):
        if not shown(i) or in_app_form(i):
            continue
        t = (doc.attr(i, "type") or "text").lower()
        if t not in ("text", "search", ""):
            continue
        names = token_set(f"{doc.attr(i, 'name') or ''} {doc.attr(i, 'id') or ''}".replace("_", " "))
        label = _label_of(doc, i)
        searchy = t == "search" or bool(names & _SEARCH_NAMES) or _region(doc, i, dense) == "search"
        if names & _LOC_NAMES or "location" in key(label) or "where" in key(label):
            emit(i, "text", label, (), (doc.attr(i, "value") or "",), ["text-box"], piece="location")
            claimed.add(i)
        elif searchy:
            emit(i, "text", label, (), (doc.attr(i, "value") or "",), ["search-box"], piece="keywords",
                 region="search")
            claimed.add(i)
    # Native selects.
    for i in doc.elements("select"):
        if not shown(i) or in_app_form(i):
            continue
        sel_opts: list[str] = []
        sel_cur: list[str] = []
        for o in range(i, doc.end[i]):
            if doc.kind[o] == ELEMENT and doc.tag_name(o) == "option":
                t = doc.text_content(o, 80)[0] or (doc.attr(o, "value") or "")
                sel_opts.append(t)
                if doc.has_attr(o, "selected"):
                    sel_cur.append(t)
        if not sel_cur and sel_opts:
            sel_cur = [sel_opts[0]]
        emit(i, "select", _label_of(doc, i), tuple(sel_opts), tuple(sel_cur), ["native-select"])
        claimed.add(i)
    # Checkbox and radio groups (by name within a container), and switches.
    groups: dict[tuple[int, str, str], list[int]] = {}
    for i in doc.elements("input"):
        t = (doc.attr(i, "type") or "").lower()
        if t not in ("checkbox", "radio") or in_app_form(i):
            continue
        nm = doc.attr(i, "name") or f"#{doc.parent[doc.parent[i]]}"
        groups.setdefault((doc.scope[i], t, nm), []).append(i)
    for (_sc, t, _nm), members in sorted(groups.items(), key=lambda kv: kv[1][0]):
        members = [m for m in members if shown(m) or vis is None or vis.why(m) in ("visible-unproven", "visible")]
        if not members:
            continue
        g_opts = tuple(_label_of(doc, m) for m in members)
        g_cur = tuple(o for m, o in zip(members, g_opts) if doc.has_attr(m, "checked"))
        if len(members) == 1 and t == "checkbox":
            emit(members[0], "switch", g_opts[0], (), ("on",) if g_cur else ("off",), ["single-checkbox"])
        else:
            label = _group_label(doc, members)
            kind = "checkbox_group" if t == "checkbox" else "radio_group"
            piece, pev = piece_for(label, g_opts)
            if piece == "unknown" and label:
                piece = "facet:" + "_".join(key(label).split())[:40]
            emit(members[0], kind, label, g_opts, g_cur, [f"{t}-group"] + ([pev] if pev else []), piece=piece)
        claimed.update(members)
    # ARIA widgets and menu buttons.
    for i in range(n):
        if doc.kind[i] != ELEMENT or i in claimed or not shown(i) or in_app_form(i):
            continue
        role = (doc.attr(i, "role") or "").lower()
        tag = doc.tag_name(i)
        if role == "switch":
            emit(i, "switch", _label_of(doc, i), (), ((doc.attr(i, "aria-checked") or "false"),), ["role=switch"])
        elif role in ("slider",) or (tag == "input" and (doc.attr(i, "type") or "").lower() == "range"):
            emit(i, "slider" if role == "slider" else "range", _label_of(doc, i), (),
                 ((doc.attr(i, "aria-valuenow") or doc.attr(i, "value") or ""),), ["slider"],
                 lo=doc.attr(i, "aria-valuemin") or doc.attr(i, "min") or "",
                 hi=doc.attr(i, "aria-valuemax") or doc.attr(i, "max") or "")
        elif role == "listbox":
            lb_opts = tuple(doc.text_content(o, 80)[0] for o in range(i, doc.end[i])
                            if (doc.attr(o, "role") or "") == "option")
            lb_cur = tuple(doc.text_content(o, 80)[0] for o in range(i, doc.end[i])
                           if (doc.attr(o, "role") or "") == "option" and doc.attr(o, "aria-selected") == "true")
            emit(i, "listbox", _label_of(doc, i), lb_opts, lb_cur, ["role=listbox"])
        elif (tag == "button" or role == "button") and (doc.has_attr(i, "aria-haspopup") or doc.has_attr(i, "aria-expanded")):
            name = doc.accessible_name(i)
            if not name:
                continue
            mb_opts: tuple[str, ...] = ()
            ctl = doc.attr(i, "aria-controls")
            if ctl:
                tgt = doc.by_id(doc.scope[i], ctl.split()[0])
                if tgt >= 0:
                    mb_opts = tuple(doc.text_content(o, 80)[0] for o in range(tgt, doc.end[tgt])
                                 if (doc.attr(o, "role") or "") in ("option", "menuitem", "menuitemradio",
                                                                     "menuitemcheckbox"))
            emit(i, "menu_button", name, mb_opts, (), ["aria-haspopup/expanded"])
        elif tag in ("button", "a") or role == "button":
            name = doc.accessible_name(i)
            if name and _REMOVE.search(name) and len(name) <= 60:
                # a chip: a removable selected filter value
                chip = doc.parent[i]
                text = doc.text_content(chip, 80)[0]
                text = _REMOVE.sub("", text).strip() or name
                emit(i, "chip", text, (), (text,), ["removable-chip"], region="chip_bar")
    # Pagination: rel=next, numbered link sets, next buttons, load more.
    numbered: dict[int, list[int]] = {}
    for i in range(n):
        if doc.kind[i] != ELEMENT or not shown(i):
            continue
        tag = doc.tag_name(i)
        if tag not in ("a", "button") and (doc.attr(i, "role") or "") != "button":
            continue
        name = doc.accessible_name(i)
        k = key(name)
        rel = (doc.attr(i, "rel") or "").lower()
        words = set(k.replace("›", " › ").replace("»", " » ").split())
        if "next" in rel.split() or (words & _NEXT and words <= _NEXT_OK and len(k) <= 24):
            emit(i, "link_set", name or "next", (), (), ["rel=next" if "next" in rel else "next-text"],
                 piece="page_next", href=doc.attr(i, "href") or "", region="pagination")
        elif any(p in k for p in _LOAD_MORE) and len(k) <= 30:
            emit(i, "link_set", name, (), (), ["load-more"], piece="load_more", region="pagination")
        elif _NUM.match(name or "") and tag == "a" and doc.has_attr(i, "href"):
            numbered.setdefault(doc.lift(i, 2), []).append(i)
    for links in numbered.values():
        if len(links) < 2:
            continue
        nums = [int(doc.accessible_name(x)) for x in links]
        if sorted(nums) != list(range(min(nums), min(nums) + len(nums))) and len(set(nums)) != len(nums):
            continue
        page_cur = tuple(doc.accessible_name(x) for x in links if doc.attr(x, "aria-current") in ("page", "true"))
        emit(links[0], "link_set", "pages", tuple(doc.accessible_name(x) for x in links), page_cur,
             ["numbered-links"], piece="page_number", region="pagination")
    out.sort(key=lambda b: b.node)
    return Controls(tuple(out))


def _run(q: Any, params: Mapping[str, Any]) -> Ok[Controls]:
    vis = q.maybe("visibility")
    forms = q.maybe("forms")
    res = find_controls(q.doc, vis, forms, params, q.tick)
    unknown = sum(1 for b in res.bindings if b.piece == "unknown")
    ev = (Evidence("unknown-controls", f"{unknown} recorded, never operated"),) if unknown else ()
    return Ok(res, evidence=ev)


TOOL = ToolSpec(id="controls", ct_id="CT-T-027", version="0.1.0", run=_run,
                needs=("visibility", "forms"),
                params=(ParamSpec("max_options", 200, 1, 10_000, doc="options kept per control (05 s15)"),),
                summary="filters, sort, chips, pagination and search boxes as bindings")
