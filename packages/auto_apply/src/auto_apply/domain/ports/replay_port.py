"""Ports for replay (item 7).

* ReplayCorpusPort — where a replay's corpus comes from (a folder of kept
  page copies, today).
* ReplayArtifactSinkPort — where its result goes, written byte for byte.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from auto_apply.domain.models.replay import ReplayCorpus

__all__ = ["ReplayCorpusPort", "ReplayArtifactSinkPort"]


@runtime_checkable
class ReplayCorpusPort(Protocol):
    """Reads a fixed corpus of kept page copies."""

    def read(self) -> ReplayCorpus:
        """Every file considered (with its sha256), the copies to replay, and
        the files that could not be replayed with the reason. A file that
        cannot be read is a skip, never an exception; a corpus that does not
        exist raises FileNotFoundError."""
        ...


@runtime_checkable
class ReplayArtifactSinkPort(Protocol):
    """Writes a replay's files exactly as given — no newline translation, no
    re-encoding."""

    def write(self, files: Mapping[str, bytes]) -> str:
        """Write every (name, bytes) pair; return where they went, for
        display."""
        ...
