
"""Pins for forced extraction-tier selection (Stage 5b).

This closes the thread that started the whole foundational-tools arc. "Cycle
miner -> pagination -> math subsystem" never mapped onto the code, because those
are complementary pipeline stages rather than interchangeable alternatives. The
real alternatives are the extraction TIERS, and until now nothing could select
one deliberately: the router chose per page, and Discovery had its own hardcoded
JSON-LD-then-mine decision.

Forcing a tier is a capability, not a default. These pins hold both halves:

    * unforced, everything selects and extracts exactly as it did;
    * forced, the chosen tier is genuinely the one that runs, and what comes out
      still satisfies the discovery verification harness.
"""
import pathlib

import pytest
from unittest.mock import MagicMock, patch

from auto_apply.application.services.auditing.discovery_verification import (
    DiscoveryVerifier,
)
from auto_apply.application.services.page_analysis_router import PageAnalysisRouter
from auto_apply.domain.models.analysis_tier import PageAnalysisTier
from auto_apply.domain.models.job import Job


def _strategy(forced_tier=None, json_ld=None, mined=None):
    from auto_apply.adapters.secondary.discovery.strategies.serp_strategy import (
        GenericSERPStrategy,
    )

    strategy = GenericSERPStrategy(
        browser=MagicMock(),
        search_prefs=None,
        source_tag="Test",
        max_results=50,
        forced_tier=forced_tier,
    )
    strategy._try_extract_json_ld = MagicMock(return_value=list(json_ld or []))
    strategy._mine_all_pages = MagicMock(
        return_value={j.url: j for j in (mined or [])}
    )
    return strategy


@pytest.fixture(autouse=True)
def _classify_as_serp(monkeypatch):
    """Stub the page classifier so these pins test forced tiers, not blocking.

    ``execute()`` and ``run()`` now classify every page before proceeding.
    A ``MagicMock`` browser makes each detection probe return a truthy mock,
    so the page reads as a CAPTCHA wall and the strategy aborts before any
    tier logic runs. These pins are about tier selection; stub the
    classifier, never weaken the gate.

    Any future pin driving ``execute()`` or ``run()`` with a MagicMock
    browser needs this same fixture.
    """
    from auto_apply.adapters.secondary.discovery.strategies import serp_strategy
    from auto_apply.domain.types import PageType

    class _AlwaysSerp:
        def __init__(self, browser, scanner) -> None:
            pass

        def classify(self):
            return PageType.SERP

    class _NoDetection:
        def __init__(self, browser) -> None:
            pass

    monkeypatch.setattr(serp_strategy, "PageClassifier", _AlwaysSerp)
    monkeypatch.setattr(serp_strategy, "DefaultDetectionStrategy", _NoDetection)


def _job(n):
    return Job(
        title=f"Engineer {n}",
        company="Acme Corp",
        url=f"https://acme.example.com/jobs/{n}",
        source="Test",
    )


# ─────────────────────────────────────────────────────────────────────────────
# BEHAVIOUR-PRESERVING DEFAULT
# ─────────────────────────────────────────────────────────────────────────────


def test_unforced_the_router_still_runs_its_own_selection():
    """The forced branch must not short-circuit the normal path.

    Spying on the scoring step is what discriminates here: a router that always
    returned a tier without scoring would pass a "returns a valid tier" check
    and fail this one.
    """
    router = PageAnalysisRouter()

    with patch.object(
        router, "_static_tier_scores", wraps=router._static_tier_scores
    ) as scored:
        router.determine_tier("https://example.test/jobs", "<html></html>")

    assert scored.called, "unforced selection skipped the scoring step"


def test_forcing_a_tier_bypasses_selection_entirely():
    router = PageAnalysisRouter(forced_tier=PageAnalysisTier.FULL_MATH_DOM)

    with patch.object(router, "_static_tier_scores") as scored:
        tier = router.determine_tier("https://example.test/jobs", "<html></html>")

    assert tier is PageAnalysisTier.FULL_MATH_DOM
    assert not scored.called, "a forced tier still paid for selection"


@pytest.mark.parametrize(
    "url,html",
    [
        ("https://example.test/careers", "<html><body>jobs</body></html>"),
        ("https://boards.greenhouse.io/acme", "<html><body>roles</body></html>"),
        (
            "https://example.test/j/1",
            '<html><script type="application/ld+json">{"@type":"JobPosting"}</script></html>',
        ),
    ],
)
def test_unforced_selection_is_unchanged_across_representative_pages(url, html):
    """Golden check: forcing nothing gives the same answer as a bare router.

    The two routers differ only in that one was given ``forced_tier=None``
    explicitly, so any divergence means the new parameter leaked into the
    default path.
    """
    bare = PageAnalysisRouter()
    explicit_none = PageAnalysisRouter(forced_tier=None)

    assert bare.determine_tier(url, html) is explicit_none.determine_tier(url, html)


def test_unforced_discovery_still_takes_the_json_ld_fast_path():
    """Discovery's default order — JSON-LD first, then mine — is untouched."""
    strategy = _strategy(forced_tier=None)

    assert strategy._json_ld_allowed() is True


def test_unforced_discovery_returns_the_json_ld_jobs_when_present():
    jobs = [_job(1), _job(2)]
    strategy = _strategy(forced_tier=None, json_ld=jobs)

    result = strategy.run()

    strategy._try_extract_json_ld.assert_called_once()
    assert result == jobs
    strategy._mine_all_pages.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# FORCING A TIER ACTUALLY ROUTES THERE
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "tier,allowed",
    [
        (None, True),
        (PageAnalysisTier.STRUCTURED_DATA, True),
        (PageAnalysisTier.KNOWN_PLATFORM, False),
        (PageAnalysisTier.CSS_EXTRACTION, False),
        (PageAnalysisTier.FULL_MATH_DOM, False),
    ],
)
def test_the_json_ld_fast_path_is_gated_by_the_forced_tier(tier, allowed):
    assert _strategy(forced_tier=tier)._json_ld_allowed() is allowed


def test_forcing_full_math_dom_skips_the_structured_fast_path():
    """Otherwise a JSON-LD page would silently never exercise the forced tier."""
    strategy = _strategy(
        forced_tier=PageAnalysisTier.FULL_MATH_DOM,
        json_ld=[_job(99)],
        mined=[_job(1), _job(2), _job(3)],
    )

    result = strategy.run()

    strategy._try_extract_json_ld.assert_not_called()
    assert {j.url for j in result} == {_job(1).url, _job(2).url, _job(3).url}


def test_forced_output_still_satisfies_the_discovery_verifier():
    """The harness from the discovery-verification work is the acceptance bar.

    Forcing a tier changes which extraction path runs; it must not change
    whether the result is real. Same three invariants: valid fields, no
    duplicates, within the resolved cap.
    """
    strategy = _strategy(
        forced_tier=PageAnalysisTier.FULL_MATH_DOM,
        json_ld=[_job(99)],
        mined=[_job(1), _job(2), _job(3)],
    )

    result = strategy.run()
    report = DiscoveryVerifier(max_results=50).verify(result)

    assert report.passed, f"forced-tier output failed verification: {report}"


# ─────────────────────────────────────────────────────────────────────────────
# DEGRADATION — a forced tier that cannot run
# ─────────────────────────────────────────────────────────────────────────────


def test_forcing_structured_data_on_a_page_without_json_ld_falls_through():
    """No JSON-LD to find is a normal harvest, not an empty result."""
    strategy = _strategy(
        forced_tier=PageAnalysisTier.STRUCTURED_DATA,
        json_ld=[],
        mined=[_job(1), _job(2)],
    )

    result = strategy.run()

    strategy._try_extract_json_ld.assert_called_once()
    assert len(result) == 2


@pytest.mark.parametrize(
    "value", [None, "", "   ", "NOT_A_TIER", "full_math", 42, "structured data"]
)
def test_an_unusable_tier_name_forces_nothing_and_never_raises(value):
    """A typo in config must not pin extraction to something unintended."""
    assert PageAnalysisTier.from_name(value) is None


@pytest.mark.parametrize(
    "value,expected",
    [
        ("FULL_MATH_DOM", PageAnalysisTier.FULL_MATH_DOM),
        ("full_math_dom", PageAnalysisTier.FULL_MATH_DOM),
        ("  Structured_Data  ", PageAnalysisTier.STRUCTURED_DATA),
        ("CSS_EXTRACTION", PageAnalysisTier.CSS_EXTRACTION),
        ("KNOWN_PLATFORM", PageAnalysisTier.KNOWN_PLATFORM),
    ],
)
def test_tier_names_parse_tolerantly(value, expected):
    assert PageAnalysisTier.from_name(value) is expected


# ─────────────────────────────────────────────────────────────────────────────
# WIRING AND SHAPE
# ─────────────────────────────────────────────────────────────────────────────


def test_the_tier_enum_lives_in_the_domain_and_is_re_exported():
    """Adapters honour a forced tier without importing an application service."""
    from auto_apply.application.services import page_analysis_router as router_module

    assert router_module.PageAnalysisTier is PageAnalysisTier


def test_the_config_key_ships_switched_off():
    yaml_text = (
        pathlib.Path(__file__).resolve().parent.parent.parent
        / "src"
        / "auto_apply"
        / "resources"
        / "config"
        / "runtime_defaults.yaml"
    ).read_text(encoding="utf-8")

    assert 'force_analysis_tier: ""' in yaml_text


def test_the_composition_root_forces_nothing_by_default():
    source = (
        pathlib.Path(__file__).resolve().parent.parent.parent
        / "src"
        / "auto_apply"
        / "infrastructure"
        / "composition_root.py"
    ).read_text(encoding="utf-8", errors="ignore")

    assert "PageAnalysisTier.from_name(" in source
    assert "forced_tier=_forced_tier" in source
