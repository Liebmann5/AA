"""The one answer to "what is this page?" — every engine asks here.

Why this module exists:
    AA answered that question in many places, and the answers disagreed.
    Discovery decided "blocked" with a weighted-substring detector over
    titles and page text; the PageClassifier re-answered it with live JS
    probes; the math
    subsystem computed a verdict nobody read. This module is the single
    structural verdict every path asks — discovery, vetting and application
    alike — with the duplicates retired.

What the verdict reads (ruled 2026-09, this change):
    A SNAPSHOT — (url, title, rendered top-frame html) — never the live
    browser. The browser is only a snapshot taker through BrowserInterface:
    page_source IS the rendered post-JS DOM, so every signal the old
    probe-based classifier used (password fields, file inputs, form ids,
    iframe sources, JSON-LD bodies) is present in it. The pure form scored
    20 of 20 on the hand-triaged real pages, runs on the --replay path with
    no browser at all, is deterministic, and cannot fabricate a verdict
    from a dead driver — an unreadable snapshot degrades to UNKNOWN, never
    to "clear". If a future signal genuinely needs a live probe (computed
    visibility is the known candidate), it arrives behind a small probe
    with the pure answer as fallback — the pattern the application path
    already uses for post-click auth dialogs.

Composition, not duplication:
    Challenge and login-wall answers come from
    domain/services/challenge_assessment.py — the measured engine (20/20),
    unchanged. Form-fillability comes from domain/services/apply_target.py
    (already shared by vetting and the application route). This module adds
    the page-kind composition on top:

        1. A GATED challenge dominates everything: the page IS the
           challenge, whatever sits behind it.
        2. A login wall outranks content kinds: the site demands an
           account before it will show anything usable.
        3. A 404 (debt: title evidence only — see below).
        4. ALREADY_APPLIED and CLOSED, from visible-text phrases: they are
           the actionable truth about a posting and outrank every content
           kind below them.
        5. A form substantial enough to BE the application outranks a
           confirmation and a description: a form page is not a
           confirmation page, however polite its text.
        6. A confirmation — a strong phrase in visible text, or a
           confirmation URL marker — means SUCCESS_PAGE, and the verdict's
           signals name the phrase or marker that decided.
        7. JSON-LD JobPosting means the page describes a job.
        8. The page family (06 section 3) for what remains: a site's home or
           landing page (HOME_PAGE) and a results list (SERP), each decided
           only by a margin over the alternatives. HOME_PAGE is decided
           before the confirmation step: a home page is not a confirmation.
        9. Anything else is UNKNOWN — an honest answer, not a failure.

    Sign-in evidence outranks confirmation phrases (EC-42): a page offering
    two or more third-party sign-in choices is LOGIN_REQUIRED even when its
    text carries a confirmation phrase.

Debt, plainly labelled:
    - The 404 check reads the TITLE ("404" / "page not found") — the only
      measured 404 evidence available. Title words are debt, so the kind
      carries confidence 0.6 and the signal "title-404" in every record it
      produces. A measured structural replacement retires this comment.
    - SUCCESS_PAGE / ALREADY_APPLIED / CLOSED are detected from the phrase
      tables in domain/services/page_phrases.py — locale-keyed data a
      translator can extend, matched on VISIBLE text only (never raw page
      source, never the title), unioning every locale so a confirmation in
      any language confirms. The weak phrases from the retired raw-source
      scan were curated, not carried; the drop list and its reasons are
      documented in page_phrases.py.
    - Vendor signals (vendor:cloudflare, vendor:datadome, ...) are
      annotations carried for research, never verdict inputs, and nothing
      about them is persisted.

Confidence semantics: a label for evidence strength, not a probability.
Structural verdicts are 0.80-0.95; the title-only 404 is 0.60; UNKNOWN is
0.0.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlparse

from auto_apply.domain.services.apply_target import (
    FormFacts,
    form_facts,
    page_controls,
    page_has_fillable_form,
)
from auto_apply.domain.services.challenge_assessment import (
    ChallengeVerdict,
    assess_challenge,
    assess_login_wall,
    visible_page_text,
)
from auto_apply.domain.services.page_phrases import (
    ALREADY_APPLIED_PHRASES,
    CLOSED_PHRASES,
    CONFIRMATION_PHRASES,
    CONFIRMATION_URL_MARKERS,
    SIGN_IN_CHOICE_PREFIXES,
)
from auto_apply.domain.types import PageType

#: A JSON-LD script block, body captured. Bounded tag match, lazy body match.
_JSON_LD_SCRIPT_RE = re.compile(
    r"<script[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class PageAssessment:
    """One page verdict plus the signals that decided it.

    ``kind`` is the page's identity in the ONE vocabulary (PageType).
    ``challenge`` is the challenge presence independent of kind — a login
    wall with a reCAPTCHA widget is LOGIN_REQUIRED + "embedded".
    ``signals``, ``vendors`` and ``detail`` travel so a disputed verdict
    says WHY, not just WHAT.
    """

    kind: PageType
    challenge: ChallengeVerdict
    signals: tuple[str, ...]
    detail: str
    confidence: float
    vendors: tuple[str, ...] = ()


#: Leading title segments that name an error page ("Error | Careers
#: Marketplace - Siemens", owner capture cookie-consent-banner, judged
#: UNKNOWN before). Whole first segment only, so "Error Analyst" is a title.
_ERROR_TITLE_SEGMENTS: frozenset[str] = frozenset(
    {"error", "not found", "page not found", "page unavailable"}
)
_TITLE_SEGMENT_RE = re.compile(r"\s+[|\u2013\u2014-]\s+|\s*\|\s*")


def _title_says_404(title: str) -> bool:
    """DEBT: title words are the only measured 404 evidence (module docstring)."""
    text = (title or "").lower()
    if "404" in text or "page not found" in text:
        return True
    first = _TITLE_SEGMENT_RE.split(text.strip(), maxsplit=1)[0].strip()
    return first in _ERROR_TITLE_SEGMENTS


_SIGN_IN_PREFIXES: tuple[str, ...] = tuple(
    dict.fromkeys(p for table in SIGN_IN_CHOICE_PREFIXES.values() for p in table)
)


def _sign_in_choices(url: str, html: str) -> int:
    """How many controls offer a third-party sign-in ("Sign in with X")."""
    try:
        controls = page_controls(url=url, html=html)
    except Exception:
        return 0
    return sum(
        1 for c in controls if c.label.lower().startswith(_SIGN_IN_PREFIXES)
    )


# ── Page family (06 section 3) ──────────────────────────────────────────────
# A log-linear model over structural features, decided only by margin. The
# weights are hand-set and documented here (06: "weights start hand-set and
# documented, later fitted"); the temperature is 1. Only HOME_PAGE and SERP
# are decided here: the kinds above keep their precedence (challenge, login,
# 404, closed and the application form dominate, as 06 section 3 requires).

#: URL query keys that carry a search query.
_QUERY_KEYS: frozenset[str] = frozenset(
    {"q", "query", "keyword", "keywords", "k", "kw", "search", "searchtext",
     "text", "what", "term", "terms", "jobtitle", "title"}
)
#: Links in list items or articles at which a page has a result run.
_RESULT_LINKS_MIN: int = 8
_FAMILY_P_MIN: float = 0.6
_FAMILY_MARGIN_MIN: float = 0.2


@dataclass(frozen=True)
class PageFamily:
    """The family decision with its evidence (scores before the softmax)."""

    kind: PageType | None
    probability: float
    margin: float
    features: tuple[str, ...]


def _url_features(url: str) -> tuple[bool, bool]:
    """(home path, search query in the URL)."""
    try:
        parsed = urlparse(url or "")
    except ValueError:
        return False, False
    path = parsed.path.strip("/").lower()
    home = path in ("", "index.html", "index.htm", "index.php", "home")
    query = any(
        key.lower() in _QUERY_KEYS and value.strip()
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
    )
    return home, query


def page_family(url: str, facts: FormFacts) -> PageFamily:
    """Score the HOME_PAGE, SERP and OTHER families; decide by margin."""
    home, query = _url_features(url)
    run = facts.item_links >= _RESULT_LINKS_MIN
    features = tuple(
        name
        for name, on in (
            ("home-path", home),
            ("url-query", query),
            ("result-links", run),
            ("search-form", facts.search_form),
        )
        if on
    )
    scores = {
        # A home path alone ties with UNKNOWN (no margin): a home page needs
        # the page structure of one too, a search form (here) or a run.
        PageType.HOME_PAGE: 1.5 * home + 1.0 * facts.search_form + 0.5 * run - 2.0 * query,
        PageType.SERP: 1.5 * query + 2.0 * run + 0.5 * facts.search_form - 2.0 * home,
        PageType.UNKNOWN: 1.5,
    }
    peak = max(scores.values())
    weights = {k: math.exp(v - peak) for k, v in scores.items()}
    total = sum(weights.values())
    ranked = sorted(((w / total, k) for k, w in weights.items()), reverse=True,
                    key=lambda pair: pair[0])
    (p1, k1), (p2, _k2) = ranked[0], ranked[1]
    decided = k1 is not PageType.UNKNOWN and p1 >= _FAMILY_P_MIN and p1 - p2 >= _FAMILY_MARGIN_MIN
    return PageFamily(
        kind=k1 if decided else None,
        probability=round(p1, 3),
        margin=round(p1 - p2, 3),
        features=features,
    )


def _has_job_posting_json_ld(html: str) -> bool:
    """True when an application/ld+json block mentions JobPosting."""
    if "ld+json" not in html or "JobPosting" not in html:
        return False
    return any(
        "JobPosting" in match.group(1)
        for match in _JSON_LD_SCRIPT_RE.finditer(html)
    )


# Phrase tables, flattened once at import. dict.fromkeys dedupes while
# preserving table order, so matched-phrase signals are deterministic across
# runs — including seeded research replays.
_CONFIRMATION_TEXT_PHRASES: tuple[str, ...] = tuple(
    dict.fromkeys(
        phrase
        for locales in CONFIRMATION_PHRASES.values()
        for table in locales.values()
        for phrase in table
    )
)
_ALREADY_APPLIED_TEXT_PHRASES: tuple[str, ...] = tuple(
    dict.fromkeys(
        phrase for locales in ALREADY_APPLIED_PHRASES.values() for phrase in locales
    )
)
_CLOSED_TEXT_PHRASES: tuple[str, ...] = tuple(
    dict.fromkeys(
        phrase for locales in CLOSED_PHRASES.values() for phrase in locales
    )
)


def _matched(text: str, phrases: tuple[str, ...]) -> list[str]:
    """Every phrase present in the page's visible text, in table order."""
    return [phrase for phrase in phrases if phrase in text]


def assess_page(*, url: str, title: str, html: str) -> PageAssessment:
    """Decide what kind of page this snapshot is.

    Pure: a function of (url, title, html) alone, replayable over kept page
    copies with no browser. Never raises on a malformed snapshot — partial
    facts yield the UNKNOWN kind, not an exception.
    """
    challenge = assess_challenge(url=url, title=title, html=html)
    signals: list[str] = list(challenge.signals)
    vendors = challenge.vendors
    detail = challenge.detail
    url_l = (url or "").lower()

    # A gated challenge dominates every other identity.
    if challenge.verdict == "gated":
        return PageAssessment(
            kind=PageType.CAPTCHA_BLOCK,
            challenge="gated",
            signals=tuple(signals),
            detail=detail,
            confidence=0.95,
            vendors=vendors,
        )

    if assess_login_wall(url=url, html=html):
        signals.append("login-wall")
        return PageAssessment(
            kind=PageType.LOGIN_REQUIRED,
            challenge=challenge.verdict,
            signals=tuple(signals),
            detail=detail,
            confidence=0.90,
            vendors=vendors,
        )

    if _title_says_404(title):
        signals.append("title-404")
        return PageAssessment(
            kind=PageType.ERROR_404,
            challenge=challenge.verdict,
            signals=tuple(signals),
            detail=f"title-404 (debt: title is the only evidence); {detail}",
            confidence=0.60,
            vendors=vendors,
        )

    text = visible_page_text(html)

    already = _matched(text, _ALREADY_APPLIED_TEXT_PHRASES)
    if already:
        signals.extend(f"already-applied-phrase:{phrase}" for phrase in already)
        return PageAssessment(
            kind=PageType.ALREADY_APPLIED,
            challenge=challenge.verdict,
            signals=tuple(signals),
            detail=detail,
            confidence=0.80,
            vendors=vendors,
        )

    closed = _matched(text, _CLOSED_TEXT_PHRASES)
    if closed:
        signals.extend(f"closed-phrase:{phrase}" for phrase in closed)
        return PageAssessment(
            kind=PageType.CLOSED,
            challenge=challenge.verdict,
            signals=tuple(signals),
            detail=detail,
            confidence=0.80,
            vendors=vendors,
        )

    # A substantial form means this page IS the application. Checked before
    # JSON-LD: a form page's own schema must not demote it to a description.
    try:
        if page_has_fillable_form(html):
            signals.append("fillable-form")
            return PageAssessment(
                kind=PageType.APPLICATION_FORM,
                challenge=challenge.verdict,
                signals=tuple(signals),
                detail=detail,
                confidence=0.85,
                vendors=vendors,
            )
    except Exception:
        pass

    try:
        family = page_family(url, form_facts(html or ""))
    except Exception:
        family = PageFamily(None, 0.0, 0.0, ())
    if family.kind is PageType.HOME_PAGE:
        signals.append("family:home-page")
        signals.extend(f"family-feature:{f}" for f in family.features)
        return PageAssessment(
            kind=PageType.HOME_PAGE,
            challenge=challenge.verdict,
            signals=tuple(signals),
            detail=f"family p={family.probability} margin={family.margin}; {detail}",
            confidence=0.80,
            vendors=vendors,
        )

    confirmation = _matched(text, _CONFIRMATION_TEXT_PHRASES)
    url_markers = [marker for marker in CONFIRMATION_URL_MARKERS if marker in url_l]
    if confirmation and not url_markers and _sign_in_choices(url, html) >= 2:
        # Sign-in evidence outranks confirmation phrases (EC-42).
        signals.append("sign-in-choices")
        return PageAssessment(
            kind=PageType.LOGIN_REQUIRED,
            challenge=challenge.verdict,
            signals=tuple(signals),
            detail=detail,
            confidence=0.80,
            vendors=vendors,
        )
    if confirmation or url_markers:
        signals.extend(f"confirmation-phrase:{phrase}" for phrase in confirmation)
        signals.extend(f"confirmation-url:{marker}" for marker in url_markers)
        return PageAssessment(
            kind=PageType.SUCCESS_PAGE,
            challenge=challenge.verdict,
            signals=tuple(signals),
            detail=detail,
            confidence=0.90 if url_markers else 0.80,
            vendors=vendors,
        )

    if _has_job_posting_json_ld(html or ""):
        signals.append("json-ld-jobposting")
        return PageAssessment(
            kind=PageType.JOB_DESCRIPTION,
            challenge=challenge.verdict,
            signals=tuple(signals),
            detail=detail,
            confidence=0.80,
            vendors=vendors,
        )

    if family.kind is PageType.SERP:
        signals.append("family:results-list")
        signals.extend(f"family-feature:{f}" for f in family.features)
        return PageAssessment(
            kind=PageType.SERP,
            challenge=challenge.verdict,
            signals=tuple(signals),
            detail=f"family p={family.probability} margin={family.margin}; {detail}",
            confidence=0.70,
            vendors=vendors,
        )

    signals.append("no-structural-verdict")
    return PageAssessment(
        kind=PageType.UNKNOWN,
        challenge=challenge.verdict,
        signals=tuple(signals),
        detail=detail,
        confidence=0.0,
        vendors=vendors,
    )
