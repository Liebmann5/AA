"""
Central registry for all research signal detectors.

Usage:
    from auto_apply.domain.services.signal_detectors import ALL_DETECTORS, run_all_detectors

    result = run_all_detectors(context)
    signals = result.signals    # what was found
    outcomes = result.outcomes  # what happened — one per detector (item 5)
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import replace

from auto_apply.domain.services.signal_detectors.base import (
    OUTCOME_CLEAN,
    OUTCOME_FIRED,
    OUTCOME_RAISED,
    DetectionContext,
    DetectionResult,
    DetectorOutcome,
    ResearchSignal,
    SignalDetector,
)

logger = logging.getLogger(__name__)
from auto_apply.domain.services.signal_detectors.ghost_job_detectors import GHOST_JOB_DETECTORS
from auto_apply.domain.services.signal_detectors.discrimination_detectors import DISCRIMINATION_DETECTORS
from auto_apply.domain.services.signal_detectors.qualification_detectors import QUALIFICATION_DETECTORS
from auto_apply.domain.services.signal_detectors.salary_detectors import SALARY_DETECTORS
from auto_apply.domain.services.signal_detectors.dark_pattern_detectors import DARK_PATTERN_DETECTORS
from auto_apply.domain.services.signal_detectors.regulatory_detectors import REGULATORY_DETECTORS
from auto_apply.domain.services.signal_detectors.extended_detectors import EXTENDED_DETECTORS

ALL_DETECTORS: list[SignalDetector] = (
    GHOST_JOB_DETECTORS
    + DISCRIMINATION_DETECTORS
    + QUALIFICATION_DETECTORS
    + SALARY_DETECTORS
    + DARK_PATTERN_DETECTORS
    + REGULATORY_DETECTORS
    + EXTENDED_DETECTORS
)


def run_all_detectors(ctx: DetectionContext) -> DetectionResult:
    """Run every registered detector against a DetectionContext.

    Pure function — no I/O, no state, safe to call from any thread.

    DEDUPLICATION: If ctx.posting_hash is set, every returned signal has
    its posting_hash field populated AND its signal_id replaced with a
    deterministic value derived from (signal_type, posting_hash,
    detected_date). This is essential because the SAME underlying job
    posting is observed through MULTIPLE code paths during a session
    (e.g. observe_job_posting() during Discovery, observe_form() during
    Application) — both contexts share jurisdiction/salary fields, so the
    same detector (e.g. ST-01 "no salary disclosed in CA") legitimately
    fires from both. Without deterministic IDs, this would double-count
    the same real-world fact in the corpus. With deterministic IDs,
    ResearchSignalAggregator's `INSERT OR IGNORE` collapses repeats into
    a single row — the signal is recorded once per (type, posting, day),
    which is the correct unit of observation for aggregate statistics.

    If ctx.posting_hash is None (e.g. macro_analysis.py's corpus-level
    signals, which have no single posting), signal_id remains a random
    UUID as before — every macro signal is distinct by definition.

    Args:
        ctx: All available data for the job posting being analyzed.

    OUTCOME ACCOUNTING (item 5): every detector that runs produces exactly
    one DetectorOutcome — "clean", "fired" or "raised" — returned with the
    signals in the DetectionResult. A raising detector is caught, recorded
    as "raised" with the exception's CLASS NAME ONLY, and the remaining
    detectors still run: the no-raise guarantee pinned in
    tests/property_based/test_math_algorithms.py survives, but the blow-up
    is now data, not silence. str(exc) is never recorded — an exception
    message can quote the posting itself (item 5, C2). BaseExceptions
    (KeyboardInterrupt, SystemExit) still propagate: process control, not
    detector failure.

    Returns:
        A DetectionResult carrying the signals (sorted by confidence
        descending), the roster of detectors that ran, and one outcome per
        roster entry. len(result.outcomes) == len(result.detectors_run) is
        the completeness invariant; the persistence layer stores only
        non-clean outcomes and derives clean from the roster (item 5, O1).
    """
    results: list[ResearchSignal] = []
    roster: list[str] = []
    outcomes: list[DetectorOutcome] = []
    for index, detector in enumerate(ALL_DETECTORS):
        # Name the detector BEFORE running it: if the signal_type property
        # itself raises, the outcome still has to name something — a raised
        # detector is a recorded fact, never silence (item 5, R3).
        try:
            signal_type = detector.signal_type
        except Exception:
            signal_type = f"detector_{index}:{type(detector).__name__}"
        roster.append(signal_type)
        try:
            raw: list[ResearchSignal] | None = detector.detect(ctx)
            if raw is None:
                # Contract violation — detect() must return a list. Recorded
                # as a raise so the defect is data, not a silent clean.
                raise TypeError(f"{signal_type}.detect() returned None")
            detected = list(raw)
        except Exception as exc:
            # C2: the exception's CLASS NAME only. str(exc) can quote the
            # posting — a company name, a URL, description text — and
            # recording it would be a PII leak with a research-data label.
            outcomes.append(
                DetectorOutcome(
                    signal_type=signal_type,
                    outcome=OUTCOME_RAISED,
                    signals_count=0,
                    error_class=type(exc).__name__,
                )
            )
            logger.debug(
                "run_all_detectors | %s raised %s",
                signal_type,
                type(exc).__name__,
            )
            continue
        outcomes.append(
            DetectorOutcome(
                signal_type=signal_type,
                outcome=OUTCOME_FIRED if detected else OUTCOME_CLEAN,
                signals_count=len(detected),
            )
        )
        results.extend(detected)

    if ctx.posting_hash:
        deduped: list[ResearchSignal] = []
        for sig in results:
            dedup_key = f"{sig.signal_type}:{ctx.posting_hash}:{sig.detected_date.isoformat()}"
            deterministic_id = hashlib.sha256(dedup_key.encode()).hexdigest()
            deduped.append(replace(sig, signal_id=deterministic_id, posting_hash=ctx.posting_hash))
        results = deduped

    ordered = sorted(results, key=lambda s: s.confidence, reverse=True)
    return DetectionResult(
        signals=tuple(ordered),
        detectors_run=tuple(roster),
        outcomes=tuple(outcomes),
    )


__all__ = [
    "ALL_DETECTORS",
    "OUTCOME_CLEAN",
    "OUTCOME_FIRED",
    "OUTCOME_RAISED",
    "DetectionContext",
    "DetectionResult",
    "DetectorOutcome",
    "ResearchSignal",
    "SignalDetector",
    "run_all_detectors",
]
