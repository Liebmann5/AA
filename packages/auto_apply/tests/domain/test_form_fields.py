"""Pure-domain pins for the form reader (domain/services/form_fields.py, S4).

Pins marked ``_teeth`` fail on the code before slice S4.
"""

from __future__ import annotations

import time

import pytest

from auto_apply.domain.models.math_dom import DOMNode, Geometry
from auto_apply.domain.services.dom_segmentation import MathFormUnderstandingService


def _input(name: str, y: float, x: float = 200.0, **attrs: str) -> DOMNode:
    pairs = (("name", name),) + tuple(attrs.items())
    return DOMNode(tag="input", attributes=pairs, geometry=Geometry(x, y, 200, 24), depth=2)


def _text(text: str, y: float, x: float = 20.0) -> DOMNode:
    return DOMNode(tag="span", text=text, geometry=Geometry(x, y, 150, 20), depth=2)


def _form(children: list[DOMNode]) -> DOMNode:
    return DOMNode(tag="form", children=tuple(children), geometry=Geometry(0, 0, 900, 9000), depth=1)


def _read(children: list[DOMNode]):
    form = _form(children)
    root = DOMNode(tag="body", children=(form,), geometry=Geometry(0, 0, 900, 9000))
    structure = MathFormUnderstandingService().analyze(root)
    assert structure.forms
    return structure.forms[0]


# ── The residual cap (05 section 14, m <= 120) ─────────────────────────────


def _stacked(count: int) -> list[DOMNode]:
    nodes: list[DOMNode] = []
    for i in range(count):
        nodes.append(_text(f"Question {i}", 30.0 * i))
        nodes.append(_input(f"q{i}", 30.0 * i))
    return nodes


def test_a_form_under_the_cap_is_paired_whole() -> None:
    region = _read(_stacked(40))
    record = region.record
    assert record is not None and record.pairing_truncated == 0
    assert record.residual_size <= 120
    labels = {f.input_node.get_attribute("name"): f.label_text for f in region.all_fields}
    assert labels["q0"] == "Question 0" and labels["q39"] == "Question 39"


def test_a_form_at_the_pairing_cap_is_bounded_and_flagged_teeth() -> None:
    started = time.monotonic()
    region = _read(_stacked(150))
    elapsed = time.monotonic() - started
    record = region.record
    assert record is not None
    assert record.residual_size <= 120
    assert record.pairing_truncated > 0
    assert ("pairing_cap", record.pairing_truncated) in record.truncations()
    assert record.to_dict()["truncations"] == [["pairing_cap", record.pairing_truncated]]
    # Controls past the cap are UNLABELED, never guessed.
    unlabeled = [f for f in region.all_fields if f.label_source == "none"]
    assert len(unlabeled) == record.pairing_truncated
    assert elapsed < 10.0


# ── The trap decision (CT-ALG-014) ─────────────────────────────────────────


_REAL_NAMES = (
    "address2", "attestation", "latest_employer", "extracurricular",
    "email_verification_code", "contest_entry", "hidden_disability_note",
    "fax", "extra_info",
)


@pytest.mark.parametrize("name", _REAL_NAMES)
def test_real_field_names_with_trap_like_substrings_are_not_traps_teeth(name: str) -> None:
    region = _read([_text("Your answer", 0), _input(name, 0), _text("Email", 40), _input("email", 40)])
    field = next(f for f in region.all_fields if f.input_node.get_attribute("name") == name)
    assert field.is_honeypot is False
    assert field.trap_verdict == "CLEAR"


def test_a_trap_token_never_decides_alone() -> None:
    from auto_apply.domain.services.form_fields import _Label, trap_decision

    visible = _input("honeypot_field", 0)
    verdict, evidence = trap_decision(visible, _Label())
    assert verdict == "UNKNOWN" and "trap-token" in evidence


def test_tokens_are_whole_tokens_not_substrings() -> None:
    from auto_apply.domain.services.form_fields import name_tokens

    assert "hp" in name_tokens(_input("hp_field", 0))
    assert "hp" not in name_tokens(_input("hpcareer", 0))
    assert "bot" not in name_tokens(_input("bottom_line", 0))


def test_an_off_screen_unlabelled_control_is_a_trap() -> None:
    region = _read([
        _text("Email", 0), _input("email", 0), _text("Name", 40), _input("name", 40),
        DOMNode(tag="input", attributes=(("name", "url"),), geometry=Geometry(-5000, 0, 100, 20), depth=2),
    ])
    trap = next(f for f in region.all_fields if f.input_node.get_attribute("name") == "url")
    assert trap.trap_verdict == "TRAP" and "hidden:off-screen" in trap.trap_evidence


# ── Requiredness (CT-FR-012) ───────────────────────────────────────────────


def test_requiredness_is_tri_state() -> None:
    from auto_apply.domain.services.form_fields import FormConventions, requiredness

    plain = FormConventions()
    legend = FormConventions(asterisk_legend=True)
    node = _input("a", 0)
    assert requiredness([node], "Name", plain)[0] == "UNKNOWN"
    assert requiredness([node], "Name *", plain)[0] == "UNKNOWN"  # +1.5 alone
    assert requiredness([node], "Name *", legend)[0] == "REQUIRED"
    assert requiredness([node], "Name (optional)", plain)[0] == "OPTIONAL"
    assert requiredness([node], "Not required", plain)[0] == "UNKNOWN"
    assert requiredness([_input("a", 0, required="")], "Name", plain)[0] == "REQUIRED"
    missing = DOMNode(tag="input", attributes=(("name", "a"),), value_missing=True)
    assert requiredness([missing], "", plain) == ("REQUIRED", ("value-missing",))


def test_the_optional_convention_shifts_unmarked_fields() -> None:
    from auto_apply.domain.services.form_fields import FormConventions, requiredness

    convention = FormConventions(optional_convention=True)
    assert requiredness([_input("a", 0)], "Name", convention)[0] == "REQUIRED"


def test_the_form_record_carries_no_page_text() -> None:
    region = _read([_text("Secret label", 0), _input("secret_name", 0), _text("Email", 40), _input("email", 40)])
    flat = repr(region.record.to_dict())
    assert "Secret" not in flat and "secret_name" not in flat
