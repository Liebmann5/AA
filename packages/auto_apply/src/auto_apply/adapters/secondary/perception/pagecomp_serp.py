"""Search-results pages read by pagecomp (slice S6, step 1).

``PagecompSerpAdapter`` implements :class:`PageUnderstandingPort`. It answers
``analyze_serp`` with pagecomp's job-list gate and hands ``analyze_form`` and
``analyze_job_listing`` to the adapter it wraps (the math adapter), so only
search pages change in this step.

One read of the live page goes through :class:`PagecompAccess` (Chrome
DevTools pierced DOM on Chromium, a bounded in-page walk elsewhere); if that
read comes back empty or timed out, the page's serialized HTML is read
instead. pagecomp then answers one of three ways:

* **a job list**: its records become ``JobCardInfo`` cards. Records the gate
  itself scored as not job-like (an ad or a "recommended searches" row inside
  the list) are left out and counted in the log;
* **no job list** (``Abstain("no-job-list")``, or no repeated records at
  all): an empty structure carrying
  ``page_verdict = NOT_A_JOB_LIST``. ``FallbackSerpExtractor`` honours it and
  does *not* hand the page to the DOM miner, whose output on such pages was
  searches, salary pages and advice (live run 2026-11-07);
* **anything else** (a timeout, a tool error, an exception): the wrapped
  adapter answers instead, and the log says so. pagecomp never makes a page
  worse than the reader it replaces.

Switch: ``serp_reader`` in ``runtime_defaults.yaml`` (``pagecomp`` or
``legacy``). Read caps: the ``comprehension_access`` block.

Company and location come from the record's other visible lines by a small
shape test (``_card_fields``). That is a stopgap: pagecomp has no field-role
tool yet, so the proper reading (columns across records) is on the problem
list.
"""

from __future__ import annotations

import logging
import re
import time
import urllib.parse
from collections.abc import Iterable, Mapping
from typing import Any

from auto_apply.domain.ports.page_understanding_port import (
    FormStructure,
    JobCardInfo,
    JobListingStructure,
    JobUrlCandidate,
    PageContext,
    SerpResolutionReport,
    SERPStructure,
)
from pagecomp import Abstain, Analyzer, Ok
from pagecomp import links as L
from pagecomp.access import ObservationRequest
from pagecomp.doc import ELEMENT
from pagecomp.observation import PageObservation, observe_html
from pagecomp.tools import default_registry

logger = logging.getLogger(__name__)

#: ``SERPStructure.page_verdict`` when the reader judged the page to hold no
#: list of job postings. Consumers must not re-read such a page another way.
NOT_A_JOB_LIST = "not-a-job-list"

#: Abstain reasons that are a judgment of the page's content (no repeated
#: records at all, or none of them a job list), as opposed to a failure of
#: the reader (``tool-error``, ``tool-contract``, a timeout). A dependency's
#: reason is chained as ``needs listing: needs records: no-repeat``.
_CONTENT_REASONS = frozenset({"no-job-list", "no-repeat"})

#: Query keys that carry the search words (job boards and search engines).
_QUERY_KEYS = ("q", "query", "keywords", "keyword", "text", "k", "p", "search", "term")

_HEADINGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
# A place: "City, ST", a postcode, a country line on its own, or a work mode.
_PLACE = re.compile(r",\s*[A-Z]{2}\b|\b\d{5}\b|^(usa|us|united states( of america)?|uk|canada)$")
_MODE = re.compile(r"\b(remote|hybrid|on-?site|in-?office)\b", re.I)
_DATE = re.compile(
    r"\b(ago|today|yesterday|just now|posted|updated|new|active)\b|\d{1,2}/\d{1,2}/\d{2,4}", re.I)
_PAY = re.compile(r"[$€£₹]|\b\d+(\.\d+)?\s*[kK]\b|\b(per hour|an hour|a year|annually|/hr|/yr|salary)\b", re.I)
_BADGE = re.compile(
    r"^(new|easily apply|easy apply|urgently hiring|hiring multiple candidates|promoted|sponsored|"
    r"featured|spotlight job|read more|apply now|view job|save|saved|full[- ]time|part[- ]time|"
    r"contract|temporary|internship|permanent( contract)?|\W+)$", re.I)


def query_from_url(url: str) -> str | None:
    """The search words a results URL carries, or None."""
    try:
        pairs = urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query)
    except ValueError:
        return None
    found = {k.lower(): v for k, v in pairs}
    for key in _QUERY_KEYS:
        value = (found.get(key) or "").strip()
        if value:
            return value
    return None


def _card_fields(lines: Iterable[str], title: str) -> tuple[str, str]:
    """(company, location) from a record's other visible lines, by shape.

    Stopgap until pagecomp reads field roles: a place ("City, ST", a
    postcode) is preferred to a work mode ("Hybrid") for the location; the
    first other line that is not the title, a date, pay, a badge, a URL or a
    long description is the company."""
    place = mode = company = ""
    t = title.casefold()
    for raw in lines:
        line = " ".join(raw.split())
        low = line.casefold()
        if not line or low == t or (len(low) > 3 and (low in t or t in low)):
            continue
        if "://" in line or "\u203a" in line or line.endswith(":") or len(line) > 60:
            continue
        if _PAY.search(line):
            continue
        if _PLACE.search(line):
            place = place or line
            continue
        if _MODE.search(line) and len(line) <= 30:
            mode = mode or line
            continue
        if company or _DATE.search(line) or _BADGE.match(line):
            continue
        company = line
    return company, place or mode


class PagecompSerpAdapter:
    """``PageUnderstandingPort`` whose ``analyze_serp`` is pagecomp's."""

    def __init__(
        self,
        legacy: Any,
        browser: Any,
        *,
        access: Mapping[str, Any] | None = None,
        posting_hosts: Iterable[str] = (),
        access_factory: Any = None,
    ) -> None:
        """
        Args:
            legacy: The adapter this one wraps; answers forms, listings, and
                any search page pagecomp could not read.
            browser: The live browser (AA's driver wrapper or a raw driver).
            access: The ``comprehension_access`` YAML block.
            posting_hosts: Hosts of known application systems (the ATS
                registry), evidence that a link leads to a posting.
            access_factory: Builds the access adapter from a raw driver
                (tests inject a fake; default ``PagecompAccess``).
        """
        self._legacy = legacy
        self._browser = browser
        self._access_cfg = dict(access or {})
        self._prefer_cdp = bool(self._access_cfg.pop("prefer_cdp", True))
        self._factory = access_factory
        hosts = ",".join(sorted({h.strip().lower() for h in posting_hosts if h and h.strip()}))
        registry = default_registry()
        self._params = registry.default_params().with_overrides(
            registry.specs(), {"joblist": {"posting_hosts": hosts}},
            reason="AA: posting hosts from the ATS registry")
        self.last_page_verdict = ""

    # -- the wrapped adapter answers everything but search pages ---------
    def analyze_form(self, context: PageContext) -> FormStructure:
        return self._legacy.analyze_form(context)

    def analyze_job_listing(self, context: PageContext) -> JobListingStructure:
        return self._legacy.analyze_job_listing(context)

    # -- reading the page --------------------------------------------------
    def _request(self, context: PageContext, query: str | None) -> ObservationRequest:
        allowed = {"level", "max_nodes", "max_bytes", "max_depth", "max_frame_depth",
                   "frame_cap", "script_deadline_ms", "wall_ms"}
        kw = {k: v for k, v in self._access_cfg.items() if k in allowed}
        return ObservationRequest(requested_url=context.url or None, query=query, **kw)

    def _raw_driver(self) -> Any:
        getter = getattr(self._browser, "get_raw_driver", None)
        if callable(getter):
            try:
                return getter()
            except Exception:  # noqa: BLE001 - a wrapper without one is fine
                pass
        return self._browser

    def _observe(self, context: PageContext, query: str | None) -> tuple[PageObservation | None, str]:
        request = self._request(context, query)
        how = "access"
        try:
            factory = self._factory
            if factory is None:
                from auto_apply.adapters.secondary.perception.pagecomp_access import (  # noqa: PLC0415
                    PagecompAccess,
                )
                factory = PagecompAccess
            outcome = factory(self._raw_driver(), prefer_cdp=self._prefer_cdp).observe(request)
            obs = outcome.observation
            if not outcome.timed_out and len(obs.doc) > 2:
                return obs, how + ("" if not outcome.notes else ":" + ",".join(outcome.notes[:3]))
            how = "html (access read was empty or timed out)"
        except Exception as exc:  # noqa: BLE001
            how = f"html (access failed: {type(exc).__name__})"
        try:
            html = self._browser.execute_script(
                "return document.documentElement ? document.documentElement.outerHTML : '';")
        except Exception as exc:  # noqa: BLE001
            logger.debug("pagecomp_serp: page HTML unavailable: %s", exc)
            return None, how
        if not isinstance(html, str) or not html:
            return None, how
        url = context.url
        try:
            url = self._browser.current_url or url
        except Exception:  # noqa: BLE001
            pass
        return observe_html(html, url=url, title=context.page_title, requested_url=context.url or None,
                            query=query, limits=request.limits()), how

    def analyze_serp(self, context: PageContext) -> SERPStructure:
        """Read the page's job list with pagecomp. Never raises."""
        self.last_page_verdict = ""
        started = time.monotonic()
        query = query_from_url(context.url)
        try:
            obs, how = self._observe(context, query)
            if obs is None:
                logger.warning("pagecomp: could not read the page (%s); the previous reader answers.", how)
                return self._legacy.analyze_serp(context)
            result = Analyzer(obs, params=self._params).get("joblist").result
        except Exception as exc:  # noqa: BLE001
            logger.warning("pagecomp: reading the results page failed (%s); the previous reader answers.",
                           exc, exc_info=True)
            return self._legacy.analyze_serp(context)
        ms = (time.monotonic() - started) * 1000.0
        if isinstance(result, Abstain) and result.reason.rsplit(": ", 1)[-1] in _CONTENT_REASONS:
            self.last_page_verdict = NOT_A_JOB_LIST
            runs = "; ".join(e.detail for e in result.evidence[:4]) or result.reason
            logger.info("pagecomp: no list of job postings on this page (%s) [%s, %.0f ms]", runs, how, ms)
            return SERPStructure(
                resolution_report=SerpResolutionReport(chosen_level="pagecomp", note="no-job-list"),
                analyze_ms=ms, page_verdict=NOT_A_JOB_LIST)
        if not isinstance(result, Ok):
            logger.warning("pagecomp: no answer (%s); the previous reader answers.",
                           getattr(result, "reason", type(result).__name__))
            return self._legacy.analyze_serp(context)
        cards, skipped = self._cards(obs, result.value)
        logger.info("pagecomp: job list of %d record(s), %d kept, %d not job-like [%s, %.0f ms]",
                    len(result.value.records), len(cards), skipped, how, ms)
        return SERPStructure(
            job_cards=tuple(cards),
            resolution_report=SerpResolutionReport(
                chosen_level="pagecomp", detected_parent_count=len(result.value.records),
                note=f"run {result.value.run_index}, share {result.value.share:.2f}"),
            analyze_ms=ms)

    def _cards(self, obs: PageObservation, joblist: Any) -> tuple[list[JobCardInfo], int]:
        doc = obs.doc
        records = joblist.records
        per = list(joblist.per_record)
        cards: list[JobCardInfo] = []
        skipped = 0
        for index, rec in enumerate(records):
            # per_record covers the chosen run; merged runs passed the gate whole.
            if index < len(per) and not per[index].job_like:
                skipped += 1
                continue
            title = " ".join((rec.title or "").split())
            if not title:
                skipped += 1
                continue
            link = rec.link
            state = rec.state
            url = link.url if (link is not None and state == L.RESOLVED) else ""
            candidates: tuple[JobUrlCandidate, ...] = ()
            if link is not None:
                candidates = (JobUrlCandidate(
                    url=link.url, original_url=link.original, anchor_text=link.text, source="static",
                    score=float(link.score), title_overlap=float(link.title_overlap),
                    method=f"pagecomp:{link.kind}:{link.method}", apply_intent=bool(link.apply_intent),
                    pending_redirect=link.kind == L.OPAQUE, canonical_url=link.canonical),)
            node = rec.title_node
            heading = node >= 0 and doc.kind[node] == ELEMENT and (
                doc.tag_name(node) in _HEADINGS or doc.attr(node, "role") == "heading")
            company, location = _card_fields(rec.lines, title)
            cards.append(JobCardInfo(
                title=title, company=company, location=location, url=url,
                confidence=1.0, card_index=index, candidates=candidates,
                resolution_state=state, title_source="heading" if heading else "anchor_name"))
        return cards, skipped
