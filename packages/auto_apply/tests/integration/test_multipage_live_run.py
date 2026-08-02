
"""Stage 7 — the multi-page live run harness.

Everything built in this arc converges here: the strategic pass across pages,
per-page research records, joinable attempt ids, the submission gate and its
fail-loud surfacing, and `navigation_retries` / `warmup_pause` on a real load.

`tests/benchmarks/ats_forms/workday_multi_step.html` is a genuine three-page
wizard — `page-1`/`page-2`/`page-3` with `next-1` and `next-2` — and until now
**nothing referenced it**. It was built and never connected, like most of what
this arc has been wiring. It is the right instrument for this run precisely
because its later pages are unreachable without navigating: a single-page filler
physically cannot touch them, so the per-page record count is a real measurement
rather than a restatement.

Two tiers here:

* **Harness pins** run everywhere. They prove the fixture exists, has the shape
  the run depends on, and is reachable over HTTP.
* **The live run** is browser-gated and skips without Selenium/Chrome. It is the
  experiment, and its first execution is on the operator's machine.
"""
import functools
import http.server
import pathlib
import socketserver
import threading
import urllib.request

import pytest
from unittest.mock import MagicMock

ATS_FORMS = (
    pathlib.Path(__file__).resolve().parent.parent / "benchmarks" / "ats_forms"
)
MULTI_STEP = ATS_FORMS / "workday_multi_step.html"


class _ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


@pytest.fixture(scope="module")
def ats_form_server():
    """Serve the benchmark ATS forms over HTTP on an ephemeral port.

    Same reasoning as the greenhouse harness: browsers refuse `history.pushState`
    on `file://` origins, so a mock that simulates a confirmation navigation can
    only behave correctly when served over HTTP.
    """
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(ATS_FORMS)
    )
    server = _ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    yield f"http://{host}:{port}"
    server.shutdown()
    thread.join(timeout=5)


# ─────────────────────────────────────────────────────────────────────────────
# HARNESS — verified everywhere, no browser required
# ─────────────────────────────────────────────────────────────────────────────


def test_the_multi_step_mock_exists():
    assert MULTI_STEP.is_file(), f"missing fixture: {MULTI_STEP}"


def test_the_mock_really_has_three_pages():
    """Otherwise the per-page record count proves nothing."""
    html = MULTI_STEP.read_text(encoding="utf-8", errors="ignore")

    for page in ("page-1", "page-2", "page-3"):
        assert f'id="{page}"' in html, f"{page} missing"
    for advance in ("next-1", "next-2"):
        assert f'id="{advance}"' in html, f"{advance} missing"


def test_later_pages_carry_fields_the_first_page_does_not():
    """The measurement only means something if the pages differ.

    A filler that never advances cannot reach `salary_expectation`; if it turns
    up filled in the run, navigation genuinely happened.
    """
    html = MULTI_STEP.read_text(encoding="utf-8", errors="ignore")
    first_page = html.split('id="page-2"')[0]

    assert 'id="legal_name"' in first_page
    for later_field in ("years_exp", "salary_expectation"):
        assert f'id="{later_field}"' in html
        assert f'id="{later_field}"' not in first_page


def test_the_mock_is_reachable_over_http(ats_form_server):
    """The run needs it served, not opened from disk."""
    with urllib.request.urlopen(
        f"{ats_form_server}/workday_multi_step.html", timeout=10
    ) as response:
        body = response.read().decode("utf-8", errors="ignore")

    assert response.status == 200
    assert 'id="page-3"' in body


def test_the_form_fixtures_are_no_longer_orphaned():
    """They existed, unreferenced, for the whole project.

    This module is the reference. Pinned so a future cleanup does not delete
    them as dead weight — they are the only multi-page instrument there is.
    """
    referenced = [
        path.name
        for path in sorted(
            (pathlib.Path(__file__).resolve().parent.parent).rglob("*.py")
        )
        if "workday_multi_step" in path.read_text(encoding="utf-8", errors="ignore")
    ]
    assert referenced, "the multi-step mock is referenced by nothing again"


class _TextMatcherStub:
    """A deterministic TextSimilarityPort with no spaCy dependency.

    The live run needs *a* matcher, not the production one. Passing a bare
    MagicMock instead is what made the first attempt fail: inside
    `_navigate_multi_page_flow`, `_, score = matcher.find_best_match(...)` tries
    to unpack a MagicMock, raises TypeError, gets swallowed by the method's broad
    except, and the wizard silently never advances — `pages_navigated=0` with no
    error anywhere.
    """

    def find_best_match(self, query: str, candidates: list[str]) -> tuple[str, float]:
        """Best candidate by difflib ratio, with a containment shortcut.

        Args:
            query: The reference string.
            candidates: Strings to compare against.

        Returns:
            ``(best_candidate, score)`` — the same contract as the real
            TextMatcher, which is what the workflow unpacks.
        """
        import difflib

        text = (query or "").strip().lower()
        best, best_score = "", 0.0
        for candidate in candidates:
            target = candidate.strip().lower()
            if target and target in text:
                score = 1.0
            else:
                score = difflib.SequenceMatcher(None, text, target).ratio()
            if score > best_score:
                best, best_score = candidate, score
        return best, best_score


def test_the_matcher_stub_honours_the_real_contract():
    """It must return a 2-tuple the workflow can unpack, with usable scores."""
    from auto_apply.application.workflows.applications_workflow import (
        ApplicationsWorkflow,
    )

    matcher = _TextMatcherStub()
    labels = ApplicationsWorkflow._NEXT_BUTTON_LABELS

    for button_text in ("Next", "NEXT ", "Save and Continue", "Continue \u2192"):
        best, score = matcher.find_best_match(button_text.lower(), labels)
        assert score > 0.7, f"{button_text!r} scored {score} against {best!r}"

    _, score = matcher.find_best_match("upload your resume", labels)
    assert score <= 0.7, "an unrelated button would be clicked as Next"


def test_navigation_finds_the_next_button_with_a_real_matcher():
    """The pin that would have caught the vacuous first run.

    Drives the real `_navigate_multi_page_flow` — no browser needed, only a
    clickable-elements list and a matcher that actually returns a tuple.
    """
    from auto_apply.application.workflows.applications_workflow import (
        ApplicationsWorkflow,
    )
    from auto_apply.domain.models.session_plan import SessionPlan

    interaction = MagicMock()
    workflow = ApplicationsWorkflow(
        profile=MagicMock(),
        browser=MagicMock(),
        perception_port=None,
        interaction_port=interaction,
        webpage_analyzer=None,
        field_classifier=None,
        semantic_filler=None,
        text_matcher=_TextMatcherStub(),
        file_handler=None,
        interruption_handler=None,
        dom_observer=None,
        ats_registry=None,
        job_repo=MagicMock(),
        task_queue=MagicMock(),
        event_bus=MagicMock(),
        interrupt_policy=MagicMock(),
        text_generation_port=None,
        browser_lease=None,
        plan=SessionPlan(session_id="test"),
    )

    resume, nxt = MagicMock(), MagicMock()
    resume.text, nxt.text = "Upload your resume", "Next"
    workflow._get_clickable_elements = lambda: [resume, nxt]

    assert workflow._navigate_multi_page_flow() is True
    assert workflow._pages_navigated == 1
    interaction.click.assert_called_once_with(nxt)


def test_a_mock_matcher_cannot_navigate_and_fails_silently():
    """Documents the trap, so nobody re-introduces it thinking it is harmless.

    A MagicMock matcher makes navigation return False with no error surfaced —
    the failure mode that produced a green-looking run measuring one page.
    """
    from auto_apply.application.workflows.applications_workflow import (
        ApplicationsWorkflow,
    )
    from auto_apply.domain.models.session_plan import SessionPlan

    workflow = ApplicationsWorkflow(
        profile=MagicMock(),
        browser=MagicMock(),
        perception_port=None,
        interaction_port=MagicMock(),
        webpage_analyzer=None,
        field_classifier=None,
        semantic_filler=None,
        text_matcher=MagicMock(),
        file_handler=None,
        interruption_handler=None,
        dom_observer=None,
        ats_registry=None,
        job_repo=MagicMock(),
        task_queue=MagicMock(),
        event_bus=MagicMock(),
        interrupt_policy=MagicMock(),
        text_generation_port=None,
        browser_lease=None,
        plan=SessionPlan(session_id="test"),
    )
    button = MagicMock()
    button.text = "Next"
    workflow._get_clickable_elements = lambda: [button]

    assert workflow._navigate_multi_page_flow() is False
    assert workflow._pages_navigated == 0


def _live_registry():
    """Timing config for the live run: real pacing, no long waits."""
    registry = MagicMock()
    registry.get_all_effective_config.return_value = {
        "enable_human_timing": False,
        "occlusion_guard": True,
        "navigation_retries": 2,
        "infinite_scroll_settle_s": 0.2,
        "macro_pause_min_s": 0.0,
        "macro_pause_max_s": 0.0,
        "settle_min_s": 0.05,
        "settle_max_s": 0.1,
        "min_action_delay_ms": 0,
        "low_resource_mode": False,
    }
    return registry


def test_the_live_run_can_build_its_browser_stack_without_a_browser():
    """The pin that would have caught the instrument bug.

    The first version of the live run imported ``SeleniumBrowserAdapter``, which
    does not exist — the class is ``SeleniumAdapter``, and the correct name was
    already imported one directory away in test_reproducibility. A wrong class
    name in test code is invisible to the F821 gate, which only covers ``src/``.

    Constructing the stack needs no browser at all: a stand-in driver is enough
    to prove the imports resolve and the constructor signatures match.
    """
    from auto_apply.adapters.secondary.browser.selenium_adapter import (
        SeleniumAdapter,
    )
    from auto_apply.adapters.secondary.interaction.human_like_adapter import (
        InteractionExecutor,
    )
    from auto_apply.application.services.page_action.service import PageActionService

    browser = SeleniumAdapter(MagicMock())
    tool = PageActionService(browser=browser, registry=_live_registry())
    executor = InteractionExecutor(browser, page_action=tool)

    assert hasattr(executor, "click")
    assert hasattr(tool, "navigate")


# ─────────────────────────────────────────────────────────────────────────────
# THE LIVE RUN — browser-gated; this is the experiment
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.browser
class TestMultiPageLiveRun:
    """Drives the real Applications engine across a real three-page wizard.

    Skips without Selenium/Chrome.

    This class carried ``xfail(strict=False)`` while it had never executed
    anywhere — there is no browser in the environment it was written in, so its
    first run was the operator's. It has now xpassed on a real browser: the
    engine advances the wizard, one research record per page, records sharing one
    attempt id, and the submission gate holding. The marker is gone; from here a
    failure here is a real failure.
    """

    @pytest.fixture(scope="class")
    def driver(self):
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
        except ImportError:
            pytest.skip("Selenium not installed")

        opts = Options()
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")

        try:
            driver = webdriver.Chrome(options=opts)
        except Exception as exc:
            pytest.skip(f"Cannot create Chrome driver: {exc}")

        yield driver

        try:
            driver.quit()
        except Exception:
            pass

    def test_diagnostic_what_the_adapter_sees_on_the_wizard(
        self, driver, ats_form_server
    ):
        """Bisect: talk to the adapter directly, with no workflow involved.

        Two predictions about why `pages_navigated` was 0 have now been wrong —
        a stale hidden control, and the analyzer gating navigation — both from
        reading rather than measuring. This test measures.

        It reports, for every button on the loaded wizard: id, text, size, and
        the matcher score against the Next labels. Whatever comes back localises
        the fault precisely:

        * no buttons at all -> the adapter's find_elements or the locator path;
        * buttons with empty text -> the `text` property under this driver;
        * buttons with text but every score <= 0.7 -> the matcher or the labels;
        * buttons with a scoring Next -> the fault is in the workflow's use of
          them, not in any of the pieces.
        """
        from auto_apply.adapters.secondary.browser.selenium_adapter import (
            SeleniumAdapter,
        )
        from auto_apply.application.workflows.applications_workflow import (
            ApplicationsWorkflow,
        )
        from auto_apply.domain.types import Locator

        browser = SeleniumAdapter(driver)
        browser.get(f"{ats_form_server}/workday_multi_step.html")

        buttons = browser.find_elements(Locator.TAG_NAME, "button") or []
        matcher = _TextMatcherStub()

        report = []
        for button in buttons:
            text = getattr(button, "text", "") or ""
            try:
                size = button.get_size()
            except Exception as exc:  # pragma: no cover - diagnostic only
                size = f"error: {exc}"
            best, score = matcher.find_best_match(
                text.lower(), ApplicationsWorkflow._NEXT_BUTTON_LABELS
            )
            report.append(
                {
                    "id": button.get_attribute("id"),
                    "text": text,
                    "size": size,
                    "best_label": best,
                    "score": round(score, 3),
                }
            )

        print("\nADAPTER DIAGNOSTIC — buttons seen on load:")  # noqa: T201
        for row in report:
            print(f"  {row}")  # noqa: T201

        assert buttons, (
            "the adapter found no buttons at all on the loaded wizard, so the "
            "fault is in find_elements or the locator path, not the workflow"
        )
        scoring = [r for r in report if r["score"] > 0.7]
        assert scoring, (
            "buttons were found but none scored as Next; the fault is in the "
            f"text property, the matcher, or the labels. Report: {report}"
        )

    def test_the_engine_walks_the_wizard_and_records_every_page(
        self, driver, ats_form_server
    ):
        """The whole arc, on one page load.

        Asserted, in the order they matter:

        1. the engine advanced past page 1 (`pages_navigated >= 1`);
        2. one research record per page reached, indexed 0..N;
        3. every record shares one attempt id, and the outcome carries it;
        4. the outcome is NOT submitted — no approval gate is wired here, so
           the Stage 1 gate must hold and the Stage 6b remedy must be available.
        """
        from auto_apply.adapters.secondary.browser.selenium_adapter import (
            SeleniumAdapter,
        )
        from auto_apply.adapters.secondary.interaction.human_like_adapter import (
            InteractionExecutor,
        )
        from auto_apply.application.services.page_action.service import (
            PageActionService,
        )
        from auto_apply.application.workflows.applications_workflow import (
            ApplicationsWorkflow,
        )
        from auto_apply.domain.models.job import Job
        from auto_apply.domain.models.session_plan import SessionPlan
        from auto_apply.domain.ports.interrupt_policy_port import (
            ProfileBasedInterruptPolicy,
        )

        observer = MagicMock()
        browser = SeleniumAdapter(driver)

        # Real interaction wiring, not a mock: with a mocked interaction port the
        # wizard cannot advance, every assertion below collapses to page 1, and
        # the test passes vacuously. Clicking has to be real for the per-page
        # count to measure anything.
        tool = PageActionService(browser=browser, registry=_live_registry())
        interaction = InteractionExecutor(browser, page_action=tool)

        workflow = ApplicationsWorkflow(
            profile=MagicMock(),
            browser=browser,
            perception_port=None,
            interaction_port=interaction,
            webpage_analyzer=None,
            field_classifier=None,
            semantic_filler=None,
            text_matcher=_TextMatcherStub(),
            file_handler=None,
            interruption_handler=None,
            dom_observer=None,
            ats_registry=None,
            job_repo=MagicMock(),
            task_queue=MagicMock(),
            event_bus=MagicMock(),
            interrupt_policy=ProfileBasedInterruptPolicy(None),
            # Same tool instance, so warmup_pause and navigation_retries
            # actually fire on this load — otherwise the engine falls back
            # to a bare browser.get and reading-list item 4 is unobservable.
            navigation=tool,
            text_generation_port=None,
            browser_lease=None,
            plan=SessionPlan(session_id="live"),
        )
        workflow._research_observer = observer

        job = Job(
            title="Senior Software Engineer",
            company="Acme Corp (Mock)",
            url=f"{ats_form_server}/workday_multi_step.html",
            source="test_fixture",
        )

        # Capture what navigation actually saw, so a failure below names the
        # cause instead of prompting another round of guessing.
        seen: list[dict] = []
        original = workflow._get_clickable_elements

        def _recording():
            elements = original()
            seen.append(
                {
                    "count": len(elements),
                    "texts": [getattr(e, "text", "") or "" for e in elements],
                }
            )
            return elements

        workflow._get_clickable_elements = _recording

        # The bisect proves a Next button is found and scores 1.0, and
        # _pages_navigated increments immediately after the click returns.
        # So pages_navigated == 0 means the CLICK RAISED and the reason was
        # swallowed by the navigation method's broad except. Capture it.
        clicks: list[str] = []
        real_click = interaction.click

        def _recording_click(element):
            label = (getattr(element, "text", "") or "?").strip()
            try:
                real_click(element)
            except Exception as exc:
                clicks.append(f"{label!r} -> {type(exc).__name__}: {exc}")
                raise
            clicks.append(f"{label!r} -> ok")

        interaction.click = _recording_click

        evidence = workflow.run(job, session_id="live")

        observations = [c.args[0] for c in observer.observe_form.call_args_list]

        assert evidence.pages_navigated >= 1, (
            "the engine never advanced past page 1, so the per-page count "
            "below would pass vacuously.\n"
            f"  what navigation saw: {seen}\n"
            f"  click attempts: {clicks}"
        )
        assert len(observations) >= 2, (
            f"expected one record per page reached, got {len(observations)}"
        )
        assert [o.page_index for o in observations] == list(
            range(len(observations))
        ), "page indices are not sequential from zero"
        assert len({o.attempt_id for o in observations}) == 1
        assert observations[0].attempt_id == evidence.attempt_id

        # No approver is wired, so the gate must hold.
        assert evidence.outcome != "SUBMITTED"
        assert evidence.submit_clicked is False
