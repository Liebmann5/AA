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
        8. Anything else is UNKNOWN — an honest answer, not a failure.

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

import re
from dataclasses import dataclass

from auto_apply.domain.services.apply_target import page_has_fillable_form
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


def _title_says_404(title: str) -> bool:
    """DEBT: title words are the only measured 404 evidence (module docstring)."""
    text = (title or "").lower()
    return "404" in text or "page not found" in text


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

    confirmation = _matched(text, _CONFIRMATION_TEXT_PHRASES)
    url_markers = [marker for marker in CONFIRMATION_URL_MARKERS if marker in url_l]
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

    signals.append("no-structural-verdict")
    return PageAssessment(
        kind=PageType.UNKNOWN,
        challenge=challenge.verdict,
        signals=tuple(signals),
        detail=detail,
        confidence=0.0,
        vendors=vendors,
    )
