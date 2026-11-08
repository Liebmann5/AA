"""Forms (CT-T-010, CT-ALG-007): controls, form roots, groups, buttons, steps.

**Controls** ``C``: ``input`` (all types; ``type=hidden`` is kept and
flagged), ``select``, ``textarea``, ARIA widgets (``textbox, combobox,
listbox, checkbox, radio, switch, slider, spinbutton``) and
``contenteditable``, in every scope: shadow roots and same-origin frames
count (SmartRecruiters' application lives in open shadow roots; the
serialized HTML of that page has no form at all).

**Form roots.** Every ``<form>`` (plus controls associated by ``form=``
id, resolved in scope). For the controls in no form, the blueprint takes
the *maximal* nodes ``v`` with ``|C ∩ T(v)| >= 2`` and control density
``|C ∩ T(v)| / |I ∩ T(v)| >= 0.4`` (``I`` = controls, buttons, links).
Two corrections, both recorded in docs/BLUEPRINT.md:

1. "Maximal nodes form a partition of C" is false: a control in no
   qualifying node (a lone newsletter box) is covered by none. Such
   controls go to one ``residual`` group per scope, so every control has
   exactly one home and nothing is silently dropped.
2. A maximal qualifying node can be the whole document. Each chosen node
   is shrunk to the lowest common ancestor of its controls, which is the
   tightest region that still holds them.

Cost ``O(n)`` with prefix sums over pre-order.

**Purpose.** A form with exactly one free-text control, no other field,
and search evidence (``role=search``, ``type=search``, a ``q``/``query``
name, an action path with ``search``) is a ``search`` form, never an
application form (EC-41: a results page's search box read as an
application form, which made Google and Bing results pages
"APPLICATION_FORM").

**Groups.** Radio and checkbox inputs sharing a ``name`` inside one form
root are one question (the miscount fixed in AA's ``apply_target`` today).

**Buttons** are classified ``next`` / ``back`` / ``submit`` / ``other`` by
type and a small lexicon (evidence), with unknown treated as **final**
(CT-INV-004: an unclassified button may submit).
"""

from __future__ import annotations

from array import array
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pagecomp.doc import ELEMENT, Doc
from pagecomp.params import ParamSpec
from pagecomp.registry import ToolSpec
from pagecomp.results import Evidence, Ok
from pagecomp.text import token_set

WIDGET_ROLES = frozenset(
    {"textbox", "combobox", "listbox", "checkbox", "radio", "switch", "slider", "spinbutton", "searchbox"}
)
BUTTON_INPUT_TYPES = frozenset({"submit", "button", "reset", "image"})
CHOICE_TYPES = frozenset({"checkbox", "radio", "select", "role:checkbox", "role:radio", "role:listbox",
                          "role:switch", "role:slider", "range"})
FREE_TEXT_TYPES = frozenset({"", "text", "search", "email", "tel", "url", "number", "password"})
_NEXT = frozenset({"next", "continue", "proceed", "forward", "weiter", "suivant", "siguiente"})
_BACK = frozenset({"back", "previous", "prev", "zurück", "retour", "anterior"})
#: Buttons that show results rather than submit an application ("Show results").
_RESULTS_WORDS = frozenset({"show", "results", "search", "filter", "filters", "update", "refine", "go", "find"})
_SUBMIT = frozenset({"submit", "apply", "send", "finish", "complete", "done", "enviar", "senden", "envoyer"})


@dataclass(frozen=True)
class Control:
    node: int
    tag: str
    type: str          # input type, "select", "textarea", "role:<r>", "contenteditable"
    name: str
    id: str
    form: int          # index into Forms.forms
    in_shadow: bool
    in_frame: bool
    hidden: str        # "" when not shown hidden, else the visibility reason
    native_required: bool
    aria_required: bool
    disabled: bool
    readonly: bool
    autocomplete: str
    has_value: bool
    options: tuple[str, ...]


@dataclass(frozen=True)
class Group:
    kind: str          # "radio" | "checkbox"
    name: str
    form: int
    controls: tuple[int, ...]   # indexes into Forms.controls


@dataclass(frozen=True)
class Button:
    node: int
    form: int
    role: str          # "next" | "back" | "submit" | "other"
    text: str
    type: str
    final: bool        # submit, or not shown to be non-final


@dataclass(frozen=True)
class FormInfo:
    root: int
    kind: str          # "form" | "formless" | "residual"
    purpose: str       # "application" | "search" | "login" | "filter" | "unknown"
    controls: tuple[int, ...]
    novalidate: bool
    method: str
    action: str
    step_markers: int


@dataclass(frozen=True)
class Forms:
    controls: tuple[Control, ...]
    forms: tuple[FormInfo, ...]
    groups: tuple[Group, ...]
    buttons: tuple[Button, ...]

    def of_form(self, form: int) -> list[Control]:
        """Controls of one form; the index is built once (O(C)), not per call."""
        idx = self.__dict__.get("_by_form")
        if idx is None:
            idx = {}
            for c in self.controls:
                idx.setdefault(c.form, []).append(c)
            object.__setattr__(self, "_by_form", idx)
        return idx.get(form, [])

    def fillable(self, form: int) -> list[Control]:
        return [c for c in self.of_form(form) if not c.hidden
                and c.type not in ("hidden",) and not c.disabled]


def control_type(doc: Doc, i: int) -> str | None:
    tag = doc.tag_name(i)
    if tag == "input":
        t = (doc.attr(i, "type") or "text").strip().lower()
        return None if t in BUTTON_INPUT_TYPES else t
    if tag in ("select", "textarea"):
        return tag
    role = (doc.attr(i, "role") or "").strip().lower()
    if role in WIDGET_ROLES:
        return f"role:{role}"
    ce = doc.attr(i, "contenteditable")
    if ce is not None and ce.lower() in ("", "true", "plaintext-only"):
        return "contenteditable"
    return None


def is_button(doc: Doc, i: int) -> bool:
    tag = doc.tag_name(i)
    if tag == "button":
        return True
    if tag == "input" and (doc.attr(i, "type") or "").lower() in BUTTON_INPUT_TYPES:
        return True
    return (doc.attr(i, "role") or "").lower() == "button"


def _in_scope_kind(doc: Doc, i: int, kind: int) -> bool:
    s = doc.scope[i]
    while s > 0:
        if doc.kind[s] == kind:
            return True
        s = doc.scope[doc.parent[s]] if doc.parent[s] >= 0 else 0
    return False


def _lca(doc: Doc, nodes: list[int]) -> int:
    anc = nodes[0]
    for x in nodes[1:]:
        while anc > 0 and not (anc == x or doc.is_ancestor(anc, x)):
            anc = doc.parent[anc]
    return anc


def _classify_button(doc: Doc, i: int) -> tuple[str, str, str]:
    tag = doc.tag_name(i)
    btype = (doc.attr(i, "type") or ("submit" if tag == "button" else "")).lower()
    text = doc.accessible_name(i) or (doc.attr(i, "value") or "")
    toks = token_set(text)
    if toks & _BACK:
        return "back", text, btype
    if toks & _NEXT:
        return "next", text, btype
    if btype in ("submit", "image") or toks & _SUBMIT:
        return "submit", text, btype
    return "other", text, btype


def _purpose(doc: Doc, root: int, ctrls: list[Control]) -> str:
    visible = [c for c in ctrls if not c.hidden]
    free = [c for c in visible if c.type in FREE_TEXT_TYPES or c.type in ("role:searchbox", "role:combobox", "role:textbox")]
    free_nodes = {c.node for c in free}   # membership by node index: O(1), not dataclass equality
    if any(c.type == "password" for c in visible) and len(visible) <= 4:
        return "login"
    others = [c for c in visible if c.node not in free_nodes]
    action = (doc.attr(root, "action") or "").lower()
    in_search = ((doc.attr(root, "role") or "") == "search" or "search" in action
                 or any((doc.attr(a, "role") or "") == "search" for a in doc.ancestors(root, 8)))
    identity_types = {"email", "tel", "password", "file", "textarea"}
    if 1 <= len(free) <= 3 and not others and not any(c.type in identity_types for c in free):
        # A results page's search bar: a keyword box, perhaps a location box.
        names = token_set(" ".join(f"{c.name} {c.id}" for c in free).replace("_", " "))
        searchy = (
            in_search or any(c.type in ("search", "role:searchbox") for c in free)
            or bool(names & {"q", "query", "search", "keywords", "keyword", "searchterm", "kw", "what"})
        )
        if searchy and (len(free) == 1 or names & {"l", "location", "where", "loc", "near", "geo", "city"}
                        or in_search):
            return "search"
    if visible and all(c.type in ("checkbox", "radio", "select", "role:checkbox", "role:radio",
                                  "role:listbox", "role:switch", "role:slider") or c.node in free_nodes
                       for c in visible) and len(free) <= 1 and \
            sum(1 for c in visible if c.type in ("checkbox", "radio", "role:checkbox", "role:radio")) >= 3:
        # Facets: choices only, at most one keyword box. A filter panel, not an application.
        return "filter"
    return "application" if visible else "unknown"


def read_forms(doc: Doc, vis: Any, p: Mapping[str, Any], tick: Any) -> Forms:
    n = len(doc)
    tick(n)
    form_of = array("i", [-1]) * n
    form_nodes: list[int] = []
    for i in range(n):
        if doc.kind[i] == ELEMENT and doc.tag_name(i) == "form" and not doc.in_inert(i):
            form_nodes.append(i)
            for j in range(i + 1, doc.end[i]):
                form_of[j] = len(form_nodes) - 1
    form_ids = {(doc.scope[f], doc.attr(f, "id") or ""): k for k, f in enumerate(form_nodes) if doc.attr(f, "id")}
    # A listbox that is another control's popup (aria-controls / aria-owns,
    # or nested in a combobox) is part of that control, not a question.
    popups: set[tuple[int, str]] = set()
    for i in range(n):
        if doc.kind[i] == ELEMENT:
            for attr in ("aria-controls", "aria-owns"):
                v = doc.attr(i, attr)
                if v:
                    for ref in v.split():
                        popups.add((doc.scope[i], ref))
    raw: list[tuple[int, str, int]] = []      # node, type, form index (or -1)
    is_ctrl = array("B", bytes(n))
    is_inter = array("B", bytes(n))
    button_nodes: list[int] = []
    for i in range(n):
        if doc.kind[i] != ELEMENT:
            continue
        t = control_type(doc, i)
        if t == "role:listbox" and (
                (doc.scope[i], doc.attr(i, "id") or "\x00") in popups
                or any((doc.attr(a, "role") or "") == "combobox" for a in doc.ancestors(i, 6))):
            t = None
        if t is not None:
            if doc.in_inert(i):
                continue
            fk = form_of[i]
            fa = doc.attr(i, "form")
            if fa and (doc.scope[i], fa) in form_ids:
                fk = form_ids[(doc.scope[i], fa)]
            raw.append((i, t, fk))
            is_inter[i] = 1
            if fk < 0:
                is_ctrl[i] = 1
        elif is_button(doc, i) or (doc.tag_name(i) == "a" and doc.has_attr(i, "href")):
            is_inter[i] = 1
            if is_button(doc, i):
                button_nodes.append(i)
    # Formless segmentation over controls in no <form>.
    cp = array("i", [0]) * (n + 1)
    ip = array("i", [0]) * (n + 1)
    for i in range(n):
        cp[i + 1] = cp[i] + is_ctrl[i]
        ip[i + 1] = ip[i] + is_inter[i]
    min_c, dens = int(p["min_controls"]), float(p["min_density"])
    chosen: list[int] = []
    i = 0
    while i < n:
        c = cp[doc.end[i]] - cp[i]
        if c >= min_c and doc.kind[i] in (ELEMENT, 2, 3, 4):
            inter = ip[doc.end[i]] - ip[i]
            if inter and c / inter >= dens:
                chosen.append(i)
                i = doc.end[i]
                continue
        i += 1
    formless: list[tuple[int, list[int]]] = []
    assigned: dict[int, int] = {}
    base = len(form_nodes)
    for region in chosen:
        members = [x for x in range(region, doc.end[region]) if is_ctrl[x]]
        root = _lca(doc, members) if len(members) > 1 else region
        formless.append((root, members))
        for x in members:
            assigned[x] = base + len(formless) - 1
    residual_by_scope: dict[int, int] = {}
    roots_extra: list[tuple[int, str]] = []
    for node, _t, fk in raw:
        if fk < 0 and node not in assigned:
            sc = doc.scope[node]
            if sc not in residual_by_scope:
                residual_by_scope[sc] = base + len(formless) + len(roots_extra)
                roots_extra.append((sc, "residual"))
            assigned[node] = residual_by_scope[sc]
    controls: list[Control] = []
    for node, t, fk in raw:
        form = fk if fk >= 0 else assigned[node]
        options: tuple[str, ...] = ()
        if t == "select":
            opts = [doc.text_content(o, 80)[0] or (doc.attr(o, "value") or "")
                    for o in range(node, doc.end[node])
                    if doc.kind[o] == ELEMENT and doc.tag_name(o) == "option"]
            options = tuple(opts[: int(p["max_options"])])
        val = doc.attr(node, "value")
        checked = doc.has_attr(node, "checked") or doc.has_attr(node, "selected")
        controls.append(Control(
            node=node, tag=doc.tag_name(node), type=t, name=doc.attr(node, "name") or "",
            id=doc.attr(node, "id") or "", form=form,
            in_shadow=_in_scope_kind(doc, node, 2), in_frame=_in_scope_kind(doc, node, 3),
            hidden=(vis.why(node) if vis is not None and vis.hidden(node) else ""),
            native_required=doc.has_attr(node, "required"),
            aria_required=(doc.attr(node, "aria-required") or "").lower() == "true",
            disabled=doc.has_attr(node, "disabled") or (doc.attr(node, "aria-disabled") or "") == "true",
            readonly=doc.has_attr(node, "readonly"),
            autocomplete=(doc.attr(node, "autocomplete") or "").strip().lower(),
            has_value=bool(val and val.strip() and t not in ("radio", "checkbox")) or checked,
            options=options,
        ))
    infos: list[FormInfo] = []
    by_form: dict[int, list[int]] = {}
    for ci, c in enumerate(controls):
        by_form.setdefault(c.form, []).append(ci)
    all_roots = [(f, "form") for f in form_nodes] + [(r, "formless") for r, _ in formless] + roots_extra
    for k, (root, kind) in enumerate(all_roots):
        mine = by_form.get(k, [])
        steps = sum(1 for x in range(root, doc.end[root]) if doc.kind[x] == ELEMENT and (
            doc.attr(x, "aria-current") == "step" or (doc.attr(x, "role") or "") == "progressbar"))
        infos.append(FormInfo(
            root=root, kind=kind,
            purpose=("unknown" if kind == "residual" else _purpose(doc, root, [controls[c] for c in mine])),
            controls=tuple(mine), novalidate=doc.has_attr(root, "novalidate") if kind == "form" else False,
            method=(doc.attr(root, "method") or "get").lower() if kind == "form" else "",
            action=doc.attr(root, "action") or "" if kind == "form" else "", step_markers=steps))
    groups: list[Group] = []
    by_key: dict[tuple[int, str, str], list[int]] = {}
    for ci, c in enumerate(controls):
        if c.type in ("radio", "checkbox") and c.name:
            by_key.setdefault((c.form, c.type, c.name), []).append(ci)
    for (form, kind, name), members in sorted(by_key.items()):
        groups.append(Group(kind, name, form, tuple(members)))
    buttons: list[Button] = []
    for b in button_nodes:
        if doc.in_inert(b):
            continue
        fk = form_of[b]
        if fk < 0:
            # nearest form root (formless or residual) containing the button
            fk = next((k for k, info in enumerate(infos)
                       if info.kind != "form" and doc.is_ancestor(info.root, b)), -1)
        role, text, btype = _classify_button(doc, b)
        buttons.append(Button(b, fk, role, text[:80], btype, final=role in ("submit", "other")))
    # Choices only, no text or file field, and no next/submit button of its
    # own: a filter panel (two "Job type" checkboxes, a "Date posted" radio
    # pair), not an application step. An application step of only choices
    # (an EEO page) has its Next/Submit, so it stays "application".
    advancing = {b.form for b in buttons if b.role in ("next", "submit")
                 and not (token_set(b.text) & _RESULTS_WORDS and not token_set(b.text) & _SUBMIT)}
    for k, info in enumerate(infos):
        if info.purpose != "application" or k in advancing:
            continue
        shown_ctrls = [controls[c] for c in info.controls if not controls[c].hidden]
        if shown_ctrls and all(c.type in CHOICE_TYPES for c in shown_ctrls):
            infos[k] = FormInfo(info.root, info.kind, "filter", info.controls, info.novalidate,
                                info.method, info.action, info.step_markers)
    return Forms(tuple(controls), tuple(infos), tuple(groups), tuple(buttons))


def _run(q: Any, params: Mapping[str, Any]) -> Ok[Forms]:
    vis = q.maybe("visibility")
    forms = read_forms(q.doc, vis, params, q.tick)
    ev = []
    shadow = sum(1 for c in forms.controls if c.in_shadow)
    if shadow:
        ev.append(Evidence("shadow-controls", f"{shadow} controls inside shadow roots"))
    if "SHADOW_PIERCING" not in q.obs.capabilities:
        ev.append(Evidence("no-shadow-piercing", "closed or script-attached shadow content unseen"))
    return Ok(forms, evidence=tuple(ev))


TOOL = ToolSpec(
    id="forms", ct_id="CT-T-010", version="0.2.0", run=_run, needs=("visibility",),
    params=(ParamSpec("min_controls", 2, 1, 50), ParamSpec("min_density", 0.4, 0.05, 1.0),
            ParamSpec("max_options", 500, 1, 100_000)),
    summary="controls, form roots (incl. formless and shadow), groups, buttons",
)
