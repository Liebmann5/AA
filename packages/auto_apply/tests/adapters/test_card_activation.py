"""Pins for click activation and post-scroll deferred resolution.

Browsers, elements, and readiness are fakes over synthetic anchor snapshots.
No fixture touches a real page, selector, or provider string.
"""

from __future__ import annotations

from auto_apply.adapters.secondary.discovery.components.card_activation import (
    CardActivator,
)
from auto_apply.adapters.secondary.discovery.components.page_understanding_extractor import (
    PageUnderstandingExtractor,
    _is_opaque_uniform,
)
from auto_apply.domain.ports.page_understanding_port import (
    CardResolutionState,
    JobCardInfo,
    JobUrlCandidate,
    SERPStructure,
    SerpResolutionReport,
)

PAGE_URL = "https://serp.example.com/search"
SERP_HOST = "serp.example.com"


class _FakeElement:
    def __init__(self, browser) -> None:
        self._browser = browser
        self.clicked = False

    def click(self) -> None:
        self.clicked = True
        self._browser._clicked = True


class _FakeReadiness:
    def __init__(self) -> None:
        self.calls = 0

    def wait_for_dom_stable(self, timeout=None) -> bool:
        self.calls += 1
        return True


class _FakeBrowser:
    def __init__(self, before, after, *, url_after: str | None = None) -> None:
        self._before = before
        self._after = after
        self._url_before = PAGE_URL
        self._url_after = url_after or PAGE_URL
        self._clicked = False
        self.element = _FakeElement(self)
        self.title = "Search"

    def find_elements(self, by, selector):
        if by == "css selector" and selector == '[data-job-ref="k777"]':
            return [self.element]
        return []

    def execute_script(self, script, *args):
        return self._after if self._clicked else self._before

    @property
    def current_url(self) -> str:
        return self._url_after if self._clicked else self._url_before


class _FakeBrowserMulti(_FakeBrowser):
    def find_elements(self, by, selector):
        return [self.element, _FakeElement(self)]


def test_relocate_click_revealed_anchor_resolves() -> None:
    browser = _FakeBrowser(
        before=[{"href": "https://serp.example.com/home", "text": "Home"}],
        after=[
            {"href": "https://serp.example.com/home", "text": "Home"},
            {"href": "https://boards.example.org/apply/eng-9", "text": "Apply for this role"},
        ],
    )
    outcome = CardActivator(browser, readiness=_FakeReadiness()).activate(
        identity_attribute="data-job-ref",
        identity_value="k777",
        title="Structural Engineer",
        serp_host=SERP_HOST,
        page_url=PAGE_URL,
    )
    assert outcome.error == ""
    assert outcome.revealed_count == 1
    assert outcome.navigated is False
    assert len(outcome.candidates) == 1
    assert outcome.candidates[0].url == "https://boards.example.org/apply/eng-9"


def test_non_unique_relocation_aborts_without_clicking() -> None:
    browser = _FakeBrowserMulti(before=[], after=[])
    outcome = CardActivator(browser).activate(
        identity_attribute="data-job-ref",
        identity_value="k777",
        title="Structural Engineer",
        serp_host=SERP_HOST,
        page_url=PAGE_URL,
    )
    assert "matches 2" in outcome.error
    assert outcome.revealed_count == 0
    assert outcome.candidates == ()


def test_navigation_outcome_produces_navigation_candidate() -> None:
    browser = _FakeBrowser(
        before=[],
        after=[],
        url_after="https://boards.example.org/jobs/eng-9",
    )
    outcome = CardActivator(browser, readiness=_FakeReadiness()).activate(
        identity_attribute="data-job-ref",
        identity_value="k777",
        title="Structural Engineer",
        serp_host=SERP_HOST,
        page_url=PAGE_URL,
    )
    assert outcome.navigated is True
    assert len(outcome.candidates) == 1
    assert outcome.candidates[0].source == "navigation"
    assert outcome.candidates[0].url == "https://boards.example.org/jobs/eng-9"


def test_click_revealing_nothing_is_honest_empty() -> None:
    browser = _FakeBrowser(
        before=[{"href": "https://serp.example.com/home", "text": "Home"}],
        after=[{"href": "https://serp.example.com/home", "text": "Home"}],
    )
    outcome = CardActivator(browser, readiness=_FakeReadiness()).activate(
        identity_attribute="data-job-ref",
        identity_value="k777",
        title="Structural Engineer",
        serp_host=SERP_HOST,
        page_url=PAGE_URL,
    )
    assert outcome.revealed_count == 0
    assert outcome.navigated is False
    assert outcome.candidates == ()


def test_readiness_port_is_used_for_settle() -> None:
    readiness = _FakeReadiness()
    browser = _FakeBrowser(before=[], after=[])
    CardActivator(browser, readiness=readiness).activate(
        identity_attribute="data-job-ref",
        identity_value="k777",
        title="Structural Engineer",
        serp_host=SERP_HOST,
        page_url=PAGE_URL,
    )
    assert readiness.calls == 1


def test_opaque_uniform_detection() -> None:
    opaque = JobUrlCandidate(
        url="https://serp.example.com/out?u=zzzz",
        pending_redirect=True,
        method="no decodable payload; wrapper kept as navigable",
    )
    assert _is_opaque_uniform(type("O", (), {"candidates": (opaque,)})(), SERP_HOST) is True

    unwrapped = JobUrlCandidate(
        url="https://boards.example.org/jobs/1",
        pending_redirect=True,
        method="unwrapped from ?u= via base64+skip2",
    )
    assert _is_opaque_uniform(type("O", (), {"candidates": (unwrapped,)})(), SERP_HOST) is False

    external_direct = JobUrlCandidate(
        url="https://boards.example.org/jobs/2",
        pending_redirect=False,
        method="no decodable payload; wrapper kept as navigable",
    )
    assert _is_opaque_uniform(type("O", (), {"candidates": (opaque, external_direct)})(), SERP_HOST) is False

    assert _is_opaque_uniform(type("O", (), {"candidates": ()})(), SERP_HOST) is False


def test_finalize_returns_only_activation_resolved_jobs() -> None:
    resolved_card = JobCardInfo(
        title="Coastal Engineer",
        company="Waveworks",
        url="https://boards.example.org/jobs/1",
        resolution_state=CardResolutionState.RESOLVED.value,
        card_index=0,
    )
    deferred_card = JobCardInfo(
        title="Pipeline Engineer",
        company="Flowstate",
        url="",
        resolution_state=CardResolutionState.NO_DESTINATION.value,
        identity_attribute="data-job-ref",
        identity_value="k777",
        card_index=1,
    )
    structure = SERPStructure(
        job_cards=(resolved_card, deferred_card),
        resolution_report=SerpResolutionReport(learned_identity=("data-job-ref",)),
    )

    class _FakeUnderstanding:
        def analyze_serp(self, context):
            return structure

    browser = _FakeBrowser(
        before=[],
        after=[{"href": "https://boards.example.org/jobs/2", "text": "Apply for this role"}],
    )
    extractor = PageUnderstandingExtractor(
        page_understanding=_FakeUnderstanding(),
        browser=browser,
        readiness=_FakeReadiness(),
    )

    new_jobs = extractor.finalize_harvest("TestProvider")

    assert len(new_jobs) == 1
    assert new_jobs[0].title == "Pipeline Engineer"
    assert new_jobs[0].company == "Flowstate"
    assert new_jobs[0].url == "https://boards.example.org/jobs/2"
    assert new_jobs[0].source == "TestProvider"
