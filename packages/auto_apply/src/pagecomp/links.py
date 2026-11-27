"""Link evidence and the destination-resolution ladder (CT-ALG-004 link part).

Ported from AA ``domain/services/url_evidence.py`` (fail-closed scoring,
advertising evidence, local unwrap ladder, dead-end phrases) and extended
with what Google's ``/goto?url=CAES...`` links (confirmed by Google on
2026-08-26 as an anti-abuse measure; not locally decodable; one token per
page load) showed was missing: a **resolution ladder** whose last rung is
honest about not knowing yet.

The ladder, strongest first:

1. ``direct``     the href is already the destination (http/https).
2. ``unwrapped``  a wrapper (``?u=a1...``, ``?q=``, ``?uddg=``) decodes
                  locally to an absolute URL; the payload is never resolved
                  against the page URL (that would invent a destination).
3. ``opaque``     a wrapper key carries a long payload that does not decode:
                  the destination is known only after the visit. The record
                  keeps the **expected host** from page evidence (the
                  ``<cite>`` breadcrumb or a rendered URL in the card), and
                  the visit the engine already makes is the resolution.
                  ``arrival_integrity`` then checks that the landed host is
                  the expected one; a mismatch is evidence of an ad, a
                  hijack or a mis-read card, and the record is dropped.
4. ``none``       no navigable href (button, ``#``, ``javascript:``).

What is deliberately *not* a rung: an out-of-browser HTTP request to follow
the redirect. It adds a second network identity and footprint outside the
browser session (07 section 10, ENGINEERING_PHILOSOPHY: few network calls,
no hidden behaviour), and the browser visit resolves it anyway.
"""

from __future__ import annotations

import base64
import posixpath
import re
import urllib.parse
from collections.abc import Iterable
from dataclasses import dataclass

DENIED_SCHEMES = frozenset(
    {"javascript", "mailto", "tel", "data", "about", "file", "ftp", "vbscript", "sms", "blob"}
)
DEAD_END_PHRASES = (
    "privacy", "cookie", "terms", "settings", "preferences", "about our ads", "advertise",
    "feedback", "help", "sign in", "log in", "report", "terms of use", "terms of service",
    "privacy policy", "cookie policy", "cookie settings", "help center", "report an ad",
    "report this ad", "why this ad", "send feedback", "cached", "similar",
)
DEAD_END_MAX_TOKENS = 5
AD_HOST_LABELS = frozenset(
    {"ads", "adservice", "adserver", "adlibrary", "adtech", "adsystem", "advertising",
     "doubleclick", "choice", "adnxs", "criteo", "taboola", "outbrain", "googleadservices"}
)
#: ``aclk`` ("ad click") is the click route of a search engine's paid results:
#: Bing's ``/aclk?ld=...&u=<base64 destination>`` (18 links on the owner's
#: plain Bing search, 2026-11-08, every one under a "Sponsored" label) and
#: Google's ``/aclk`` and ``/pagead/aclk``. A bot that follows one charges the
#: advertiser for a click no person made.
AD_TOKENS = frozenset({"ad", "ads", "advert", "advertisement", "sponsored", "promoted",
                       "aclk", "pagead"})
WRAPPER_KEYS = ("url", "u", "q", "uddg", "target", "dest", "destination", "r", "redirect")
OPAQUE_PAYLOAD_MIN_LEN = 40

CANDIDATE_THRESHOLD = 0.5
SELECTION_MARGIN = 0.5
TITLE_OVERLAP_FOR_SELECTION = 0.5
APPLY_INTENT_BONUS = 0.6
EXTERNAL_HOST_BONUS = 0.5
PENDING_REDIRECT_BONUS = 0.4
TITLE_RELATION_BONUS = 0.5

DIRECT, UNWRAPPED, OPAQUE, NONE = "direct", "unwrapped", "opaque", "none"
RESOLVED, MULTI_ROUTE, DEFERRED, NO_DESTINATION = "resolved", "multi_route", "deferred", "no_destination"

_SHORT_SLDS = frozenset({"co", "com", "org", "net", "ac", "gov", "edu"})


def url_tokens(value: str) -> frozenset[str]:
    value = urllib.parse.unquote(value)
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in value)
    return frozenset(cleaned.split())


def _overlap_tokens(text: str) -> frozenset[str]:
    return frozenset(t for t in url_tokens(text) if len(t) > 3)


def title_overlap(title: str, text: str) -> float:
    tt = _overlap_tokens(title)
    if not tt:
        return 0.0
    return len(tt & _overlap_tokens(text)) / len(tt)


def site(host: str) -> str:
    """Registrable domain by a small table (not a public-suffix list)."""
    labels = [p for p in (host or "").lower().split(".") if p]
    if len(labels) >= 3 and labels[-2] in _SHORT_SLDS and len(labels[-1]) == 2:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def hosts_related(a: str, b: str) -> bool:
    a, b = (a or "").lower().strip("."), (b or "").lower().strip(".")
    if not a or not b:
        return False
    return a == b or a.endswith("." + b) or b.endswith("." + a) or site(a) == site(b)


def resolve_href(href: str, base_url: str) -> str:
    if not href:
        return ""
    try:
        return urllib.parse.urljoin(base_url, href) if base_url else href
    except ValueError:
        return ""


def canonical_url(url: str, base_url: str = "") -> str:
    absolute = resolve_href(url, base_url) if base_url else url
    try:
        parts = urllib.parse.urlsplit(absolute)
    except ValueError:
        return absolute
    if parts.scheme.lower() not in {"http", "https"}:
        return absolute
    scheme, netloc = parts.scheme.lower(), parts.netloc.lower()
    if scheme == "http" and netloc.endswith(":80"):
        netloc = netloc[:-3]
    elif scheme == "https" and netloc.endswith(":443"):
        netloc = netloc[:-4]
    path = posixpath.normpath(parts.path or "/")
    pairs = sorted(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
    return urllib.parse.urlunsplit((scheme, netloc, path, urllib.parse.urlencode(pairs, doseq=True), ""))


def advertising_evidence(url: str) -> tuple[str, ...]:
    """Structural ad signals; path segments quoted by token, never by text."""
    ev: list[str] = []
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return ()
    for label in (parts.hostname or "").lower().strip(".").split("."):
        if not label:
            continue
        if label in AD_HOST_LABELS:
            ev.append(f"advertising host label {label!r}")
        elif url_tokens(label) & AD_TOKENS:
            ev.append(f"host label {label!r} contains advertising token")
    for seg in parts.path.split("/"):
        hits = sorted(url_tokens(seg) & AD_TOKENS) if seg else []
        if hits:
            ev.append(f"path segment contains advertising token {hits}")
    for k, _ in urllib.parse.parse_qsl(parts.query, keep_blank_values=True):
        hits = sorted(url_tokens(k) & AD_TOKENS)
        if hits:
            ev.append(f"query key {k!r} contains advertising token {hits}")
    return tuple(ev)


def _b64(value: str, skip: int) -> str:
    payload = value[skip:]
    payload += "=" * (-len(payload) % 4)
    return base64.urlsafe_b64decode(payload).decode("utf-8", "strict")


def unwrap(href: str, base_url: str = "") -> tuple[str, str]:
    """Local decode ladder. Returns ``(url, how)``; the href itself if none."""
    absolute = resolve_href(href, base_url) if base_url else href
    try:
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(absolute).query, keep_blank_values=True)
    except ValueError:
        return absolute, "unparseable"
    for k in WRAPPER_KEYS:
        for raw in params.get(k, []):
            for label, dec in (("plain", lambda s: s), ("percent", urllib.parse.unquote),
                               ("base64", lambda s: _b64(s, 0)),
                               ("base64+skip1", lambda s: _b64(s, 1)),
                               ("base64+skip2", lambda s: _b64(s, 2))):
                try:
                    decoded = urllib.parse.unquote(dec(raw))
                except Exception:
                    continue
                if decoded.startswith(("http://", "https://")):
                    return decoded, f"unwrapped ?{k}= via {label}"
    return absolute, "no decodable payload"


def opaque_payload(href: str) -> bool:
    try:
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(href).query, keep_blank_values=True)
    except ValueError:
        return False
    return any(len(v) >= OPAQUE_PAYLOAD_MIN_LEN for k, vs in params.items()
               if k in WRAPPER_KEYS for v in vs)


def _words(text: str) -> list[str]:
    return re.findall(r"[0-9a-z]+", text.casefold())


def is_dead_end_text(text: str) -> bool:
    toks = _words(text)
    if not toks or len(toks) > DEAD_END_MAX_TOKENS:
        return False
    for phrase in DEAD_END_PHRASES:
        p = phrase.split()
        if 2 * len(p) < len(toks):
            continue
        for s in range(len(toks) - len(p) + 1):
            if toks[s:s + len(p)] == p:
                return True
    return False


def has_apply_intent(text: str) -> bool:
    return "apply" in url_tokens(text)


_APPLY_PHRASES = ("i'm interested", "i am interested", "im interested", "easy apply",
                  "start application", "start your application", "submit application")


def is_apply_text(text: str) -> bool:
    """A control that starts an application (lexicon evidence, English in v0.1).

    "I'm interested" is SmartRecruiters' apply control (problem list item 13).
    """
    if has_apply_intent(text):
        return True
    t = " ".join(text.casefold().replace("\u2019", "'").split())
    return len(t) <= 40 and any(p in t for p in _APPLY_PHRASES)


_ENTRY_PHRASES = ("autofill", "auto-fill", "apply manually", "use my last application",
                  "apply with linkedin", "apply with indeed", "apply with resume",
                  "apply with your resume", "upload resume", "upload your resume",
                  "continue as guest", "apply as guest", "start application",
                  "start your application", "create account", "quick apply", "easy apply")


def is_entry_choice(text: str) -> bool:
    """One way of *starting* an application, offered as a choice
    (Workday's "Autofill with Resume / Apply Manually / Use My Last
    Application"). Lexicon evidence, English."""
    t = " ".join(text.casefold().replace("\u2019", "'").split())
    return 0 < len(t) <= 48 and any(p in t for p in _ENTRY_PHRASES)


POSTING_PATH_TOKENS = frozenset({
    "job", "jobs", "career", "careers", "position", "positions", "posting", "postings",
    "opening", "openings", "vacancy", "vacancies", "req", "requisition", "apply",
    "jobdetail", "jobdetails", "viewjob", "hiring",
})
_IDENT_PARTS = re.compile(r"[A-Za-z0-9]+")


def has_identifier(text: str) -> bool:
    """An id-like token: >= 3 digits in a row, a mixed letter+digit token of
    >= 6 characters (``7ySmewF``, ``aa8f78e98959``), or >= 24 characters."""
    for tok in _IDENT_PARTS.findall(text):
        if len(tok) >= 24 or re.search(r"\d{3,}", tok):
            return True
        if len(tok) >= 6 and any(ch.isdigit() for ch in tok) and any(ch.isalpha() for ch in tok):
            return True
    return False


#: Query keys that carry tracking or session state, never a posting's id.
_TRACKING_KEYS = frozenset({
    "ved", "ei", "sa", "usg", "sca_esv", "sxsrf", "oq", "gs_lcrp", "rlz", "uact", "fbclid",
    "gclid", "msclkid", "dclid", "yclid", "_ga", "_gl", "mc_cid", "mc_eid", "trk", "trkinfo",
    "refid", "ref", "referrer", "from", "source", "src", "sid", "session", "sessionid",
    "tracking", "trackingid", "cid", "clickid", "bb", "xkcb", "xpse", "xfps", "tk",
})
#: Query keys that make a URL a *search*: its results, not one item.
_SEARCH_KEYS = frozenset({"q", "query", "keywords", "keyword", "search", "text", "p", "k", "term"})
#: Path segments that make a URL a *search* page.
_SEARCH_SEGMENTS = frozenset({"search", "results", "search-results", "searchresults"})


def specific_destination(url: str) -> bool:
    """Does the URL name **one** item rather than a search or a category?

    * an identifier (``has_identifier``) in the path;
    * a posting word as a whole path segment followed by a segment that is
      not itself a category name (``/jobs/head-of-product-design_paris``, but
      not ``/jobs/j2ee-developer-jobs``);
    * an identifier in the value of a non-tracking query key (Indeed's
      ``/rc/clk?jk=…``), unless the URL is itself a search (``?q=…``).

    Related-search and category links (``/q-junior-web-developer-…-jobs.html``,
    ``/c/audit-jobs``, ``/search?q=…&ved=…``) are not specific, and neither is
    a path with a search segment (``/jobs/dev-engineering/search/backend-engineer``,
    Built In's results page on the owner's Google search of 2026-11-08) unless
    it carries an identifier.
    """
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    if not parts.scheme.startswith("http"):
        return False
    if has_identifier(parts.path):
        return True
    segs = [x for x in parts.path.split("/") if x]
    if any(seg.lower() in _SEARCH_SEGMENTS for seg in segs):
        return False
    for i, seg in enumerate(segs[:-1]):
        if seg.lower() in POSTING_PATH_TOKENS:
            nxt = segs[i + 1]
            if len(nxt) >= 3 and not (url_tokens(nxt) & POSTING_PATH_TOKENS):
                return True
    try:
        pairs = urllib.parse.parse_qsl(parts.query, keep_blank_values=False)
    except ValueError:
        return False
    keys = {k.lower() for k, _ in pairs}
    if keys & _SEARCH_KEYS:
        return False
    return any(has_identifier(v) for k, v in pairs
               if k.lower() not in _TRACKING_KEYS and not k.lower().startswith("utm_"))


def posting_path(url: str) -> float:
    """How much a URL looks like one posting's address (0, 0.5 or 1).

    1.0: a posting token in the path **and** an identifier (``has_identifier``)
    in path or query; a hyphenated slug of words is a title, not an
    identifier (``/q-software-engineer-l-...-jobs.html``); 0.5: the token alone (a category
    page such as ``/c/audit-jobs``). Structural evidence shared by the title
    rule (CT-ALG-004) and the job-list gate, so the two cannot disagree.
    """
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return 0.0
    if not parts.scheme.startswith("http"):
        return 0.0
    toks = url_tokens(parts.path)
    if not toks & POSTING_PATH_TOKENS:
        return 0.0
    return 1.0 if has_identifier(parts.path + "?" + parts.query) else 0.5


# -- page evidence of a destination: breadcrumbs and rendered URLs ---------

_HOST_RE = r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}"
_SCHEME_URL = re.compile(r"\bhttps?://(?P<host>" + _HOST_RE + r")(?::\d+)?(?P<rest>[^\s<>\"']*)")
_BREADCRUMB = re.compile(r"(?P<host>" + _HOST_RE + r")(?::\d+)?[ \t ]*[›»]")


def evidence_host(texts: Iterable[str]) -> str:
    """First destination host rendered in the card's text (breadcrumb or URL)."""
    return breadcrumb(texts)[0]


_CRUMB_TAIL = re.compile(r"\s*[\u203a\u00bb]\s*([^\u203a\u00bb\n]+)")


def breadcrumb(texts: Iterable[str]) -> tuple[str, str]:
    """``(host, tail)`` of the first rendered destination: the host, and the
    path the page shows after it (``"p › 4151651bd442-senior-backe..."``),
    as displayed, truncation marks included. Page evidence only."""
    for t in texts:
        m = _SCHEME_URL.search(t) or _BREADCRUMB.search(t)
        if not m:
            continue
        host = m.group("host").lower()
        rest = t[m.end("host"):]
        if m.re is _SCHEME_URL and m.group("rest") and m.group("rest") not in ("/", ""):
            return host, m.group("rest").strip("/").replace("/", " \u203a ")
        segs = []
        pos = 0
        while True:
            mt = _CRUMB_TAIL.match(rest, pos)
            if not mt:
                break
            segs.append(mt.group(1).strip())
            pos = mt.end()
        return host, " \u203a ".join(x for x in segs if x)
    return "", ""


def arrival_integrity(expected_host: str, landed_url: str) -> bool | None:
    """Does the landed page belong to the host the card displayed?

    ``None`` when there was no expectation (nothing to check). Used after an
    ``opaque`` link is visited: the visit is the resolution, this is its check.
    """
    if not expected_host:
        return None
    try:
        host = urllib.parse.urlsplit(landed_url).hostname or ""
    except ValueError:
        return False
    return hosts_related(expected_host, host)


@dataclass(frozen=True)
class LinkCandidate:
    url: str               # destination if known, else the navigable href
    original: str
    text: str
    kind: str              # direct | unwrapped | opaque
    method: str
    score: float
    title_overlap: float
    structural: bool       # contains, or sits inside, the record's title element
    apply_intent: bool
    canonical: str
    expected_host: str     # from page evidence, for opaque links
    node: int
    expected_path: str = ""  # breadcrumb tail shown with an opaque link (linkage evidence)


@dataclass(frozen=True)
class LinkRejection:
    original: str
    reason: str
    detail: tuple[str, ...] = ()
    node: int = -1


def evaluate(items: Iterable[tuple[int, str, str, str]], *, title: str, page_url: str,
             evidence_texts: Iterable[str] = ()) -> tuple[tuple[LinkCandidate, ...], tuple[LinkRejection, ...]]:
    """Score ``(node, href, text, relation)`` items. Rejection precedes scoring."""
    page_host = (urllib.parse.urlsplit(page_url).hostname or "").lower() if page_url else ""
    shown, shown_path = breadcrumb(evidence_texts)
    cands: list[LinkCandidate] = []
    rejs: list[LinkRejection] = []
    tt = _overlap_tokens(title)
    for node, raw, text, relation in items:
        raw = (raw or "").strip()
        if not raw:
            continue
        if raw.startswith("#"):
            rejs.append(LinkRejection(raw, "fragment-only", node=node))
            continue
        href = resolve_href(raw, page_url)
        scheme = urllib.parse.urlsplit(href).scheme.lower() if href else ""
        if not href or scheme in DENIED_SCHEMES or scheme not in ("http", "https"):
            rejs.append(LinkRejection(raw, f"denied scheme {scheme or 'none'!r}", node=node))
            continue
        if is_dead_end_text(text):
            rejs.append(LinkRejection(raw, "dead-end text", node=node))
            continue
        ad = advertising_evidence(href)
        if ad:
            rejs.append(LinkRejection(raw, "advertising evidence", ad, node))
            continue
        resolved, how = unwrap(href, page_url)
        opaque = how == "no decodable payload" and opaque_payload(href)
        if opaque:
            kind = OPAQUE
        elif resolved != href:
            kind = UNWRAPPED
        else:
            kind = DIRECT
        if kind == UNWRAPPED:
            rad = advertising_evidence(resolved)
            if rad:
                rejs.append(LinkRejection(raw, "resolved payload is advertising", rad, node))
                continue
        dest_host = (urllib.parse.urlsplit(resolved).hostname or "").lower()
        # For an opaque link the visible breadcrumb is the only destination
        # evidence; it decides "external", never the wrapper's own host.
        effective_host = shown if kind == OPAQUE else dest_host
        overlap = title_overlap(title, (resolved if kind != OPAQUE else "") + " " + text) if tt else 0.0
        external = bool(effective_host) and not hosts_related(effective_host, page_host)
        score = (overlap
                 + (EXTERNAL_HOST_BONUS if external else 0.0)
                 + (PENDING_REDIRECT_BONUS if kind == OPAQUE else 0.0)
                 + (APPLY_INTENT_BONUS if has_apply_intent(text) else 0.0)
                 + (TITLE_RELATION_BONUS if relation in ("title", "title-structural") else 0.0))
        cands.append(LinkCandidate(
            url=resolved, original=raw, text=text, kind=kind, method=how, score=round(score, 6),
            title_overlap=round(overlap, 6), structural=relation == "title-structural",
            apply_intent=has_apply_intent(text),
            canonical=canonical_url(resolved), expected_host=shown if kind == OPAQUE else "",
            node=node, expected_path=shown_path if kind == OPAQUE else ""))
    return _merge(cands), tuple(rejs)


def _merge(cands: list[LinkCandidate]) -> tuple[LinkCandidate, ...]:
    """One candidate per destination (defect 25). Opaque tokens differ per
    load, so opaque links merge by expected host + anchor text instead."""
    best: dict[str, LinkCandidate] = {}
    for c in cands:
        k = f"opaque:{c.expected_host}:{c.text.casefold()}" if c.kind == OPAQUE else c.canonical
        cur = best.get(k)
        if cur is None or (c.score, -c.node) > (cur.score, -cur.node):
            best[k] = c
    return tuple(sorted(best.values(), key=lambda c: (-c.score, c.node)))


def decide(cands: tuple[LinkCandidate, ...], rejs: tuple[LinkRejection, ...]) -> tuple[str, LinkCandidate | None]:
    """resolved / multi_route / deferred / no_destination (AA's enum values).

    An ``opaque`` winner is ``resolved`` as a *route* (the engine can visit
    it) with ``kind == "opaque"``: the destination URL is learned on arrival.
    """
    if not cands:
        return (DEFERRED if rejs else NO_DESTINATION), None
    eligible = [c for c in cands if c.score >= CANDIDATE_THRESHOLD]
    if not eligible:
        return DEFERRED, None
    if len(eligible) == 1:
        return RESOLVED, eligible[0]
    # Structure beats text: the one link that holds (or is held by) the title
    # element is the record's link, even when a "salaries for <title>" link
    # repeats the title's words.
    structural = [c for c in eligible if c.structural]
    if len(structural) == 1:
        return RESOLVED, structural[0]
    aligned = [c for c in eligible if c.title_overlap >= TITLE_OVERLAP_FOR_SELECTION]
    if len(aligned) == 1 and aligned[0] is eligible[0] and \
            eligible[0].score - eligible[1].score >= SELECTION_MARGIN:
        return RESOLVED, eligible[0]
    return MULTI_ROUTE, None
