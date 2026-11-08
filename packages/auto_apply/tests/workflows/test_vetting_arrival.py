"""Teeth pins for vetting's arrival check of an opaque route.

Discovery keeps a Google ``/goto`` hit on the destination its results page
shows (2ef7019). What the page shows is a claim; vetting is where AA first
lands, so vetting confirms it before reading, judging or applying.
"""
from __future__ import annotations

from auto_apply.adapters.secondary.discovery.ats_registry import ATSRegistry
from auto_apply.application.workflows.vetting_workflow import (
    ARRIVAL_WAIT_SECONDS,
    VettingWorkflow,
)
from auto_apply.domain.events import Event

_ROUTE = "https://www.google.com/goto?url=CAESaQHEIkXXo_WqMhp-QAnfytxyPIc3nz1rqUjgMcnlZef"
_POSTING = "https://jobs.jobvite.com/brahma/job/oAbCdEfG"


class _Perception:
    """navigate() lands on ``landings`` in turn; each get_current_url() call
    advances one step (a script hop), the last landing then stays."""

    def __init__(self, landings: list[str], text: str = "Backend engineer. " * 30,
                 html: str = "<html><body>posting</body></html>"):
        self._landings = list(landings)
        self._i = 0
        self.navigated: list[str] = []
        self.text_reads = 0
        self._text = text
        self._html = html

    def navigate(self, url: str) -> None:
        self.navigated.append(url)

    def get_current_url(self) -> str:
        url = self._landings[min(self._i, len(self._landings) - 1)]
        self._i += 1
        return url

    def get_page_text(self) -> str:
        self.text_reads += 1
        return self._text

    def get_page_html(self) -> str:
        return self._html


class _Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _passing_filter():
    from unittest.mock import MagicMock

    filt = MagicMock()
    filt.check.return_value = (True, "ok")
    filt.__class__.__name__ = "ThrottlingFilter"
    return filt


def _workflow(perception, deps, registry=ATSRegistry(), clock=None):
    profile, bus, repo, queue, matcher = deps
    clock = clock or _Clock()
    return VettingWorkflow(
        profile=profile,
        filters=[_passing_filter()],
        job_repo=repo,
        task_queue=queue,
        event_bus=bus,
        text_matcher=matcher,
        perception_port=perception,
        ats_registry=registry,
        sleep=clock.sleep,
        clock=clock.time,
    )


def _opaque(job):
    job.url = _ROUTE
    job.metadata["target_platform"] = "jobvite"
    job.metadata["shown_destination"] = "jobs.jobvite.com/brahma"
    return job


def _deps(mock_profile, mock_event_bus, mock_job_repo, mock_task_queue, mock_text_matcher):
    return (mock_profile, mock_event_bus, mock_job_repo, mock_task_queue, mock_text_matcher)


def test_an_opaque_hit_landing_on_a_posting_is_vetted_from_its_real_address(
    mock_profile, sample_job, mock_event_bus, mock_job_repo, mock_task_queue, mock_text_matcher,
):
    job = _opaque(sample_job)
    perception = _Perception([_POSTING])
    wf = _workflow(perception, _deps(mock_profile, mock_event_bus, mock_job_repo,
                                     mock_task_queue, mock_text_matcher))

    assert wf.run(job) is True
    assert job.metadata["landed_url"] == _POSTING
    assert job.metadata["resolved_url"] == _POSTING
    assert job.metadata["ats"] == "jobvite"
    assert job.url == _ROUTE, "the job's identity (its discovered URL) is unchanged"


def test_a_script_hop_off_the_route_is_waited_for_bounded(
    mock_profile, sample_job, mock_event_bus, mock_job_repo, mock_task_queue, mock_text_matcher,
):
    job = _opaque(sample_job)
    clock = _Clock()
    perception = _Perception([_ROUTE, _ROUTE, _POSTING])
    wf = _workflow(perception, _deps(mock_profile, mock_event_bus, mock_job_repo,
                                     mock_task_queue, mock_text_matcher), clock=clock)

    assert wf.run(job) is True
    assert len(clock.sleeps) == 2 and job.metadata["resolved_url"] == _POSTING


def test_a_route_that_never_leaves_the_engine_is_rejected_unread(
    mock_profile, sample_job, mock_event_bus, mock_job_repo, mock_task_queue, mock_text_matcher,
):
    """TEETH: before the check, the engine's interstitial (or a block page)
    was read and judged as the posting."""
    job = _opaque(sample_job)
    clock = _Clock()
    perception = _Perception(["https://www.google.com/url?q=x"])
    wf = _workflow(perception, _deps(mock_profile, mock_event_bus, mock_job_repo,
                                     mock_task_queue, mock_text_matcher), clock=clock)

    assert wf.run(job) is False
    assert "did not resolve" in job.rejection_reason
    assert perception.text_reads == 0, "nothing on the wrong page is read"
    assert clock.now <= ARRIVAL_WAIT_SECONDS + 0.5, "the wait is bounded"
    mock_task_queue.queue_task.assert_not_called()
    assert Event.JOB_VETTED_FAIL in [e for e, _ in mock_event_bus.published_events]


def test_a_landing_on_another_platform_is_rejected(
    mock_profile, sample_job, mock_event_bus, mock_job_repo, mock_task_queue, mock_text_matcher,
):
    job = _opaque(sample_job)
    perception = _Perception(["https://job-boards.greenhouse.io/acme/jobs/4012345"])
    wf = _workflow(perception, _deps(mock_profile, mock_event_bus, mock_job_repo,
                                     mock_task_queue, mock_text_matcher))

    assert wf.run(job) is False
    assert "off platform" in job.rejection_reason
    assert "resolved_url" not in job.metadata
    mock_task_queue.queue_task.assert_not_called()


def test_a_landing_on_a_company_list_page_is_rejected(
    mock_profile, sample_job, mock_event_bus, mock_job_repo, mock_task_queue, mock_text_matcher,
):
    job = _opaque(sample_job)
    perception = _Perception(["https://jobs.jobvite.com/leantechio/search?q=backend"])
    wf = _workflow(perception, _deps(mock_profile, mock_event_bus, mock_job_repo,
                                     mock_task_queue, mock_text_matcher))

    assert wf.run(job) is False
    assert "not a posting" in job.rejection_reason


def test_an_opaque_hit_without_a_registry_is_never_vetted_on_trust(
    mock_profile, sample_job, mock_event_bus, mock_job_repo, mock_task_queue, mock_text_matcher,
):
    job = _opaque(sample_job)
    perception = _Perception([_POSTING])
    wf = _workflow(perception, _deps(mock_profile, mock_event_bus, mock_job_repo,
                                     mock_task_queue, mock_text_matcher), registry=None)

    assert wf.run(job) is False
    assert "no platform registry" in job.rejection_reason


def test_a_direct_hit_is_not_checked_but_its_landing_is_recorded(
    mock_profile, sample_job, mock_event_bus, mock_job_repo, mock_task_queue, mock_text_matcher,
):
    """Direct links were matched against the platform's posting patterns in
    discovery; only the landing is recorded, nothing is rejected."""
    sample_job.url = "https://board.example/posting/1"
    landed = "https://board.example/posting/1?ref=redirect"
    perception = _Perception([landed])
    wf = _workflow(perception, _deps(mock_profile, mock_event_bus, mock_job_repo,
                                     mock_task_queue, mock_text_matcher))

    assert wf.run(sample_job) is True
    assert sample_job.metadata["landed_url"] == landed
    assert "resolved_url" not in sample_job.metadata


def test_the_apply_target_is_read_against_the_landed_page(
    mock_profile, sample_job, mock_event_bus, mock_job_repo, mock_task_queue, mock_text_matcher,
):
    """TEETH: the posting's own Apply link was judged against the route's
    host (google.com), so it read as an off-host target and was recorded."""
    job = _opaque(sample_job)
    html = ('<html><body><a href="https://jobs.jobvite.com/brahma/job/oAbCdEfG/apply">'
            "Apply</a></body></html>")
    perception = _Perception([_POSTING], html=html)
    wf = _workflow(perception, _deps(mock_profile, mock_event_bus, mock_job_repo,
                                     mock_task_queue, mock_text_matcher))

    wf.run(job)
    assert "apply_url" not in job.metadata


def test_a_removed_jobvite_posting_is_named_as_such(
    mock_profile, sample_job, mock_event_bus, mock_job_repo, mock_task_queue, mock_text_matcher,
):
    """Live run 2026-11-08: Google still listed leantechio/job/otsNAfw2; the
    visit landed on jobs.jobvite.com/careers/leantechio/jobs?error=404."""
    job = _opaque(sample_job)
    landed = "https://jobs.jobvite.com/careers/leantechio/jobs?error=404"
    wf = _workflow(_Perception([landed]), _deps(mock_profile, mock_event_bus, mock_job_repo,
                                                mock_task_queue, mock_text_matcher))

    assert wf.run(job) is False
    assert "closed or removed" in job.rejection_reason
