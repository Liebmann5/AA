"""Applications Workflow — fills and submits job application forms.

What this engine does:
    For each vetted job, navigate to the application form, analyze its structure
    mathematically (Hungarian-algorithm field pairing), classify every field, fill
    standard fields from the user profile, answer custom open-ended questions using
    GPT4All (with SpaCy similarity fallback), handle file uploads, navigate multi-page
    forms, and submit the completed application.

10‑step sequence:
    1.  _navigate_to_application       — route from the posting to a real form:
                                          learned apply target → off-host hrefs →
                                          one bounded click; challenge and
                                          account verdicts at every landing
    2.  _detect_login_wall             — check for authentication barriers before filling
    3.  _get_form_structure_with_iframe_fallback — search iFrames + Shadow DOM if main frame empty
    4.  _analyze_form_mathematically   — route analysis tier (KNOWN_PLATFORM/CSS_EXTRACTION/
                                          FULL_MATH_DOM); produce FormStructure
    5.  _classify_all_fields           — FieldClassifier + SpaCy fallback for ambiguous labels
    6.  _fill_standard_fields          — SemanticFiller → profile → interaction_port
    7.  _generate_custom_answers       — GPT4All or SpaCy-ranked experience paragraph
    8.  _handle_file_uploads           — resume / cover letter upload
    9.  _navigate_multi_page_flow      — detect Next/Continue, click, wait for DOM
    10. _handle_interruptions          — banners, structural challenge detection via
                                          the ONE domain predicate, an in-place
                                          human pause on a presented challenge,
                                          and redirect detection
    11. _submit_application            — HITL gate, submit button, cooldown extraction
    12. _record_application_outcome    — persist result, publish event, telemetry

Inputs:
    profile           — UserProfile (all form fill data)
    browser           — BrowserInterface (navigation)
    perception_port   — PerceptionPort (page scanning)
    interaction_port  — InteractionPort (clicking, typing)
    webpage_analyzer  — WebpageAnalyzer (mathematical form understanding)
    field_classifier  — FieldClassifier (label → FieldType)
    semantic_filler   — SemanticFiller (FieldType → profile value)
    text_matcher      — TextMatcher (similarity for label disambiguation)
    page_analysis_router — PageAnalysisRouter (lightweight‑first tier decision)
    file_handler      — FileInteractionHandler (resume/cover letter upload)
    interruption_handler — InterruptionHandler (dismisses cookie banners)
    dom_observer      — DOMObserver (waits for DOM stability)
    ats_registry      — ATSRegistry (ATS platform detection)
    job_repo          — JobRepositoryPort (persists outcome)
    task_queue        — WorkQueuePort (company batch scheduling).
    event_bus         — EventBus
    interrupt_policy  — InterruptPolicyPort (HITL checkpoint decisions)
    rng               — random.Random (deterministic randomness; optional)

Outputs:
    Returns ApplicationEvidence — structured evidence with boolean truthiness.
    Publishes: FORM_FIELD_FILLED, FORM_FIELD_FAILED, APPLICATION_SUBMITTED,
               APPLICATION_FAILED, REDIRECT_TO_LIST_DETECTED, CAPTCHA_DETECTED.

Three intelligence layers (each degrades gracefully):
    1. Mathematical:  WebpageAnalyzer + Hungarian algorithm (form structure)
    2. Linguistic:    SpaCy via TextMatcher (field classification, label similarity)
    3. Generative:    GPT4All via TextGenerationPort (custom question answers)

How to extend:
    To add a new ATS handler: add a YAML file to resources/ats/ and register
    in ATSRegistry. No changes to this workflow file required.
"""
from __future__ import annotations

import logging
import random
import re
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from auto_apply.application.services.company_batch_scheduler import (
    CompanyBatchScheduler,
)
from auto_apply.domain.events import Event
from auto_apply.domain.models.application_evidence import (
    ApplicationEvidence,
)
from auto_apply.domain.models.job import Job
from auto_apply.domain.models.session_plan import SessionPlan
from auto_apply.domain.models.profile import PersonalInfo, UserProfile, is_document_path
from auto_apply.domain.models.ui import (
    InteractionType,
    UIElement,
    UIElementType,
)
from auto_apply.domain.exceptions import ApplicationError
from auto_apply.domain.ports.interrupt_policy_port import (
    ApplicationContext,
    Checkpoint,
)
from auto_apply.domain.ports.navigation_port import InterruptionHandlerPort, NullInterruptionHandler
from auto_apply.domain.ports.page_understanding_port import (
    FormFieldInfo,
    FormStructure,
)
from auto_apply.domain.ports.research_port import (
    ApplicationOutcomeObservation,
    FormObservation,
    ResearchObserverPort,
)
from auto_apply.domain.services.posting_observation import infer_jurisdiction
from auto_apply.domain.services.page_assessment import (
    PageAssessment,
    assess_page,
)
from auto_apply.domain.types import PageType
from auto_apply.domain.services.apply_target import (
    auth_dialog_present,
    find_apply_controls,
    is_apply_label,
    page_has_fillable_form,
)
from auto_apply.domain.services.research_identity import compute_company_id
from auto_apply.application.services.page_analysis_router import (
    PageAnalysisRouter,
    PageAnalysisTier,
)

logger = logging.getLogger(__name__)

# ── Cooldown patterns ───────────────────────────────────────────────────────
_COOLDOWN_PATTERNS = [
    re.compile(r"apply\s+again\s+in\s+(\d+)\s+months?", re.IGNORECASE),
    re.compile(r"(\d+)[- ]month\s+cooldown", re.IGNORECASE),
    re.compile(r"reapply\s+after\s+(\d+)\s+months?", re.IGNORECASE),
]
_KEEP_ON_FILE_PATTERN = re.compile(
    r"keep\s+your\s+application\s+on\s+file", re.IGNORECASE
)

# Degree name → numeric level mapping for knockout thresholds
_DEGREE_LEVEL_MAP = {
    "high school": 0,
    "bachelor": 1,
    "bachelors": 1,
    "ba": 1,
    "bs": 1,
    "master": 2,
    "masters": 2,
    "ma": 2,
    "ms": 2,
    "mba": 2,
    "phd": 3,
    "doctorate": 3,
    "doctoral": 3,
}

# ── Login wall detection ────────────────────────────────────────────────────
# The indicator lists that used to live here are deleted. The verdict is
# computed structurally by domain/services/challenge_assessment.py — the ONE
# predicate — from the login URL markers and password-field/form/text shape
# defined there. A title substring ("register") is no longer consulted, which
# is why a posting titled "Registered Nurse" is no longer a login wall.


class ApplicationsWorkflow:
    """Orchestrates the full Applications pipeline for a single job."""

    MAX_PAGES: int = 10
    MAX_STEPS_PER_PAGE: int = 15
    DOM_STABILIZATION_TIMEOUT_S: float = 8.0
    _NEXT_BUTTON_LABELS: list[str] = [
        "next", "continue", "save and continue", "proceed", "step", "forward",
    ]
    _SUBMIT_KEYWORDS: list[str] = [
        "submit", "submit application", "apply now", "send application",
        "complete application", "finish application",
    ]

    def __init__(
        self,
        profile: UserProfile,
        browser,
        perception_port,
        interaction_port,
        webpage_analyzer,
        field_classifier,
        semantic_filler,
        text_matcher,
        file_handler,
        interruption_handler: InterruptionHandlerPort | None,
        dom_observer,
        ats_registry,
        job_repo,
        task_queue,
        event_bus,
        interrupt_policy,
        text_generation_port=None,
        approval_gate=None,
        config: dict | None = None,
        context_manager=None,
        research_observer: ResearchObserverPort | None = None,
        page_analysis_router: PageAnalysisRouter | None = None,
        browser_lease=None,   # <--- NEW: injected by composition root
        navigation=None,
        reasoning_port=None,
        rng: random.Random | None = None,    # deterministic randomness
        *,
        plan: SessionPlan,
    ) -> None:
        """Initialize with all dependencies injected.

        Args:
            profile: Active user profile.
            browser: BrowserInterface for navigation.
            perception_port: PerceptionPort for page scanning.
            interaction_port: InteractionPort for clicking and typing.
            webpage_analyzer: WebpageAnalyzer for mathematical form understanding.
            field_classifier: FieldClassifier for label → FieldType mapping.
            semantic_filler: SemanticFiller for FieldType → profile value mapping.
            text_matcher: TextMatcher for similarity-based label disambiguation.
            file_handler: FileInteractionHandler for resume/cover letter upload.
            interruption_handler: InterruptionHandlerPort for cookie banner
                dismissal (None degrades, loudly, to no auto-dismissal).
            dom_observer: DOMObserver for waiting on DOM stability.
            ats_registry: ATSRegistry for ATS platform detection.
            job_repo: JobRepositoryPort for persisting application outcomes.
            task_queue: WorkQueuePort for the company batch scheduler.
            event_bus: EventBus for publishing application events.
            interrupt_policy: InterruptPolicyPort for HITL checkpoint decisions.
            text_generation_port: TextGenerationPort | None — GPT4All or None.
            approval_gate: ApprovalGate | None — HITL approval callable.
            config: Effective config dict from registry.
            context_manager: ContextManager | None — tab/window switching.
            research_observer: ResearchObserverPort | None — new research signal pipeline.
            page_analysis_router: PageAnalysisRouter | None — lightweight‑first tier decision.
            browser_lease: Optional BrowserLeaseManager — concurrency safety.
            rng: Optional seeded random.Random instance for deterministic behaviour.
        """
        self._profile = profile
        self._browser = browser
        self._perception_port = perception_port
        self._interaction_port = interaction_port
        self._webpage_analyzer = webpage_analyzer
        self._field_classifier = field_classifier
        self._semantic_filler = semantic_filler
        self._text_matcher = text_matcher
        self._file_handler = file_handler
        self._interruption_handler = interruption_handler
        self._dom_observer = dom_observer
        self._ats_registry = ats_registry
        self._job_repo = job_repo
        self._task_queue = task_queue
        self._event_bus = event_bus
        self._interrupt_policy = interrupt_policy
        self._navigation = navigation
        self._interruption_warning_emitted: bool = False
        # The planner half of understand -> plan -> act. Built by the
        # composition root since day one and never handed to anyone.
        self._reasoning_port = reasoning_port
        self._text_generation_port = text_generation_port
        self._approval_gate = approval_gate
        self._config = config or {}
        self._context_manager = context_manager
        self._research_observer = research_observer
        self._page_analysis_router = page_analysis_router
        self._browser_lease = browser_lease
        self._rng = rng if rng is not None else random.Random()
        # Required session plan. Unlike DiscoveryWorkflow, this is not defaulted
        # to a fabricated fallback — a missing plan must fail at construction,
        # not silently run as if non-deterministic.
        self._plan = plan
        # Feedback-loop capture: the tier the router chose and the page it chose
        # it for, remembered between form analysis and the recorded outcome.
        self._last_analysis_tier: PageAnalysisTier | None = None
        self._last_page_url: str = ""
        self._last_page_source: str = ""

        self._current_job: Job | None = None
        self._pages_navigated: int = 0
        #: Monotonic per-session counter; makes each attempt's id unique so
        #: two attempts at the same job do not merge into one set of rows.
        self._attempt_seq: int = 0
        self._attempt_id: str = ""
        #: Set when a challenge verdict shaped this attempt; stamped onto the
        #: evidence so a disputed outcome says why, not just what.
        self._captcha_encountered: bool = False
        self._challenge_signals: list[str] = []
        self._challenge_note: str = ""
        #: Bounds in-place challenge pauses per attempt, so a challenge that
        #: keeps returning after reported solves ends honestly, not in a loop.
        self._challenge_pauses: int = 0
        self._fields_filled: int = 0
        self._fields_classified: int = 0
        self._required_fields_filled: int = 0
        #: Labels of required fields whose fill failed this attempt. A non-empty
        #: list at the end of the page loop blocks submission (fail closed).
        self._failed_required_fields: list[str] = []
        self._gpt4all_invoked: bool = False
        self._session_id: str | None = None

        # ── Company‑batch scheduler (owned here, called by orchestrator) ──
        batch_threshold = self._cfg("applications.batch_threshold", 3)
        self.batch_scheduler = CompanyBatchScheduler(
            task_queue=self._task_queue,
            batch_threshold=batch_threshold,
        )

    def set_approval_gate(self, gate) -> None:
        """Late-bind the HITL approval gate.

        ApplicationsWorkflow is constructed in the composition root before the
        SessionController exists, so the approval gate (which the controller
        owns) cannot be injected at construction time. SessionController calls
        this after wiring is complete to resolve that ordering dependency.

        Args:
            gate: An ApprovalGate callable ``(question, options, context_id) -> str``.
        """
        self._approval_gate = gate

    def _cfg(self, key: str, default: Any) -> Any:
        """Read a dot-path config key from self._config with a default fallback."""
        parts = key.split(".")
        node = self._config
        for part in parts:
            if not isinstance(node, dict):
                return default
            node = node.get(part, default)
            if node is default:
                return default
        return node

    # ──────────────────────────────────────────────────────────────────────────
    # LOGIN WALL DETECTION (Wave K2)
    # ──────────────────────────────────────────────────────────────────────────

    def _page_snapshot(self, fallback_url: str) -> tuple[str, str, str]:
        """(url, title, html) of the page the browser is on RIGHT NOW.

        The browser is only a snapshot taker; every verdict about the page
        is computed from these three values by the pure predicate. Values
        are coerced defensively: a driver that cannot answer (or a test
        double whose attributes are not strings) degrades to empty strings
        rather than poisoning the parse.
        """
        url = getattr(self._browser, "current_url", "") or ""
        if not isinstance(url, str) or not url:
            url = fallback_url
        title = getattr(self._browser, "title", "") or ""
        if not isinstance(title, str):
            title = ""
        html = getattr(self._browser, "page_source", "") or ""
        if not isinstance(html, str):
            html = ""
        return url, title, html

    def _detect_login_wall(self, job: Job) -> bool:
        """Returns True if the current page is a login/authentication wall.

        Structural verdict, computed by the ONE page verdict
        (domain/services/page_assessment.py, which delegates to
        challenge_assessment.py for the login answer): a login URL, or a
        password field on a page too small to carry a posting. The page
        title is never read — the old title-substring check made a posting
        titled "Registered Nurse" a login wall.

        Called after navigation, before form filling — prevents AA from
        trying to fill a login form with the applicant's profile data.
        """
        try:
            url, title, html = self._page_snapshot(fallback_url=job.url)
            walled = (
                assess_page(url=url, title=title, html=html).kind
                is PageType.LOGIN_REQUIRED
            )
        except Exception as exc:
            logger.debug("Login wall detection error: %s", exc)
            return False
        if walled:
            logger.warning(
                "Login wall detected (structural) | job=%s @ %s",
                job.title[:30],
                job.company[:30],
            )
        return walled

    # ──────────────────────────────────────────────────────────────────────────
    # IFRAME + SHADOW DOM FORM SEARCH (Wave K1)
    # ──────────────────────────────────────────────────────────────────────────

    def _get_form_structure_with_iframe_fallback(self, job: Job):
        """Analyze the current page for a form, searching iFrames if main frame
        is empty.

        Returns the form structure from wherever it is found.
        Returns None if no form is found anywhere on the page.
        """
        # ── Attempt 1: Main frame ──────────────────────────────────────────
        form_structure = self._analyze_form_mathematically()

        if form_structure and self._has_fillable_fields(form_structure):
            return form_structure

        logger.info(
            "No form found in main frame — scanning iFrames | url=%s",
            job.url[:60],
        )

        # ── Attempt 2: iFrame scan ─────────────────────────────────────────
        try:
            from auto_apply.domain.types import Locator  # noqa: PLC0415

            iframes = self._browser.find_elements(Locator.TAG_NAME, "iframe")
            logger.debug("Found %d iFrames to scan", len(iframes) if iframes else 0)

            if iframes:
                for i, iframe in enumerate(iframes):
                    try:
                        self._browser.switch_to_iframe(iframe)
                        frame_structure = self._analyze_form_mathematically()

                        if frame_structure and self._has_fillable_fields(
                            frame_structure
                        ):
                            logger.info(
                                "Form found in iFrame %d/%d | url=%s",
                                i + 1,
                                len(iframes),
                                job.url[:60],
                            )
                            # Stay in the iFrame context so field filling works.
                            return frame_structure

                        # Not found in this frame — go back to default before
                        # trying the next one.
                        self._browser.switch_to_default_content()

                    except Exception as exc:
                        logger.debug("iFrame %d scan error: %s", i, exc)
                        try:
                            self._browser.switch_to_default_content()
                        except Exception:
                            pass

        except Exception as exc:
            logger.warning("iFrame enumeration failed: %s", exc)
            try:
                self._browser.switch_to_default_content()
            except Exception:
                pass

        # ── Attempt 3: Shadow DOM (Web Components) ─────────────────────────
        shadow_structure = self._scan_shadow_dom_for_form()
        if shadow_structure and self._has_fillable_fields(shadow_structure):
            logger.info("Form found inside Shadow DOM | url=%s", job.url[:60])
            return shadow_structure

        logger.warning(
            "No form found in main frame, iFrames, or Shadow DOM | url=%s",
            job.url[:60],
        )
        return None

    def _scan_shadow_dom_for_form(self):
        """Attempt to pierce Shadow DOM and find form elements.

        Web Component-based ATS (some modern platforms) put their forms inside
        a Shadow DOM that Selenium cannot access directly. We use JavaScript
        to pierce it.

        Returns the form structure if found, or None.
        """
        try:
            # Pierce the shadow DOM and extract form elements via JavaScript
            result = self._browser.execute_script("""
                function queryShadowAll(root, selector) {
                    let elements = Array.from(root.querySelectorAll(selector));
                    root.querySelectorAll('*').forEach(el => {
                        if (el.shadowRoot) {
                            elements = elements.concat(
                                queryShadowAll(el.shadowRoot, selector)
                            );
                        }
                    });
                    return elements;
                }
                const inputs = queryShadowAll(
                    document,
                    'input:not([type=hidden]),textarea,select'
                );
                return inputs.length;
            """)

            if result and result > 0:
                logger.info(
                    "Shadow DOM contains %d form inputs — "
                    "attempting JavaScript fill strategy",
                    result,
                )
                # Shadow DOM forms require a JS-based fill strategy.
                # Return a marker structure indicating shadow DOM mode.
                return {"shadow_dom_mode": True, "input_count": result}

        except Exception as exc:
            logger.debug("Shadow DOM scan failed: %s", exc)

        return None

    @staticmethod
    def _has_fillable_fields(form_structure) -> bool:
        """Returns True if the form structure contains at least one fillable field."""
        if not form_structure:
            return False
        if isinstance(form_structure, dict) and form_structure.get("shadow_dom_mode"):
            return True
        # Check for actual field pairs in the math subsystem's structure
        label_pairs = getattr(form_structure, "label_field_pairs", None) or {}
        return len(label_pairs) > 0

    # ──────────────────────────────────────────────────────────────────────────
    # NAVIGATION
    # ──────────────────────────────────────────────────────────────────────────

    def _navigate_to_application(
        self, job: Job, evidence: ApplicationEvidence
    ) -> ApplicationEvidence:
        """Get from the job URL to a page carrying a fillable application form.

        The route:
            1. Start from the apply target vetting recorded in
               ``metadata["apply_url"]`` when there is one — the posting is
               never reloaded in that case (it was already read, once, at
               vetting; two navigations to the most bot-guarded page in the
               flow was the measured cost of learning nothing).
            2. Otherwise load the posting and work its apply controls: an
               off-host <a> href is FOLLOWED BY NAVIGATION (deterministic,
               and the hop is recorded); a target-less button is CLICKED
               (what a person does), after which a new tab is followed, a
               JS navigation is honoured, an authentication dialog ends the
               route as ACCOUNT_REQUIRED, and a revealed form is filled.
            3. Every landing page gets part A's two verdicts: a presented
               challenge pauses in place; a login wall before any form ends
               the route as ACCOUNT_REQUIRED. Hops are bounded
               (``applications.max_apply_hops``, default 3) and loops end
               honestly — never a hang.

        The route is recorded on the evidence: posting host, apply target
        host, landed host, hop count, and the ATS of the LANDED page.
        Matching ATSRegistry against job.url alone could never match
        anything when job.url is a job board — which in live runs is every
        job.

        Returns:
            Updated ApplicationEvidence. A terminal route outcome
            (FAILED_NAVIGATION / CAPTCHA_BLOCKED / ACCOUNT_REQUIRED) means
            the caller records and stops; anything else means a page worth
            filling is loaded.
        """
        metadata = job.metadata if hasattr(job, "metadata") else {}
        apply_url = metadata.get("apply_url")
        if not isinstance(apply_url, str) or not apply_url.strip():
            apply_url = ""

        posting_host = _host_of(job.url)
        start_url = apply_url or job.url
        evidence = evidence.model_copy(update={
            "posting_host": posting_host,
            "apply_target_host": _host_of(apply_url) if apply_url else "",
        })

        try:
            self._navigate(start_url)
        except Exception as exc:
            logger.warning(
                "ApplicationsWorkflow: navigation failed | url=%s error=%s",
                start_url,
                exc,
            )
            return evidence.model_copy(update={
                "outcome": "FAILED_NAVIGATION",
                "confidence": 0.95,
                "error_message": str(exc)[:200],
                **self._run_statistics(),
            })

        visited: set[str] = {job.url, start_url}
        current = self._current_url(default=start_url)
        visited.add(current)
        max_hops = self._cfg("applications.max_apply_hops", 3)
        hops = 0
        clicks = 0

        while True:
            url, title, html = self._page_snapshot(fallback_url=current)

            # ── Part A verdicts at every landing ─────────────────────────
            terminal = self._check_route_landing(job, url, title, html, evidence)
            if terminal is not None:
                return terminal

            # ── ATS on the LANDED page, not on job.url ───────────────────
            evidence, ats_matched = self._match_landed_ats(job, url, evidence)

            # ── An off-host apply href OUTRANKS any on-page form ─────────
            # It is the posting's own statement of where applying happens.
            # Form-first ordering stopped on the one measured off-host
            # route and filled the posting's alert form, because that form
            # crossed the fillable bar (probe_item12, 2026-09).
            href = self._find_apply_href(url, html, visited)
            if href is not None:
                if hops >= max_hops:
                    return self._route_failed(
                        evidence,
                        url,
                        f"apply route exceeded the hop bound ({max_hops})",
                    )
                hops += 1
                visited.add(href)
                try:
                    self._navigate(href)
                except Exception as exc:
                    return self._route_failed(evidence, href, str(exc)[:200])
                current = self._current_url(default=href)
                visited.add(current)
                if not evidence.apply_target_host:
                    evidence = evidence.model_copy(update={
                        "apply_target_host": _host_of(href),
                    })
                continue

            # A substantial form means this page IS the application. It is
            # checked after the href on purpose: a form page's own submit
            # has no off-host href, so a real form page never reaches this
            # line via the route.
            if page_has_fillable_form(html) or ats_matched:
                break

            # ── Then a target-less apply control: click, as a person would ─
            if clicks == 0 and self._click_apply_control(job):
                clicks += 1
                if self._context_manager is not None:
                    try:
                        self._context_manager.switch_to_new_tab()
                    except Exception:
                        pass
                after_url, _after_title, after_html = self._page_snapshot(
                    fallback_url=url
                )
                if after_url != url:
                    hops += 1
                    visited.add(after_url)
                    current = after_url
                if self._auth_dialog_blocking(
                    before_html=html, after_html=after_html
                ):
                    logger.info(
                        "ApplicationsWorkflow: apply control opened an "
                        "authentication dialog | job=%s",
                        job.title,
                    )
                    return evidence.model_copy(update={
                        "outcome": "ACCOUNT_REQUIRED",
                        "confidence": 0.90,
                        "login_wall_encountered": True,
                        "error_message": (
                            "the apply flow requires an account on this site "
                            "(an authentication dialog opened; nothing was filled)"
                        ),
                        "landed_host": _host_of(after_url),
                        **self._run_statistics(),
                    })
                continue

            # ── Nothing left to follow ───────────────────────────────────
            if hops > 0 or clicks > 0:
                # A route was attempted and ended on a page with no form.
                # Filling whatever this page is would be the pre-12B defect,
                # so the route fails honestly instead.
                return self._route_failed(
                    evidence,
                    url,
                    "apply route ended on a page with no application form "
                    "and no further apply control",
                )
            # No route was ever found: preserve the pre-12B behaviour of
            # attempting the page as-is (it may be a weak-markup form page).
            break

        final_url = self._current_url(default=start_url)
        return evidence.model_copy(update={
            "landed_host": _host_of(final_url),
            "apply_route_hops": hops,
        })

    def _current_url(self, default: str) -> str:
        """The browser's current URL as a plain string, or ``default``."""
        url = getattr(self._browser, "current_url", "") or ""
        if not isinstance(url, str) or not url:
            return default
        return url

    def _route_failed(
        self, evidence: ApplicationEvidence, url: str, reason: str
    ) -> ApplicationEvidence:
        """Terminal route failure with the reason recorded, never a hang."""
        logger.warning(
            "ApplicationsWorkflow: apply route failed | url=%s reason=%s",
            url,
            reason,
        )
        return evidence.model_copy(update={
            "outcome": "FAILED_NAVIGATION",
            "confidence": 0.90,
            "error_message": reason[:200],
            "landed_host": _host_of(url),
            **self._run_statistics(),
        })

    def _check_route_landing(
        self,
        job: Job,
        url: str,
        title: str,
        html: str,
        evidence: ApplicationEvidence,
    ) -> ApplicationEvidence | None:
        """Part A's two verdicts for one route landing. None means proceed.

        A presented challenge pauses IN PLACE (ruling A): a solve continues
        the route on the now-clear page; anything else ends the route as
        CAPTCHA_BLOCKED. A whole-page login wall before any form was reached
        ends the route as ACCOUNT_REQUIRED — the site demands an account
        before it will even show a form.
        """
        page = assess_page(url=url, title=title, html=html)
        if page.challenge == "gated":
            self._captcha_encountered = True
            self._challenge_signals = list(page.signals)
            logger.info(
                "ApplicationsWorkflow: challenge presented on apply route | "
                "url=%s signals=%s",
                url,
                ",".join(page.signals),
            )
            try:
                self._event_bus.publish(
                    Event.CAPTCHA_DETECTED,
                    {
                        "job_url": job.url,
                        "url": url,
                        "signals": list(page.signals),
                        "detail": page.detail,
                    },
                )
            except Exception:
                pass
            if not self._pause_for_challenge(job, url, page):
                return evidence.model_copy(update={
                    "outcome": "CAPTCHA_BLOCKED",
                    "confidence": 0.90,
                    "captcha_encountered": True,
                    "error_message": self._challenge_note or None,
                    "landed_host": _host_of(url),
                    **self._run_statistics(),
                })
            return None
        if page.challenge == "embedded":
            self._challenge_signals = list(page.signals)
        if page.kind is PageType.LOGIN_REQUIRED:
            logger.info(
                "ApplicationsWorkflow: apply route reached a login wall "
                "before any form | url=%s",
                url,
            )
            return evidence.model_copy(update={
                "outcome": "ACCOUNT_REQUIRED",
                "confidence": 0.90,
                "login_wall_encountered": True,
                "error_message": (
                    "an account is required before this site will show an "
                    "application form"
                ),
                "landed_host": _host_of(url),
                **self._run_statistics(),
            })
        return None

    def _match_landed_ats(
        self, job: Job, url: str, evidence: ApplicationEvidence
    ) -> tuple[ApplicationEvidence, bool]:
        """Match ATSRegistry against the LANDED URL and record it.

        Returns (evidence, matched). A matched ATS page is also a route stop
        signal: a known application host is a destination even when its form
        markup is unusual.
        """
        descriptor = None
        try:
            if self._ats_registry is not None:
                descriptor = self._ats_registry.match(url)
        except Exception:
            descriptor = None
        if descriptor is None:
            return evidence, False
        if hasattr(job, "metadata"):
            job.metadata["ats"] = descriptor.name
        return evidence.model_copy(update={"ats_platform": descriptor.name}), True

    def _find_apply_href(
        self, page_url: str, html: str, visited: set[str]
    ) -> str | None:
        """The first off-host apply href on this page that is not yet visited.

        Read from the page's markup by the SAME pure parser vetting learns
        from, so the target learned and the target followed cannot be two
        different answers.
        """
        try:
            controls = find_apply_controls(url=page_url, html=html)
        except Exception as exc:
            logger.debug(
                "ApplicationsWorkflow: apply-control parse failed: %s", exc
            )
            return None
        for control in controls:
            if control.href and control.off_host and control.href not in visited:
                return control.href
        return None

    def _click_apply_control(self, job: Job) -> bool:
        """Click the first apply-intent control that has no navigable href.

        Navigable controls (an <a> with a real href) are followed by
        navigation, never clicked — a click invites pop-ups and new tabs
        where a navigation is deterministic and recorded.
        """
        if self._interaction_port is None:
            return False
        try:
            for el in self._get_clickable_elements():
                if not self._is_apply_control(el):
                    continue
                href = self._control_href(el)
                if href and not href.startswith(("#", "javascript:")):
                    continue
                label = self._control_label(el)
                self._interaction_port.click(el)
                self._wait_for_dom_stable()
                logger.info(
                    "ApplicationsWorkflow: apply control clicked | job=%s label=%s",
                    job.title,
                    label[:40],
                )
                return True
        except Exception as exc:
            logger.debug(
                "ApplicationsWorkflow: apply control click failed: %s", exc
            )
        return False

    def _auth_dialog_blocking(self, *, before_html: str, after_html: str) -> bool:
        """Did the apply click leave an authentication dialog BLOCKING the page?

        "A dialog is in the markup" is not "the click opened a dialog":
        measured job-board postings carry a hidden sign-in modal at all
        times (2-8 password inputs on the PRE-click page, probe_item12).
        The verdict asks, in order:

        1. Is there a password-bearing dialog in the after-click markup at
           all? (pure parse — no dialog, no account requirement.)
        2. Is such a dialog VISIBLE? The browser answers through a JS probe
           (getClientRects), which sees CSS display:none; the HTML parser
           provably cannot.
        3. When the probe is unavailable (a driver that cannot run JS),
           fall back to the transition: a dialog absent before the click
           and present after. On a JS-less driver a pre-hidden modal then
           answers False — the conservative answer, disclosed: an
           account-gated site reads as a route failure there, never as a
           filled sign-in form.
        """
        if not auth_dialog_present(after_html):
            return False
        visible = self._visible_password_dialogs()
        if visible is not None:
            return visible > 0
        return not auth_dialog_present(before_html)

    def _visible_password_dialogs(self) -> int | None:
        """Password inputs inside VISIBLE dialogs, or None when the browser
        cannot answer. Only a real integer is a verdict — a MagicMock or an
        exception is "unavailable", never zero."""
        try:
            result = self._browser.execute_script(
                'var ds = document.querySelectorAll('
                '\'[role="dialog"], [aria-modal="true"]\');'
                'var n = 0;'
                'ds.forEach(function(d) {'
                '  if (d.getClientRects().length === 0) { return; }'
                '  n += d.querySelectorAll(\'input[type="password"]\').length;'
                '});'
                'return n;'
            )
        except Exception:
            return None
        if isinstance(result, bool) or not isinstance(result, int):
            return None
        return result

    def _is_apply_control(self, el) -> bool:
        """Apply intent by accessible name — the same predicate the parser uses."""
        return is_apply_label(self._control_label(el))

    def _get_clickable_elements(self) -> list:
        """All actionable controls on the current page.

        The ONE source for the Apply, Next and Submit searches, covering the
        four shapes an actionable control actually takes: ``<a>``,
        ``<button>``, ``<input type=submit|button>`` and ``[role=button]``.
        The buttons-only search this replaces could not see an offsite apply
        link, a submit input, or an ARIA button at all (measured 2026-09-10).
        """
        try:
            if hasattr(self._browser, "find_elements"):
                from auto_apply.domain.types import Locator  # noqa: PLC0415

                return (
                    self._browser.find_elements(
                        Locator.CSS_SELECTOR,
                        "a, button, input[type='submit'], "
                        "input[type='button'], [role='button']",
                    )
                    or []
                )
        except Exception:
            pass
        return []

    @staticmethod
    def _control_label(el) -> str:
        """The control's accessible name: rendered text, then value,
        aria-label, title. An <input>'s label lives in its value — its
        ``.text`` is always empty, which is why submit inputs were invisible
        to the old label reader. Priority mirrors the pure parser's, so a
        control the parser sees and a control the browser sees agree."""
        text = getattr(el, "text", "") or ""
        if isinstance(text, str) and text.strip():
            return text.strip()
        getter = getattr(el, "get_attribute", None)
        if callable(getter):
            for name in ("value", "aria-label", "title"):
                try:
                    value = getter(name)
                except Exception:
                    value = None
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return ""

    @staticmethod
    def _control_href(el) -> str:
        """The control's href (resolved by the driver), or "" when it has none."""
        getter = getattr(el, "get_attribute", None)
        if not callable(getter):
            return ""
        try:
            value = getter("href")
        except Exception:
            return ""
        return value if isinstance(value, str) else ""

    def _wait_for_dom_stable(self, timeout: float | None = None) -> None:
        """Wait for DOM to stabilize, with graceful degradation."""
        t = timeout or self.DOM_STABILIZATION_TIMEOUT_S
        if self._dom_observer is None:
            return
        try:
            # Unconditional. This used to be guarded by a hasattr() probe
            # for a method that did not exist, so the wait never ran once.
            self._dom_observer.wait_for_dom_stable(timeout=t)
        except Exception as exc:
            logger.debug(
                "ApplicationsWorkflow: DOM stabilization wait failed: %s", exc
            )

    def _analyze_form_mathematically(self):
        """Analyze the current page to produce a form structure.

        Uses the PageAnalysisRouter to choose the cheapest effective tier:
          1. KNOWN_PLATFORM / CSS_EXTRACTION → lightweight (DOMScanner)
          2. FULL_MATH_DOM → existing WebpageAnalyzer

        Always falls back to WebpageAnalyzer if the lightweight path yields no
        fillable fields.
        """
        # ── Determine tier ──────────────────────────────────────────────────
        page_url = ""
        page_source = ""
        try:
            page_url = self._browser.current_url or ""
            page_source = getattr(self._browser, "page_source", "") or ""
        except Exception:
            pass

        tier = PageAnalysisTier.FULL_MATH_DOM
        if self._page_analysis_router is not None:
            try:
                tier = self._page_analysis_router.determine_tier(
                    page_url, page_source
                )
                logger.debug("PageAnalysisTier: %s | url=%s", tier.name, page_url[:80])
            except Exception as exc:
                logger.warning("PageAnalysisRouter raised: %s — defaulting to FULL_MATH_DOM", exc)

        # Remember the tier and page for the feedback loop. The outcome that
        # tells us whether this tier actually worked is not known until the
        # application concludes, in _record_application_outcome.
        self._last_analysis_tier = tier
        self._last_page_url = page_url
        self._last_page_source = page_source

        # ── Lightweight path ────────────────────────────────────────────────
        if tier != PageAnalysisTier.FULL_MATH_DOM:
            structure = self._build_simple_form_structure(tier)
            if structure and structure.fields:
                logger.info(
                    "Using lightweight form structure | tier=%s fields=%d",
                    tier.name,
                    len(structure.fields),
                )
                return structure
            logger.debug("Lightweight path returned no fields — falling back to math DOM")

        # ── Full math DOM (fallback) ────────────────────────────────────────
        if self._webpage_analyzer is None:
            logger.warning(
                "ApplicationsWorkflow: WebpageAnalyzer not available — "
                "returning empty form structure"
            )
            return FormStructure()

        try:
            return self._webpage_analyzer.analyze()
        except Exception as exc:
            logger.warning(
                "ApplicationsWorkflow: WebpageAnalyzer failed: %s", exc
            )
            return FormStructure()

    # ------------------------------------------------------------------
    # Lightweight form structure builder
    # ------------------------------------------------------------------

    def _build_simple_form_structure(
        self, tier: PageAnalysisTier
    ) -> FormStructure:
        """Construct a FormStructure using cheaper perception methods.

        Args:
            tier: The recommended analysis tier (already not FULL_MATH_DOM).

        Returns:
            A FormStructure populated from DOMScanner (or empty if no browser).
        """
        ui_model = None
        try:
            if self._perception_port is not None:
                ui_model = self._perception_port.scan_page()
        except Exception as exc:
            logger.warning("DOM scan failed for lightweight structure: %s", exc)

        if ui_model is None or not ui_model.elements:
            return FormStructure()

        fields: list[FormFieldInfo] = []
        for el in ui_model.elements:
            # Map UIElement → FormFieldInfo (conservative mapping).
            field_type = _map_ui_element_type(el.element_type)

            # Try to classify the field type via the injected classifier
            # (may upgrade the field_type to a more specific semantic type).
            if self._field_classifier is not None:
                # We need a DOMNode-compatible object; FieldClassifier.classify
                # expects an ElementInterface.  Since our lightweight path uses
                # the generic elements from the perception port, we can try to
                # call classify with the underlying reference if available.
                try:
                    # For DOMScanner the elements have a reference attachment.
                    raw_ref = el.get_reference()
                    if raw_ref is not None:
                        ft = self._field_classifier.classify(raw_ref)
                        if ft is not None:
                            field_type = str(ft)
                except Exception:
                    pass

            fields.append(
                FormFieldInfo(
                    field_id=el.id or "",
                    label_text=el.label or el.placeholder or el.name or "",
                    field_type=field_type,
                    name=el.name or "",
                    placeholder=el.placeholder or "",
                    is_required=el.is_required,
                    is_honeypot=False,
                    options=tuple(el.options) if el.options else (),
                )
            )

        return FormStructure(fields=tuple(fields))

    def _run_strategic_pass(self) -> int:
        """Understand -> plan -> act over whatever the classifier left unfilled.

        This is the domain's own triad, live for the first time:
        ``perception_port.scan_page()`` produces a UIModel,
        ``reasoning_port.devise_plan()`` turns it into an ordered
        InteractionPlan, and ``interaction_port.execute_plan()`` runs it.

        It SUPPLEMENTS the classifier pass rather than replacing it. Two rules
        keep it from changing anything the existing path already decided:

        1. **No clicks.** ``FormSolver.devise_plan`` includes a submit button in
           its plan. Executing that here would submit the application from a
           path that never consults the submission gate — so this pass fills,
           and every click stays with the workflow, which owns both the gate and
           the page loop.
        2. **No overwrites.** An action is dropped if its element already holds
           a value, and also dropped if the element cannot be inspected: not
           being able to check is a reason to leave a field alone, not a licence
           to overwrite it.

        Returns:
            The number of actions executed. Zero on any missing collaborator or
            any failure — a supplementary pass must never break a fill.
        """
        if (
            self._perception_port is None
            or self._reasoning_port is None
            or self._interaction_port is None
        ):
            return 0

        try:
            ui_model = self._perception_port.scan_page()
            plan = self._reasoning_port.devise_plan(ui_model)
        except Exception as exc:
            logger.debug("ApplicationsWorkflow: strategic pass planning failed: %s", exc)
            return 0

        actions = [a for a in getattr(plan, "actions", []) if self._is_safe_fill(a)]
        if not actions:
            return 0

        try:
            executed = plan.model_copy(update={"actions": actions})
            self._interaction_port.execute_plan(executed)
        except Exception as exc:
            logger.debug("ApplicationsWorkflow: strategic pass execution failed: %s", exc)
            return 0

        logger.info(
            "ApplicationsWorkflow: strategic pass filled %d element(s)", len(actions)
        )
        return len(actions)

    def _is_safe_fill(self, action) -> bool:
        """Whether a planned action may run in the supplementary pass."""
        if getattr(action, "action_type", None) is not InteractionType.TYPE:
            return False

        element = getattr(action, "ui_element", None)
        reference = element.get_reference() if element is not None else None
        if reference is None:
            return False

        try:
            existing = reference.get_attribute("value")
        except Exception:
            return False
        return not (existing and str(existing).strip())

    def _classify_all_fields(self, structure) -> dict:
        """Classify each form field using FieldClassifier + SpaCy fallback.

        Args:
            structure: WebpageStructure from _analyze_form_mathematically.

        Returns:
            Dict mapping field element → FieldType.
        """
        classifications: dict = {}
        fields = getattr(structure, "fields", []) or []
        label_pairs = getattr(structure, "label_field_pairs", {}) or {}
        honeypots = set(getattr(structure, "honeypots", []) or [])

        for field_el in fields:
            if field_el in honeypots:
                continue
            try:
                field_type = self._field_classifier.classify(field_el)
            except Exception:
                field_type = None

            if field_type is None or str(field_type).upper() in (
                "UNKNOWN", "NONE",
            ):
                label_text = label_pairs.get(field_el, "")
                if label_text:
                    _, score = self._text_matcher.find_best_match(
                        label_text, []
                    )
                    if score > 0.7:
                        pass

            classifications[field_el] = field_type

        return classifications

    def _fill_standard_fields(self, classifications: dict) -> int:
        """Fill non-custom fields using profile data via SemanticFiller.

        The boolean from ``InteractionPort.fill`` is honoured: a failed fill
        publishes FORM_FIELD_FAILED and is never counted as filled. A failed
        REQUIRED field is additionally recorded so the workflow can refuse to
        submit an application it knows is incomplete (fail closed).

        Args:
            classifications: Dict of field element → FieldType.

        Returns:
            Count of fields successfully filled.
        """
        filled = 0
        structure_label_pairs: dict[Any, Any] = {}

        for field_el, field_type in classifications.items():
            type_name = str(field_type).upper() if field_type else "UNKNOWN"
            if type_name in ("UNKNOWN", "CUSTOM_OPEN_ENDED", "NONE"):
                continue

            label_text = structure_label_pairs.get(field_el, "")
            is_required = bool(getattr(field_el, "is_required", False))
            try:
                value = self._semantic_filler.get_value_for_field(
                    field_type, label_text
                )
            except Exception as exc:
                logger.debug(
                    "SemanticFiller failed for %s: %s", type_name, exc
                )
                continue

            if not value:
                # A required field with no answer is exactly what
                # ApplicationEvidence.unknown_required_field exists to record.
                if is_required:
                    self._failed_required_fields.append(label_text or type_name)
                continue

            try:
                if self._interaction_port.fill(field_el, str(value)):
                    self._event_bus.publish(
                        Event.FORM_FIELD_FILLED,
                        {
                            "field_label": label_text,
                            "field_type": type_name,
                            "strategy": "semantic_filler",
                        },
                    )
                    filled += 1
                    if is_required:
                        self._required_fields_filled += 1
                else:
                    self._event_bus.publish(
                        Event.FORM_FIELD_FAILED,
                        {
                            "field_label": label_text,
                            "field_type": type_name,
                            "strategy": "semantic_filler",
                            "error": "fill returned False",
                        },
                    )
                    if is_required:
                        self._failed_required_fields.append(label_text or type_name)
            except Exception as exc:
                logger.warning(
                    "ApplicationsWorkflow: fill failed | type=%s label=%s error=%s",
                    type_name,
                    label_text,
                    exc,
                )
                try:
                    self._event_bus.publish(
                        Event.FORM_FIELD_FAILED,
                        {
                            "field_label": label_text,
                            "field_type": type_name,
                            "error": str(exc),
                        },
                    )
                except Exception:
                    pass
                if is_required:
                    self._failed_required_fields.append(label_text or type_name)

        return filled

    def _generate_custom_answers(
        self, classifications: dict, structure
    ) -> int:
        """Generate answers for custom/unknown text fields using GPT4All or SpaCy
        fallback.

        The boolean from ``InteractionPort.fill`` is honoured here exactly as in
        ``_fill_standard_fields``: a failed fill publishes FORM_FIELD_FAILED and
        a failed required field is recorded for the fail-closed gate.

        Args:
            classifications: Dict of field element → FieldType.
            structure: WebpageStructure.

        Returns:
            Count of custom fields successfully answered.
        """
        filled = 0
        label_pairs = getattr(structure, "label_field_pairs", {}) or {}

        for field_el, field_type in classifications.items():
            type_name = str(field_type).upper() if field_type else "UNKNOWN"
            label_text = label_pairs.get(field_el, "") or ""
            is_required = bool(getattr(field_el, "is_required", False))

            is_custom = type_name == "CUSTOM_OPEN_ENDED"
            is_substantive_unknown = (
                type_name == "UNKNOWN"
                and (len(label_text) >= 10 or label_text.endswith("?"))
            )
            if not (is_custom or is_substantive_unknown):
                continue

            experiences = getattr(self._profile, "work_experience", []) or []
            scored = []
            for exp in experiences:
                desc = getattr(exp, "description", "") or ""
                try:
                    score = self._text_matcher.get_similarity(
                        label_text, desc
                    )
                except Exception:
                    score = 0.0
                scored.append((score, exp))
            scored.sort(reverse=True)
            best_exp = scored[0][1] if scored else None
            best_desc = (
                getattr(best_exp, "description", "") or ""
                if best_exp
                else ""
            )

            answer: str | None = None

            if self._text_generation_port is not None:
                prompt = (
                    f"Given this work experience:\n"
                    f"{best_desc if best_desc else 'I have relevant professional experience.'}\n\n"
                    f"Answer this job application question naturally, concisely, "
                    f"in first person (2-3 sentences max):\n{label_text}"
                )
                try:
                    answer = self._text_generation_port.generate(
                        prompt,
                        max_tokens=self._cfg(
                            "applications.custom_answer_max_tokens", 150
                        ),
                    )
                    if answer:
                        self._gpt4all_invoked = True
                except Exception as exc:
                    logger.warning(
                        "ApplicationsWorkflow: GPT4All generate failed: %s",
                        exc,
                    )
                    answer = None

            if not answer:
                logger.debug(
                    "ApplicationsWorkflow: GPT4All unavailable for custom answer, "
                    "using SpaCy-ranked experience paragraph"
                )
                answer = best_desc

            if not answer:
                if is_required:
                    self._failed_required_fields.append(label_text or type_name)
                continue

            try:
                if self._interaction_port.fill(field_el, answer):
                    self._event_bus.publish(
                        Event.FORM_FIELD_FILLED,
                        {
                            "field_label": label_text,
                            "field_type": type_name,
                            "strategy": (
                                "gpt4all"
                                if self._gpt4all_invoked
                                else "spacy_fallback"
                            ),
                        },
                    )
                    filled += 1
                    if is_required:
                        self._required_fields_filled += 1
                else:
                    self._event_bus.publish(
                        Event.FORM_FIELD_FAILED,
                        {
                            "field_label": label_text,
                            "field_type": type_name,
                            "strategy": (
                                "gpt4all"
                                if self._gpt4all_invoked
                                else "spacy_fallback"
                            ),
                            "error": "fill returned False",
                        },
                    )
                    if is_required:
                        self._failed_required_fields.append(label_text or type_name)
            except Exception as exc:
                logger.warning(
                    "ApplicationsWorkflow: custom fill failed | label=%s error=%s",
                    label_text,
                    exc,
                )
                try:
                    self._event_bus.publish(
                        Event.FORM_FIELD_FAILED,
                        {
                            "field_label": label_text,
                            "field_type": type_name,
                            "error": str(exc),
                        },
                    )
                except Exception:
                    pass
                if is_required:
                    self._failed_required_fields.append(label_text or type_name)

        return filled

    def _handle_file_uploads(self, structure) -> None:
        """Attach resume and cover-letter documents to upload fields.

        Document values are resolved through the profile's portable-path
        accessors — the only correct way to read them. A configured document
        whose file cannot be found becomes evidence and blocks the fail-closed
        gate, per the ruling:

            state                | DOM required | outcome
            unset                | no           | proceed, INFO log only
            unset                | yes          | block (required, unfillable)
            set, file exists     | either       | upload the resolved absolute path
            set, file missing    | either       | FORM_FIELD_FAILED + block,
                                                 | unconditionally

        Set-but-missing blocks even when the DOM does not mark the upload
        required, because DOM ``required`` is a weak signal on upload controls
        while employers discard resume-less applications — a person who cannot
        tell their resume did not attach is the worst-case user this project
        puts first. Blocking is how they find out.

        The raw-text cover-letter branch honours the ``InteractionPort.fill``
        boolean exactly as the other fill sites do.

        Args:
            structure: The form-analysis result; its fields may include
                file-upload controls.
        """
        personal = getattr(self._profile, "personal_info", None)
        resume_stored = getattr(personal, "resume_path", None)
        cover_letter = getattr(personal, "cover_letter", None)

        fields = getattr(structure, "fields", []) or []
        for field_el in fields:
            try:
                el_type = str(
                    getattr(field_el, "element_type", "")
                    or getattr(field_el, "field_type", "")
                    or ""
                )
                el_name = getattr(field_el, "name", "") or ""
                el_label = str(
                    getattr(field_el, "label", "")
                    or getattr(field_el, "label_text", "")
                    or ""
                )

                is_file = (
                    el_type.lower() in ("file", "file_upload")
                    or "file" in el_name.lower()
                    or "upload" in el_label.lower()
                )
                if not is_file:
                    continue

                is_resume = any(
                    kw in (el_name + " " + el_label).lower()
                    for kw in ("resume", "cv", "curriculum")
                )
                is_cover = any(
                    kw in (el_name + " " + el_label).lower()
                    for kw in ("cover", "letter", "motivation")
                )

                if is_resume:
                    self._attach_document(
                        field_el,
                        el_label,
                        stored=resume_stored,
                        resolver=(
                            personal.get_resolved_resume_path
                            if personal is not None
                            else None
                        ),
                        role="RESUME",
                    )
                elif is_cover:
                    self._attach_cover_letter(
                        field_el,
                        el_label,
                        cover_letter=cover_letter,
                        personal=personal,
                    )
            except Exception as exc:
                logger.warning(
                    "ApplicationsWorkflow: upload field processing failed | %s",
                    exc,
                )

    def _attach_document(
        self,
        field_el: Any,
        el_label: str,
        *,
        stored: Any,
        resolver: Callable[[], Path | None] | None,
        role: str,
    ) -> None:
        """Attach one document to one upload field, per the ruling table.

        The portable-path accessor is consulted only when *stored* names a
        file — that is the caller-side distinction the ruling requires: unset
        is read from the field itself, and the accessor's contract ("None
        means no file to attach") stays intact for its existing consumers.

        Args:
            field_el: The upload control element.
            el_label: Its visible label, used in evidence.
            stored: The raw stored value from the profile.
            resolver: Zero-arg callable returning the resolved absolute Path
                (or None when the file does not exist).
            role: "RESUME" or "COVER_LETTER", for evidence and logs.
        """
        is_required = bool(getattr(field_el, "is_required", False))

        if stored is None or (isinstance(stored, str) and not stored.strip()):
            if is_required:
                self._failed_required_fields.append(el_label or role)
                self._event_bus.publish(
                    Event.FORM_FIELD_FAILED,
                    {
                        "field_label": el_label,
                        "field_type": role,
                        "strategy": "document_upload",
                        "error": f"no {role.lower()} is configured in the profile",
                    },
                )
                logger.warning(
                    "ApplicationsWorkflow: required %s upload has no file "
                    "configured in the profile | label=%s",
                    role.lower(),
                    el_label,
                )
            else:
                logger.info(
                    "ApplicationsWorkflow: no %s configured; optional upload "
                    "skipped | label=%s",
                    role.lower(),
                    el_label,
                )
            return

        resolved = resolver() if resolver is not None else None

        if resolved is None:
            # Set but the file cannot be found — block unconditionally.
            self._event_bus.publish(
                Event.FORM_FIELD_FAILED,
                {
                    "field_label": el_label,
                    "field_type": role,
                    "strategy": "document_upload",
                    "error": f"{role.lower()} file not found: {stored}",
                },
            )
            self._failed_required_fields.append(el_label or role)
            logger.warning(
                "ApplicationsWorkflow: %s file not found — blocking "
                "submission | stored=%s",
                role.lower(),
                stored,
            )
            return

        try:
            self._file_handler.upload(field_el, str(resolved))
        except Exception as exc:
            self._event_bus.publish(
                Event.FORM_FIELD_FAILED,
                {
                    "field_label": el_label,
                    "field_type": role,
                    "strategy": "document_upload",
                    "error": str(exc)[:200],
                },
            )
            if is_required:
                self._failed_required_fields.append(el_label or role)

    def _attach_cover_letter(
        self,
        field_el: Any,
        el_label: str,
        *,
        cover_letter: Any,
        personal: PersonalInfo | None,
    ) -> None:
        """Upload a cover-letter file, or fill a cover-letter text field.

        cover_letter is a union of a file path and raw prose. Paths go through
        the same upload ruling as the resume; prose is typed into the field
        byte-identical to what the user wrote.
        """
        is_required = bool(getattr(field_el, "is_required", False))

        if cover_letter is None or (
            isinstance(cover_letter, str) and not cover_letter.strip()
        ):
            if is_required:
                self._failed_required_fields.append(el_label or "COVER_LETTER")
                self._event_bus.publish(
                    Event.FORM_FIELD_FAILED,
                    {
                        "field_label": el_label,
                        "field_type": "COVER_LETTER",
                        "strategy": "document_upload",
                        "error": "no cover letter is configured in the profile",
                    },
                )
                logger.warning(
                    "ApplicationsWorkflow: required cover-letter field has no "
                    "cover letter configured | label=%s",
                    el_label,
                )
            else:
                logger.info(
                    "ApplicationsWorkflow: no cover letter configured; "
                    "optional field skipped | label=%s",
                    el_label,
                )
            return

        if is_document_path(cover_letter):
            self._attach_document(
                field_el,
                el_label,
                stored=cover_letter,
                resolver=(
                    personal.get_resolved_cover_letter_path
                    if personal is not None
                    else None
                ),
                role="COVER_LETTER",
            )
            return

        # Raw prose: type it into the field, exactly as written.
        try:
            if not self._interaction_port.fill(field_el, cover_letter):
                self._event_bus.publish(
                    Event.FORM_FIELD_FAILED,
                    {
                        "field_label": el_label,
                        "field_type": "COVER_LETTER",
                        "strategy": "raw_text",
                        "error": "fill returned False",
                    },
                )
                if is_required:
                    self._failed_required_fields.append(el_label or "COVER_LETTER")
        except Exception as exc:
            self._event_bus.publish(
                Event.FORM_FIELD_FAILED,
                {
                    "field_label": el_label,
                    "field_type": "COVER_LETTER",
                    "strategy": "raw_text",
                    "error": str(exc)[:200],
                },
            )
            if is_required:
                self._failed_required_fields.append(el_label or "COVER_LETTER")

    def _navigate_multi_page_flow(self) -> bool:
        """Detect and click the Next/Continue button.

        Returns:
            True if navigation succeeded and more pages exist, False on terminal page.
        """
        max_pages = self._cfg("applications.max_pages", self.MAX_PAGES)
        if self._pages_navigated >= max_pages:
            logger.warning(
                "ApplicationsWorkflow: reached MAX_PAGES=%d, stopping navigation",
                max_pages,
            )
            return False

        try:
            next_button = None
            for btn in self._get_clickable_elements():
                btn_text = self._control_label(btn)
                if _label_matches(btn_text, self._NEXT_BUTTON_LABELS):
                    next_button = btn
                    break

            if next_button is None:
                return False

            self._interaction_port.click(next_button)
            self._wait_for_dom_stable()
            self._pages_navigated += 1
            return True

        except Exception as exc:
            logger.debug(
                "ApplicationsWorkflow: multi-page navigation failed: %s", exc
            )
            return False

    def _warn_interruption_unavailable_once(self, reason: str) -> None:
        """Warn once per session that banner/consent dismissal is unavailable.

        A bare ``except: pass`` over a safety collaborator is how a dead
        handler stayed invisible for weeks. Absence degrades — filling
        proceeds — but it degrades LOUDLY, exactly once.
        """
        if self._interruption_warning_emitted:
            return
        self._interruption_warning_emitted = True
        logger.warning(
            "ApplicationsWorkflow: interruption handling unavailable (%s) — "
            "banners and consent overlays will NOT be auto-dismissed for the "
            "rest of this session",
            reason,
        )

    def _handle_interruptions(self, job: Job) -> bool:
        """Dismiss banners and check for CAPTCHA or suspicious redirects.

        Args:
            job: The current job (for context data).

        Returns:
            True to continue, False to pause/abort.
        """
        if self._interruption_handler is None:
            self._warn_interruption_unavailable_once("no handler was wired")
        else:
            try:
                self._interruption_handler.handle_interruptions()
            except Exception as exc:
                self._warn_interruption_unavailable_once(
                    f"{type(exc).__name__}: {exc}"
                )

        # ── Challenge assessment: the ONE predicate (item 12A) ──────────
        # gated/embedded/clear comes from the ONE page verdict
        # (domain/services/page_assessment.py, delegating to
        # challenge_assessment.py for the challenge answer). On "gated" the
        # human is asked IN PLACE — before
        # any outcome is recorded, while the browser is still on the
        # challenge page (ruling A). A solve re-checks the page and continues
        # the SAME attempt. No hand-off task is enqueued: the late, wrong-page
        # escalation that task produced is the defect this replaces.
        current_url, page_title, page_source = job.url, "", ""
        page: PageAssessment | None = None
        try:
            current_url, page_title, page_source = self._page_snapshot(
                fallback_url=job.url
            )
            page = assess_page(
                url=current_url, title=page_title, html=page_source
            )
        except Exception as exc:
            logger.debug(
                "ApplicationsWorkflow: challenge assessment failed: %s", exc
            )

        if page is not None and page.challenge == "gated":
            self._captcha_encountered = True
            self._challenge_signals = list(page.signals)
            logger.info(
                "ApplicationsWorkflow: challenge presented | url=%s signals=%s",
                current_url,
                ",".join(page.signals),
            )
            try:
                self._event_bus.publish(
                    Event.CAPTCHA_DETECTED,
                    {
                        "job_url": job.url,
                        "url": current_url,
                        "signals": list(page.signals),
                        "detail": page.detail,
                    },
                )
            except Exception:
                pass
            if not self._pause_for_challenge(job, current_url, page):
                return False
        elif page is not None and page.challenge == "embedded":
            # A challenge element inside a usable page (a reCAPTCHA widget
            # in a sign-in modal, say): the page can be worked. Record the
            # signals and proceed; the element only matters if a later step
            # trips on it.
            self._challenge_signals = list(page.signals)
            logger.info(
                "ApplicationsWorkflow: embedded challenge element on a "
                "usable page — proceeding | url=%s signals=%s",
                current_url,
                ",".join(page.signals),
            )

        try:
            page_source = getattr(self._browser, "page_source", "") or ""
            form_count = page_source.lower().count("<form")
            job_link_count = page_source.lower().count("job")

            if form_count == 0 and job_link_count > 5:
                current_url = getattr(self._browser, "current_url", "")
                logger.info(
                    "ApplicationsWorkflow: suspicious redirect detected | url=%s",
                    current_url,
                )
                try:
                    self._event_bus.publish(
                        Event.REDIRECT_TO_LIST_DETECTED,
                        {"url": current_url, "job_title": job.title},
                    )
                except Exception:
                    pass

                try:
                    ctx = self._checkpoint_context(
                        Checkpoint.ON_SUSPICIOUS_REDIRECT, job, url=current_url
                    )
                    if self._interrupt_policy.should_pause(
                        Checkpoint.ON_SUSPICIOUS_REDIRECT, ctx
                    ):
                        if self._approval_gate is not None:
                            choice = self._approval_gate(
                                "Suspicious redirect detected. Continue?",
                                ["continue", "skip"],
                                checkpoint="ON_SUSPICIOUS_REDIRECT",
                            )
                            if choice == "skip":
                                return False
                        else:
                            return False
                except Exception:
                    pass
        except Exception as exc:
            logger.debug(
                "ApplicationsWorkflow: redirect check failed: %s", exc
            )

        return True

    def _pause_for_challenge(
        self,
        job: Job,
        challenge_url: str,
        assessment: PageAssessment,
    ) -> bool:
        """Ask the human, in place, while the browser is still on the challenge.

        Ruling A (2026-09-09): pause synchronously at the moment of
        detection, record no terminal outcome before asking, and never
        navigate away. The approval gate blocks the agent thread; nothing
        here touches the browser, so it stays on *challenge_url* and the
        human solves the challenge in the window that is actually showing
        it. No hand-off task is enqueued — the late, wrong-page escalation
        that path produced is the defect this replaces.

        Returns:
            True only when the human reports the challenge solved AND the
            in-place re-check agrees the page is no longer gated — the SAME
            attempt then continues. False for skip, stop, timeout, a raised
            gate, a missing gate, or a page still gated after a reported
            solve; the caller records CAPTCHA_BLOCKED with
            ``self._challenge_note`` saying exactly why.
        """
        self._challenge_pauses += 1
        if self._challenge_pauses > 3:
            self._challenge_note = (
                "challenge kept returning after repeated human solves"
            )
            logger.error(
                "ApplicationsWorkflow: challenge pause budget exhausted — "
                "the challenge returned after %d reported solves | url=%s",
                self._challenge_pauses - 1,
                challenge_url,
            )
            return False
        if self._approval_gate is None:
            self._challenge_note = (
                "a human-verification challenge is presented and no "
                "human-review gate is wired"
            )
            logger.warning(
                "ApplicationsWorkflow: challenge presented but no HITL gate "
                "is wired — recording CAPTCHA_BLOCKED without pausing | "
                "url=%s signals=%s",
                challenge_url,
                ",".join(assessment.signals),
            )
            return False

        try:
            choice = self._approval_gate(
                "A human-verification challenge is blocking the current "
                "page. Solve it in the browser window, then choose how to "
                "continue.",
                ["solved", "skip", "stop"],
                checkpoint="CAPTCHA_PRESENTED",
            )
        except Exception as exc:
            self._challenge_note = f"approval gate raised: {exc}"[:200]
            logger.error(
                "ApplicationsWorkflow: HITL gate raised during challenge "
                "pause | url=%s error=%s",
                challenge_url,
                exc,
                exc_info=True,
            )
            return False

        if choice != "solved":
            self._challenge_note = (
                f"challenge not solved (gate answer: {choice!r})"
            )
            return False

        # Re-check in place: the browser never left the page, so a real
        # solve shows up as a non-gated assessment of the same URL.
        recheck: PageAssessment | None = None
        try:
            url_now, title_now, html_now = self._page_snapshot(
                fallback_url=challenge_url
            )
            recheck = assess_page(url=url_now, title=title_now, html=html_now)
        except Exception as exc:
            logger.debug(
                "ApplicationsWorkflow: post-solve re-check failed: %s", exc
            )

        if recheck is None or recheck.challenge != "gated":
            logger.info(
                "ApplicationsWorkflow: challenge cleared after human solve "
                "— continuing the same attempt | url=%s",
                challenge_url,
            )
            return True

        self._challenge_note = (
            "challenge still presented after a reported solve"
        )
        logger.warning(
            "ApplicationsWorkflow: page still gated after a reported solve "
            "| url=%s",
            challenge_url,
        )
        return False

    # ------------------------------------------------------------------
    # Submission gate
    # ------------------------------------------------------------------

    #: The one answer from an approval gate that authorises a submission.
    #: SessionController.request_approval offers ["submit", "skip"] and returns
    #: "skip" on timeout, so anything else — None, "", a dismissed dialog, an
    #: unexpected UI value — is ambiguity, and ambiguity does not submit.
    SUBMIT_APPROVAL_TOKEN: str = "submit"

    def _checkpoint_context(
        self,
        checkpoint: Checkpoint,
        job: Job,
        *,
        url: str = "",
    ) -> ApplicationContext:
        """Build the real ApplicationContext a checkpoint policy is promised.

        The port defines a frozen dataclass with named fields; passing an ad hoc
        object instead means any policy that reads ``ctx.url`` or ``ctx.company``
        raises — and a raised policy check used to be swallowed into an
        unauthorised submit.

        Args:
            checkpoint: The checkpoint being evaluated.
            job: The job under consideration.
            url: Current page URL, when it differs from the job URL.

        Returns:
            A populated ApplicationContext.
        """
        return ApplicationContext(
            checkpoint=checkpoint,
            job_title=getattr(job, "title", "") or "",
            company=getattr(job, "company", "") or "",
            url=url or (getattr(job, "url", "") or ""),
        )

    #: Set once a session has explained why submissions are being blocked.
    _gate_warning_emitted: bool = False

    def _warn_once_about_the_gate(self, outcome: str, detail: str) -> None:
        """Explain a blocked submission loudly, once per session.

        Fail-closed is only safe if it is also fail-loud. A default install with
        no approval gate wired blocks every submission correctly — and, if that
        only ever reaches evidence records and debug logs, the run looks broken
        rather than safe, which invites the operator to "fix" it by disabling
        the very check protecting them.

        One WARNING per session, carrying the reason AND the remedy. Per-job
        lines stay at INFO so a long run does not turn into a wall of identical
        warnings.

        Args:
            outcome: The evidence outcome recorded for this refusal.
            detail: Why authorisation was refused.
        """
        if outcome != "SUBMISSION_GATE_BLOCKED" or self._gate_warning_emitted:
            return
        self._gate_warning_emitted = True

        logger.warning(
            "Submissions are being BLOCKED by the pre-submit review gate. "
            "This is the safe default, not a fault: reason=%s. "
            "To submit automatically, either wire an approval gate (enable the "
            "review prompt) or remove 'BEFORE_FORM_SUBMIT' from "
            "human_review_checkpoints in your profile to opt into autonomous "
            "submission.",
            detail,
        )

    def _run_statistics(self) -> dict:
        """Per-attempt counters, so every outcome carries what actually happened.

        These were stamped only on the path that reaches a submit attempt. Every
        early return — the submission gate, a CAPTCHA, a login wall, a failed
        navigation, no submit button — recorded zeros for work that had
        demonstrably happened: a live run walked all three pages of a wizard and
        reported ``pages_navigated=0``.

        That matters most where it is least visible: gate-blocked is the DEFAULT
        outcome for an install with no approver wired, so the research dataset
        lost these counters on exactly the runs a cautious user produces.

        ``fields_classified`` and ``required_fields_filled`` are now separate
        counters — two concepts that used to be stamped with one shared value
        by construction.

        Returns:
            The counter fields to merge into any ApplicationEvidence update.
        """
        return {
            "pages_navigated": self._pages_navigated,
            "fields_classified": self._fields_classified,
            "required_fields_filled": self._required_fields_filled,
            "used_gpt4all": self._gpt4all_invoked,
            "captcha_encountered": self._captcha_encountered,
            "challenge_signals": list(self._challenge_signals),
        }

    def _authorize_submission(self, job: Job) -> tuple[bool, str, str]:
        """Decide whether this application may be submitted. Fail closed.

        Submission is authorised by exactly one of two things:

        1. The user's interrupt policy does not ask for a pre-submit pause.
           Removing ``BEFORE_FORM_SUBMIT`` from ``human_review_checkpoints`` is
           a deliberate, sovereign choice to run autonomously, and it is
           honoured — the gate exists to catch ambiguity, never to override a
           user who chose no review.
        2. A wired approval gate returned :attr:`SUBMIT_APPROVAL_TOKEN`.

        Every other path — no approval gate wired, a policy that raised, a gate
        that raised, an unrecognised answer — is ambiguity, and returns refusal.
        The caller records evidence and does not click.

        Args:
            job: The job about to be submitted.

        Returns:
            ``(authorized, outcome, detail)``. When *authorized* is False,
            *outcome* is the ApplicationEvidence outcome to record and *detail*
            explains why, for the log and the evidence error_message.
        """
        ctx = self._checkpoint_context(Checkpoint.BEFORE_FORM_SUBMIT, job)

        try:
            pause_required = bool(
                self._interrupt_policy.should_pause(
                    Checkpoint.BEFORE_FORM_SUBMIT, ctx
                )
            )
        except Exception as exc:
            return (
                False,
                "SUBMISSION_GATE_BLOCKED",
                f"interrupt policy raised: {exc}"[:200],
            )

        if not pause_required:
            # The user configured autonomous submission for this checkpoint.
            return True, "", "no pre-submit review configured"

        if self._approval_gate is None:
            return (
                False,
                "SUBMISSION_GATE_BLOCKED",
                "pre-submit review is required but no approval gate is wired",
            )

        try:
            choice = self._approval_gate(
                "Submit application?",
                ["submit", "skip"],
                checkpoint="BEFORE_FORM_SUBMIT",
            )
        except Exception as exc:
            return (
                False,
                "SUBMISSION_GATE_BLOCKED",
                f"approval gate raised: {exc}"[:200],
            )

        if choice == self.SUBMIT_APPROVAL_TOKEN:
            return True, "", "user approved"

        if choice == "skip":
            return False, "USER_SKIPPED", "user declined at the submit checkpoint"

        return (
            False,
            "SUBMISSION_GATE_BLOCKED",
            f"approval gate returned an unrecognised answer: {choice!r}",
        )

    def _navigate(self, url: str) -> None:
        """Load a URL through the shared PageActionService tool.

        Routing here is what finally activates two features that had been
        written, tested and left on a dead branch: ``navigation_retries``
        (a bounded search for a working URL, so a dead link is abandoned rather
        than hanging the session) and ``warmup_pause`` (a one-time human-scale
        pause before the very first page load, which measurably reduces the
        chance of an immediate CAPTCHA).

        The tool never raises — it returns a falsy ``ActionResult`` — so the
        failure is converted here, preserving this engine's existing
        FAILED_NAVIGATION path exactly.

        Args:
            url: The fully qualified URL to load.

        Raises:
            ApplicationError: If the load did not complete.
        """
        if self._navigation is None:
            # Degradation: no tool (no driver, or direct construction). Fall
            # back to the raw browser rather than inventing a second retry
            # implementation here.
            self._browser.get(url)
            return

        result = self._navigation.navigate(url)
        if not result:
            reason = getattr(result, "reason", "unknown")
            raise ApplicationError(f"navigation did not complete: {reason}")

    def _submit_application(
        self, job: Job, evidence: ApplicationEvidence
    ) -> ApplicationEvidence:
        """Perform pre-submit HITL check, find submit button, click, and scan
        confirmation.

        Uses the ONE page verdict: a confirmation is SUCCESS_PAGE, decided by
        a strong phrase in VISIBLE text or a confirmation URL marker, and the
        verdict's signals name which one decided. The outcome ladder
        (SUBMITTED / PROBABLY_SUBMITTED / AMBIGUOUS) is unchanged.

        Args:
            job: The job being applied to.
            evidence: Evidence accumulator to update with submission outcome.

        Returns:
            Updated ApplicationEvidence with submission outcome, confirmation
            phrases found, cooldown extraction, and confidence score.
        """
        # ── Submission gate (fail closed) ─────────────────────────────────
        # Nothing below this point may run unless submission is authorised.
        # This is deliberately NOT wrapped in a try/except that continues: a
        # swallowed error here is how an unapproved application gets sent.
        authorized, gate_outcome, gate_detail = self._authorize_submission(job)
        if not authorized:
            self._warn_once_about_the_gate(gate_outcome, gate_detail)
            logger.info(
                "ApplicationsWorkflow: submission not authorised | job=%s "
                "outcome=%s reason=%s",
                job.title,
                gate_outcome,
                gate_detail,
            )
            return evidence.model_copy(update={
                "submit_clicked": False,
                "outcome": gate_outcome,
                "error_message": gate_detail,
                "confidence": 1.0,
                **self._run_statistics(),
            })

        logger.debug(
            "ApplicationsWorkflow: submission authorised | job=%s reason=%s",
            job.title,
            gate_detail,
        )

        # ── Find the submit button ────────────────────────────────────────
        submit_button = None
        submit_text = ""
        try:
            for btn in self._get_clickable_elements():
                btn_text = self._control_label(btn)
                if _label_matches(btn_text, self._SUBMIT_KEYWORDS):
                    submit_button = btn
                    submit_text = btn_text[:50]
                    break
        except Exception as exc:
            logger.warning(
                "ApplicationsWorkflow: submit button search failed: %s", exc
            )

        if submit_button is None:
            logger.warning(
                "ApplicationsWorkflow: no submit button found | job=%s",
                job.title,
            )
            return evidence.model_copy(update={
                "submit_button_found": False,
                "outcome": "FAILED_NO_SUBMIT_BUTTON",
                "confidence": 0.95,
                **self._run_statistics(),
            })

        # ── Click submit ──────────────────────────────────────────────────
        evidence = evidence.model_copy(update={
            "submit_button_found": True,
            "submit_button_text": submit_text,
        })

        try:
            self._interaction_port.click(submit_button, irreversible=True)
            evidence = evidence.model_copy(update={
                "submit_clicked": True,
            })
        except Exception as exc:
            return evidence.model_copy(update={
                "submit_clicked": False,
                "outcome": "ERROR",
                "error_message": str(exc)[:200],
                "confidence": 0.90,
                **self._run_statistics(),
            })

        # ── Wait for post-submit page to settle ───────────────────────────
        try:
            if self._dom_observer is not None:
                # FOLLOW-UP: this 15.0 and DOM_STABILIZATION_TIMEOUT_S (8.0)
                # are page-transition budgets, still literals. Collapsing
                # them onto config is a separate single-source change —
                # doing it here would silently shorten live waits.
                self._dom_observer.wait_for_dom_stable(timeout=15.0)
        except Exception:
            pass

        # ── Collect post-submit state ─────────────────────────────────────
        post_url = ""
        post_title = ""
        page_source = ""
        try:
            post_url = getattr(self._browser, "current_url", "") or ""
            post_title = getattr(self._browser, "title", "") or ""
            page_source = getattr(self._browser, "page_source", "") or ""
        except Exception:
            pass
        if not isinstance(post_url, str):
            post_url = ""
        if not isinstance(post_title, str):
            post_title = ""
        if not isinstance(page_source, str):
            page_source = ""

        url_changed = bool(post_url and post_url != job.url)

        # ── Confirmation via the ONE page verdict ─────────────────────────
        # A confirmation is SUCCESS_PAGE: a strong phrase in VISIBLE text
        # (never raw page source) or a confirmation URL marker, with the
        # deciding phrase or marker carried in the verdict's signals. The
        # outcome ladder is unchanged; only the source of "was a
        # confirmation seen?" changes.
        try:
            post_page = assess_page(url=post_url, title=post_title, html=page_source)
            confirmation_seen = post_page.kind is PageType.SUCCESS_PAGE
            found_phrases = [
                signal.split(":", 1)[1]
                for signal in post_page.signals
                if signal.startswith("confirmation-")
            ]
        except Exception:
            confirmation_seen = False
            found_phrases = []

        # ── Classify the outcome ──────────────────────────────────────────
        if confirmation_seen and url_changed:
            outcome = "SUBMITTED"
            confidence = 0.95
        elif confirmation_seen:
            outcome = "SUBMITTED"
            confidence = 0.85
        elif url_changed:
            outcome = "PROBABLY_SUBMITTED"
            confidence = 0.65
        else:
            outcome = "AMBIGUOUS"
            confidence = 0.35

        # ── Cooldown extraction from confirmation page ────────────────────
        for pattern in _COOLDOWN_PATTERNS:
            match = pattern.search(page_source)
            if match:
                months = int(match.group(1))
                if hasattr(job, "metadata"):
                    job.metadata["company_cooldown_days"] = months * 30
                logger.info(
                    "ApplicationsWorkflow: cooldown detected %d months | job=%s",
                    months,
                    job.title,
                )
                break
        else:
            if _KEEP_ON_FILE_PATTERN.search(page_source):
                if hasattr(job, "metadata"):
                    job.metadata["company_cooldown_days"] = 180
                logger.info(
                    "ApplicationsWorkflow: 'keep on file' cooldown (6 months) | job=%s",
                    job.title,
                )

        # ── Build final evidence ──────────────────────────────────────────
        evidence = evidence.model_copy(update={
            "post_submit_url": post_url,
            "page_title_after": post_title,
            "confirmation_text_found": found_phrases,
            "url_changed_after_submit": url_changed,
            "outcome": outcome,
            "confidence": confidence,
            "required_fields_filled": self._required_fields_filled,
            "fields_classified": self._fields_classified,
            "pages_navigated": self._pages_navigated,
            "used_gpt4all": self._gpt4all_invoked,
            "captcha_encountered": self._captcha_encountered,
            "challenge_signals": list(self._challenge_signals),
        })

        # ── Persist to job repository ─────────────────────────────────────
        try:
            if hasattr(self._job_repo, "mark_applied"):
                self._job_repo.mark_applied(job, self._session_id)
        except Exception as exc:
            logger.warning(
                "ApplicationsWorkflow: mark_applied failed: %s", exc
            )

        # ── Publish event ─────────────────────────────────────────────────
        self._event_bus.publish(
            (
                Event.APPLICATION_SUBMITTED
                if evidence.is_likely_success
                else Event.APPLICATION_FAILED
            ),
            {
                "job_title": job.title,
                "company": job.company,
                "url": job.url,
                "evidence": evidence.to_log_string(),
            },
        )
        return evidence

    def _record_application_outcome(self, evidence: ApplicationEvidence) -> None:
        """Persist result and publish the final application event.

        Args:
            evidence: The ApplicationEvidence from the submission attempt.
        """
        job = self._current_job
        if job is None:
            return

        # ── Close the page-analysis feedback loop ────────────────────
        # The router chose a tier for this page; now we know whether the
        # application succeeded. Feed that back so the router learns which tier
        # works for pages like this one. is_deterministic comes from the session
        # plan: on a seeded research run the service drops the write, so two
        # identical runs cannot poison each other's store. Only records when a
        # tier was actually chosen for this job.
        if (
            self._page_analysis_router is not None
            and self._last_analysis_tier is not None
        ):
            try:
                self._page_analysis_router.record_tier_outcome(
                    self._last_page_url,
                    self._last_page_source,
                    self._last_analysis_tier.name,
                    evidence.is_likely_success,
                    is_deterministic=self._plan.is_deterministic,
                )
            except Exception as exc:
                logger.warning(
                    "ApplicationsWorkflow: feedback recording failed: %s", exc
                )
            finally:
                # Reset so the next job cannot misattribute to this one's tier.
                self._last_analysis_tier = None

        status = "APPLIED" if evidence.is_likely_success else "FAILED"
        try:
            if hasattr(self._job_repo, "mark_applied"):
                self._job_repo.mark_applied(
                    job, self._session_id, status=status
                )
        except Exception as exc:
            logger.warning(
                "ApplicationsWorkflow: outcome persistence failed: %s", exc
            )

        event = (
            Event.APPLICATION_SUBMITTED
            if evidence.is_likely_success
            else Event.APPLICATION_FAILED
        )
        payload = {
            "job_url": job.url,
            "job_title": job.title,
            "company": job.company,
            "ats": (
                job.metadata.get("ats")
                if hasattr(job, "metadata")
                else None
            ),
            "pages_navigated": self._pages_navigated,
            "fields_filled": self._fields_filled,
            "used_gpt4all": self._gpt4all_invoked,
            "evidence_outcome": evidence.outcome,
            "evidence_confidence": evidence.confidence,
            "challenge_signals": list(self._challenge_signals),
        }
        try:
            self._event_bus.publish(event, payload)
        except Exception as exc:
            logger.warning(
                "ApplicationsWorkflow: event publish failed: %s", exc
            )

        # ── New research observer: application outcome observation ────────
        # Gated on is_enabled, not merely on an observer being present:
        # composition injects NullResearchObserver (not None) when research
        # is off, and minting below resolves the research salt — so the old
        # check attempted an HMAC on every application with research
        # disabled and swallowed a ResearchSaltError at DEBUG, once per
        # attempt, for nothing. An enabled aggregator resolves the salt at
        # construction, so the mint here can no longer raise for a missing
        # salt.
        if self._research_observer is not None and self._research_observer.is_enabled:
            try:
                company_id = compute_company_id(job.company)
                outcome_obs = ApplicationOutcomeObservation(
                    platform=getattr(job, "source", "unknown"),
                    company_id=company_id,
                    submitted_date=date.today(),
                    acknowledgment_received=evidence.is_likely_success,
                    acknowledgment_date=None,
                )
                self._research_observer.observe_application_outcome(
                    outcome_obs
                )
            except Exception as _exc:
                logger.debug(
                    "ApplicationsWorkflow: observe_application_outcome "
                    "failed (non-fatal): %s",
                    _exc,
                )

    # ──────────────────────────────────────────────────────────────────────────
    # Form reveal — render lazy sections before analysis (tool cadence)
    # ──────────────────────────────────────────────────────────────────────────

    def _reveal_form_content(self) -> None:
        """Wheel-scan the page with the tool's cadence, then return to the top.

        The raw smooth scroll-to-top this replaces could not render
        lazy sections below the fold, so the analysis never saw them. The
        reveal runs in the tool (seeded, measured, bounded by
        ``applications.form_reveal_max_scrolls``); a failure here must never
        abort an application, so it degrades to a debug log.
        """
        if self._navigation is None:
            return
        try:
            self._navigation.reveal_page(
                max_steps=self._cfg("applications.form_reveal_max_scrolls", 8)
            )
        except Exception as exc:
            logger.debug("ApplicationsWorkflow: form reveal failed: %s", exc)

    def run(
        self, job: Job, session_id: str | None = None
    ) -> ApplicationEvidence:
        """Apply to a single job end to end. Returns structured evidence.

        The entire browser-touching portion of the application is optionally
        wrapped in a browser lease (if a ``browser_lease`` was injected) to
        serialize concurrent access to the shared driver instance.

        Truthiness: ``bool(result)`` delegates to ``result.is_likely_success``.

        Args:
            job: The approved Job to apply to. Must have job.url set.
            session_id: Optional session identifier for persistence records.

        Returns:
            ApplicationEvidence with outcome classification and confidence.
        """
        self._current_job = job
        self._pages_navigated = 0
        self._fields_filled = 0
        self._fields_classified = 0
        self._required_fields_filled = 0
        self._failed_required_fields = []
        self._gpt4all_invoked = False
        self._captcha_encountered = False
        self._challenge_signals = []
        self._challenge_note = ""
        self._challenge_pauses = 0
        self._session_id = session_id

        logger.info(
            "ApplicationsWorkflow.run() | job=%s company=%s",
            job.title,
            job.company,
        )

        # One identifier per attempt, stamped on the outcome record and on
        # every per-page research row, so friction data joins to the
        # outcome that produced it. Deterministic: no RNG, so a seeded
        # replay produces the same ids.
        self._attempt_seq += 1
        self._attempt_id = f"{session_id or 'session'}:{self._attempt_seq}"

        evidence = ApplicationEvidence(
            attempt_id=self._attempt_id,
            pre_submit_url=job.url,
            page_title_before=job.title,
        )

        # ── Concurrency safety ───────────────────────────────────────────────
        if self._browser_lease:
            with self._browser_lease.acquire():
                return self._apply_single(job, evidence)
        else:
            return self._apply_single(job, evidence)

    # ──────────────────────────────────────────────────────────────────────────
    # Private core of run() — same logic, extracted for lease wrapping
    # ──────────────────────────────────────────────────────────────────────────

    def _apply_single(
        self, job: Job, evidence: ApplicationEvidence
    ) -> ApplicationEvidence:
        """Core of a single application attempt; called under lease when provided."""
        evidence = self._navigate_to_application(job, evidence)
        if evidence.outcome in (
            "FAILED_NAVIGATION",
            "CAPTCHA_BLOCKED",
            "ACCOUNT_REQUIRED",
        ):
            self._record_application_outcome(evidence)
            return evidence

        # ── Login wall detection (Wave K2) ──────────────────────────────
        if self._detect_login_wall(job):
            evidence = evidence.model_copy(update={
                "outcome": "LOGIN_WALL_BLOCKED",
                "confidence": 0.90,
                "login_wall_encountered": True,
                "error_message": (
                    "Login wall — application form requires authentication"
                ),
                            **self._run_statistics(),
            })
            self._record_application_outcome(evidence)
            return evidence

        if not self._handle_interruptions(job):
            evidence = evidence.model_copy(update={
                "outcome": "CAPTCHA_BLOCKED",
                "confidence": 0.90,
                "captcha_encountered": True,
                "error_message": self._challenge_note or None,
                            **self._run_statistics(),
            })
            self._record_application_outcome(evidence)
            return evidence

        try:
            while True:
                # ── Reveal lazy content before analysis (tool cadence) ──
                self._reveal_form_content()
                # ── iFrame + Shadow DOM fallback (Wave K1) ──────────────
                structure = self._get_form_structure_with_iframe_fallback(job)
                # One research record per wizard step, page-indexed.
                self._observe_form_structure(
                    structure, job, page_index=self._pages_navigated
                )
                classifications = self._classify_all_fields(structure)
                self._fields_classified += len(classifications)

                self._fields_filled += self._fill_standard_fields(
                    classifications
                )
                self._fields_filled += self._generate_custom_answers(
                    classifications, structure
                )
                self._handle_file_uploads(structure)
                self._fields_filled += self._run_strategic_pass()

                if not self._handle_interruptions(job):
                    evidence = evidence.model_copy(update={
                        "outcome": "CAPTCHA_BLOCKED",
                        "confidence": 0.90,
                        "captcha_encountered": True,
                        "error_message": self._challenge_note or None,
                        **self._run_statistics(),
                    })
                    self._record_application_outcome(evidence)
                    return evidence

                has_next = self._navigate_multi_page_flow()
                if not has_next:
                    break

            # ── Required-field gate (fail closed) ────────────────────────
            # A required field that could not be filled means the application
            # is provably incomplete. Submitting it is irreversible, burns the
            # per-company cap and cooldown, and produces an employer-side
            # rejection on record — so this blocks before the submit step.
            # Optional-field failures are recorded (FORM_FIELD_FAILED) but
            # never reach this gate.
            if self._failed_required_fields:
                logger.warning(
                    "ApplicationsWorkflow: aborting before submit — required "
                    "field(s) could not be filled | job=%s fields=%s",
                    job.title,
                    self._failed_required_fields,
                )
                evidence = evidence.model_copy(update={
                    "outcome": "FAILED_REQUIRED_FIELD",
                    "unknown_required_field": self._failed_required_fields[0],
                    "submit_clicked": False,
                    "confidence": 0.90,
                    **self._run_statistics(),
                })
                self._record_application_outcome(evidence)
                return evidence

            evidence = self._submit_application(job, evidence)
            self._record_application_outcome(evidence)

            # ❯❯❯ Close the tab that was opened for the application if any
            if self._context_manager:
                self._context_manager.close_current_tab_and_return()

            logger.info(
                "ApplicationsWorkflow.run() complete | %s pages=%d fields=%d gpt4all=%s",
                evidence.to_log_string(),
                self._pages_navigated,
                self._fields_filled,
                self._gpt4all_invoked,
            )
            return evidence

        finally:
            # ── Always restore to main frame context (Wave K1 safety) ────
            try:
                self._browser.switch_to_default_content()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Research observation helpers
    # ------------------------------------------------------------------

    def _observe_form_structure(
        self, form_structure, job: Job, page_index: int = 0
    ) -> None:
        """Submit one form-structure observation to the research pipeline.

        Called once per wizard page rather than once per application, so a
        multi-step form contributes one record per step. Previously this ran
        after the page loop, where ``structure`` had been rebound on every
        iteration — a five-page application contributed only its last page.

        Args:
            form_structure: A FormStructure from PageUnderstandingPort (or empty stub).
            job: The Job being processed.
            page_index: Zero-based step within the application.
        """
        if self._research_observer is None:
            return
        try:
            posting_hash = (
                job.metadata.get("posting_hash")
                if hasattr(job, "metadata")
                else None
            )
            platform = getattr(job, "source", None)
            fs = (
                form_structure
                if isinstance(form_structure, FormStructure)
                else None
            )

            self._research_observer.observe_form(
                FormObservation(
                    platform=platform or "",
                    company_name=job.company,
                    job_title=job.title,
                    jurisdiction=infer_jurisdiction(
                        job.location or ""
                    ),
                    posting_hash=posting_hash,
                    form_structure=fs or FormStructure(),
                    knockout_thresholds=(
                        self._extract_knockout_thresholds(fs) if fs else {}
                    ),
                    estimated_completion_minutes=(
                        self._estimate_completion_minutes(fs) if fs else None
                    ),
                    application_form_field_count=(
                        len(fs.fields) if fs else 0
                    ),
                    page_index=page_index,
                    attempt_id=self._attempt_id,
                )
            )
        except Exception as exc:
            logger.debug(
                "ApplicationsWorkflow: observe_form failed: %s", exc
            )

    # ------------------------------------------------------------------
    # Static helper methods for research data extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _estimate_completion_minutes(form_structure: FormStructure) -> int:
        """Estimate application completion time in minutes from the form structure.

        Heuristic:
            - 0.5 minutes per field
            - +3.0 minutes for each textarea (essay) field
            - +1.0 minutes for each file upload field

        Returns integer minutes, never raises.
        """
        try:
            if not isinstance(form_structure, FormStructure):
                return 60  # default guess
            total = 0.0
            for field in form_structure.fields:
                total += 0.5
                ftype = field.field_type.lower()
                if ftype == "textarea":
                    total += 3.0
                elif ftype in ("file_upload", "file"):
                    total += 1.0
            return max(1, int(round(total)))
        except Exception:
            return 60

    @staticmethod
    def _extract_knockout_thresholds(
        form_structure: FormStructure,
    ) -> dict[str, float]:
        """Scan form fields for binary/numeric knockout questions and extract
        thresholds.

        Returns a dictionary mapping threshold type (str) to a numeric value
        (float). Example keys: ``"min_years_experience"``,
        ``"min_salary_expectation_ceiling"``, ``"min_degree_level"``.

        Never raises — returns an empty dict on any error.
        """
        thresholds: dict[str, float] = {}
        try:
            if (
                not isinstance(form_structure, FormStructure)
                or not form_structure.fields
            ):
                return thresholds

            for field in form_structure.fields:
                label = (field.label_text or "").lower()
                options = field.options or ()
                combined = " ".join([label] + list(options)).lower()

                # 1. Years of experience threshold
                if (
                    "experience" in label
                    or "years" in label
                    or "experience" in combined
                ):
                    nums = re.findall(
                        r"(\d+)\s*(?:\+)?\s*(?:\s*years?)?", combined
                    )
                    if nums:
                        min_years = min(int(n) for n in nums)
                        thresholds["min_years_experience"] = float(min_years)

                # 2. Salary expectation ceiling
                if (
                    ("salary" in label or "compensation" in label)
                    and "expect" in label
                ):
                    nums = re.findall(r"\$?([\d,]+)", combined)
                    if nums:
                        cleaned = int(nums[-1].replace(",", ""))
                        thresholds["min_salary_expectation_ceiling"] = float(
                            cleaned
                        )

                # 3. Degree level requirement
                if "degree" in label or "education" in label:
                    for keyword, level in _DEGREE_LEVEL_MAP.items():
                        if keyword in combined:
                            thresholds["min_degree_level"] = float(level)
                            break
                    else:
                        if options:
                            for opt in options:
                                opt_lower = opt.lower()
                                for keyword, level in _DEGREE_LEVEL_MAP.items():
                                    if keyword in opt_lower:
                                        thresholds["min_degree_level"] = float(
                                            level
                                        )
                                        break
        except Exception:
            pass
        return thresholds


# --------------------------------------------------------------------------
# Module‑level helper
# --------------------------------------------------------------------------

def _label_matches(label: str, keywords: list[str]) -> bool:
    """Deterministic label match: any keyword as a substring, case-insensitive.

    Replaces the fuzzy 0.7-threshold matcher at the Apply/Next/Submit
    searches: for fixed short English label lists the fuzzy layer added only
    nondeterminism (and an un-mockable dependency in tests).
    """
    text = (label or "").lower()
    return any(keyword in text for keyword in keywords)


def _host_of(url: str) -> str:
    """The lowercase host of a URL, or "" when it cannot be parsed."""
    try:
        return urlparse(url or "").netloc.lower()
    except Exception:
        return ""


def _map_ui_element_type(ui_type: UIElementType) -> str:
    """Map a UIElementType to a simple form field type string."""
    if ui_type in (UIElementType.TEXT_INPUT, UIElementType.TEXT_AREA):
        return "text"
    if ui_type == UIElementType.SELECT:
        return "select"
    if ui_type == UIElementType.CHECKBOX:
        return "checkbox"
    if ui_type == UIElementType.RADIO:
        return "radio"
    if ui_type == UIElementType.BUTTON:
        return "button"
    if ui_type == UIElementType.FILE_UPLOAD:
        return "file"
    return "text"
