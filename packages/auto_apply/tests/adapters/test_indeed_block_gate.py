"""Pins: Indeed's navigation health check asks the ONE page verdict and
records the blocked observation it used to skip (D5 parity with the SERP
gate).

Pre-change the health check consulted EvasionManager.check_page_safety —
or, with none wired, always answered healthy — and a block during
navigation returned [] with no observation recorded. The fixtures reuse
the measured page shapes: a Cloudflare-style interstitial (gated) and an
ordinary posting (clear).
"""

from __future__ import annotations

from auto_apply.adapters.secondary.discovery.providers.indeed import IndeedProvider

_GATED_HTML = (
    "<html><head>"
    '<script src="https://challenges.cloudflare.com/turnstile/v0/api.js">'
    "</script></head><body>"
    '<input type="hidden" name="cf-turnstile-response" value=""/>'
    "<p>Checking your browser before continuing.</p>"
    "</body></html>"
)

_POSTING_HTML = (
    "<html><body>"
    "<form id='search'><input name='q'/></form>"
    "<form id='alert'><input name='email'/></form>"
    f"<p>{'Backend Engineer role details. ' * 60}</p>"
    "</body></html>"
)


class _FakeBrowser:
    def __init__(
        self,
        html: str,
        url: str = "https://www.indeed.example/jobs?q=x",
        title: str = "Jobs",
    ) -> None:
        self.page_source = html
        self.current_url = url
        self.title = title


class _FakeResearchObserver:
    def __init__(self) -> None:
        self.observations: list = []

    @property
    def is_enabled(self) -> bool:
        return True

    def observe_discovery(self, observation) -> None:
        self.observations.append(observation)


def test_gated_page_fails_health_and_records_the_observation_once():
    """TEETH: a blocked page is one observation, however often the
    navigator health-checks during a single run."""
    observer = _FakeResearchObserver()
    provider = IndeedProvider(
        browser=_FakeBrowser(_GATED_HTML, title="Just a moment..."),
        research_observer=observer,
    )

    assert provider._is_page_healthy() is False
    assert provider._is_page_healthy() is False  # navigator may ask again
    assert len(observer.observations) == 1
    observation = observer.observations[0]
    assert observation.blocked is True
    assert observation.page_state == "captcha_block"
    assert observation.provider == "Indeed"
    assert observation.card_count == 0
    assert observation.page_host == "www.indeed.example"


def test_login_wall_fails_health_and_records_login_state():
    """A non-CAPTCHA block kind is recorded with its own state, not merged."""
    observer = _FakeResearchObserver()
    provider = IndeedProvider(
        browser=_FakeBrowser(
            _POSTING_HTML, url="https://www.indeed.example/account/login"
        ),
        research_observer=observer,
    )
    assert provider._is_page_healthy() is False
    assert len(observer.observations) == 1
    assert observer.observations[0].page_state == "login_required"


def test_clear_posting_passes_health_and_records_nothing():
    """BEHAVIOUR-PRESERVING: an ordinary posting is healthy, as before."""
    observer = _FakeResearchObserver()
    provider = IndeedProvider(
        browser=_FakeBrowser(_POSTING_HTML),
        research_observer=observer,
    )
    assert provider._is_page_healthy() is True
    assert observer.observations == []


def test_no_observer_still_fails_closed():
    """Research consent off must not change the health verdict."""
    provider = IndeedProvider(
        browser=_FakeBrowser(_GATED_HTML, title="Just a moment...")
    )
    assert provider._is_page_healthy() is False
