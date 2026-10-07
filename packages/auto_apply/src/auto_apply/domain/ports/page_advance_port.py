"""PageAdvancePort — one verified attempt to move a results page forward.

Implemented by VerifiedPageAdvancer (adapters/secondary/navigation/
page_advancer.py). Consumers (GenericSERPStrategy) never learn HOW a page
advances — URL template, rel=next, structural control, numbered control,
load-more, or scroll growth — only whether it verifiably did. A fresh
instance serves one query; the port is deliberately stateless-looking so a
shared instance cannot leak a page position across queries.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from auto_apply.domain.models.page_advance import AdvanceOutcome


@runtime_checkable
class PageAdvancePort(Protocol):
    """The single page-advance verb."""

    def advance(self) -> AdvanceOutcome:
        """Try one step forward. Never raises; an unverifiable advance is
        ``AdvanceOutcome(advanced=False)`` with a stop reason, not a guess."""
        ...
