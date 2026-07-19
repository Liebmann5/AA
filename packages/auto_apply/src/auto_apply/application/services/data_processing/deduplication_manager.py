"""In-session URL deduplication to prevent redundant job processing.

This module provides DeduplicationManager, which tracks every job URL seen
during a session and detects duplicates even when the same job appears with
different query parameters (tracking tags, referral codes, etc.).

Two-Stage Detection:
    Stage 1 — Exact match: The URL is normalized (tracking params stripped,
        scheme/host lowercased, path standardized) and compared against a
        set of previously seen normalized URLs. O(1) average.

    Stage 2 — Signature match: A job-specific identifier is extracted from
        the URL using ATS-platform-aware patterns (LinkedIn job ID, Indeed
        jk param, Greenhouse job number, Workday JR code, etc.) and hashed.
        This catches the same job appearing via different URL shapes, such as
        a direct apply link vs. a SERP result link pointing to the same role.

Scope:
    DeduplicationManager is an in-session, in-memory cache. It does NOT
    persist across sessions. Cross-session deduplication (never apply to
    the same job twice) is handled by JobRepository, which writes to
    the persistent database. The orchestrator checks both before dispatching
    an APPLY task.

Thread Safety:
    All public methods are protected by a threading.Lock. Although the
    orchestrator calls dedup from a single main thread, guard conditions
    and research collectors may query is_duplicate() from other contexts.

Example:
    >>> manager = DeduplicationManager()
    >>>
    >>> # Atomic check-and-mark (preferred — no TOCTOU gap)
    >>> if manager.check_and_mark("https://linkedin.com/jobs/view/123?utm_source=email"):
    ...     process(job)  # Not a duplicate; now marked seen
    >>>
    >>> # Or explicit two-step (only if you need the check result separately)
    >>> if not manager.is_duplicate(url):
    ...     manager.mark_seen(url)
"""

# Layer: application
# Depends on: domain

import hashlib
import logging
import re
import threading
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urlparse

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Tracking parameters stripped during URL normalization.
# These parameters encode referral/campaign data but don't identify the job.
# ─────────────────────────────────────────────────────────────────────────────
_TRACKING_PARAMS: frozenset = frozenset({
    # UTM campaign tags
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_placement",
    # Referral tags
    "ref", "referer", "referrer", "source", "campaign", "origin",
    # Ad click IDs
    "fbclid", "gclid", "msclkid", "dclid", "twclid", "li_fat_id",
    # LinkedIn-specific
    "refid", "trackingid", "trk",
    # Indeed-specific
    "aceid", "from", "alid",
    # Generic
    "sid", "cid", "pid", "aid",
})

# ─────────────────────────────────────────────────────────────────────────────
# ATS job identifier extraction patterns.
# Ordered from most specific (exact platform patterns) to most general.
# The first match wins. Each pattern must capture group(1) as the job ID.
# ─────────────────────────────────────────────────────────────────────────────
_JOB_ID_PATTERNS: tuple = (
    # LinkedIn: /jobs/view/1234567890
    (r"/jobs/view/(\d{7,})", "linkedin_view"),
    # LinkedIn: /jobs/1234567890 (direct)
    (r"/jobs/(\d{7,})(?:/|$|\?)", "linkedin_direct"),
    # Indeed: jk=abc1234567890abc
    (r"[?&]jk=([a-zA-Z0-9]{14,})", "indeed_jk"),
    # Greenhouse: /jobs/1234567 or /gh/jobs/1234567
    (r"/(?:gh/)?jobs/(\d{5,})", "greenhouse"),
    # Lever: /company-name/UUID
    (r"/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", "lever_uuid"),
    # Workday: /job/Job-Title/JR123456 or /job/JR123456
    (r"/job/(?:[^/]+/)?(JR\d{4,})", "workday_jr"),
    # Workday numeric: /job/Job-Title/123456_JR or similar
    (r"/job/[^/]+/(\d{5,})", "workday_numeric"),
    # iCIMS: /jobs/12345/job
    (r"/jobs/(\d{4,})/job", "icims"),
    # SmartRecruiters: /jobs/view/UUID
    (r"/jobs/view/([A-Z0-9]{16,})", "smartrecruiters"),
    # BambooHR: /jobs/view.php?id=123
    (r"[?&]id=(\d{3,})", "bamboohr_id"),
    # Generic: jobId=xxx or job_id=xxx
    (r"[?&]job_?id=([a-zA-Z0-9_-]{3,})", "generic_jobid"),
    # Generic: requisitionId=xxx
    (r"[?&]requisition_?id=([a-zA-Z0-9_-]{3,})", "generic_req"),
    # Generic UUID in path (Lever, etc.)
    (r"/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", "generic_uuid"),  # noqa: E501
    # Long alphanumeric path segment — catch-all for unknown ATSes
    (r"/([a-zA-Z0-9_-]{20,})(?:/apply|$|\?)", "generic_long_id"),
)


@dataclass
class DeduplicationStats:
    """Performance metrics for the deduplication cache.

    Attributes:
        total_checks: Total is_duplicate() calls (including check_and_mark).
        exact_duplicates: Duplicates caught by normalized URL exact match.
        signature_duplicates: Duplicates caught by job ID signature match.
        unique_urls: URLs added via mark_seen() / check_and_mark().
    """
    total_checks:        int = 0
    exact_duplicates:    int = 0
    signature_duplicates: int = 0
    unique_urls:         int = 0

    @property
    def duplicate_rate(self) -> float:
        """Fraction of checks that were duplicates. 0.0 if no checks yet.

        Returns:
            Float between 0.0 and 1.0.
        """
        if self.total_checks == 0:
            return 0.0
        total_dupes = self.exact_duplicates + self.signature_duplicates
        return total_dupes / self.total_checks

    def to_dict(self) -> dict:
        """Serializes stats to a plain dict for logging and reporting.

        Returns:
            JSON-serializable dict of all stat fields.
        """
        return {
            "total_checks":          self.total_checks,
            "exact_duplicates":      self.exact_duplicates,
            "signature_duplicates":  self.signature_duplicates,
            "unique_urls":           self.unique_urls,
            "duplicate_rate":        round(self.duplicate_rate, 4),
        }


class DeduplicationManager:
    """In-session, in-memory cache for job URL deduplication.

    Detects duplicate job URLs using two complementary strategies: exact
    normalized URL matching and platform-aware job ID signature matching.
    Thread-safe for concurrent reads and writes.

    Example:
        >>> mgr = DeduplicationManager()
        >>> mgr.check_and_mark("https://linkedin.com/jobs/view/9999?utm_source=email")
        True   # First time seen — not a duplicate, now marked
        >>> mgr.check_and_mark("https://linkedin.com/jobs/view/9999?ref=twitter")
        False  # Same job ID — duplicate detected
    """

    def __init__(self) -> None:
        """Initializes an empty deduplication cache."""
        # Normalized URL exact-match set.
        self._seen_urls: set[str] = set()
        # Job ID signature hash set for fuzzy matching.
        self._signatures: set[int] = set()
        # Performance metrics.
        self._stats = DeduplicationStats()
        # Lock for thread-safe access to all mutable state.
        self._lock = threading.Lock()

        logger.info("DeduplicationManager initialized")

    # =========================================================================
    # PRIMARY INTERFACE
    # =========================================================================

    def check_and_mark(self, url: str) -> bool:
        """Atomically checks if a URL is new and marks it seen if so.

        This is the preferred method for the orchestrator. It performs
        the check and mark as a single locked operation, eliminating any
        TOCTOU (time-of-check/time-of-use) gap between is_duplicate()
        and mark_seen().

        Args:
            url: The job URL to check.

        Returns:
            True if the URL is NOT a duplicate (i.e., it's new and was
            just marked as seen).
            False if the URL IS a duplicate (not marked again).

        Example:
            >>> if manager.check_and_mark(job.url):
            ...     queue_for_processing(job)
        """
        with self._lock:
            self._stats.total_checks += 1

            normalized = self._normalize_url(url)

            # Stage 1: exact match.
            if normalized in self._seen_urls:
                self._stats.exact_duplicates += 1
                logger.debug("Dedup exact match | url=%s", url)
                return False

            # Stage 2: signature match.
            sig = self._compute_signature(normalized)
            if sig is not None and sig in self._signatures:
                self._stats.signature_duplicates += 1
                logger.debug("Dedup signature match | url=%s", url)
                return False

            # Not a duplicate — mark it now inside the same lock.
            self._seen_urls.add(normalized)
            if sig is not None:
                self._signatures.add(sig)
            self._stats.unique_urls += 1

            return True

    def is_duplicate(self, url: str) -> bool:
        """Returns True if this URL has already been seen this session.

        Prefer check_and_mark() when you intend to also mark the URL.
        Use is_duplicate() only when you need to check without marking,
        for example in a pre-flight read-only gate.

        Args:
            url: The job URL to check.

        Returns:
            True if this URL or its job signature was previously seen.

        Example:
            >>> manager.is_duplicate("https://greenhouse.io/jobs/12345")
            False
        """
        with self._lock:
            self._stats.total_checks += 1

            normalized = self._normalize_url(url)

            if normalized in self._seen_urls:
                self._stats.exact_duplicates += 1
                return True

            sig = self._compute_signature(normalized)
            if sig is not None and sig in self._signatures:
                self._stats.signature_duplicates += 1
                return True

            return False

    def mark_seen(self, url: str) -> None:
        """Marks a URL as seen to prevent future duplicates.

        Call this after is_duplicate() returns False and you've decided to
        process the URL. If you're doing check + mark together, prefer the
        atomic check_and_mark() instead.

        Args:
            url: The job URL to register as seen.

        Example:
            >>> if not manager.is_duplicate(url):
            ...     manager.mark_seen(url)
            ...     process(job)
        """
        with self._lock:
            normalized = self._normalize_url(url)
            sig = self._compute_signature(normalized)

            self._seen_urls.add(normalized)
            if sig is not None:
                self._signatures.add(sig)
            self._stats.unique_urls += 1

            logger.debug("Marked seen | url=%s", url)

    # =========================================================================
    # DIAGNOSTICS
    # =========================================================================

    def get_stats(self) -> DeduplicationStats:
        """Returns a snapshot of deduplication performance metrics.

        Returns:
            A copy of the current DeduplicationStats.

        Example:
            >>> stats = manager.get_stats()
            >>> print(f"Duplicate rate: {stats.duplicate_rate:.1%}")
        """
        with self._lock:
            import copy  # noqa: PLC0415
            return copy.copy(self._stats)

    def clear(self) -> None:
        """Resets all deduplication state.

        Clears both the URL set and the signature set. Use only for testing
        or when intentionally starting a fresh in-session context.
        """
        with self._lock:
            self._seen_urls.clear()
            self._signatures.clear()
            self._stats = DeduplicationStats()
        logger.info("DeduplicationManager cleared")

    def __len__(self) -> int:
        """Returns the number of unique URLs tracked in this session.

        Returns:
            Count of unique seen URLs.
        """
        with self._lock:
            return len(self._seen_urls)

    def __repr__(self) -> str:
        with self._lock:
            return (
                f"DeduplicationManager("
                f"seen={len(self._seen_urls)}, "
                f"signatures={len(self._signatures)}, "
                f"checks={self._stats.total_checks})"
            )

    # =========================================================================
    # URL NORMALIZATION
    # =========================================================================

    def _normalize_url(self, url: str) -> str:
        """Strips tracking parameters and standardizes URL format.

        Removes all parameters in _TRACKING_PARAMS, lowercases scheme
        and host, sorts remaining query params for consistent ordering,
        and strips trailing slashes from the path.

        Args:
            url: The raw URL to normalize.

        Returns:
            A normalized URL string, or the lowercased original if parsing fails.

        Example:
            >>> mgr._normalize_url("https://Site.com/Job/123?utm_source=email&id=456")
            'https://site.com/job/123?id=456'
        """
        try:
            parsed = urlparse(url.strip())

            # Scheme and host are case-insensitive; normalize to lowercase.
            scheme = parsed.scheme.lower()
            host   = parsed.netloc.lower()

            # Strip trailing slashes from path for consistency.
            path = parsed.path.rstrip("/") or "/"

            # Filter out tracking params; sort remaining for stable ordering.
            raw_params = parse_qs(parsed.query, keep_blank_values=False)
            kept_params = {
                k: v for k, v in raw_params.items()
                if k.lower() not in _TRACKING_PARAMS
            }
            # Sort keys so ?b=2&a=1 and ?a=1&b=2 produce identical strings.
            clean_query = urlencode(
                sorted(kept_params.items()), doseq=True
            )

            normalized = f"{scheme}://{host}{path}"
            if clean_query:
                normalized += f"?{clean_query}"

            return normalized

        except Exception as exc:
            logger.warning(
                "URL normalization failed | url=%s error=%s", url, exc
            )
            return url.lower()

    # =========================================================================
    # SIGNATURE EXTRACTION
    # =========================================================================

    def _compute_signature(self, normalized_url: str) -> int | None:
        """Extracts a platform-aware job identifier hash from a URL.

        Tries each pattern in _JOB_ID_PATTERNS in order. On the first
        match, hashes the captured job ID into a stable integer signature.
        Falls back to hashing the full path+query if no pattern matches.

        Using a hash rather than the raw string prevents the signature set
        from growing unboundedly with long UUIDs and alphanumeric IDs.

        Args:
            normalized_url: The already-normalized URL to extract from.

        Returns:
            An integer signature, or None if the URL is malformed.

        Example:
            >>> mgr._compute_signature("https://greenhouse.io/jobs/987654")
            # Returns consistent hash of "987654" every time
        """
        try:
            for pattern, _platform_label in _JOB_ID_PATTERNS:
                match = re.search(pattern, normalized_url, re.IGNORECASE)
                if match:
                    job_id = match.group(1).lower()
                    return self._hash_string(job_id)

            # No pattern matched — fall back to hashing path+query.
            parsed = urlparse(normalized_url)
            fallback = f"{parsed.netloc}{parsed.path}{parsed.query}"
            return self._hash_string(fallback)

        except Exception as exc:
            logger.warning(
                "Signature computation failed | url=%s error=%s",
                normalized_url,
                exc,
            )
            return None

    @staticmethod
    def _hash_string(value: str) -> int:
        """Computes a stable 32-bit integer hash of a string.

        Uses the first 8 hex characters of the MD5 digest. MD5 is chosen
        for speed, not cryptographic security — collision resistance at
        this scale (tens of thousands of URLs per session) is negligible.

        Args:
            value: The string to hash.

        Returns:
            A positive integer in the range [0, 2^32).
        """
        return int(hashlib.md5(value.encode("utf-8")).hexdigest()[:8], 16)