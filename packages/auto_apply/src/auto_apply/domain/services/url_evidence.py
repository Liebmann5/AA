"""Fail-closed URL evidence classification for SERP card destinations.

Reads the *whole* URL as evidence: host labels, path-segment tokens, and
query-key tokens. Tokenization is what makes ``ad_domain``/``ad_provider``
advertising signals while ``adobe``/``admin``/``read`` are not.

No vendor selectors, no host allow-lists. Deterministic: same inputs, same
decision, every run. Standard library only.

Scoring (all constants documented in-module):
    score = title_overlap
          + 0.5  if the resolved host differs from the SERP host
          + 0.4  if the original href carries an opaque long wrapper payload
          + 0.6  if the anchor text expresses apply intent

A candidate is eligible at score >= 0.5. Selection among eligible candidates
requires either a single eligible candidate, or exactly one title-aligned
candidate that also leads by a real margin — otherwise the card is
``multi_route`` and nothing is chosen.
"""

from __future__ import annotations

import base64
import posixpath
import urllib.parse

from auto_apply.domain.ports.page_understanding_port import (
    CardResolutionState,
    JobUrlCandidate,
    JobUrlRejection,
)

DENIED_SCHEMES = frozenset(
    {"javascript", "mailto", "tel", "data", "about", "file", "ftp", "vbscript", "sms"}
)

DEAD_END_TEXT = (
    "privacy", "cookie", "terms", "settings", "preferences", "about our ads",
    "advertise", "feedback", "help", "sign in", "log in", "report",
)

# Host labels that identify advertising infrastructure wherever they appear.
AD_HOST_LABELS = frozenset(
    {"ads", "adservice", "adserver", "adlibrary", "adtech", "adsystem",
     "advertising", "doubleclick", "choice", "adnxs", "criteo", "taboola", "outbrain"}
)

# Token vocabulary for advertising. Tokenization makes ``ad_domain`` contain
# the token ``ad`` while ``adobe``/``admin`` contain no such token.
AD_TOKENS = frozenset({"ad", "ads", "advert", "advertisement", "sponsored", "promoted"})

# Query keys that conventionally carry a redirect payload.
WRAPPER_KEYS = ("url", "u", "q", "uddg", "target", "dest", "destination", "r", "redirect")

CANDIDATE_THRESHOLD = 0.5
SELECTION_MARGIN = 0.5
TITLE_OVERLAP_FOR_SELECTION = 0.5
APPLY_INTENT_BONUS = 0.6
EXTERNAL_HOST_BONUS = 0.5
PENDING_REDIRECT_BONUS = 0.4

_OPAQUE_PAYLOAD_MIN_LEN = 40


def _url_tokens(value: str) -> frozenset[str]:
    """Lowercased alphanumeric tokens, no length filter (``ad`` is short)."""
    value = urllib.parse.unquote(value)
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in value)
    return frozenset(cleaned.split())


def _overlap_tokens(text: str) -> frozenset[str]:
    """Tokens used for title alignment; short tokens carry no meaning here."""
    return frozenset(t for t in _url_tokens(text) if len(t) > 3)


def resolve_href(href: str, base_url: str) -> str:
    """Resolve a possibly relative href against the page URL (D3).

    For anchor hrefs only. Wrapper payloads are NOT resolved through this
    path — see :func:`unwrap` for why.
    """
    if not href:
        return ""
    return urllib.parse.urljoin(base_url, href) if base_url else href


def canonical_url(url: str, base_url: str = "") -> str:
    """Stable, non-destructive URL identity for dedup.

    Resolves relatives, lowercases scheme/host, strips default ports,
    normalizes the path, sorts query pairs, and drops the fragment. Query
    parameters are NEVER stripped: they can be the ad signal or the wrapper
    payload.
    """
    absolute = resolve_href(url, base_url) if base_url else url
    try:
        parts = urllib.parse.urlsplit(absolute)
    except Exception:
        return absolute
    if parts.scheme.lower() not in {"http", "https"}:
        return absolute

    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    if scheme == "http" and netloc.endswith(":80"):
        netloc = netloc[:-3]
    elif scheme == "https" and netloc.endswith(":443"):
        netloc = netloc[:-4]

    path = parts.path or "/"
    try:
        path = posixpath.normpath(path)
    except Exception:
        pass

    pairs = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    pairs.sort(key=lambda pair: (pair[0], pair[1]))
    query = urllib.parse.urlencode(pairs, doseq=True)
    return urllib.parse.urlunsplit((scheme, netloc, path, query, ""))


def advertising_evidence(url: str) -> tuple[str, ...]:
    """Advertising signals found anywhere in a URL (D1).

    Structural, not vendor knowledge: a host label in ``AD_HOST_LABELS``, or
    a host/path/query-key token in ``AD_TOKENS``.
    """
    evidence: list[str] = []
    try:
        parts = urllib.parse.urlsplit(url)
    except Exception:
        return ()

    hostname = (parts.hostname or "").lower().strip(".")
    for label in hostname.split("."):
        if not label:
            continue
        if label in AD_HOST_LABELS:
            evidence.append(f"advertising host label {label!r}")
        elif _url_tokens(label) & AD_TOKENS:
            evidence.append(f"host label {label!r} contains advertising token")

    for segment in parts.path.split("/"):
        if segment and (_url_tokens(segment) & AD_TOKENS):
            evidence.append(f"path segment {segment!r} contains advertising token")

    for key, _value in urllib.parse.parse_qsl(parts.query, keep_blank_values=True):
        hits = sorted(_url_tokens(key) & AD_TOKENS)
        if hits:
            evidence.append(f"query key {key!r} contains advertising token {hits}")

    return tuple(evidence)


def _base64_decode(value: str, skip: int) -> str:
    payload = value[skip:]
    payload += "=" * (-len(payload) % 4)
    return base64.urlsafe_b64decode(payload).decode("utf-8", "strict")


def unwrap(href: str, base_url: str = "") -> tuple[str, str]:
    """Attempt to decode a redirect wrapper through a ladder of stdlib codecs.

    Returns ``(resolved_url, how)``. Two different things are handled here
    and they must not share a path:

    * The *wrapper* href may itself be relative — it is resolved against
      ``base_url`` so the navigable fallback stays usable.
    * The *payload* inside it is only ever a destination when the decoded
      value is ALREADY an absolute http(s) URL. A payload is NEVER resolved
      against the page URL: ``urljoin`` turns any opaque string into a
      bogus absolute URL on the results host, which is exactly the failure
      this function exists to prevent. If no rung decodes to an absolute
      URL, the original href is returned unchanged, kept as navigable.
    """
    absolute = resolve_href(href, base_url) if base_url else href
    try:
        parts = urllib.parse.urlsplit(absolute)
        params = urllib.parse.parse_qs(parts.query, keep_blank_values=True)
    except Exception:
        return absolute, "unparseable"

    for key in WRAPPER_KEYS:
        for raw in params.get(key, []):
            for label, decoder in (
                ("plain", lambda s: s),
                ("percent", urllib.parse.unquote),
                ("base64", lambda s: _base64_decode(s, 0)),
                ("base64+skip1", lambda s: _base64_decode(s, 1)),
                ("base64+skip2", lambda s: _base64_decode(s, 2)),
            ):
                try:
                    decoded = urllib.parse.unquote(decoder(raw))
                except Exception:
                    continue
                # Only an already-absolute decoded value is a destination.
                if decoded.startswith(("http://", "https://")):
                    return decoded, f"unwrapped from ?{key}= via {label}"

    return absolute, "no decodable payload; wrapper kept as navigable"


def has_pending_redirect(href: str) -> bool:
    """True when a wrapper query key carries an opaque long payload."""
    try:
        parts = urllib.parse.urlsplit(href)
        params = urllib.parse.parse_qs(parts.query, keep_blank_values=True)
    except Exception:
        return False
    return any(
        any(len(value) > _OPAQUE_PAYLOAD_MIN_LEN for value in values)
        for key, values in params.items()
        if key in WRAPPER_KEYS
    )


def has_apply_intent(text: str) -> bool:
    """General intent signal: the anchor itself says the user applies."""
    return "apply" in _url_tokens(text)


def merge_candidates(
    *groups: tuple[JobUrlCandidate, ...],
) -> tuple[JobUrlCandidate, ...]:
    """Dedupe candidates by canonical URL, keeping the highest score."""
    best: dict[str, JobUrlCandidate] = {}
    for group in groups:
        for candidate in group:
            key = candidate.canonical_url or candidate.url or candidate.original_url
            if not key:
                continue
            existing = best.get(key)
            if existing is None or candidate.score > existing.score:
                best[key] = candidate
    return tuple(sorted(best.values(), key=lambda c: (-c.score, c.canonical_url)))


def merge_rejections(
    *groups: tuple[JobUrlRejection, ...],
) -> tuple[JobUrlRejection, ...]:
    """Dedupe rejections by (canonical URL, reason), first record wins."""
    best: dict[tuple[str, str], JobUrlRejection] = {}
    for group in groups:
        for rejection in group:
            key = (canonical_url(rejection.original_url), rejection.reason)
            best.setdefault(key, rejection)
    return tuple(best.values())


def evaluate_candidates(
    items: list[dict[str, str]],
    *,
    title: str,
    serp_host: str,
    base_url: str,
) -> tuple[tuple[JobUrlCandidate, ...], tuple[JobUrlRejection, ...]]:
    """Classify and score URL candidates. Rejection precedes scoring.

    An advertising URL never becomes a candidate; it is retained as a
    rejection with concrete evidence (the research record keeps the reason).
    """
    title_tokens = _overlap_tokens(title)
    serp_host = (serp_host or urllib.parse.urlsplit(base_url).netloc).lower()

    candidates: list[JobUrlCandidate] = []
    rejections: list[JobUrlRejection] = []

    for item in items:
        raw = (item.get("href") or "").strip()
        text = (item.get("text") or "").strip()
        source = item.get("source", "unknown")
        if not raw:
            continue

        if raw.startswith("#"):
            rejections.append(JobUrlRejection(raw, "", "fragment-only URL"))
            continue

        try:
            href = resolve_href(raw, base_url)
        except Exception:
            rejections.append(
                JobUrlRejection(raw, "", "unparseable URL", ("urljoin failed",))
            )
            continue

        scheme = urllib.parse.urlsplit(href).scheme.lower()
        if scheme in DENIED_SCHEMES or not href.lower().startswith(("http://", "https://")):
            rejections.append(
                JobUrlRejection(raw, href, f"denied scheme {scheme or 'none'!r}")
            )
            continue

        if any(term in text.lower() for term in DEAD_END_TEXT):
            rejections.append(
                JobUrlRejection(raw, href, "dead-end text", (text[:80],))
            )
            continue

        ad_evidence = advertising_evidence(href)
        if ad_evidence:
            rejections.append(
                JobUrlRejection(raw, href, "advertising evidence", ad_evidence)
            )
            continue

        resolved, how = unwrap(href, base_url)
        if not resolved.startswith(("http://", "https://")):
            rejections.append(
                JobUrlRejection(raw, href, "resolved URL is not http(s)")
            )
            continue

        resolved_ad = advertising_evidence(resolved)
        if resolved_ad:
            rejections.append(
                JobUrlRejection(raw, resolved, "resolved payload is advertising", resolved_ad)
            )
            continue

        resolved_host = urllib.parse.urlsplit(resolved).netloc.lower()
        overlap = (
            len(title_tokens & _overlap_tokens(resolved + " " + text)) / len(title_tokens)
            if title_tokens
            else 0.0
        )
        external = bool(resolved_host) and resolved_host != serp_host
        pending = has_pending_redirect(href)
        apply_intent = has_apply_intent(text)

        score = (
            overlap
            + (EXTERNAL_HOST_BONUS if external else 0.0)
            + (PENDING_REDIRECT_BONUS if pending else 0.0)
            + (APPLY_INTENT_BONUS if apply_intent else 0.0)
        )

        candidates.append(
            JobUrlCandidate(
                url=resolved,
                original_url=raw,
                anchor_text=text,
                source=source,
                score=score,
                title_overlap=overlap,
                method=how,
                apply_intent=apply_intent,
                pending_redirect=pending,
                canonical_url=canonical_url(resolved, base_url),
            )
        )

    return tuple(candidates), tuple(rejections)


def decide_resolution_state(
    candidates: tuple[JobUrlCandidate, ...],
    rejections: tuple[JobUrlRejection, ...],
    *,
    material_seen: bool,
) -> tuple[CardResolutionState, JobUrlCandidate | None]:
    """Choose between resolved / multi_route / deferred / no_destination.

    Multiple legitimate ``Apply on X`` routes never collapse into the first
    one. A route is selected only when it is unique, or when it is the only
    title-aligned candidate and leads by a real margin.
    """
    if not candidates:
        if rejections or material_seen:
            return CardResolutionState.DEFERRED, None
        return CardResolutionState.NO_DESTINATION, None

    eligible = sorted(
        (c for c in candidates if c.score >= CANDIDATE_THRESHOLD),
        key=lambda c: (-c.score, c.canonical_url or c.url),
    )
    if not eligible:
        return CardResolutionState.DEFERRED, None
    if len(eligible) == 1:
        return CardResolutionState.RESOLVED, eligible[0]

    title_aligned = [c for c in eligible if c.title_overlap >= TITLE_OVERLAP_FOR_SELECTION]
    if len(title_aligned) == 1 and title_aligned[0] is eligible[0]:
        if eligible[0].score - eligible[1].score >= SELECTION_MARGIN:
            return CardResolutionState.RESOLVED, eligible[0]

    return CardResolutionState.MULTI_ROUTE, None
