"""Tests for VettingWorkflow.

Covers:
    - A job that passes all filters is enqueued and run() returns True.
    - A job that fails a filter is rejected and run() returns False.
    - Borderline-score job receives a YES from GPT4All → score bumped above band.
    - Graceful degradation when GPT4All or perception_port is None.
"""
import pytest
from unittest.mock import MagicMock

from auto_apply.application.workflows.vetting_workflow import VettingWorkflow
from auto_apply.domain.events import Event
from auto_apply.domain.models.job import Job


def _make_passing_filter() -> MagicMock:
    filt = MagicMock()
    filt.check.return_value = (True, "ok")
    filt.__class__.__name__ = "ThrottlingFilter"
    return filt


def _make_failing_filter(reason: str = "blocked") -> MagicMock:
    filt = MagicMock()
    filt.check.return_value = (False, reason)
    filt.__class__.__name__ = "LogicFilters"
    return filt


def _make_workflow(
    profile,
    filters,
    job_repo,
    task_queue,
    event_bus,
    text_matcher,
    text_generation_port=None,
    perception_port=None,
) -> VettingWorkflow:
    return VettingWorkflow(
        profile=profile,
        filters=filters,
        job_repo=job_repo,
        task_queue=task_queue,
        event_bus=event_bus,
        text_matcher=text_matcher,
        text_generation_port=text_generation_port,
        perception_port=perception_port,
    )


# ─────────────────────────────────────────────────────────────────────────────


def test_run_passes_good_job(
    mock_profile,
    sample_job,
    mock_event_bus,
    mock_job_repo,
    mock_task_queue,
    mock_text_matcher,
):
    """A job that passes all filters is enqueued and run() returns True."""
    passing_filter = _make_passing_filter()
    wf = _make_workflow(
        profile=mock_profile,
        filters=[passing_filter],
        job_repo=mock_job_repo,
        task_queue=mock_task_queue,
        event_bus=mock_event_bus,
        text_matcher=mock_text_matcher,
    )

    result = wf.run(sample_job)

    assert result is True
    assert mock_task_queue.queue_task.call_count == 1

    published_events = [e for e, _ in mock_event_bus.published_events]
    assert Event.JOB_VETTED_PASS in published_events


def test_run_rejects_failing_job(
    mock_profile,
    sample_job,
    mock_event_bus,
    mock_job_repo,
    mock_task_queue,
    mock_text_matcher,
):
    """A job that fails a filter is not enqueued and run() returns False."""
    failing_filter = _make_failing_filter("title_blacklisted")
    wf = _make_workflow(
        profile=mock_profile,
        filters=[failing_filter],
        job_repo=mock_job_repo,
        task_queue=mock_task_queue,
        event_bus=mock_event_bus,
        text_matcher=mock_text_matcher,
    )

    result = wf.run(sample_job)

    assert result is False
    mock_task_queue.queue_task.assert_not_called()

    published_events = [e for e, _ in mock_event_bus.published_events]
    assert Event.JOB_VETTED_FAIL in published_events


def test_gpt4all_borderline_yes_bumps_score(
    mock_profile,
    sample_job,
    mock_event_bus,
    mock_job_repo,
    mock_task_queue,
    mock_text_matcher,
):
    """A borderline-score job receives YES from GPT4All → score bumped above band."""
    # One filter passes — partial score for one filter with weight 0.10 = 0.10,
    # which is within the default borderline band [0.45, 0.65].
    # We configure a very light filter to produce a borderline score and
    # test that the GPT4All YES response adjusts the outcome.

    # Use actual DEFAULT_WEIGHTS so we get a predictable fit_score.
    # With only ThrottlingFilter passing (weight=0.10), score = 0.10 < band.
    # Instead use weights that put a single-filter pass inside the band.
    custom_weights = {"SomeFilter": 0.55}

    passing_filter = MagicMock()
    passing_filter.check.return_value = (True, "ok")
    passing_filter.__class__.__name__ = "SomeFilter"

    gpt4all = MagicMock()
    gpt4all.generate.return_value = "YES"

    wf = VettingWorkflow(
        profile=mock_profile,
        filters=[passing_filter],
        job_repo=mock_job_repo,
        task_queue=mock_task_queue,
        event_bus=mock_event_bus,
        text_matcher=mock_text_matcher,
        text_generation_port=gpt4all,
        weights=custom_weights,
        borderline_band=(0.45, 0.65),
    )

    result = wf.run(sample_job)

    # Score 0.55 is in band [0.45, 0.65]; GPT4All says YES → bumped to 0.66
    assert result is True
    gpt4all.generate.assert_called_once()


def test_handles_missing_optional_dependency_gracefully(
    mock_profile,
    sample_job,
    mock_event_bus,
    mock_job_repo,
    mock_task_queue,
    mock_text_matcher,
):
    """Workflow runs without crash when GPT4All and perception_port are both None."""
    passing_filter = _make_passing_filter()
    wf = VettingWorkflow(
        profile=mock_profile,
        filters=[passing_filter],
        job_repo=mock_job_repo,
        task_queue=mock_task_queue,
        event_bus=mock_event_bus,
        text_matcher=mock_text_matcher,
        text_generation_port=None,
        perception_port=None,
    )

    # Must not raise, even with no GPT4All and no perception port
    result = wf.run(sample_job)

    assert isinstance(result, bool)


# ── BUG-5: _fetch_job_description uses the canonical get_page_text path ────────

def test_fetch_job_description_uses_get_page_text(
    mock_profile,
    sample_job,
    mock_event_bus,
    mock_job_repo,
    mock_task_queue,
    mock_text_matcher,
    mock_perception_port,
):
    """Description text comes from perception_port.get_page_text(), not text_content."""
    wf = _make_workflow(
        profile=mock_profile,
        filters=[_make_passing_filter()],
        job_repo=mock_job_repo,
        task_queue=mock_task_queue,
        event_bus=mock_event_bus,
        text_matcher=mock_text_matcher,
        perception_port=mock_perception_port,
    )

    text = wf._fetch_job_description(sample_job)

    mock_perception_port.navigate.assert_called_once_with(sample_job.url)
    mock_perception_port.get_page_text.assert_called_once()
    assert "Software Engineer" in text


def test_fetch_job_description_falls_back_to_title_when_text_empty(
    mock_profile,
    sample_job,
    mock_event_bus,
    mock_job_repo,
    mock_task_queue,
    mock_text_matcher,
    mock_perception_port,
):
    """An empty page text degrades to the job title rather than an empty string."""
    mock_perception_port.get_page_text.return_value = ""
    wf = _make_workflow(
        profile=mock_profile,
        filters=[_make_passing_filter()],
        job_repo=mock_job_repo,
        task_queue=mock_task_queue,
        event_bus=mock_event_bus,
        text_matcher=mock_text_matcher,
        perception_port=mock_perception_port,
    )

    text = wf._fetch_job_description(sample_job)

    assert text == sample_job.title


def test_fetch_job_description_no_perception_returns_title(
    mock_profile,
    sample_job,
    mock_event_bus,
    mock_job_repo,
    mock_task_queue,
    mock_text_matcher,
):
    """With no perception port, the title is used and navigate is never attempted."""
    wf = _make_workflow(
        profile=mock_profile,
        filters=[_make_passing_filter()],
        job_repo=mock_job_repo,
        task_queue=mock_task_queue,
        event_bus=mock_event_bus,
        text_matcher=mock_text_matcher,
        perception_port=None,
    )

    assert wf._fetch_job_description(sample_job) == (sample_job.title or "")
