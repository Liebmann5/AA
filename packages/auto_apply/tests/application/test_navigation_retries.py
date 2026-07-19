"""Pin: navigation retries are bounded by the configured ``navigation_retries``.

Before this feature the live navigator (``PageActionService.navigate``) made a
single ``get()`` and returned failure immediately — a genuinely dead URL was
abandoned after one try, and the ``navigation_retries`` config value governed
nothing (it was a dead field on TimingProfile). This pin holds the new
behaviour: navigation is a bounded-retry *search* that gives up after exactly
``navigation_retries`` attempts, and the ``next_candidate`` seam (the future
Application Traversal Graph injection point) is honoured.

Verified to FAIL against the old single-attempt navigate(): with
navigation_retries=3 and a browser that always fails, the old code called get()
once, not three times.
"""

from __future__ import annotations

import pytest

from auto_apply.application.services.page_action.service import PageActionService


class _CountingBrowser:
    """Minimal BrowserInterface stand-in: counts get() calls, records targets."""

    def __init__(self, *, fail_times: int) -> None:
        self.calls: list[str] = []
        self._fail_times = fail_times

    def get(self, url: str) -> None:
        self.calls.append(url)
        if len(self.calls) <= self._fail_times:
            raise RuntimeError(f"boom on attempt {len(self.calls)}")

    # navigate() with fingerprint disabled never touches these, but keep them safe.
    def perform_mouse_fidget(self) -> None:  # pragma: no cover
        pass


class _StubRegistry:
    def __init__(self, navigation_retries: int) -> None:
        self._cfg = {
            "navigation_retries": navigation_retries,
            "enable_human_timing": False,
            "enable_fingerprint_spoofing": False,
            "macro_pause_min_s": 0.0,
            "macro_pause_max_s": 0.0,
            "settle_min_s": 0.0,
            "settle_max_s": 0.0,
            "micro_timing_peak_ms": 0.0,
        }

    def get_all_effective_config(self) -> dict:
        return dict(self._cfg)


def _service(navigation_retries: int, fail_times: int) -> tuple[PageActionService, _CountingBrowser]:
    browser = _CountingBrowser(fail_times=fail_times)
    svc = PageActionService(browser, _StubRegistry(navigation_retries))
    return svc, browser


@pytest.mark.parametrize("n", [1, 2, 3, 5])
def test_navigation_gives_up_after_exactly_navigation_retries(n: int) -> None:
    """A permanently failing URL is attempted exactly ``navigation_retries`` times."""
    svc, browser = _service(navigation_retries=n, fail_times=10_000)
    result = svc.navigate("https://dead.example/job")
    assert not result.success
    assert len(browser.calls) == n, (
        f"navigation_retries={n} but the browser was hit {len(browser.calls)} "
        f"times — the retry budget is not bounding live navigation."
    )


def test_navigation_success_is_a_single_attempt() -> None:
    """A URL that loads first try must not be retried — the count is a ceiling."""
    svc, browser = _service(navigation_retries=5, fail_times=0)
    result = svc.navigate("https://live.example/job")
    assert result.success
    assert len(browser.calls) == 1


def test_navigation_recovers_within_the_budget() -> None:
    """Failing twice then succeeding on the third attempt returns success."""
    svc, browser = _service(navigation_retries=3, fail_times=2)
    result = svc.navigate("https://flaky.example/job")
    assert result.success
    assert len(browser.calls) == 3


def test_next_candidate_seam_supplies_the_next_target() -> None:
    """The traversal-graph seam drives which target each retry attempts.

    This is the contract the future Application Traversal Graph relies on: the
    loop asks ``next_candidate`` for the next link/path on each failure, bounded
    by navigation_retries, without any other change to control flow.
    """
    svc, browser = _service(navigation_retries=3, fail_times=10_000)

    supplied = ["https://candidate.example/2", "https://candidate.example/3"]

    def provider(failed_target: str, attempt: int) -> str | None:
        return supplied[attempt - 1] if attempt - 1 < len(supplied) else None

    result = svc.navigate("https://candidate.example/1", next_candidate=provider)
    assert not result.success
    assert browser.calls == [
        "https://candidate.example/1",
        "https://candidate.example/2",
        "https://candidate.example/3",
    ], "next_candidate seam did not drive the retry targets in order"
