"""S8k pins — silent-degradation detector.

Pin labels (honest, per standing method):
  1-4  COVERAGE — the detector is NEW code; pre-stage these fail on
       ImportError, which is weak evidence. They specify the guard's
       contract: bench on dual collapse, collect-only when the baseline is
       immature, never bench on a single-metric dip, never act when
       deterministic.
  5    TEETH — strategy integration: GenericSERPStrategy pre-stage has no
       degradation_detector kwarg, so construction raises TypeError -> fails
       on the old tree for a structural reason. Post-stage, a benched
       provider returns [] and the miner is never invoked.
  6    BEHAVIOUR-PRESERVING — an unwired strategy (detector=None) mines and
       returns jobs exactly as before, on both trees.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
from auto_apply.adapters.secondary.dom.classifier import PageType

import pytest

from auto_apply.adapters.secondary.discovery.strategies.serp_strategy import (
    GenericSERPStrategy,
)
from auto_apply.adapters.secondary.persistence.harvest_baseline_repository import (
    HarvestBaseline,
    HarvestBaselineRepository,
)
from auto_apply.application.services.auditing.degradation_detector import (
    SilentDegradationDetector,
)
from auto_apply.domain.models.job import Job


def _job() -> Job:
    return Job(
        title="Engineer", company="Acme",
        url="https://acme.example/1", source="test",
    )


class _FakeStore:
    def __init__(self, baseline=None):
        self._baseline = baseline
        self.recorded: list = []

    def get_baseline(self, provider):
        return self._baseline

    def record_harvest(self, provider, visible, page_bytes, elapsed):
        self.recorded.append((provider, visible, page_bytes, elapsed))


_MATURE = HarvestBaseline(
    avg_visible=20.0, avg_page_bytes=100_000.0,
    avg_elapsed_seconds=40.0, sample_count=5,
)


# --------------------------------------------------------------------------
# Pins 1-4 (COVERAGE): detector contract
# --------------------------------------------------------------------------

def test_dual_collapse_benches_provider():
    store = _FakeStore(_MATURE)
    det = SilentDegradationDetector(store)
    det.evaluate_first_harvest(
        provider="Indeed", visible_count=2, page_bytes=20_000,
        elapsed_seconds=2.2, route="fallback:empty",
    )
    assert det.is_benched("Indeed")
    assert store.recorded == [], "a benched harvest must not enter the baseline"


def test_immature_baseline_records_without_benching():
    store = _FakeStore(None)
    det = SilentDegradationDetector(store)
    det.evaluate_first_harvest(
        provider="Indeed", visible_count=0, page_bytes=500,
        elapsed_seconds=1.0, route="fast",
    )
    assert not det.is_benched("Indeed")
    assert len(store.recorded) == 1


def test_single_signal_dip_does_not_bench():
    # Yield collapses but the page is full-size: legitimately sparse query.
    store = _FakeStore(_MATURE)
    det = SilentDegradationDetector(store)
    det.evaluate_first_harvest(
        provider="Indeed", visible_count=2, page_bytes=95_000,
        elapsed_seconds=30.0, route="miner",
    )
    assert not det.is_benched("Indeed")
    assert len(store.recorded) == 1, "healthy harvests must refresh the baseline"


def test_deterministic_run_never_writes_and_never_benches():
    store = _FakeStore(_MATURE)
    det = SilentDegradationDetector(store, deterministic=True)
    det.evaluate_first_harvest(
        provider="Indeed", visible_count=0, page_bytes=0,
        elapsed_seconds=0.5, route="fast",
    )
    assert not det.is_benched("Indeed")
    assert store.recorded == []


def test_baseline_store_round_trip(tmp_path):
    repo = HarvestBaselineRepository(tmp_path / "baselines.db")
    assert repo.get_baseline("Google") is None
    repo.record_harvest("Google", 20, 100_000, 40.0)
    repo.record_harvest("Google", 10, 50_000, 20.0)
    base = repo.get_baseline("Google")
    assert base is not None and base.sample_count == 2
    assert base.avg_visible == pytest.approx(18.0)   # EMA alpha=0.2
    assert base.avg_page_bytes == pytest.approx(90_000.0)


# --------------------------------------------------------------------------
# Pin 5 (TEETH): benched provider returns [] and never mines
# --------------------------------------------------------------------------

@patch("auto_apply.adapters.secondary.discovery.strategies.serp_strategy.PageClassifier")
def test_benched_provider_short_circuits_before_mining(mock_classifier_class):
    mock_classifier = MagicMock()
    mock_classifier.classify.return_value = PageType.SERP
    mock_classifier_class.return_value = mock_classifier

    det = SilentDegradationDetector(None)
    det._benched.add("Google")

    miner_spy = MagicMock()
    miner_spy.mine_jobs.return_value = [_job()]

    strategy = GenericSERPStrategy(
        browser=MagicMock(),
        search_prefs=None,
        source_tag="Google",
        degradation_detector=det,
    )
    strategy.miner = miner_spy

    assert strategy.execute() == []
    miner_spy.mine_jobs.assert_not_called()

# --------------------------------------------------------------------------
# Pin 6 (BEHAVIOUR-PRESERVING): unwired strategy behaves exactly as before
# --------------------------------------------------------------------------

@patch("auto_apply.adapters.secondary.discovery.strategies.serp_strategy.PageClassifier")
def test_unwired_strategy_mines_normally(mock_classifier_class):
    mock_classifier = MagicMock()
    mock_classifier.classify.return_value = PageType.SERP
    mock_classifier_class.return_value = mock_classifier
    
    miner = MagicMock()
    miner.mine_jobs.return_value = [_job()]

    strategy = GenericSERPStrategy(
        browser=MagicMock(),
        search_prefs=None,
        source_tag="Google",
    )
    strategy.miner = miner

    results = strategy.execute()
    assert len(results) == 1
    miner.mine_jobs.assert_called()