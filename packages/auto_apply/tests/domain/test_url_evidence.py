"""Pins for fail-closed URL evidence classification.

Every URL in this file is synthetic. The shapes are the point: first-party
advertising carried in query keys, relative hrefs, wrappers with decodable
and opaque payloads, and groups of apply-intent routes. No fixture contains
a real provider's class names, hosts, or attribute values.
"""

from __future__ import annotations

import base64

import pytest

from auto_apply.domain.ports.page_understanding_port import (
    CardResolutionState,
    JobUrlCandidate,
)
from auto_apply.domain.services.url_evidence import (
    advertising_evidence,
    canonical_url,
    decide_resolution_state,
    evaluate_candidates,
    has_pending_redirect,
    merge_candidates,
    merge_rejections,
    resolve_href,
    unwrap,
)

PAGE_URL = "https://serp.example.com/search"
SERP_HOST = "serp.example.com"


def _evaluate(items, title="Senior Marine Engineer"):
    return evaluate_candidates(
        items, title=title, serp_host=SERP_HOST, base_url=PAGE_URL
    )


# ─────────────────────────────────────────────────────────────────────────────
# D3 — relative hrefs resolve against the page URL
# ─────────────────────────────────────────────────────────────────────────────


def test_relative_href_resolved_against_page_url() -> None:
    assert resolve_href("/openings/eng-101", PAGE_URL) == (
        "https://serp.example.com/openings/eng-101"
    )
    candidates, rejections = _evaluate(
        [{"href": "/openings/eng-101", "text": "Apply now", "source": "static"}]
    )
    assert rejections == ()
    assert len(candidates) == 1
    assert candidates[0].url == "https://serp.example.com/openings/eng-101"


# ─────────────────────────────────────────────────────────────────────────────
# D1 — advertising evidence read from the whole URL
# ─────────────────────────────────────────────────────────────────────────────


def test_first_party_ad_query_tokens_rejected() -> None:
    """An ad on the results host itself must still be rejected.

    The signal is in the query keys (ad_domain / ad_provider / ad_type
    shapes), not in the hostname — a host-only rejector misses this.
    """
    href = (
        "https://serp.example.com/y.js"
        "?ad_domain=shopexample.co&ad_provider=netads&ad_type=txad"
    )
    candidates, rejections = _evaluate(
        [{"href": href, "text": "Senior Marine Engineer", "source": "static"}]
    )
    assert candidates == ()
    assert len(rejections) == 1
    assert "advertising" in rejections[0].reason.lower()
    assert any("query key" in e for e in rejections[0].evidence)


def test_adobe_admin_read_not_flagged() -> None:
    """Tokenization guard: 'adobe', 'admin', and 'read' contain no ad token."""
    items = [
        {"href": "https://www.adobe-example.com/jobs/1", "text": "Apply now", "source": "static"},
        {"href": "https://boards.example.org/admin/jobs/2", "text": "Apply now", "source": "static"},
        {"href": "https://boards.example.org/read/jobs/3", "text": "Apply now", "source": "static"},
    ]
    candidates, rejections = _evaluate(items)
    assert rejections == ()
    assert len(candidates) == 3


def test_ad_path_token_rejected() -> None:
    href = "https://boards.example.org/ads/click?id=9"
    evidence = advertising_evidence(href)
    assert any("path segment" in e for e in evidence)


@pytest.mark.parametrize(
    "href",
    [
        "https://ads.example.net/x",
        "https://doubleclick.example.org/r",
        "https://adserver.example.io/c",
    ],
)
def test_ad_host_labels_rejected(href: str) -> None:
    candidates, rejections = _evaluate(
        [{"href": href, "text": "Apply now", "source": "static"}]
    )
    assert candidates == ()
    assert "advertising" in rejections[0].reason.lower()


# ─────────────────────────────────────────────────────────────────────────────
# Scheme / fragment / dead-end rejection
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "href",
    [
        "javascript:void(0)",
        "mailto:jobs@example.com",
        "tel:+15551234567",
    ],
)
def test_denied_scheme_rejected(href: str) -> None:
    candidates, rejections = _evaluate(
        [{"href": href, "text": "Apply now", "source": "static"}]
    )
    assert candidates == ()
    assert "denied scheme" in rejections[0].reason


def test_fragment_only_rejected() -> None:
    candidates, rejections = _evaluate(
        [{"href": "#apply-panel", "text": "Apply now", "source": "static"}]
    )
    assert candidates == ()
    assert rejections[0].reason == "fragment-only URL"


@pytest.mark.parametrize("text", ["Privacy Policy", "Sign in to continue"])
def test_dead_end_text_rejected(text: str) -> None:
    candidates, rejections = _evaluate(
        [{"href": "https://boards.example.org/jobs/1", "text": text, "source": "static"}]
    )
    assert candidates == ()
    assert rejections[0].reason == "dead-end text"


# ─────────────────────────────────────────────────────────────────────────────
# Wrapper decoding ladder
# ─────────────────────────────────────────────────────────────────────────────


def test_unwrap_plain_payload() -> None:
    href = "https://redirect.example.com/out?url=https://boards.example.org/jobs/42"
    resolved, how = unwrap(href, PAGE_URL)
    assert resolved == "https://boards.example.org/jobs/42"
    assert "plain" in how


def test_unwrap_percent_encoded_payload() -> None:
    href = (
        "https://redirect.example.com/out"
        "?u=https%253A%252F%252Fboards.example.org%252Fjobs%252F43"
    )
    resolved, _how = unwrap(href, PAGE_URL)
    assert resolved == "https://boards.example.org/jobs/43"


def test_unwrap_base64_payload() -> None:
    payload = base64.urlsafe_b64encode(b"https://boards.example.org/jobs/45").decode()
    resolved, how = unwrap(
        f"https://redirect.example.com/out?u={payload}", PAGE_URL
    )
    assert resolved == "https://boards.example.org/jobs/45"
    assert "base64" in how


def test_unwrap_base64_skip1() -> None:
    payload = "q" + base64.urlsafe_b64encode(b"https://boards.example.org/jobs/46").decode()
    resolved, how = unwrap(
        f"https://redirect.example.com/out?u={payload}", PAGE_URL
    )
    assert resolved == "https://boards.example.org/jobs/46"
    assert "skip1" in how


def test_unwrap_base64_skip2() -> None:
    """The measured production shape: a two-character prefix on the payload."""
    payload = "qx" + base64.urlsafe_b64encode(b"https://boards.example.org/jobs/47").decode()
    resolved, how = unwrap(
        f"https://redirect.example.com/out?u={payload}", PAGE_URL
    )
    assert resolved == "https://boards.example.org/jobs/47"
    assert "skip2" in how


def test_opaque_payload_kept_navigable_and_pending() -> None:
    payload = "Z9xQ" * 20  # decodes to nothing resembling a URL
    href = f"https://redirect.example.com/out?u={payload}"
    resolved, how = unwrap(href, PAGE_URL)
    assert resolved == href
    assert "no decodable payload" in how
    assert has_pending_redirect(href) is True


# ─────────────────────────────────────────────────────────────────────────────
# Scoring and selection
# ─────────────────────────────────────────────────────────────────────────────


def test_apply_intent_raises_score() -> None:
    items = [
        {"href": "https://boards.example.org/jobs/9", "text": "Apply now", "source": "static"},
        {"href": "https://boards.example.org/jobs/9", "text": "Learn more", "source": "static"},
    ]
    candidates, _ = _evaluate(items)
    by_text = {c.anchor_text: c for c in candidates}
    assert by_text["Apply now"].score > by_text["Learn more"].score
    assert by_text["Apply now"].apply_intent is True
    assert by_text["Learn more"].apply_intent is False


def test_single_eligible_candidate_resolves() -> None:
    candidates, _ = _evaluate(
        [{"href": "/openings/eng-101", "text": "Apply now", "source": "static"}]
    )
    state, selected = decide_resolution_state(candidates, (), material_seen=True)
    assert state is CardResolutionState.RESOLVED
    assert selected is not None
    assert selected.url == "https://serp.example.com/openings/eng-101"


def test_multi_apply_wrappers_become_multi_route() -> None:
    """Several legitimate apply-intent routes with no title signal must not
    collapse into a guess — the card keeps them all and selects nothing."""
    items = [
        {"href": f"/out?u={'Z9xQ' * 20}{i}", "text": "Apply now", "source": "revealed"}
        for i in range(3)
    ]
    candidates, _ = _evaluate(items)
    assert len(candidates) == 3
    state, selected = decide_resolution_state(candidates, (), material_seen=True)
    assert state is CardResolutionState.MULTI_ROUTE
    assert selected is None


def test_title_aligned_winner_by_margin_resolves() -> None:
    items = [
        {
            "href": "https://boards.example.org/jobs/senior-marine-engineer",
            "text": "Apply now",
            "source": "static",
        },
        {"href": "https://other.example.net/click/123", "text": "Apply now", "source": "static"},
        {"href": "https://third.example.net/go/456", "text": "Apply now", "source": "static"},
    ]
    candidates, _ = _evaluate(items)
    state, selected = decide_resolution_state(candidates, (), material_seen=True)
    assert state is CardResolutionState.RESOLVED
    assert selected is not None
    assert selected.title_overlap >= 0.5


def test_below_threshold_candidate_is_never_selected() -> None:
    items = [
        {"href": "https://serp.example.com/about", "text": "View details", "source": "static"}
    ]
    candidates, _ = _evaluate(items)
    assert candidates and candidates[0].score < 0.5
    state, selected = decide_resolution_state(candidates, (), material_seen=True)
    assert state is CardResolutionState.DEFERRED
    assert selected is None


def test_no_candidates_states() -> None:
    state, _ = decide_resolution_state((), (), material_seen=False)
    assert state is CardResolutionState.NO_DESTINATION
    state, _ = decide_resolution_state((), (), material_seen=True)
    assert state is CardResolutionState.DEFERRED


# ─────────────────────────────────────────────────────────────────────────────
# Canonical identity and merge behaviour
# ─────────────────────────────────────────────────────────────────────────────


def test_canonical_url_normalization() -> None:
    assert canonical_url("HTTP://Example.COM:80/a/../b?z=1&a=2#frag") == (
        "http://example.com/b?a=2&z=1"
    )


def _candidate(url: str, score: float) -> JobUrlCandidate:
    return JobUrlCandidate(
        url=url,
        original_url=url,
        anchor_text="",
        source="static",
        score=score,
        canonical_url=canonical_url(url),
    )


def test_merge_candidates_dedups_by_canonical_url() -> None:
    merged = merge_candidates(
        (_candidate("http://example.com:80/jobs/1", 1.0),),
        (_candidate("http://example.com/jobs/1", 2.0),),
    )
    assert len(merged) == 1
    assert merged[0].score == 2.0


def test_merge_rejections_dedups_by_url_and_reason() -> None:
    from auto_apply.domain.ports.page_understanding_port import JobUrlRejection

    merged = merge_rejections(
        (JobUrlRejection("http://example.com:80/a", "", "advertising evidence"),),
        (JobUrlRejection("http://example.com/a", "", "advertising evidence"),),
    )
    assert len(merged) == 1
