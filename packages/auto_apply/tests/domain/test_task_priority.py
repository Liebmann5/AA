"""The discovery-pipeline priority bands must interleave per search (ADR-011).

The work queue dispatches ORDER BY priority ASC, created_at ASC (confirmed in
database.get_next_task). These pins model that ordering faithfully and prove the
named bands make each search flow discover -> vet -> apply before the next
search's discovery — the fix for the batch behaviour caused by VET and DISCOVER
sharing priority 5.
"""
from __future__ import annotations

from auto_apply.domain.models.task_priority import TaskPriority


class _MiniQueue:
    """Faithful model of the real work queue's dispatch order: most urgent first
    (lowest priority number), ties broken by insertion order — i.e. the
    ``ORDER BY priority ASC, created_at ASC`` in database.get_next_task."""

    def __init__(self) -> None:
        self._items: list[tuple[int, int, str]] = []
        self._seq = 0

    def put(self, priority: int, tag: str) -> None:
        self._items.append((priority, self._seq, tag))
        self._seq += 1

    def pop(self) -> str | None:
        if not self._items:
            return None
        self._items.sort(key=lambda x: (x[0], x[1]))
        return self._items.pop(0)[2]


def _drain_pipeline(queue: _MiniQueue) -> list[str]:
    """Drive the mini pipeline: a discovery enqueues that search's vetting, a
    vetting enqueues that search's application. Returns dispatch order."""
    order: list[str] = []
    while (tag := queue.pop()) is not None:
        order.append(tag)
        stage, _, search = tag.partition(":")
        if stage == "discover":
            queue.put(TaskPriority.VET, f"vet:{search}")
        elif stage == "vet":
            queue.put(TaskPriority.apply_for_fit(0.9), f"apply:{search}")
    return order


def test_pipeline_interleaves_per_search():
    q = _MiniQueue()
    q.put(TaskPriority.DISCOVER, "discover:s1")  # seeded up front, as the controller does
    q.put(TaskPriority.DISCOVER, "discover:s2")
    order = _drain_pipeline(q)
    # Each search fully drains (discover -> vet -> apply) before the next search
    # is discovered — the "one search -> vet -> apply -> next search" behaviour.
    assert order == [
        "discover:s1", "vet:s1", "apply:s1",
        "discover:s2", "vet:s2", "apply:s2",
    ], order


def test_bands_are_ordered_apply_lt_vet_lt_discover():
    # even the worst-fit application still outranks vetting and discovery
    assert TaskPriority.apply_for_fit(0.0) < TaskPriority.VET < TaskPriority.DISCOVER
    assert TaskPriority.apply_for_fit(1.0) < TaskPriority.VET


def test_applications_are_fit_ordered_within_band():
    assert (
        TaskPriority.apply_for_fit(1.0)
        < TaskPriority.apply_for_fit(0.5)
        < TaskPriority.apply_for_fit(0.0)
    )
    assert TaskPriority.apply_for_fit(1.0) == TaskPriority.APPLY_BASE
    assert (
        TaskPriority.apply_for_fit(0.0)
        == TaskPriority.APPLY_BASE + TaskPriority.APPLY_SPREAD
    )


def test_apply_for_fit_handles_none_and_out_of_range():
    assert TaskPriority.apply_for_fit(None) == TaskPriority.APPLY_BASE + TaskPriority.APPLY_SPREAD
    assert TaskPriority.apply_for_fit(2.0) == TaskPriority.APPLY_BASE       # clamped to 1.0
    assert TaskPriority.apply_for_fit(-1.0) == TaskPriority.APPLY_BASE + TaskPriority.APPLY_SPREAD
