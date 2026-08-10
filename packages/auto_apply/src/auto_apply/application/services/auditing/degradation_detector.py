"""Silent-degradation detector — fail closed when a provider serves
thinned content.

A provider that decides AA is a bot has three ways to say so:

  1. Hard block (403/429)          — covered: "403 forbidden" is a detection
                                     keyword in evasion/detection.py.
  2. Soft block (challenge page    — covered: DefaultDetectionStrategy /
     at HTTP 200, e.g. /sorry/)      PageClassifier abort the strategy.
  3. SILENT DEGRADATION            — previously uncovered. A normal-looking
     page, served thinned. Measured: Indeed went from 17 real jobs in 88s to
     3 nav links in 2.2s (a ~40x page-size drop) between runs, and nothing
     noticed. AA treated the collapse as a legitimate harvest.

This detector compares each provider's FIRST harvest per instruction — yield
count, page bytes, elapsed seconds — against that provider's own recorded
baseline (an EMA store persisted across sessions). It benches the provider
for the rest of the session ONLY when yield and page size collapse together:
a single-metric dip can be a legitimately sparse query, and false positives
silently discard real jobs, which is the worse error in the other direction.

Design rules (recorded per the TODO's P2 item):

  * Fail closed. If AA may have been served false information, leaving is
    the safe move. A benched provider returns nothing for the rest of the
    session, loudly.
  * Never fire without a baseline. First encounters are recorded, not judged.
  * Never write in a deterministic (seeded) run — two identical runs must not
    shift each other's baselines (same contract as PageFeedbackService).
  * This module is deliberately the seed of the future research
    "contamination" feature: the same machinery that detects "this page is
    not what it should be" will later answer "this data cannot be trusted
    for research". Say so here so the intent survives.
"""
from __future__ import annotations

import logging
from typing import Any

from auto_apply.domain.events import Event

logger = logging.getLogger(__name__)


class SilentDegradationDetector:
    """Session-scoped guard that benches providers serving thinned content.

    Args:
        baseline_store: An object with
            ``get_baseline(provider) -> HarvestBaseline | None`` and
            ``record_harvest(provider, visible, page_bytes, elapsed)``.
            Deliberately duck-typed: no domain port yet — the port arrives
            when a second implementation does. May be None (record-and-judge
            become no-ops; is_benched still works).
        config: The ``discovery`` section of the effective config. Reads
            degradation_collapse_ratio, degradation_page_bytes_ratio,
            degradation_min_samples — all with defaults matching
            runtime_defaults.yaml.
        event_bus: Optional EventBus for Event.PROVIDER_BENCHED.
        deterministic: When True (seeded research run), no baseline writes
            and no benching — evaluation is log-only, so two seeded runs are
            byte-identical.
    """

    def __init__(
        self,
        baseline_store: Any,
        config: dict | None = None,
        event_bus: Any = None,
        deterministic: bool = False,
    ) -> None:
        self._store = baseline_store
        cfg = config or {}
        self._collapse_ratio = float(cfg.get("degradation_collapse_ratio", 0.15))
        self._bytes_ratio = float(cfg.get("degradation_page_bytes_ratio", 0.25))
        self._min_samples = int(cfg.get("degradation_min_samples", 3))
        self._event_bus = event_bus
        self._deterministic = deterministic
        self._benched: set[str] = set()

    def is_benched(self, provider: str) -> bool:
        """True if *provider* has been benched this session."""
        return provider in self._benched

    def evaluate_first_harvest(
        self,
        *,
        provider: str,
        visible_count: int,
        page_bytes: int,
        elapsed_seconds: float,
        route: str = "",
    ) -> None:
        """Evaluate (and maybe record) the first harvest of one instruction.

        Only the first harvest is meaningful: the dry-scroll tail is expected
        to thin out and must never reach the baseline. Never raises.
        """
        if provider in self._benched or self._deterministic:
            return
        try:
            baseline = self._store.get_baseline(provider) if self._store else None
        except Exception as exc:
            logger.debug("degradation guard: baseline read failed: %s", exc)
            baseline = None

        if baseline is None or baseline.sample_count < self._min_samples:
            self._record(provider, visible_count, page_bytes, elapsed_seconds)
            logger.info(
                "%s: degradation guard collecting baseline (%d sample(s)); "
                "harvest accepted (%d visible, %d bytes, %.1fs, via %s)",
                provider,
                baseline.sample_count if baseline else 0,
                visible_count,
                page_bytes,
                elapsed_seconds,
                route or "unknown",
            )
            return

        if baseline.avg_visible < 1.0 or baseline.avg_page_bytes < 1.0:
            # Degenerate baseline (e.g. built entirely from empty harvests) —
            # it cannot support a collapse judgment. Refresh and move on.
            self._record(provider, visible_count, page_bytes, elapsed_seconds)
            return

        yield_ratio = visible_count / baseline.avg_visible
        bytes_ratio = page_bytes / baseline.avg_page_bytes

        if yield_ratio <= self._collapse_ratio and bytes_ratio <= self._bytes_ratio:
            self._benched.add(provider)
            logger.warning(
                "SILENT DEGRADATION — benching %s for this session: "
                "yield %d vs baseline %.1f (ratio %.3f <= %.2f) AND page "
                "bytes %d vs baseline %.0f (ratio %.3f <= %.2f), over %d "
                "baseline samples. Treating the harvest as invalid, not as "
                "a legitimate result.",
                provider,
                visible_count,
                baseline.avg_visible,
                yield_ratio,
                self._collapse_ratio,
                page_bytes,
                baseline.avg_page_bytes,
                bytes_ratio,
                self._bytes_ratio,
                baseline.sample_count,
            )
            if self._event_bus is not None:
                try:
                    self._event_bus.publish(
                        Event.PROVIDER_BENCHED,
                        {
                            "provider": provider,
                            "yield_ratio": round(yield_ratio, 4),
                            "bytes_ratio": round(bytes_ratio, 4),
                            "baseline_samples": baseline.sample_count,
                        },
                    )
                except Exception as exc:
                    logger.debug("degradation guard: event publish failed: %s", exc)
            return

        # Healthy harvest — keep the baseline current.
        self._record(provider, visible_count, page_bytes, elapsed_seconds)

    def _record(
        self, provider: str, visible: int, page_bytes: int, elapsed: float
    ) -> None:
        if self._store is None or self._deterministic:
            return
        try:
            self._store.record_harvest(provider, visible, page_bytes, elapsed)
        except Exception as exc:
            logger.debug("degradation guard: baseline write failed: %s", exc)
