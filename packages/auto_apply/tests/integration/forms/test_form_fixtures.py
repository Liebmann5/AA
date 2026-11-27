"""Slice S4 on real application forms from four ATSs (Ashby, Greenhouse, Gem, Eightfold).

Fixtures (``fixtures/``) are rendered pages the owner saved on his own
machine on 2026-11-03 (environment ``owner``, the owner's evidence archive),
with scripts, frames, inline handlers, comments, SVG bodies, external
stylesheets and data URIs removed, so a page renders the same with or
without a network; each file's first line names its source. They are third-party pages and are never committed
(``fixtures/.gitignore``, owner's ruling): a pin whose page is absent skips.
The assertions were checked by hand against each capture's screenshot. They
guard code against regressions; they are never proof of AA's live
behaviour.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.browser

FIXTURES = Path(__file__).parent / "fixtures"


def _load(forms, name: str):
    path = FIXTURES / name
    if not path.is_file():
        pytest.skip(f"{name} is kept on the owner's machine, not committed; absent here.")
    structure = forms.read(f"/{name}", path.read_text(encoding="utf-8"))
    fields = [
        f for f in forms.fields_of(structure)
        if f.input_node.tag != "button"
        and f.input_node.get_attribute("type") not in ("submit", "button")
    ]
    return structure, fields


def _by_label(fields, label: str):
    for field in fields:
        if field.label_text == label:
            return field
    raise AssertionError(f"no field labelled {label!r}: {[f.label_text for f in fields]}")


def test_ashby_tillster_every_visible_question_labelled_and_required(forms) -> None:
    _structure, fields = _load(forms, "ashby_tillster.html")
    visible_questions = (
        "Name", "Email", "Resume", "Phone Number you can be reached at?", "Location",
        "What city and country do you currently reside in?",
        "When can you start a new role?", "What is your current address?",
        "Where are you previously employed? (Company Name)",
    )
    for label in visible_questions:
        field = _by_label(fields, label)
        # Every one carries a red asterisk on the page. "Location" has no
        # required attribute; its asterisk is drawn by the site's external
        # stylesheet (``::after``), which the fixture does not carry, so here
        # nothing says required and the honest answer is UNKNOWN (filled if
        # data exists, else asked). On the live page the marker is read.
        if label == "Location":
            assert field.requiredness == "UNKNOWN"
        else:
            assert field.requiredness == "REQUIRED", label
        assert field.is_honeypot is False
    # The Yes/No question is two buttons over a hidden checkbox.
    work = next(f for f in fields if f.label_text.startswith("Are you authorized to work"))
    # Hidden on the live page; visible here without the site's stylesheet.
    # Either way it is labelled with its question and is never a trap.
    assert work.trap_verdict == "CLEAR" and not work.is_honeypot
    resume = _by_label(fields, "Resume")
    assert resume.input_node.get_attribute("type") == "file" and not resume.is_honeypot
    assert sum(1 for f in fields if f.is_honeypot) == 0


def test_ashby_snowflake_questions_are_groups_with_their_options(forms) -> None:
    from auto_apply.domain.models.math_webpage import FieldType

    _structure, fields = _load(forms, "ashby_snowflake.html")
    for label, count in (("Gender", 3), ("Race", 8), ("Veteran Status", 3)):
        group = _by_label(fields, label)
        assert group.inferred_type is FieldType.RADIO
        assert len(group.option_nodes) == count == len(group.options)
        assert group.label_source == "group-heading"
    for label in ("Full Name", "Email", "Phone Number", "Resume"):
        assert _by_label(fields, label).requiredness == "REQUIRED"
    assert _by_label(fields, "LinkedIn Profile, if available").is_honeypot is False


def test_greenhouse_canopy_labels_and_requiredness(forms) -> None:
    structure, fields = _load(forms, "greenhouse_canopy.html")
    required = ("First Name", "Last Name", "Email", "Phone", "Country", "LinkedIn Profile")
    for label in required:
        assert _by_label(fields, label).requiredness == "REQUIRED", label
    for label in ("Preferred First Name", "Website", "Gender", "Are you Hispanic/Latino?", "Veteran Status"):
        field = _by_label(fields, label)
        assert field.requiredness != "REQUIRED", label
        assert field.is_honeypot is False
    assert all(not f.is_honeypot for f in fields if not f.is_hidden)
    record = structure.forms[0].record
    assert record is not None and record.pairing_truncated == 0


def test_eightfold_john_deere_screening_questions_are_radio_groups(forms) -> None:
    from auto_apply.domain.models.math_webpage import FieldType

    _structure, fields = _load(forms, "eightfold_johndeere.html")
    for label in ("Legal First Name", "Legal Last Name", "Email", "Address Line 1", "City", "Postal Code"):
        assert _by_label(fields, label).requiredness == "REQUIRED", label
    groups = [f for f in fields if f.is_group]
    assert len(groups) == 6
    assert all(g.inferred_type is FieldType.RADIO and len(g.options) == 2 for g in groups)
    adult = next(g for g in groups if g.label_text.startswith("Are you 18 years of age"))
    assert adult.requiredness == "REQUIRED"
    assert sum(1 for f in fields if f.is_honeypot) <= 1  # the reCAPTCHA token field only


def test_gem_questions_without_names_or_fieldsets_are_groups(forms) -> None:
    from auto_apply.domain.models.math_webpage import FieldType

    _structure, fields = _load(forms, "gem_expedition.html")
    for label in ("First name", "Last name", "Email", "Phone number", "Location"):
        assert _by_label(fields, label).requiredness == "REQUIRED", label
    authorization = _by_label(fields, "Work Authorization")
    assert authorization.inferred_type is FieldType.RADIO and len(authorization.options) == 5
    assert authorization.topic is FieldType.WORK_AUTHORIZATION
    relocate = _by_label(fields, "Are you willing to relocate?")
    assert relocate.inferred_type is FieldType.CHECKBOX and relocate.options == ["Yes", "No"]
    clearance = next(f for f in fields if f.label_text.startswith("Please select the U.S.-government"))
    assert len(clearance.options) == 8
    assert sum(1 for f in fields if f.is_honeypot) == 0
