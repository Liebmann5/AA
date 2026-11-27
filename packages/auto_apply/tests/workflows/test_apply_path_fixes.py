"""Teeth pins for the apply-path fixes found in the owner's run 3 (2026-11-03).

Five pasted links (Greenhouse, Ashby, Lever, Workday, SmartRecruiters)
filled no field. The causes pinned here:

1. A known ATS host was treated as "this page is the form", so the route
   stopped on every posting before its Apply control.
2. A same-host apply link (Lever's ``/apply``, Ashby's ``/application``,
   Workday's ``/apply``) was neither followed (only off-host links were) nor
   clicked (controls with a navigable href never are).
3. "Suspicious redirect" was a word count (no ``<form`` and "job" more than
   five times), true on every posting.
4. The submit checkpoint asked "Submit application?" over 0 filled fields.
5. ``_is_safe_fill`` let ``UIElement.get_reference``'s ValueError escape and
   end the whole attempt.
6. The shadow-DOM scan counted light-DOM inputs and returned a marker that
   no filler reads.

Five pins are TEETH (each fails on ``0bed559``); one is a GUARD, labelled.
These are unit guards; the proof is the owner's live re-run of the same
five links.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

from auto_apply.application.workflows.applications_workflow import ApplicationsWorkflow
from auto_apply.domain.events import Event
from auto_apply.domain.models.session_plan import SessionPlan
from auto_apply.domain.models.ui import InteractionType, UIElement

POSTING = "https://jobs.ats.example/acme/123"
APPLY = "https://jobs.ats.example/acme/123/apply"


class _Browser:
    """get() navigates; page_source is served by URL."""

    def __init__(self, pages: dict, start: str):
        self._pages = dict(pages)
        self.current_url = start
        self.title = ""
        self.get_calls: list[str] = []
        self.js_result = None

    @property
    def page_source(self) -> str:
        return self._pages.get(self.current_url, "<html><body></body></html>")

    def get(self, url: str) -> None:
        self.get_calls.append(url)
        self.current_url = url

    def find_elements(self, *args, **kwargs) -> list:
        return []

    def execute_script(self, *args, **kwargs):
        return self.js_result

    def switch_to_default_content(self) -> None:
        pass


def _posting(apply_href: str = APPLY) -> str:
    """An ATS posting: no form, a same-host "Apply for this job" link, and
    the word "job" many times (every real posting trips the old count)."""
    return (
        "<html><head><title>Backend Engineer</title></head><body>"
        f"<p>{'About the job. Job duties. Job benefits. ' * 5}</p>"
        f'<a href="{apply_href}">Apply for this job</a>'
        "</body></html>"
    )


def _form() -> str:
    return (
        "<html><head><title>Apply</title></head><body><form>"
        "<input name='first'/><input name='last'/><input type='email' name='email'/>"
        "</form></body></html>"
    )


def _ats_registry() -> MagicMock:
    registry = MagicMock()
    registry.match.return_value = SimpleNamespace(name="someats")
    registry.is_terminal_page.return_value = False
    return registry


def _workflow(browser, *, pause=False, approval_gate=None, registry=None):
    policy = MagicMock()
    policy.should_pause.return_value = pause
    bus = MagicMock()
    wf = ApplicationsWorkflow(
        profile=MagicMock(),
        browser=browser,
        perception_port=None,
        interaction_port=MagicMock(),
        webpage_analyzer=None,
        field_classifier=None,
        semantic_filler=None,
        text_matcher=MagicMock(),
        file_handler=None,
        interruption_handler=None,
        dom_observer=None,
        ats_registry=registry,
        job_repo=MagicMock(),
        task_queue=MagicMock(),
        event_bus=bus,
        interrupt_policy=policy,
        text_generation_port=None,
        approval_gate=approval_gate,
        plan=SessionPlan(session_id="test"),
    )
    return wf, bus


def _job():
    job = MagicMock()
    job.url = POSTING
    job.title = "Backend Engineer"
    job.company = "Acme"
    job.metadata = {}
    return job


def test_ats_posting_follows_its_same_host_apply_link():
    """TEETH (causes 1 and 2): an ATS posting with a same-host Apply link is
    routed to the apply page. Before: the route stopped on the posting
    (get_calls == [POSTING])."""
    browser = _Browser({POSTING: _posting(), APPLY: _form()}, start=POSTING)
    wf, _bus = _workflow(browser, registry=_ats_registry())

    result = wf.run(_job())

    assert browser.get_calls == [POSTING, APPLY]
    assert result.apply_route_hops == 1
    assert result.landed_host == "jobs.ats.example"


def test_same_host_link_to_this_same_page_is_not_followed():
    """GUARD (passes before and after): a link back to the posting itself
    (a fragment) is not a route; the posting is attempted as-is, as before.
    It keeps the new same-host rule from looping on its own page."""
    browser = _Browser({POSTING: _posting(POSTING + "#apply")}, start=POSTING)
    wf, _bus = _workflow(browser)

    result = wf.run(_job())

    assert browser.get_calls == [POSTING]
    assert result.apply_route_hops == 0


def test_a_posting_is_not_a_suspicious_redirect():
    """TEETH (cause 3): a formless posting that says "job" many times
    publishes no REDIRECT_TO_LIST_DETECTED (which enqueued a company
    discovery task for every pasted link)."""
    browser = _Browser({POSTING: _posting()}, start=POSTING)
    wf, bus = _workflow(browser)
    wf._navigate_to_application = lambda job, ev: ev

    wf.run(_job())

    published = [c.args[0] for c in bus.publish.call_args_list if c.args]
    assert Event.REDIRECT_TO_LIST_DETECTED not in published


def test_nothing_filled_never_asks_to_submit():
    """TEETH (cause 4): with 0 fields filled, the submit checkpoint is not
    shown and the outcome says so. Before: the owner was asked
    "Submit application?" with fields 0/0."""
    browser = _Browser({APPLY: _form()}, start=APPLY)
    gate = MagicMock(return_value="skip")
    wf, _bus = _workflow(browser, pause=True, approval_gate=gate)
    job = _job()
    job.url = APPLY

    result = wf.run(job)

    asked = [c for c in gate.call_args_list if "ubmit" in str(c)]
    assert asked == []
    assert result.outcome == "FAILED_NOTHING_FILLED"
    assert result.submit_clicked is False
    assert result.fields_classified == 0


def test_an_element_without_a_live_reference_is_skipped_not_raised():
    """TEETH (cause 5): the strategic pass skips an element it cannot
    inspect. Before: ValueError ended the whole attempt (Greenhouse)."""
    wf, _bus = _workflow(_Browser({}, start=POSTING))
    element = UIElement(id="first_name-First Name-text_input")
    action = SimpleNamespace(action_type=InteractionType.TYPE, ui_element=element)

    assert wf._is_safe_fill(action) is False


def test_shadow_scan_returns_no_marker_the_fill_path_cannot_use():
    """TEETH (cause 6): controls inside shadow roots are reported, and no
    pretend "shadow DOM mode" structure is returned for a filler that does
    not exist. Before: {"shadow_dom_mode": True, ...} counted as fillable."""
    browser = _Browser({}, start=POSTING)
    browser.js_result = 17
    wf, _bus = _workflow(browser)

    wf._scan_shadow_dom_for_form()  # reports, never raises
    assert wf._get_form_structure_with_iframe_fallback(_job()) is None
