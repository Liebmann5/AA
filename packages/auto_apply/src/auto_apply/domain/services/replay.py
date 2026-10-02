"""Replay: the detectors re-run over a fixed corpus, byte for byte (item 7).

A research claim is only as good as the ability of someone else to re-run
it and get the same answer. A live session cannot be re-run: the web
changes between visits. What can be re-run is the step from a page AA kept
to the signals AA derived from it. This module is that step, as a pure
function of the corpus:

    kept page copy --visible_text--> text
                   --posting_observation / posting_detection_context-->
                   --run_all_detectors--> signals --> canonical bytes

(the same builders and detectors a live run uses — see posting_context).

The result is the same bytes for the same corpus and AA version, on any
machine, because nothing in it comes from the machine:

* no clock — each posting is replayed as of its own capture date;
* no randomness — signal ids are derived from (copy, signal type, index);
* no private key — the anonymous company code needs the contributor's
  key, so it is not replayed (detectors use the company for nothing else);
* no paths — corpus files are named by their path inside the corpus;
* no platform formatting — canonical JSON (sorted keys, fixed separators,
  UTF-8, "\\n" line ends, no NaN), emitted as bytes;
* sorted everything — records by (copy_id, source), files by source.

What the manifest does NOT claim: that a replay reproduces the live run's
signals. A live run reads the page's text through the browser (innerText,
which sees CSS); a replay extracts it from the kept copy with AA's own
extractor, from a page whose own-details were already cleaned out. The
manifest names the extraction method and lists what is not replayed.

Pure: no I/O. Standard library plus AA's own domain.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import date
from typing import Any

from auto_apply.domain.constants import RESEARCH_SCHEMA_VERSION
from auto_apply.domain.models.replay import (
    REPLAY_FORMAT,
    ReplayCorpus,
    ReplayItem,
    ReplayOutput,
    ReplaySkip,
)
from auto_apply.domain.services.posting_context import (
    posting_detection_context,
    posting_observation,
)
from auto_apply.domain.services.signal_detectors import (
    OUTCOME_CLEAN,
    ResearchSignal,
    detector_roster,
    run_all_detectors,
)
from auto_apply.domain.services.text_extraction import EXTRACTION_METHOD, visible_text

__all__ = [
    "NOT_REPLAYED",
    "REPLAYED_CONTEXTS",
    "canonical_json_line",
    "replay_corpus",
    "replay_item",
]

#: Page contexts a replay re-runs. Search pages are never kept (item 6).
REPLAYED_CONTEXTS: frozenset[str] = frozenset({"job_posting"})

#: Inputs a live run has and a replay deliberately does not — named in every
#: manifest, so a reader knows exactly which signals a replay cannot
#: reproduce and why.
NOT_REPLAYED: tuple[tuple[str, str], ...] = (
    (
        "company_id",
        "the anonymous company code is keyed by the contributor's private "
        "research key; detectors use the company name for nothing else",
    ),
    (
        "lifecycle history",
        "days live, reposting and cross-platform sightings come from the "
        "contributor's research database, not from a page",
    ),
    (
        "salary corpus percentile",
        "the below-market comparison (ST-03) reads the contributor's salary "
        "corpus",
    ),
    (
        "corpus-level macro signals",
        "LM-01..LM-03 are computed over a whole research database",
    ),
    (
        "form observations",
        "application forms are not kept as page copies",
    ),
)


def canonical_json_line(value: Any) -> bytes:
    """One value as canonical JSON bytes: sorted keys, no spaces, UTF-8,
    NaN refused — the same bytes on every platform and Python version."""
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _signal_id(copy_id: str, signal_type: str, index: int) -> str:
    """Deterministic: the same copy yields the same ids on every replay."""
    return "replay-" + _sha256(f"{copy_id}\x00{signal_type}\x00{index}".encode())[:32]


def _signal_record(signal: ResearchSignal, signal_id: str, captured_on: date) -> dict[str, Any]:
    return {
        "signal_id": signal_id,
        "signal_type": signal.signal_type,
        "severity": signal.severity,
        "confidence": signal.confidence,
        "evidence_text": signal.evidence_text,
        "jurisdiction": signal.jurisdiction,
        "platform": signal.platform,
        "job_category": signal.job_category,
        "detected_date": captured_on.isoformat(),
    }


def replay_item(item: ReplayItem) -> dict[str, Any]:
    """Replay one kept page copy into its record.

    The posting is observed exactly as a live run observes it
    (posting_observation), as of the copy's capture date, with the text
    re-extracted from the copy and no company (see NOT_REPLAYED).
    """
    captured_on = date.fromisoformat(item.captured_at[:10])
    text = visible_text(item.page)
    facts = item.facts
    observation = posting_observation(
        job_title=facts.job_title if facts else "",
        job_description=text,
        company_name=None,
        location=facts.location if facts else None,
        platform=facts.platform if facts else None,
        url=item.url,
        seen_on=captured_on,
        page_copy_id=item.copy_id,
    )
    result = run_all_detectors(
        posting_detection_context(observation, current_date=captured_on)
    )
    per_type: dict[str, int] = {}
    signals: list[dict[str, Any]] = []
    for signal in result.signals:
        index = per_type.get(signal.signal_type, 0)
        per_type[signal.signal_type] = index + 1
        signals.append(
            _signal_record(signal, _signal_id(item.copy_id, signal.signal_type, index), captured_on)
        )
    text_bytes = text.encode("utf-8")
    return {
        "copy_id": item.copy_id,
        "source": item.source,
        "captured_on": captured_on.isoformat(),
        "observation": {
            "job_title": observation.job_title,
            "location": observation.location,
            "jurisdiction": observation.jurisdiction,
            "metro_area": observation.metro_area,
            "platform": observation.platform,
            "application_url_is_generic": observation.application_url_is_generic,
            "facts_recorded": facts is not None,
            "text_sha256": _sha256(text_bytes),
            "text_chars": len(text),
        },
        "detectors_run": list(result.detectors_run),
        "outcomes": [
            {
                "signal_type": o.signal_type,
                "outcome": o.outcome,
                "signals_count": o.signals_count,
                "error_class": o.error_class,
            }
            for o in result.outcomes
            if o.outcome != OUTCOME_CLEAN
        ],
        "signals": signals,
    }


def replay_corpus(corpus: ReplayCorpus, *, aa_version: str) -> ReplayOutput:
    """Replay a whole corpus into the exact bytes of its artifact.

    Args:
        corpus: What a corpus reader found (files, items, skips).
        aa_version: The AA version doing the replay — part of the result's
            identity, because a new version may detect differently.

    Returns:
        The records and manifest as bytes, with their digests and counts.
    """
    skipped = list(corpus.skipped)
    replayable: list[ReplayItem] = []
    for item in corpus.items:
        if item.context in REPLAYED_CONTEXTS:
            replayable.append(item)
        else:
            skipped.append(
                ReplaySkip(item.source, f"page context {item.context!r} is not replayed")
            )
    records = [replay_item(i) for i in sorted(replayable, key=lambda i: (i.copy_id, i.source))]
    artifact = b"".join(canonical_json_line(r) + b"\n" for r in records)
    files = sorted(corpus.files)
    corpus_list = [{"source": s, "sha256": h} for s, h in files]
    corpus_digest = _sha256(canonical_json_line(corpus_list))
    signals = sum(len(r["signals"]) for r in records)
    manifest_value = {
        "format": REPLAY_FORMAT,
        "aa_version": aa_version,
        "research_schema_version": RESEARCH_SCHEMA_VERSION,
        "extraction": EXTRACTION_METHOD,
        "detectors": list(detector_roster()),
        "dates": (
            "each posting is replayed as of its own capture date; the date "
            "of the replay is never used"
        ),
        "corpus": {"files": corpus_list, "digest": corpus_digest},
        "items": len(records),
        "signals": signals,
        "skipped": [
            {"source": s.source, "reason": s.reason}
            for s in sorted(skipped, key=lambda s: (s.source, s.reason))
        ],
        "artifact": {"name": "replay.jsonl", "sha256": _sha256(artifact)},
        "not_replayed": [{"input": k, "why": v} for k, v in NOT_REPLAYED],
    }
    manifest = (
        json.dumps(
            manifest_value, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False
        )
        + "\n"
    ).encode("utf-8")
    return ReplayOutput(
        records=artifact,
        manifest=manifest,
        corpus_digest=corpus_digest,
        artifact_sha256=_sha256(artifact),
        manifest_sha256=_sha256(manifest),
        items=len(records),
        signals=signals,
        skipped=tuple(sorted(skipped, key=lambda s: (s.source, s.reason))),
    )
