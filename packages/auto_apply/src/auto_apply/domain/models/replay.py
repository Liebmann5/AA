"""Replay values (item 7): what goes into a replay and what comes out.

A replay re-runs text extraction and the research detectors over a fixed
corpus of kept page copies, with no browser, no network, no database and no
clock. Same corpus + same AA version = the same bytes, on every operating
system and Python version AA supports (CI checks this on all six legs).

Pure data, standard library only.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from auto_apply.domain.models.page_copy import PostingFacts

__all__ = [
    "REPLAY_FORMAT",
    "ReplayItem",
    "ReplaySkip",
    "ReplayCorpus",
    "ReplayOutput",
    "ReplayReport",
]

#: Named in every manifest. Change it whenever the record or manifest
#: layout changes, so two artifacts in different layouts are never compared
#: as if they were one.
REPLAY_FORMAT = "aa-replay/1"


@dataclass(frozen=True)
class ReplayItem:
    """One kept page copy, read from the corpus.

    Attributes:
        source: The file's path inside the corpus, with forward slashes —
            never an absolute path, so the artifact does not depend on where
            the corpus sits on disk.
        copy_id: The copy's fingerprint (what research rows carry).
        context: Why the page was read ("job_posting").
        captured_at: When it was read, ISO 8601 UTC. The replay uses this
            date as "today"; the replay's own date never enters the result.
        url: Where it was read.
        page: The cleaned page source.
        facts: What the listing said, or None for a copy made before item 7.
    """

    source: str
    copy_id: str
    context: str
    captured_at: str
    url: str
    page: str
    facts: PostingFacts | None = None


@dataclass(frozen=True)
class ReplaySkip:
    """A corpus file that was read but not replayed, and why."""

    source: str
    reason: str


@dataclass(frozen=True)
class ReplayCorpus:
    """Everything a corpus reader found.

    Attributes:
        files: (source, sha256 hex) for EVERY file considered, replayed or
            skipped, sorted by source — the corpus's identity.
        items: The copies to replay.
        skipped: Files read but not replayed.
    """

    files: tuple[tuple[str, str], ...]
    items: tuple[ReplayItem, ...]
    skipped: tuple[ReplaySkip, ...] = ()


@dataclass(frozen=True)
class ReplayOutput:
    """The replay's result, as the exact bytes to write.

    Attributes:
        records: replay.jsonl — one canonical JSON line per replayed copy.
        manifest: manifest.json — what was replayed, how, and the digests.
        corpus_digest: sha256 hex over the corpus file list.
        artifact_sha256: sha256 hex of ``records``.
        manifest_sha256: sha256 hex of ``manifest`` — the one number that
            identifies the whole result (it covers the artifact digest).
        items: Copies replayed.
        signals: Signals produced.
        skipped: Files not replayed.
    """

    records: bytes
    manifest: bytes
    corpus_digest: str
    artifact_sha256: str
    manifest_sha256: str
    items: int
    signals: int
    skipped: tuple[ReplaySkip, ...] = ()


@dataclass(frozen=True)
class ReplayReport:
    """What a surface shows after a replay.

    Attributes:
        output: The result (digests and counts).
        location: Where the artifact was written (for display only).
        signals_by_type: (signal_type, count) sorted by signal_type.
    """

    output: ReplayOutput
    location: str
    signals_by_type: tuple[tuple[str, int], ...] = field(default_factory=tuple)
