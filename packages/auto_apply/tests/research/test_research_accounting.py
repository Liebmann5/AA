"""Item 3 — research accounting leaves the process.

Item 5 counted observation-path failures in ``_failures`` and added
examination totals to get_statistics_summary(); no production code read
either, and only four of the aggregator's swallowing sites counted at all.
Measured on 7f6d847: a failed signal write, a failed discovery write, a
failed lifecycle write, an observation the outcome or discovery path dropped,
and a signal written WITHOUT its provenance signature were each a log line
and nothing else; the session report and both results views said nothing.

Now:
* every site that loses or weakens research data counts it, in records;
* ResearchAccounting separates recorded / lost / degraded, plus corpus
  totals (get_statistics_summary's keys finally have a reader);
* the orchestrator stops the collector at teardown — flushing what is
  queued — and writes the accounting into the saved session report;
* the controller's results view carries it, and the CLI and GUI print the
  same lines.

Each pin's docstring says whether it is TEETH (fails on 7f6d847), a
DIFFERENTIAL, or a GUARD.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from auto_apply.adapters.secondary.research import signal_aggregator
from auto_apply.adapters.secondary.research.signal_aggregator import (
    ResearchSignalAggregator,
    _DetectorExamination,
)
from auto_apply.domain.constants import CURRENT_CONSENT_VERSION, RESEARCH_SCHEMA_VERSION
from auto_apply.domain.models.session_report import SessionReport
from auto_apply.domain.models.ui_contract import ResearchSessionView, SessionSummary
from auto_apply.domain.ports.research_port import (
    ApplicationOutcomeObservation,
    DiscoveryObservation,
    NullResearchObserver,
    ResearchAccounting,
    ResearchSessionPort,
)
from auto_apply.domain.services.signal_detectors import ResearchSignal


@pytest.fixture(autouse=True)
def _bypass_research_salt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same narrow stand-in as the other research pins."""
    monkeypatch.setattr(
        signal_aggregator, "resolve_research_salt", lambda: "test-salt"
    )


def _aggregator(tmp_path: Path, flush: float = 0.05) -> ResearchSignalAggregator:
    return ResearchSignalAggregator(
        db_path=tmp_path / "research" / "r.db",
        consent_version=CURRENT_CONSENT_VERSION,
        flush_interval_seconds=flush,
        macro_signal_interval_seconds=3600.0,
        provenance_key_path=tmp_path / "provenance_key.pem",
    )


def _signal(signal_id: str) -> ResearchSignal:
    return ResearchSignal(
        signal_id=signal_id, signal_type="GJ-01", severity="warning",
        confidence=0.8, evidence_text="e", platform="p", jurisdiction="CA",
        company_id=None, job_category=None, detected_date=date(2026, 10, 2),
        schema_version=RESEARCH_SCHEMA_VERSION, posting_hash=None,
    )


def _examination() -> _DetectorExamination:
    return _DetectorExamination(
        posting_hash=None, platform="p", jurisdiction="CA",
        detectors_roster=("GJ-01",), detectors_fired=0, signals_fired=0,
        detectors_raised=0, outcomes=(),
    )


@contextmanager
def _broken_connection():
    raise sqlite3.OperationalError("disk I/O error")
    yield  # pragma: no cover


# ── what is counted ──────────────────────────────────────────────────────────


def test_recorded_counts_new_rows_not_duplicates(tmp_path: Path) -> None:
    """TEETH — nothing counted what was written. INSERT OR IGNORE collapses a
    repeated signal_id, and a collapsed duplicate is not a new row."""
    agg = _aggregator(tmp_path)
    agg._write_batch([_signal("a"), _signal("b")])
    agg._write_batch([_signal("a")])
    agg._write_discovery_batch([DiscoveryObservation(provider="Bing")])
    agg._write_examination_batch([_examination(), _examination()])
    acc = agg.accounting()
    assert acc.active and acc.complete
    assert dict(acc.recorded) == {
        "research_signals": 2,
        "discovery_pages": 1,
        "detector_examinations": 2,
    }
    assert acc.lost == () and acc.degraded == ()


@pytest.mark.parametrize(
    ("write", "items", "site"),
    [
        ("_write_batch", [_signal("x"), _signal("y"), _signal("z")], "signal_write"),
        (
            "_write_discovery_batch",
            [DiscoveryObservation(), DiscoveryObservation()],
            "discovery_write",
        ),
        ("_write_examination_batch", [_examination()] * 4, "examination_write"),
    ],
)
def test_a_failed_batch_counts_every_record_it_lost(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write: str,
    items: list[Any],
    site: str,
) -> None:
    """TEETH — signal and discovery write failures were a log line only; the
    examination write counted one per BATCH. Lost is counted in records."""
    agg = _aggregator(tmp_path)
    monkeypatch.setattr(agg, "_get_connection", _broken_connection)
    getattr(agg, write)(items)
    assert dict(agg.accounting().lost) == {site: len(items)}
    assert agg.accounting().recorded == ()


def test_outcome_and_discovery_observations_that_fail_are_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TEETH — observe_application_outcome and observe_discovery swallowed
    at debug level without counting."""
    agg = _aggregator(tmp_path)
    monkeypatch.setattr(agg, "_get_connection", _broken_connection)
    agg.observe_application_outcome(ApplicationOutcomeObservation(
        platform="p", company_id=None, submitted_date=date(2026, 10, 2),
    ))

    class _FullQueue:
        def put_nowait(self, item: object) -> None:
            raise RuntimeError("queue full")

        def empty(self) -> bool:
            return True

    monkeypatch.setattr(agg, "_queue", _FullQueue())
    agg.observe_discovery(DiscoveryObservation(provider="Bing"))
    assert dict(agg.accounting().lost) == {
        "observe_application_outcome": 1,
        "observe_discovery": 1,
    }


def test_a_signal_written_without_its_signature_is_degraded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TEETH — with no signer the rows were written unsigned and only a
    debug line said so. The rows are still recorded; the weakness is now
    counted, because a dataset that says "every row signed" must be able to
    say when one is not."""
    agg = _aggregator(tmp_path)
    monkeypatch.setattr(agg, "_ensure_signer", lambda: None)
    agg._write_batch([_signal("u1"), _signal("u2")])
    acc = agg.accounting()
    assert dict(acc.recorded) == {"research_signals": 2}
    assert dict(acc.degraded) == {"signal_unsigned": 2}


def test_degrading_reads_are_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TEETH — a lifecycle lookup or salary percentile that failed let the
    detectors run on less evidence, silently."""
    agg = _aggregator(tmp_path)
    monkeypatch.setattr(agg, "_get_connection", _broken_connection)
    assert agg._load_lifecycle("fp", "p") is None
    assert agg._load_all_lifecycles_for_fingerprint("fp") == []
    assert agg._compute_role_percentile("engineer", 25.0) == (None, 0)
    assert dict(agg.accounting().degraded) == {
        "lifecycle_load": 2,
        "salary_percentile": 1,
    }


def test_corpus_totals_come_from_get_statistics_summary(tmp_path: Path) -> None:
    """TEETH — get_statistics_summary's item-5 keys had no reader; accounting()
    is it, and reports them as corpus totals."""
    agg = _aggregator(tmp_path)
    agg._write_batch([_signal("c1")])
    agg._write_examination_batch([_examination()])
    corpus = dict(agg.accounting().corpus)
    assert corpus["total_signals"] == 1
    assert corpus["examinations"] == 1


def test_counters_are_exact_under_concurrent_producers(tmp_path: Path) -> None:
    """GUARD — producers run on several threads; every update holds the
    counter lock, so no increment is dropped."""
    agg = _aggregator(tmp_path)

    def worker() -> None:
        for _ in range(2000):
            agg._record_failure("observe_discovery")

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert dict(agg.accounting().lost) == {"observe_discovery": 16000}


def test_research_off_reports_inactive() -> None:
    """GUARD — no consent, nothing to account for, and both research-off
    shapes agree."""
    off = ResearchSignalAggregator(db_path=Path("unused.db"), consent_version=None)
    assert off.accounting() == ResearchAccounting()
    assert NullResearchObserver().accounting() == ResearchAccounting()
    assert isinstance(off, ResearchSessionPort)
    assert isinstance(NullResearchObserver(), ResearchSessionPort)


def test_accounting_reports_incomplete_while_still_flushing(tmp_path: Path) -> None:
    """DIFFERENTIAL — read while the daemon still holds queued work, the
    accounting says it is not final; after stop() it is final and counts it."""
    agg = _aggregator(tmp_path, flush=60.0)
    agg.start()
    agg.observe_discovery(DiscoveryObservation(provider="Bing"))
    before = agg.accounting()
    agg.stop()
    after = agg.accounting()
    assert before.complete is False
    assert after.complete is True
    assert dict(after.recorded) == {"discovery_pages": 1}


# ── where it goes ────────────────────────────────────────────────────────────


def _teardown_orchestrator(tmp_path: Path, research: Any) -> Any:
    """Partial orchestrator, the pattern test_browser_lifecycle.py uses: only
    what _teardown touches, plus a REAL SessionReport and research session."""
    from auto_apply.application.agent.orchestrator import AgentOrchestrator

    orch = object.__new__(AgentOrchestrator)
    orch._shutdown_lock = threading.Lock()
    orch._shutdown_complete = False
    orch._workflows = {}
    orch.state_machine = MagicMock()
    orch._browser_monitor = None
    orch._network_monitor = None
    orch._watchdog = None
    orch.checkpoint_manager = MagicMock()
    orch.event_bus = MagicMock()
    orch._driver = None
    orch._session_report = SessionReport(session_id="acct-test", profile_name="p")
    orch.context = SimpleNamespace(
        elapsed_seconds=lambda: 1.0,
        stats=SimpleNamespace(summary_line=lambda: ""),
    )
    orch._research_session = research
    return orch


def test_teardown_flushes_research_and_writes_it_into_the_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TEETH — the saved report had no research section. Teardown stops the
    collector BEFORE writing the report, so an observation still queued (a
    60-second flush interval guarantees it is) is recorded and counted."""
    from auto_apply.application.agent import orchestrator as orch_module

    monkeypatch.setattr(orch_module, "USER_DATA_DIR", tmp_path / "data")
    agg = _aggregator(tmp_path, flush=60.0)
    agg.start()
    agg.observe_discovery(DiscoveryObservation(provider="Bing"))

    orch = _teardown_orchestrator(tmp_path, agg)
    orch.shutdown()

    assert agg.is_enabled is False, "teardown must stop the collector"
    reports = list((tmp_path / "data" / "reports").glob("session_*.json"))
    assert len(reports) == 1
    research = json.loads(reports[0].read_text(encoding="utf-8"))["research"]
    assert research["active"] is True
    assert research["complete"] is True
    assert research["recorded"] == {"discovery_pages": 1}
    assert research["lost"] == {}


def test_a_research_off_report_still_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GUARD — every report carries the section, so "off" is stated, not
    inferred from an absence."""
    from auto_apply.application.agent import orchestrator as orch_module

    monkeypatch.setattr(orch_module, "USER_DATA_DIR", tmp_path / "data")
    orch = _teardown_orchestrator(tmp_path, NullResearchObserver())
    orch.shutdown()
    report = next((tmp_path / "data" / "reports").glob("session_*.json"))
    assert json.loads(report.read_text(encoding="utf-8"))["research"] == {
        "active": False, "complete": True, "recorded": {}, "lost": {},
        "degraded": {}, "corpus": {},
    }


def _lost_view() -> ResearchSessionView:
    return ResearchSessionView(
        active=True, complete=True, recorded=7, lost=3, degraded=2,
        lost_by_site=(("signal_write", 3),),
        degraded_by_site=(("signal_unsigned", 2),),
    )


def test_controller_summary_carries_the_accounting() -> None:
    """TEETH — SessionSummary had no research field; the controller now maps
    the orchestrator's public research_accounting() onto it."""
    from auto_apply.application.services.session_controller import SessionController

    controller = object.__new__(SessionController)
    controller.orchestrator = MagicMock()
    accounting = ResearchAccounting.from_counts(
        complete=True,
        recorded={"research_signals": 5, "discovery_pages": 2},
        lost={"signal_write": 3},
        degraded={"signal_unsigned": 2},
        corpus={},
    )
    controller.orchestrator.research_accounting.return_value = accounting
    assert controller._research_view() == _lost_view()

    # Through the public results view, the path both surfaces read.
    stats = SimpleNamespace(jobs_discovered=0, jobs_vetted=0)
    controller.orchestrator.context.stats = stats
    controller._report = SessionReport()
    idle = SessionSummary().state
    controller._view_state = lambda: idle  # type: ignore[method-assign]
    controller._load_discovered_jobs = lambda: ()  # type: ignore[method-assign]
    controller.autonomy = lambda: False  # type: ignore[method-assign]
    assert controller.summary().research == _lost_view()

    controller.orchestrator.research_accounting.side_effect = RuntimeError("gone")
    assert controller._research_view() == ResearchSessionView()


def test_view_lines_name_what_was_lost_and_stay_silent_when_off() -> None:
    """GUARD — a loss is named with its site and points at the report; an
    off session prints nothing; an unfinished read says so."""
    lines = "\n".join(_lost_view().lines)
    assert "7 record(s) saved" in lines
    assert "3 record(s) could NOT be saved (signal_write 3)" in lines
    assert "2 saved in a weaker form (signal_unsigned 2)" in lines
    assert ResearchSessionView().lines == ()
    unfinished = ResearchSessionView(active=True, complete=False, recorded=1)
    assert "may be low" in unfinished.lines[-1]


def test_cli_prints_the_research_lines(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """TEETH — the CLI results view printed nothing about research."""
    from auto_apply.adapters.primary.cli.startup import CLIStartup

    monkeypatch.setattr("builtins.input", lambda *a, **k: "n")

    controller = MagicMock()
    controller.summary.return_value = SessionSummary(research=_lost_view())
    cli = object.__new__(CLIStartup)
    cli._print_history = lambda c: None  # type: ignore[method-assign]
    cli._offer_results_export = lambda c: None  # type: ignore[method-assign]
    cli._offer_profile_export = lambda c: None  # type: ignore[method-assign]
    cli._print_results(controller)
    out = capsys.readouterr().out
    for line in _lost_view().lines:
        assert line in out


def test_gui_renders_the_same_research_lines() -> None:
    """TEETH — parity (ruling C): the GUI results lines carry exactly the
    lines the CLI prints. Needs Tk to import the GUI module."""
    pytest.importorskip("tkinter")
    from auto_apply.adapters.primary.gui.app import format_results_lines

    lines = format_results_lines(SessionSummary(research=_lost_view()))
    for line in _lost_view().lines:
        assert line in lines
