"""WarcReplayCorpus — a folder of kept page copies, read as a replay corpus.

Reads every ``*.warc.gz`` under the folder (at any depth — the page-copy
store keeps one folder per capture day), in sorted order of their path
inside the corpus, so the corpus reads the same on every file system.
Half-written files (``*.partial``) are not part of a corpus and are not
read. A file that cannot be read as a page copy is listed as skipped with
the reason; it never stops the replay, and it still counts in the corpus's
identity, so two corpora that differ only in a broken file do not look
alike.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from auto_apply.adapters.secondary.research.warc_page_store import read_warc_records
from auto_apply.domain.models.page_copy import PostingFacts
from auto_apply.domain.models.replay import ReplayCorpus, ReplayItem, ReplaySkip

__all__ = ["WarcReplayCorpus"]


class WarcReplayCorpus:
    """ReplayCorpusPort over a folder of WARC page copies."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def read(self) -> ReplayCorpus:
        if not self._root.is_dir():
            raise FileNotFoundError(f"no corpus folder at {self._root}")
        paths = sorted(
            (p for p in self._root.rglob("*.warc.gz") if p.is_file()),
            key=lambda p: p.relative_to(self._root).as_posix(),
        )
        files: list[tuple[str, str]] = []
        items: list[ReplayItem] = []
        skipped: list[ReplaySkip] = []
        for path in paths:
            source = path.relative_to(self._root).as_posix()
            data = path.read_bytes()
            files.append((source, hashlib.sha256(data).hexdigest()))
            try:
                items.append(self._parse(source, path))
            except Exception as exc:  # noqa: BLE001 — a bad file is a skip
                skipped.append(ReplaySkip(source, f"not a readable page copy ({type(exc).__name__})"))
        return ReplayCorpus(files=tuple(files), items=tuple(items), skipped=tuple(skipped))

    @staticmethod
    def _parse(source: str, path: Path) -> ReplayItem:
        resource: tuple[dict[str, str], bytes] | None = None
        metadata: dict[str, object] | None = None
        for headers, block in read_warc_records(path):
            kind = headers.get("WARC-Type")
            if kind == "resource":
                resource = (headers, block)
            elif kind == "metadata":
                metadata = json.loads(block.decode("utf-8"))
        if resource is None or metadata is None:
            raise ValueError("missing resource or metadata record")
        posting = metadata.get("posting")
        facts = None
        if isinstance(posting, dict):
            facts = PostingFacts(
                job_title=str(posting.get("job_title") or ""),
                location=posting.get("location") if isinstance(posting.get("location"), str) else None,
                platform=posting.get("platform") if isinstance(posting.get("platform"), str) else None,
            )
        return ReplayItem(
            source=source,
            copy_id=str(metadata["copy_id"]),
            context=str(metadata["context"]),
            captured_at=str(metadata["captured_at"]),
            url=resource[0].get("WARC-Target-URI", ""),
            page=resource[1].decode("utf-8"),
            facts=facts,
        )
