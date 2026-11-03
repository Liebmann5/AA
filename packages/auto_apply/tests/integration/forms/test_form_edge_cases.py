"""Edge cases of 12 that the form reader touches, in a real browser (slice S4).

Each page is a small real form read through AA's extraction script. Pins
marked ``_teeth`` fail on the code before slice S4.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.browser

_STYLE = "<style>body{font:16px sans-serif;margin:20px} input,select,textarea{display:block;width:260px}</style>"


def _page(body: str, html_attrs: str = "") -> str:
    return f"<!DOCTYPE html><html {html_attrs}><head>{_STYLE}</head><body>{body}</body></html>"


def test_label_far_above_its_field_is_its_label_and_never_a_trap_teeth(forms) -> None:
    # EC-32: the old rule flagged a field whose label sat more than 50 px above.
    html = _page(
        "<form><div>City of residence</div><div style='height:180px'></div>"
        "<input name=city><div>Country</div><input name=ctry></form>"
    )
    fields = forms.fields_of(forms.read("/far", html))
    city = forms.by_name(fields, "city")
    assert city.label_text == "City of residence"
    assert city.is_honeypot is False and city.trap_verdict == "CLEAR"


def test_right_to_left_form_pairs_labels_on_the_right_teeth(forms) -> None:
    # EC-32, CT-PH-105/201: the start side is the right in RTL.
    row = "<div style='display:flex;gap:12px;margin:8px 0'><span>{label}</span><input name={name} style='width:200px'></div>"
    html = _page(
        "<form>" + row.format(label="الاسم", name="name") + row.format(label="البريد", name="mail") + "</form>",
        "dir=rtl lang=ar",
    )
    fields = forms.fields_of(forms.read("/rtl", html))
    name = forms.by_name(fields, "name")
    assert name.input_node.rtl is True
    assert name.label_text == "الاسم"
    assert forms.by_name(fields, "mail").label_text == "البريد"
    assert name.is_honeypot is False


def test_label_nested_inside_the_field_wrapper(forms) -> None:
    html = _page(
        "<form><div class=field><label>Mobile phone</label><div class=control><input name=phone type=tel></div></div>"
        "<div class=field><label>Postcode</label><div class=control><input name=zip></div></div></form>"
    )
    fields = forms.fields_of(forms.read("/nested", html))
    assert forms.by_name(fields, "phone").label_text == "Mobile phone"
    assert forms.by_name(fields, "zip").label_text == "Postcode"


def test_duplicate_ids_give_the_label_to_the_first_element_only(forms) -> None:
    # CT-PH-185: label[for] names the first element with the id in tree order.
    html = _page(
        "<form><label for=dup>Work email</label><input id=dup name=work>"
        "<div style='height:40px'></div><input id=dup name=personal></form>"
    )
    structure = forms.read("/dup", html)
    fields = forms.fields_of(structure)
    assert forms.by_name(fields, "work").label_text == "Work email"
    assert forms.by_name(fields, "work").label_source == "label-for"
    assert forms.by_name(fields, "personal").label_source != "label-for"
    record = structure.forms[0].record
    assert record is not None and record.duplicate_ids == 2


def test_a_field_with_no_label_stays_unknown_and_is_never_invented(forms) -> None:
    from auto_apply.domain.models.math_webpage import FieldType

    html = _page("<form><label for=a>Email</label><input id=a name=a type=email><input></form>")
    fields = forms.fields_of(forms.read("/nolabel", html))
    bare = [f for f in fields if not f.input_node.get_attribute("name")][0]
    assert bare.label_text == ""
    assert bare.label_source == "none"
    assert bare.inferred_type is FieldType.UNKNOWN
    assert bare.trap_verdict == "UNKNOWN"  # visible and unlabelled: never filled
    assert bare.is_honeypot is False


def test_group_without_legend_takes_the_preceding_question(forms) -> None:
    from auto_apply.domain.models.math_webpage import FieldType

    html = _page(
        "<form><label for=n>Name</label><input id=n name=n>"
        "<p>Are you legally authorized to work in the United States?</p>"
        "<div role=radiogroup><label><input type=radio name=auth value=1> Yes</label>"
        "<label><input type=radio name=auth value=0> No</label></div></form>"
    )
    fields = forms.fields_of(forms.read("/nolegend", html))
    group = forms.by_name(fields, "auth")
    assert group.inferred_type is FieldType.RADIO
    assert group.label_text == "Are you legally authorized to work in the United States?"
    assert group.options == ["Yes", "No"]
    assert group.label_source == "preceding-text"
    assert group.topic is FieldType.WORK_AUTHORIZATION


def test_checkbox_group_with_aria_labelledby_question(forms) -> None:
    from auto_apply.domain.models.math_webpage import FieldType

    html = _page(
        "<form><label for=n>Name</label><input id=n name=n>"
        "<h3 id=q>Which locations interest you?</h3>"
        "<div role=group aria-labelledby=q>"
        "<input type=checkbox id=l1 name=loc1><label for=l1>Chicago</label>"
        "<input type=checkbox id=l2 name=loc2><label for=l2>Remote</label></div></form>"
    )
    fields = forms.fields_of(forms.read("/cbgroup", html))
    group = forms.by_name(fields, "loc1")
    assert group.inferred_type is FieldType.CHECKBOX
    assert group.label_text == "Which locations interest you?"
    assert group.options == ["Chicago", "Remote"]


def test_hidden_required_control_is_reported_hidden_and_required_teeth(forms) -> None:
    # EC-36 (defect 13): a display:none required input used to vanish.
    html = _page(
        "<form><label for=a>Name</label><input id=a name=a required>"
        "<label for=r>Resume</label><input id=r name=resume type=file required style='display:none'>"
        "<button type=button>Upload</button></form>"
    )
    fields = forms.fields_of(forms.read("/hiddenreq", html))
    resume = forms.by_name(fields, "resume")
    assert resume.hidden_reason == "display-none"
    assert resume.requiredness == "REQUIRED"
    assert "value-missing" in resume.required_signals
    # A hidden control with a visible label is a widget's backing input.
    assert resume.is_honeypot is False and "visible-label" in resume.trap_evidence


def test_a_real_trap_is_still_a_trap_with_its_evidence(forms) -> None:
    html = _page(
        "<form><label for=a>Email</label><input id=a name=email type=email>"
        "<label for=b>Name</label><input id=b name=name>"
        "<div style='position:absolute;left:-9999px'><input name=website tabindex=-1 autocomplete=off></div>"
        "</form>"
    )
    structure = forms.read("/trap", html)
    trap = forms.by_name(forms.fields_of(structure), "website")
    assert trap.is_honeypot is True and trap.trap_verdict == "TRAP"
    assert "hidden:off-screen" in trap.trap_evidence
    assert "no-label" in trap.trap_evidence
    record = structure.forms[0].record
    assert record.traps == 1 and dict(record.trap_evidence)["hidden"] == 1


def test_requiredness_signals_in_order(forms) -> None:
    html = _page(
        "<form><p>* indicates a required field</p>"
        "<label for=a>First name *</label><input id=a name=a>"
        "<label for=b>Middle name (optional)</label><input id=b name=b>"
        "<label for=c>Nickname</label><input id=c name=c>"
        "<label for=d>Email</label><input id=d name=d aria-required=true>"
        "<label for=e>Phone (required)</label><input id=e name=e></form>"
    )
    fields = forms.fields_of(forms.read("/req", html))
    first = forms.by_name(fields, "a")
    assert first.requiredness == "REQUIRED" and "asterisk+legend" in first.required_signals
    assert first.label_text == "First name"  # the marker is not part of the label
    assert forms.by_name(fields, "b").requiredness == "OPTIONAL"
    assert forms.by_name(fields, "c").requiredness == "UNKNOWN"
    assert forms.by_name(fields, "d").requiredness == "REQUIRED"
    assert forms.by_name(fields, "e").requiredness == "REQUIRED"


def test_extraction_reads_control_state_without_interacting(forms) -> None:
    html = _page(
        "<form><input name=vis required><input name=gone style='visibility:hidden'>"
        "<input name=clear style='opacity:0'><div hidden><input name=attr></div>"
        "<input name=tiny style='width:1px;height:1px;padding:0;border:0'></form>"
    )
    structure = forms.read("/state", html)
    nodes = {
        n.get_attribute("name"): n
        for n in structure.dom_root.iter_nodes()
        if n.tag == "input"
    }
    assert nodes["vis"].hidden_reason == "" and nodes["vis"].value_missing is True
    assert nodes["gone"].hidden_reason == "visibility-hidden"
    assert nodes["clear"].hidden_reason == "opacity-zero"
    assert nodes["attr"].hidden_reason in ("hidden-attribute", "display-none")
    assert nodes["tiny"].hidden_reason == "zero-size"
