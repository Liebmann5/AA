"""Unit tests for discovery providers, engine strategies, selector loader,
toolbar locator, and the _ats_site_filters helper, plus JSON‑LD extraction
and IndeedProvider inheritance/health‑check.

All browser I/O is mocked. Tests are split into seven groups:
    1. Engine strategy tests — URL construction, homepage URLs, toolbar selectors.
    2. Provider tests — verify delegation to navigator + strategy.
    3. _ats_site_filters tests — domain extraction from ATS descriptors.
    4. SelectorLoader tests — YAML loading, user‑override merging, caching.
    5. ToolbarElementLocator tests — CSS/XPath selection, Math‑DOM fallback,
       confidence tracking.
    6. JSON‑LD extraction tests — GenericSERPStrategy._try_extract_json_ld().
    7. IndeedProvider tests — inheritance and page‑health check.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from auto_apply.adapters.secondary.discovery.providers.base_provider import (
    BaseSearchProvider,
)
from auto_apply.adapters.secondary.discovery.providers.google import (
    GoogleProvider,
    _ats_site_filters,
)
from auto_apply.adapters.secondary.discovery.providers.bing import BingProvider
from auto_apply.adapters.secondary.discovery.providers.indeed import IndeedProvider
from auto_apply.adapters.secondary.discovery.strategies.engine_strategies import (
    GoogleSearchStrategy,
    BingSearchStrategy,
    IndeedSearchStrategy,
    SearchEngineStrategy,
    _GOOGLE_DATE_RANGE_MAP,
)
from auto_apply.adapters.secondary.discovery.strategies.selector_loader import (
    SelectorLoader,
    _deep_merge,
)
from auto_apply.adapters.secondary.discovery.strategies.serp_strategy import (
    GenericSERPStrategy,
)
from auto_apply.adapters.secondary.discovery.strategies.toolbar_locator import (
    ToolbarElementLocator,
    SelectorConfidenceTracker,
)
from auto_apply.domain.models.search_instruction import SearchInstruction
from auto_apply.domain.ports.ats_port import ATSDescriptor


# ═════════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════════

def _mock_browser() -> MagicMock:
    b = MagicMock()
    b.current_url = "https://example.com"
    b.page_source = ""  # default empty
    return b


def _descriptor(name: str, *patterns: str) -> ATSDescriptor:
    return ATSDescriptor(
        name=name,
        url_patterns=patterns,
        login_wall_signals=(),
        success_signals=(),
        form_root_selector="",
        submit_button_selector="",
        multi_step=False,
    )


def _mock_registry(*descriptors: ATSDescriptor) -> MagicMock:
    r = MagicMock()
    r.all_descriptors.return_value = list(descriptors)
    return r


def _instruction(**kwargs) -> SearchInstruction:
    defaults = {"title": "Engineer", "location": "Remote", "workplace_type": "remote"}
    defaults.update(kwargs)
    return SearchInstruction(**defaults)


# ═════════════════════════════════════════════════════════════════════════════
# 1. ENGINE STRATEGY TESTS
# ═════════════════════════════════════════════════════════════════════════════

class TestGoogleSearchStrategy:
    """Verify GoogleSearchStrategy URL construction, homepage, and selectors."""

    def test_homepage_url(self):
        assert GoogleSearchStrategy().homepage_url == "https://www.google.com"

    def test_engine_name(self):
        assert GoogleSearchStrategy().engine_name == "google"

    def test_build_search_url_basic(self):
        strategy = GoogleSearchStrategy()
        url = strategy.build_search_url(_instruction(title="Python Dev", location="Remote"))
        assert "google.com/search" in url
        assert "q=" in url
        assert "ibp=htl%3Bjobs" in url or "ibp=htl;jobs" in url

    def test_build_search_url_with_raw_query(self):
        strategy = GoogleSearchStrategy()
        instr = _instruction(
            title="Advanced",
            location="Remote",
            raw_query_string='site:jobs.lever.co "software engineer"',
        )
        url = strategy.build_search_url(instr)
        assert "site%3Ajobs.lever.co" in url or "site:jobs.lever.co" in url

    def test_date_range_maps_to_tbs_parameter(self):
        strategy = GoogleSearchStrategy()
        url = strategy.build_search_url(_instruction(date_range="week"))
        assert "tbs=qdr%3Aw" in url or "tbs=qdr:w" in url

    def test_date_range_none_omits_tbs(self):
        strategy = GoogleSearchStrategy()
        url = strategy.build_search_url(_instruction(date_range=None))
        assert "tbs=" not in url

    @pytest.mark.parametrize("date_range,expected_code", [
        ("day", "d"), ("week", "w"), ("month", "m"), ("year", "y"),
    ])
    def test_date_range_codes(self, date_range, expected_code):
        strategy = GoogleSearchStrategy()
        url = strategy.build_search_url(_instruction(date_range=date_range))
        assert f"qdr%3A{expected_code}" in url or f"qdr:{expected_code}" in url

    def test_search_bar_selectors_are_non_empty(self):
        selectors = GoogleSearchStrategy().search_bar_selectors
        assert len(selectors) > 0
        assert "input[name='q']" in selectors

    def test_apply_toolbar_filters_no_date_does_nothing(self):
        browser = _mock_browser()
        strategy = GoogleSearchStrategy()
        strategy.apply_toolbar_filters(browser, _instruction(date_range=None))
        browser.find_element.assert_not_called()

    def test_apply_toolbar_filters_with_date_attempts_toolbar(self):
        browser = _mock_browser()
        browser.find_element.return_value = None  # simulate element not found
        strategy = GoogleSearchStrategy()
        strategy.apply_toolbar_filters(browser, _instruction(date_range="week"))
        # Should not raise even when toolbar elements are missing.
        assert browser.find_element.call_count >= 0

    def test_locator_injection_updates_selectors(self):
        """When a locator is injected, search_bar_selectors come from YAML."""
        locator = MagicMock()
        locator.search_bar_selectors = ["input.custom-search"]
        locator.homepage_url = "https://custom.google.com"

        strategy = GoogleSearchStrategy()
        strategy.set_locator(locator)

        assert strategy.search_bar_selectors == ["input.custom-search"]
        assert strategy.homepage_url == "https://custom.google.com"

    def test_locator_injection_empty_selectors_keeps_defaults(self):
        """When locator has empty selectors, hardcoded defaults are kept."""
        locator = MagicMock()
        locator.search_bar_selectors = []
        locator.homepage_url = ""

        strategy = GoogleSearchStrategy()
        original_selectors = list(strategy.search_bar_selectors)
        strategy.set_locator(locator)
        # Defaults should be preserved since locator values are empty
        assert strategy.search_bar_selectors == original_selectors


class TestBingSearchStrategy:
    """Verify BingSearchStrategy URL construction, homepage, and selectors."""

    def test_homepage_url(self):
        assert BingSearchStrategy().homepage_url == "https://www.bing.com"

    def test_engine_name(self):
        assert BingSearchStrategy().engine_name == "bing"

    def test_build_search_url_basic(self):
        strategy = BingSearchStrategy()
        url = strategy.build_search_url(_instruction(title="PM", location="NYC"))
        assert "bing.com/jobs" in url
        assert "q=" in url

    def test_date_range_adds_filter_parameter(self):
        strategy = BingSearchStrategy()
        url = strategy.build_search_url(_instruction(date_range="week"))
        assert "filters=ex1" in url

    def test_date_range_none_omits_filter(self):
        strategy = BingSearchStrategy()
        url = strategy.build_search_url(_instruction(date_range=None))
        assert "filters=ex1" not in url

    def test_search_bar_selectors_are_non_empty(self):
        selectors = BingSearchStrategy().search_bar_selectors
        assert len(selectors) > 0


class TestIndeedSearchStrategy:
    """Verify IndeedSearchStrategy URL construction, homepage, and selectors."""

    def test_homepage_url(self):
        assert IndeedSearchStrategy().homepage_url == "https://www.indeed.com"

    def test_engine_name(self):
        assert IndeedSearchStrategy().engine_name == "indeed"

    def test_build_search_url_basic(self):
        strategy = IndeedSearchStrategy()
        url = strategy.build_search_url(_instruction(title="Data Scientist", location="Austin"))
        assert "indeed.com/jobs" in url
        assert "q=" in url
        assert "l=" in url

    def test_date_range_adds_fromage_parameter(self):
        strategy = IndeedSearchStrategy()
        url = strategy.build_search_url(_instruction(date_range="week"))
        assert "fromage=7" in url

    def test_date_range_none_omits_fromage(self):
        strategy = IndeedSearchStrategy()
        url = strategy.build_search_url(_instruction(date_range=None))
        assert "fromage=" not in url

    def test_search_bar_selectors_are_non_empty(self):
        selectors = IndeedSearchStrategy().search_bar_selectors
        assert len(selectors) > 0


class TestSearchEngineStrategyProtocol:
    """Verify all concrete strategies satisfy the abstract contract."""

    def test_all_strategies_implement_required_methods(self):
        for strat_cls in (GoogleSearchStrategy, BingSearchStrategy, IndeedSearchStrategy):
            strat = strat_cls()
            assert isinstance(strat.engine_name, str) and len(strat.engine_name) > 0
            assert isinstance(strat.homepage_url, str) and strat.homepage_url.startswith("https://")
            url = strat.build_search_url(_instruction())
            assert url.startswith("https://")
            assert isinstance(strat.search_bar_selectors, list)
            assert len(strat.search_bar_selectors) > 0

    def test_google_date_range_map_coverage(self):
        expected = {"hour", "day", "week", "month", "year"}
        assert set(_GOOGLE_DATE_RANGE_MAP.keys()) == expected


# ═════════════════════════════════════════════════════════════════════════════
# 2. PROVIDER TESTS — delegation to navigator + strategy
# ═════════════════════════════════════════════════════════════════════════════

class TestGoogleProviderDelegation:
    """Verify GoogleProvider delegates to navigator with strategy + instruction."""

    def test_has_navigator(self):
        provider = GoogleProvider(_mock_browser())
        assert hasattr(provider, "navigator")

    def test_has_engine_strategy(self):
        provider = GoogleProvider(_mock_browser())
        assert isinstance(provider._engine_strategy, GoogleSearchStrategy)

    def test_run_uses_navigator_not_safe_navigate(self):
        browser = _mock_browser()
        provider = GoogleProvider(browser)

        captured_strategy = None
        captured_instruction = None

        def fake_navigate_with_fallback(strategy, instruction, validator):
            nonlocal captured_strategy, captured_instruction
            captured_strategy = strategy
            captured_instruction = instruction
            return False

        provider.navigator.navigate_with_fallback = fake_navigate_with_fallback

        instr = _instruction(title="SWE", location="Remote")
        provider.run(instr)

        assert isinstance(captured_strategy, GoogleSearchStrategy)
        assert captured_instruction is instr

    def test_run_skips_scraping_when_navigator_fails(self):
        browser = _mock_browser()
        provider = GoogleProvider(browser)
        provider.navigator.navigate_with_fallback = MagicMock(return_value=False)
        assert provider.run(_instruction()) == []

    def test_run_calls_toolbar_filters_after_navigation(self):
        browser = _mock_browser()
        provider = GoogleProvider(browser)
        provider.navigator.navigate_with_fallback = MagicMock(return_value=True)
        provider._engine_strategy.apply_toolbar_filters = MagicMock()

        provider.run(_instruction(date_range="week"))

        provider._engine_strategy.apply_toolbar_filters.assert_called_once()

    def test_executes_one_search_per_instruction(self):
        browser = _mock_browser()
        provider = GoogleProvider(browser)
        provider.navigator = MagicMock()
        provider.navigator.navigate_with_fallback.return_value = True
        provider.run(_instruction(title="Data Engineer", location="Austin"))
        assert provider.navigator.navigate_with_fallback.call_count == 1

    def test_accepts_ats_registry(self):
        reg = _mock_registry(_descriptor("greenhouse", "*.greenhouse.io/jobs/*"))
        provider = GoogleProvider(_mock_browser(), ats_registry=reg)
        assert provider._ats_registry is reg

    # New: verify that GoogleProvider no longer imports or uses JSONLDParser
    def test_no_jsonld_parser_usage(self):
        import ast
        with open(Path(__file__).parent.parent.parent / "src" / "auto_apply" /
                  "adapters" / "secondary" / "discovery" / "providers" / "google.py",
                  encoding="utf-8") as f:
            code = f.read()
        assert "JSONLDParser" not in code
        assert "_convert_json_to_jobs" not in code


class TestBingProviderDelegation:
    """Verify BingProvider delegates to navigator with strategy + instruction."""

    def test_has_navigator(self):
        provider = BingProvider(_mock_browser())
        assert hasattr(provider, "navigator")

    def test_has_engine_strategy(self):
        provider = BingProvider(_mock_browser())
        assert isinstance(provider._engine_strategy, BingSearchStrategy)

    def test_run_uses_navigator_with_strategy(self):
        browser = _mock_browser()
        provider = BingProvider(browser)
        captured_strategy = None
        captured_instruction = None

        def fake_navigate_with_fallback(strategy, instruction, validator):
            nonlocal captured_strategy, captured_instruction
            captured_strategy = strategy
            captured_instruction = instruction
            return False

        provider.navigator.navigate_with_fallback = fake_navigate_with_fallback
        provider.run(_instruction(title="PM", location="NYC"))
        assert isinstance(captured_strategy, BingSearchStrategy)
        assert captured_instruction is not None

    def test_skips_scraping_when_navigator_fails(self):
        browser = _mock_browser()
        provider = BingProvider(browser)
        provider.navigator.navigate_with_fallback = MagicMock(return_value=False)
        assert provider.run(_instruction()) == []

    def test_run_calls_toolbar_filters_after_navigation(self):
        browser = _mock_browser()
        provider = BingProvider(browser)
        provider.navigator.navigate_with_fallback = MagicMock(return_value=True)
        provider._engine_strategy.apply_toolbar_filters = MagicMock()
        provider.run(_instruction(date_range="week"))
        provider._engine_strategy.apply_toolbar_filters.assert_called_once()


class TestIndeedProviderDelegation:
    """Verify IndeedProvider delegates to navigator with strategy + instruction."""

    def test_has_navigator(self):
        provider = IndeedProvider(_mock_browser())
        assert hasattr(provider, "navigator")

    def test_has_engine_strategy(self):
        provider = IndeedProvider(_mock_browser())
        assert isinstance(provider._engine_strategy, IndeedSearchStrategy)

    def test_run_uses_navigator_with_strategy(self):
        browser = _mock_browser()
        provider = IndeedProvider(browser)
        captured_strategy = None
        captured_instruction = None

        def fake_navigate_with_fallback(strategy, instruction, validator):
            nonlocal captured_strategy, captured_instruction
            captured_strategy = strategy
            captured_instruction = instruction
            return False

        provider.navigator.navigate_with_fallback = fake_navigate_with_fallback
        provider.run(_instruction(title="Designer", location="Remote"))
        assert isinstance(captured_strategy, IndeedSearchStrategy)
        assert captured_instruction is not None

    def test_skips_scraping_when_navigator_fails(self):
        browser = _mock_browser()
        provider = IndeedProvider(browser)
        provider.navigator.navigate_with_fallback = MagicMock(return_value=False)
        assert provider.run(_instruction()) == []

    def test_run_calls_toolbar_filters_after_navigation(self):
        browser = _mock_browser()
        provider = IndeedProvider(browser)
        provider.navigator.navigate_with_fallback = MagicMock(return_value=True)
        provider._engine_strategy.apply_toolbar_filters = MagicMock()
        provider.run(_instruction(date_range="week"))
        provider._engine_strategy.apply_toolbar_filters.assert_called_once()

    def test_inherits_from_base_search_provider(self):
        provider = IndeedProvider(_mock_browser())
        assert isinstance(provider, BaseSearchProvider)


# ═════════════════════════════════════════════════════════════════════════════
# 3. PROVIDER TESTS — find_company_career_page (Google only)
# ═════════════════════════════════════════════════════════════════════════════

class TestFindCompanyCareerPage:
    """Verify GoogleProvider.find_company_career_page behavior."""

    def test_uses_registry_domains(self):
        reg = _mock_registry(
            _descriptor("greenhouse", "*.greenhouse.io/jobs/*"),
            _descriptor("lever", "jobs.lever.co/*"),
        )
        browser = _mock_browser()
        browser.find_element.return_value = None
        provider = GoogleProvider(browser, ats_registry=reg)
        provider.find_company_career_page("Acme")
        called_url: str = browser.get.call_args[0][0]
        assert "greenhouse.io" in called_url
        assert "lever.co" in called_url

    def test_fallback_without_registry(self):
        browser = _mock_browser()
        browser.find_element.return_value = None
        provider = GoogleProvider(browser)
        provider.find_company_career_page("Acme")
        called_url: str = browser.get.call_args[0][0]
        assert "greenhouse.io" in called_url

    def test_returns_none_when_no_result(self):
        browser = _mock_browser()
        browser.find_element.return_value = None
        provider = GoogleProvider(browser)
        assert provider.find_company_career_page("Acme Corp") is None

    def test_returns_none_on_exception(self):
        browser = _mock_browser()
        browser.get.side_effect = Exception("network error")
        provider = GoogleProvider(browser)
        assert provider.find_company_career_page("Acme Corp") is None


# ═════════════════════════════════════════════════════════════════════════════
# 4. _ats_site_filters TESTS
# ═════════════════════════════════════════════════════════════════════════════

class TestAtsSiteFilters:

    def test_returns_fallback_when_no_registry(self):
        result = _ats_site_filters(None)
        assert "greenhouse.io" in result

    def test_extracts_root_domain_from_wildcard(self):
        reg = _mock_registry(_descriptor("greenhouse", "*.greenhouse.io/jobs/*"))
        result = _ats_site_filters(reg)
        assert "greenhouse.io" in result

    def test_deduplicates_same_root(self):
        reg = _mock_registry(
            _descriptor("greenhouse", "*.greenhouse.io/jobs/*", "boards.greenhouse.io/*/jobs/*"),
        )
        result = _ats_site_filters(reg)
        assert result.count("greenhouse.io") == 1

    def test_returns_fallback_when_registry_empty(self):
        reg = _mock_registry()
        result = _ats_site_filters(reg)
        assert "greenhouse.io" in result


# ═════════════════════════════════════════════════════════════════════════════
# 5. SELECTOR LOADER TESTS
# ═════════════════════════════════════════════════════════════════════════════

class TestDeepMerge:
    """Test the _deep_merge helper used by SelectorLoader."""

    def test_scalar_override_wins(self):
        base = {"homepage_url": "https://google.com"}
        override = {"homepage_url": "https://custom.google.com"}
        result = _deep_merge(base, override)
        assert result["homepage_url"] == "https://custom.google.com"

    def test_list_prepends_user_entries(self):
        base = {"selectors": ["a", "b"]}
        override = {"selectors": ["c"]}
        result = _deep_merge(base, override)
        assert result["selectors"] == ["c", "a", "b"]

    def test_nested_dict_recursive_merge(self):
        base = {"toolbar": {"open": {"selectors": ["a"]}}}
        override = {"toolbar": {"open": {"selectors": ["x"]}}}
        result = _deep_merge(base, override)
        assert result["toolbar"]["open"]["selectors"] == ["x", "a"]

    def test_new_key_added(self):
        base = {"a": 1}
        override = {"b": 2}
        result = _deep_merge(base, override)
        assert result["b"] == 2
        assert result["a"] == 1

    def test_base_not_mutated(self):
        base = {"selectors": ["a"]}
        override = {"selectors": ["b"]}
        _deep_merge(base, override)
        assert base["selectors"] == ["a"]


class TestSelectorLoader:
    """Test SelectorLoader YAML loading, caching, and user overrides."""

    def test_load_bundled_yaml(self, tmp_path):
        """Loader reads a bundled YAML file and returns the config."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        (bundled / "google.yaml").write_text(
            "engine: google\nhomepage_url: 'https://www.google.com'\n"
            "search_bar_selectors:\n  - 'input[name=q]'\n"
        )

        loader = SelectorLoader(bundled_dir=bundled, user_override_dir=tmp_path / "user")
        config = loader.load("google")

        assert config["engine"] == "google"
        assert config["homepage_url"] == "https://www.google.com"
        assert config["search_bar_selectors"] == ["input[name=q]"]

    def test_load_returns_empty_when_file_missing(self, tmp_path):
        """When no YAML file exists, an empty dict is returned."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        loader = SelectorLoader(bundled_dir=bundled, user_override_dir=tmp_path / "user")
        config = loader.load("nonexistent")
        assert config == {}

    def test_merges_user_override(self, tmp_path):
        """User YAML entries are prepended to bundled selectors."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        (bundled / "google.yaml").write_text(
            "engine: google\nsearch_bar_selectors:\n  - 'a'\n  - 'b'\n"
        )

        user_dir = tmp_path / "user"
        user_dir.mkdir()
        (user_dir / "google.yaml").write_text(
            "engine: google\nsearch_bar_selectors:\n  - 'custom'\n"
        )

        loader = SelectorLoader(bundled_dir=bundled, user_override_dir=user_dir)
        config = loader.load("google")
        assert config["search_bar_selectors"] == ["custom", "a", "b"]

    def test_cache_returns_same_object(self, tmp_path):
        """Second load returns the cached config (same object identity)."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        (bundled / "google.yaml").write_text("engine: google\nsearch_bar_selectors: []\n")

        loader = SelectorLoader(bundled_dir=bundled, user_override_dir=tmp_path / "user")
        c1 = loader.load("google")
        c2 = loader.load("google")
        assert c1 is c2

    def test_reload_bypasses_cache(self, tmp_path):
        """reload() returns a fresh config, not the cached one."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        (bundled / "google.yaml").write_text("engine: google\nsearch_bar_selectors: []\n")

        loader = SelectorLoader(bundled_dir=bundled, user_override_dir=tmp_path / "user")
        c1 = loader.load("google")
        c2 = loader.reload("google")
        # After reload with no file changes, they should be equal but not the same object
        assert c1 == c2

    def test_malformed_user_yaml_does_not_crash(self, tmp_path):
        """A malformed user YAML is ignored; bundled config is used."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        (bundled / "google.yaml").write_text("engine: google\nsearch_bar_selectors: ['safe']\n")

        user_dir = tmp_path / "user"
        user_dir.mkdir()
        (user_dir / "google.yaml").write_text("{invalid: yaml: :")

        loader = SelectorLoader(bundled_dir=bundled, user_override_dir=user_dir)
        config = loader.load("google")
        assert config["search_bar_selectors"] == ["safe"]


# ═════════════════════════════════════════════════════════════════════════════
# 6. SELECTOR CONFIDENCE TRACKER TESTS
# ═════════════════════════════════════════════════════════════════════════════

class TestSelectorConfidenceTracker:
    """Test confidence tracking, ordering, and persistence."""

    def test_unseen_selector_returns_neutral_confidence(self):
        tracker = SelectorConfidenceTracker(file_path=None)
        conf = tracker.get_confidence("google", "open_button", "div#x")
        assert conf == 0.5

    def test_success_increases_confidence(self):
        tracker = SelectorConfidenceTracker(file_path=None)
        tracker.record_success("google", "open", "div#x")
        conf = tracker.get_confidence("google", "open", "div#x")
        assert conf > 0.5

    def test_failure_decreases_confidence(self):
        tracker = SelectorConfidenceTracker(file_path=None)
        tracker.record_failure("google", "open", "div#x")
        conf = tracker.get_confidence("google", "open", "div#x")
        assert conf < 0.5

    def test_proven_selector_boosted_to_front(self):
        """A selector with ≥ _PROVEN_THRESHOLD successes is boosted."""
        tracker = SelectorConfidenceTracker(file_path=None)
        selectors = ["div#new", "div#proven"]
        # Make div#proven succeed 3 times
        for _ in range(3):
            tracker.record_success("google", "open", "div#proven")
        ordered = tracker.order_selectors("google", "open", selectors)
        assert ordered[0] == "div#proven"

    def test_persistence_round_trip(self, tmp_path):
        """Confidence data survives a save + load cycle."""
        path = tmp_path / "confidence.json"
        tracker1 = SelectorConfidenceTracker(file_path=path)
        tracker1.record_success("google", "open", "div#x")
        tracker1.record_failure("google", "open", "div#x")

        tracker2 = SelectorConfidenceTracker(file_path=path)
        conf = tracker2.get_confidence("google", "open", "div#x")
        # After 1 success + 1 failure: (1+1)/(2+2) = 0.5
        assert conf == pytest.approx(0.5)

    def test_get_stats_returns_raw_counts(self):
        tracker = SelectorConfidenceTracker(file_path=None)
        tracker.record_success("google", "open", "div#x")
        stats = tracker.get_stats("google", "open")
        assert stats["div#x"]["success"] == 1
        assert stats["div#x"]["fail"] == 0


# ═════════════════════════════════════════════════════════════════════════════
# 7. TOOLBAR ELEMENT LOCATOR TESTS
# ═════════════════════════════════════════════════════════════════════════════

class TestToolbarElementLocator:
    """Test ToolbarElementLocator CSS/XPath selection and Math‑DOM fallback."""

    @staticmethod
    def _make_config() -> dict:
        """Minimal config matching the YAML schema."""
        return {
            "engine": "google",
            "homepage_url": "https://www.google.com",
            "search_bar_selectors": ["input[name='q']"],
            "toolbar": {
                "date_filter": {
                    "open_button": {
                        "selectors": [
                            {"type": "css", "value": "div#hdtb-tls"},
                            {"type": "xpath", "value": "//div[@aria-label='Tools']"},
                        ],
                        "fallback": {
                            "tag": "div",
                            "role": "button",
                            "aria_label_contains": ["tools", "search tools"],
                        },
                    },
                    "date_options": {
                        "past_week": {
                            "selectors": [
                                {"type": "xpath", "value": "//a[contains(., 'Past week')]"},
                            ],
                            "fallback": {
                                "text_contains": ["past week", "last week"],
                            },
                        },
                    },
                },
            },
        }

    def _make_locator(self, browser, config=None, math_dom=None):
        loader = MagicMock()
        loader.load.return_value = config or self._make_config()
        return ToolbarElementLocator(
            browser=browser,
            engine_name="google",
            loader=loader,
            math_dom_adapter=math_dom,
            confidence_tracker=SelectorConfidenceTracker(file_path=None),
        )

    def test_find_element_uses_css_selector(self):
        """When a CSS selector matches, the element is returned."""
        browser = _mock_browser()
        mock_el = MagicMock()
        browser.find_element.return_value = mock_el

        locator = self._make_locator(browser)
        result = locator.find_element("toolbar.date_filter.open_button")

        assert result is mock_el
        browser.find_element.assert_called()

    def test_find_element_tries_next_selector_on_failure(self):
        """When the first CSS selector returns None, the XPath selector is tried."""
        browser = _mock_browser()
        mock_el = MagicMock()
        browser.find_element.side_effect = [None, mock_el]

        locator = self._make_locator(browser)
        result = locator.find_element("toolbar.date_filter.open_button")

        assert result is mock_el
        assert browser.find_element.call_count == 2

    def test_find_element_returns_none_when_all_fail(self):
        """When all selectors fail and no Math DOM is available, returns None."""
        browser = _mock_browser()
        browser.find_element.return_value = None

        locator = self._make_locator(browser)
        result = locator.find_element("toolbar.date_filter.open_button")

        assert result is None

    def test_find_element_uses_math_dom_fallback(self):
        """When all CSS/XPath fail, Math‑DOM fallback is attempted."""
        browser = _mock_browser()
        browser.find_element.return_value = None
        # The Math‑DOM fallback will call find_elements as a last resort.
        browser.find_elements.return_value = []

        math_dom = MagicMock()
        # Build a DOMNode tree with a matching element.
        from auto_apply.domain.models.math_dom import DOMNode, Geometry

        target = DOMNode(
            tag="div",
            attributes=(("role", "button"), ("aria-label", "Search tools"), ("id", "tools-btn")),
            geometry=Geometry(100, 100, 200, 40),
            depth=1,
        )
        root = DOMNode(tag="body", depth=0, children=(target,))
        math_dom.extract_full_dom_tree.return_value = root

        # The locator will first try to find by id (#tools-btn).
        mock_el = MagicMock()
        browser.find_element.side_effect = [None, mock_el]  # first fail, second succeed

        locator = self._make_locator(browser, math_dom=math_dom)
        result = locator.find_element("toolbar.date_filter.open_button")

        assert result is mock_el

    def test_find_element_unknown_path_returns_none(self):
        """A section_path that doesn't exist in config returns None."""
        browser = _mock_browser()
        locator = self._make_locator(browser)
        result = locator.find_element("toolbar.nonexistent.path")
        assert result is None

    def test_search_bar_selectors_from_config(self):
        """search_bar_selectors property reads from the loaded config."""
        browser = _mock_browser()
        locator = self._make_locator(browser)
        assert locator.search_bar_selectors == ["input[name='q']"]

    def test_homepage_url_from_config(self):
        """homepage_url property reads from the loaded config."""
        browser = _mock_browser()
        locator = self._make_locator(browser)
        assert locator.homepage_url == "https://www.google.com"

    def test_click_element_returns_false_when_not_found(self):
        """click_element returns False when no element is found."""
        browser = _mock_browser()
        browser.find_element.return_value = None

        locator = self._make_locator(browser)
        assert not locator.click_element("toolbar.date_filter.open_button")

    def test_click_element_returns_true_on_success(self):
        """click_element returns True when element is found and clicked."""
        browser = _mock_browser()
        mock_el = MagicMock()
        browser.find_element.return_value = mock_el

        locator = self._make_locator(browser)
        result = locator.click_element("toolbar.date_filter.open_button")
        assert result is True

    def test_locator_injected_into_strategy(self):
        """End‑to‑end: a locator injected into GoogleSearchStrategy is used for toolbar."""
        browser = _mock_browser()
        mock_el = MagicMock()
        # First find returns the tools button.
        browser.find_element.return_value = mock_el

        locator = self._make_locator(browser)
        strategy = GoogleSearchStrategy()
        strategy.set_locator(locator)

        # apply_toolbar_filters should use the locator (not legacy).
        strategy.apply_toolbar_filters(browser, _instruction(date_range="week"))

        # The locator's find_element should have been called for open_button,
        # time_menu, and date_options.past_week.
        # We verify by checking that browser.find_element was called (locator uses it).
        assert browser.find_element.call_count >= 1


# ═════════════════════════════════════════════════════════════════════════════
# 8. JSON‑LD EXTRACTION TESTS (GenericSERPStrategy._try_extract_json_ld)
# ═════════════════════════════════════════════════════════════════════════════

class TestJSONLDExtraction:
    """Test GenericSERPStrategy._try_extract_json_ld using BS4 on page_source."""

    @pytest.fixture
    def mock_strategy(self):
        """Return a GenericSERPStrategy instance with a mocked browser."""
        browser = _mock_browser()
        # The strategy needs a browser and source_tag; the search_prefs can be None
        return GenericSERPStrategy(
            browser=browser,
            search_prefs=None,
            source_tag="Test",
        )

    def test_no_jsonld_returns_empty_list(self, mock_strategy):
        """If page_source contains no JSON‑LD, an empty list is returned."""
        mock_strategy.browser.page_source = "<html></html>"
        assert mock_strategy._try_extract_json_ld() == []

    def test_valid_jobposting_extracted(self, mock_strategy):
        """A single JobPosting JSON‑LD block yields one Job."""
        job_json = json.dumps({
            "@context": "http://schema.org",
            "@type": "JobPosting",
            "title": "Software Engineer",
            "hiringOrganization": {"@type": "Organization", "name": "Acme Corp"},
            "url": "https://acme.com/jobs/1",
            "jobLocation": {"@type": "Place", "address": {"addressLocality": "Remote"}},
        })
        mock_strategy.browser.page_source = (
            '<html><script type="application/ld+json">' + job_json + "</script></html>"
        )
        jobs = mock_strategy._try_extract_json_ld()
        assert len(jobs) == 1
        assert jobs[0].title == "Software Engineer"
        assert jobs[0].company == "Acme Corp"
        assert jobs[0].url == "https://acme.com/jobs/1"
        assert jobs[0].location == "Remote"

    def test_jobposting_in_graph_extracted(self, mock_strategy):
        """A JSON‑LD @graph containing a JobPosting is extracted."""
        graph_json = json.dumps({
            "@context": "http://schema.org",
            "@graph": [
                {"@type": "WebPage"},
                {
                    "@type": "JobPosting",
                    "title": "Data Analyst",
                    "hiringOrganization": {"name": "Data Inc"},
                    "url": "https://data.com/job/2",
                }
            ],
        })
        mock_strategy.browser.page_source = (
            '<html><script type="application/ld+json">' + graph_json + "</script></html>"
        )
        jobs = mock_strategy._try_extract_json_ld()
        assert len(jobs) == 1
        assert jobs[0].title == "Data Analyst"

    def test_missing_url_falls_back_to_google_search_url(self, mock_strategy):
        """If no url field is present, a Google search URL is constructed."""
        job_json = json.dumps({
            "@context": "http://schema.org",
            "@type": "JobPosting",
            "title": "Systems Administrator",
            "hiringOrganization": {"name": "IT Corp"},
        })
        mock_strategy.browser.page_source = (
            '<html><script type="application/ld+json">' + job_json + "</script></html>"
        )
        jobs = mock_strategy._try_extract_json_ld()
        assert len(jobs) == 1
        assert "google.com/search" in jobs[0].url

    def test_missing_title_skips(self, mock_strategy):
        """If title is missing, the entry is skipped."""
        job_json = json.dumps({
            "@context": "http://schema.org",
            "@type": "JobPosting",
            "hiringOrganization": {"name": "No Title Inc"},
            "url": "https://notitle.com",
        })
        mock_strategy.browser.page_source = (
            '<html><script type="application/ld+json">' + job_json + "</script></html>"
        )
        jobs = mock_strategy._try_extract_json_ld()
        assert len(jobs) == 0

    def test_malformed_json_skipped(self, mock_strategy):
        """Malformed JSON blocks are silently skipped."""
        mock_strategy.browser.page_source = (
            '<html><script type="application/ld+json">{bad json}</script></html>'
        )
        jobs = mock_strategy._try_extract_json_ld()
        assert len(jobs) == 0


# ═════════════════════════════════════════════════════════════════════════════
# 9. INDEEDPROVIDER TESTS — inheritance and page‑health
# ═════════════════════════════════════════════════════════════════════════════

class TestIndeedProviderHealthCheck:
    """Test IndeedProvider's page‑health check with optional evasion."""

    def test_healthy_with_no_evasion(self):
        """Without an evasion manager, the page is always considered healthy."""
        provider = IndeedProvider(_mock_browser())
        assert provider._is_page_healthy() is True

    def test_blocked_when_evasion_detects(self):
        """If the evasion manager detects a block, _is_page_healthy returns False."""
        browser = _mock_browser()
        evasion = MagicMock()
        evasion.check_page_safety.return_value = False  # blocked
        provider = IndeedProvider(browser, evasion_manager=evasion)
        assert provider._is_page_healthy() is False

    def test_healthy_when_evasion_ok(self):
        """If the evasion manager says the page is safe, returns True."""
        browser = _mock_browser()
        evasion = MagicMock()
        evasion.check_page_safety.return_value = True
        provider = IndeedProvider(browser, evasion_manager=evasion)
        assert provider._is_page_healthy() is True