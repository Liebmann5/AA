"""PageCopier — keep a cleaned copy of a page AA read (item 6).

Built by composition only when the person has turned page copies on (a
consent of its own, on top of research participation). Otherwise workflows
get NullPageCopier, which reads nothing and keeps nothing.

The order inside copy() is the privacy guarantee: read the page into
memory, clean it (page_redaction), and only then hand the CLEANED copy to
the store. The raw page is never written.

copy() does no disk I/O of its own: reading and cleaning happen here, the
write happens wherever the injected store does it — composition gives it a
background writer (QueuedPageCopyStore), so a copy never slows vetting.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Callable, Iterable
from datetime import datetime, timezone

from auto_apply.domain.models.page_copy import (
    PageCopy,
    PageSnapshot,
    PostingFacts,
    commitment,
)
from auto_apply.domain.ports.page_copy_port import PageCopyStorePort
from auto_apply.domain.services.page_redaction import redact_page

logger = logging.getLogger(__name__)

__all__ = ["PageCopier", "NullPageCopier", "COPY_CONTEXTS", "own_details"]

#: Pages AA may keep copies of. Search result pages are deliberately absent:
#: a results page contains the search itself, and AA never keeps searches.
COPY_CONTEXTS: frozenset[str] = frozenset({"job_posting"})


def own_details(personal_info: object) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The person's own details to remove from every copy, from their profile.

    Returns (values, names): ``values`` match in any letter case — full name
    forms, email, phone, street address; ``names`` are the single first,
    middle and last names, matched as written (see page_redaction). City,
    state and ZIP are NOT removed: they are where jobs are, and a job
    page's location is research data, not the person's.
    """

    def text(field: str) -> str:
        value = getattr(personal_info, field, None)
        return str(value).strip() if value else ""

    first, middle, last = text("first_name"), text("middle_name"), text("last_name")
    full_forms = {
        " ".join(p for p in (first, last) if p),
        " ".join(p for p in (first, middle, last) if p),
        ", ".join(p for p in (last, first) if p),
    }
    # A "full" form with one part is just a single name: it belongs with
    # the as-written names, not with the any-case values.
    multi_part = {f for f in full_forms if " " in f}
    contact = {text("email"), text("phone_number"), text("street_address")}
    values = tuple(sorted(v for v in multi_part | contact if v))
    names = tuple(sorted({n for n in (first, middle, last) if n}))
    return values, names


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class NullPageCopier:
    """Page copies are off: nothing is read, nothing is kept."""

    is_enabled = False

    def copy(
        self,
        context: str,
        url: str,
        read_html: Callable[[], str],
        facts: PostingFacts | None = None,
    ) -> str | None:
        return None


class PageCopier:
    """PageCopierPort over a store, with the person's own details to remove."""

    is_enabled = True

    def __init__(
        self,
        store: PageCopyStorePort,
        own_values: Iterable[str] = (),
        own_names: Iterable[str] = (),
        clock: Callable[[], str] = _utc_now,
        allowed: Callable[[], bool] = lambda: True,
        nonce: Callable[[bytes], bytes] = lambda _content: secrets.token_bytes(16),
    ) -> None:
        """
        Args:
            store: Where cleaned copies go (composition: a background writer).
            own_values: The person's details removed in any letter case.
            own_names: Single names removed as written.
            clock: UTC capture time, ISO 8601 to the second.
            allowed: Read before every copy; False stops it before the read.
            nonce: cleaned page -> 16-byte nonce. Composition passes
                derive_nonce under the installation's research key; the
                random default exists for tests and gives no deduplication.
        """
        self._store = store
        self._own_values = tuple(v for v in own_values if v and v.strip())
        self._own_names = tuple(n for n in own_names if n and n.strip())
        self._clock = clock
        self._allowed = allowed
        self._nonce = nonce
        #: Pages that could not be kept this session, by reason.
        self.failures: dict[str, int] = {}

    def _fail(self, reason: str) -> None:
        self.failures[reason] = self.failures.get(reason, 0) + 1

    def copy(
        self,
        context: str,
        url: str,
        read_html: Callable[[], str],
        facts: PostingFacts | None = None,
    ) -> str | None:
        if context not in COPY_CONTEXTS:
            self._fail("context_not_allowed")
            return None
        try:
            # Read on every copy, so turning copies off (or withdrawing from
            # research) mid-session stops the very next one.
            if not self._allowed():
                return None
        except Exception:  # noqa: BLE001 — unknown means no
            return None
        try:
            snapshot = PageSnapshot(
                context=context, url=url, html=read_html() or "", captured_at=self._clock()
            )
        except Exception as exc:  # noqa: BLE001 — a copy must never break a workflow
            self._fail("read_failed")
            logger.debug("PageCopier: could not read the page (%s)", type(exc).__name__)
            return None
        if not snapshot.html.strip():
            self._fail("empty_page")
            return None
        cleaned, redactions = redact_page(snapshot.html, self._own_values, self._own_names)
        content = cleaned.encode("utf-8")
        nonce = self._nonce(content)
        page_copy = PageCopy(
            copy_id=commitment(nonce, content),
            nonce=nonce.hex(),
            context=snapshot.context,
            url=snapshot.url,
            captured_at=snapshot.captured_at,
            content=content,
            redactions=redactions,
            facts=facts,
        )
        try:
            kept = self._store.save(page_copy)
        except Exception as exc:  # noqa: BLE001
            self._fail("save_failed")
            logger.warning("PageCopier: could not keep the copy (%s)", type(exc).__name__)
            return None
        if kept is None:
            self._fail("not_kept")  # e.g. the background writer's queue was full
        return kept
