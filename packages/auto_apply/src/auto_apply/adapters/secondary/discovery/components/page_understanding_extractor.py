"""Single-script SERP extraction, with the DOM-walking miner kept as fallback.

``SemanticMiner`` reaches the page one WebDriver round trip at a time. On a
live Google SERP that was measured at ~150 round trips/second with a ~6 ms
median, 93% of the harvest's wall time spent on the wire, and 24% of responses
being "no such element" — the extractors exhausting every candidate selector
against every element and missing.

``MathDOMAdapter._EXTRACTION_SCRIPT`` already walks the entire DOM in one
``execute_script``. It has been built, and injected into ``GoogleProvider``,
and never read. This module is the read.

The fallback is not defensive decoration. ``analyze_serp`` has never produced a
job card on a live SERP — its input stage (``extract_full_dom_tree``) is
production-wired for ``DISCOVER_COMPANY`` and well covered, but its card
*detection* stage is a different implementation from the wired one and carries
two unit pins over a stubbed tree. So the fast path is tried, and the miner
that has worked for years catches it if it comes up empty.
"""

from __future__ import annotations

import logging
import time
import urllib.parse
from dataclasses import replace
from typing import Any

from auto_apply.domain.models.job import Job
from auto_apply.domain.ports.page_understanding_port import (
    CardResolutionState,
    JobCardInfo,
    PageContext,
    SerpResolutionReport,
)
from auto_apply.domain.ports.research_port import (
    DiscoveryCandidateObservation,
    DiscoveryCardObservation,
    DiscoveryObservation,
    NullResearchObserver,
)
from auto_apply.domain.services.url_evidence import (
    decide_resolution_state,
    merge_candidates,
    merge_rejections,
)
from auto_apply.adapters.secondary.discovery.components.card_activation import (
    CardActivator,
)

logger = logging.getLogger(__name__)

# Hard bound on clicks per page during deferred resolution. A bound, not a
# knob: it exists so a click architecture that yields nothing cannot consume
# unbounded time and rate-limit budget. (Class constant in the spirit of
# MAX_PAGES elsewhere; hoisting to runtime_defaults.yaml is a later-stage
# config decision, deliberately not bundled into this batch.)
DEFAULT_MAX_CARD_ACTIVATIONS = 8


def _normalize_card(card: Any) -> JobCardInfo:
    """Build a JobCardInfo from any card-shaped object using defensive reads.

    The extractor consumes a port. Port consumers must not require fields
    the protocol did not previously carry — stub cards and older adapters
    may only have ``title``/``company``/``url``. Everything added by the
    resolution pipeline is read with a default here.
    """
    return JobCardInfo(
        title=getattr(card, "title", "") or "",
        company=getattr(card, "company", "") or "",
        location=getattr(card, "location", "") or "",
        url=getattr(card, "url", "") or "",
        snippet=getattr(card, "snippet", "") or "",
        posted_date_text=getattr(card, "posted_date_text", "") or "",
        salary_text=getattr(card, "salary_text", "") or "",
        confidence=getattr(card, "confidence", 1.0) or 0.0,
        card_index=getattr(card, "card_index", -1),
        candidates=tuple(getattr(card, "candidates", ()) or ()),
        rejections=tuple(getattr(card, "rejections", ()) or ()),
        resolution_state=(
            getattr(card, "resolution_state", "")
            or CardResolutionState.NO_DESTINATION.value
        ),
        identity_attribute=getattr(card, "identity_attribute", "") or "",
        identity_value=getattr(card, "identity_value", "") or "",
    )


class PageUnderstandingExtractor:
    """Adapts a :class:`PageUnderstandingPort` to :class:`SerpExtractionPort`.

    Validation is deliberately identical to ``SemanticMiner._extract_single_job``:
    a card becomes a :class:`Job` only if it has both a title and a URL, and an
    empty company becomes ``"Unknown"``. Two extraction routes that disagree
    about what counts as a job would make the fallback incomparable and the
    research dataset inconsistent.
    """

    def __init__(
        self,
        page_understanding: Any,
        browser: Any,
        observer: Any = None,
        readiness: Any = None,
        research_observer: Any = None,
        max_card_activations: int = DEFAULT_MAX_CARD_ACTIVATIONS,
    ) -> None:
        """Store the collaborators.

        Args:
            page_understanding: An object with ``analyze_serp(PageContext)``.
            browser: The live browser, read for URL/title and used for
                activation during :meth:`finalize_harvest`.
            observer: Optional extraction observer. Receives one
                ``audit_extraction_attempt`` per card, matching the miner's use
                of that method.
            readiness: Optional DomReadinessPort for post-click settle waits.
            research_observer: Optional ResearchObserverPort. Receives one
                ``observe_discovery`` per finalized page. The null observer
                (default) makes observation cost exactly nothing.
            max_card_activations: Hard cap on clicks per page.
        """
        self._page_understanding = page_understanding
        self._browser = browser
        self._observer = observer
        self._readiness = readiness
        self._research_observer = research_observer or NullResearchObserver()
        self._max_card_activations = max(0, int(max_card_activations))
        # State consumed by FallbackSerpExtractor's commit rule: how many
        # cards the most recent analyze_serp saw. Fallback commits use it to
        # distinguish "nothing on the page" from "cards exist but URLs need
        # deferred resolution".
        self.last_card_count: int = 0
        self.last_resolution_report: SerpResolutionReport | None = None
        self._activator: CardActivator | None = None

    def _context(self) -> PageContext:
        """Build the page context, tolerating a browser that will not answer."""
        url = title = ""
        try:
            url = self._browser.current_url or ""
        except Exception:  # noqa: BLE001 - a dead browser must not raise here
            pass
        try:
            title = self._browser.title or ""
        except Exception:  # noqa: BLE001
            pass
        return PageContext(url=url, page_title=title)

    def _get_activator(self) -> CardActivator | None:
        """Lazily build the activator when the browser can relocate elements."""
        if self._activator is not None:
            return self._activator
        if not callable(getattr(self._browser, "find_elements", None)):
            return None
        self._activator = CardActivator(self._browser, readiness=self._readiness)
        return self._activator

    def mine_jobs(self, source_name: str) -> list[Job]:
        """Extract listings via one page-understanding pass. Never raises."""
        try:
            structure = self._page_understanding.analyze_serp(self._context())
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "PageUnderstandingExtractor: analyze_serp failed (%s); "
                "reporting no jobs so the caller can fall back.", exc,
            )
            return []

        cards = list(getattr(structure, "job_cards", ()) or ())
        self.last_card_count = len(cards)
        self.last_resolution_report = getattr(structure, "resolution_report", None)

        jobs: list[Job] = []
        seen = dropped_no_title = dropped_no_url = 0
        dropped_multi_route = dropped_deferred = 0
        for card in cards:
            seen += 1
            # Defensive reads: a port consumer must not require fields the
            # protocol did not previously carry (stub cards, older adapters).
            title = (getattr(card, "title", "") or "").strip()
            url = (getattr(card, "url", "") or "").strip()
            company = (getattr(card, "company", "") or "").strip() or "Unknown"
            state = getattr(card, "resolution_state", "") or ""
            candidate_count = len(getattr(card, "candidates", ()) or ())

            if not (title and url):
                if not title:
                    dropped_no_title += 1
                elif state == CardResolutionState.MULTI_ROUTE.value:
                    dropped_multi_route += 1
                    self._audit(
                        {"title": title, "candidates": candidate_count},
                        False,
                        "multi-route candidates deferred",
                    )
                elif state == CardResolutionState.DEFERRED.value:
                    dropped_deferred += 1
                    self._audit(
                        {"title": title, "candidates": candidate_count},
                        False,
                        "deferred candidates",
                    )
                else:
                    dropped_no_url += 1
                    self._audit({"title": title, "url": url}, False, "missing title or url")
                continue

            try:
                jobs.append(
                    Job(title=title, company=company, url=url, source=source_name)
                )
            except Exception as exc:  # noqa: BLE001
                self._audit({"title": title, "url": url}, False, f"invalid job: {exc}")
                continue
            self._audit({"title": title, "company": company, "url": url}, True)

        # Say what was thrown away, in the console, once per harvest. The
        # per-card audit rows go to the observer and never reach the log a
        # person actually reads, so a route that silently discards everything
        # looks identical to a page with nothing on it.
        if seen and len(jobs) != seen:
            logger.info(
                "%s: %d card(s) seen, %d kept, %d dropped (no title), "
                "%d dropped (no url), %d dropped (multi-route deferred), "
                "%d dropped (deferred).",
                source_name,
                seen,
                len(jobs),
                dropped_no_title,
                dropped_no_url,
                dropped_multi_route,
                dropped_deferred,
            )

        return jobs

    # ------------------------------------------------------------------
    # Deferred resolution — runs once per page, AFTER the scroll loop
    # ------------------------------------------------------------------

    def finalize_harvest(self, source_name: str) -> list[Job]:
        """Resolve deferred cards via bounded click activation.

        Called once per page after the scroll loop completes, so a click
        never contaminates a harvest. Re-runs the static pass on the final
        DOM (single source of truth for the page's final state), activates
        unresolved cards under a hard budget with an opaque-architecture
        early stop, emits the discovery observation, and returns only the
        jobs whose resolution came from activation — statically resolved
        cards were already emitted during the harvest.
        """
        context = self._context()
        try:
            structure = self._page_understanding.analyze_serp(context)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "PageUnderstandingExtractor.finalize_harvest: analyze_serp "
                "failed (%s); returning no additional jobs.", exc,
            )
            return []

        # Normalize once at the port boundary: every downstream read is then
        # a direct attribute access on a real JobCardInfo, and merge/replace
        # cannot fail on card-shaped stubs.
        cards = [
            _normalize_card(c)
            for c in (getattr(structure, "job_cards", ()) or ())
        ]
        self.last_card_count = len(cards)
        report = getattr(structure, "resolution_report", None)
        self.last_resolution_report = report

        serp_host = urllib.parse.urlsplit(context.url).netloc.lower()
        new_jobs: list[Job] = []
        activation_attempts = 0
        activation_resolved = 0
        opaque_stop = False

        activator = self._get_activator()
        if activator is not None and self._max_card_activations > 0:
            updated: list[JobCardInfo] = []
            for card in cards:
                if (
                    opaque_stop
                    or activation_attempts >= self._max_card_activations
                    or card.resolution_state == CardResolutionState.RESOLVED.value
                    or not card.identity_attribute
                    or not card.identity_value
                ):
                    updated.append(card)
                    continue

                outcome = activator.activate(
                    identity_attribute=card.identity_attribute,
                    identity_value=card.identity_value,
                    title=card.title,
                    serp_host=serp_host,
                    page_url=context.url,
                )
                activation_attempts += 1

                if outcome.error:
                    updated.append(card)
                    continue
                if not outcome.candidates and not outcome.rejections and not outcome.navigated:
                    updated.append(card)
                    continue

                merged_candidates = merge_candidates(card.candidates, outcome.candidates)
                merged_rejections = merge_rejections(card.rejections, outcome.rejections)
                state, selected = decide_resolution_state(
                    merged_candidates,
                    merged_rejections,
                    material_seen=True,
                )
                card = replace(
                    card,
                    candidates=merged_candidates,
                    rejections=merged_rejections,
                    resolution_state=state.value,
                    url=selected.url if selected else "",
                )
                updated.append(card)

                if selected is not None and card.title:
                    activation_resolved += 1
                    try:
                        new_jobs.append(
                            Job(
                                title=card.title,
                                company=(card.company or "").strip() or "Unknown",
                                url=selected.url,
                                source=source_name,
                            )
                        )
                        self._audit(
                            {"title": card.title, "url": selected.url},
                            True,
                            "resolved via activation",
                        )
                    except Exception as exc:  # noqa: BLE001
                        self._audit(
                            {"title": card.title, "url": selected.url},
                            False,
                            f"invalid job: {exc}",
                        )

                if _is_opaque_uniform(outcome, serp_host):
                    opaque_stop = True
                    logger.info(
                        "%s: activation reveals an opaque redirect architecture "
                        "(no decodable or direct external destination) — "
                        "stopping further activations on this page.",
                        source_name,
                    )

            cards = updated

        self._emit_observation(
            source_name, context, cards, report, activation_attempts, activation_resolved
        )

        logger.info(
            "%s finalize: %d card(s), %d activation attempt(s), "
            "%d job(s) resolved via activation.",
            source_name,
            len(cards),
            activation_attempts,
            len(new_jobs),
        )
        return new_jobs

    # ------------------------------------------------------------------
    # Observation (§4b) — consent-gated by the observer itself
    # ------------------------------------------------------------------

    def _emit_observation(
        self,
        source_name: str,
        context: PageContext,
        cards: list[JobCardInfo],
        report: SerpResolutionReport | None,
        activation_attempts: int,
        activation_resolved: int,
    ) -> None:
        """Build and emit one DiscoveryObservation for the finalized page.

        Guarded by the observer's own ``is_enabled``: with consent absent
        this method costs exactly nothing.
        """
        if not self._research_observer.is_enabled:
            return
        try:
            card_obs: list[DiscoveryCardObservation] = []
            for card in cards:
                cand_obs: list[DiscoveryCandidateObservation] = []
                for cand in card.candidates:
                    cand_obs.append(
                        DiscoveryCandidateObservation(
                            original_url=cand.original_url,
                            resolved_url=cand.url,
                            resolved_host=urllib.parse.urlsplit(cand.url).netloc.lower(),
                            anchor_text=cand.anchor_text,
                            source=cand.source,
                            outcome=("selected" if cand.url == card.url else "candidate"),
                            rejection_reason="",
                            apply_intent=cand.apply_intent,
                            title_overlap=cand.title_overlap,
                            method=cand.method,
                        )
                    )
                for rej in card.rejections:
                    cand_obs.append(
                        DiscoveryCandidateObservation(
                            original_url=rej.original_url,
                            resolved_url=rej.resolved_url,
                            resolved_host=urllib.parse.urlsplit(rej.resolved_url).netloc.lower(),
                            anchor_text="",
                            source="",
                            outcome="rejected",
                            rejection_reason=rej.reason,
                            ad_evidence=rej.evidence if "advertising" in rej.reason.lower() else (),
                        )
                    )
                card_obs.append(
                    DiscoveryCardObservation(
                        card_index=card.card_index,
                        title=card.title,
                        resolution_state=card.resolution_state,
                        selected_host=urllib.parse.urlsplit(card.url).netloc.lower() if card.url else "",
                        candidates=tuple(cand_obs),
                    )
                )

            resolved_n = sum(
                1 for c in cards if c.resolution_state == CardResolutionState.RESOLVED.value
            )
            multi_n = sum(
                1 for c in cards if c.resolution_state == CardResolutionState.MULTI_ROUTE.value
            )
            deferred_n = sum(
                1 for c in cards if c.resolution_state == CardResolutionState.DEFERRED.value
            )
            no_dest_n = sum(
                1 for c in cards if c.resolution_state == CardResolutionState.NO_DESTINATION.value
            )
            sponsored_n = sum(
                1 for c in cards if not c.candidates and c.has_ad_rejection
            )

            observation = DiscoveryObservation(
                provider=source_name,
                page_host=urllib.parse.urlsplit(context.url).netloc.lower(),
                page_state="normal",
                blocked=False,
                architecture=_derive_architecture(cards, report),
                card_count=len(cards),
                resolved_count=resolved_n,
                multi_route_count=multi_n,
                deferred_count=deferred_n,
                no_destination_count=no_dest_n,
                sponsored_card_count=sponsored_n,
                activation_attempts=activation_attempts,
                activation_resolved=activation_resolved,
                learned_identity=tuple(report.learned_identity) if report else (),
                cards=tuple(card_obs),
            )
            self._research_observer.observe_discovery(observation)
        except Exception as exc:  # noqa: BLE001
            # Observation must never break extraction.
            logger.debug("PageUnderstandingExtractor: observation failed (non-fatal): %s", exc)

    def _audit(self, data: dict, success: bool, reason: str = "") -> None:
        if self._observer is None:
            return
        try:
            self._observer.audit_extraction_attempt(data, success, reason)
        except Exception:  # noqa: BLE001 - observation must never break extraction
            pass


def _derive_architecture(
    cards: list[JobCardInfo],
    report: SerpResolutionReport | None,
) -> str:
    """Derived card-group architecture label for the observation record.

    Computed from resolution outcomes, not from vendor knowledge: a group
    that mostly resolves statically is anchorful; a group that is mostly
    anchorless but carries a learned identity is identifier-plus-JS.
    """
    if not cards:
        return "none"
    anchorful = sum(1 for c in cards if c.resolution_state == CardResolutionState.RESOLVED.value)
    identifier_js = sum(
        1
        for c in cards
        if c.resolution_state in (CardResolutionState.NO_DESTINATION.value,)
        and c.identity_attribute
    )
    total = len(cards)
    if anchorful * 2 >= total:
        return "anchorful"
    if identifier_js * 2 >= total:
        return "identifier_js"
    return "mixed"


def _is_opaque_uniform(outcome, serp_host: str) -> bool:
    """True when a page's click architecture is uniformly opaque.

    The signal is about codec success, not vendors: revealed candidates
    exist, but none decoded through the wrapper ladder and none is a direct
    external destination. One such card is evidence for the whole page —
    the same widget renders every card — so further clicks buy nothing.
    """
    if not outcome.candidates:
        return False
    for cand in outcome.candidates:
        if "unwrapped from" in (cand.method or ""):
            return False
        if not cand.pending_redirect:
            host = urllib.parse.urlsplit(cand.url).netloc.lower()
            if host and host != serp_host:
                return False
    return True


class FallbackSerpExtractor:
    """Tries the fast extractor once, then commits to one route for the page.

    The commitment matters more than it looks. Without it, the dry-scroll tail
    would be the expensive case: a feed that is genuinely exhausted returns no
    new jobs for ``dry_scroll_limit`` consecutive harvests, and an
    "empty means fall back" rule would run a full miner pass on every one of
    them — making a search *slower* than before this class existed.

    The decision is taken once per instance, on the first harvest, and logged:

    * fast path returns jobs        -> use it for the rest of the page
    * fast path returns nothing BUT -> stay fast: a card group exists, so the
      detected cards are real, and      URLs may only need deferred resolution
      ``last_card_count > 0``           (``fast:deferred``)
    * fast path returns nothing and -> use the miner for the rest of the page
      detected no cards
    * fast path raises              -> use the miner for the rest of the page

    A page with genuinely no listings therefore costs one wasted fast attempt
    (tens of milliseconds) plus exactly what it costs today. That is the
    intended worst case: never worse than the miner alone.
    """

    def __init__(self, fast: Any, fallback: Any):
        self._fast = fast
        self._fallback = fallback
        self._chosen: Any = None
        self._route = "undecided"

    @property
    def route_label(self) -> str:
        """Which route this instance committed to — for logs and pins."""
        return self._route

    def mine_jobs(self, source_name: str) -> list[Job]:
        """Harvest via the committed route, choosing one on the first call."""
        if self._chosen is not None:
            return self._chosen.mine_jobs(source_name=source_name)

        try:
            jobs = self._fast.mine_jobs(source_name=source_name)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "%s: fast SERP extraction raised (%s) — falling back to the "
                "DOM miner for this page.", source_name, exc,
            )
            self._commit(self._fallback, "fallback:error")
            return self._fallback.mine_jobs(source_name=source_name)

        if jobs:
            self._commit(self._fast, "fast")
            logger.info(
                "%s: fast SERP extraction produced %d listings — using it for "
                "this page.", source_name, len(jobs),
            )
            return jobs

        # A card group exists but nothing yielded a URL yet. The cards are
        # real (the detector found them); the destinations need deferred
        # resolution. Falling to the miner here would re-walk the same
        # anchorless cards and pay the miner's cost for the same nothing.
        card_count = getattr(self._fast, "last_card_count", 0)
        if isinstance(card_count, int) and card_count > 0:
            self._commit(self._fast, "fast:deferred")
            logger.info(
                "%s: fast SERP extraction found a card group (%d cards) but "
                "no immediately usable URLs — staying on the fast route for "
                "deferred resolution.",
                source_name,
                card_count,
            )
            return []

        logger.info(
            "%s: fast SERP extraction found no listings — falling back to the "
            "DOM miner for this page.", source_name,
        )
        self._commit(self._fallback, "fallback:empty")
        return self._fallback.mine_jobs(source_name=source_name)

    def finalize_harvest(self, source_name: str) -> list[Job]:
        """Delegate post-scroll deferred resolution to the fast extractor.

        The fast extractor always ran at least the first harvest, so it is
        the right place to emit the page observation and to run bounded
        activation. When the chosen route is the miner, the fast extractor
        holds no deferred cards and returns nothing.
        """
        finalize = getattr(self._fast, "finalize_harvest", None)
        if not callable(finalize):
            return []
        try:
            return finalize(source_name=source_name) or []
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "%s: finalize_harvest failed (%s); returning no additional jobs.",
                source_name, exc,
            )
            return []

    def _commit(self, route: Any, label: str) -> None:
        self._chosen = route
        self._route = label
