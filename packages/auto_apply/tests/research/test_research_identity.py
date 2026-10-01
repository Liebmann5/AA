"""Teeth for research_identity and the aggregator's handling of the salt.

T1: one construction, identical across both call paths, pinned against a
    hand-computed HMAC over the CANONICAL form (and against the retired
    concatenating scheme).
T2: an unset salt is fatal at aggregator construction — observable, named.
T3: blank salts are unset; the literal "default_dev_salt" is a legal salt.
T4: an absent company needs no salt at all — and neither do the placeholder
    display strings producers invent when extraction fails.
T5: legacy (pre-item-4a) company_id values are nulled exactly once; a
    post-migration row survives a second construction.
T6: the canonical form — whitespace, invisible format characters, Unicode
    canonical/compatibility spelling and case all collapse to one id, while
    punctuation and legal-entity forms deliberately stay split.
T7: the LM-02 black-hole scenario, end to end through the real aggregator:
    split variants of one employer merge, placeholder employers vanish from
    the per-company grouping but remain in the per-platform one.
T8: the phantom-identity migration nulls exactly the provable phantom ids,
    once; fresh and pre-4a databases come out clean at user_version 4.
T9: the application path mints an outcome identity only when research is
    enabled, and mints None for placeholder companies when it is.
T10: the absence-token set is exact — extending it merges real names, so
    growing it must be a deliberate, diff-visible act.
"""
from __future__ import annotations

import hashlib
import hmac
import sqlite3
import unicodedata as ud
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from auto_apply.adapters.secondary.research.signal_aggregator import (
    _SCHEMA_SQL,
    ResearchSignalAggregator,
)
from auto_apply.application.workflows.applications_workflow import ApplicationsWorkflow
from auto_apply.domain.models.application_evidence import ApplicationEvidence
from auto_apply.domain.models.job import Job
from auto_apply.domain.ports.research_port import ApplicationOutcomeObservation
from auto_apply.domain.services.research_identity import (
    ResearchSaltError,
    _normalise_company_name,
    compute_company_id,
    resolve_research_salt,
)
from auto_apply.domain.services.signal_detectors.base import ResearchSignal

SALT = "unit-test-salt"


def _hmac_id(name_canonical: str, salt: str = SALT) -> str:
    """Hand-computed identity for an already-canonical name."""
    return hmac.new(
        salt.encode(), name_canonical.encode(), hashlib.sha256
    ).hexdigest()[:16]


# ── T1: one construction, both paths, pinned against a hand-computed HMAC ────


def test_company_id_is_identical_across_call_paths(monkeypatch) -> None:
    """TEETH: the construction is HMAC over the CANONICAL form, not over lower().

    The predecessor of this pin hand-computed HMAC over ``name.lower()`` and
    passed by coincidence: its only input ("Acme Corp") canonicalises to
    "acme corp", so it would have blessed the old construction forever. This
    version pins the canonical form deliberately, with an input where
    lower() and the canonical form differ.
    """
    monkeypatch.setenv("AA_RESEARCH_SALT", SALT)

    expected = _hmac_id("acme corp")
    direct = compute_company_id("Acme Corp")
    assert direct == expected, (
        "the construction drifted — company_id must remain "
        "HMAC-SHA256(key=salt, msg=canonical(name))[:16]"
    )
    # An input where lower() and the canonical form genuinely disagree.
    assert compute_company_id("  Acme   Corp\n") == expected, (
        "the HMAC message is not the canonical form — whitespace variants "
        "must meet at one identity"
    )

    signal = ResearchSignal.create(
        signal_type="GJ-01",
        severity="flag",
        confidence=0.5,
        evidence_text="evidence",
        company_name="Acme Corp",
    )
    assert signal.company_id == direct, (
        "the detector path and the direct path disagree — the fork item 4a "
        "closed has reopened"
    )


def test_company_id_never_matches_the_retired_concat_scheme(monkeypatch) -> None:
    monkeypatch.setenv("AA_RESEARCH_SALT", SALT)
    retired = hashlib.sha256(b"acme corp" + SALT.encode()).hexdigest()[:16]
    assert compute_company_id("Acme Corp") != retired


# ── T2: an unset salt is fatal at construction, observably ───────────────────


def test_unset_salt_is_fatal_at_aggregator_construction(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("AA_RESEARCH_SALT", raising=False)
    with pytest.raises(ResearchSaltError, match="AA_RESEARCH_SALT"):
        ResearchSignalAggregator(db_path=tmp_path / "research.db", consent_version="2.1")


def test_disabled_research_needs_no_salt(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("AA_RESEARCH_SALT", raising=False)
    agg = ResearchSignalAggregator(db_path=tmp_path / "research.db", consent_version=None)
    assert not agg.is_enabled


# ── T3: blank is unset; the published literal is not magic ───────────────────


@pytest.mark.parametrize("blank", ["", "   ", "\t \n"])
def test_blank_salt_is_treated_as_unset(monkeypatch, blank: str) -> None:
    monkeypatch.setenv("AA_RESEARCH_SALT", blank)
    with pytest.raises(ResearchSaltError):
        resolve_research_salt()


def test_default_dev_salt_literal_is_not_special_cased(monkeypatch) -> None:
    monkeypatch.setenv("AA_RESEARCH_SALT", "default_dev_salt")
    assert resolve_research_salt() == "default_dev_salt"


# ── T4: absence of a company is not a company named anything ─────────────────


def test_absent_company_returns_none_without_a_salt(monkeypatch) -> None:
    monkeypatch.delenv("AA_RESEARCH_SALT", raising=False)
    assert compute_company_id(None) is None
    assert compute_company_id("") is None


@pytest.mark.parametrize(
    "placeholder",
    [
        "Unknown",   # what eight discovery producers emit when extraction fails
        "unknown",
        "UNKNOWN",
        "N/A",
        "n/a",
        "None",      # str(None), the classic producer accident
        "none",
        "   ",       # truthy: slips the `if not company_name` guard
        "\u00a0",    # a single non-breaking space
        "\u200b",    # a single zero-width space
    ],
)
def test_placeholder_company_returns_none_without_a_salt(monkeypatch, placeholder: str) -> None:
    """TEETH: placeholders mint absence, and do so without touching the salt.

    Every one of these produced a real, joinable company_id before the fix —
    "Unknown" was the phantom employer of LM-02. The salt is deleted from
    the environment so this also pins that absence is recognised before any
    configuration is consulted.
    """
    monkeypatch.delenv("AA_RESEARCH_SALT", raising=False)
    assert compute_company_id(placeholder) is None


def test_real_names_are_not_absence(monkeypatch) -> None:
    """GUARD: the absence rule is exact-match — no length or pattern creep.

    "X" is a real employer (a live run minted single-letter companies from
    avatar tiles; that extraction defect is a separate item). A company
    whose name merely CONTAINS a placeholder word is a company.
    """
    monkeypatch.setenv("AA_RESEARCH_SALT", SALT)
    assert compute_company_id("X") is not None
    assert compute_company_id("Unknown Devices Ltd") is not None
    assert compute_company_id("None Such Enterprises") is not None
    assert compute_company_id("N/A Motors") is not None


# ── T6: the canonical form ────────────────────────────────────────────────────


def test_whitespace_and_format_variants_collapse_to_one_id(monkeypatch) -> None:
    """TEETH: every measured spelling-variant of one name yields one id."""
    monkeypatch.setenv("AA_RESEARCH_SALT", SALT)
    base = compute_company_id("Acme Corp")
    assert base is not None
    variants = [
        "acme corp",
        "ACME CORP",
        "  Acme Corp  ",
        "Acme Corp\n",
        "Acme  Corp",
        "Acme\u00a0Corp",      # non-breaking space
        "Acme\u200b Corp",     # zero-width space
        "Acme\tCorp",
    ]
    for variant in variants:
        assert compute_company_id(variant) == base, repr(variant)


def test_unicode_spelling_variants_collapse_to_one_id(monkeypatch) -> None:
    """TEETH: Unicode canonical/compatibility spellings and case collapse."""
    monkeypatch.setenv("AA_RESEARCH_SALT", SALT)
    nfc = compute_company_id("Nestlé")
    nfd = compute_company_id(ud.normalize("NFD", "Nestlé"))
    assert nfc is not None and nfc == nfd
    assert compute_company_id("Straße") == compute_company_id("STRASSE")
    # Full-width Latin, as typed on CJK input methods, plus an ideographic space.
    assert compute_company_id("Ａｃｍｅ　Ｃｏｒｐ") == compute_company_id("Acme Corp")


def test_canonical_form_is_a_fixed_point__teeth(monkeypatch) -> None:
    """TEETH: the canonical form normalises to itself, and so mints one id.

    Stripping format characters AFTER NFKC left combining marks out of
    canonical order whenever an invisible character sat between them; both
    inputs below were measured non-idempotent under that order, so a name
    and its own canonical form minted two different company_ids.
    """
    monkeypatch.setenv("AA_RESEARCH_SALT", SALT)
    for raw in ("Cafe\u0301\u200b\u0323", "e\u0301\u2060\u0327"):
        once = _normalise_company_name(raw)
        assert _normalise_company_name(once) == once, repr(raw)
        assert compute_company_id(raw) == compute_company_id(once), repr(raw)


@settings(max_examples=500, deadline=None)
@given(st.text(max_size=24))
def test_canonical_form_is_a_fixed_point__guard(name: str) -> None:
    """GUARD: for arbitrary text, normalising twice equals normalising once.

    A guard, not teeth: random text rarely hits the combining-mark case the
    __teeth test pins, so this holds the property against future edits
    rather than proving the original defect.
    """
    once = _normalise_company_name(name)
    assert _normalise_company_name(once) == once


def test_punctuation_and_legal_forms_stay_split(monkeypatch) -> None:
    """GUARD: the accepted under-split, pinned so relaxing it is deliberate.

    These pairs are each distinct identities BY RULING: a false split
    dilutes a truthful count; a false merge fabricates an entity. Suffix
    stripping is jurisdiction-bound and merges different legal persons.
    """
    monkeypatch.setenv("AA_RESEARCH_SALT", SALT)
    base = compute_company_id("Acme Corp")
    assert base is not None
    assert compute_company_id("Acme Corp.") != base
    assert compute_company_id("Acme Corporation") != base
    assert compute_company_id("Acme, Inc.") != compute_company_id("Acme Inc")


# ── T7: the LM-02 black-hole scenario, through the real aggregator ────────────


def test_black_hole_scenario_reports_ground_truth(monkeypatch, tmp_path) -> None:
    """TEETH: ground truth 5 employers / 6 applications; LM-02 must see it.

    Acme arrives twice (once with a trailing newline) and must merge; three
    different employers extraction could not name arrive as "Unknown" and
    must NOT merge — they join the nameless cohort (NULL company_id), which
    the per-company query excludes and the per-platform query keeps; CredX
    arrives as "C", a real (if badly extracted) name, kept as its own row.
    """
    monkeypatch.setenv("AA_RESEARCH_SALT", SALT)
    agg = ResearchSignalAggregator(db_path=tmp_path / "r.db", consent_version="2.1")
    applications = [
        ("Acme Corp", True),
        ("Acme Corp\n", False),
        ("Unknown", False),
        ("Unknown", False),
        ("Unknown", True),
        ("C", False),
    ]
    for seen, ack in applications:
        agg.observe_application_outcome(
            ApplicationOutcomeObservation(
                platform="probe",
                company_id=compute_company_id(seen),
                submitted_date=date.today(),
                acknowledgment_received=ack,
                acknowledgment_date=None,
            )
        )

    records = agg._query_response_rate_records()
    company = {r.entity_id: r for r in records if r.entity_type == "company"}
    acme_id = compute_company_id("Acme Corp")
    credx_id = compute_company_id("C")
    assert set(company) == {acme_id, credx_id}, (
        "the phantom 'Unknown' employer must not appear, and the split "
        "newline variant must have merged"
    )
    assert (company[acme_id].applications_sent, company[acme_id].responses_received) == (2, 1)
    assert (company[credx_id].applications_sent, company[credx_id].responses_received) == (1, 0)

    platform = {r.entity_id: r for r in records if r.entity_type == "platform"}
    assert (platform["probe"].applications_sent, platform["probe"].responses_received) == (6, 2), (
        "nameless outcomes stay in the per-platform denominator — excluded "
        "from the company grouping, not from the corpus"
    )

    conn = sqlite3.connect(str(tmp_path / "r.db"))
    try:
        nulls = conn.execute(
            "SELECT COUNT(*) FROM application_outcomes WHERE company_id IS NULL"
        ).fetchone()[0]
    finally:
        conn.close()
    assert nulls == 3


# ── T5 / T8: the migrations ───────────────────────────────────────────────────


def _seed_legacy_rows(db_path: Path) -> None:
    """Build a pre-item-4a database: schema present, migrations not yet run."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(_SCHEMA_SQL)
        conn.execute(
            "INSERT INTO research_signals "
            "(signal_id, signal_type, severity, confidence, detected_date, company_id) "
            "VALUES (?,?,?,?,?,?)",
            ("sig-1", "GJ-01", "flag", 0.9, date.today().isoformat(), "legacyhmac1234567"),
        )
        conn.execute(
            "INSERT INTO application_outcomes "
            "(outcome_id, platform, submitted_date, company_id) VALUES (?,?,?,?)",
            ("out-1", "linkedin", date.today().isoformat(), "legacyconcat4567"),
        )
        conn.commit()
    finally:
        conn.close()


def test_legacy_company_ids_are_nulled_and_new_rows_survive(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AA_RESEARCH_SALT", SALT)
    db = tmp_path / "research.db"
    _seed_legacy_rows(db)

    ResearchSignalAggregator(db_path=db, consent_version="2.1")
    conn = sqlite3.connect(str(db))
    try:
        assert conn.execute(
            "SELECT company_id FROM research_signals WHERE signal_id='sig-1'"
        ).fetchone()[0] is None
        assert conn.execute(
            "SELECT company_id FROM application_outcomes WHERE outcome_id='out-1'"
        ).fetchone()[0] is None
        # Only the dishonest field was made absent; the row itself survives.
        assert conn.execute(
            "SELECT signal_type FROM research_signals WHERE signal_id='sig-1'"
        ).fetchone()[0] == "GJ-01"
        # A post-migration row must survive a second construction untouched.
        conn.execute(
            "INSERT INTO research_signals "
            "(signal_id, signal_type, severity, confidence, detected_date, company_id) "
            "VALUES (?,?,?,?,?,?)",
            ("sig-2", "ST-01", "concern", 0.8, date.today().isoformat(), "newschemeid12345"),
        )
        conn.commit()
    finally:
        conn.close()

    ResearchSignalAggregator(db_path=db, consent_version="2.1")
    conn = sqlite3.connect(str(db))
    try:
        assert conn.execute(
            "SELECT company_id FROM research_signals WHERE signal_id='sig-2'"
        ).fetchone()[0] == "newschemeid12345"
    finally:
        conn.close()


def _seed_version3_rows(db_path: Path, salt: str) -> dict[str, str]:
    """Build a post-4a, pre-canonical-form database (user_version 3).

    Three kinds of company_id, minted under the retired lower()-only
    construction: the phantom ("unknown"), a real name whose old id equals
    its new id, and a mergeable variant ("acme corp\\n") whose old id the
    new code will never mint again.
    """
    def legacy_id(name: str) -> str:
        return hmac.new(
            salt.encode(), name.lower().encode(), hashlib.sha256
        ).hexdigest()[:16]

    ids = {
        "phantom": legacy_id("unknown"),
        "valid": legacy_id("acme corp"),
        "split": legacy_id("acme corp\n"),
    }
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(_SCHEMA_SQL)
        conn.execute("PRAGMA user_version = 3")
        for signal_id, company_id in (
            ("sig-p", ids["phantom"]),
            ("sig-v", ids["valid"]),
            ("sig-s", ids["split"]),
        ):
            conn.execute(
                "INSERT INTO research_signals "
                "(signal_id, signal_type, severity, confidence, detected_date, company_id) "
                "VALUES (?,?,?,?,?,?)",
                (signal_id, "GJ-01", "flag", 0.9, date.today().isoformat(), company_id),
            )
        conn.execute(
            "INSERT INTO application_outcomes "
            "(outcome_id, platform, submitted_date, company_id) VALUES (?,?,?,?)",
            ("out-p", "probe", date.today().isoformat(), ids["phantom"]),
        )
        conn.commit()
    finally:
        conn.close()
    return ids


def test_phantom_identity_migration_nulls_only_the_phantom(monkeypatch, tmp_path) -> None:
    """TEETH: the v4 migration nulls exactly the provable phantom, once.

    The valid id survives AND equals what the new code mints — join
    continuity across the boundary. The split-variant id survives by ruling
    (truthful about its cohort; unidentifiable as a variant). Everything is
    idempotent.
    """
    monkeypatch.setenv("AA_RESEARCH_SALT", SALT)
    db = tmp_path / "r.db"
    ids = _seed_version3_rows(db, SALT)

    ResearchSignalAggregator(db_path=db, consent_version="2.1")
    conn = sqlite3.connect(str(db))
    try:
        row = lambda sid: conn.execute(
            "SELECT company_id FROM research_signals WHERE signal_id=?", (sid,)
        ).fetchone()[0]
        assert row("sig-p") is None, "the phantom employer must be nulled"
        assert row("sig-v") == ids["valid"]
        assert row("sig-s") == ids["split"], (
            "mergeable variants stay — dead weight, not fabricated data"
        )
        assert ids["valid"] == compute_company_id("Acme Corp"), (
            "a name whose old form equals the canonical form keeps one "
            "continuous identity across the migration"
        )
        assert conn.execute(
            "SELECT company_id FROM application_outcomes WHERE outcome_id='out-p'"
        ).fetchone()[0] is None
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
    finally:
        conn.close()

    # Idempotent: a second construction changes nothing.
    ResearchSignalAggregator(db_path=db, consent_version="2.1")
    conn = sqlite3.connect(str(db))
    try:
        assert conn.execute(
            "SELECT company_id FROM research_signals WHERE signal_id='sig-v'"
        ).fetchone()[0] == ids["valid"]
    finally:
        conn.close()


def test_migration_is_a_noop_on_an_absent_database(monkeypatch, tmp_path) -> None:
    """TEETH on the version stamp (fails before the v4 migration exists),
    GUARD on the no-op: a fresh database runs both migrations as no-ops and
    lands at user_version 4."""
    monkeypatch.setenv("AA_RESEARCH_SALT", SALT)
    db = tmp_path / "fresh.db"
    ResearchSignalAggregator(db_path=db, consent_version="2.1")
    conn = sqlite3.connect(str(db))
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
    finally:
        conn.close()


# ── T9: the application path mints only when research is enabled ──────────────


class _RecordingObserver:
    """ResearchObserverPort-shaped double: records outcome observations."""

    def __init__(self, *, enabled: bool) -> None:
        self._enabled = enabled
        self.outcome_calls: list = []

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def observe_job_posting(self, observation) -> None:
        pass

    def observe_form(self, observation) -> None:
        pass

    def observe_application_outcome(self, observation) -> None:
        self.outcome_calls.append(observation)

    def observe_discovery(self, observation) -> None:
        pass


def _make_workflow(observer: _RecordingObserver) -> ApplicationsWorkflow:
    """An ApplicationsWorkflow with only what _record_application_outcome reads.

    Built via __new__ to bypass the 27-argument constructor; every attribute
    the method touches is set explicitly. Evidence construction mirrors
    run()/model_copy exactly, because those are the verified-valid call
    shapes from production code.
    """
    wf = object.__new__(ApplicationsWorkflow)
    wf._research_observer = observer
    wf._page_analysis_router = None
    wf._last_analysis_tier = None
    wf._current_job = Job(
        title="T", company="Acme Corp", url="https://example.test/j", source="probe"
    )
    wf._job_repo = object()
    wf._session_id = "s"
    wf._event_bus = SimpleNamespace(publish=lambda *a, **k: None)
    wf._pages_navigated = 0
    wf._fields_filled = 0
    wf._gpt4all_invoked = False
    return wf


def _submitted_evidence() -> ApplicationEvidence:
    return ApplicationEvidence(
        attempt_id="s:1",
        pre_submit_url="https://example.test/j",
        page_title_before="T",
    ).model_copy(update={"outcome": "SUBMITTED", "confidence": 0.95})


def test_application_outcome_not_minted_when_research_disabled(monkeypatch) -> None:
    """TEETH: research off -> no mint, no observation — even with a salt set.

    The salt IS set here so minting would succeed if attempted: before the
    fix, this path minted an identity on every application with research
    disabled and handed it to a Null observer. (With the salt unset it
    raised ResearchSaltError into a DEBUG-level swallow instead — same
    defect, quieter.)
    """
    monkeypatch.setenv("AA_RESEARCH_SALT", SALT)
    observer = _RecordingObserver(enabled=False)
    wf = _make_workflow(observer)
    wf._record_application_outcome(_submitted_evidence())
    assert observer.outcome_calls == []


def test_application_outcome_mint_respects_absence_when_enabled(monkeypatch) -> None:
    """TEETH/GUARD: enabled -> mints real names (guard) and None for
    placeholder companies (teeth)."""
    monkeypatch.setenv("AA_RESEARCH_SALT", SALT)
    observer = _RecordingObserver(enabled=True)
    wf = _make_workflow(observer)

    wf._record_application_outcome(_submitted_evidence())
    assert observer.outcome_calls[0].company_id == compute_company_id("Acme Corp")

    wf._current_job = Job(
        title="T2", company="Unknown", url="https://example.test/k", source="probe"
    )
    wf._record_application_outcome(_submitted_evidence())
    assert observer.outcome_calls[1].company_id is None, (
        "an apply-path job whose company is the discovery placeholder must "
        "arrive at the corpus as absence, not as the phantom employer"
    )


# ── T10: the absence-token set is exact ───────────────────────────────────────


def test_absence_token_set_is_exact_and_deliberate() -> None:
    """GUARD/RATCHET: growing this set merges real names into absence.

    Every token here is a measured producer placeholder. Adding one is a
    decision that a string is never a real employer, in every jurisdiction
    AA runs in — it must be a deliberate, diff-visible act, so it is pinned.
    """
    from auto_apply.domain.services.research_identity import ABSENT_COMPANY_TOKENS

    assert ABSENT_COMPANY_TOKENS == frozenset({"unknown", "n/a", "none"})
