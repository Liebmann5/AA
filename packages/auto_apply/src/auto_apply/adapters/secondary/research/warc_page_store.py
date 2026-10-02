"""WarcPageStore — cleaned page copies as WARC files, on this device (item 6).

WARC (ISO 28500) is the web-archiving standard: any archive tool can open
these files (ReplayWeb.page, warcio, pywb). Each copy is one file holding
three records, each gzipped separately as the format recommends:

* ``warcinfo`` — what wrote the file;
* ``resource`` — the cleaned page. It is a RESOURCE record, not a
  ``response``: AA reads the page through a browser and has the rendered
  page, not the bytes the server sent, and the record type says so rather
  than pretending otherwise;
* ``metadata`` — why the page was read, when, how, what cleaning removed
  (rule by rule), and what the listing said about the posting (title,
  location, platform) for replays.

Deterministic: record ids are derived from the copy's fingerprint and the
gzip headers carry no timestamp, so the same copy always produces the same
bytes. A page already kept under the same fingerprint is not written again.
After the research key changes, the same page gets a new fingerprint and is
kept again under it; the older copy stays until it expires, and each
verifies the rows that name it.

Bounded: with ``max_bytes`` set, the oldest copies (by capture day) are
deleted once the folder grows past it — a person whose only storage is a USB
drive must not find it filled by research copies. The copy just written is
never the one deleted.

Layout: ``<root>/<YYYY-MM-DD>/<first 16 hex of the fingerprint>.warc.gz``,
one folder per capture day, so expiry deletes whole days. The name comes
from the fingerprint (the keyed commitment research rows carry), NOT from a
plain hash of the page: file names appear in replay manifests (item 7), and
a plain page hash there would let anyone holding the same public page test
whether it is in someone's corpus — the guess the commitment exists to stop
(see domain/models/page_copy.py).

Standard library only: worst-case machines get page copies without an extra
dependency.
"""

from __future__ import annotations

import gzip
import io
import json
import logging
import shutil
import uuid
from datetime import date, timedelta
from pathlib import Path

from auto_apply.domain.models.page_copy import PageCopy, content_digest

logger = logging.getLogger(__name__)

__all__ = ["WarcPageStore", "read_warc_records"]

_NAMESPACE = uuid.UUID("6f1c5b0e-2f43-4c4e-9d4a-6b1d9e0a7a11")


def _record_id(copy_id: str, kind: str) -> str:
    return f"<urn:uuid:{uuid.uuid5(_NAMESPACE, f'{copy_id}/{kind}')}>"


def _gzip_member(data: bytes) -> bytes:
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as gz:
        gz.write(data)
    return buffer.getvalue()


def _record(headers: list[tuple[str, str]], block: bytes) -> bytes:
    lines = ["WARC/1.1"] + [f"{k}: {v}" for k, v in headers] + [
        f"WARC-Block-Digest: {content_digest(block)}",
        f"Content-Length: {len(block)}",
    ]
    head = ("\r\n".join(lines) + "\r\n\r\n").encode("utf-8")
    return _gzip_member(head + block + b"\r\n\r\n")


def read_warc_records(path: Path) -> list[tuple[dict[str, str], bytes]]:
    """Read back every record of a file this store wrote: (headers, block)."""
    raw = gzip.decompress(path.read_bytes())
    records: list[tuple[dict[str, str], bytes]] = []
    pos = 0
    while pos < len(raw):
        head_end = raw.index(b"\r\n\r\n", pos)
        head = raw[pos:head_end].decode("utf-8").split("\r\n")
        headers = dict(line.split(": ", 1) for line in head[1:])
        length = int(headers["Content-Length"])
        start = head_end + 4
        records.append((headers, raw[start : start + length]))
        pos = start + length + 4
    return records


class WarcPageStore:
    """PageCopyStorePort over a folder of WARC files."""

    def __init__(
        self, root: Path, software: str = "AutoApply", max_bytes: int | None = None
    ) -> None:
        self._root = root
        self._software = software
        self._max_bytes = max_bytes
        #: Copies deleted to stay under max_bytes, since construction.
        self.evicted = 0

    def _name(self, copy: PageCopy) -> str:
        return f"{copy.copy_id.split(':', 1)[1][:16]}.warc.gz"

    def _kept(self, copy: PageCopy) -> Path | None:
        """The file already keeping this copy, on any day, if one exists."""
        if not self._root.is_dir():
            return None
        for found in self._root.glob(f"*/{self._name(copy)}"):
            return found
        return None

    @staticmethod
    def _kept_id(path: Path) -> str | None:
        try:
            for headers, block in read_warc_records(path):
                if headers.get("WARC-Type") == "metadata":
                    return str(json.loads(block)["copy_id"])
        except (OSError, ValueError, KeyError):
            return None  # unreadable: replaced below
        return None

    def save(self, copy: PageCopy) -> str:
        kept = self._kept(copy)
        if kept is not None:
            if self._kept_id(kept) == copy.copy_id:
                return copy.copy_id
            kept.unlink(missing_ok=True)
        path = self._root / copy.captured_at[:10] / self._name(copy)
        info = json.dumps(
            {
                "software": self._software,
                "format": "WARC/1.1",
                "note": "Cleaned page copies kept on this device; see docs/research_module.",
            },
            sort_keys=True,
        ).encode("utf-8")
        metadata = json.dumps(
            {
                "copy_id": copy.copy_id,
                "nonce": copy.nonce,
                "context": copy.context,
                "captured_at": copy.captured_at,
                "method": copy.method,
                "redactions": dict(copy.redactions),
                # What the listing said (item 7): a replay needs it to
                # observe the posting as the live run did. null when the
                # copy was made without it.
                "posting": copy.facts.as_dict() if copy.facts else None,
            },
            sort_keys=True,
        ).encode("utf-8")
        resource_id = _record_id(copy.copy_id, "resource")
        data = b"".join(
            (
                _record(
                    [
                        ("WARC-Type", "warcinfo"),
                        ("WARC-Record-ID", _record_id(copy.copy_id, "warcinfo")),
                        ("WARC-Date", copy.captured_at),
                        ("Content-Type", "application/json"),
                    ],
                    info,
                ),
                _record(
                    [
                        ("WARC-Type", "resource"),
                        ("WARC-Record-ID", resource_id),
                        ("WARC-Date", copy.captured_at),
                        ("WARC-Target-URI", copy.url),
                        ("WARC-Payload-Digest", copy.digest),
                        ("Content-Type", "text/html; charset=utf-8"),
                    ],
                    copy.content,
                ),
                _record(
                    [
                        ("WARC-Type", "metadata"),
                        ("WARC-Record-ID", _record_id(copy.copy_id, "metadata")),
                        ("WARC-Date", copy.captured_at),
                        ("WARC-Concurrent-To", resource_id),
                        ("WARC-Target-URI", copy.url),
                        ("Content-Type", "application/json"),
                    ],
                    metadata,
                ),
            )
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(".partial")
        partial.write_bytes(data)
        partial.replace(path)
        self._enforce_budget(keep=path)
        return copy.copy_id

    def discard(self, copy: PageCopy) -> None:
        kept = self._kept(copy)
        if kept is not None and self._kept_id(kept) == copy.copy_id:
            kept.unlink(missing_ok=True)

    def _files_oldest_first(self) -> list[Path]:
        return sorted(
            (f for d in self._days() for f in d.glob("*.warc.gz")),
            key=lambda f: (f.parent.name, f.name),
        )

    def _enforce_budget(self, keep: Path) -> None:
        if self._max_bytes is None:
            return
        files = self._files_oldest_first()
        total = sum(f.stat().st_size for f in files)
        for f in files:
            if total <= self._max_bytes:
                break
            if f == keep:
                continue
            size = f.stat().st_size
            f.unlink(missing_ok=True)
            total -= size
            self.evicted += 1
            if not any(f.parent.iterdir()):
                f.parent.rmdir()

    def _days(self) -> list[Path]:
        if not self._root.is_dir():
            return []
        return [d for d in self._root.iterdir() if d.is_dir()]

    def count(self) -> int:
        return sum(len(list(d.glob("*.warc.gz"))) for d in self._days())

    def expire(self, today: date, keep_days: int) -> int:
        cutoff = today - timedelta(days=max(keep_days, 0))
        removed = 0
        for day in self._days():
            try:
                folder_date = date.fromisoformat(day.name)
            except ValueError:
                continue
            if folder_date < cutoff:
                removed += len(list(day.glob("*.warc.gz")))
                shutil.rmtree(day, ignore_errors=True)
        return removed

    def purge(self) -> int:
        removed = self.count()
        if self._root.exists():
            shutil.rmtree(self._root, ignore_errors=True)
        return removed
