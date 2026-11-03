"""The five cases of the independent review of form understanding (slice S4).

Each is a small real form, loaded into Chrome and read through AA's real
extraction script and ``MathFormUnderstandingService``. Every pin marked
``_teeth`` failed on the code before slice S4 in the way the review found:

1. help text below a field became the label of the field above it;
2. explicit ``label[for]`` placed far from its control: labels right, but all
   three fields flagged as honeypots;
3. a field labelled only by ``aria-labelledby``: empty label, flagged as a
   honeypot;
4. legitimate names ``extracurricular`` and ``hidden_disability_note``
   flagged as honeypots by substring (``extra``, ``hidden``);
5. a radio question with Yes/No labels: question text lost, typed ``TEXT``.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.browser

_STYLE = "<style>body{font:16px sans-serif;margin:20px} .f{margin:0 0 18px} input{display:block;width:280px}</style>"


def _page(body: str, extra: str = "") -> str:
    return f"<!DOCTYPE html><html><head>{_STYLE}{extra}</head><body>{body}</body></html>"


_CASE_1 = _page(
    "<form>"
    "<div class=f><div>First name</div><input name=first><small>As on your passport</small></div>"
    "<div class=f><div>Last name</div><input name=last><small>As on your passport</small></div>"
    "<div class=f><div>Email</div><input name=email type=email><small>We never share it</small></div>"
    "</form>"
)


def test_case_1_help_text_below_is_a_description_not_a_label_teeth(forms) -> None:
    fields = forms.fields_of(forms.read("/case1", _CASE_1))
    assert forms.by_name(fields, "first").label_text == "First name"
    assert forms.by_name(fields, "last").label_text == "Last name"
    assert forms.by_name(fields, "email").label_text == "Email"
    assert forms.by_name(fields, "first").description == "As on your passport"
    assert forms.by_name(fields, "email").description == "We never share it"
    assert forms.by_name(fields, "first").label_source == "geometry"


_CASE_2 = _page(
    "<form><div style='display:flex;gap:300px'>"
    "<div><label for=a>Given name</label><br><label for=b>Surname</label><br><label for=c>Phone</label></div>"
    "<div><input id=a name=a><input id=b name=b style='margin-top:120px'><input id=c name=c type=tel style='margin-top:240px'></div>"
    "</div></form>"
)


def test_case_2_explicit_labels_far_from_their_controls_are_not_traps_teeth(forms) -> None:
    fields = forms.fields_of(forms.read("/case2", _CASE_2))
    for name, label in (("a", "Given name"), ("b", "Surname"), ("c", "Phone")):
        field = forms.by_name(fields, name)
        assert field.label_text == label
        assert field.is_honeypot is False
        assert field.trap_verdict == "CLEAR"
        assert field.label_source == "label-for"


_CASE_3 = _page(
    "<form><p id=q1>Preferred first name</p><input name=pref aria-labelledby=q1>"
    "<p id=q2>Pronouns</p><input name=pron aria-labelledby=q2></form>"
)


def test_case_3_aria_labelledby_names_the_field_teeth(forms) -> None:
    fields = forms.fields_of(forms.read("/case3", _CASE_3))
    field = forms.by_name(fields, "pref")
    assert field.label_text == "Preferred first name"
    assert field.is_honeypot is False
    assert field.label_source == "aria-labelledby"
    assert forms.by_name(fields, "pron").label_text == "Pronouns"


_CASE_4 = _page(
    "<form><div class=f><label for=x>Extracurricular activities</label>"
    "<input id=x name=extracurricular></div>"
    "<div class=f><label for=h>Anything we should know about a disability?</label>"
    "<textarea id=h name=hidden_disability_note></textarea></div></form>"
)


def test_case_4_trap_like_names_on_visible_labelled_fields_are_not_traps_teeth(forms) -> None:
    fields = forms.fields_of(forms.read("/case4", _CASE_4))
    for name in ("extracurricular", "hidden_disability_note"):
        field = forms.by_name(fields, name)
        assert field.is_honeypot is False, name
        assert field.trap_verdict == "CLEAR"


_CASE_5 = _page(
    "<form><div class=f><label for=n>Name</label><input id=n name=name></div>"
    "<fieldset><legend>Will you now or in the future require visa sponsorship?</legend>"
    "<input type=radio id=y name=sponsor value=yes><label for=y>Yes</label>"
    "<input type=radio id=no name=sponsor value=no><label for=no>No</label>"
    "</fieldset></form>"
)


def test_case_5_radio_group_is_one_question_with_its_options_teeth(forms) -> None:
    from auto_apply.domain.models.math_webpage import FieldType

    fields = forms.fields_of(forms.read("/case5", _CASE_5))
    question = forms.by_name(fields, "sponsor")
    assert question.inferred_type is FieldType.RADIO
    assert question.label_text == "Will you now or in the future require visa sponsorship?"
    assert question.options == ["Yes", "No"]
    assert len(question.option_nodes) == 2
    assert question.topic is FieldType.SPONSORSHIP
    # One field for the question, not one per option.
    assert sum(1 for f in fields if f.input_node.get_attribute("name") == "sponsor") == 1
