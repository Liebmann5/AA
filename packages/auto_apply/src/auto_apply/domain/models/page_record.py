"""The per-page record: what AA observed on a page and what it decided.

This is the start of the record ADR-022 calls the per-page record and the
comprehension blueprint calls the trace (CT-T-018, levels L0 and L1; 08
section 1). Slice S1 builds the discovery part: every result card found on a
page, and the one fate each card met (kept, dropped, or deferred to the click
pass), each with an enumerated reason; and, in the click pass, every card
opened and what came of it.

Privacy by construction (08 section 5): the L0 and L1 views hold only
counters, enumerations, durations and hashes. No string that came from the
page (titles, link text, URLs, hosts, attribute names or values) is ever
stored in a field of these types. A destination is referred to by
:func:`url_ref`, a short SHA-256 commitment of its canonical URL, so a local
log line (LR-6) or an L2 page copy can be joined to the record without the
record holding the URL. The test ``test_l0_l1_carry_no_page_text`` pins this.

Pure standard library; no I/O. The extractor that builds a record decides
where it goes (today: the session log, one JSON line per pass).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

#: Version of the record layout. Bump on any field change (08 section 1).
TRACE_SCHEMA = 1


def url_ref(canonical: str) -> str:
    """Return a 16-hex-digit commitment to a canonical URL ("" for "")."""
    if not canonical:
        return ""
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


class PassKind(str, Enum):
    """Which discovery pass made the decisions."""

    HARVEST = "harvest"  # static read during the scroll loop (mine_jobs)
    FINALIZE = "finalize"  # click pass after the scroll loop


class DecisionStage(str, Enum):
    """The step of a card's life a decision belongs to."""

    FOUND = "found"
    FATE = "fate"
    OPENED = "opened"


class CardFate(str, Enum):
    """The one outcome each card meets in a pass."""

    KEPT = "kept"
    DROPPED = "dropped"
    DEFERRED = "deferred"  # left for the click pass


class CardReason(str, Enum):
    """Why a decision was made. Enumerated, never free text."""

    DETECTED = "detected"
    TITLE_AND_LINK = "title_and_link"
    NO_TITLE = "no_title"
    MULTI_ROUTE = "multi_route"
    NO_ELIGIBLE_LINK = "no_eligible_link"
    NO_LINK = "no_link"
    INVALID_JOB = "invalid_job"
    # click pass
    ALREADY_RESOLVED = "already_resolved"
    NO_IDENTITY = "no_identity"
    CLICK_BUDGET = "click_budget"
    OPAQUE_STOP = "opaque_stop"
    NO_ACTIVATOR = "no_activator"
    OPENED_RESOLVED = "opened_resolved"
    OPENED_NO_TITLE = "opened_no_title"
    OPENED_UNRESOLVED = "opened_unresolved"
    OPENED_NOTHING = "opened_nothing"
    OPENED_ERROR = "opened_error"


class TitleSource(str, Enum):
    """Where a card's title came from (06 section 2)."""

    HEADING = "heading"
    ANCHOR_NAME = "anchor_name"
    NONE = "none"


@dataclass(frozen=True)
class ObservationFacts:
    """Cost and honesty facts about one extraction (08 `observation` event).

    ``text_capped`` counts nodes whose full text or name was cut at the text
    cap; ``text_budget_hit`` says the observation-wide text budget ran out;
    ``depth_cut`` counts elements not walked because of the depth cap (today
    silent elsewhere; defect 14).
    """

    node_count: int = 0
    payload_bytes: int = 0
    script_ms: float = 0.0
    build_ms: float = 0.0
    stitch_ms: float = 0.0
    text_capped: int = 0
    text_budget_hit: bool = False
    depth_cut: int = 0

    def truncations(self) -> tuple[tuple[str, int], ...]:
        """Caps that fired, as ``(kind, count)`` pairs; empty when none did."""
        out: list[tuple[str, int]] = []
        if self.text_capped:
            out.append(("text_cap", self.text_capped))
        if self.text_budget_hit:
            out.append(("text_budget", 1))
        if self.depth_cut:
            out.append(("depth_cap", self.depth_cut))
        return tuple(out)


@dataclass(frozen=True)
class ListingDetectionFacts:
    """Numbers from card detection: the candidate groups and the choice.

    ``group_sizes`` lists every candidate group's size in ranked order (the
    chosen group first); ``chrome_excluded`` counts card-like nodes left out
    because they sit in a navigation, banner, footer or complementary
    landmark.
    """

    candidate_count: int = 0
    chrome_excluded: int = 0
    group_sizes: tuple[int, ...] = ()


@dataclass(frozen=True)
class FormRecord:
    """How one form was read (slice S4): counters and enumerations only.

    Privacy as for the rest of this module: no page text. ``label_sources``
    counts fields per pairing-ladder rung; ``trap_evidence`` counts each
    evidence enumeration behind a trap decision; ``residual_size`` is the
    largest residual pairing problem solved (``m`` = labels + controls);
    ``pairing_truncated`` counts controls left unlabelled because a section
    reached the residual cap (05 section 14: ``m <= 120``).
    """

    controls: int = 0
    fields: int = 0
    groups: int = 0
    group_options: int = 0
    unlabeled: int = 0
    hidden: int = 0
    traps: int = 0
    hidden_labelled: int = 0
    trap_unknown: int = 0
    required: int = 0
    optional: int = 0
    required_unknown: int = 0
    described: int = 0
    duplicate_ids: int = 0
    residual_size: int = 0
    residual_sections: int = 0
    pairing_truncated: int = 0
    label_sources: tuple[tuple[str, int], ...] = ()
    trap_evidence: tuple[tuple[str, int], ...] = ()

    def truncations(self) -> list[tuple[str, int]]:
        """Every cap that fired while the form was read."""
        return [("pairing_cap", self.pairing_truncated)] if self.pairing_truncated else []

    def to_dict(self) -> dict[str, Any]:
        """Plain data for the trace."""
        out: dict[str, Any] = {
            name: getattr(self, name)
            for name in (
                "controls", "fields", "groups", "group_options", "unlabeled",
                "hidden", "traps", "hidden_labelled", "trap_unknown", "required", "optional",
                "required_unknown", "described", "duplicate_ids",
                "residual_size", "residual_sections", "pairing_truncated",
            )
        }
        out["label_sources"] = dict(self.label_sources)
        out["trap_evidence"] = dict(self.trap_evidence)
        out["truncations"] = [list(t) for t in self.truncations()]
        return out


@dataclass(frozen=True)
class CardDecision:
    """One decision about one card. Holds no page text (see module doc)."""

    card_index: int
    stage: DecisionStage
    reason: CardReason
    fate: CardFate | None = None
    resolution_state: str = ""
    candidates: int = 0
    rejections: int = 0
    title_source: TitleSource = TitleSource.NONE
    title_truncated: bool = False
    url_ref: str = ""

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "card": self.card_index,
            "stage": self.stage.value,
            "reason": self.reason.value,
        }
        if self.fate is not None:
            out["fate"] = self.fate.value
        if self.resolution_state:
            out["state"] = self.resolution_state
        if self.candidates:
            out["candidates"] = self.candidates
        if self.rejections:
            out["rejections"] = self.rejections
        if self.title_source is not TitleSource.NONE:
            out["title_source"] = self.title_source.value
        if self.title_truncated:
            out["title_truncated"] = True
        if self.url_ref:
            out["url_ref"] = self.url_ref
        return out


#: Resolution states are an enumeration owned by the port; the record keeps
#: the enumerated value only.
_STATE_VALUES = frozenset({"resolved", "multi_route", "deferred", "no_destination", ""})


@dataclass(frozen=True)
class PageRecord:
    """One pass over one page: observation facts, detection, decisions.

    ``record_level`` and ``identity_level`` are AA's own level labels
    ("detected", "+1", ...), not page text.
    """

    pass_kind: PassKind
    pass_index: int = 0
    page_index: int = -1
    observation: ObservationFacts | None = None
    detection: ListingDetectionFacts | None = None
    record_level: str = ""
    identity_level: str = ""
    identity_attributes: int = 0
    analyze_ms: float = 0.0
    decisions: tuple[CardDecision, ...] = field(default=())

    def __post_init__(self) -> None:
        for decision in self.decisions:
            if decision.resolution_state not in _STATE_VALUES:
                raise ValueError("resolution_state must be an enumerated value")

    def fates(self) -> dict[int, CardDecision]:
        """Map card index to its fate decision."""
        return {
            d.card_index: d for d in self.decisions if d.stage is DecisionStage.FATE
        }

    def counts(self) -> dict[str, int]:
        """L0 counters: decisions per ``stage`` and per ``fate:reason``."""
        out: dict[str, int] = {}
        for d in self.decisions:
            out[d.stage.value] = out.get(d.stage.value, 0) + 1
            if d.fate is not None:
                key = f"{d.fate.value}:{d.reason.value}"
                out[key] = out.get(key, 0) + 1
            elif d.stage is DecisionStage.OPENED:
                key = f"opened:{d.reason.value}"
                out[key] = out.get(key, 0) + 1
        return out

    def to_level(self, level: int) -> dict[str, Any]:
        """Return the L0 (``level=0``) or L1 (``level>=1``) view as plain data."""
        out: dict[str, Any] = {
            "trace_schema": TRACE_SCHEMA,
            "level": 0 if level <= 0 else 1,
            "pass": self.pass_kind.value,
            "pass_index": self.pass_index,
            "page_index": self.page_index,
            "analyze_ms": round(self.analyze_ms, 1),
            "counts": self.counts(),
        }
        if self.observation is not None:
            obs = self.observation
            out["observation"] = {
                "nodes": obs.node_count,
                "bytes": obs.payload_bytes,
                "script_ms": round(obs.script_ms, 1),
                "build_ms": round(obs.build_ms, 1),
                "stitch_ms": round(obs.stitch_ms, 1),
                "truncations": [list(t) for t in obs.truncations()],
            }
        if level <= 0:
            return out
        if self.detection is not None:
            out["detection"] = {
                "candidates": self.detection.candidate_count,
                "chrome_excluded": self.detection.chrome_excluded,
                "group_sizes": list(self.detection.group_sizes),
            }
        out["record_level"] = self.record_level
        out["identity_level"] = self.identity_level
        out["identity_attributes"] = self.identity_attributes
        out["decisions"] = [d.to_dict() for d in self.decisions]
        return out
