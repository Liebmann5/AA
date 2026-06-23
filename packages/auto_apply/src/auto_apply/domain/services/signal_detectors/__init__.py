"""
Central registry for all research signal detectors.

Usage:
    from auto_apply.domain.services.signal_detectors import ALL_DETECTORS, run_all_detectors

    signals = run_all_detectors(context)
"""
from __future__ import annotations

import hashlib
from dataclasses import replace

from auto_apply.domain.services.signal_detectors.base import (
    DetectionContext,
    ResearchSignal,
    SignalDetector,
)
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


def run_all_detectors(ctx: DetectionContext) -> list[ResearchSignal]:
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

    Returns:
        All detected signals from all detectors, sorted by confidence descending.
    """
    results: list[ResearchSignal] = []
    for detector in ALL_DETECTORS:
        try:
            results.extend(detector.detect(ctx))
        except Exception:
            pass  # A failing detector must never crash the pipeline

    if ctx.posting_hash:
        deduped: list[ResearchSignal] = []
        for sig in results:
            dedup_key = f"{sig.signal_type}:{ctx.posting_hash}:{sig.detected_date.isoformat()}"
            deterministic_id = hashlib.sha256(dedup_key.encode()).hexdigest()
            deduped.append(replace(sig, signal_id=deterministic_id, posting_hash=ctx.posting_hash))
        results = deduped

    return sorted(results, key=lambda s: s.confidence, reverse=True)


__all__ = [
    "DetectionContext",
    "ResearchSignal",
    "SignalDetector",
    "ALL_DETECTORS",
    "run_all_detectors",
]
