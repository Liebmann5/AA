"""Phrase tables for page-outcome kinds — locale-keyed data a translator can extend.

These tables feed the ONE page verdict (domain/services/page_assessment.py),
which matches them on VISIBLE TEXT only — never raw page source, never the
page title. They are data, not logic: to add a language, add its locale key
("fr", "de", ...) with the same outcome kinds; to add an ATS, add its table
under the locale.

Matching unions EVERY locale and every ATS, on purpose: recognition must be
language-agnostic. A French confirmation page must confirm for an
English-profile user, and a Lever confirmation phrase confirms on a
Greenhouse page — the phrases are confirmation-shaped regardless of ATS.
The per-locale, per-ATS structure exists for translators and auditors, not
for matching.

The bar for a phrase, documented so translators hold it: a phrase belongs
here only if it does NOT appear in ordinary posting or form text. The
retired raw-source scan (application_evidence.ATS_CONFIRMATION_PATTERNS)
matched against page source and carried phrases that fail that bar; they
were curated out, not carried:

    dropped "your application" (bare)   — appears on every form page; a
        submission that never navigated read as SUBMITTED (0.85).
    dropped "thank you" (bare), "we'll be in touch",
        "thank you for your interest", "we'll review"
                                          — ordinary posting text.
    dropped "application status"          — a nav link on posting pages,
        misfired already-applied.
    dropped "you applied" (bare)          — matches questions and badges.
    tightened "we received" / "we have received" → "...your".
"""

from __future__ import annotations

#: Confirmation phrases, by locale then by ATS. Matched on visible text.
CONFIRMATION_PHRASES: dict[str, dict[str, tuple[str, ...]]] = {
    "en": {
        "greenhouse": (
            "thank you for applying",
            "application submitted",
        ),
        "lever": (
            "thank you for applying",
            "application received",
        ),
        "workday": (
            "application submitted",
            "your application has been submitted",
            "we have received your",
        ),
        "ashby": (
            "thanks for applying",
            "application submitted",
            "received your application",
        ),
        "icims": (
            "application was submitted",
            "successfully submitted",
        ),
        "taleo": (
            "application submission is confirmed",
            "thank you for completing",
            "application was submitted",
        ),
        "smartrecruiters": (
            "application received",
            "we received your",
        ),
        "brassring": (
            "your application has been submitted",
        ),
        "jobvite": (
            "application submitted",
        ),
        "linkedin": (
            "application sent",
            "added to your applied jobs",
        ),
        "generic": (
            "thank you for applying",
            "application submitted",
            "application received",
            "successfully submitted",
            "application sent",
            "successfully applied",
            "your application has been",
            "we have received your",
            "received your application",
        ),
    },
}

#: Confirmation signals in the URL itself. Not localized — paths do not
#: translate. Matched against the lowercased URL. The URL fragments that
#: used to sit in ATS_CONFIRMATION_PATTERNS pretending to be text phrases.
CONFIRMATION_URL_MARKERS: tuple[str, ...] = (
    "/confirmations/",
    "/thank-you",
    "/system/templates/selfapply/",
    "/web#action/viewjobpostings",
)

#: "You already applied" phrases, by locale. Matched on visible text.
ALREADY_APPLIED_PHRASES: dict[str, tuple[str, ...]] = {
    "en": (
        "you applied on",
        "you already applied",
        "already applied",
        "already submitted",
    ),
}

#: "This posting is closed" phrases, by locale. Matched on visible text.
CLOSED_PHRASES: dict[str, tuple[str, ...]] = {
    "en": (
        "no longer accepting",
        "job closed",
        "position filled",
        "position has been filled",
        "job is closed",
        "posting expired",
    ),
}
