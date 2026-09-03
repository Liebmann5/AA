"""Pins for the shared block gate (D5).

A CAPTCHA/login/404 page is a blocked page, not an empty result set: both
entry paths must abort identically, the degradation guard must never see it,
and the blocked verdict is observable only when consent is active.
"""

from __future__ import annotations

from auto_apply.adapters.secondary.discovery.strategies import serp_strategy as serp_strategy_module
from auto_apply.adapters.secondary.discovery.strategies.serp_strategy import (
    GenericSERPStrategy,
)
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
        self.last_card_count = 0

    def mine_jobs(self, source_name):
        self.mine_calls += 1
        return []

    def finalize_harvest(self, source_name):
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


class _FakeDetectionStrategy:
    def __init__(self, browser) -> None:
        pass


def _classifier_for(page_type):
    class _FakeClassifier:
        def __init__(self, browser, scanner) -> None:
            pass

        def classify(self):
            return page_type

    return _FakeClassifier


def _strategy(monkeypatch, page_type, *, observer=None):
    monkeypatch.setattr(
        serp_strategy_module, "PageClassifier", _classifier_for(page_type)
    )
    monkeypatch.setattr(
        serp_strategy_module, "DefaultDetectionStrategy", _FakeDetectionStrategy
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
