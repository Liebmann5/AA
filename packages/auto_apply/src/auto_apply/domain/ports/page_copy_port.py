"""Ports for page copies (item 6).

* PageCopyStorePort — where cleaned copies are kept on this device (the
  WARC store), and how they are expired and deleted.
* PageCopierPort — what a workflow calls when it has just read a page:
  "keep a cleaned copy of this, if the person allowed it". Returns the
  copy's fingerprint for the research row, or None.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Protocol, runtime_checkable

from auto_apply.domain.models.page_copy import PageCopy, PostingFacts

__all__ = ["PageCopyStorePort", "PageCopierPort"]


@runtime_checkable
class PageCopyStorePort(Protocol):
    """Keeps cleaned page copies on this device."""

    def save(self, copy: PageCopy) -> str | None:
        """Keep one copy; return the fingerprint research rows should carry,
        or None when the copy will not be kept (a full background queue).

        A page whose cleaned bytes are already kept under the same
        fingerprint is not written again. A store may write in the
        background: a returned fingerprint means the copy was ACCEPTED, and
        a write that later fails is counted by the store, not reported here.
        """
        ...

    def discard(self, copy: PageCopy) -> None:
        """Delete this one copy if it is kept (used when permission was
        withdrawn while it was being written)."""
        ...

    def expire(self, today: date, keep_days: int) -> int:
        """Delete copies older than ``keep_days``. Returns how many."""
        ...

    def purge(self) -> int:
        """Delete every copy. Returns how many."""
        ...

    def count(self) -> int:
        """How many copies are kept."""
        ...


@runtime_checkable
class PageCopierPort(Protocol):
    """Called by a workflow right after it reads a page."""

    @property
    def is_enabled(self) -> bool:
        ...

    def copy(
        self,
        context: str,
        url: str,
        read_html: Callable[[], str],
        facts: PostingFacts | None = None,
    ) -> str | None:
        """Keep a cleaned copy of the page just read, if allowed.

        ``facts`` (item 7) is what the listing said about the posting; it
        is kept with the copy so a replay can observe the posting as the
        live run did.

        ``read_html`` is called only when a copy will be kept, so a
        workflow pays nothing when page copies are off. Returns the copy's
        fingerprint, or None (off, nothing read, or the save failed —
        never raises).
        """
        ...
