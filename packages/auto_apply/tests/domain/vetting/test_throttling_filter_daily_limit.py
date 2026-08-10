"""Pin tests for red pin #1: the daily application limit must be injected
into ThrottlingFilter and enforced — not computed internally and discarded.

Pin label: TEETH. On the pre-stage tree, every test in this module fails at
construction with ``TypeError`` (missing injected caps) — which is exactly the
defect being pinned: the limit had no injection path and was computed from the
profile into an attribute that was never read.
"""

from datetime import datetime, timezone
from types import SimpleNamespace

from auto_apply.domain.models.job import Job
from auto_apply.domain.vetting.throttling_filter import ThrottlingFilter


class _FakeJobRepo:
    """Minimal JobRepositoryPort double — only what ThrottlingFilter calls."""

    def __init__(self, daily_count: int) -> None:
        self._daily_count = daily_count
        self.count_since_calls: int = 0
        self.last_since: datetime | None = None

    def count_applications_since(self, since: datetime) -> int:
        self.count_since_calls += 1
        self.last_since = since
        return self._daily_count

    def count_applications_for_company(self, company_name: str) -> int:
        return 0

    def get_last_applied_date(self, company_name: str):
        return None

    def get_company_mandate_cooldown(self, company_name: str) -> int:
        return 0

    def was_applied(self, url: str) -> bool:
        return False

    def mark_applied(self, job, session_id: str) -> None:
        pass


def _profile(app_limit: int | None = None) -> SimpleNamespace:
    ns = SimpleNamespace(
        application_preferences=SimpleNamespace(cooldown_days=None)
    )
    if app_limit is not None:
        ns.app_config = SimpleNamespace(daily_application_limit=app_limit)
    return ns


def _job(company: str = "Acme") -> Job:
    return Job(
        title="Engineer",
        company=company,
        url="https://example.com/j/1",
        source="test",
    )


def _make_filter(repo, limit: int = 3) -> ThrottlingFilter:
    return ThrottlingFilter(
        _profile(),
        repo,
        cooldown_days_default=180,
        daily_application_limit=limit,
        max_applications_per_company=3,
    )


class TestDailyLimitEnforcement:
    def test_limit_enforced_at_cap(self):
        repo = _FakeJobRepo(daily_count=3)
        filt = _make_filter(repo, limit=3)
        passed, reason = filt.check(_job())
        assert not passed
        assert "daily" in reason.lower()

    def test_under_cap_passes_and_repo_is_consulted(self):
        # The count_since_calls assertion is the "is read" proof: the filter
        # must actually query the count, not merely accept the kwarg.
        repo = _FakeJobRepo(daily_count=2)
        filt = _make_filter(repo, limit=3)
        passed, _ = filt.check(_job())
        assert passed
        assert repo.count_since_calls == 1

    def test_injected_limit_wins_over_profile_value(self):
        # Sharpest teeth for the pin's name: the enforced number must be the
        # injected one, not the profile-computed one. Pre-stage, the ONLY
        # source was the profile; this profile claims 99999 yet must still
        # be blocked by the injected limit of 1.
        repo = _FakeJobRepo(daily_count=1)
        filt = ThrottlingFilter(
            _profile(app_limit=99999),
            repo,
            cooldown_days_default=180,
            daily_application_limit=1,
            max_applications_per_company=3,
        )
        passed, _ = filt.check(_job())
        assert not passed

    def test_daily_cap_gates_unknown_company_jobs(self):
        # Pins the intentional ordering change: the quota is user-global, so
        # it runs before the "Unknown Company (Pass Open)" early return.
        repo = _FakeJobRepo(daily_count=5)
        filt = _make_filter(repo, limit=5)
        passed, _ = filt.check(_job(company="Unknown"))
        assert not passed

    def test_window_is_start_of_today_utc(self):
        # NB: can flake if run exactly across 00:00 UTC — acceptable, rerun.
        repo = _FakeJobRepo(daily_count=0)
        filt = _make_filter(repo, limit=1)
        filt.check(_job())
        since = repo.last_since
        assert since is not None and since.tzinfo is not None
        assert (since.hour, since.minute, since.second) == (0, 0, 0)
        assert since.date() == datetime.now(timezone.utc).date()
