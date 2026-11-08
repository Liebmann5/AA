"""Pins: the end of a session says which engines searched, which searches an
engine answered without their ``site:`` restriction, and why vetting
rejected what it rejected; "Jobs vetted" counts every job vetting judged.

Owner run 2026-11-08: Bing and Indeed sat idle (nothing on screen said
so), Google dropped six restrictions (nothing said so), and nine jobs were
all rejected while the summary read "Jobs vetted: 0". The owner "couldn't
even tell if the other 2 engines ran".
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from auto_apply.application.agent.context import SessionStatistics
from auto_apply.application.agent.event_bus import EventBus
from auto_apply.application.agent.orchestrator import AgentOrchestrator
from auto_apply.application.services.auditing.degradation_detector import (
    SilentDegradationDetector,
)
from auto_apply.application.services.i18n import configure_locale, get_text
from auto_apply.application.services.session_controller import SessionController
from auto_apply.application.workflows.discovery_workflow import (
    DiscoveryWorkflow,
    _DiscoveryStats,
)
from auto_apply.domain.events import Event
from auto_apply.domain.models.session_plan import SessionPlan
from auto_apply.domain.models.session_report import SessionReport
from auto_apply.domain.models.ui_contract import (
    IgnoredRestriction,
    RejectionCount,
    SessionSummary,
    UnsearchedEngine,
    format_discovery_outcome_lines,
)
from auto_apply.domain.services import search_planner


def _controller() -> tuple[SessionController, EventBus]:
    plan = SessionPlan(session_id="transparency-test")
    registry = MagicMock()
    registry.get_session_plan.return_value = plan
    registry.get_active_profile.return_value = MagicMock()
    db = MagicMock()
    db.get_queue_stats.return_value = {
        "pending": 0, "in_progress": 0, "completed": 0,
        "failed": 0, "skipped": 0, "permanently_failed": 0,
    }
    db.get_jobs_by_session.return_value = []
    bus = EventBus()
    orchestrator = MagicMock()
    orchestrator.session_plan = plan
    orchestrator.context.session_id = "transparency-test"
    orchestrator.context.stats = SessionStatistics()
    orchestrator.task_queue = db
    orchestrator.event_bus = bus
    controller = SessionController(registry=registry, db=db, orchestrator=orchestrator)
    controller._check_network_connectivity = lambda: True
    controller._load_discovered_jobs = lambda: ()  # type: ignore[method-assign]
    return controller, bus


def _owners_session(bus: EventBus) -> None:
    """The owner's session of 2026-11-08, as the bus carried it (now)."""
    workflow = DiscoveryWorkflow(
        profile=MagicMock(), providers=[], task_queue=MagicMock(), event_bus=bus,
        dedup=MagicMock(), text_matcher=MagicMock(), plan=SessionPlan(session_id="s"),
    )
    workflow._unused_engines = {"bing": "no_measured_platform", "indeed": "no_site_form"}
    workflow._emit_completion_summary(_DiscoveryStats(raw_found=9, enqueued=9))
    detector = SilentDegradationDetector(None, event_bus=bus)
    detail = "direct URL: 0 of 10 results on jobs.lever.co; typed search: 0 of 9 results on jobs.lever.co"
    detector.mark_restriction_ignored("google", "jobs.lever.co", detail)
    detector.mark_restriction_ignored("google", "jobs.lever.co", detail)  # once only
    for reason in ["ArrivalCheck: landed off platform (x)"] * 5 + [
        "TitleLogicFilter: Low Relevance Score (0.39)"] * 4:
        bus.publish(Event.JOB_VETTED_FAIL, {"job_title": "t", "company": "c",
                                            "fit_score": 0.0, "reason": reason})


def test_the_summary_names_idle_engines_ignored_restrictions_and_rejections_teeth():
    """TEETH: SessionSummary had none of these fields; jobs_vetted was 0."""
    controller, bus = _controller()
    _owners_session(bus)
    summary = controller.summary()
    assert summary.engines_not_searched == (
        UnsearchedEngine(engine="bing", reason="no_measured_platform"),
        UnsearchedEngine(engine="indeed", reason="no_site_form"),
    )
    assert summary.restrictions_ignored == (
        IgnoredRestriction(provider="google", restriction="jobs.lever.co",
                           detail="direct URL: 0 of 10 results on jobs.lever.co; "
                                  "typed search: 0 of 9 results on jobs.lever.co"),
    )
    assert summary.vetting_rejections == (
        RejectionCount(check="ArrivalCheck", count=5),
        RejectionCount(check="TitleLogicFilter", count=4),
    )
    assert summary.jobs_vetted == 9 and summary.jobs_passed_vetting == 0
    assert controller.snapshot().jobs_vetted == 9


def test_a_pass_and_a_rejection_are_both_vetted():
    controller, bus = _controller()
    bus.publish(Event.JOB_VETTED_PASS, {"job_title": "t", "company": "c",
                                        "fit_score": 0.8, "reason": "all_filters_passed"})
    bus.publish(Event.JOB_VETTED_FAIL, {"job_title": "t", "company": "c",
                                        "fit_score": 0.0, "reason": "HardSkillsFilter: skills_gap"})
    summary = controller.summary()
    assert (summary.jobs_vetted, summary.jobs_passed_vetting) == (2, 1)


def test_the_feed_says_what_was_not_searched_and_what_was_ignored():
    controller, bus = _controller()
    _owners_session(bus)
    feed = "\n".join(record.text for record in controller._recent_events)
    assert "not searched: bing, indeed" in feed
    assert "google answered site:jobs.lever.co without the restriction" in feed


def test_the_results_view_explains_it_in_english_and_spanish():
    controller, bus = _controller()
    _owners_session(bus)
    summary = controller.summary()
    try:
        configure_locale(language="en")
        en = "\n".join(format_discovery_outcome_lines(summary, translate=get_text))
        configure_locale(language="es")
        es = "\n".join(format_discovery_outcome_lines(summary, translate=get_text))
    finally:
        configure_locale(language="en")
    assert "Search engines that ran no search this session:" in en
    assert "bing — no enabled platform's site: restriction has been measured on it" in en
    assert "indeed — it has no form for site-restricted searches" in en
    assert "google: site:jobs.lever.co — direct URL: 0 of 10 results" in en
    assert "Vetting rejected 9 of 9 jobs:" in en
    assert "the link did not lead to the posting the results page showed: 5" in en
    assert "Buscadores que no hicieron ninguna búsqueda en esta sesión:" in es
    assert "La evaluación rechazó 9 de 9 empleos:" in es
    assert "Search engines" not in es


def test_an_unknown_reason_or_check_is_shown_as_recorded():
    """A code without a translation is shown as is, never dropped."""
    summary = SessionSummary(
        jobs_vetted=1,
        engines_not_searched=(UnsearchedEngine(engine="duck", reason="new_code"),),
        vetting_rejections=(RejectionCount(check="NewFilter", count=1),),
    )
    configure_locale(language="en")
    text = "\n".join(format_discovery_outcome_lines(summary, translate=get_text))
    assert "duck" in text and "new_code" in text and "NewFilter" in text


@pytest.mark.parametrize("lang", ["en", "es"])
def test_every_reason_code_and_check_has_a_translation(lang):
    """GUARD: a planner reason code or a vetting check added without a
    string would reach the user as a raw code."""
    root = Path(search_planner.__file__).resolve().parents[2] / "resources/locales"
    strings = json.loads((root / f"{lang}.json").read_text(encoding="utf-8"))
    results = strings["searchplan"]["results"]
    codes = {v for k, v in vars(search_planner).items() if k.startswith("UNUSED_")}
    assert codes and codes <= set(results["unsearched_reason"])
    checks = {"ArrivalCheck", "TitleLogicFilter", "RoleAlignmentFilter", "HardSkillsFilter",
              "ExperienceFilter", "LocationLogicFilter", "SpatialLocationFilter",
              "CompanyBlacklistFilter", "ThrottlingFilter"}
    assert checks <= set(results["check"])


def test_the_saved_report_counts_rejections_by_check_teeth():
    """TEETH: SessionReport.jobs_rejected_by_filter had no writer; the saved
    report's "jobs_rejected" was always 0."""
    orch = object.__new__(AgentOrchestrator)
    orch.state_machine = MagicMock()
    orch.context = MagicMock()
    orch._session_report = SessionReport()
    workflow = MagicMock()
    workflow.run.return_value = False
    orch._get_workflow = lambda name: workflow
    orch._get_execution_mode = lambda: None
    job = SimpleNamespace(title="t", company="c",
                          rejection_reason="ArrivalCheck: landed off platform (x)")
    orch._handle_vetting(SimpleNamespace(payload=job))
    orch._handle_vetting(SimpleNamespace(payload=job))
    assert orch._session_report.jobs_rejected_by_filter == 2
    assert orch._session_report.rejection_reasons == {"ArrivalCheck": 2}
