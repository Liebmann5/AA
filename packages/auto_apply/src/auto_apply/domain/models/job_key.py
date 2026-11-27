"""The job key: one identity per posting, independent of the URL's shape.

Phase 0 (P0-2). Two URLs can name the same posting — a search engine's
redirect wrapper, a tracked link, a copied link with fresh campaign
parameters. Dedup on the raw URL misses them; dedup on a wrong key blocks a
job AA never touched. The key is therefore derived, never stored from the
card:

    (registrable host, posting id)

* host — the full hostname of the unwrapped, canonical final URL,
  lowercased, with only a leading ``www.`` removed. Never the registrable
  domain: requisition ids and careers paths are per-employer, and the tenant
  lives in the subdomain — keying on the registrable domain joins different
  employers' postings. A host alias (two hostnames for one board) becomes a
  miss, which is the safe direction. Vetting records the final URL as
  ``metadata["landed_url"]`` / ``metadata["resolved_url"]``; the card URL
  (``job.url``) is the fallback.
* posting id — the posting's own JSON-LD ``JobPosting.identifier`` when
  vetting recorded one (``metadata["structured_posting"]["identifier"]``),
  else the canonical path *plus query*. The query is kept deliberately:
  postings that differ only in the query (``?jk=...``) are different jobs.
  A tracking-only difference producing two keys is a miss, never a false
  block — and the identifier, when present, is what joins the shapes.

Pure: no I/O, no clock, no registry, no per-site code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from pagecomp.links import canonical_url, unwrap

__all__ = ["JobKey", "compute_job_key"]


@dataclass(frozen=True)
class JobKey:
    """A posting's dedup identity.

    ``source_url`` is provenance, not identity: two keys are equal exactly
    when ``(host, posting_id)`` is equal, and hashing follows equality.
    """

    host: str
    posting_id: str
    source_url: str = field(compare=False)

    @property
    def as_string(self) -> str:
        return f"{self.host}|{self.posting_id}"


def compute_job_key(job: Any) -> JobKey:
    """Derive the key from a Job. Never raises: an unreadable URL degrades to
    an empty host plus the raw path, which is still stable."""
    metadata = getattr(job, "metadata", None)
    if not isinstance(metadata, dict):
        metadata = {}
    raw_url = (
        metadata.get("landed_url")
        or metadata.get("resolved_url")
        or getattr(job, "url", "")
        or ""
    )
    raw_url = raw_url if isinstance(raw_url, str) else ""
    resolved, _how = unwrap(raw_url)
    canonical = canonical_url(resolved)
    # urlsplit raises on malformed URLs (an unterminated IPv6 literal), and
    # .hostname on a bad port. The key must never raise: degrade to an empty
    # host and the raw string as the path component — a stable, weak identity.
    try:
        parts = urlsplit(canonical)
        # Full hostname, not the registrable domain: the tenant lives in the
        # subdomain, and requisition ids are per-employer.
        host = (parts.hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        path = parts.path
        query = parts.query
    except ValueError:
        host = ""
        path = ""
        query = ""

    posting_id = ""
    structured = metadata.get("structured_posting")
    if isinstance(structured, dict):
        identifier = structured.get("identifier")
        if isinstance(identifier, str) and identifier.strip():
            posting_id = identifier.strip()
    if not posting_id:
        posting_id = path or "/"
        if query:
            posting_id = f"{posting_id}?{query}"
    return JobKey(host=host, posting_id=posting_id, source_url=canonical)
