"""Pins for bench-before-navigation and pace-at-the-navigation-seam.

New-surface pins. Mutations caught: a benched engine still being navigated
to; the pacer running after (or never around) navigation; a site-scoped
bench stopping generic queries; a provider without pacer/guard regressing.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from auto_apply.adapters.secondary.discovery.providers import google as google_module
from auto_apply.adapters.secondary.discovery.providers.google import GoogleProvider
from auto_apply.domain.models.search_instruction import SearchInstruction


class _SpyStrategy:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def execute(self):
        return []


def _provider(monkeypatch, detector=None, pacer=None) -> GoogleProvider:
    monkeypatch.setattr(google_module, "GenericSERPStrategy", _SpyStrategy)
    provider = GoogleProvider(
        browser=MagicMock(),
        degradation_detector=detector,
        host_pacer=pacer,
    )
    provider.navigator = MagicMock()
    provider.navigator.navigate_with_fallback.return_value = True
    return provider


def test_a_benched_engine_sends_no_request(monkeypatch):
    """TEETH: pre-change, a benched engine was still navigated to."""
    detector = MagicMock()
    detector.is_benched.side_effect = lambda name: name == "google"
    provider = _provider(monkeypatch, detector=detector)
    assert provider.run(SearchInstruction(title="Engineer")) == []
    provider.navigator.navigate_with_fallback.assert_not_called()


def test_pacing_precedes_navigation(monkeypatch):
    """The per-host floor applies before the engine is contacted."""
    calls: list[str] = []
    pacer = MagicMock()
    pacer.wait_for_url.side_effect = lambda url: calls.append("pace")
    provider = _provider(monkeypatch, pacer=pacer)
    provider.navigator.navigate_with_fallback.side_effect = (
        lambda *a, **k: calls.append("nav") or True
    )
    provider.run(SearchInstruction(title="Engineer"))
    assert calls == ["pace", "nav"]
    assert pacer.wait_for_url.call_args.args[0].startswith(
        "https://www.google.com/search"
    )


def test_a_site_scoped_bench_stops_only_site_queries(monkeypatch):
    """A degraded site-search path never benches the engine's generic path."""
    detector = MagicMock()
    detector.is_benched.side_effect = lambda name: name == "google#site"
    provider = _provider(monkeypatch, detector=detector)
    generic = SearchInstruction(title="Engineer")
    assert provider.run(generic) == []
    provider.navigator.navigate_with_fallback.assert_called_once()
    provider.navigator.navigate_with_fallback.reset_mock()
    site = SearchInstruction(title="Engineer", platform="jobvite")
    assert provider.run(site) == []
    provider.navigator.navigate_with_fallback.assert_not_called()


def test_no_guard_and_no_pacer_runs_as_before(monkeypatch):
    """Default path: with neither wired, the provider navigates normally."""
    provider = _provider(monkeypatch)
    assert provider.run(SearchInstruction(title="Engineer")) == []
    provider.navigator.navigate_with_fallback.assert_called_once()
