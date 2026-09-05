"""Pins for the documents contract: resume and cover-letter paths, end to end.

Two causes of prose mangling are pinned separately — the model validator and
the settings writer's storage decision — because fixing one alone leaves the
bug live while looking fixed.

Cross-OS portability (R2): relative document values are stored in POSIX form
so a profile written on Windows resolves on Linux and macOS. The resolver
accepts legacy Windows-form values via a raw-first, separator-fallback rule.

Platform scoping: backslash input has two different CORRECT outcomes by OS —
Windows converts it (backslash was the separator), POSIX preserves it
(backslash is a legal filename character). The two outcomes are pinned by two
skipif-scoped pins; CI runs all three operating systems and both must be green.

Pin labels:
    TEETH — verified to fail against the pre-fix tree for the reason stated.
    GUARD — passes on both trees; it freezes behaviour a future "fix" must not
            silently change (characterisation).
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from auto_apply.application.workflows.applications_workflow import (
    ApplicationsWorkflow,
)
from auto_apply.domain.events import Event
from auto_apply.domain.models.job import Job
from auto_apply.domain.models.profile import (
    PersonalInfo,
    is_document_path,
    make_portable_path,
    prepare_cover_letter_for_storage,
)
from auto_apply.domain.models.session_plan import SessionPlan

_JOB = Job(
    title="Software Engineer",
    company="Acme Corp",
    url="https://acme.example.com/apply",
    source="test",
)


def _info(**overrides) -> PersonalInfo:
    data = {
        "first_name": "A",
        "last_name": "B",
        "email": "a@b.com",
        "phone_number": "555-0100",
        "street_address": "1 Main St",
        "city": "Town",
        "state": "ST",
        "zip_code": "00000",
        "resume_path": None,
        "cover_letter": None,
    }
    data.update(overrides)
    return PersonalInfo(**data)


def _workflow(profile) -> ApplicationsWorkflow:
    return ApplicationsWorkflow(
        profile=profile,
        browser=MagicMock(),
        perception_port=None,
        interaction_port=MagicMock(),
        webpage_analyzer=None,
        field_classifier=None,
        semantic_filler=None,
        text_matcher=MagicMock(),
        file_handler=MagicMock(),
        interruption_handler=None,
        dom_observer=None,
        ats_registry=None,
        job_repo=MagicMock(),
        task_queue=MagicMock(),
        event_bus=MagicMock(),
        interrupt_policy=MagicMock(),
        text_generation_port=None,
        browser_lease=None,
        plan=SessionPlan(session_id="test"),
    )


def _failed_payloads(wf: ApplicationsWorkflow) -> list:
    return [
        c.args[1]
        for c in wf._event_bus.publish.call_args_list
        if c.args and c.args[0] is Event.FORM_FIELD_FAILED
    ]


# ─────────────────────────────────────────────────────────────────────────────
# TEETH: resolution through the accessor
# ─────────────────────────────────────────────────────────────────────────────


def test_resume_relative_path_uploads_resolved_absolute_file(tmp_path, monkeypatch):
    """TEETH: "resume.pdf" under a PROFILES_DIR that is not the working
    directory uploads the real absolute file. Fails today — the handler
    receives the bare string."""
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    resume = profiles / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr("auto_apply.domain.config.PROFILES_DIR", profiles)
    other_cwd = tmp_path / "elsewhere"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)

    profile = MagicMock()
    profile.personal_info = _info(resume_path="resume.pdf")
    wf = _workflow(profile)

    field = SimpleNamespace(
        element_type="file", name="resume", label="Resume", is_required=True
    )
    wf._handle_file_uploads(SimpleNamespace(fields=[field]))

    wf._file_handler.upload.assert_called_once_with(field, str(resume))


def test_cover_letter_relative_pdf_uploads_resolved_file(tmp_path, monkeypatch):
    """TEETH: a cover letter stored as a relative .pdf path uploads the
    resolved file."""
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    cover = profiles / "cover.pdf"
    cover.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr("auto_apply.domain.config.PROFILES_DIR", profiles)
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)

    profile = MagicMock()
    profile.personal_info = _info(cover_letter="cover.pdf")
    wf = _workflow(profile)

    field = SimpleNamespace(
        element_type="file", name="cover_letter", label="Cover Letter",
        is_required=False,
    )
    wf._handle_file_uploads(SimpleNamespace(fields=[field]))

    wf._file_handler.upload.assert_called_once_with(field, str(cover))


# ─────────────────────────────────────────────────────────────────────────────
# TEETH: failures become evidence and block the gate
# ─────────────────────────────────────────────────────────────────────────────


def test_required_resume_missing_file_blocks_submission(tmp_path, monkeypatch):
    """TEETH: a required resume field whose file cannot be resolved publishes
    FORM_FIELD_FAILED and blocks the gate. Fails today — swallowed by
    `except Exception`."""
    profiles = tmp_path / "profiles"
    profiles.mkdir()  # note: resume.pdf is NOT created
    monkeypatch.setattr("auto_apply.domain.config.PROFILES_DIR", profiles)

    profile = MagicMock()
    profile.personal_info = _info(resume_path="resume.pdf")
    wf = _workflow(profile)

    field = SimpleNamespace(
        element_type="file", name="resume", label="Resume", is_required=True
    )

    wf._navigate_to_application = MagicMock(side_effect=lambda job, ev: ev)
    wf._detect_login_wall = MagicMock(return_value=False)
    wf._handle_interruptions = MagicMock(return_value=True)
    wf._get_form_structure_with_iframe_fallback = MagicMock(
        return_value=SimpleNamespace(fields=[field])
    )
    wf._classify_all_fields = MagicMock(return_value={})
    wf._lazy_scroll_to_top = MagicMock()
    wf._observe_form_structure = MagicMock()
    wf._navigate_multi_page_flow = MagicMock(return_value=False)
    wf._submit_application = MagicMock()

    evidence = wf.run(_JOB, session_id="test")

    wf._submit_application.assert_not_called()
    assert evidence.outcome == "FAILED_REQUIRED_FIELD"
    assert evidence.submit_clicked is False
    assert _failed_payloads(wf)


def test_resume_unset_required_field_blocks():
    """TEETH (ruling row 2): no resume configured + a required upload field
    blocks. Today the field is silently skipped."""
    profile = MagicMock()
    profile.personal_info = _info(resume_path=None)
    wf = _workflow(profile)

    field = SimpleNamespace(
        element_type="file", name="resume", label="Resume", is_required=True
    )
    wf._handle_file_uploads(SimpleNamespace(fields=[field]))

    assert wf._failed_required_fields
    wf._file_handler.upload.assert_not_called()


def test_set_but_missing_resume_blocks_even_when_field_optional(tmp_path, monkeypatch):
    """TEETH (ruling row 4): a configured resume whose file is gone blocks
    unconditionally, because DOM `required` is a weak signal on upload
    controls while employers discard resume-less applications."""
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    monkeypatch.setattr("auto_apply.domain.config.PROFILES_DIR", profiles)

    profile = MagicMock()
    profile.personal_info = _info(resume_path="resume.pdf")
    wf = _workflow(profile)

    field = SimpleNamespace(
        element_type="file", name="resume", label="Resume", is_required=False
    )
    wf._handle_file_uploads(SimpleNamespace(fields=[field]))

    assert wf._failed_required_fields
    failed = _failed_payloads(wf)
    assert failed
    assert failed[0]["field_type"] == "RESUME"


# ─────────────────────────────────────────────────────────────────────────────
# TEETH: prose round-trips byte-identical — the two causes pinned separately
# ─────────────────────────────────────────────────────────────────────────────


def test_cover_letter_prose_with_url_survives_construction():
    """TEETH (cause 1 — the model validator): constructing PersonalInfo with
    prose containing a URL preserves it. Fails today."""
    prose = "See my work at https://github.com/Liebmann5/AA — thanks!"
    info = _info(cover_letter=prose)
    assert info.cover_letter == prose


def test_cover_letter_prose_with_url_survives_assignment():
    """TEETH (cause 1, second trigger): validate_assignment=True re-runs the
    validator on every assignment. Fails today."""
    info = _info()
    prose = "Portfolio: https://github.com/Liebmann5/AA"
    info.cover_letter = prose
    assert info.cover_letter == prose


def test_writer_storage_normalisation_preserves_prose_with_url():
    """TEETH (cause 2 — the settings writer): the storage decision must not
    pass prose through make_portable_path. Fails today."""
    prose = "Portfolio: https://github.com/Liebmann5/AA"
    assert prepare_cover_letter_for_storage(prose) == prose


def test_cover_letter_prose_fills_byte_identical_through_engine():
    """TEETH: save-then-fill round trip — prose reaches the employer's form
    exactly as written. Fails today on BOTH causes."""
    prose = "Portfolio: https://github.com/Liebmann5/AA"
    stored = prepare_cover_letter_for_storage(prose)
    info = _info(cover_letter=stored)
    assert info.cover_letter == prose

    profile = MagicMock()
    profile.personal_info = info
    wf = _workflow(profile)

    field = SimpleNamespace(
        element_type="text", name="cover_upload",
        label="Upload your cover letter", is_required=False,
    )
    wf._handle_file_uploads(SimpleNamespace(fields=[field]))

    wf._interaction_port.fill.assert_called_once_with(field, prose)


# ─────────────────────────────────────────────────────────────────────────────
# TEETH: the Windows → POSIX round trip, both directions (R2)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.skipif(
    os.name != "nt",
    reason="backslash-to-POSIX conversion only happens on Windows; POSIX "
    "preserves a backslash in a filename (pinned separately below).",
)
def test_validator_normalises_windows_form_input_to_posix():
    """TEETH (Windows-only, storage direction): a value typed with backslashes,
    as a Windows user would type, is stored in POSIX form. The POSIX outcome
    for the same input is different and correct — pinned separately."""
    info = _info(cover_letter="documents\\cover.pdf")
    assert info.cover_letter == "documents/cover.pdf"


@pytest.mark.skipif(
    os.name == "nt",
    reason="a backslash is a legal POSIX filename character, preserved by "
    "as_posix(); this characterisation only holds on POSIX.",
)
def test_validator_preserves_backslash_in_posix_filename():
    """GUARD (POSIX-only characterisation): the same input Windows converts,
    POSIX preserves — a backslash is a legal filename character there, and
    as_posix() only converts the platform separator. This is the correct
    behaviour the module docstring describes, pinned so a future "fix" cannot
    silently start mangling POSIX filenames."""
    info = _info(cover_letter="documents\\cover.pdf")
    assert info.cover_letter == "documents\\cover.pdf"


def test_posix_form_resume_round_trips_through_storage(tmp_path, monkeypatch):
    """TEETH on Windows (validator used to re-mangle the POSIX form to native
    on save); GUARD on POSIX: the POSIX-form value stored by any platform
    resolves to the real file end to end."""
    profiles = tmp_path / "profiles"
    (profiles / "documents").mkdir(parents=True)
    resume = profiles / "documents" / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr("auto_apply.domain.config.PROFILES_DIR", profiles)

    stored = make_portable_path("documents/resume.pdf")
    assert stored == "documents/resume.pdf"

    info = _info(resume_path=stored)
    assert info.resume_path == "documents/resume.pdf"
    assert info.get_resolved_resume_path() == resume


def test_posix_form_cover_letter_round_trips_through_storage(tmp_path, monkeypatch):
    """TEETH on Windows (same re-mangling on the cover-letter path); GUARD on
    POSIX: prepare → validate → resolve finds the file."""
    profiles = tmp_path / "profiles"
    (profiles / "documents").mkdir(parents=True)
    cover = profiles / "documents" / "cover.pdf"
    cover.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr("auto_apply.domain.config.PROFILES_DIR", profiles)

    stored = prepare_cover_letter_for_storage("documents/cover.pdf")
    assert stored == "documents/cover.pdf"

    info = _info(cover_letter=stored)
    assert info.cover_letter == "documents/cover.pdf"
    assert info.get_resolved_cover_letter_path() == cover


def test_resume_resolver_accepts_legacy_windows_form_via_fallback(tmp_path, monkeypatch):
    """TEETH (read direction): a profile written on Windows before the POSIX
    rule stores "documents\\resume.pdf"; the resolver must find the nested
    file. Validation is bypassed (object.__setattr__) so the resolver's
    fallback is what is exercised. Fails today — one literal segment."""
    profiles = tmp_path / "profiles"
    (profiles / "documents").mkdir(parents=True)
    resume = profiles / "documents" / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr("auto_apply.domain.config.PROFILES_DIR", profiles)

    info = _info()
    object.__setattr__(info, "resume_path", "documents\\resume.pdf")
    assert info.get_resolved_resume_path() == resume


def test_cover_letter_resolver_accepts_legacy_windows_form_via_fallback(tmp_path, monkeypatch):
    """TEETH (read direction, cover letter): same legacy Windows-form value,
    same fallback. Fails today."""
    profiles = tmp_path / "profiles"
    (profiles / "documents").mkdir(parents=True)
    cover = profiles / "documents" / "cover.pdf"
    cover.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr("auto_apply.domain.config.PROFILES_DIR", profiles)

    info = _info()
    object.__setattr__(info, "cover_letter", "documents\\cover.pdf")
    assert info.get_resolved_cover_letter_path() == cover


@pytest.mark.skipif(os.name == "nt", reason="backslash is a separator on Windows; the tradeoff only exists on POSIX")
def test_resolver_raw_form_wins_over_windows_form_fallback(tmp_path, monkeypatch):
    """GUARD (the stated tradeoff): on POSIX, a file legitimately NAMED
    'documents\\cover.pdf' (one segment) outranks the nested interpretation.
    The raw form is tried first; the Windows-form fallback never shadows a
    POSIX literal filename."""
    profiles = tmp_path / "profiles"
    (profiles / "documents").mkdir(parents=True)
    nested = profiles / "documents" / "cover.pdf"
    nested.write_bytes(b"%PDF-1.4")
    literal = profiles / "documents\\cover.pdf"  # one segment, literal backslash
    literal.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr("auto_apply.domain.config.PROFILES_DIR", profiles)

    info = _info()
    object.__setattr__(info, "cover_letter", "documents\\cover.pdf")
    assert info.get_resolved_cover_letter_path() == literal


# ─────────────────────────────────────────────────────────────────────────────
# GUARD pins
# ─────────────────────────────────────────────────────────────────────────────


def test_resume_unset_optional_field_proceeds():
    """GUARD (ruling row 1): no resume configured + an optional upload field
    just proceeds — no block, no failure event."""
    profile = MagicMock()
    profile.personal_info = _info(resume_path=None)
    wf = _workflow(profile)

    field = SimpleNamespace(
        element_type="file", name="resume", label="Resume", is_required=False
    )
    wf._handle_file_uploads(SimpleNamespace(fields=[field]))

    assert wf._failed_required_fields == []
    wf._file_handler.upload.assert_not_called()


@pytest.mark.parametrize(
    "value,expected",
    [
        ("resume.pdf", True),
        ("documents/cover.docx", True),
        ("COVER.PDF", True),
        ("notes.txt", True),
        ("https://example.com/cover.pdf", False),
        ("Portfolio: https://github.com/Liebmann5/AA", False),
        ("Dear team,\nreport.pdf", False),
        ("Dear team, I am a strong fit.", False),
        ("", False),
        (None, False),
    ],
)
def test_is_document_path_predicate(value, expected):
    """GUARD: the single predicate — suffixes (case-insensitive) count as
    paths; URLs, newline-bearing prose and ordinary prose do not."""
    assert is_document_path(value) is expected


def test_get_resolved_cover_letter_path_returns_none_for_prose():
    """GUARD: the accessor's contract — prose is not a file, so None."""
    info = _info(cover_letter="Dear team, see https://example.com for details.")
    assert info.get_resolved_cover_letter_path() is None


def test_validator_preserves_relative_document_path():
    """GUARD: the validator normalises a real document path without breaking
    its portable (relative) POSIX form — on every platform."""
    info = _info(cover_letter="documents/cover.pdf")
    assert info.cover_letter == "documents/cover.pdf"


def test_absolute_document_values_stay_native(tmp_path):
    """GUARD (ruling clause 2): absolute document values are stored native,
    untouched by the POSIX-form normalisation."""
    absolute = tmp_path / "cover.pdf"
    absolute.write_bytes(b"%PDF-1.4")
    info = _info(cover_letter=str(absolute))
    assert info.cover_letter == str(absolute)


def test_make_portable_path_relative_input_unchanged_from_any_cwd(tmp_path, monkeypatch):
    """GUARD (characterisation): a relative input is returned unchanged from
    any working directory. Passes today — pinned so a future "fix" cannot
    silently change it."""
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    monkeypatch.setattr("auto_apply.domain.config.PROFILES_DIR", profiles)
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)

    assert make_portable_path("resume.pdf") == "resume.pdf"
