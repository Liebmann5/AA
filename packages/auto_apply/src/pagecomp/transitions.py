"""Transitions (S5; CT-T-016, CT-ALG-012, 016, 017, 024, 025).

Pure: no clock, no browser. Time arrives as numbers from the caller; window
facts arrive as values. Every loop is bounded by a cap and every cap that
fires gives a typed result.

* ``node_keys`` / ``diff``: DocDiff by stable keys (06 s8, ALG-017), never by
  node index. Regenerated keys over-report, which is the safe direction.
* ``Settler``: K quiet reads within ``T_max`` (ALG-016), time injected.
* ``ConditionalLoop``: BLUEPRINT s8 item 10, fixpoint over question keys.
* ``map_errors``: BLUEPRINT s8 item 11, the ALG-012 ladder then
  generalisation by skeleton similarity from the first mapped error.
* ``classify_window`` / ``WindowSet``: ALG-025 window set, cap 4 per action.
* ``PauseContext`` / ``resume``: ALG-024.
"""

from __future__ import annotations

import urllib.parse
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pagecomp.doc import ELEMENT, FRAME, ROOT, SHADOW, TEXT, Doc
from pagecomp.results import Stale, Timeout
from pagecomp.text import tokens

# ---------------------------------------------------------------------------
# DocDiff
# ---------------------------------------------------------------------------

NodeKey = tuple[Any, ...]


def _ident(doc: Doc, i: int) -> str:
    k = doc.kind[i]
    if k == TEXT:
        return "#text"
    if k == SHADOW:
        return "#shadow"
    if k == FRAME:
        return "#frame:" + (doc.attr(i, "url") or "")
    if k == ROOT:
        return "#root"
    for a in ("id", "name", "aria-label", "role", "for"):
        v = doc.attr(i, a)
        if v:
            return f"{a}={v}"
    return ""


def node_keys(doc: Doc) -> list[NodeKey]:
    """Key per node: (parent key, tag, identity, ordinal among equal siblings).
    O(n), one forward pass (pre-order: parents precede children)."""
    n = len(doc)
    keys: list[NodeKey] = [()] * n
    seen: dict[tuple[int, str, str], int] = {}
    for i in range(n):
        p = doc.parent[i]
        tag = doc.tag_name(i)
        ident = _ident(doc, i)
        ordinal = seen.get((p, tag, ident), 0)
        seen[(p, tag, ident)] = ordinal + 1
        # Keys are interned as small tuples: (parent key hash, tag, ident, ordinal).
        pk = hash(keys[p]) if p >= 0 else 0
        keys[i] = (pk, tag, ident, ordinal)
    return keys


def _payload(doc: Doc, i: int) -> tuple[Any, ...]:
    if doc.kind[i] == TEXT:
        return ("t", doc.own_text(i))
    return ("a", tuple(sorted(doc.attrs(i).items())) if doc.kind[i] == ELEMENT else ())


@dataclass(frozen=True)
class DocDiff:
    added: tuple[int, ...]      # node indexes in the new doc
    removed: tuple[int, ...]    # node indexes in the old doc
    changed: tuple[tuple[int, int], ...]  # (old index, new index): text or attributes differ
    truncated: bool = False     # either side was truncated: absence is not proof of removal

    @property
    def empty(self) -> bool:
        return not (self.added or self.removed or self.changed)


def diff(old: Doc, new: Doc) -> DocDiff:
    """Hash-join on keys. ``diff(a, a)`` is empty. O(n)."""
    ko, kn = node_keys(old), node_keys(new)
    mo = {k: i for i, k in enumerate(ko)}
    mn = {k: i for i, k in enumerate(kn)}
    added = tuple(i for i, k in enumerate(kn) if k not in mo)
    removed = tuple(i for i, k in enumerate(ko) if k not in mn)
    changed = tuple((mo[k], j) for j, k in enumerate(kn)
                    if k in mo and _payload(old, mo[k]) != _payload(new, j))
    return DocDiff(added, removed, changed, bool(old.truncations or new.truncations))


def top_level(doc: Doc, nodes: Iterable[int]) -> list[int]:
    """The nodes of a set that have no ancestor in the set (subtree roots)."""
    s = sorted(set(nodes))
    out: list[int] = []
    for i in s:
        if out and doc.is_ancestor(out[-1], i):
            continue
        out.append(i)
    return out


# ---------------------------------------------------------------------------
# Settle (ALG-016)
# ---------------------------------------------------------------------------

SETTLING, SETTLED = "settling", "settled"


@dataclass
class Settler:
    """Feed one reading per poll: ``observe(signature, now)``. ``signature``
    is a structure hash or a mutation count; ``now`` is seconds from any
    monotonic clock the caller owns. Settled when ``quiet`` consecutive
    readings equal the previous one; ``Timeout(last signature)`` once
    ``now - first >= t_max`` or after ``max_reads`` readings."""

    quiet: int = 2
    t_max: float = 10.0
    max_reads: int = 200
    _first: float | None = None
    _last: Any = None
    _same: int = 0
    _reads: int = 0

    def observe(self, signature: Any, now: float) -> str | Timeout[Any]:
        if self._first is None:
            self._first = now
        self._reads += 1
        if self._reads > 1 and signature == self._last:
            self._same += 1
        else:
            self._same = 0
        self._last = signature
        if self._same >= self.quiet:
            return SETTLED
        if now - self._first >= self.t_max or self._reads >= self.max_reads:
            return Timeout(signature, self._reads, "settle T_max reached")
        return SETTLING

    @staticmethod
    def interval(t: int) -> float:
        """Poll interval in seconds for poll ``t``: min(50·1.5^t, 500) ms."""
        return min(0.05 * (1.5 ** min(t, 20)), 0.5)


# ---------------------------------------------------------------------------
# Conditional fields (BLUEPRINT s8 item 10)
# ---------------------------------------------------------------------------

QuestionKey = tuple[str, str, str, str]   # (form-root path, name, id, label key)
CHOICE_KINDS = frozenset({"radio", "select", "checkbox", "combobox", "choice"})


@dataclass(frozen=True)
class Question:
    key: QuestionKey
    kind: str          # "text", "radio", "select", "checkbox", "combobox", ...


@dataclass(frozen=True)
class RoundResult:
    revealed: tuple[QuestionKey, ...]
    withdrawn: tuple[QuestionKey, ...]
    agenda: tuple[QuestionKey, ...]
    status: str        # "continue" | "done" | "cycle" | "cap"


@dataclass
class ConditionalLoop:
    """Fixpoint over question keys. The engine answers the head of
    ``agenda``; after a *choice* answer it re-observes the form region and
    calls ``after_answer``. Ends on an empty agenda (``done``), a repeated
    (questions, answers) state (``cycle``: hand to the human), or the round
    cap ``|F| + 10`` (``cap``)."""

    questions: list[Question]
    agenda: list[QuestionKey] = field(default_factory=list)
    answers: dict[QuestionKey, str] = field(default_factory=dict)
    edges: list[tuple[QuestionKey, tuple[QuestionKey, ...]]] = field(default_factory=list)
    rounds: int = 0
    _states: set[tuple[Any, ...]] = field(default_factory=set)

    def __post_init__(self) -> None:
        if not self.agenda:
            self.agenda = [q.key for q in self.questions]
        self.cap = len(self.questions) + 10

    def needs_reobserve(self, q: Question) -> bool:
        return q.kind in CHOICE_KINDS

    def after_answer(self, answered: QuestionKey, value: str,
                     now_visible: Sequence[Question]) -> RoundResult:
        self.rounds += 1
        self.answers[answered] = value
        if answered in self.agenda:
            self.agenda.remove(answered)
        before = {q.key for q in self.questions}
        after = {q.key for q in now_visible}
        revealed = tuple(q.key for q in now_visible if q.key not in before)
        withdrawn = tuple(k for k in (q.key for q in self.questions) if k not in after)
        for k in withdrawn:
            self.answers.pop(k, None)
            if k in self.agenda:
                self.agenda.remove(k)
        if revealed:
            self.edges.append((answered, revealed))
            self.agenda[0:0] = [k for k in revealed if k not in self.answers]
        self.questions = list(now_visible)
        state = (frozenset(after), frozenset(self.answers.items()))
        if state in self._states:
            status = "cycle"
        elif self.rounds >= self.cap:
            status = "cap"
        elif not self.agenda:
            status = "done"
        else:
            status = "continue"
        self._states.add(state)
        return RoundResult(revealed, withdrawn, tuple(self.agenda), status)


# ---------------------------------------------------------------------------
# Post-attempt errors (BLUEPRINT s8 item 11, CT-ALG-012)
# ---------------------------------------------------------------------------

ERROR_WORDS = frozenset(
    "required error invalid missing please must enter provide cannot incorrect wrong".split())


@dataclass(frozen=True)
class MappedError:
    node: int            # error node in the after-doc
    control: int         # control node in the after-doc, -1 when unmapped
    rung: str            # "aria-errormessage" | "aria-describedby" | "aria-invalid-adjacent"
                         # | "container" | "preceding" | "unmapped"
    learned: bool        # found by skeleton similarity, not by markers


def _skeleton(doc: Doc, v: int, depth: int = 4, cap: int = 200) -> Counter[str]:
    c: Counter[str] = Counter()
    base = doc.depth[v]
    for i in doc.subtree(v):
        if len(c) >= cap:
            break
        if doc.kind[i] == ELEMENT and doc.depth[i] - base <= depth:
            c[f"{doc.depth[i] - base}:{doc.tag_name(i)}"] += 1
        elif doc.kind[i] == TEXT and doc.own_text(i).strip():
            c[f"{doc.depth[i] - base}:#t"] += 1
    return c


def _ruzicka(a: Counter[str], b: Counter[str]) -> float:
    keys = set(a) | set(b)
    den = sum(max(a[k], b[k]) for k in keys)
    return sum(min(a[k], b[k]) for k in keys) / den if den else 0.0


def _is_error_marked(doc: Doc, i: int) -> bool:
    if doc.kind[i] != ELEMENT:
        return False
    role = (doc.attr(i, "role") or "").lower()
    if role == "alert" or doc.attr(i, "aria-live") in ("assertive", "polite"):
        return True
    words = set(tokens(doc.text_content(i, 120)[0]))
    return bool(words & ERROR_WORDS) and len(words) <= 20


def map_errors(after: Doc, d: DocDiff, controls: Sequence[int], tau: float = 0.7,
               max_candidates: int = 200) -> tuple[MappedError, ...]:
    """Map new error nodes to controls (indexes in ``after``).

    Candidates are the top-level added nodes plus changed nodes, capped at
    ``max_candidates``. Ladder per error: ``aria-errormessage`` / ``aria-
    describedby`` pointing at it → the control that newly became
    ``aria-invalid`` right before it → the smallest container holding it and
    exactly one control → the nearest preceding control. Then the first
    marker-mapped error's skeleton is the form's template: other candidates
    within ``tau`` are errors too, even without a lexicon word. Unmapped
    errors are returned with ``control = -1``, never dropped."""
    cset = sorted(set(controls))
    cands = top_level(after, list(d.added) + [j for _, j in d.changed])[:max_candidates]
    ids: dict[str, int] = {}
    for i in cands:
        for j in after.subtree(i):
            v = after.attr(j, "id") if after.kind[j] == ELEMENT else None
            if v:
                ids.setdefault(v, i)
    invalid = [c for c in cset if after.attr(c, "aria-invalid") == "true"]

    def ladder(e: int) -> tuple[int, str]:
        for c in cset:
            for attr in ("aria-errormessage", "aria-describedby"):
                for ref in (after.attr(c, attr) or "").split():
                    if ids.get(ref) == e:
                        return c, attr
        prev = [c for c in invalid if c < e]
        if prev and not any(prev[-1] < x < e for x in cset):
            return prev[-1], "aria-invalid-adjacent"
        for a in after.ancestors(e, limit=8):
            inside = [c for c in cset if after.is_ancestor(a, c)]
            if len(inside) == 1:
                return inside[0], "container"
            if len(inside) > 1:
                break
        prev_all = [c for c in cset if c < e]
        if prev_all:
            return prev_all[-1], "preceding"
        return -1, "unmapped"

    out: list[MappedError] = []
    marked = [e for e in cands if any(_is_error_marked(after, j) for j in after.subtree(e)
                                      if j - e < 64)]
    template: Counter[str] | None = None
    for e in marked:
        c, rung = ladder(e)
        out.append(MappedError(e, c, rung, False))
        if template is None and c >= 0:
            template = _skeleton(after, e)
    if template is not None:
        for e in cands:
            if e in marked or any(after.is_ancestor(e, c) or e == c for c in cset):
                continue
            if _ruzicka(template, _skeleton(after, e)) >= tau:
                c, rung = ladder(e)
                out.append(MappedError(e, c, rung, True))
    return tuple(sorted(out, key=lambda m: m.node))


# ---------------------------------------------------------------------------
# Windows (ALG-025)
# ---------------------------------------------------------------------------

OAUTH_POPUP = "OAUTH_POPUP"        # hand to the human
EXTERNAL_APPLY = "EXTERNAL_APPLY"  # follow
AD_UNKNOWN = "AD_UNKNOWN"          # close and record
DIALOG = "DIALOG"                  # JS alert/confirm/prompt/beforeunload: record, never accept a submit
OVER_CAP = "OVER_CAP"              # beyond the per-action cap: close

OAUTH_PARAMS = frozenset({"client_id", "redirect_uri", "response_type", "scope", "code_challenge",
                          "state", "nonce", "SAMLRequest"})
#: Identity-provider hosts (suffix match). Data, not site logic: AA may pass its own.
IDP_HOSTS = ("accounts.google.com", "login.microsoftonline.com", "login.live.com",
             "appleid.apple.com", "www.facebook.com/dialog", "github.com/login",
             "www.linkedin.com/oauth", "api.twitter.com/oauth", "auth0.com", "okta.com",
             "onelogin.com")
AD_HOSTS = ("doubleclick.net", "googlesyndication.com", "adservice.google.com",
            "amazon-adsystem.com", "taboola.com", "outbrain.com", "criteo.com")


@dataclass(frozen=True)
class WindowEvent:
    handle: str
    url: str
    kind: str = "window"      # "window" | "dialog"
    opener_action: str = ""   # the control key of the action that opened it


def _hostpath(url: str) -> tuple[str, str, dict[str, list[str]]]:
    try:
        p = urllib.parse.urlsplit(url or "")
        return (p.hostname or "").lower(), p.path or "", urllib.parse.parse_qs(p.query)
    except ValueError:
        return "", "", {}


def classify_window(ev: WindowEvent, *, apply_hosts: Sequence[str] = (),
                    expected_apply: bool = False, idp_hosts: Sequence[str] = IDP_HOSTS,
                    ad_hosts: Sequence[str] = AD_HOSTS) -> str:
    """OAuth/sign-in → ``OAUTH_POPUP``; a known ATS host, or any http(s)
    page opened by an action that was expected to open the application
    (an "Apply" control) → ``EXTERNAL_APPLY``; everything else, ad hosts and
    ``about:blank`` included → ``AD_UNKNOWN`` (closed and recorded)."""
    if ev.kind == "dialog":
        return DIALOG
    host, path, qs = _hostpath(ev.url)
    hp = host + path
    if (set(qs) & OAUTH_PARAMS and ("client_id" in qs or "SAMLRequest" in qs)) or any(
            hp == h or hp.startswith(h) or host.endswith("." + h) or host == h for h in idp_hosts):
        return OAUTH_POPUP
    if any(host == h or host.endswith("." + h) for h in ad_hosts):
        return AD_UNKNOWN
    if any(host == h or host.endswith("." + h) for h in apply_hosts):
        return EXTERNAL_APPLY
    if expected_apply and ev.url.startswith(("http://", "https://")):
        return EXTERNAL_APPLY
    return AD_UNKNOWN


@dataclass(frozen=True)
class WindowDecision:
    event: WindowEvent
    kind: str
    action: str    # "hand-to-human" | "follow" | "close" | "record"


@dataclass
class WindowSet:
    """Diff the window set around each action; at most ``cap`` new windows
    are classified per action, the rest are ``OVER_CAP`` (closed)."""

    known: set[str] = field(default_factory=set)
    cap: int = 4

    def after_action(self, handles_now: Mapping[str, str], dialogs: Sequence[WindowEvent] = (),
                     opener_action: str = "", expected_apply: bool = False,
                     apply_hosts: Sequence[str] = ()) -> tuple[WindowDecision, ...]:
        out: list[WindowDecision] = []
        new = [h for h in handles_now if h not in self.known]
        for n, h in enumerate(new):
            ev = WindowEvent(h, handles_now[h], "window", opener_action)
            if n >= self.cap:
                out.append(WindowDecision(ev, OVER_CAP, "close"))
                continue
            kind = classify_window(ev, apply_hosts=apply_hosts, expected_apply=expected_apply)
            act = {OAUTH_POPUP: "hand-to-human", EXTERNAL_APPLY: "follow"}.get(kind, "close")
            out.append(WindowDecision(ev, kind, act))
        for d in dialogs[: self.cap]:
            out.append(WindowDecision(d, DIALOG, "record"))
        self.known = set(handles_now)   # closed windows leave the set
        return tuple(out)


# ---------------------------------------------------------------------------
# Pause and resume (ALG-024, CT-DS-012)
# ---------------------------------------------------------------------------

NO_CHANGE, FIELD_EDITS, NAVIGATED, WINDOWS_CHANGED, CHALLENGE_CLEARED, PAGE_GONE = (
    "NO_CHANGE", "FIELD_EDITS", "NAVIGATED", "WINDOWS_CHANGED", "CHALLENGE_CLEARED", "PAGE_GONE")


@dataclass(frozen=True)
class PlannedStep:
    control_key: NodeKey
    intent: str
    expected_value: str | None = None  # precondition: the control's value when planned


@dataclass(frozen=True)
class PauseContext:
    observation_id: str          # PageObservation.content_hash
    epoch: int
    url: str
    findings: tuple[Any, ...]
    intended: tuple[PlannedStep, ...]
    confidence: float
    windows: frozenset[str] = frozenset()
    challenge: bool = False      # paused because the verdict said challenge
    values: Mapping[NodeKey, str] = field(default_factory=dict)  # control values at pause


@dataclass(frozen=True)
class ResumeResult:
    classification: str
    epoch: int
    stale: tuple[Stale, ...]               # one per old finding: never act on them
    kept: tuple[PlannedStep, ...]          # preconditions still hold
    dropped: tuple[PlannedStep, ...]
    human_owned: frozenset[NodeKey]        # controls the human changed: never overwrite


def control_values(doc: Doc) -> dict[NodeKey, str]:
    keys = node_keys(doc)
    out: dict[NodeKey, str] = {}
    for i in range(len(doc)):
        if doc.kind[i] == ELEMENT and doc.tag_name(i) in ("input", "select", "textarea"):
            out[keys[i]] = doc.attr(i, "value") or ("checked" if doc.has_attr(i, "checked") else "")
    return out


def resume(ctx: PauseContext, *, new_epoch: int, old_doc: Doc | None, new_doc: Doc | None,
           new_url: str, windows_now: frozenset[str], challenge_now: bool) -> ResumeResult:
    """Always re-observe first: the caller passes the fresh ``new_doc``.
    Every old finding is ``Stale``; plan steps survive only when their
    control still exists with the value they expected."""
    if new_epoch <= ctx.epoch:
        new_epoch = ctx.epoch + 1
    stale = tuple(Stale(ctx.epoch, new_epoch) for _ in ctx.findings)
    if new_doc is None:
        return ResumeResult(PAGE_GONE, new_epoch, stale, (), ctx.intended, frozenset())
    now_vals = control_values(new_doc)
    human = frozenset(k for k, v in ctx.values.items() if k in now_vals and now_vals[k] != v)
    kept: list[PlannedStep] = []
    dropped: list[PlannedStep] = []
    for s in ctx.intended:
        ok = s.control_key in now_vals and s.control_key not in human and (
            s.expected_value is None or now_vals[s.control_key] == s.expected_value)
        (kept if ok else dropped).append(s)
    if _strip(new_url) != _strip(ctx.url):
        cls = NAVIGATED
    elif ctx.challenge and not challenge_now:
        cls = CHALLENGE_CLEARED
    elif windows_now != ctx.windows:
        cls = WINDOWS_CHANGED
    elif human:
        cls = FIELD_EDITS
    elif old_doc is not None and not diff(old_doc, new_doc).empty:
        cls = FIELD_EDITS
    else:
        cls = NO_CHANGE
    if cls == NAVIGATED:
        dropped, kept = dropped + kept, []
    return ResumeResult(cls, new_epoch, stale, tuple(kept), tuple(dropped), human)


def _strip(url: str) -> str:
    return (url or "").split("#", 1)[0]
