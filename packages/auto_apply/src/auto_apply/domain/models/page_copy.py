"""Page copies (item 6): a cleaned copy of a page AA read, kept on this device.

Two values, because the raw page and the kept copy must never be confused:

* PageSnapshot — what the browser showed, in memory only, for the instant
  between reading the page and cleaning it. Never written anywhere.
* PageCopy — the cleaned copy that is kept: the user's own details,
  scripts, form values and hidden fields removed (domain/services/
  page_redaction.py), with a fingerprint that research rows carry so a row
  can be proved to come from this copy without the copy leaving the device.

Why the fingerprint is a COMMITMENT, not a plain hash. A plain sha256 of a
public job page could be recomputed by anyone who fetches the same page:
hash every posting on a board, match the hashes in someone's research rows,
and you have the list of postings they read — the very search the research
record promises not to keep. So the fingerprint is sha256(nonce ‖ page),
with a random 16-byte nonce that lives only inside the kept copy. Whoever
holds the copy can recompute it and prove the link; nobody else can test a
guess against it.

The nonce is derived, not drawn at random: HMAC(this installation's private
research key, page). The same cleaned page therefore always gets the same
fingerprint on this device — so a page read twice is recognised without
looking at disk, which lets the copy be written in the background — while
anyone without the key still cannot compute it from the page.

Pure data, standard library only.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

__all__ = [
    "PageSnapshot",
    "PageCopy",
    "PostingFacts",
    "content_digest",
    "commitment",
    "derive_nonce",
]

#: Domain separation for the nonce: the research key also keys company ids,
#: and a value derived here must never coincide with one minted there.
_NONCE_CONTEXT = b"aa/page-copy-nonce/v1\x00"


def content_digest(content: bytes) -> str:
    """``sha256:<hex>`` of the kept bytes — local only (file naming and the
    WARC payload digest); never written to a research row."""
    return "sha256:" + hashlib.sha256(content).hexdigest()


def commitment(nonce: bytes, content: bytes) -> str:
    """The research-row fingerprint: ``commit-sha256:<hex>`` of nonce ‖ page."""
    return "commit-sha256:" + hashlib.sha256(nonce + content).hexdigest()


def derive_nonce(key: bytes, content: bytes) -> bytes:
    """The 16-byte nonce for a cleaned page: HMAC-SHA256(key, context ‖ page).

    Deterministic per (installation, page), unguessable without the key.
    """
    return hmac.new(key, _NONCE_CONTEXT + content, hashlib.sha256).digest()[:16]


@dataclass(frozen=True)
class PostingFacts:
    """What AA knew about a posting from the listing, besides its page.

    Kept with a page copy (item 7) because a replay needs them to observe
    the posting the way the live run did: the location decides the
    jurisdiction and metro area, and with them which pay-transparency
    detectors apply. They describe the job, not the person. The company is
    deliberately absent: detectors use it only to mint the anonymous
    company code, which needs the contributor's private key and is not
    replayed.

    Attributes:
        job_title: The title as the listing showed it.
        location: The location string as the listing showed it.
        platform: The job board or ATS the listing came from.
    """

    job_title: str = ""
    location: str | None = None
    platform: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {"job_title": self.job_title, "location": self.location, "platform": self.platform}


@dataclass(frozen=True)
class PageSnapshot:
    """A page as read, before cleaning. Lives in memory only.

    Attributes:
        context: Why AA read the page ("job_posting").
        url: The address the page was read from.
        html: The rendered page source as the browser held it.
        captured_at: UTC time the page was read, ISO 8601 to the second
            ("2026-10-02T12:00:00Z"). Fixed here, at capture, so a later
            replay of this page uses the time it was read, not the time it
            is replayed.
    """

    context: str
    url: str
    html: str
    captured_at: str


@dataclass(frozen=True)
class PageCopy:
    """A cleaned page, ready to keep.

    Attributes:
        copy_id: The commitment (see module docstring) — what research rows
            carry.
        nonce: The commitment's nonce, hex (see derive_nonce). Stored only
            in the copy.
        context: Why AA read the page.
        url: Where it was read from. Kept with the copy on this device; it
            never enters a research row.
        captured_at: UTC time the page was read (see PageSnapshot).
        content: The cleaned page, UTF-8.
        redactions: (rule, count) pairs: what cleaning removed, by rule.
        facts: The posting facts from the listing (item 7), or None for a
            copy made without them.
        method: How the page was obtained, stated plainly for anyone who
            later reads the copy ("rendered DOM, read after load").
    """

    copy_id: str
    nonce: str
    context: str
    url: str
    captured_at: str
    content: bytes
    redactions: tuple[tuple[str, int], ...]
    method: str = "rendered DOM (browser page source after load)"
    facts: PostingFacts | None = None

    @property
    def digest(self) -> str:
        """sha256 of the kept bytes (local)."""
        return content_digest(self.content)

    def verifies(self) -> bool:
        """True when copy_id is the commitment of this nonce and content."""
        return self.copy_id == commitment(bytes.fromhex(self.nonce), self.content)
