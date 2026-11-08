"""Reading a form's fields (CT-T-011 pairing, 012 typing, 013 required, ALG-014 traps).

One finding per *question*: a single control, or a radio/checkbox group.

**Pairing ladder (CT-ALG-008)**, constraints before costs: ``label[for]``
(first element with that id in the label's scope), a wrapping ``label`` with
exactly one labelable control, ``aria-labelledby`` (its targets are claimed),
``aria-label``, the group's ``legend`` / group name, then a residual
assignment, and ``title``/``placeholder`` last. The order of the last two
follows AA's pass-4 reader (a placeholder vanishes when typed; a visible
label is what a person reads), not 06 s4, which put them before the
residual: recorded as a blueprint correction. Without the layout capability the residual cost is
structural: ``c = beta·log(1+d_tree) + gamma·[label after control]``, padded
with dummies at ``c0`` (pagecomp.hungarian), at most 12 controls by 8
nearest blocks per solve (m <= 108 <= 120, 05 s14). Margin = second-best
cost minus chosen.

**Typing (CT-ALG-009)**: HTML autofill tokens first, then input type, then
whole-token lexicon on name/id/label (evidence, English in v0.1).

**Requiredness (CT-ALG-010)** as log-odds ``L = b0 + Σ w_i`` with
``b0`` an explicit prior (correction: the blueprint's score had none, so
its thresholds silently assumed a 50% base rate): native/aria required +6
(one correlated group), the word "required" +3, an asterisk +1.5 (+4 with a
legend defining it), "(optional)" -5, the "most fields say optional"
convention +2.5; and a second convention the blueprint missed: when a form
marks *some* labels with "*" and not others, "*" is the form's required
marker (+4, as with a legend) and an unmarked field leans optional (-2.5). REQUIRED at ``L >= 2``, OPTIONAL at ``L <= -2``, else
UNKNOWN — and UNKNOWN is never treated as optional.

**Traps (CT-ALG-014)**: ``p = σ(-3 + 4·hidden + 1.5·unlabelled +
1·(tabindex=-1 & autocomplete=off) + 1·trap-token)``, trap iff hidden and
``p >= θ = C_skip/(C_skip+C_trap) = 1/11`` (``C_trap = 10·C_skip``, a
safety parameter). Visible and labelled → FILL; hidden but labelled like a
real field → HIDDEN (decide again on the next observation); visible and
unlabelled → UNKNOWN (never filled); disabled/readonly → SKIP.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pagecomp import hungarian
from pagecomp.doc import ELEMENT, TEXT, Doc
from pagecomp.params import ParamSpec
from pagecomp.registry import ToolSpec
from pagecomp.results import Evidence, Ok
from pagecomp.text import collapse, token_set
from pagecomp.tools.forms import Control, Forms

REQUIRED, OPTIONAL, UNKNOWN = "REQUIRED", "OPTIONAL", "UNKNOWN"
FILL, TRAP, HIDDEN, UNLABELLED, SKIP = "FILL", "TRAP", "HIDDEN", "UNKNOWN", "SKIP"

_LABELABLE = frozenset({"input", "select", "textarea", "button", "meter", "output", "progress"})
_NO_BLOCK = frozenset({"option", "button", "script", "style", "select", "textarea", "template", "svg"})
_STARS = "*✱＊∗"
_ASTERISK = re.compile(r"(^\s*[" + _STARS + r"])|([" + _STARS + r"]\s*:?\s*$)")
_REQ_WORD = re.compile(r"(?<!not )\brequired\b|\bmandatory\b|\bpflichtfeld\b|\bobligatoire\b", re.I)
_OPT_WORD = re.compile(r"\(\s*optional\s*\)|\boptional\b|\bfacultatif\b", re.I)
_LEGEND = re.compile(r"[" + _STARS + r"]\s*(=|indicates|denotes|means|marks)?\s*(a\s+)?(required|mandatory)", re.I)
_LEAVE_BLANK = re.compile(r"\b(leave|keep)\s+(this\s+|it\s+)?(field\s+|input\s+)?(blank|empty)\b|"
                         r"\bdo\s+not\s+(fill|complete|enter)\b|\bif\s+you\s+are\s+(a\s+)?human\b", re.I)
_ALL_REQUIRED = re.compile(r"\b(fields|questions)\s+(marked|with)\b.*\brequired\b|\ball\s+fields\s+are\s+(required|mandatory)\b", re.I)
_TRAP_TOKENS = frozenset({"honeypot", "hpot", "botcheck", "bot", "trap", "leaveblank", "nospam", "antispam"})

#: HTML autofill field names (HTML Living Standard 4.10.18.7.1) -> canonical type.
AUTOFILL = {
    "given-name": "first_name", "family-name": "last_name", "name": "full_name",
    "additional-name": "middle_name", "email": "email", "tel": "phone", "tel-national": "phone",
    "street-address": "address", "address-line1": "address", "address-line2": "address2",
    "address-level2": "city", "address-level1": "region", "postal-code": "postal_code",
    "country": "country", "country-name": "country", "organization": "employer",
    "organization-title": "job_title", "url": "website", "bday": "birth_date",
    "sex": "gender", "username": "username", "new-password": "password",
    "current-password": "password", "one-time-code": "otp",
}
INPUT_TYPES = {"email": "email", "tel": "phone", "url": "website", "file": "file", "date": "date",
               "password": "password", "number": "number", "checkbox": "checkbox", "radio": "radio"}
#: Whole-token lexicon, most specific first. Evidence, not structure.
LEXICON: tuple[tuple[str, frozenset[str]], ...] = (
    ("resume", frozenset({"resume", "cv", "résumé"})),
    ("cover_letter", frozenset({"cover", "coverletter", "motivation"})),
    ("first_name", frozenset({"first", "firstname", "given", "fname", "forename"})),
    ("last_name", frozenset({"last", "lastname", "surname", "family", "lname"})),
    ("full_name", frozenset({"fullname", "name"})),
    ("email", frozenset({"email", "e-mail", "mail"})),
    ("phone", frozenset({"phone", "telephone", "mobile", "tel", "cell"})),
    ("linkedin", frozenset({"linkedin"})),
    ("github", frozenset({"github"})),
    ("website", frozenset({"website", "portfolio", "url", "homepage", "site"})),
    ("postal_code", frozenset({"zip", "zipcode", "postal", "postcode"})),
    ("city", frozenset({"city", "town"})),
    ("region", frozenset({"state", "province", "region"})),
    ("country", frozenset({"country"})),
    ("address", frozenset({"address", "street"})),
    ("location", frozenset({"location"})),
    ("salary", frozenset({"salary", "compensation", "pay"})),
    ("start_date", frozenset({"start", "availability", "available", "notice"})),
    ("work_authorization", frozenset({"authorized", "authorised", "authorization", "eligible", "eligibility"})),
    ("sponsorship", frozenset({"sponsorship", "sponsor", "visa"})),
    ("gender", frozenset({"gender", "sex"})),
    ("ethnicity", frozenset({"race", "ethnicity", "hispanic", "latino"})),
    ("veteran", frozenset({"veteran", "military"})),
    ("disability", frozenset({"disability", "disabled"})),
    ("pronouns", frozenset({"pronouns", "pronoun"})),
    ("school", frozenset({"school", "university", "college", "institution"})),
    ("degree", frozenset({"degree", "education"})),
    ("employer", frozenset({"employer", "company", "organization"})),
    ("referral", frozenset({"referral", "referred", "hear", "source"})),
    ("job_title", frozenset({"title", "position", "role"})),
)
#: Types a long question may carry (the rest are short field names).
QUESTION_TYPES = frozenset({"work_authorization", "sponsorship", "gender", "ethnicity", "veteran",
                            "disability", "pronouns", "salary", "start_date", "referral",
                            "relocation", "cover_letter", "resume", "linkedin", "website", "github"})
#: Canonical types whose answers must come from the user's explicit answer only.
SENSITIVE = frozenset({"gender", "ethnicity", "veteran", "disability", "pronouns",
                       "work_authorization", "sponsorship", "birth_date"})


@dataclass(frozen=True)
class FieldReading:
    controls: tuple[int, ...]     # indexes into Forms.controls
    form: int
    kind: str                     # "single" | "radio" | "checkbox"
    label: str
    label_source: str
    label_margin: float | None
    field_type: str
    type_source: str
    required: str
    required_logodds: float
    decision: str
    options: tuple[str, ...]
    description: str
    sensitive: bool
    hidden: str
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class FormReading:
    fields: tuple[FieldReading, ...]
    legend_defines_asterisk: tuple[int, ...]   # per form: 1 when a legend defines "*"


def _label_index(doc: Doc, forms: Forms) -> tuple[dict[int, int], dict[int, int]]:
    by_node = {c.node: k for k, c in enumerate(forms.controls)}
    label_for: dict[int, int] = {}
    labels_count: dict[int, int] = {}
    for lab in doc.elements("label"):
        f = doc.attr(lab, "for")
        if not f:
            continue
        tgt = doc.by_id(doc.scope[lab], f)
        if tgt in by_node:
            labels_count[tgt] = labels_count.get(tgt, 0) + 1
            label_for.setdefault(tgt, lab)
    return label_for, labels_count


def _label_text(doc: Doc, lab: int) -> str:
    """Label text without the text of controls inside it (select options)."""
    parts = []
    j, stop = lab + 1, doc.end[lab]
    while j < stop:
        if doc.kind[j] == ELEMENT and doc.tag_name(j) in ("select", "option", "textarea", "script", "style"):
            j = doc.end[j]
            continue
        if doc.kind[j] == TEXT:
            parts.append(doc.own_text(j))
        elif doc.kind[j] == ELEMENT and doc.tag_name(j) not in ("span", "b", "i", "em", "strong", "a", "abbr"):
            parts.append(" ")
        j += 1
    return collapse("".join(parts))


def _wrapping_label(doc: Doc, node: int) -> int:
    for a in doc.ancestors(node, 8):
        if doc.kind[a] != ELEMENT:
            return -1
        if doc.tag_name(a) == "label":
            inner = sum(1 for x in range(a + 1, doc.end[a])
                        if doc.kind[x] == ELEMENT and doc.tag_name(x) in _LABELABLE
                        and (doc.tag_name(x) != "input" or (doc.attr(x, "type") or "").lower() != "hidden"))
            return a if inner == 1 else -1
    return -1


def _blocks(doc: Doc, root: int, vis: Any, claimed: set[int]) -> list[int]:
    out = []
    j, stop = root, doc.end[root]
    while j < stop:
        if doc.kind[j] == ELEMENT:
            tag = doc.tag_name(j)
            if tag in _NO_BLOCK or (vis is not None and vis.reason[j]) or j in claimed:
                j = doc.end[j]
                continue
            own = " ".join(doc.own_text(c) for c in doc.children(j) if doc.kind[c] == TEXT).strip()
            if own and not _LEGEND.search(own) and not _ALL_REQUIRED.search(own):
                out.append(j)   # a form's legend sentence is never a field's label
        j += 1
    return out


def _tree_distance(doc: Doc, a: int, b: int) -> int:
    da, db = doc.depth[a], doc.depth[b]
    x, y, d = a, b, 0
    while da > db:
        x, da, d = doc.parent[x], da - 1, d + 1
    while db > da:
        y, db, d = doc.parent[y], db - 1, d + 1
    while x != y and x >= 0 and y >= 0:
        x, y, d = doc.parent[x], doc.parent[y], d + 2
    return d


def field_type(c: Control, label: str) -> tuple[str, str]:
    for tok in c.autocomplete.split():
        if tok in AUTOFILL:
            return AUTOFILL[tok], f"autocomplete={tok}"
    words = token_set(f"{label} {c.name.replace('_', ' ')} {c.id.replace('_', ' ')}")
    # A long label is a question, not a field name: "Please list the names of
    # any friends, family or ..." must not read as last_name via "family".
    question = len(token_set(label)) > 6
    if c.type == "file":
        for canon in ("resume", "cover_letter"):
            if words & dict(LEXICON)[canon]:
                return canon, "type=file+lexicon(en)"
    if c.type in INPUT_TYPES and c.type not in ("checkbox", "radio"):
        return INPUT_TYPES[c.type], f"type={c.type}"
    for canon, lex in LEXICON:
        if question and canon not in QUESTION_TYPES:
            continue
        if words & lex:
            return canon, "lexicon(en)" + ("+question" if question else "")
    if c.type in ("select", "role:combobox", "role:listbox"):
        return "choice", f"type={c.type}"
    if c.type in ("radio", "checkbox"):
        return c.type, f"type={c.type}"
    return "text", "default"


def requiredness(native: bool, label: str, legend_defined: bool, optional_convention: bool,
                 p: Mapping[str, Any], star_convention: bool = False) -> tuple[str, float, list[str]]:
    logit = float(p["prior_logodds"])
    ev: list[str] = []
    if native:
        logit += float(p["w_native"])
        ev.append("native-required")
    if _REQ_WORD.search(label):
        logit += float(p["w_word"])
        ev.append("word-required")
    star = bool(_ASTERISK.search(label))
    if star:
        defined = legend_defined or star_convention
        logit += float(p["w_star_legend"] if defined else p["w_star"])
        ev.append("asterisk" + ("+legend" if legend_defined else ("+convention" if star_convention else "")))
    if _OPT_WORD.search(label):
        logit += float(p["w_optional"])
        ev.append("word-optional")
    elif optional_convention and not native and not ev:
        logit += float(p["w_convention"])
        ev.append("optional-convention")
    elif star_convention and not star and not native and not ev:
        # The form marks required fields with "*" and this one is unmarked.
        logit += float(p["w_unstarred"])
        ev.append("unstarred-in-star-form")
    hi, lo = float(p["required_at"]), float(p["optional_at"])
    state = REQUIRED if logit >= hi else (OPTIONAL if logit <= lo else UNKNOWN)
    return state, round(logit, 6), ev


def trap_decision(c: Control, labelled: bool, doc: Doc, p: Mapping[str, Any],
                  label: str = "") -> tuple[str, float]:
    if c.disabled or c.readonly:
        return SKIP, 0.0
    if "captcha" in f"{c.name} {c.id}".lower():
        return SKIP, 0.0          # a challenge widget's response field: never ours to fill
    if label and _LEAVE_BLANK.search(label):
        # The label tells a person to leave it empty: leaving it empty is right
        # whether or not a person can see it.
        return TRAP, 1.0
    hidden = bool(c.hidden) and c.type != "hidden"
    toks = token_set(f"{c.name} {c.id}".replace("_", " ").replace("-", " "))
    f3 = (doc.attr(c.node, "tabindex") == "-1") and c.autocomplete == "off"
    z = -3.0 + (4.0 if hidden else 0.0) + (0.0 if labelled else 1.5) + (1.0 if f3 else 0.0) \
        + (1.0 if toks & _TRAP_TOKENS else 0.0)
    pt = 1.0 / (1.0 + math.exp(-z))
    theta = float(p["c_skip"]) / (float(p["c_skip"]) + float(p["c_trap"]))
    if c.type == "hidden":
        return SKIP, round(pt, 6)
    if hidden and c.type == "file" and not (toks & _TRAP_TOKENS):
        # The native file input hidden behind an "Attach"/"Upload" widget is
        # how most ATS forms take a résumé; files are set on the input, not
        # typed by a person, and no honeypot is a file input.
        return FILL, round(pt, 6)
    if hidden:
        if labelled and not (toks & _TRAP_TOKENS):
            return HIDDEN, round(pt, 6)
        return (TRAP if pt >= theta else HIDDEN), round(pt, 6)
    if not labelled:
        return UNLABELLED, round(pt, 6)
    return FILL, round(pt, 6)


def read_fields(doc: Doc, forms: Forms, vis: Any, p: Mapping[str, Any], tick: Any) -> FormReading:
    label_for, label_count = _label_index(doc, forms)
    claimed: set[int] = set()
    names: dict[int, tuple[str, str, float | None]] = {}
    # Rungs 1-4 and 6: constraints.
    for k, c in enumerate(forms.controls):
        tick(4)
        node = c.node
        lab = label_for.get(node, -1)
        if lab >= 0:
            names[k] = (_label_text(doc, lab), "label-for" + ("(dup)" if label_count.get(node, 0) > 1 else ""), None)
            claimed.add(lab)
            continue
        wrap = _wrapping_label(doc, node)
        if wrap >= 0:
            names[k] = (_label_text(doc, wrap), "wrapping-label", None)
            claimed.add(wrap)
            continue
        t = doc.idref_text(node, "aria-labelledby")
        if t:
            names[k] = (t, "aria-labelledby", None)
            for ref in (doc.attr(node, "aria-labelledby") or "").split():
                j = doc.by_id(doc.scope[node], ref)
                if j >= 0:
                    claimed.add(j)
            continue
        t = collapse(doc.attr(node, "aria-label") or "")
        if t:
            names[k] = (t, "aria-label", None)
            continue
    # Rung 7: residual assignment for unlabelled, visible, non-group controls.
    pending = [k for k, c in enumerate(forms.controls)
               if k not in names and c.type not in ("hidden", "radio", "checkbox") and not c.hidden]
    roots = {f: info.root for f, info in enumerate(forms.forms)}
    block_cache: dict[int, list[int]] = {}
    for start in range(0, len(pending), 12):
        chunk = pending[start:start + 12]
        cand: list[int] = []
        per: dict[int, list[int]] = {}
        for k in chunk:
            c = forms.controls[k]
            root = roots.get(c.form, 0)
            if root not in block_cache:
                block_cache[root] = _blocks(doc, root, vis, claimed)
                tick(doc.size(root))
            blocks = block_cache[root]
            near = sorted(blocks, key=lambda b: (_tree_distance(doc, b, c.node), abs(b - c.node)))[:8]
            tick(len(blocks))
            per[k] = near
            for b in near:
                if b not in cand:
                    cand.append(b)
        if not cand:
            continue
        beta, gamma, c0 = float(p["beta"]), float(p["gamma_after"]), float(p["c0"])
        big = c0 * 50
        cost = []
        for k in chunk:
            node = forms.controls[k].node
            row = []
            for b in cand:
                if b not in per[k]:
                    row.append(big)
                    continue
                # Pre-order: a block after the control cannot be its ancestor.
                after = 1.0 if b > node else 0.0
                row.append(beta * math.log1p(_tree_distance(doc, b, node)) + gamma * after)
            cost.append(row)
        tick(len(cost) * len(cand) * (len(cost) + len(cand)))
        choice = hungarian.assign_partial(cost, c0)
        for r, k in enumerate(chunk):
            col = choice[r]
            if col >= 0:
                srt = sorted(cost[r])
                margin = (srt[1] - cost[r][col]) if len(srt) > 1 else None
                names[k] = (doc.text_content(cand[col], 200, visual=True)[0], "residual-tree", margin)
    # Weak rung 6 for whatever is still unnamed.
    for k, c in enumerate(forms.controls):
        if k in names:
            continue
        t = collapse(doc.attr(c.node, "title") or doc.attr(c.node, "placeholder") or "")
        if t:
            names[k] = (t, "title" if doc.attr(c.node, "title") else "placeholder", None)
    # Group questions first: they count toward the form's conventions.
    group_q = {gi: _group_question(doc, [forms.controls[m].node for m in g.controls])
               for gi, g in enumerate(forms.groups)}
    # Form conventions.
    legend = []
    optional_conv = []
    star_conv: list[bool] = []
    for f, info in enumerate(forms.forms):
        text = doc.text_content(info.root, 20_000)[0]
        legend.append(1 if _LEGEND.search(text) else 0)
        grouped_here = {m for g in forms.groups if g.form == f for m in g.controls}
        labels = [names[k][0] for k in info.controls if k in names and k not in grouped_here]
        labels += [group_q[gi][0] for gi, g in enumerate(forms.groups) if g.form == f and group_q[gi][0]]
        opt = sum(1 for t in labels if _OPT_WORD.search(t))
        optional_conv.append(bool(labels) and opt > len(labels) / 2)
        stars = sum(1 for t in labels if _ASTERISK.search(t))
        # "*" discriminates when some labels carry it and some do not.
        star_conv.append(stars >= 2 and stars < len(labels))
    out: list[FieldReading] = []
    grouped: set[int] = set()
    for gi, g in enumerate(forms.groups):
        members = list(g.controls)
        grouped.update(members)
        first = forms.controls[members[0]]
        question, source = group_q[gi]
        opts = tuple(names.get(m, ("", "", None))[0] or (doc.attr(forms.controls[m].node, "value") or "")
                     for m in members)
        if g.kind == "checkbox" and len(members) == 1 and not question:
            question, source = names.get(members[0], ("", "none", None))[:2]
        native = any(forms.controls[m].native_required or forms.controls[m].aria_required for m in members)
        req, lo, rev = requiredness(native, question, bool(legend[g.form]), optional_conv[g.form], p,
                                    star_conv[g.form])
        ftype, tsrc = field_type(first, question)
        decisions = [trap_decision(forms.controls[m], True, doc, p)[0] for m in members]
        decision = FILL if FILL in decisions else (decisions[0] if decisions else UNLABELLED)
        if not question and decision == FILL:
            decision = UNLABELLED
        out.append(FieldReading(tuple(members), g.form, g.kind, question, source, None, ftype, tsrc,
                                req, lo, decision, opts, "", ftype in SENSITIVE,
                                first.hidden, tuple(rev)))
    for k, c in enumerate(forms.controls):
        if k in grouped:
            continue
        label, source, margin = names.get(k, ("", "none", None))
        native = c.native_required or c.aria_required
        req, lo, rev = requiredness(native, label, bool(legend[c.form]), optional_conv[c.form], p,
                                    star_conv[c.form])
        ftype, tsrc = field_type(c, label)
        decision, _pt = trap_decision(c, bool(label), doc, p, label)
        desc = doc.idref_text(c.node, "aria-describedby", 200)
        out.append(FieldReading((k,), c.form, "single", label, source, margin, ftype, tsrc, req, lo,
                                decision, c.options, desc, ftype in SENSITIVE, c.hidden, tuple(rev)))
    out.sort(key=lambda f: forms.controls[f.controls[0]].node)
    return FormReading(tuple(out), tuple(legend))


def _group_question(doc: Doc, nodes: list[int]) -> tuple[str, str]:
    anc = nodes[0]
    for x in nodes[1:]:
        while anc > 0 and not doc.is_ancestor(anc, x):
            anc = doc.parent[anc]
    for a in [anc, *doc.ancestors(anc, 6)]:
        if doc.kind[a] != ELEMENT:
            break
        tag = doc.tag_name(a)
        if tag == "fieldset":
            for c in doc.children(a):
                if doc.kind[c] == ELEMENT and doc.tag_name(c) == "legend":
                    return doc.text_content(c, 300, visual=True)[0], "legend"
        role = (doc.attr(a, "role") or "").lower()
        if role in ("radiogroup", "group"):
            t = doc.idref_text(a, "aria-labelledby", 300) or collapse(doc.attr(a, "aria-label") or "")
            if t:
                return t, "group-name"
    # nearest preceding text block outside the options
    j = nodes[0] - 1
    stop = max(0, nodes[0] - 400)
    while j > stop:
        if doc.kind[j] == TEXT and doc.own_text(j).strip() and not doc.is_ancestor(doc.parent[j], nodes[0]):
            p = doc.parent[j]
            if doc.tag_name(p) not in ("option", "script", "style"):
                return doc.text_content(p, 300, visual=True)[0], "preceding-text"
        j -= 1
    return "", "none"


def _run(q: Any, params: Mapping[str, Any]) -> Ok[FormReading]:
    forms = q.need_ok("forms")
    vis = q.maybe("visibility")
    reading = read_fields(q.doc, forms, vis, params, q.tick)
    ev: tuple[Evidence, ...] = ()
    if "SNAPSHOT_LAYOUT" not in q.obs.capabilities:
        ev = (Evidence("no-layout", "residual pairing by tree distance; geometry unavailable"),)
    return Ok(reading, evidence=ev)


TOOL = ToolSpec(
    id="formread", ct_id="CT-T-011..013", version="0.1.0", run=_run, needs=("forms", "visibility"),
    params=(
        ParamSpec("beta", 1.0, 0.0, 10.0, doc="tree-distance weight in residual cost"),
        ParamSpec("gamma_after", 2.0, 0.0, 10.0, doc="penalty: text after the control is help text"),
        ParamSpec("c0", 2.5, 0.1, 50.0, doc="dummy cost: 'no label' beats a worse label"),
        ParamSpec("prior_logodds", 0.0, -5.0, 5.0, doc="b0: base-rate prior of required"),
        ParamSpec("w_native", 6.0), ParamSpec("w_word", 3.0), ParamSpec("w_star", 1.5),
        ParamSpec("w_star_legend", 4.0), ParamSpec("w_optional", -5.0), ParamSpec("w_convention", 2.5),
        ParamSpec("w_unstarred", -2.5, -10.0, 0.0, doc="unmarked field in a form that marks required with *"),
        ParamSpec("required_at", 2.0), ParamSpec("optional_at", -2.0),
        ParamSpec("c_skip", 1.0, 0.01, 100.0, safety=True, doc="cost of skipping a real field"),
        ParamSpec("c_trap", 10.0, 0.01, 1000.0, safety=True, doc="cost of filling a trap"),
    ),
    summary="labels, types, requiredness and fill decisions per question",
)
