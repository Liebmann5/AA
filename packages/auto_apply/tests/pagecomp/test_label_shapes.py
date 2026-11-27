"""Names from labels that hold no words (live ATS form, 2026-11-26)."""

from __future__ import annotations

from pathlib import Path

import pytest

from pagecomp import Analyzer, observe_html

FIXTURE = Path(__file__).parents[1] / "fixtures" / "form_engine" / "icon_labels_and_wrapped_radios.html"


def _fields(html: str):
    an = Analyzer(observe_html(html, url="https://ats.example/apply"), strict=True)
    return an.value("formread").fields


def test_the_live_shapes_read_as_the_person_sees_them() -> None:
    got = [(f.kind, f.label, f.field_type, f.required, len(f.controls))
           for f in _fields(FIXTURE.read_text(encoding="utf-8"))]
    assert got == [
        ("single", "*First name", "first_name", "REQUIRED", 1),
        ("single", "*Address", "address", "REQUIRED", 1),
        ("single", "Resume Choose file", "resume", "REQUIRED", 1),
        ("radio", "Do you have a minimum of 3 years of Python experience?", "radio", "REQUIRED", 2),
        ("radio", "Will you now or in the future require visa sponsorship?",
         "sponsorship", "REQUIRED", 2),
    ], got


def test_svg_fallback_text_is_never_part_of_a_name() -> None:
    html = ('<form><label>City <svg><desc>SVGs not supported</desc><title>info</title>'
            '<metadata>x</metadata></svg><input name=c></label></form>')
    assert [f.label for f in _fields(html)] == ["City"]


@pytest.mark.parametrize("empty", ["", "*", " : ", "* "])
def test_a_label_without_words_gives_way_to_aria_labelledby(empty: str) -> None:
    html = (f'<form><span id=n>Portfolio link</span><label>{empty}'
            '<input name=p aria-labelledby=n></label></form>')
    (field,) = _fields(html)
    assert field.label_source == "aria-labelledby"
    assert field.label.endswith("Portfolio link")
    assert field.label.startswith("*") == ("*" in empty)


def test_a_label_with_words_still_wins() -> None:
    html = ('<form><span id=n>Other words</span><label>Portfolio'
            '<input name=p aria-labelledby=n></label></form>')
    (field,) = _fields(html)
    assert (field.label, field.label_source) == ("Portfolio", "wrapping-label")


def test_a_role_box_around_two_native_inputs_is_kept() -> None:
    """Only a box around exactly one native input of its kind is its drawing."""
    html = ('<form><div role=checkbox aria-label="Both"><input type=checkbox name=a>'
            '<input type=checkbox name=b></div></form>')
    kinds = sorted(c.type for c in Analyzer(observe_html(html, url="https://x.example/"),
                                            strict=True).value("forms").controls)
    assert kinds == ["checkbox", "checkbox", "role:checkbox"]
