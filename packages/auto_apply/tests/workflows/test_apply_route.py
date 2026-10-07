"""Teeth pins for the apply route (item 12B + follow-up deliverables 3-4).

A stateful fake browser serves whole pages by URL, so route tests exercise
the real loop in _navigate_to_application — not mocks of its insides. Its
`js_result` attribute stands in for the browser's visibility probe: None
means "probe unavailable" (the fallback path), an int is a verdict.
"""
from unittest.mock import MagicMock

from auto_apply.application.workflows.applications_workflow import ApplicationsWorkflow
from auto_apply.domain.models.session_plan import SessionPlan


class _RouteBrowser:
    """A minimal browser double: get() navigates, page_source serves by URL."""

    def __init__(self, pages: dict, start: str, controls: list | None = None):
        self._pages = dict(pages)
        self.current_url = start
        self.title = ""
        self.get_calls: list[str] = []
        self._controls = list(controls or [])
        self.js_result = None  # what the visibility probe returns; None = unavailable

    @property
    def page_source(self) -> str:
        return self._pages.get(self.current_url, "<html><body></body></html>")

    def set_page(self, url: str, html: str) -> None:
        self._pages[url] = html

    def get(self, url: str) -> None:
        self.get_calls.append(url)
        self.current_url = url

    def find_elements(self, *args, **kwargs) -> list:
        return list(self._controls)

    def execute_script(self, *args, **kwargs):
        return self.js_result

    def switch_to_default_content(self) -> None:
        pass

    def close(self) -> None:
        pass


def _posting_html() -> str:
    """A posting: two one-control side forms, real text, no fillable form."""
    return (
        "<html><head><title>Backend Engineer</title></head><body>"
        "<form><input name='q'/></form>"
        "<form><input name='e'/></form>"
        f"<p>{'Great backend role at a real company. ' * 40}</p>"
        "</body></html>"
    )


def _form_html() -> str:
    """An application form page: one form with three fillable controls."""
    return (
        "<html><head><title>Apply</title></head><body>"
        "<form>"
        "<input name='first'/><input name='last'/><input name='email'/>"
        "</form>"
        "</body></html>"
    )


def _make_route_workflow(
    browser,
    event_bus,
    job_repo,
    task_queue,
    text_matcher,
    interaction_port,
    profile,
) -> ApplicationsWorkflow:
    policy = MagicMock()
    policy.should_pause.return_value = False
    return ApplicationsWorkflow(
        profile=profile,
        browser=browser,
        perception_port=None,
        interaction_port=interaction_port,
        webpage_analyzer=None,
        field_classifier=None,
        semantic_filler=None,
        text_matcher=text_matcher,
        file_handler=None,
        interruption_handler=None,
        dom_observer=None,
        ats_registry=None,
        job_repo=job_repo,
        task_queue=task_queue,
        event_bus=event_bus,
        interrupt_policy=policy,
        text_generation_port=None,
        plan=SessionPlan(session_id="test"),
    )


def _apply_button(label: str = "Apply") -> MagicMock:
    button = MagicMock()
    button.text = label
    button.get_attribute = lambda name: None
    return button


def test_off_host_apply_route_through_one_redirector(
    mock_profile,
    sample_job,
    mock_event_bus,
    mock_job_repo,
    mock_task_queue,
    mock_text_matcher,
    mock_interaction_port,
):
    """TEETH: a posting with 2+ forms and an off-host <a> Apply is FOLLOWED
    — through one redirector — to the target page, starting from vetting's
    learned target (the posting is never reloaded)."""
    redirector = "https://publisher.example/go/123"
    employer = "https://employer.example/apply/9"
    sample_job.url = "https://board.example/posting/1"
    sample_job.metadata["apply_url"] = redirector
    browser = _RouteBrowser(
        pages={
            redirector: (
                "<html><body>"
                f'<a href="{employer}">Apply on the website</a>'
                "<p>Taking you to the employer's site.</p>"
                "</body></html>"
            ),
            employer: _form_html(),
        },
        start=sample_job.url,
    )
    wf = _make_route_workflow(
        browser,
        mock_event_bus,
        mock_job_repo,
        mock_task_queue,
        mock_text_matcher,
        mock_interaction_port,
        mock_profile,
    )

    result = wf.run(sample_job)

    assert browser.get_calls == [redirector, employer]
    assert result.posting_host == "board.example"
    assert result.apply_target_host == "publisher.example"
    assert result.landed_host == "employer.example"
    assert result.apply_route_hops == 1
    assert result.outcome == "FAILED_NO_SUBMIT_BUTTON"


def test_posting_with_off_host_link_is_routed_not_filled(
    mock_profile,
    sample_job,
    mock_event_bus,
    mock_job_repo,
    mock_task_queue,
    mock_text_matcher,
    mock_interaction_port,
):
    """TEETH (follow-up deliverable 3): the measured jobrapido shape — a
    posting whose ALERT form crosses the fillable bar (3 inputs), a second
    form carrying a reCAPTCHA textarea, and an off-host "Apply on the
    website" anchor, with nothing learned at vetting. Form-first ordering
    filled the alert form in place; the posting's own link must win."""
    employer = "https://employer.example/apply/9"
    sample_job.url = "https://board.example/posting/1"
    posting = (
        "<html><body>"
        "<form><input name='a'/><input name='b'/><input name='c'/></form>"
        "<form><div class='g-recaptcha'>"
        "<textarea name='g-recaptcha-response'></textarea></div></form>"
        f'<a href="{employer}">Apply on the website</a>'
        f"<p>{'Backend role, Node.js, London. ' * 40}</p>"
        "</body></html>"
    )
    browser = _RouteBrowser(
        pages={sample_job.url: posting, employer: _form_html()},
        start=sample_job.url,
    )
    wf = _make_route_workflow(
        browser,
        mock_event_bus,
        mock_job_repo,
        mock_task_queue,
        mock_text_matcher,
        mock_interaction_port,
        mock_profile,
    )

    result = wf.run(sample_job)

    assert browser.get_calls == [sample_job.url, employer]
    assert result.landed_host == "employer.example"
    assert result.apply_route_hops == 1
    mock_interaction_port.fill.assert_not_called()
    assert result.outcome == "FAILED_NO_SUBMIT_BUTTON"


def test_apply_opening_a_new_tab_is_followed_and_closed(
    mock_profile,
    sample_job,
    mock_event_bus,
    mock_job_repo,
    mock_task_queue,
    mock_text_matcher,
    mock_interaction_port,
):
    """TEETH: an Apply whose click opens a new tab — AA continues on that
    tab and closes it afterwards."""
    employer = "https://employer.example/apply/9"
    sample_job.url = "https://board.example/posting/1"
    browser = _RouteBrowser(
        pages={sample_job.url: _posting_html(), employer: _form_html()},
        start=sample_job.url,
        controls=[_apply_button()],
    )

    context_manager = MagicMock()

    def _click(_el):
        browser.current_url = "about:blank"

    def _switch():
        browser.current_url = employer
        return True

    mock_interaction_port.click.side_effect = _click
    context_manager.switch_to_new_tab.side_effect = _switch

    wf = _make_route_workflow(
        browser,
        mock_event_bus,
        mock_job_repo,
        mock_task_queue,
        mock_text_matcher,
        mock_interaction_port,
        mock_profile,
    )
    wf._context_manager = context_manager

    result = wf.run(sample_job)

    context_manager.switch_to_new_tab.assert_called_once()
    assert result.landed_host == "employer.example"
    assert result.outcome == "FAILED_NO_SUBMIT_BUTTON"
    context_manager.close_current_tab_and_return.assert_called_once()


def test_account_gated_apply_records_account_required_and_fills_nothing(
    mock_profile,
    sample_job,
    mock_event_bus,
    mock_job_repo,
    mock_task_queue,
    mock_text_matcher,
    mock_interaction_port,
):
    """TEETH: an Apply <button> with no target whose click opens a sign-in
    dialog (fallback path: the dialog was NOT in the pre-click markup, and
    the visibility probe is unavailable)."""
    sample_job.url = "https://board.example/posting/1"
    browser = _RouteBrowser(
        pages={sample_job.url: _posting_html()},
        start=sample_job.url,
        controls=[_apply_button()],
    )

    def _click(_el):
        browser.set_page(
            sample_job.url,
            _posting_html().replace(
                "</body>",
                '<div role="dialog"><form>'
                "<input name='session_key'/>"
                "<input type='password' name='session_password'/>"
                "</form></div></body>",
            ),
        )

    mock_interaction_port.click.side_effect = _click

    wf = _make_route_workflow(
        browser,
        mock_event_bus,
        mock_job_repo,
        mock_task_queue,
        mock_text_matcher,
        mock_interaction_port,
        mock_profile,
    )

    result = wf.run(sample_job)

    assert result.outcome == "ACCOUNT_REQUIRED"
    assert result.login_wall_encountered is True
    assert "account" in (result.error_message or "")
    mock_interaction_port.fill.assert_not_called()


def test_hidden_signin_modal_does_not_block_a_revealed_form(
    mock_profile,
    sample_job,
    mock_event_bus,
    mock_job_repo,
    mock_task_queue,
    mock_text_matcher,
    mock_interaction_port,
):
    """TEETH (follow-up deliverable 4): the measured pre-click shape — a
    hidden sign-in modal ALWAYS in the markup (password inputs on the
    pre-click page). The click reveals an in-page form, and the visibility
    probe says no dialog is shown: NOT ACCOUNT_REQUIRED."""
    sample_job.url = "https://board.example/posting/1"
    hidden_modal = (
        '<div role="dialog" style="display:none"><form>'
        "<input name='session_key'/>"
        "<input type='password' name='session_password'/>"
        "</form></div>"
    )
    posting_with_modal = _posting_html().replace("</body>", hidden_modal + "</body>")
    browser = _RouteBrowser(
        pages={sample_job.url: posting_with_modal},
        start=sample_job.url,
        controls=[_apply_button("Easy Apply")],
    )
    browser.js_result = 0  # the probe: the sign-in dialog is not visible

    def _click(_el):
        browser.set_page(
            sample_job.url,
            posting_with_modal.replace(
                "</body>",
                '<div role="dialog"><form>'
                "<input name='first'/><input name='last'/>"
                "<input name='email'/><input name='phone'/>"
                "</form></div></body>",
            ),
        )

    mock_interaction_port.click.side_effect = _click

    wf = _make_route_workflow(
        browser,
        mock_event_bus,
        mock_job_repo,
        mock_task_queue,
        mock_text_matcher,
        mock_interaction_port,
        mock_profile,
    )

    result = wf.run(sample_job)

    assert result.outcome != "ACCOUNT_REQUIRED"
    assert result.outcome == "FAILED_NO_SUBMIT_BUTTON"  # reached the form stage


def test_visible_signin_dialog_after_click_is_account_required(
    mock_profile,
    sample_job,
    mock_event_bus,
    mock_job_repo,
    mock_task_queue,
    mock_text_matcher,
    mock_interaction_port,
):
    """TEETH (follow-up deliverable 4): the LinkedIn shape — the sign-in
    modal is in the markup before AND after, and the visibility probe says
    it is now SHOWN (the click opened it). ACCOUNT_REQUIRED, nothing filled."""
    sample_job.url = "https://board.example/posting/1"
    modal = (
        '<div role="dialog"><form>'
        "<input name='session_key'/>"
        "<input type='password' name='session_password'/>"
        "</form></div>"
    )
    posting_with_modal = _posting_html().replace("</body>", modal + "</body>")
    browser = _RouteBrowser(
        pages={sample_job.url: posting_with_modal},
        start=sample_job.url,
        controls=[_apply_button()],
    )
    browser.js_result = 1  # the probe: one password field in a visible dialog

    wf = _make_route_workflow(
        browser,
        mock_event_bus,
        mock_job_repo,
        mock_task_queue,
        mock_text_matcher,
        mock_interaction_port,
        mock_profile,
    )

    result = wf.run(sample_job)

    assert result.outcome == "ACCOUNT_REQUIRED"
    assert result.login_wall_encountered is True
    mock_interaction_port.fill.assert_not_called()


def test_onsite_apply_modal_is_proceeded_with_not_account_required(
    mock_profile,
    sample_job,
    mock_event_bus,
    mock_job_repo,
    mock_task_queue,
    mock_text_matcher,
    mock_interaction_port,
):
    """TEETH: the onsite apply-modal shape — a dialog carrying a real form,
    not a sign-in. AA proceeds to fill it."""
    sample_job.url = "https://board.example/posting/1"
    browser = _RouteBrowser(
        pages={sample_job.url: _posting_html()},
        start=sample_job.url,
        controls=[_apply_button("Easy Apply")],
    )

    def _click(_el):
        browser.set_page(
            sample_job.url,
            _posting_html().replace(
                "</body>",
                '<div role="dialog"><form>'
                "<input name='first'/><input name='last'/>"
                "<input name='email'/><input name='phone'/>"
                "</form></div></body>",
            ),
        )

    mock_interaction_port.click.side_effect = _click

    wf = _make_route_workflow(
        browser,
        mock_event_bus,
        mock_job_repo,
        mock_task_queue,
        mock_text_matcher,
        mock_interaction_port,
        mock_profile,
    )

    result = wf.run(sample_job)

    assert result.outcome != "ACCOUNT_REQUIRED"
    assert result.outcome != "CAPTCHA_BLOCKED"
    assert result.outcome == "FAILED_NO_SUBMIT_BUTTON"


def test_redirect_loop_ends_honestly_never_hangs(
    mock_profile,
    sample_job,
    mock_event_bus,
    mock_job_repo,
    mock_task_queue,
    mock_text_matcher,
    mock_interaction_port,
):
    """GUARD: A → B → A. The visited set ends the route honestly."""
    a = "https://a.example/posting"
    b = "https://b.example/go"
    sample_job.url = a
    browser = _RouteBrowser(
        pages={
            a: f'<html><body><a href="{b}">Apply</a></body></html>',
            b: f'<html><body><a href="{a}">Apply</a></body></html>',
        },
        start=a,
    )
    wf = _make_route_workflow(
        browser,
        mock_event_bus,
        mock_job_repo,
        mock_task_queue,
        mock_text_matcher,
        mock_interaction_port,
        mock_profile,
    )

    result = wf.run(sample_job)

    assert result.outcome == "FAILED_NAVIGATION"
    assert "no application form" in (result.error_message or "")
    assert browser.get_calls == [a, b]


def test_hop_bound_ends_with_honest_outcome(
    mock_profile,
    sample_job,
    mock_event_bus,
    mock_job_repo,
    mock_task_queue,
    mock_text_matcher,
    mock_interaction_port,
):
    """GUARD: an endless chain of distinct redirectors stops at the hop
    bound (default 3) with an honest outcome."""
    hosts = [f"https://r{i}.example/go" for i in range(6)]
    sample_job.url = hosts[0]
    pages = {
        hosts[i]: (
            f'<html><body><a href="{hosts[i + 1]}">Apply</a></body></html>'
        )
        for i in range(5)
    }
    browser = _RouteBrowser(pages=pages, start=hosts[0])
    wf = _make_route_workflow(
        browser,
        mock_event_bus,
        mock_job_repo,
        mock_task_queue,
        mock_text_matcher,
        mock_interaction_port,
        mock_profile,
    )

    result = wf.run(sample_job)

    assert result.outcome == "FAILED_NAVIGATION"
    assert "hop bound" in (result.error_message or "")
    assert len(browser.get_calls) == 4  # initial load + 3 hops, then refusal


def test_jsless_fallback_needs_a_dialog_to_appear():
    """GUARD: with no visibility probe (a JS-less driver), a sign-in modal that
    was already in the markup before the click is not a blocking dialog; one
    that appears only after the click is. Inverting this fallback survived
    every other pin."""
    import types

    wf = object.__new__(ApplicationsWorkflow)
    wf._browser = types.SimpleNamespace(execute_script=lambda *a, **k: None)
    empty = "<html><body><p>posting</p></body></html>"
    modal = (
        "<html><body><p>posting</p>"
        "<div role='dialog'><input type='password' name='p'/></div>"
        "</body></html>"
    )
    assert wf._auth_dialog_blocking(before_html=modal, after_html=modal) is False
    assert wf._auth_dialog_blocking(before_html=empty, after_html=modal) is True
