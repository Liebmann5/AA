"""Reading the fields of one form: labels, groups, requiredness, traps (slice S4).

Pure functions over the immutable ``DOMNode`` tree. The toolkit decides
*what* a field is; nothing here operates a page (05 section 17).

Four algorithms of the comprehension blueprint (06 sections 4 to 6):

* **Pairing ladder (CT-ALG-008).** Explicit associations are constraints, not
  costs: ``label[for]`` to the first element with that id in tree order
  (duplicate ids are counted), a wrapping ``<label>`` holding exactly one
  labelable control, ``aria-labelledby``, ``aria-label``, then the accessible
  name the extraction computed. Only what remains goes to geometry: a
  Hungarian assignment over the residual (unclaimed text blocks near
  unlabelled controls), padded with dummies at a finite cost ``c0`` so a
  control prefers no label to a bad one, capped at ``m <= 120`` per section
  with the 8 nearest candidates per control (05 section 14). Orientation is
  direction-aware: the start side is the left in left-to-right text and the
  right in right-to-left text; a label above the control is natural at any
  horizontal offset near its start edge; text below a field is help text,
  never its label. ``title`` and ``placeholder`` come last (a placeholder
  vanishes when typed in, and a visible label is what a person reads).
  Help text (``aria-describedby``, a hint line directly below the field) is
  the field's description.
* **Question groups.** Radio and checkbox groups become one question with
  its options. The question comes from the ``legend``, then
  ``aria-labelledby``/``aria-label`` on the group, then the nearest preceding
  heading, label or text block.
* **Requiredness (CT-ALG-010, CT-FR-012).** Tri-state from log-odds over the
  signals of 06 section 5, strongest first: ``validity.valueMissing``
  (certain), native ``required`` / ``aria-required`` (+6, one correlated
  group), the word "required" in the label (+3), an asterisk (+1.5, or +4
  when the form carries a legend defining it), "(optional)" (-5), and the
  "most fields say optional" convention (+2.5 for unmarked fields). REQUIRED
  at >= +2, OPTIONAL at <= -2, else UNKNOWN. A hidden required control is
  still reported, flagged hidden.
* **Trap decision (CT-ALG-014).** A control is a trap only on evidence that a
  person cannot see it (computed style read by the extraction, no box,
  off-screen). Name tokens are weak evidence, matched as whole tokens, never
  substrings, and never decide alone. A visibly labelled control is never a
  trap, and neither is a control hidden in place inside a visible widget
  (the native input behind an "Upload" button or a custom checkbox): both
  are reported hidden, and the widget is what gets operated. A hidden
  control labelled like a real field, in a section a person cannot see now
  (a later step, a closed panel), is HIDDEN: never filled, decided again
  when the page is observed again. A visible, unlabelled control is UNKNOWN: recorded, never
  filled. ``p(trap) = sigmoid(sum w_i f_i)``; trap iff hidden and
  ``p >= 0.09`` (``C_trap = 10 C_skip``, a safety parameter).

Every loop runs over a finite, capped collection; nothing recurses.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from auto_apply.domain.models.math_dom import DOMNode, Geometry
from auto_apply.domain.models.math_webpage import FieldType, LabeledField, LabelSource
from auto_apply.domain.models.page_record import FormRecord
from auto_apply.domain.services.label_input_pairing import hungarian_assign

REQUIRED = "REQUIRED"
OPTIONAL = "OPTIONAL"
UNKNOWN = "UNKNOWN"

TRAP = "TRAP"
CLEAR = "CLEAR"
#: Hidden now, but labelled like a real field (a later step, a closed panel,
#: a dialog not yet open): never filled, decided again on re-observation.
HIDDEN = "HIDDEN"


@dataclass(frozen=True)
class FormReadingParams:
    """Tunable numbers of the form reader (worst-case profile defaults).

    ``residual_cap`` and ``candidates_per_control`` are the pairing caps of
    05 section 14. ``trap_threshold`` is ``C_skip / (C_skip + C_trap)`` and
    is a safety parameter, not tunable upward automatically (CT-NFR-019).
    """

    residual_cap: int = 120
    candidates_per_control: int = 8
    em: float = 16.0
    max_label_distance: float = 300.0
    section_gap: float = 60.0
    trap_threshold: float = 0.09


DEFAULT_PARAMS = FormReadingParams()

_BUTTON_INPUT_TYPES = frozenset({"submit", "button", "reset", "image"})
_CHECKABLE_TYPES = frozenset({"radio", "checkbox"})
_NOT_TEXT_TAGS = frozenset(
    {"script", "style", "noscript", "template", "button", "a", "option",
     "select", "textarea", "input", "svg"}
)
_HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6", "legend", "label"})
#: Asterisk glyphs used as required markers: "*", "✱" (Lever), "＊", "∗".
_STARS = "*\u2731\uff0a\u2217"
_MARKER_ONLY = re.compile(
    r"^[\s" + _STARS + r":]*(\(?\s*(required|optional)\s*\)?)?[\s" + _STARS + r":]*$", re.I
)

#: Whole name tokens that suggest a trap. Weak evidence: never decides alone.
_TRAP_TOKENS = frozenset(
    {"honeypot", "honey", "hpot", "hp", "trap", "bot", "botcheck", "nospam", "antispam"}
)
_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+|(?<=[a-z])(?=[0-9])")

_REQUIRED_WORD = re.compile(r"(?<!not )\brequired\b", re.I)
_OPTIONAL_WORD = re.compile(r"\(\s*optional\s*\)|\boptional\b", re.I)
_ASTERISK = re.compile(r"(^\s*[" + _STARS + r"])|([" + _STARS + r"]\s*:?\s*$)")
_LEGEND = re.compile(
    r"(\*\s*(indicates|denotes|marks|means|=)?\s*(a\s+)?(required|mandatory))"
    r"|((required|mandatory)\s+fields?\s+(are\s+)?(marked|indicated|denoted))"
    r"|(fields?\s+marked\s+with\s+(an?\s+)?(\*|asterisk))",
    re.I,
)
_ALL_REQUIRED = re.compile(r"\ball\s+fields\s+are\s+(required|mandatory)\b", re.I)

#: HTML autofill tokens to field types (06 section 4, typing first rung).
_AUTOFILL = {
    "given-name": FieldType.FIRST_NAME,
    "family-name": FieldType.LAST_NAME,
    "name": FieldType.FULL_NAME,
    "email": FieldType.EMAIL,
    "tel": FieldType.TELEPHONE,
    "tel-national": FieldType.TELEPHONE,
    "street-address": FieldType.STREET_ADDRESS,
    "address-line1": FieldType.STREET_ADDRESS,
    "address-level2": FieldType.CITY,
    "address-level1": FieldType.STATE,
    "postal-code": FieldType.ZIP_CODE,
    "country": FieldType.COUNTRY,
    "country-name": FieldType.COUNTRY,
}
_INPUT_TYPES = {
    "email": FieldType.EMAIL,
    "tel": FieldType.TELEPHONE,
    "password": FieldType.PASSWORD,
    "number": FieldType.NUMBER,
    "date": FieldType.DATE,
}


# ── Document index ──────────────────────────────────────────────────────────


@dataclass
class DocIndex:
    """Lookups built once per page: parents, ids, ``label[for]``, order."""

    parent: dict[int, DOMNode | None]
    ids: dict[str, list[DOMNode]]
    label_for: dict[str, list[DOMNode]]
    order: dict[int, int]

    def first_by_id(self, ident: str) -> DOMNode | None:
        nodes = self.ids.get(ident)
        return nodes[0] if nodes else None

    def ancestors(self, node: DOMNode, limit: int = 64):
        current = self.parent.get(id(node))
        steps = 0
        while current is not None and steps < limit:
            yield current
            current = self.parent.get(id(current))
            steps += 1


def build_index(root: DOMNode) -> DocIndex:
    """Index the page once. Iterative; document order is pre-order."""
    parent: dict[int, DOMNode | None] = {id(root): None}
    ids: dict[str, list[DOMNode]] = defaultdict(list)
    label_for: dict[str, list[DOMNode]] = defaultdict(list)
    order: dict[int, int] = {}
    stack = [root]
    position = 0
    while stack:
        node = stack.pop()
        order[id(node)] = position
        position += 1
        ident = node.get_attribute("id")
        if ident:
            ids[ident].append(node)
        if node.tag == "label":
            target = node.get_attribute("for")
            if target:
                label_for[target].append(node)
        for child in reversed(node.children):
            parent[id(child)] = node
            stack.append(child)
    return DocIndex(parent=parent, ids=dict(ids), label_for=dict(label_for), order=order)


# ── Small predicates ────────────────────────────────────────────────────────


def is_button(node: DOMNode) -> bool:
    """A button: never a data field (no label pairing beyond its name)."""
    if node.tag == "button" or node.get_attribute("role") == "button":
        return True
    return node.tag == "input" and node.get_attribute("type", "text").lower() in _BUTTON_INPUT_TYPES


def is_form_control(node: DOMNode) -> bool:
    """A control a form is made of (06 section 4), hidden inputs excluded."""
    if node.tag == "input":
        return node.get_attribute("type", "text").lower() != "hidden"
    return node.is_interactable


def _check_kind(node: DOMNode) -> str:
    """``"radio"``, ``"checkbox"`` or ``""``."""
    if node.tag == "input":
        kind = node.get_attribute("type", "text").lower()
        return kind if kind in _CHECKABLE_TYPES else ""
    role = node.get_attribute("role")
    return role if role in _CHECKABLE_TYPES else ""


def _visible(node: DOMNode) -> bool:
    return node.geometry is not None and node.geometry.width > 0 and node.geometry.height > 0


def hidden_reason(node: DOMNode) -> str:
    """Why a person cannot see this control ("" when visible)."""
    if node.hidden_reason:
        return node.hidden_reason
    if any(k == "hidden" for k, _ in node.attributes):
        return "hidden-attribute"
    if node.geometry is None:
        return "no-box"
    g = node.geometry
    if g.width * g.height < 1.0:
        return "zero-size"
    if g.x + g.width < -50 or g.y + g.height < -50:
        return "off-screen"
    return ""


def _clean_label(text: str) -> str:
    """Whitespace-normalised label without its required/optional marker."""
    text = " ".join((text or "").split())
    text = re.sub(r"\s*[" + _STARS + r"]+\s*$", "", text)
    text = re.sub(r"^\s*[" + _STARS + r"]+\s*", "", text)
    text = re.sub(r"\s*\(\s*required\s*\)\s*$", "", text, flags=re.I)
    return text.strip()


def _node_text(node: DOMNode) -> str:
    return node.display_name() if node.tag in _HEADING_TAGS else (node.text or "")


def _resolve_ids(index: DocIndex, value: str) -> tuple[str, list[DOMNode]]:
    nodes: list[DOMNode] = []
    for ident in value.split():
        target = index.first_by_id(ident)
        if target is not None:
            nodes.append(target)
    text = " ".join(" ".join(n.subtree_text()[0].split()) for n in nodes)
    return text.strip(), nodes


# ── The pairing ladder (explicit rungs) ─────────────────────────────────────


@dataclass
class _Label:
    text: str = ""
    source: str = LabelSource.NONE
    node: DOMNode | None = None
    visible: bool = False


_CONTROL_TEXT_TAGS = frozenset({"select", "option", "textarea", "button", "script", "style", "template"})


def _own_label_text(label: DOMNode) -> str:
    """A wrapping label's text without the text of the controls it holds."""
    parts: list[str] = []
    stack = [label]
    while stack:
        item = stack.pop()
        if item.tag in _CONTROL_TEXT_TAGS or any(k == "hidden" for k, _ in item.attributes):
            continue
        if item is not label and label.geometry is not None and item.geometry is None:
            continue  # not rendered (a hidden error or status message)
        if item.text:
            parts.append(item.text)
        stack.extend(reversed(item.children))
    return " ".join(" ".join(parts).split())


def _wrapping_label(node: DOMNode, index: DocIndex) -> DOMNode | None:
    for ancestor in index.ancestors(node, limit=12):
        if ancestor.tag == "label":
            controls = [
                n for n in ancestor.iter_nodes()
                if n is not ancestor and is_form_control(n) and not is_button(n)
            ]
            return ancestor if len(controls) == 1 else None
        if ancestor.tag in ("form", "fieldset", "body"):
            return None
    return None


def explicit_label(node: DOMNode, index: DocIndex, claimed: set[int]) -> _Label:
    """Rungs 1 to 5 of the ladder for one control (06 section 4)."""
    ident = node.get_attribute("id")
    if ident:
        owner = index.first_by_id(ident)
        labels = index.label_for.get(ident, [])
        # label[for] names the first element with that id in tree order;
        # a later control sharing the id does not get the label.
        if labels and owner is node:
            if len(labels) > 1 and _check_kind(node):
                # An option takes its own label; a second label naming the
                # same option is the group's heading (Ashby), left for the
                # question.
                labels = [min(labels, key=lambda lbl: _tree_distance(lbl, node, index))]
            texts = [_clean_label(lbl.display_name()) for lbl in labels]
            text = " ".join(t for t in texts if t)
            if text:
                for lbl in labels:
                    claimed.add(id(lbl))
                return _Label(text, LabelSource.LABEL_FOR, labels[0], any(_visible(l) for l in labels))
    wrapper = _wrapping_label(node, index)
    if wrapper is not None:
        text = _clean_label(_own_label_text(wrapper))
        if text:
            claimed.add(id(wrapper))
            return _Label(text, LabelSource.WRAPPING_LABEL, wrapper, _visible(wrapper))
    labelledby = node.get_attribute("aria-labelledby")
    if labelledby:
        text, nodes = _resolve_ids(index, labelledby)
        text = _clean_label(text)
        if text:
            for target in nodes:
                claimed.add(id(target))
            return _Label(text, LabelSource.ARIA_LABELLEDBY, nodes[0], any(_visible(n) for n in nodes))
    aria = _clean_label(node.get_attribute("aria-label"))
    if aria:
        return _Label(aria, LabelSource.ARIA_LABEL)
    if node.accessible_name:
        return _Label(_clean_label(node.accessible_name), LabelSource.ACCESSIBLE_NAME)
    if is_button(node):
        # A button is named by its content or value (accname); the S1 script
        # computes that, and a tree built without it falls back here.
        name = " ".join((node.display_name() or node.get_attribute("value")).split())
        if name:
            return _Label(name, LabelSource.ACCESSIBLE_NAME, node, _visible(node))
    return _Label()


# ── Residual geometry ───────────────────────────────────────────────────────


def _relation(label: Geometry, ctrl: Geometry, rtl: bool, checkable: bool, em: float) -> float | None:
    """Orientation penalty in em; None when the label may not be this control's."""
    tol = 4.0
    if label.y + label.height <= ctrl.y + tol:  # above
        start_gap = (
            abs((label.x + label.width) - (ctrl.x + ctrl.width)) if rtl else abs(label.x - ctrl.x)
        )
        overlap = label.x < ctrl.x + ctrl.width and label.x + label.width > ctrl.x
        return 0.0 if overlap or start_gap <= 3 * em else 1.0
    if label.y >= ctrl.y + ctrl.height - tol:  # below
        return 3.0 if checkable else None
    # same row
    start_side = (label.x >= ctrl.x + ctrl.width - tol) if rtl else (label.x + label.width <= ctrl.x + tol)
    end_side = (label.x + label.width <= ctrl.x + tol) if rtl else (label.x >= ctrl.x + ctrl.width - tol)
    if start_side:
        return 0.0
    if end_side:
        return 0.0 if checkable else 2.0
    return 1.0  # overlapping boxes: a floating label inside the field


def _edge_distance(a: Geometry, b: Geometry) -> float:
    dx = max(0.0, a.x - (b.x + b.width), b.x - (a.x + a.width))
    dy = max(0.0, a.y - (b.y + b.height), b.y - (a.y + a.height))
    return math.hypot(dx, dy)


def _tree_distance(a: DOMNode, b: DOMNode, index: DocIndex) -> int:
    path = {id(a): 0}
    for steps, ancestor in enumerate(index.ancestors(a), start=1):
        path[id(ancestor)] = steps
    if id(b) in path:
        return path[id(b)]
    for steps, ancestor in enumerate(index.ancestors(b), start=1):
        if id(ancestor) in path:
            return steps + path[id(ancestor)]
    return 64


def _text_blocks(container: DOMNode, excluded: set[int]) -> list[DOMNode]:
    """Visible text blocks inside the container that may label a control."""
    blocks: list[DOMNode] = []
    stack = [container]
    while stack:
        node = stack.pop()
        if id(node) in excluded or node.tag in _NOT_TEXT_TAGS:
            continue
        if node.tag in _HEADING_TAGS and node is not container:
            text = node.display_name()
            if _visible(node) and text and not _MARKER_ONLY.match(text):
                blocks.append(node)
            continue  # a label or heading is one block
        if node.text and _visible(node) and not _MARKER_ONLY.match(node.text):
            blocks.append(node)
        stack.extend(reversed(node.children))
    return blocks


@dataclass
class _Residual:
    assigned: dict[int, DOMNode] = field(default_factory=dict)
    max_size: int = 0
    sections: int = 0
    truncated: int = 0


def _solve_section(
    controls: list[DOMNode],
    candidates: dict[int, list[tuple[float, DOMNode]]],
    params: FormReadingParams,
) -> dict[int, DOMNode]:
    labels: list[DOMNode] = []
    seen: set[int] = set()
    for ctrl in controls:
        for _cost, lbl in candidates[id(ctrl)]:
            if id(lbl) not in seen:
                seen.add(id(lbl))
                labels.append(lbl)
    if not labels:
        return {}
    n_k, n_l = len(controls), len(labels)
    size = n_k + n_l
    c0 = params.max_label_distance / params.em
    big = 1e6
    col = {id(lbl): j for j, lbl in enumerate(labels)}
    matrix = [[0.0] * size for _ in range(size)]
    for i, ctrl in enumerate(controls):
        row = matrix[i]
        for j in range(n_l):
            row[j] = big
        for cost, lbl in candidates[id(ctrl)]:
            row[col[id(lbl)]] = cost
        for j in range(n_l, size):
            row[j] = c0 if j - n_l == i else big
    rows, cols = hungarian_assign(matrix)
    out: dict[int, DOMNode] = {}
    for i, j in zip(rows, cols):
        if i < n_k and j < n_l and matrix[i][j] < c0:
            out[id(controls[i])] = labels[j]
    return out


def residual_pairing(
    controls: list[DOMNode],
    container: DOMNode,
    index: DocIndex,
    excluded: set[int],
    hints: dict[int, int],
    params: FormReadingParams,
    boxes: dict[int, Geometry] | None = None,
) -> _Residual:
    """Hungarian assignment over the residual, capped per section.

    ``boxes`` gives a stand-in box for a control a person cannot see but
    operates through a visible widget (the widget's box).
    """
    result = _Residual()
    proxies = boxes or {}

    def box(ctrl: DOMNode) -> Geometry | None:
        return proxies.get(id(ctrl), ctrl.geometry)

    located = [c for c in controls if box(c) is not None]
    if not located:
        return result
    blocks = [b for b in _text_blocks(container, excluded) if b.geometry is not None]
    em = params.em
    candidates: dict[int, list[tuple[float, DOMNode]]] = {}
    for ctrl in located:
        cbox = box(ctrl)
        assert cbox is not None
        scored: list[tuple[float, DOMNode]] = []
        checkable = bool(_check_kind(ctrl)) and id(ctrl) not in proxies
        for block in blocks:
            assert block.geometry is not None
            orient = _relation(block.geometry, cbox, ctrl.rtl, checkable, em)
            if orient is None:
                continue
            distance = _edge_distance(block.geometry, cbox)
            if distance > params.max_label_distance:
                continue
            cost = (
                distance / em
                + math.log1p(_tree_distance(block, ctrl, index))
                + 2.0 * orient
                + (2.0 if hints.get(id(block), id(ctrl)) != id(ctrl) else 0.0)
            )
            scored.append((cost, block))
        scored.sort(key=lambda pair: pair[0])
        candidates[id(ctrl)] = scored[: params.candidates_per_control]

    def position(ctrl: DOMNode) -> tuple[float, float]:
        g = box(ctrl)
        return (g.y, g.x) if g is not None else (0.0, 0.0)

    ordered = sorted(located, key=position)
    sections: list[list[DOMNode]] = []
    previous_bottom: float | None = None
    for ctrl in ordered:
        g = box(ctrl)
        assert g is not None
        top = g.y
        if previous_bottom is None or top - previous_bottom > params.section_gap:
            sections.append([])
        sections[-1].append(ctrl)
        bottom = g.y + g.height
        previous_bottom = bottom if previous_bottom is None else max(previous_bottom, bottom)

    for section in sections:
        kept: list[DOMNode] = []
        labels: set[int] = set()
        for ctrl in section:
            new = {id(lbl) for _c, lbl in candidates[id(ctrl)]} - labels
            if len(kept) + 1 + len(labels) + len(new) > params.residual_cap:
                result.truncated += 1
                continue
            kept.append(ctrl)
            labels |= new
        if not kept:
            continue
        result.sections += 1
        result.max_size = max(result.max_size, len(kept) + len(labels))
        result.assigned.update(_solve_section(kept, candidates, params))
    return result


def _hint_lines(controls: list[DOMNode], blocks: list[DOMNode], em: float) -> dict[int, int]:
    """For each text block directly below a control: that control's id."""
    hints: dict[int, int] = {}
    for block in blocks:
        g = block.geometry
        if g is None:
            continue
        best: tuple[float, int] | None = None
        for ctrl in controls:
            c = ctrl.geometry
            if c is None:
                continue
            gap = g.y - (c.y + c.height)
            overlap = g.x < c.x + c.width and g.x + g.width > c.x
            if -2.0 <= gap <= 1.0 * em and overlap and (best is None or gap < best[0]):
                best = (gap, id(ctrl))
        if best is not None:
            hints[id(block)] = best[1]
    return hints


# ── Groups ──────────────────────────────────────────────────────────────────


def _group_container(node: DOMNode, index: DocIndex) -> DOMNode | None:
    for ancestor in index.ancestors(node, limit=12):
        if ancestor.tag == "fieldset" or ancestor.get_attribute("role") in ("radiogroup", "group"):
            return ancestor
        if ancestor.tag == "form":
            return None
    return None


def find_groups(
    controls: list[DOMNode], index: DocIndex
) -> list[tuple[str, list[DOMNode], DOMNode | None]]:
    """Radio and checkbox groups: (kind, options in order, group container)."""
    keyed: dict[tuple, list[DOMNode]] = defaultdict(list)
    containers: dict[tuple, DOMNode | None] = {}
    loose: list[DOMNode] = []
    for ctrl in controls:
        kind = _check_kind(ctrl)
        if not kind:
            continue
        container = _group_container(ctrl, index)
        name = ctrl.get_attribute("name")
        if kind == "radio" and name:
            key: tuple = ("radio", name)
        elif container is not None:
            key = (kind, "container", id(container))
        elif name:
            key = (kind, name)
        else:
            loose.append(ctrl)
            continue
        keyed[key].append(ctrl)
        containers.setdefault(key, container)
    # Options left alone by name and container (Gem: each option its own
    # name, no fieldset) are grouped by the nearest wrapper they share with
    # another loose option of the same kind, at most four levels up.
    for key in [k for k, m in keyed.items() if len(m) == 1]:
        loose.append(keyed.pop(key)[0])
    loose_ids = {id(n) for n in loose}
    for ctrl in loose:
        kind = _check_kind(ctrl)
        for ancestor in index.ancestors(ctrl, limit=4):
            if any(
                n is not ctrl and id(n) in loose_ids and _check_kind(n) == kind
                for n in ancestor.iter_nodes()
            ):
                key = (kind, "wrapper", id(ancestor))
                keyed[key].append(ctrl)
                containers.setdefault(key, ancestor)
                break
    groups: list[tuple[str, list[DOMNode], DOMNode | None]] = []
    for key, members in keyed.items():
        if len(members) < 2:
            continue
        container = containers[key]
        if container is None:
            container = _common_ancestor(members, index)
        groups.append((key[0], members, container))
    return groups


def _common_ancestor(nodes: list[DOMNode], index: DocIndex) -> DOMNode | None:
    first = [nodes[0]] + list(index.ancestors(nodes[0]))
    for candidate in first[1:]:
        if all(candidate is n or any(a is candidate for a in index.ancestors(n)) for n in nodes[1:]):
            return candidate
    return None


def _option_text_blocks(controls: list[DOMNode], index: DocIndex) -> set[int]:
    """Ids of the elements whose own text sits beside a radio or checkbox."""
    out: set[int] = set()
    for ctrl in controls:
        if not _check_kind(ctrl):
            continue
        parent = index.parent.get(id(ctrl))
        if parent is None:
            continue
        out.add(id(parent))
        after = False
        for sibling in parent.children:
            if sibling is ctrl:
                after = True
            elif after and sibling.tag not in ("fieldset", "div", "ul", "ol"):
                out.add(id(sibling))
    return out


def _legend(container: DOMNode) -> DOMNode | None:
    for child in container.children:
        if child.tag == "legend":
            return child
    return None


def group_question(
    container: DOMNode | None,
    first_option: DOMNode,
    form_root: DOMNode,
    index: DocIndex,
    claimed: set[int],
    option_text: set[int],
) -> _Label:
    """The question of a group: legend, group name, then preceding text."""
    if container is not None:
        legend = _legend(container)
        if legend is not None:
            text = _clean_label(legend.display_name())
            if text:
                claimed.add(id(legend))
                return _Label(text, LabelSource.LEGEND, legend, _visible(legend))
        labelledby = container.get_attribute("aria-labelledby")
        if labelledby:
            text, nodes = _resolve_ids(index, labelledby)
            text = _clean_label(text)
            if text:
                for target in nodes:
                    claimed.add(id(target))
                return _Label(text, LabelSource.GROUP_LABELLEDBY, nodes[0], any(_visible(n) for n in nodes))
        aria = _clean_label(container.get_attribute("aria-label"))
        if aria:
            return _Label(aria, LabelSource.ARIA_LABEL)
        # The first heading or text inside the group, before its first option.
        first_at = index.order.get(id(first_option), 0)
        inside = [
            b for b in _text_blocks(container, claimed | option_text)
            if index.order.get(id(b), first_at) < first_at
        ]
        if inside:
            heading = min(inside, key=lambda b: index.order.get(id(b), 0))
            text = _clean_label(_node_text(heading))
            if text:
                claimed.add(id(heading))
                return _Label(text, LabelSource.GROUP_HEADING, heading, _visible(heading))
    # Nearest preceding heading, label or text block in document order. Text
    # that sits beside a radio or checkbox is an option's label, never a
    # question (option_text holds those blocks' ids).
    first_at = index.order.get(id(first_option), 0)
    best: tuple[int, DOMNode] | None = None
    for block in _text_blocks(form_root, claimed | option_text):
        at = index.order.get(id(block), -1)
        if at < first_at and (best is None or at > best[0]):
            best = (at, block)
    if best is not None:
        text = _clean_label(_node_text(best[1]))
        if text:
            claimed.add(id(best[1]))
            return _Label(text, LabelSource.PRECEDING_TEXT, best[1], _visible(best[1]))
    return _Label()


# ── Requiredness ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FormConventions:
    """Form-level facts requiredness reads: a legend, a convention."""

    asterisk_legend: bool = False
    all_required: bool = False
    optional_convention: bool = False


def form_conventions(container: DOMNode, labels: list[str]) -> FormConventions:
    legend = False
    all_required = False
    for node in container.iter_nodes():
        text = node.text
        if not text:
            continue
        if not legend and _LEGEND.search(text):
            legend = True
        if not all_required and _ALL_REQUIRED.search(text):
            all_required = True
        if legend and all_required:
            break
    marked_optional = sum(1 for t in labels if _OPTIONAL_WORD.search(t))
    return FormConventions(
        asterisk_legend=legend,
        all_required=all_required,
        optional_convention=bool(labels) and marked_optional > len(labels) / 2,
    )


def requiredness(
    controls: list[DOMNode], raw_label: str, conventions: FormConventions,
    group: DOMNode | None = None,
) -> tuple[str, tuple[str, ...]]:
    """Tri-state requiredness with the signals that decided it."""
    signals: list[str] = []
    if any(c.value_missing for c in controls):
        return REQUIRED, ("value-missing",)
    holders = list(controls) + ([group] if group is not None else [])
    native = any(any(k == "required" for k, _ in c.attributes) for c in holders)
    aria = any(c.get_attribute("aria-required").lower() == "true" for c in holders)
    score = 0.0
    if native or aria:
        score += 6.0
        signals.append("required-attribute" if native else "aria-required")
    red = (raw_label or "").endswith("!red")
    label_text = (raw_label or "")[:-4] if red else (raw_label or "")
    if _REQUIRED_WORD.search(label_text):
        score += 3.0
        signals.append("label-word-required")
    if _ASTERISK.search(label_text):
        score += 4.0 if conventions.asterisk_legend else 1.5
        signals.append("asterisk+legend" if conventions.asterisk_legend else "asterisk")
        if red:
            score += 2.0
            signals.append("red-marker")
    if _OPTIONAL_WORD.search(label_text):
        score -= 5.0
        signals.append("label-optional")
    if not signals:
        if conventions.all_required:
            score += 4.0
            signals.append("form-all-required")
        elif conventions.optional_convention:
            score += 2.5
            signals.append("optional-convention")
    if score >= 2.0:
        return REQUIRED, tuple(signals)
    if score <= -2.0:
        return OPTIONAL, tuple(signals)
    return UNKNOWN, tuple(signals)


# ── Trap decision ───────────────────────────────────────────────────────────


def name_tokens(node: DOMNode) -> set[str]:
    tokens: set[str] = set()
    for attr in ("name", "id"):
        value = node.get_attribute(attr).lower()
        tokens.update(t for t in _TOKEN_SPLIT.split(value) if t)
    return tokens


#: Hidden-in-place reasons: the control is hidden where it stands, which is
#: how custom widgets hide their native input. Moving a control off-screen
#: is not hiding in place.
_IN_PLACE = frozenset({"display-none", "opacity-zero", "zero-size", "visibility-hidden", "no-box"})
_WIDGET_ROLES = frozenset({"combobox", "listbox", "textbox", "button", "checkbox", "radio", "switch"})


def _on_screen(node: DOMNode) -> bool:
    g = node.geometry
    return g is not None and g.width * g.height > 0 and g.x + g.width >= -50 and g.y + g.height >= -50


def _backing_widget(node: DOMNode, reason: str, index: DocIndex | None) -> bool:
    """True when a hidden control is the native input behind a visible widget.

    Measured on the owner's captures (form-* folders): every ATS form hides
    its ``<input type=file>`` behind an "Upload" button, and custom checkbox,
    radio and select widgets hide the native control the same way. The
    shape: hidden in place, inside a visible container that shows the
    widget (text or a control a person operates). A trap's container is
    itself hidden or moved off-screen.
    """
    if index is None or reason not in _IN_PLACE:
        return False
    native = node.tag == "select" or _check_kind(node) != "" or (
        node.tag == "input" and node.get_attribute("type", "text").lower() == "file"
    )
    for level, ancestor in enumerate(index.ancestors(node, limit=3)):
        if not _on_screen(ancestor):
            return False
        seen = 0
        for item in ancestor.iter_nodes():
            seen += 1
            if seen > 200:
                break
            if item is node or not _on_screen(item):
                continue
            widget = (
                item.tag in ("button", "label") or item.get_attribute("role") in _WIDGET_ROLES
                or item.get_attribute("contenteditable").lower() == "true"
            )
            if widget or (native and item.text.strip() and level <= 1):
                return True
    return False


def trap_decision(
    node: DOMNode, label: _Label, params: FormReadingParams = DEFAULT_PARAMS,
    index: DocIndex | None = None,
) -> tuple[str, tuple[str, ...]]:
    """CT-ALG-014: TRAP only when hidden; CLEAR when labelled; else UNKNOWN."""
    if is_button(node):
        return CLEAR, ()
    reason = hidden_reason(node)
    evidence: list[str] = []
    logit = -4.0
    if reason:
        logit += 6.0
        evidence.append(f"hidden:{reason}")
        if _backing_widget(node, reason, index):
            logit -= 7.0
            evidence.append("backing-control")
    if node.aria_hidden:
        logit += 1.0
        evidence.append("aria-hidden")
    labelled = label.source != LabelSource.NONE
    if label.visible:
        logit -= 7.0
        evidence.append("visible-label")
    elif not labelled:
        logit += 1.5
        evidence.append("no-label")
    if node.get_attribute("tabindex").strip() == "-1":
        logit += 1.0
        evidence.append("tabindex-1")
        if node.get_attribute("autocomplete").lower() == "off":
            logit += 1.0
            evidence.append("autocomplete-off")
    if name_tokens(node) & _TRAP_TOKENS:
        logit += 1.5
        evidence.append("trap-token")
    threshold = math.log(params.trap_threshold / (1.0 - params.trap_threshold))
    if reason:
        # A visible label or a visible widget around the control is what a
        # person sees and operates: never a trap, whatever else is present.
        if label.visible or "backing-control" in evidence:
            return CLEAR, tuple(evidence)
        strong = {"trap-token", "autocomplete-off"} & set(evidence)
        if labelled and not strong:
            evidence.append("label-not-visible")
            return HIDDEN, tuple(evidence)
        return (TRAP if logit >= threshold else CLEAR), tuple(evidence)
    # A person can see it: never a trap. Labelled: fill. Unlabelled: UNKNOWN.
    return (CLEAR if labelled else UNKNOWN), tuple(evidence)


# ── Typing ──────────────────────────────────────────────────────────────────


def score_field_type(input_node: DOMNode, label_text: str) -> FieldType:
    """Semantic type by scoring (the classifier kept [WIRED], 06 section 4)."""
    scores: dict[FieldType, int] = defaultdict(int)
    type_attr = input_node.get_attribute("type", "").lower()
    name_attr = input_node.get_attribute("name", "").lower()
    id_attr = input_node.get_attribute("id", "").lower()
    placeholder = input_node.get_attribute("placeholder", "").lower()
    autocomplete = input_node.get_attribute("autocomplete", "").lower()
    combined = f"{label_text} {name_attr} {id_attr} {placeholder} {autocomplete}".lower()
    if type_attr == "email" or "email" in combined:
        scores[FieldType.EMAIL] += 20
    if "e-mail" in combined or "email" in name_attr:
        scores[FieldType.EMAIL] += 10
    if type_attr == "tel" or "phone" in combined or "mobile" in combined:
        scores[FieldType.TELEPHONE] += 20
    if "first" in combined and "name" in combined:
        scores[FieldType.FIRST_NAME] += 25
    if "last" in combined and "name" in combined:
        scores[FieldType.LAST_NAME] += 25
    if ("full" in combined or "your name" in combined) and "name" in combined:
        scores[FieldType.FULL_NAME] += 20
    if "address" in combined:
        scores[FieldType.STREET_ADDRESS] += 15
    if "city" in combined:
        scores[FieldType.CITY] += 20
    if "state" in combined or "province" in combined:
        scores[FieldType.STATE] += 20
    if "zip" in combined or "postal" in combined:
        scores[FieldType.ZIP_CODE] += 20
    if type_attr == "file":
        if "resume" in combined or "cv" in combined:
            scores[FieldType.RESUME_UPLOAD] += 30
        elif "cover" in combined:
            scores[FieldType.COVER_LETTER_UPLOAD] += 30
    if "linkedin" in combined:
        scores[FieldType.LINKEDIN_URL] += 25
    if "github" in combined:
        scores[FieldType.GITHUB_URL] += 25
    if "portfolio" in combined or "website" in combined:
        scores[FieldType.PORTFOLIO_URL] += 20
    if "authorized" in combined or "authorised" in combined or "eligibility" in combined:
        scores[FieldType.WORK_AUTHORIZATION] += 15
    if "sponsor" in combined:
        scores[FieldType.SPONSORSHIP] += 15
    if "gender" in combined:
        scores[FieldType.GENDER] += 15
    if "race" in combined or "ethnicity" in combined:
        scores[FieldType.RACE] += 15
    if "veteran" in combined:
        scores[FieldType.VETERAN] += 15
    if "disability" in combined:
        scores[FieldType.DISABILITY] += 15
    if input_node.tag == "select":
        scores[FieldType.SELECT] += 10
    if scores:
        return max(scores.items(), key=lambda x: x[1])[0]
    if type_attr == "email":
        return FieldType.EMAIL
    if type_attr == "tel":
        return FieldType.TELEPHONE
    if type_attr == "file":
        return FieldType.RESUME_UPLOAD
    return FieldType.TEXT




def infer_type(node: DOMNode, label_text: str, has_label: bool) -> FieldType:
    """Autofill token, then input type, then the scorer; UNKNOWN without evidence."""
    for token in node.get_attribute("autocomplete").lower().split():
        if token in _AUTOFILL:
            return _AUTOFILL[token]
    kind = _check_kind(node)
    if kind == "radio":
        return FieldType.RADIO
    if kind == "checkbox":
        return FieldType.CHECKBOX
    type_attr = node.get_attribute("type", "").lower()
    if node.tag == "input" and type_attr in _INPUT_TYPES:
        return _INPUT_TYPES[type_attr]
    scored = score_field_type(node, label_text)
    if scored is FieldType.TEXT and not has_label and not any(
        node.get_attribute(a) for a in ("name", "id", "placeholder", "title")
    ):
        return FieldType.UNKNOWN
    return scored


_TOPIC_WORDS: tuple[tuple[FieldType, re.Pattern[str]], ...] = (
    (FieldType.SPONSORSHIP, re.compile(r"\bsponsor(ship)?\b|\bvisa\b", re.I)),
    (FieldType.WORK_AUTHORIZATION, re.compile(
        r"\bauthori[sz](ed|ation)\b|\beligib(le|ility)\b|\bright to work\b", re.I)),
    (FieldType.VETERAN, re.compile(r"\bveteran\b", re.I)),
    (FieldType.DISABILITY, re.compile(r"\bdisabilit(y|ies)\b", re.I)),
    (FieldType.GENDER, re.compile(r"\bgender\b|\bsex\b", re.I)),
    (FieldType.RACE, re.compile(r"\brace\b|\bethnicity\b|\bhispanic\b", re.I)),
)


def topic_of(text: str) -> FieldType:
    """What a question is about, when its text says so (EEO, authorization).

    Whole words, first match in this order (sponsorship questions mention
    authorization too, so sponsorship is tested first).
    """
    for topic, pattern in _TOPIC_WORDS:
        if pattern.search(text or ""):
            return topic
    return FieldType.UNKNOWN


# ── One form ────────────────────────────────────────────────────────────────


def _description(node: DOMNode, index: DocIndex, hint: DOMNode | None) -> str:
    describedby = node.get_attribute("aria-describedby")
    if describedby:
        text, _nodes = _resolve_ids(index, describedby)
        if text:
            return text
    if hint is not None:
        return " ".join(_node_text(hint).split())
    return ""


def _options(node: DOMNode) -> list[str]:
    if node.tag != "select":
        return []
    out: list[str] = []
    for child in node.iter_nodes():
        if child.tag == "option":
            text = " ".join((child.subtree_text()[0] or child.text).split())
            if text:
                out.append(text)
    return out


def read_form(
    container: DOMNode,
    controls: list[DOMNode],
    index: DocIndex,
    params: FormReadingParams = DEFAULT_PARAMS,
) -> tuple[list[LabeledField], FormRecord]:
    """Read one form's controls into fields, with the form's record."""
    controls = sorted(controls, key=lambda c: index.order.get(id(c), 0))
    claimed: set[int] = set()
    labels: dict[int, _Label] = {}
    duplicate_ids = 0
    for ctrl in controls:
        ident = ctrl.get_attribute("id")
        if ident and len(index.ids.get(ident, ())) > 1:
            duplicate_ids += 1
        labels[id(ctrl)] = explicit_label(ctrl, index, claimed)

    groups = find_groups([c for c in controls if not is_button(c)], index)
    option_text = _option_text_blocks(controls, index)
    in_group: dict[int, int] = {}
    questions: list[_Label] = []
    for g, (_kind, members, group_node) in enumerate(groups):
        for member in members:
            in_group[id(member)] = g
        questions.append(
            group_question(group_node, members[0], container, index, claimed, option_text)
        )

    # Text that describes a control is never a label candidate.
    for ctrl in controls:
        describedby = ctrl.get_attribute("aria-describedby")
        if describedby:
            for ident in describedby.split():
                target = index.first_by_id(ident)
                if target is not None:
                    claimed.add(id(target))

    data_controls = [c for c in controls if not is_button(c)]
    blocks = [b for b in _text_blocks(container, claimed)]
    hints = _hint_lines(data_controls, blocks, params.em)
    unlabeled = [
        c for c in data_controls
        if labels[id(c)].source == LabelSource.NONE and _visible(c) and not hidden_reason(c)
    ]
    # A hidden native input behind a visible widget (Ashby's Yes/No buttons
    # over a hidden checkbox) is labelled where the widget stands.
    widget_boxes: dict[int, Geometry] = {}
    for ctrl in data_controls:
        reason = hidden_reason(ctrl)
        if (
            labels[id(ctrl)].source == LabelSource.NONE and reason
            and id(ctrl) not in in_group and _backing_widget(ctrl, reason, index)
        ):
            for ancestor in index.ancestors(ctrl, limit=3):
                if _on_screen(ancestor) and ancestor.geometry is not None:
                    widget_boxes[id(ctrl)] = ancestor.geometry
                    unlabeled.append(ctrl)
                    break
    residual = residual_pairing(
        unlabeled, container, index, set(claimed), hints, params, widget_boxes
    )
    for ctrl in unlabeled:
        block = residual.assigned.get(id(ctrl))
        if block is not None:
            labels[id(ctrl)] = _Label(_clean_label(_node_text(block)), LabelSource.GEOMETRY, block, True)
            claimed.add(id(block))
    for ctrl in data_controls:
        if labels[id(ctrl)].source == LabelSource.NONE:
            title = _clean_label(ctrl.get_attribute("title"))
            placeholder = _clean_label(ctrl.get_attribute("placeholder"))
            if title:
                labels[id(ctrl)] = _Label(title, LabelSource.TITLE)
            elif placeholder:
                labels[id(ctrl)] = _Label(placeholder, LabelSource.PLACEHOLDER)

    hint_of: dict[int, DOMNode] = {}
    for block in blocks:
        owner = hints.get(id(block))
        if owner is not None and id(block) not in claimed and owner not in hint_of:
            hint_of[owner] = block

    raw_texts = [_raw_label(labels[id(c)]) for c in data_controls]
    conventions = form_conventions(container, raw_texts)

    fields: list[LabeledField] = []
    emitted_groups: set[int] = set()
    for ctrl in controls:
        member_of = in_group.get(id(ctrl))
        if member_of is not None:
            if member_of in emitted_groups:
                continue
            emitted_groups.add(member_of)
            fields.append(
                _group_field(
                    groups[member_of], questions[member_of], labels, conventions,
                    index, hint_of, params,
                )
            )
            continue
        fields.append(_single_field(ctrl, labels[id(ctrl)], conventions, index, hint_of, params))

    record = _record(fields, controls, duplicate_ids, residual)
    return fields, record


def _raw_label(label: _Label) -> str:
    """The label text as written, markers included (for requiredness).

    A marker drawn by CSS is appended, and a red marker is spelled ``*!red``
    so requiredness can weigh the colour (06 section 5).
    """
    if label.node is None:
        return label.text
    text = " ".join(label.node.display_name().split()) or label.text
    markers = [n for n in label.node.iter_nodes() if n.marker][:4]
    if markers and not text.rstrip().endswith("*"):
        text += " *"
    if any(n.marker_red for n in markers):
        text += "!red"
    return text


def _single_field(
    ctrl: DOMNode, label: _Label, conventions: FormConventions, index: DocIndex,
    hint_of: dict[int, DOMNode], params: FormReadingParams,
) -> LabeledField:
    button = is_button(ctrl)
    has_label = label.source != LabelSource.NONE
    state, signals = (UNKNOWN, ()) if button else requiredness([ctrl], _raw_label(label), conventions)
    verdict, evidence = trap_decision(ctrl, label, params, index)
    inferred = infer_type(ctrl, label.text, has_label)
    topic = topic_of(label.text) if inferred is FieldType.CHECKBOX else FieldType.UNKNOWN
    return LabeledField(
        input_node=ctrl,
        label_node=label.node,
        label_text=label.text,
        inferred_type=inferred,
        is_required=state == REQUIRED,
        is_honeypot=verdict == TRAP,
        options=_options(ctrl),
        label_source=label.source,
        description="" if button else _description(ctrl, index, hint_of.get(id(ctrl))),
        requiredness=state,
        required_signals=signals,
        hidden_reason=hidden_reason(ctrl),
        trap_verdict=verdict,
        trap_evidence=evidence,
        topic=topic,
    )


def _group_field(
    group: tuple[str, list[DOMNode], DOMNode | None],
    question: _Label,
    labels: dict[int, _Label],
    conventions: FormConventions,
    index: DocIndex,
    hint_of: dict[int, DOMNode],
    params: FormReadingParams,
) -> LabeledField:
    kind, members, container = group
    option_labels = [labels[id(m)].text for m in members]
    state, signals = requiredness(members, _raw_label(question), conventions, container)
    # The group is a trap only if every option is (a person sees none).
    decisions = [trap_decision(m, labels[id(m)], params, index) for m in members]
    verdicts = {d[0] for d in decisions}
    if verdicts == {TRAP}:
        verdict = TRAP
    elif verdicts <= {TRAP, HIDDEN}:
        verdict = HIDDEN
    elif UNKNOWN in verdicts and question.source == LabelSource.NONE:
        verdict = UNKNOWN
    else:
        verdict = CLEAR
    evidence = tuple(sorted({e for d in decisions for e in d[1]}))
    hidden = [hidden_reason(m) for m in members]
    first = members[0]
    describedby = container.get_attribute("aria-describedby") if container is not None else ""
    description = _resolve_ids(index, describedby)[0] if describedby else ""
    return LabeledField(
        input_node=first,
        label_node=question.node,
        label_text=question.text,
        inferred_type=FieldType.RADIO if kind == "radio" else FieldType.CHECKBOX,
        is_required=state == REQUIRED,
        is_honeypot=verdict == TRAP,
        options=option_labels,
        label_source=question.source,
        description=description,
        requiredness=state,
        required_signals=signals,
        hidden_reason=hidden[0] if all(hidden) else "",
        trap_verdict=verdict,
        trap_evidence=evidence,
        option_nodes=tuple(members),
        topic=topic_of(question.text),
    )


def _record(
    fields: list[LabeledField], controls: list[DOMNode], duplicate_ids: int, residual: _Residual
) -> FormRecord:
    data = [f for f in fields if not is_button(f.input_node)]
    sources = Counter(f.label_source for f in data)
    evidence = Counter(e.split(":", 1)[0] if e.startswith("hidden:") else e
                       for f in data if f.trap_verdict == TRAP for e in f.trap_evidence)
    return FormRecord(
        controls=len(controls),
        fields=len(data),
        groups=sum(1 for f in data if f.is_group),
        group_options=sum(len(f.option_nodes) for f in data),
        unlabeled=sources.get(LabelSource.NONE, 0),
        hidden=sum(1 for f in data if f.is_hidden),
        traps=sum(1 for f in data if f.trap_verdict == TRAP),
        hidden_labelled=sum(1 for f in data if f.trap_verdict == HIDDEN),
        trap_unknown=sum(1 for f in data if f.trap_verdict == UNKNOWN),
        required=sum(1 for f in data if f.requiredness == REQUIRED),
        optional=sum(1 for f in data if f.requiredness == OPTIONAL),
        required_unknown=sum(1 for f in data if f.requiredness == UNKNOWN),
        described=sum(1 for f in data if f.description),
        duplicate_ids=duplicate_ids,
        residual_size=residual.max_size,
        residual_sections=residual.sections,
        pairing_truncated=residual.truncated,
        label_sources=tuple(sorted(sources.items())),
        trap_evidence=tuple(sorted(evidence.items())),
    )
