"""Discovery verification — assert that discovery output is *real*, not hoped-for.

The mission bar is "know, not hope": a run that reports "found 18 jobs" tells you
nothing about whether those are 18 valid, unique, in-cap job records or 18 pieces
of DOM garbage. This module answers that definitively.

It is deliberately separate from ``DiscoveryMathAuditor`` (which *logs* the
extraction process for observability). This verifies the *output* and returns a
structured pass/fail report:

  * valid fields   — every job has a non-empty title, a non-empty company, and a
                     well-formed absolute http(s) URL. (pydantic requires the
                     fields to exist but accepts empty strings, so this is a real
                     gap it does not cover.)
  * no duplicates  — no two jobs share a dedup key (URL, or title|company for the
                     rare URL-less job), i.e. the pipeline's dedup actually held.
  * within cap     — the job count does not exceed the resolved ceiling, i.e. the
                     per-query result caps were respected end-to-end.

The verifier is pure and side-effect-free so it is trivially unit-testable and
usable anywhere: the discovery pipeline calls it at runtime to log a per-run
report; tests call ``report.assert_valid()`` to fail loudly on bad output.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from auto_apply.domain.models.job import Job


class DiscoveryVerificationError(AssertionError):
    """Raised by ``VerificationReport.assert_valid`` when a check fails."""


def _is_valid_url(url: object) -> bool:
    """True for a non-empty absolute http(s) URL with a network location."""
    if not isinstance(url, str) or not url.strip():
        return False
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


_SEARCH_ENGINE_HOSTS = ("google.", "bing.", "duckduckgo.", "search.yahoo.")


def _is_navigation_chrome(job: Job) -> str:
    """Return why this record looks like site furniture, or "" if it does not.

    Two rules, both learned from live runs rather than guessed:

    * ``title == company`` — a real posting names a role and an employer, and
      they are not the same string. Every one of Indeed's ``Find jobs`` /
      ``Company Reviews`` and Bing's ``Rewards`` records has this shape.
    * a job URL hosted on a search engine — a posting is never served from
      google.com or bing.com. Indeed is deliberately absent from that list:
      real Indeed postings *do* live on indeed.com.
    """
    title = (job.title or "").strip()
    company = (job.company or "").strip()
    if title and company and title.casefold() == company.casefold():
        return f"title equals company ({title!r})"
    try:
        host = urlparse((job.url or "").strip()).netloc.lower()
    except ValueError:
        return ""
    if any(part in host for part in _SEARCH_ENGINE_HOSTS):
        return f"job URL is hosted on a search engine ({host})"
    return ""


def _dedup_key(job: Job) -> str:
    """The same identity a deduplicated feed collapses on: URL when present,
    else a title|company fallback for URL-less records."""
    url = (job.url or "").strip().lower()
    if url:
        return url
    return f"{(job.title or '').strip().lower()}|{(job.company or '').strip().lower()}"


@dataclass(frozen=True)
class CheckResult:
    """One named check: whether it passed and a human-readable detail line."""

    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class VerificationReport:
    """The structured outcome of verifying one discovery output list."""

    total_jobs: int
    checks: tuple[CheckResult, ...]

    @property
    def passed(self) -> bool:
        """True only when every check passed."""
        return all(c.passed for c in self.checks)

    def summary(self) -> str:
        """A single compact line suitable for a log record."""
        marks = " | ".join(
            f"{c.name} {'OK' if c.passed else 'FAIL'}" for c in self.checks
        )
        verdict = "PASS" if self.passed else "FAIL"
        return f"discovery verification [{verdict}]: {self.total_jobs} jobs | {marks}"

    def details(self) -> str:
        """Multi-line detail for the failing (or all) checks."""
        return "\n".join(f"  - {c.name}: {c.detail}" for c in self.checks)

    def assert_valid(self) -> None:
        """Raise DiscoveryVerificationError with details if any check failed.

        For tests and strict callers; the runtime pipeline logs the report
        instead of raising, so bad output is loud but never crashes a run.
        """
        if not self.passed:
            raise DiscoveryVerificationError(self.summary() + "\n" + self.details())


class DiscoveryVerifier:
    """Verifies a discovery output list against the three invariants.

    Args:
        max_results: the resolved ceiling the list must not exceed. When None,
            the cap check is skipped (e.g. when verifying an unbounded fixture).
        sample_size: how many offending items to name in a failure detail.
    """

    def __init__(self, max_results: int | None = None, sample_size: int = 5) -> None:
        self._cap = max_results
        self._sample = max(1, sample_size)

    def verify(self, jobs: list[Job]) -> VerificationReport:
        checks = [
            self._check_fields(jobs),
            self._check_chrome(jobs),
            self._check_dedup(jobs),
        ]
        if self._cap is not None:
            checks.append(self._check_within_cap(jobs))
        return VerificationReport(total_jobs=len(jobs), checks=tuple(checks))

    def _check_fields(self, jobs: list[Job]) -> CheckResult:
        invalid = [
            j
            for j in jobs
            if not (j.title and j.title.strip())
            or not (j.company and j.company.strip())
            or not _is_valid_url(j.url)
        ]
        if not invalid:
            return CheckResult("fields", True, f"all {len(jobs)} jobs have valid fields")
        sample = ", ".join(
            f"[title={j.title!r} company={j.company!r} url={j.url!r}]"
            for j in invalid[: self._sample]
        )
        return CheckResult(
            "fields",
            False,
            f"{len(invalid)} of {len(jobs)} jobs missing title/company or with a "
            f"non-http(s) URL; e.g. {sample}",
        )

    def _check_chrome(self, jobs: list[Job]) -> CheckResult:
        """Fail when the feed contains a site's own navigation rather than jobs.

        This check reports; it does not filter. Dropping chrome belongs where
        the record is created, not in the auditor — but a run that enqueues a
        tab bar should say so instead of reporting ``[PASS]``, which is what
        happened for four live runs.
        """
        offenders = [(j, why) for j in jobs if (why := _is_navigation_chrome(j))]
        if not offenders:
            return CheckResult(
                "chrome", True, f"none of {len(jobs)} jobs look like navigation"
            )
        sample = ", ".join(
            f"[title={j.title!r} company={j.company!r}: {why}]"
            for j, why in offenders[: self._sample]
        )
        return CheckResult(
            "chrome",
            False,
            f"{len(offenders)} of {len(jobs)} records look like site navigation "
            f"rather than job postings; e.g. {sample}",
        )

    def _check_dedup(self, jobs: list[Job]) -> CheckResult:
        seen: set[str] = set()
        dupes: list[str] = []
        for job in jobs:
            key = _dedup_key(job)
            if key in seen:
                dupes.append(key)
            else:
                seen.add(key)
        if not dupes:
            return CheckResult("dedup", True, f"no duplicates across {len(jobs)} jobs")
        sample = ", ".join(dupes[: self._sample])
        return CheckResult(
            "dedup",
            False,
            f"{len(dupes)} duplicate job(s) slipped through dedup; e.g. {sample}",
        )

    def _check_within_cap(self, jobs: list[Job]) -> CheckResult:
        assert self._cap is not None
        if len(jobs) <= self._cap:
            return CheckResult(
                "cap", True, f"{len(jobs)} jobs within ceiling of {self._cap}"
            )
        return CheckResult(
            "cap",
            False,
            f"{len(jobs)} jobs exceeds the resolved ceiling of {self._cap} — a "
            f"per-query result cap was not respected",
        )
