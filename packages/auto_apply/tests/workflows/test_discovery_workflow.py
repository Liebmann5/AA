"""Tests for DiscoveryWorkflow.

Covers:
    - Basic run() returns enqueued count.
    - Deduplication drops jobs already seen.
    - A single provider failure does not abort sibling providers.
    - Graceful degradation when optional dependencies (SpaCy, ATSRegistry) are absent.
"""
import pytest
from unittest.mock import MagicMock, patch

from auto_apply.application.workflows.discovery_workflow import DiscoveryWorkflow
from auto_apply.domain.models.job import Job
from auto_apply.domain.models.search_instruction import SearchInstruction
from auto_apply.domain.events import Event


def _make_mock_provider(jobs: list[Job], name: str = "MockProvider") -> MagicMock:
    """Build a MagicMock discovery provider that returns the given jobs."""
    provider = MagicMock()
    provider.__class__.__name__ = name
    provider.requires_live_browser = False
    provider.run.return_value = jobs
    return provider


def _make_workflow(
    profile,
    providers,
    task_queue,
    event_bus,
    text_matcher,
    dedup=None,
    ats_registry=None,
) -> DiscoveryWorkflow:
    if dedup is None:
        dedup = MagicMock()
        # is_duplicate returns False = "not seen yet" (new job, passes dedup)
        dedup.is_duplicate.return_value = False
        dedup.mark_seen.return_value = None
    return DiscoveryWorkflow(
        profile=profile,
        providers=providers,
        task_queue=task_queue,
        event_bus=event_bus,
        dedup=dedup,
        text_matcher=text_matcher,
        ats_registry=ats_registry,
    )


# ─────────────────────────────────────────────────────────────────────────────


def test_run_returns_enqueued_count(
    mock_profile, mock_event_bus, mock_task_queue, mock_text_matcher
):
    """run() returns the number of unique jobs enqueued for vetting."""
    jobs = [
        Job(title="SWE", company="Acme", url="https://acme.com/1", source="test"),
        Job(title="SWE", company="Blume", url="https://blume.com/2", source="test"),
    ]
    provider = _make_mock_provider(jobs)
    wf = _make_workflow(
        profile=mock_profile,
        providers=[provider],
        task_queue=mock_task_queue,
        event_bus=mock_event_bus,
        text_matcher=mock_text_matcher,
    )

    # Provide a single SearchInstruction so DiscoveryWorkflow doesn't derive from the profile.
    count = wf.run(instructions=[SearchInstruction(title="SWE", location="Remote")])

    assert count == 2
    assert mock_task_queue.queue_task.call_count == 2


def test_deduplication_drops_seen_jobs(
    mock_profile, mock_event_bus, mock_task_queue, mock_text_matcher
):
    """Jobs that DeduplicationManager marks as seen are not enqueued."""
    jobs = [
        Job(title="SWE", company="Acme", url="https://acme.com/1", source="test"),
        Job(title="SWE", company="Blume", url="https://blume.com/2", source="test"),
    ]
    provider = _make_mock_provider(jobs)

    # First job is new (is_duplicate=False), second is duplicate (is_duplicate=True)
    dedup = MagicMock()
    dedup.is_duplicate.side_effect = [False, True]
    dedup.mark_seen.return_value = None

    wf = _make_workflow(
        profile=mock_profile,
        providers=[provider],
        task_queue=mock_task_queue,
        event_bus=mock_event_bus,
        text_matcher=mock_text_matcher,
        dedup=dedup,
    )

    # Provide a single SearchInstruction to force exactly one query.
    count = wf.run(instructions=[SearchInstruction(title="SWE", location="Remote")])

    # Only 1 job should be enqueued; duplicate was dropped
    assert count == 1
    assert mock_task_queue.queue_task.call_count == 1

    # TASK_SKIPPED_DUPLICATE event should have been published
    published_events = [e for e, _ in mock_event_bus.published_events]
    assert Event.TASK_SKIPPED_DUPLICATE in published_events


def test_provider_failure_does_not_abort_siblings(
    mock_profile, mock_event_bus, mock_task_queue, mock_text_matcher
):
    """A provider that raises an exception does not prevent others from running."""
    good_job = Job(
        title="SWE", company="Acme", url="https://acme.com/1", source="test"
    )
    failing_provider = MagicMock()
    failing_provider.requires_live_browser = False
    failing_provider.run.side_effect = RuntimeError("Provider exploded")

    good_provider = _make_mock_provider([good_job], name="GoodProvider")

    wf = _make_workflow(
        profile=mock_profile,
        providers=[failing_provider, good_provider],
        task_queue=mock_task_queue,
        event_bus=mock_event_bus,
        text_matcher=mock_text_matcher,
    )

    # Provide a single SearchInstruction to force exactly one query.
    count = wf.run(instructions=[SearchInstruction(title="SWE", location="Remote")])

    # The good provider's job should still be enqueued despite the sibling failing
    assert count == 1
    assert mock_task_queue.queue_task.call_count == 1


def test_handles_missing_optional_dependency_gracefully(
    mock_profile, mock_event_bus, mock_task_queue, mock_text_matcher
):
    """Workflow runs without crash when ats_registry is None and providers list is empty."""
    wf = DiscoveryWorkflow(
        profile=mock_profile,
        providers=[],
        task_queue=mock_task_queue,
        event_bus=mock_event_bus,
        dedup=MagicMock(),
        text_matcher=mock_text_matcher,
        ats_registry=None,
    )

    # No SearchInstructions and no providers → 0 enqueued, no crash.
    count = wf.run()

    assert count == 0