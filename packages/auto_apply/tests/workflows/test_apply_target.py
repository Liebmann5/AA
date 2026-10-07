"""Teeth pins for the pure apply-target parser (item 12B).

Fixtures are built from the measured shapes in apply_targets.txt (the
off-host jobrapido anchor; the no-target account-gated button; postings
that always carry small forms), with invented hosts — never site markup.
"""
from auto_apply.domain.services.apply_target import (
    auth_dialog_present,
    find_apply_controls,
    page_has_fillable_form,
)


def test_off_host_apply_anchor_is_found_with_resolved_href():
    """The measured jobrapido shape: an <a> "Apply on the website" pointing
    off-host (at a redirector)."""
    html = (
        "<html><body>"
        "<form><input name='q'/></form>"
        '<a href="https://publisher.example/go/123">Apply on the website</a>'
        "</body></html>"
    )
    controls = find_apply_controls(
        url="https://uk.board.example/job/1", html=html
    )
    assert len(controls) == 1
    assert controls[0].href == "https://publisher.example/go/123"
    assert controls[0].off_host is True
    assert controls[0].tag == "a"


def test_join_now_and_dismiss_are_not_apply_controls():
    """The measured sign-in-modal companions must not be followed."""
    html = (
        "<html><body>"
        '<a href="https://board.example/signup">Join now</a>'
        "<button>Dismiss</button>"
        "</body></html>"
    )
    assert find_apply_controls(url="https://board.example/j/1", html=html) == ()


def test_submit_input_is_a_control_with_value_label():
    html = (
        "<html><body><form>"
        '<input type="submit" value="Apply now"/>'
        "</form></body></html>"
    )
    controls = find_apply_controls(url="https://ats.example/apply", html=html)
    assert len(controls) == 1
    assert controls[0].label == "Apply now"


def test_relative_href_resolves_and_stays_on_host():
    html = '<html><body><a href="/apply/9">Apply</a></body></html>'
    controls = find_apply_controls(url="https://ats.example/jobs/9", html=html)
    assert len(controls) == 1
    assert controls[0].href == "https://ats.example/apply/9"
    assert controls[0].off_host is False


def test_javascript_and_fragment_hrefs_are_rejected():
    html = (
        "<html><body>"
        '<a href="javascript:void(0)">Apply</a>'
        '<a href="#apply">Apply</a>'
        "</body></html>"
    )
    controls = find_apply_controls(url="https://x.example/j/1", html=html)
    assert len(controls) == 2
    assert all(c.href == "" for c in controls)


def test_three_control_form_is_fillable():
    html = (
        "<html><body><form>"
        "<input name='a'/><input name='b'/><input name='c'/>"
        "</form></body></html>"
    )
    assert page_has_fillable_form(html) is True


def test_posting_side_forms_are_not_fillable():
    """A posting's search box and sign-in form stay below the bar."""
    html = (
        "<html><body>"
        "<form><input name='q'/></form>"
        "<form><input name='e'/><input type='password' name='p'/></form>"
        f"<p>{'posting text. ' * 50}</p>"
        "</body></html>"
    )
    assert page_has_fillable_form(html) is False


def test_file_input_makes_a_form_fillable():
    html = (
        "<html><body><form>"
        "<input name='a'/><input type='file' name='resume'/>"
        "</form></body></html>"
    )
    assert page_has_fillable_form(html) is True


def test_auth_dialog_with_password_is_detected():
    html = (
        "<html><body>"
        '<div role="dialog"><form>'
        "<input name='session_key'/><input type='password' name='session_password'/>"
        "</form></div>"
        "</body></html>"
    )
    assert auth_dialog_present(html) is True


def test_password_outside_a_dialog_is_not_an_auth_dialog():
    html = (
        "<html><body><form>"
        "<input name='u'/><input type='password' name='p'/>"
        "</form></body></html>"
    )
    assert auth_dialog_present(html) is False


def test_dialog_without_password_is_not_an_auth_dialog():
    """The onsite apply-modal shape: a dialog carrying a form, not a sign-in."""
    html = (
        "<html><body>"
        '<div role="dialog"><form>'
        "<input name='first'/><input name='last'/>"
        "<input name='email'/><input name='phone'/>"
        "</form></div>"
        "</body></html>"
    )
    assert auth_dialog_present(html) is False
