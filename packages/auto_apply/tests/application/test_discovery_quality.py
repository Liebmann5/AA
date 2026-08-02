"""Pins for Stage 8e — discovery stops manufacturing jobs out of navigation.

Live run 4 was the first with the fast SERP route working: a Google harvest
went from 42 s to 0.6 s. It also enqueued **61 records and vetted every one to
FAIL**, because all 61 were site furniture — Google's tab bar and filter chips
(``All``, ``Images``, ``Forums``, ``Remote``, ``No degree``, ``Date posted``),
Indeed's ``Find jobs`` / ``Company Reviews``, Bing's ``Rewards``.

Three separate defects produced that, and this file pins all three.

**A — a placeholder defeated the guard.** ``_extract_job_cards`` built
``JobCardInfo(title=title or "Unknown", ...)``. ``"Unknown"`` is truthy, so
every title-less card walked straight through
``PageUnderstandingExtractor``'s ``if not (title and url)`` — the guard whose
entire job was to drop it. Its sibling signal, ``confidence=0.5``, was written
and never read by anybody.

**A2 — nothing said a title was missing.** Titles came out empty because the
extractor looked only at ``h1``-``h6``; Google's jobs vertical marks card
titles with ``role="heading"``, which ``google.py`` already knew — it lists
``div[role='heading']`` first among the selectors it injects into
SemanticMiner. Once the placeholder goes, a route that drops everything has to
say so, or it is indistinguishable from an empty page.

**B — the auditor called it a pass.** ``DiscoveryVerifier`` checked fields,
dedup and cap. A tab bar has a title, a company and an http URL, so it passed
all three, and four live runs reported ``[PASS]`` over feeds made entirely of
navigation.

**C — a routine no-op logged as data loss.** ``record_job_discovery`` promised
"False if it already existed" but issued a bare ``INSERT``, so re-finding a
known job raised ``IntegrityError`` and surfaced as two ERROR lines per repeat.

Pin labelling, measured against the pre-stage tree rather than assumed —
**7 failed, 6 passed** there. Of the 7, four fail on behaviour
(``test_a_card_without_a_heading_gets_no_title``,
``test_an_aria_heading_is_a_title``, ``test_the_drop_is_reported``,
``test_rediscovering_a_known_job_is_not_an_error``) and three fail because the
``chrome`` check does not exist yet, which is a weaker kind of evidence and is
labelled as such rather than counted as four more teeth.

``test_title_less_cards_are_dropped_by_the_extractor`` passes on BOTH trees,
and that is the point of it: ``PageUnderstandingExtractor``'s guard was never
broken. It was handed a truthy ``"Unknown"`` and did exactly what it was told.
"""

import sqlite3

import pytest

from auto_apply.adapters.secondary.discovery.components.page_understanding_extractor import (  # noqa: E501
    PageUnderstandingExtractor,
)
from auto_apply.adapters.secondary.perception.math_dom_adapter import (
    MathPageUnderstandingAdapter,
)
from auto_apply.application.services.auditing.discovery_verification import (
    DiscoveryVerifier,
)
from auto_apply.domain.models.job import Job
from auto_apply.domain.models.math_dom import DOMNode, Geometry
from auto_apply.domain.ports.page_understanding_port import JobCardInfo, SERPStructure


def _geo(i: int = 0) -> Geometry:
    return Geometry(x=10.0, y=float(i), width=280.0, height=90.0)


def _job(title="Backend Engineer", company="Acme", url="https://acme.test/j/1"):
    return Job(title=title, company=company, url=url, source="Google")


class _StubPageUnderstanding:
    def __init__(self, cards):
        self._cards = cards

    def analyze_serp(self, _context):
        return SERPStructure(job_cards=tuple(self._cards))


class _StubBrowser:
    current_url = "https://www.google.com/search?q=engineer&udm=8"
    title = "engineer jobs - Google Search"


# ===========================================================================
# A — the "Unknown" placeholder, and ARIA headings
# ===========================================================================


def test_a_card_without_a_heading_gets_no_title():
    """TOOTH. The placeholder must not stand in for a title.

    ``_extract_job_cards`` is a staticmethod, so it is callable directly with
    the node list ``MathFormUnderstandingService`` would have handed it.
    """
    chip = DOMNode(
        tag="div",
        text="No degree",
        geometry=_geo(1),
        children=(
            DOMNode(
                tag="a",
                text="No degree",
                attributes=(("href", "/search?q=x"),),
                geometry=_geo(2),
            ),
        ),
    )

    cards = MathPageUnderstandingAdapter._extract_job_cards(
        [chip], "https://www.google.com/search"
    )

    assert cards, "fixture produced no card at all"
    assert cards[0].title == "", (
        f"A card with no heading came back with title={cards[0].title!r}. "
        f"'Unknown' is truthy, so it passes PageUnderstandingExtractor's "
        f"`if not (title and url)` guard — the guard that exists to drop "
        f"exactly this. Live run 4 enqueued 61 such records, every one of them "
        f"a tab bar entry or a filter chip."
    )


def test_an_aria_heading_is_a_title():
    """TOOTH. Google marks job titles with role='heading', not h1-h6."""
    card = DOMNode(
        tag="div",
        geometry=_geo(1),
        children=(
            DOMNode(
                tag="div",
                text="Senior Backend Engineer",
                attributes=(("role", "heading"),),
                geometry=_geo(2),
            ),
            DOMNode(tag="span", text="Acme Corp", geometry=_geo(3)),
            DOMNode(
                tag="a",
                attributes=(("href", "https://acme.test/jobs/9"),),
                geometry=_geo(4),
            ),
        ),
    )

    cards = MathPageUnderstandingAdapter._extract_job_cards(
        [card], "https://www.google.com/search"
    )

    assert cards[0].title == "Senior Backend Engineer", (
        f"title={cards[0].title!r}. _extract_job_cards looks only at h1-h6, but "
        f"google.py lists div[role='heading'] FIRST among the title selectors "
        f"it injects into SemanticMiner — the codebase already knows where "
        f"Google puts titles. Real job cards therefore produced no title, which "
        f"is how the 'Unknown' placeholder came to be doing the work."
    )


def test_an_h_tag_is_still_a_title():
    """Behaviour-preserving: the original heading rule still holds."""
    card = DOMNode(
        tag="div",
        geometry=_geo(1),
        children=(
            DOMNode(tag="h3", text="Platform Engineer", geometry=_geo(2)),
            DOMNode(tag="span", text="Globex", geometry=_geo(3)),
            DOMNode(
                tag="a",
                attributes=(("href", "https://globex.test/j/2"),),
                geometry=_geo(4),
            ),
        ),
    )

    cards = MathPageUnderstandingAdapter._extract_job_cards([card], "https://x.test")

    assert cards[0].title == "Platform Engineer"


def test_an_empty_heading_is_not_a_title():
    """Behaviour-preserving: a heading with no text must not win."""
    card = DOMNode(
        tag="div",
        geometry=_geo(1),
        children=(
            DOMNode(tag="h2", text="   ", geometry=_geo(2)),
            DOMNode(tag="span", text="Real Title Here", geometry=_geo(3)),
        ),
    )

    cards = MathPageUnderstandingAdapter._extract_job_cards([card], "https://x.test")

    assert cards[0].title != "   "


def test_company_still_falls_back_to_unknown():
    """Behaviour-preserving: only *title* loses its placeholder.

    SemanticMiner._extract_single_job also writes "Unknown" for a missing
    company, and the two routes must agree about what a job record looks like
    or the fallback becomes incomparable.
    """
    card = DOMNode(
        tag="div",
        geometry=_geo(1),
        children=(
            DOMNode(tag="h3", text="Data Engineer", geometry=_geo(2)),
            DOMNode(
                tag="a",
                attributes=(("href", "https://x.test/j/3"),),
                geometry=_geo(3),
            ),
        ),
    )

    cards = MathPageUnderstandingAdapter._extract_job_cards([card], "https://x.test")

    assert cards[0].company == "Unknown"


# ===========================================================================
# A2 — the extractor drops title-less cards, and says so
# ===========================================================================


def test_title_less_cards_are_dropped_by_the_extractor():
    """TOOTH. End to end: a card with no title must not become a Job."""
    extractor = PageUnderstandingExtractor(
        page_understanding=_StubPageUnderstanding(
            [
                JobCardInfo(title="", company="Images", url="https://g.test/i"),
                JobCardInfo(
                    title="Backend Engineer",
                    company="Acme",
                    url="https://acme.test/j/1",
                ),
            ]
        ),
        browser=_StubBrowser(),
    )

    jobs = extractor.mine_jobs(source_name="Google")

    assert [j.title for j in jobs] == ["Backend Engineer"]


def test_the_drop_is_reported(caplog):
    """TOOTH. A route that discards everything must not look like an empty page."""
    extractor = PageUnderstandingExtractor(
        page_understanding=_StubPageUnderstanding(
            [JobCardInfo(title="", company="Forums", url="https://g.test/f")]
        ),
        browser=_StubBrowser(),
    )

    with caplog.at_level("INFO"):
        jobs = extractor.mine_jobs(source_name="Google")

    assert jobs == []
    assert any("dropped (no title)" in r.getMessage() for r in caplog.records), (
        "The extractor discarded every card and logged nothing. Per-card audit "
        "rows go to the observer, which does not reach the console anyone reads, "
        "so 'found nothing' and 'threw everything away' were the same line."
    )


def test_a_clean_harvest_stays_quiet(caplog):
    """Behaviour-preserving: no drop, no extra log line."""
    extractor = PageUnderstandingExtractor(
        page_understanding=_StubPageUnderstanding(
            [JobCardInfo(title="SRE", company="Acme", url="https://acme.test/j/4")]
        ),
        browser=_StubBrowser(),
    )

    with caplog.at_level("INFO"):
        jobs = extractor.mine_jobs(source_name="Google")

    assert len(jobs) == 1
    assert not any("dropped" in r.getMessage() for r in caplog.records)


# ===========================================================================
# B — the verifier can see navigation
# ===========================================================================


def test_title_equal_to_company_is_navigation():
    """TOOTH. Indeed's 'Find jobs' and Bing's 'Rewards' have this exact shape."""
    report = DiscoveryVerifier(max_results=None).verify(
        [
            _job(),
            Job(
                title="Find jobs",
                company="Find jobs",
                url="https://www.indeed.com/find",
                source="Indeed",
            ),
        ]
    )

    chrome = next(c for c in report.checks if c.name == "chrome")
    assert not chrome.passed, (
        "A record whose title and company are the same string passed "
        "verification. A real posting names a role and an employer; those are "
        "not the same string. Four live runs reported [PASS] over feeds made "
        "entirely of navigation."
    )
    assert "Find jobs" in chrome.detail


def test_a_job_url_on_the_search_engine_is_navigation():
    """TOOTH. A posting is never served from google.com."""
    report = DiscoveryVerifier(max_results=None).verify(
        [Job(title="Short videos", company="Google", url="https://www.google.com/vid",
             source="Google")]
    )

    chrome = next(c for c in report.checks if c.name == "chrome")
    assert not chrome.passed
    assert "search engine" in chrome.detail


def test_indeed_postings_are_not_treated_as_navigation():
    """TOOTH. The rule must not eat the real jobs it sits next to.

    Indeed is deliberately absent from the search-engine host list: real
    postings do live on indeed.com. Getting this wrong would delete the only
    provider that has ever produced genuine results.
    """
    report = DiscoveryVerifier(max_results=None).verify(
        [
            Job(
                title="Backend Engineer",
                company="Acme Corp",
                url="https://www.indeed.com/viewjob?jk=abc123",
                source="Indeed",
            )
        ]
    )

    chrome = next(c for c in report.checks if c.name == "chrome")
    assert chrome.passed, chrome.detail


def test_a_clean_feed_passes_every_check():
    """Behaviour-preserving: the new check must not fire on real jobs."""
    report = DiscoveryVerifier(max_results=None).verify([_job(), _job(url="https://b.test/2")])

    assert report.passed, [c.detail for c in report.checks if not c.passed]


# ===========================================================================
# C — re-discovery is a no-op, not an error
# ===========================================================================


def test_rediscovering_a_known_job_is_not_an_error():
    """TOOTH. The second insert used to raise IntegrityError.

    Exercised against the real schema statement rather than the DatabaseManager,
    so the pin needs no temp directory and no manager lifecycle — the behaviour
    under test is the SQL, and OR IGNORE is what makes rowcount mean what
    ``record_job_discovery``'s docstring already promises.
    """
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE job_history (url_hash TEXT PRIMARY KEY, url TEXT, "
        "company TEXT, title TEXT, status TEXT, applied_at TEXT)"
    )

    from auto_apply.adapters.secondary.persistence import database as db_module

    src = db_module.DatabaseManager.record_job_discovery.__doc__ or ""
    assert "already existed" in src, "docstring moved; re-check this pin's premise"

    import inspect

    body = inspect.getsource(db_module.DatabaseManager.record_job_discovery)
    assert "INSERT OR IGNORE INTO job_history" in body, (
        "record_job_discovery issues a bare INSERT, so re-finding a job you "
        "already know raises IntegrityError and surfaces as two ERROR lines: "
        "'Database transaction failed' and 'Failed to record job discovery'. "
        "Re-discovery is the normal case on every repeat search."
    )

    row = ("h1", "https://x.test/1", "Acme", "Eng", "DISCOVERED", "now")
    first = conn.execute(
        "INSERT OR IGNORE INTO job_history VALUES (?,?,?,?,?,?)", row
    )
    assert first.rowcount == 1
    second = conn.execute(
        "INSERT OR IGNORE INTO job_history VALUES (?,?,?,?,?,?)", row
    )
    assert second.rowcount == 0, "OR IGNORE must report 0 rows, not raise"
    conn.close()


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-q"])
