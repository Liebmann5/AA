"""Forms: segmentation, purpose, groups, pairing ladder, requiredness, traps, assignment."""

from __future__ import annotations

import itertools
import random

import pytest

from pagecomp import Analyzer, observe_html
from pagecomp.hungarian import assign, assign_partial


def _read(html, url="https://ats.example/apply"):
    an = Analyzer(observe_html(html, url=url), strict=True)
    return an, an.value("forms"), an.value("formread")


def _by_label(reading, text):
    return next(f for f in reading.fields if text in f.label)


def test_formless_spa_form_is_found_and_shrunk_to_its_controls():
    html = ("<body><header><a href=/>Home</a><a href=/jobs>Jobs</a></header>"
            "<div id=app><section><label for=n>Name</label><input id=n>"
            "<label for=e>Email</label><input id=e type=email>"
            "<label for=f>Resume</label><input id=f type=file></section></div></body>")
    an, forms, _ = _read(html)
    formless = [f for f in forms.forms if f.kind == "formless"]
    assert len(formless) == 1
    assert an.obs.doc.tag_name(formless[0].root) == "section"
    assert formless[0].purpose == "application"


def test_lone_control_goes_to_residual_never_dropped():
    html = ("<main>" + "<p><a href=/a>a</a><a href=/b>b</a><a href=/c>c</a></p>" * 3 +
            "<input name=newsletter></main>")
    _, forms, _ = _read(html)
    assert len(forms.controls) == 1
    assert forms.forms[forms.controls[0].form].kind == "residual"


def test_search_box_is_not_an_application_form_ec41():
    _, forms, _ = _read('<form action="/search" role="search"><input name="q"><button>Search</button></form>',
                        url="https://www.google.com/search?q=x")
    assert forms.forms[0].purpose == "search"


def test_radio_group_is_one_question_with_its_legend():
    html = ("<form><fieldset><legend>Are you authorized to work?<span aria-hidden=true> *</span></legend>"
            "<input type=radio name=auth id=y><label for=y>Yes</label>"
            "<input type=radio name=auth id=n><label for=n>No</label></fieldset>"
            "<label for=a>Name *</label><input id=a><label for=b>Nick</label><input id=b></form>")
    _, forms, reading = _read(html)
    assert len(forms.groups) == 1
    q = _by_label(reading, "authorized")
    assert q.kind == "radio" and q.options == ("Yes", "No")
    assert q.field_type == "work_authorization" and q.sensitive
    assert q.required == "REQUIRED", "visual asterisk in an aria-hidden span counts"


def test_pairing_ladder_order():
    html = ('<form><label for=a>By for</label><input id=a>'
            '<label>Wrapped <input id=b></label>'
            '<span id=lb>By labelledby</span><input id=c aria-labelledby=lb>'
            '<input id=d aria-label="By aria-label">'
            '<input id=e placeholder="By placeholder"></form>')
    _, _, reading = _read(html)
    sources = {f.label: f.label_source for f in reading.fields}
    assert sources == {"By for": "label-for", "Wrapped": "wrapping-label",
                       "By labelledby": "aria-labelledby", "By aria-label": "aria-label",
                       "By placeholder": "placeholder"}


def test_residual_pairing_uses_dummy_cost_not_a_bad_label():
    html = "<form><div><div>First name</div><input name=x1></div><div><input name=x2></div></form>"
    _, _, reading = _read(html)
    labels = [f.label for f in reading.fields]
    assert "First name" in labels
    assert reading.fields[1].label != "First name", "one block is not given to two controls"


def test_requiredness_conventions():
    html = ("<form><label for=a>First *</label><input id=a><label for=b>Last *</label><input id=b>"
            "<label for=c>Website</label><input id=c><label for=d>Notes (optional)</label><input id=d>"
            "<label for=e>Native</label><input id=e required></form>")
    _, _, r = _read(html)
    got = {f.label: f.required for f in r.fields}
    assert got == {"First *": "REQUIRED", "Last *": "REQUIRED", "Website": "OPTIONAL",
                   "Notes (optional)": "OPTIONAL", "Native": "REQUIRED"}


def test_lone_asterisk_without_convention_is_unknown_not_optional():
    _, _, r = _read("<form><label for=a>Name *</label><input id=a></form>")
    assert r.fields[0].required == "UNKNOWN"


def test_trap_rules():
    html = ('<form><label for=v>Email</label><input id=v type=email>'
            '<div style="display:none"><input name="hp_website"></div>'
            '<div style="position:absolute;left:-9999px"><label for=h>Phone</label><input id=h></div>'
            '<label for=lb>Please leave this field blank</label><input id=lb>'
            '<input name=nolabel>'
            '<div style="display:none"><input type=file id=f name=resume></div>'
            '<textarea name="g-recaptcha-response" style="display:none"></textarea></form>')
    _, forms, r = _read(html)
    dec = {forms.controls[f.controls[0]].name or forms.controls[f.controls[0]].id: f.decision for f in r.fields}
    assert dec["v"] == "FILL"
    assert dec["hp_website"] == "TRAP"
    assert dec["h"] == "HIDDEN", "hidden but labelled like a real field: decide again later"
    assert dec["lb"] == "TRAP"
    assert dec["nolabel"] == "UNKNOWN", "visible and unlabelled: never filled"
    assert dec["resume"] == "FILL", "file input behind an upload widget"
    assert dec["g-recaptcha-response"] == "SKIP"


def test_combobox_popup_listbox_is_not_a_separate_question():
    html = ('<form><label for=c>Country</label><input id=c role=combobox aria-controls=lst>'
            '<ul id=lst role=listbox><li role=option>US</li></ul></form>')
    _, forms, _ = _read(html)
    assert len(forms.controls) == 1 and forms.controls[0].tag == "input"


def test_long_question_is_not_typed_as_a_name_field():
    _, _, r = _read("<form><label for=q>Please list the names of any friends, family or relatives who work here"
                    "</label><input id=q></form>")
    assert r.fields[0].field_type == "text"


def test_hungarian_matches_brute_force():
    rnd = random.Random(3)
    for n in range(1, 7):
        for _ in range(20):
            m = [[rnd.randint(0, 9) for _ in range(n)] for _ in range(n)]
            col = assign(m)
            best = min(sum(m[i][p[i]] for i in range(n)) for p in itertools.permutations(range(n)))
            assert sum(m[i][col[i]] for i in range(n)) == best


def test_partial_assignment_prefers_none_over_costly():
    assert assign_partial([[1.0, 9.0], [9.0, 9.0]], c0=2.5) == [0, -1]
    with pytest.raises(ValueError):
        assign_partial([[1.0]], c0=0.0)
