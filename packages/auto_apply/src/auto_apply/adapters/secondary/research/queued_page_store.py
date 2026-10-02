"""QueuedPageCopyStore — page copies are written off the workflow's path (item 6).

The research module's rule (docs/research_module/index.md, "Non-Blocking by
Design"): research collection cannot slow down a session; its I/O happens
on a background writer. Vetting reads and cleans a page (memory and CPU
only) and hands the cleaned copy here; this store queues it and returns at
once. A writer thread does the disk work.

Bounded: when the queue is full the copy is DROPPED and counted — the
workflow is never made to wait, and the research row then carries no
page_copy_id (save returns None), so no row points at a copy that was never
going to exist.

Permission is re-read on the writer: a copy queued before the person turned
copies off (or withdrew from research) is not written, and a copy whose write
was already under way when they did is deleted again right after.

The writer thread starts on the first save and exits after a few idle
seconds, so a process that builds many sessions (the GUI) does not collect
idle threads. close() — also registered with atexit — drains what is queued.
"""

from __future__ import annotations

import atexit
import logging
import queue
import threading
import time
import weakref
from collections.abc import Callable
from datetime import date

from auto_apply.domain.models.page_copy import PageCopy
from auto_apply.domain.ports.page_copy_port import PageCopyStorePort

logger = logging.getLogger(__name__)

__all__ = ["QueuedPageCopyStore"]


class QueuedPageCopyStore:
    """PageCopyStorePort that writes through ``inner`` on a background thread."""

    def __init__(
        self,
        inner: PageCopyStorePort,
        allowed: Callable[[], bool] = lambda: True,
        max_pending: int = 64,
        idle_seconds: float = 5.0,
    ) -> None:
        self._inner = inner
        self._allowed = allowed
        self._queue: queue.Queue[PageCopy] = queue.Queue(maxsize=max(max_pending, 1))
        self._idle_seconds = idle_seconds
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        #: Copies not kept, by reason ("queue_full", "not_allowed",
        #: "write_failed", "withdrawn_during_write").
        self.failures: dict[str, int] = {}
        self.written = 0
        # Weakly: a store a finished session dropped must not be kept alive
        # by the exit hook.
        close = weakref.WeakMethod(self.close)
        atexit.register(lambda: (method := close()) is not None and method())

    def _count(self, reason: str) -> None:
        with self._lock:
            self.failures[reason] = self.failures.get(reason, 0) + 1

    # ── PageCopyStorePort ───────────────────────────────────────────────────

    def save(self, copy: PageCopy) -> str | None:
        with self._lock:
            try:
                self._queue.put_nowait(copy)
            except queue.Full:
                self.failures["queue_full"] = self.failures.get("queue_full", 0) + 1
                return None
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._run, name="page-copy-writer", daemon=True
                )
                self._thread.start()
        return copy.copy_id

    def discard(self, copy: PageCopy) -> None:
        self._inner.discard(copy)

    def expire(self, today: date, keep_days: int) -> int:
        return self._inner.expire(today, keep_days)

    def purge(self) -> int:
        self._drain_pending("not_allowed")
        return self._inner.purge()

    def count(self) -> int:
        return self._inner.count()

    # ── Writer ──────────────────────────────────────────────────────────────

    def _allowed_now(self) -> bool:
        try:
            return bool(self._allowed())
        except Exception:  # noqa: BLE001 — unknown permission is no permission
            return False

    def _write(self, copy: PageCopy) -> None:
        if not self._allowed_now():
            self._count("not_allowed")
            return
        try:
            self._inner.save(copy)
        except Exception as exc:  # noqa: BLE001 — counted; never raised
            self._count("write_failed")
            logger.warning("Page copies | a copy could not be written (%s)", type(exc).__name__)
            return
        if not self._allowed_now():
            # Turned off while this copy was being written: the deletion the
            # person asked for may already have run, so remove this one too.
            try:
                self._inner.discard(copy)
            finally:
                self._count("withdrawn_during_write")
            return
        with self._lock:
            self.written += 1

    def _run(self) -> None:
        while True:
            try:
                copy = self._queue.get(timeout=self._idle_seconds)
            except queue.Empty:
                with self._lock:
                    if self._queue.empty():
                        self._thread = None
                        return
                continue
            try:
                self._write(copy)
            finally:
                self._queue.task_done()

    def _drain_pending(self, reason: str) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return
            self._queue.task_done()
            self._count(reason)

    def close(self, timeout: float = 10.0) -> bool:
        """Wait (up to ``timeout`` seconds) for queued copies to be written.

        Returns True when nothing is left pending.
        """
        deadline = time.monotonic() + timeout
        while self._queue.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.02)
        return not self._queue.unfinished_tasks
