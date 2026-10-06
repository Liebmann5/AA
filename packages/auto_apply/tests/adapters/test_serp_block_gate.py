"""Pins for the shared block gate (D5).

A CAPTCHA/login/404 page is a blocked page, not an empty result set: both
entry paths must abort identically, the degradation guard must never see it,
and the blocked verdict is observable only when consent is active.

The verdict itself is the ONE page verdict
(domain/services/page_assessment.assess_page); these pins stub it at the
strategy's import site and pin what the strategy DOES with each answer.
The verdict's own fixtures live in tests/workflows/test_page_assessment.py.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from auto_apply.adapters.secondary.discovery.strategies import (
    serp_strategy as serp_strategy_module,
)
from auto_apply.adapters.secondary.discovery.strategies.serp_strategy import (
    GenericSERPStrategy,
)
from auto_apply.domain.services.page_assessment import PageAssessment
from auto_apply.domain.types import PageType


class _FakeBrowser:
    def __init__(self) -> None:
        self.title = "Attention required"
        self.current_url = "https://serp.example.com/challenge"
        self.page_source = ""

    def find_elements(self, by, selector):
        return []

    def execute_script(self, script, *args):
        return None

    def switch_to_default_content(self):
        return None


class _FakeFastExtractor:
    def __init__(self) -> None:
        self.mine_calls = 0

    def mine_jobs(self, source_name):
        self.mine_calls += 1
        return []

    def finalize_harvest(self, source_name):
        return []


class _SpyMiner:
    """Records every mine, and with what source_name; serves scripted feeds."""

    def __init__(self, feed=None):
        self.calls: list[str] = []
        self._feed = list(feed) if feed is not None else None

    def mine_jobs(self, source_name: str):
        self.calls.append(source_name)
        if self._feed is None:
            return []
        if self._feed:
            return self._feed.pop(0)
        return []


class _FakeDegradationDetector:
    def __init__(self) -> None:
        self.evaluations: list = []

    def is_benched(self, provider) -> bool:
        return False

    def evaluate_first_harvest(self, **kwargs) -> None:
        self.evaluations.append(kwargs)


class _FakeResearchObserver:
    def __init__(self) -> None:
        self.observations: list = []

    @property
    def is_enabled(self) -> bool:
        return True

    def observe_discovery(self, observation) -> None:
        self.observations.append(observation)


def _verdict(kind: PageType) -> PageAssessment:
    """A stubbed verdict of the given kind, as the one predicate would return."""
    return PageAssessment(
        kind=kind,
        challenge="gated" if kind is PageType.CAPTCHA_BLOCK else "clear",
        signals=("stubbed",),
        detail="stub",
        confidence=1.0,
    )


def _strategy(monkeypatch, kind: PageType, *, observer=None):
    monkeypatch.setattr(
        serp_strategy_module, "assess_page", lambda **kwargs: _verdict(kind)
    )
    fast = _FakeFastExtractor()
    degradation = _FakeDegradationDetector()
    strategy = GenericSERPStrategy(
        browser=_FakeBrowser(),
        search_prefs=None,
        source_tag="TestProvider",
        max_results=5,
        scroller=None,
        fast_extractor=fast,
        degradation_detector=degradation,
        research_observer=observer,
    )
    return strategy, fast, degradation


def test_execute_aborts_on_block_without_mining_or_evaluating(monkeypatch) -> None:
    strategy, fast, degradation = _strategy(monkeypatch, PageType.CAPTCHA_BLOCK)

    assert strategy.execute() == []
    assert fast.mine_calls == 0
    assert degradation.evaluations == []


def test_run_aborts_on_block_without_mining(monkeypatch) -> None:
    """run() previously had no block check at all — this is the D5 teeth."""
    strategy, fast, degradation = _strategy(monkeypatch, PageType.CAPTCHA_BLOCK)

    assert strategy.run() == []
    assert fast.mine_calls == 0
    assert degradation.evaluations == []


def test_blocked_page_emits_observation_when_consent_active(monkeypatch) -> None:
    observer = _FakeResearchObserver()
    strategy, _fast, _deg = _strategy(
        monkeypatch, PageType.CAPTCHA_BLOCK, observer=observer
    )

    strategy.execute()

    assert len(observer.observations) == 1
    observation = observer.observations[0]
    assert observation.blocked is True
    assert observation.page_state == "captcha_block"
    assert observation.provider == "TestProvider"
    assert observation.card_count == 0


def test_blocked_page_with_null_observer_returns_empty_without_error(monkeypatch) -> None:
    strategy, _fast, _deg = _strategy(monkeypatch, PageType.LOGIN_REQUIRED)
    assert strategy.execute() == []


def test_non_blocked_page_proceeds_and_evaluates(monkeypatch) -> None:
    strategy, fast, degradation = _strategy(monkeypatch, PageType.SERP)

    assert strategy.execute() == []
    assert fast.mine_calls == 1
    assert len(degradation.evaluations) == 1


def test_execute_mines_once_per_harvest_not_once_extra(monkeypatch) -> None:
    """The strategy pays for extraction only inside the harvest loop.

    Ported from the retired test_classifier_probe.py: the page-health check
    used to run a full extraction of its own whose answer could not reach a
    decision (~40s per SERP, measured). The scripted feed yields the same
    two jobs on every harvest, so the dry-scroll guard (limit 2) stops the
    loop after exactly three mines — one initial, two dry.
    """
    monkeypatch.setattr(
        serp_strategy_module,
        "assess_page",
        lambda **kwargs: _verdict(PageType.SERP),
    )
    jobs = [
        SimpleNamespace(url="https://example.test/1", title="Job 1", company="Acme"),
        SimpleNamespace(url="https://example.test/2", title="Job 2", company="Acme"),
    ]
    miner = _SpyMiner(feed=[list(jobs) for _ in range(12)])

    strategy = GenericSERPStrategy(
        browser=_FakeBrowser(),
        search_prefs=None,
        source_tag="ProbePin",
        max_results=100,
        dry_scroll_limit=2,
        inter_scroll_delay_s=0.0,
        scroller=MagicMock(),
    )
    strategy.miner = miner
    strategy.interruption_handler = MagicMock()

    results = strategy.execute()

    assert miner.calls == ["ProbePin", "ProbePin", "ProbePin"], miner.calls
    assert {j.url for j in results} == {j.url for j in jobs}
