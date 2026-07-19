"""Tests for CompanyBatchScheduler in isolation.

No real browser, orchestrator, or event loop.  The WorkQueuePort is mocked
so we can verify dedup behaviour and buffer management.
"""

from unittest.mock import MagicMock

import pytest

from auto_apply.application.services.company_batch_scheduler import CompanyBatchScheduler
from auto_apply.domain.models.job import Job


@pytest.fixture
def mock_task_queue():
    """A WorkQueuePort mock — has_applied_previously defaults to False."""
    q = MagicMock()
    q.has_applied_previously.return_value = False
    return q


@pytest.fixture
def scheduler(mock_task_queue):
    return CompanyBatchScheduler(task_queue=mock_task_queue, batch_threshold=2)


def _job(title="Engineer", company="Acme", url="https://acme.com/1"):
    return Job(title=title, company=company, url=url, source="test")


class TestBufferingAndDedup:
    """Verify internal buffering and cross‑session rejections."""

    def test_buffer_job_accepts_and_returns_true(self, scheduler, mock_task_queue):
        assert scheduler.buffer_job(_job()) is True
        assert scheduler.has_any_buffered() is True

    def test_buffer_job_rejects_duplicate(self, scheduler, mock_task_queue):
        mock_task_queue.has_applied_previously.return_value = True
        assert scheduler.buffer_job(_job(url="dup")) is False
        # Duplicate must not be stored.
        assert scheduler.has_any_buffered() is False

    def test_buffer_job_handles_db_exception_gracefully(self, scheduler, mock_task_queue):
        mock_task_queue.has_applied_previously.side_effect = RuntimeError("db down")
        # Should treat as not‑duplicate (fail‑open) and accept the job.
        assert scheduler.buffer_job(_job()) is True
        assert scheduler.has_any_buffered() is True


class TestBatchReadiness:
    """Verify that check_batch_ready reports correctly."""

    def test_ready_after_threshold(self, scheduler):
        scheduler.buffer_job(_job(company="A", url="1"))
        scheduler.buffer_job(_job(company="A", url="2"))
        assert scheduler.check_batch_ready() is True

    def test_not_ready_below_threshold(self, scheduler):
        scheduler.buffer_job(_job(company="A", url="1"))
        assert scheduler.check_batch_ready() is False

    def test_ready_after_mixed_companies(self, scheduler):
        scheduler.buffer_job(_job(company="A", url="1"))
        scheduler.buffer_job(_job(company="A", url="2"))
        scheduler.buffer_job(_job(company="B", url="1"))  # only one for B
        assert scheduler.check_batch_ready() is True  # A is ready


class TestBatchDragging:
    """Verify pop_best_ready_batch and flush_all_batches."""

    def test_pop_returns_correct_company_and_jobs(self, scheduler):
        scheduler.buffer_job(_job(company="A", url="1"))
        scheduler.buffer_job(_job(company="A", url="2"))
        scheduler.buffer_job(_job(company="B", url="1"))
        # Only A is ready; B has one job.
        company_key, jobs = scheduler.pop_best_ready_batch()
        assert company_key == "a"
        assert len(jobs) == 2
        # A's buffer should be removed; B remains.
        assert scheduler.has_any_buffered()
        # Pop again should not return A.
        assert not scheduler.check_batch_ready()

    def test_flush_all_batches_returns_all(self, scheduler):
        scheduler.buffer_job(_job(company="A", url="1"))
        scheduler.buffer_job(_job(company="A", url="2"))
        scheduler.buffer_job(_job(company="B", url="1"))
        remaining = scheduler.flush_all_batches()
        assert len(remaining) == 2
        assert len(remaining["a"]) == 2
        assert len(remaining["b"]) == 1
        assert not scheduler.has_any_buffered()


class TestSingleDedupCallSite:
    """Prove that the cross‑session dedup implementation is shared between
    buffering and future flush processing (the orchestrator would call
    is_duplicate again during its batch loop, but all paths funnel through
    the same `is_duplicate` method on the scheduler).
    """

    def test_buffer_and_apply_both_call_dedup(self, scheduler, mock_task_queue):
        """Simulate one job arriving via buffer and later being processed:
        the dedup method must be exercised from both call sites."""
        job_a = _job(url="a")
        # Buffer the job — calls is_duplicate indirectly via buffer_job.
        assert scheduler.buffer_job(job_a) is True
        mock_task_queue.has_applied_previously.assert_called_with("a")
        mock_task_queue.reset_mock()

        # Simulate what _process_batch would do: check dedup per job before running.
        assert scheduler.is_duplicate(job_a.url) is False
        mock_task_queue.has_applied_previously.assert_called_with("a")

    def test_dedup_called_exactly_once_per_dedup_method_invocation(self, scheduler, mock_task_queue):
        """The dedup database query is called via scheduler.is_duplicate,
        which is the SINGLE implementation.  We can verify the mock is called
        every time we invoke the method, regardless of path."""
        # Direct call
        scheduler.is_duplicate("x")
        assert mock_task_queue.has_applied_previously.call_count == 1
        # Buffer path
        scheduler.buffer_job(_job(url="x"))
        # buffer_job calls is_duplicate → has_applied_previously again
        assert mock_task_queue.has_applied_previously.call_count == 2