"""Guard: Bing and Indeed honor the fast-route wiring discipline.

Stage 1 of Batch 2 threads page_understanding_port into BingProvider and
IndeedProvider and has each pass a PageUnderstandingExtractor into its
GenericSERPStrategy — the same contract GoogleProvider already satisfies.
The discipline being pinned:

  * a real page-understanding adapter -> _fast_extractor() returns a
    PageUnderstandingExtractor, and that extractor is threaded into the
    strategy the provider builds;
  * a NullPageUnderstandingAdapter -> _fast_extractor() returns None, so a
    "fallback:empty" log line always means "the detector ran and found
    nothing", never "no detector was wired".
"""

import logging
from unittest.mock import Mock

from auto_apply.adapters.secondary.discovery.components.page_understanding_extractor import (
    PageUnderstandingExtractor,
)
from auto_apply.adapters.secondary.discovery.providers import bing as bing_module
from auto_apply.adapters.secondary.discovery.providers import indeed as indeed_module
from auto_apply.adapters.secondary.discovery.providers.bing import BingProvider
from auto_apply.adapters.secondary.discovery.providers.indeed import IndeedProvider
from auto_apply.domain.models.search_instruction import SearchInstruction
from auto_apply.domain.ports.page_understanding_port import (
    JobCardInfo,
    NullPageUnderstandingAdapter,
    SERPStructure,
)


def _stub_page_understanding() -> Mock:
    stub = Mock()
    stub.analyze_serp.return_value = SERPStructure(
        job_cards=(
            JobCardInfo(
                title="Software Engineer",
                company="ExampleCo",
                url="https://jobs.example/1",
            ),
        ),
    )
    return stub


def _strategy_spy(captured: dict):
    class _SpyStrategy:
        def __init__(self, *args, **kwargs):
            captured.update(kwargs)

        def execute(self):
            return []

        def run(self):
            return []

    return _SpyStrategy


def _run_provider(provider, monkeypatch, module) -> dict:
    captured: dict = {}
    monkeypatch.setattr(module, "GenericSERPStrategy", _strategy_spy(captured))
    monkeypatch.setattr(
        module.behavior, "simulate_idle_time", lambda *a, **k: None
    ) if hasattr(module, "behavior") else None
    provider.navigator = Mock()
    provider.navigator.navigate_with_fallback.return_value = True
    provider.run(SearchInstruction(title="Engineer", location="Remote"))
    return captured


def test_bing_fast_extractor_honors_real_adapter() -> None:
    provider = BingProvider(browser=Mock(), page_understanding_port=_stub_page_understanding())
    extractor = provider._fast_extractor()
    assert isinstance(extractor, PageUnderstandingExtractor)
    jobs = extractor.mine_jobs(source_name="Bing")
    assert len(jobs) == 1
    assert jobs[0].title == "Software Engineer"
    assert jobs[0].url == "https://jobs.example/1"


def test_bing_fast_extractor_null_adapter_returns_none(caplog) -> None:
    provider = BingProvider(browser=Mock(), page_understanding_port=NullPageUnderstandingAdapter())
    with caplog.at_level(logging.INFO):
        assert provider._fast_extractor() is None
    assert any("Null adapter" in r.getMessage() for r in caplog.records)


def test_indeed_fast_extractor_honors_real_adapter() -> None:
    provider = IndeedProvider(browser=Mock(), page_understanding_port=_stub_page_understanding())
    extractor = provider._fast_extractor()
    assert isinstance(extractor, PageUnderstandingExtractor)
    jobs = extractor.mine_jobs(source_name="Indeed")
    assert len(jobs) == 1
    assert jobs[0].title == "Software Engineer"


def test_indeed_fast_extractor_null_adapter_returns_none(caplog) -> None:
    provider = IndeedProvider(browser=Mock(), page_understanding_port=NullPageUnderstandingAdapter())
    with caplog.at_level(logging.INFO):
        assert provider._fast_extractor() is None
    assert any("Null adapter" in r.getMessage() for r in caplog.records)


def test_bing_threads_fast_extractor_into_strategy(monkeypatch) -> None:
    provider = BingProvider(browser=Mock(), page_understanding_port=_stub_page_understanding())
    captured = _run_provider(provider, monkeypatch, bing_module)
    assert isinstance(captured.get("fast_extractor"), PageUnderstandingExtractor)


def test_indeed_threads_fast_extractor_into_strategy(monkeypatch) -> None:
    provider = IndeedProvider(browser=Mock(), page_understanding_port=_stub_page_understanding())
    captured = _run_provider(provider, monkeypatch, indeed_module)
    assert isinstance(captured.get("fast_extractor"), PageUnderstandingExtractor)
