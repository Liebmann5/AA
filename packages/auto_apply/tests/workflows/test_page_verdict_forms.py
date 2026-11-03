"""The page verdict on real form shapes (defect 19; EC-40, EC-41, EC-42).

Synthetic recreations of shapes measured in the owner's evidence archive
(environment ``owner``, 2026-11-03): both Ashby application pages were
judged ``CAPTCHA_BLOCK``; a careers home page with a search form, a posting
with a job-search form and a company list page with a search form were
judged ``APPLICATION_FORM``; a careers error page titled "Error | ..." was
``UNKNOWN``. Pins marked ``_teeth`` fail on the code before the change.
"""

from __future__ import annotations

from auto_apply.domain.services.page_assessment import assess_page
from auto_apply.domain.types import PageType

_INVISIBLE_RECAPTCHA = (
    "<iframe title='reCAPTCHA' src='https://www.recaptcha.net/recaptcha/api2/anchor"
    "?ar=1&k=x&size=invisible'></iframe>"
)

_ASHBY_SHAPE = (
    "<html><body><div id='root'><h1>Software Engineer</h1>"
    "<div><label for='n'>Name</label><input id='n' name='n' required></div>"
    "<div><label for='e'>Email</label><input id='e' type='email' required></div>"
    "<div><label for='r'>Resume</label><input id='r' type='file'></div>"
    "<button type='submit'>Submit Application</button></div>"
    + _INVISIBLE_RECAPTCHA + "</body></html>"
)


def test_invisible_recaptcha_on_a_formless_application_is_not_a_gate_teeth() -> None:
    verdict = assess_page(
        url="https://jobs.ashbyhq.com/acme/123/application", title="Apply", html=_ASHBY_SHAPE
    )
    assert verdict.kind is PageType.APPLICATION_FORM
    assert verdict.challenge == "embedded"


def test_formless_text_controls_are_page_content_teeth() -> None:
    html = _ASHBY_SHAPE.replace("<input id='r' type='file'>", "")
    verdict = assess_page(url="https://jobs.example/apply", title="Apply", html=html)
    assert verdict.kind is not PageType.CAPTCHA_BLOCK


def test_a_bare_challenge_is_still_a_gate() -> None:
    html = "<html><body><p>Checking</p>" + _INVISIBLE_RECAPTCHA.replace("invisible", "normal") + "</body></html>"
    assert assess_page(url="https://x.example/", title="", html=html).kind is PageType.CAPTCHA_BLOCK


def test_a_list_page_with_a_search_form_is_not_an_application_form_teeth() -> None:
    html = (
        "<html><body><form role='search' action='/search'><input name='q'>"
        "<input name='location'><select name='radius'><option>25</option></select></form>"
        "<ul>" + "".join(f"<li><a href='/job/{i}'>Job {i}</a></li>" for i in range(12)) + "</ul>"
        "</body></html>"
    )
    verdict = assess_page(url="https://careers.example/search?q=engineer", title="Jobs", html=html)
    assert verdict.kind is PageType.SERP


def test_a_search_form_with_an_upload_is_still_an_application() -> None:
    html = (
        "<html><body><form><input name='q'><input name='l'>"
        "<input type='file' name='resume'></form></body></html>"
    )
    assert assess_page(url="https://x.example/apply", title="", html=html).kind is PageType.APPLICATION_FORM


def test_sign_in_choices_outrank_a_confirmation_phrase_teeth() -> None:
    html = (
        "<html><body><h1>Sign in to apply</h1>"
        "<button>Sign in with Microsoft</button><button>Sign in with LinkedIn</button>"
        "<p>Track your application submitted earlier.</p></body></html>"
    )
    verdict = assess_page(url="https://careers.example/careers/apply?pid=1", title="Apply", html=html)
    assert verdict.kind is PageType.LOGIN_REQUIRED
    assert "sign-in-choices" in verdict.signals


def test_error_title_is_an_error_page_teeth() -> None:
    verdict = assess_page(
        url="https://jobs.example/en_US/externaljobs/Error",
        title="Error | Careers Marketplace - Example",
        html="<html><body><p>Something went wrong.</p></body></html>",
    )
    assert verdict.kind is PageType.ERROR_404


def test_a_title_starting_with_error_as_a_word_is_not_an_error_page() -> None:
    verdict = assess_page(
        url="https://jobs.example/job/1", title="Error Analyst - Example", html="<p>x</p>"
    )
    assert verdict.kind is not PageType.ERROR_404
