"""Pin tests for red pin #2: the per-company application cap must be injected
into ThrottlingFilter and read from configuration — not hardcoded as a class
constant that ignores ``max_applications_per_company``.

Pin label: TEETH. On the pre-stage tree:
  - Tests 1–3 and 5 fail at construction with ``TypeError: __init__() got an
    unexpected keyword argument 'max_applications_per_company'`` — the cap had
    no injection path.
  - Test 4 fails with ``AssertionError`` because the class constant
    ``MAX_APPLICATIONS_PER_COMPANY = 3`` still exists.
Both failure modes are the defect being pinned.
"""

from datetime import datetime
from types import SimpleNamespace

from auto_apply.domain.models.job import Job
from auto_apply.domain.vetting.throttling_filter import ThrottlingFilter


class _FakeJobRepo:
    """Minimal JobRepositoryPort double — only what ThrottlingFilter calls."""

    def __init__(self, company_count: int) -> None:
        self._company_count = company_count
        self.company_count_calls: int = 0

    def count_applications_since(self, since: datetime) -> int:
        return 0  # daily quota never binds in these tests

    def count_applications_for_company(self, company_name: str) -> int:
        self.company_count_calls += 1
        return self._company_count

    def get_last_applied_date(self, company_name: str):
        return None

    def get_company_mandate_cooldown(self, company_name: str) -> int:
        return 0

    def was_applied(self, url: str) -> bool:
        return False

    def mark_applied(self, job, session_id: str) -> None:
        pass


def _profile() -> SimpleNamespace:
    return SimpleNamespace(
        application_preferences=SimpleNamespace(cooldown_days=None)
    )


def _job(company: str = "Acme") -> Job:
    return Job(
        title="Engineer",
        company=company,
        url="https://example.com/j/1",
        source="test",
    )


def _make_filter(repo, cap: int) -> ThrottlingFilter:
    return ThrottlingFilter(
        _profile(),
        repo,
        cooldown_days_default=180,
        daily_application_limit=50,
        max_applications_per_company=cap,
    )


class TestPerCompanyCapIsConfigurable:
    def test_injected_cap_blocks_at_limit(self):
        repo = _FakeJobRepo(company_count=1)
        filt = _make_filter(repo, cap=1)
        passed, reason = filt.check(_job())
        assert not passed
        assert "max applications" in reason.lower()
        assert "1" in reason

    def test_higher_injected_cap_passes(self):
        # Also proves the read: the repo must actually be consulted.
        repo = _FakeJobRepo(company_count=1)
        filt = _make_filter(repo, cap=3)
        passed, _ = filt.check(_job())
        assert passed
        assert repo.company_count_calls == 1

    def test_injected_cap_overrides_shipped_default(self):
        # The inversion of the original red pin: YAML ships 3, the class
        # constant said 3, so "set 1 → still applies 3×" was invisible.
        # Injecting 1 must block the second application.
        repo = _FakeJobRepo(company_count=1)
        filt = _make_filter(repo, cap=1)
        assert not filt.check(_job())[0]

    def test_class_constant_removed(self):
        # Deletion pin: a shadowed constant would be a new decoy.
        assert not hasattr(ThrottlingFilter, "MAX_APPLICATIONS_PER_COMPANY")

    def test_cap_boundary(self):
        assert not _make_filter(_FakeJobRepo(2), cap=2).check(_job())[0]
        assert _make_filter(_FakeJobRepo(1), cap=2).check(_job())[0]
