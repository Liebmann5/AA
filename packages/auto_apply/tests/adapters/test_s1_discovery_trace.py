"""Slice S1 pins: the per-page record (trace, CT-T-018 L0/L1) and LR-6 logging.

Every card a discovery pass sees has exactly one recorded fate with an
enumerated reason; every click is an ``opened`` decision; the L0 and L1 views
carry no text from the page (titles, URLs, hosts, attribute names); and every
URL found, kept or dropped reaches the session log with its reason (LR-6).
``..._teeth`` pins fail at the branch head (no record exists there).
"""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace

from auto_apply.adapters.secondary.discovery.components.page_understanding_extractor import (
    PageUnderstandingExtractor,
)
from auto_apply.domain.models.page_record import (
    CardFate,
    CardReason,
    DecisionStage,
    ListingDetectionFacts,
    ObservationFacts,
    PageRecord,
    PassKind,
)
from auto_apply.domain.ports.page_understanding_port import (
    CardResolutionState,
    JobCardInfo,
    JobUrlCandidate,
    JobUrlRejection,
    SERPStructure,
    SerpResolutionReport,
)

PAGE_URL = "https://search.example/search?q=secret+words"
SECRET_STRINGS = (
    "Clandestine Welder", "Hidden Corp", "careers.secret.example", "secret",
    "data-secret-id", "/job/42", "Privacy",
)


def _cand(url: str, score: float = 1.0) -> JobUrlCandidate:
    return JobUrlCandidate(url=url, original_url=url, anchor_text="Clandestine Welder",
                           score=score, canonical_url=url)


def _cards() -> tuple[JobCardInfo, ...]:
    kept = JobCardInfo(title="Clandestine Welder", company="Hidden Corp",
                       url="https://careers.secret.example/job/42",
                       candidates=(_cand("https://careers.secret.example/job/42"),),
                       resolution_state=CardResolutionState.RESOLVED.value,
                       title_source="heading", card_index=0)
    no_title = JobCardInfo(title="", candidates=(_cand("https://careers.secret.example/job/43"),),
                           resolution_state=CardResolutionState.RESOLVED.value,
                           url="https://careers.secret.example/job/43", card_index=1)
    multi = JobCardInfo(title="Clandestine Welder II",
                        candidates=(_cand("https://a.secret.example/1", 0.2), _cand("https://b.secret.example/2", 0.2)),
                        resolution_state=CardResolutionState.MULTI_ROUTE.value, card_index=2,
                        identity_attribute="data-secret-id", identity_value="v2")
    deferred = JobCardInfo(title="Clandestine Welder III",
                           rejections=(JobUrlRejection("https://search.example/privacy",
                                                       "https://search.example/privacy",
                                                       "dead-end text", ("Privacy",)),),
                           resolution_state=CardResolutionState.DEFERRED.value, card_index=3)
    nothing = JobCardInfo(title="Clandestine Welder IV", card_index=4,
                          resolution_state=CardResolutionState.NO_DESTINATION.value)
    return (kept, no_title, multi, deferred, nothing)


def _structure(cards=None) -> SERPStructure:
    return SERPStructure(
        job_cards=_cards() if cards is None else cards,
        resolution_report=SerpResolutionReport(learned_identity=("data-secret-id",),
                                               record_level="+1", identity_level="+2"),
        observation=ObservationFacts(node_count=900, payload_bytes=50_000, script_ms=12.0,
                                     text_capped=3),
        listing_facts=ListingDetectionFacts(candidate_count=12, chrome_excluded=4,
                                            group_sizes=(5, 3)),
        analyze_ms=4.0,
    )


def _extractor(structure: SERPStructure, **kwargs) -> PageUnderstandingExtractor:
    pu = SimpleNamespace(analyze_serp=lambda ctx: structure)
    browser = SimpleNamespace(current_url=PAGE_URL, title="secret words - Search")
    return PageUnderstandingExtractor(pu, browser, **kwargs)


def _rec(extractor: PageUnderstandingExtractor) -> PageRecord:
    record = extractor.last_page_record
    assert isinstance(record, PageRecord)
    return record


def test_every_card_has_exactly_one_fate_with_a_reason_teeth() -> None:
    extractor = _extractor(_structure())
    jobs = extractor.mine_jobs("Pin")
    record = _rec(extractor)
    assert record.pass_kind is PassKind.HARVEST
    fates = [d for d in record.decisions if d.stage is DecisionStage.FATE]
    found = [d for d in record.decisions if d.stage is DecisionStage.FOUND]
    assert sorted(d.card_index for d in fates) == [0, 1, 2, 3, 4]
    assert sorted(d.card_index for d in found) == [0, 1, 2, 3, 4]
    by_card = {d.card_index: (d.fate, d.reason) for d in fates}
    assert by_card == {
        0: (CardFate.KEPT, CardReason.TITLE_AND_LINK),
        1: (CardFate.DROPPED, CardReason.NO_TITLE),
        2: (CardFate.DEFERRED, CardReason.MULTI_ROUTE),
        3: (CardFate.DEFERRED, CardReason.NO_ELIGIBLE_LINK),
        4: (CardFate.DEFERRED, CardReason.NO_LINK),
    }
    assert len(jobs) == 1
    assert record.to_level(1)["counts"]["kept:title_and_link"] == 1


def test_l0_l1_carry_no_page_text_teeth() -> None:
    extractor = _extractor(_structure())
    extractor.mine_jobs("Pin")
    for level in (0, 1):
        blob = json.dumps(_rec(extractor).to_level(level))
        for secret in SECRET_STRINGS:
            assert secret not in blob, (level, secret)
    l1 = _rec(extractor).to_level(1)
    assert l1["detection"] == {"candidates": 12, "chrome_excluded": 4, "group_sizes": [5, 3]}
    assert l1["observation"]["truncations"] == [["text_cap", 3]]
    assert l1["record_level"] == "+1" and l1["identity_attributes"] == 1
    l0 = _rec(extractor).to_level(0)
    assert "decisions" not in l0 and "detection" not in l0


def test_url_ref_joins_record_to_log_without_holding_the_url() -> None:
    extractor = _extractor(_structure())
    extractor.mine_jobs("Pin")
    kept = _rec(extractor).fates()[0]
    assert len(kept.url_ref) == 16 and "secret" not in kept.url_ref


def test_every_url_is_logged_with_its_reason_lr6(caplog) -> None:
    caplog.set_level(logging.DEBUG, logger="auto_apply")
    extractor = _extractor(_structure())
    extractor.mine_jobs("Pin")
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("discovery url:")]
    for url in ("https://careers.secret.example/job/42", "https://careers.secret.example/job/43",
                "https://a.secret.example/1", "https://b.secret.example/2",
                "https://search.example/privacy"):
        assert any(url in line for line in lines), url
    assert any("outcome=rejected rejection=dead-end text" in line for line in lines)
    assert any("fate=kept reason=title_and_link outcome=selected" in line for line in lines)
    trace_lines = [r for r in caplog.records if r.name == "auto_apply.trace"]
    assert len(trace_lines) == 1
    assert "secret" not in trace_lines[0].getMessage().replace("Pin", "")


def test_empty_list_records_a_pass_with_no_decisions() -> None:
    extractor = _extractor(_structure(cards=()))
    assert extractor.mine_jobs("Pin") == []
    record = _rec(extractor)
    assert record.decisions == () and record.to_level(0)["counts"] == {}


def test_identical_cards_get_one_fate_each() -> None:
    same = JobCardInfo(title="Line Cook", url="https://careers.secret.example/job/1",
                       candidates=(_cand("https://careers.secret.example/job/1"),),
                       resolution_state=CardResolutionState.RESOLVED.value)
    extractor = _extractor(_structure(cards=(same, same, same)))
    extractor.mine_jobs("Pin")
    assert sorted(_rec(extractor).fates()) == [0, 1, 2]


class _Activator:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def activate(self, **kwargs):
        self.calls += 1
        return self.outcomes.pop(0)


def test_click_pass_records_opened_and_one_fate_per_card() -> None:
    extractor = _extractor(_structure(), max_card_activations=1)
    outcome = SimpleNamespace(error="", candidates=(_cand("https://careers.secret.example/job/9", 1.5),),
                              rejections=(), navigated=True, destination_url="")
    extractor._activator = _Activator([outcome])
    jobs = extractor.finalize_harvest("Pin", page_index=0)
    record = _rec(extractor)
    assert record.pass_kind is PassKind.FINALIZE and record.page_index == 0
    fates = record.fates()
    assert sorted(fates) == [0, 1, 2, 3, 4]
    opened = [d for d in record.decisions if d.stage is DecisionStage.OPENED]
    assert [(d.card_index, d.reason) for d in opened] == [(2, CardReason.OPENED_RESOLVED)]
    assert fates[2].fate is CardFate.KEPT
    assert fates[0].reason is CardReason.ALREADY_RESOLVED
    assert fates[1].reason is CardReason.NO_TITLE
    assert fates[3].reason is CardReason.NO_IDENTITY
    assert fates[4].reason is CardReason.NO_IDENTITY
    assert len(jobs) == 1


def test_click_budget_is_a_recorded_reason() -> None:
    cards = tuple(
        JobCardInfo(title=f"Role {i}", resolution_state=CardResolutionState.DEFERRED.value,
                    identity_attribute="data-k", identity_value=f"v{i}", card_index=i)
        for i in range(3)
    )
    extractor = _extractor(_structure(cards=cards), max_card_activations=1)
    nothing = SimpleNamespace(error="", candidates=(), rejections=(), navigated=False,
                              destination_url="")
    extractor._activator = _Activator([nothing])
    extractor.finalize_harvest("Pin", page_index=2)
    reasons = {i: d.reason for i, d in _rec(extractor).fates().items()}
    assert reasons == {0: CardReason.OPENED_NOTHING, 1: CardReason.CLICK_BUDGET,
                       2: CardReason.CLICK_BUDGET}
