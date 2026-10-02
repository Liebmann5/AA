"""Pins for the CLI research-consent screen and the shared wording module.

Every pin is driven by scripted input (builtins.input patched) with no
terminal, against a consent service over a temporary database — the same
pattern TestCLIControl established for the autonomy control.

Labels are honest per the standing method:
  TEETH — fail against the pre-change tree. For pins in this new file the
  red is an import error (the screen and the wording module did not
  exist); the BEHAVIOUR each pin locks is stated in its docstring, and the
  S2 stop-channel teeth that fail by ASSERTION on the old tree live in
  tests/research/test_research_consent.py.
  GUARD — freezes a property that must not be broken silently.
  COVERAGE — documents behaviour of the new code.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from auto_apply.adapters.primary.cli import research_consent_screen as screen
from auto_apply.adapters.secondary.research.signal_aggregator import (
    ResearchSignalAggregator,
)
from auto_apply.adapters.secondary.research.sqlite_consent_repository import (
    SqliteConsentRepository,
)
from auto_apply.application.services.research_consent import ResearchConsentManager
from auto_apply.domain.constants import CURRENT_CONSENT_VERSION
from auto_apply.domain.models.consent import ConsentRecord
from auto_apply.domain.ports.research_consent_port import (
    PageCopiesState,
    ResearchConsentReason,
    ResearchConsentState,
    ResearchConsentStatus,
)
from auto_apply.domain.services import research_consent_wording as wording


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


class _Script:
    """Scripted stdin: each input() call pops the next answer. Exhaustion
    raises StopIteration inside input, so tests end scripts exactly where
    the EOF they want to simulate should happen — see _install_input."""

    def __init__(self, answers: list[str]) -> None:
        self._answers = iter(answers)
        self.prompts: list[str] = []

    def __call__(self, prompt: str = "") -> str:
        self.prompts.append(prompt)
        try:
            return next(self._answers)
        except StopIteration:
            raise EOFError from None


def _install_input(monkeypatch: pytest.MonkeyPatch, answers: list[str]) -> _Script:
    script = _Script(answers)
    monkeypatch.setattr("builtins.input", script)
    return script


def _service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, salt: bool = True
) -> tuple[ResearchConsentManager, SqliteConsentRepository]:
    """A consent service over a temporary consent database, with the research
    salt set (ACTIVE-capable) unless the pin wants the NO_SALT state."""
    if salt:
        monkeypatch.setenv("AA_RESEARCH_SALT", "cli-screen-salt")
    else:
        monkeypatch.delenv("AA_RESEARCH_SALT", raising=False)
    repo = SqliteConsentRepository(
        consent_db_path=tmp_path / "research_consent.db",
        research_db_path=tmp_path / "research" / "research_signals.db",
        provenance_key_path=tmp_path / "provenance_key.pem",
        page_copies_dir=tmp_path / "research" / "page_copies",
    )
    return ResearchConsentManager(repo), repo


def _write_research_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE t (id INTEGER)")
        conn.execute("INSERT INTO t VALUES (1)")
        conn.commit()
    finally:
        conn.close()


def _status(
    state: ResearchConsentState,
    reason: ResearchConsentReason = ResearchConsentReason.NONE,
    **kw: Any,
) -> ResearchConsentStatus:
    fields: dict[str, Any] = {
        "offered": True,
        "collecting_now": False,
        "consent_version": None,
        "current_version": CURRENT_CONSENT_VERSION,
    }
    fields.update(kw)  # a pin may override any default, e.g. collecting_now
    return ResearchConsentStatus(state=state, reason=reason, **fields)


# ─────────────────────────────────────────────────────────────────────────────
# Grant discipline: blank, EOF, and decline never record anything
# ─────────────────────────────────────────────────────────────────────────────


def test_a_blank_line_never_grants(tmp_path, monkeypatch) -> None:
    """TEETH: '2' then a BLANK agree answer records nothing. A default
    action must never grant (FORK 1 constraint)."""
    service, repo = _service(tmp_path, monkeypatch)
    _install_input(monkeypatch, ["2", ""])
    assert screen.run(service) == 0
    record = repo.load_consent()
    assert record.granted is False
    assert record.granted_at is None


def test_eof_at_the_agree_prompt_never_grants(tmp_path, monkeypatch) -> None:
    """TEETH: the input stream ending AT the agree prompt (Ctrl-D / Ctrl-C)
    is a decline, not a grant."""
    service, repo = _service(tmp_path, monkeypatch)
    _install_input(monkeypatch, ["2"])  # EOF arrives at the agree prompt
    assert screen.run(service) == 0
    assert repo.load_consent().granted is False


def test_a_decline_records_nothing(tmp_path, monkeypatch) -> None:
    """TEETH: 'n' at the agree prompt leaves the consent store untouched —
    no grant, no version, no timestamp."""
    service, repo = _service(tmp_path, monkeypatch)
    _install_input(monkeypatch, ["2", "n"])
    screen.run(service)
    record = repo.load_consent()
    assert record.granted is False
    assert record.consent_version is None
    assert record.granted_at is None


def test_a_grant_records_the_version_the_rendered_dialog_carried(
    tmp_path, monkeypatch
) -> None:
    """TEETH: the dialog is rendered BEFORE grant() is called, and the
    recorded version is the version that dialog carried — the port's
    'what the user saw is what was recorded' contract, pinned end to end."""
    service, repo = _service(tmp_path, monkeypatch)
    names: list[str] = []

    # A real subclass, not MagicMock(wraps=...): on Python 3.12+ an
    # isinstance check against a runtime_checkable Protocol reads attributes
    # statically, and a MagicMock's are dynamic, so the screen's port check
    # would refuse it there while passing on 3.11.
    class _Spy(type(service)):  # type: ignore[misc]
        def consent_dialog(self):  # type: ignore[no-untyped-def]
            names.append("consent_dialog")
            return super().consent_dialog()

        def grant(self):  # type: ignore[no-untyped-def]
            names.append("grant")
            return super().grant()

    spy = _Spy.__new__(_Spy)
    spy.__dict__.update(service.__dict__)
    _install_input(monkeypatch, ["2", "y"])
    screen.run(spy)
    record = repo.load_consent()
    assert record.granted is True
    assert record.consent_version == service.consent_dialog().version
    assert record.consent_version == CURRENT_CONSENT_VERSION
    assert names.index("consent_dialog") < names.index("grant"), (
        "grant() was called before the dialog was rendered"
    )


def test_reconsent_flow_shows_the_old_version_and_updates_the_record(
    tmp_path, monkeypatch, capsys
) -> None:
    """COVERAGE (NEEDS_RECONSENT): the screen names the version the user
    previously agreed to, shows where the changes are recorded (FORK 4's
    substitute for the 'View Changes' link), and a new agreement records
    the CURRENT version."""
    service, repo = _service(tmp_path, monkeypatch)
    repo.save_consent(
        ConsentRecord(
            granted=True,
            consent_version="2.3",
            granted_at=datetime.now(timezone.utc),
        )
    )
    _install_input(monkeypatch, ["2", "y"])
    screen.run(service)
    out = capsys.readouterr().out
    assert "Research Practices Have Been Updated" in out
    assert "2.3" in out
    assert "CHANGELOG.md" in out
    assert repo.load_consent().consent_version == CURRENT_CONSENT_VERSION


# ─────────────────────────────────────────────────────────────────────────────
# Withdrawal: stops a running observer; delete is export-first + typed DELETE
# ─────────────────────────────────────────────────────────────────────────────


def test_a_withdrawal_through_the_screen_stops_a_running_observer(
    tmp_path, monkeypatch
) -> None:
    """TEETH (the S2 measurement driven through the CLI): a running
    aggregator registered with a DIFFERENT consent instance is stopped by
    the screen's withdrawal. Red on the old tree by assertion — the old
    stop channel was per instance."""
    service, repo = _service(tmp_path, monkeypatch)
    service.grant()
    db = tmp_path / "research" / "research_signals.db"
    key = tmp_path / "provenance_key.pem"
    agg = ResearchSignalAggregator(
        db_path=db,
        consent_version=CURRENT_CONSENT_VERSION,
        provenance_key_path=key,
    )
    agg.start()
    # The session's own instance holds the observer; the screen uses another.
    session_side = ResearchConsentManager(
        SqliteConsentRepository(
            consent_db_path=tmp_path / "research_consent.db",
            research_db_path=db,
            provenance_key_path=key,
        )
    )
    session_side.register_observer(agg)
    _install_input(monkeypatch, ["3", "y", "n"])
    try:
        screen.run(service)
    finally:
        session_side.stop_collection()  # idempotent; registry cleanup either way
    assert not agg.is_enabled
    record = repo.load_consent()
    assert record.granted is False
    assert record.withdrawn_at is not None


def test_withdraw_with_delete_offers_export_first_and_purges(
    tmp_path, monkeypatch
) -> None:
    """TEETH (FORK 4 + FORK 5): the delete path offers export BEFORE the
    irreversible step — the consent text promises "export a copy ...
    before deleting it" — then requires the typed DELETE, then purges."""
    service, repo = _service(tmp_path, monkeypatch)
    service.grant()
    db = tmp_path / "research" / "research_signals.db"
    _write_research_db(db)
    monkeypatch.setattr(screen, "RESEARCH_DB_PATH", db)
    exported = MagicMock(
        return_value=SimpleNamespace(
            directory=tmp_path / "bundle",
            format="csv",
            requested_format="csv",
            degraded=False,
            bundle_digest="digest",
        )
    )
    monkeypatch.setattr(screen, "export_research_bundle", exported)
    # withdraw? y / delete? y / export first? y / format: blank = CSV / DELETE
    _install_input(monkeypatch, ["3", "y", "y", "y", "", "DELETE"])
    screen.run(service)
    exported.assert_called_once_with("csv")
    assert not db.exists(), "the purge must delete the research database"
    assert repo.load_consent().withdrawn_at is not None


def test_delete_requires_typing_delete(tmp_path, monkeypatch) -> None:
    """TEETH (FORK 4): anything but the literal DELETE cancels the whole
    withdrawal — nothing is withdrawn, nothing is purged. It cannot be
    undone; the confirmation strength matches profile deletion."""
    service, repo = _service(tmp_path, monkeypatch)
    service.grant()
    db = tmp_path / "research" / "research_signals.db"
    _write_research_db(db)
    monkeypatch.setattr(screen, "RESEARCH_DB_PATH", db)
    _install_input(monkeypatch, ["3", "y", "y", "n", "WRONG"])
    screen.run(service)
    assert repo.load_consent().granted is True
    assert repo.load_consent().withdrawn_at is None
    assert db.exists()


def test_withdraw_when_nothing_was_granted_says_so(
    tmp_path, monkeypatch, capsys
) -> None:
    """GUARD: withdrawing from OFF is a sentence, not an error or a record."""
    service, repo = _service(tmp_path, monkeypatch)
    _install_input(monkeypatch, ["3"])
    screen.run(service)
    assert "no research consent to withdraw" in capsys.readouterr().out
    assert repo.load_consent().granted is False


# ─────────────────────────────────────────────────────────────────────────────
# Page copies through the screen
# ─────────────────────────────────────────────────────────────────────────────


def test_page_copies_on_then_off_with_deletion(tmp_path, monkeypatch) -> None:
    """TEETH (FORK 3): the screen grants page copies only after rendering
    the versioned dialog, and turning them off deletes kept copies by
    default."""
    service, repo = _service(tmp_path, monkeypatch)
    service.grant()
    _install_input(monkeypatch, ["4", "y"])
    screen.run(service)
    assert service.should_copy_pages() is True
    assert repo.load_consent().page_copies_version is not None
    _install_input(monkeypatch, ["4", "y", "y"])
    screen.run(service)
    assert service.should_copy_pages() is False
    assert repo.load_consent().page_copies is False


def test_page_copies_needs_research_consent_first(
    tmp_path, monkeypatch, capsys
) -> None:
    """GUARD (grant_page_copies' own rule, surfaced): with no current
    research consent the screen explains instead of offering — it must
    never reach the manager's ValueError."""
    service, _repo = _service(tmp_path, monkeypatch)
    _install_input(monkeypatch, ["4"])
    screen.run(service)
    assert "research consent first" in capsys.readouterr().out


# ─────────────────────────────────────────────────────────────────────────────
# Export through the screen
# ─────────────────────────────────────────────────────────────────────────────


def test_export_with_no_research_database_says_so(
    tmp_path, monkeypatch, capsys
) -> None:
    """GUARD: export with nothing collected is a sentence, not a traceback
    (the exporter raises for a missing file; the screen checks first)."""
    service, _repo = _service(tmp_path, monkeypatch)
    monkeypatch.setattr(screen, "RESEARCH_DB_PATH", tmp_path / "absent.db")
    _install_input(monkeypatch, ["5"])
    screen.run(service)
    assert "No research data" in capsys.readouterr().out


def test_export_defaults_to_csv_and_prints_the_bundle_path(
    tmp_path, monkeypatch, capsys
) -> None:
    """COVERAGE: a blank format answer means CSV — export carries no consent
    consequence, so a default is honest here — and the result is printed."""
    service, _repo = _service(tmp_path, monkeypatch)
    db = tmp_path / "research" / "research_signals.db"
    _write_research_db(db)
    monkeypatch.setattr(screen, "RESEARCH_DB_PATH", db)
    fake = MagicMock(
        return_value=SimpleNamespace(
            directory=tmp_path / "aa_research_export_x",
            format="csv",
            requested_format="csv",
            degraded=False,
            bundle_digest="abc123",
        )
    )
    monkeypatch.setattr(screen, "export_research_bundle", fake)
    _install_input(monkeypatch, ["5", ""])
    screen.run(service)
    fake.assert_called_once_with("csv")
    out = capsys.readouterr().out
    assert "aa_research_export_x" in out
    assert "abc123" in out


# ─────────────────────────────────────────────────────────────────────────────
# The shared wording: totality and distinctness over every state and reason
# ─────────────────────────────────────────────────────────────────────────────


def test_every_state_and_reason_has_non_empty_distinct_words() -> None:
    """TEETH (S4): pre-change no wording existed at all. Totality: every
    state renders a non-empty headline and detail; the three INACTIVE
    reasons render non-empty, pairwise-distinct details; ACTIVE renders
    differently while collecting vs waiting for the next session."""
    headlines = {
        wording.status_headline(_status(state)) for state in ResearchConsentState
    }
    assert len(headlines) == len(ResearchConsentState)
    assert all(headlines)
    for state in ResearchConsentState:
        assert wording.status_detail(_status(state))
    reason_details = {
        wording.status_detail(_status(ResearchConsentState.INACTIVE, reason))
        for reason in (
            ResearchConsentReason.NO_SALT,
            ResearchConsentReason.ADMIN_PROHIBITED,
            ResearchConsentReason.NOT_OFFERED,
        )
    }
    assert len(reason_details) == 3
    assert all(reason_details)
    assert wording.status_detail(
        _status(ResearchConsentState.ACTIVE, collecting_now=True)
    ) != wording.status_detail(_status(ResearchConsentState.ACTIVE))


def test_every_page_copies_state_has_a_line() -> None:
    """TEETH (S3 + S4): every PageCopiesState renders non-empty, distinct
    text — including the 'on but not copying' rendering."""
    lines = {
        wording.page_copies_line(
            _status(ResearchConsentState.ACTIVE, page_copies=pcs)
        )
        for pcs in PageCopiesState
    }
    assert len(lines) == len(PageCopiesState)
    assert all(lines)


def test_no_salt_screen_says_the_choice_is_remembered(
    tmp_path, monkeypatch, capsys
) -> None:
    """TEETH (S4's most common screen): a grant with no salt lands on
    INACTIVE/NO_SALT — the screen must say nothing is collected AND that
    the choice is remembered and takes effect once the key is present."""
    service, _repo = _service(tmp_path, monkeypatch, salt=False)
    _install_input(monkeypatch, ["2", "y"])
    screen.run(service)
    out = capsys.readouterr().out
    status = service.status()
    assert status.state is ResearchConsentState.INACTIVE
    assert status.reason is ResearchConsentReason.NO_SALT
    assert "nothing is being collected" in out
    assert "remembered" in out
    assert "AA_RESEARCH_SALT" in out


def test_the_screen_prints_the_current_state_in_plain_words(
    tmp_path, monkeypatch, capsys
) -> None:
    """COVERAGE: headline, detail and page-copies line all reach the
    terminal, verbatim from the wording module."""
    service, _repo = _service(tmp_path, monkeypatch)
    _install_input(monkeypatch, [""])  # blank at the menu quits
    assert screen.run(service) == 0
    out = capsys.readouterr().out
    status = service.status()
    assert wording.status_headline(status) in out
    assert wording.status_detail(status) in out
    assert wording.page_copies_line(status) in out
