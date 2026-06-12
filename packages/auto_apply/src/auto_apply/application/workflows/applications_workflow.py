"""Applications Workflow — fills and submits job application forms.

What this engine does:
    For each vetted job, navigate to the application form, analyze its structure
    mathematically (Hungarian-algorithm field pairing), classify every field, fill
    standard fields from the user profile, answer custom open-ended questions using
    GPT4All (with SpaCy similarity fallback), handle file uploads, navigate multi-page
    forms, and submit the completed application.

11-step sequence:
    1.  _navigate_to_application       — open form URL, detect ATS, click Apply CTA
    2.  _analyze_form_mathematically   — WebpageAnalyzer + Hungarian for field pairing
    3.  _instantiate_form_fsm          — UniversalApplicationStrategy FSM
    4.  _classify_all_fields           — FieldClassifier + SpaCy fallback for ambiguous labels
    5.  _fill_standard_fields          — SemanticFiller → profile → interaction_port
    6.  _generate_custom_answers       — GPT4All or SpaCy-ranked experience paragraph
    7.  _handle_file_uploads           — resume / cover letter upload
    8.  _navigate_multi_page_flow      — detect Next/Continue, click, wait for DOM
    9.  _handle_interruptions          — banners, CAPTCHA detection, redirect detection
    10. _submit_application            — HITL gate, submit button, cooldown extraction
    11. _record_application_outcome    — persist result, publish event, telemetry

Inputs:
    profile           — UserProfile (all form fill data)
    browser           — BrowserInterface (navigation)
    perception_port   — PerceptionPort (page scanning)
    interaction_port  — InteractionPort (clicking, typing)
    webpage_analyzer  — WebpageAnalyzer (mathematical form understanding)
    field_classifier  — FieldClassifier (label → FieldType)
    semantic_filler   — SemanticFiller (FieldType → profile value)
    text_matcher      — TextMatcher (similarity for label disambiguation)
    file_handler      — FileInteractionHandler (resume/cover letter upload)
    interruption_handler — InterruptionHandler (dismisses cookie banners)
    dom_observer      — DOMObserver (waits for DOM stability)
    ats_registry      — ATSRegistry (ATS platform detection)
    job_repo          — JobRepositoryPort (persists outcome)
    task_queue        — WorkQueuePort (CAPTCHA hand-off)
    event_bus         — EventBus
    interrupt_policy  — InterruptPolicyPort (HITL checkpoint decisions)

Outputs:
    Returns bool — True iff application was submitted successfully.
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
import re
from typing import Any

from auto_apply.domain.events import Event
from auto_apply.domain.models.job import Job
from auto_apply.domain.models.profile import UserProfile
from auto_apply.domain.models.work_unit import TaskType, WorkUnit
from auto_apply.domain.ports.interrupt_policy_port import Checkpoint

logger = logging.getLogger(__name__)

_COOLDOWN_PATTERNS = [
    re.compile(r"apply\s+again\s+in\s+(\d+)\s+months?", re.IGNORECASE),
    re.compile(r"(\d+)[- ]month\s+cooldown", re.IGNORECASE),
    re.compile(r"reapply\s+after\s+(\d+)\s+months?", re.IGNORECASE),
]
_KEEP_ON_FILE_PATTERN = re.compile(r"keep\s+your\s+application\s+on\s+file", re.IGNORECASE)


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
        interruption_handler,
        dom_observer,
        ats_registry,
        job_repo,
        task_queue,
        event_bus,
        interrupt_policy,
        text_generation_port=None,
        approval_gate=None,
        research_collector=None,
        config: dict | None = None,
        context_manager=None,              # NEW: ContextManager for tab management
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
            interruption_handler: InterruptionHandler for cookie banner dismissal.
            dom_observer: DOMObserver for waiting on DOM stability.
            ats_registry: ATSRegistry for ATS platform detection.
            job_repo: JobRepositoryPort for persisting application outcomes.
            task_queue: WorkQueuePort for CAPTCHA hand-off WorkUnits.
            event_bus: EventBus for publishing application events.
            interrupt_policy: InterruptPolicyPort for HITL checkpoint decisions.
            text_generation_port: TextGenerationPort | None — GPT4All or None.
            approval_gate: ApprovalGate | None — HITL approval callable.
            research_collector: ResearchCollector | None — anonymized telemetry.
            config: Effective config dict from registry.
            context_manager: ContextManager | None — tab/window switching.
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
        self._text_generation_port = text_generation_port
        self._approval_gate = approval_gate
        self._research_collector = research_collector
        self._config = config or {}
        self._context_manager = context_manager   # NEW

        self._current_job: Job | None = None
        self._pages_navigated: int = 0
        self._fields_filled: int = 0
        self._gpt4all_invoked: bool = False
        self._session_id: str | None = None

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

    def _navigate_to_application(self, job: Job) -> bool:
        """Open the job URL, detect ATS, and click the Apply CTA if on a listing page.

        Args:
            job: The Job to apply to.

        Returns:
            True on successful navigation, False on failure.
        """
        try:
            self._browser.get(job.url)
        except Exception as exc:
            logger.warning(
                "ApplicationsWorkflow: navigation failed | url=%s error=%s",
                job.url, exc,
            )
            return False

        try:
            descriptor = self._ats_registry.match(job.url)
            if descriptor is not None and hasattr(job, "metadata"):
                job.metadata["ats"] = descriptor.name
        except Exception:
            pass

        try:
            page_source = getattr(self._browser, "page_source", "") or ""
            if "<form" not in page_source.lower():
                apply_labels = ["apply now", "apply", "easy apply", "quick apply"]
                buttons = self._get_clickable_elements()
                for button in buttons:
                    label = getattr(button, "text", "") or ""
                    _, score = self._text_matcher.find_best_match(label.lower(), apply_labels)
                    if score > 0.7:
                        self._interaction_port.click(button)
                        self._wait_for_dom_stable()
                        # ❯❯❯ Tab switch detection after clicking Apply CTA ❮❮❮
                        if self._context_manager:
                            self._context_manager.switch_to_new_tab()
                        break
        except Exception as exc:
            logger.debug("ApplicationsWorkflow: apply CTA search failed: %s", exc)

        return True

    def _get_clickable_elements(self) -> list:
        """Return a best-effort list of button/link elements from the current page."""
        try:
            if hasattr(self._browser, "find_elements"):
                from auto_apply.domain.types import Locator  # noqa: PLC0415
                return self._browser.find_elements(Locator.TAG, "button") or []
        except Exception:
            pass
        return []

    def _wait_for_dom_stable(self, timeout: float | None = None) -> None:
        """Wait for DOM to stabilize, with graceful degradation."""
        t = timeout or self.DOM_STABILIZATION_TIMEOUT_S
        try:
            if hasattr(self._dom_observer, "wait_for_dom_stable"):
                self._dom_observer.wait_for_dom_stable(timeout=t)
        except Exception as exc:
            logger.debug("ApplicationsWorkflow: DOM stabilization wait failed: %s", exc)

    def _analyze_form_mathematically(self):
        """Run WebpageAnalyzer to extract form structure.

        Returns:
            WebpageStructure with fields, labels, honeypots.
        """
        try:
            return self._webpage_analyzer.analyze()
        except Exception as exc:
            logger.warning(
                "ApplicationsWorkflow: WebpageAnalyzer failed: %s", exc
            )

        class _EmptyStructure:
            fields = []
            honeypots = []
            label_field_pairs = {}

        return _EmptyStructure()

    def _instantiate_form_fsm(self, structure) -> None:
        """Instantiate the UniversalApplicationStrategy FSM for this page.

        Args:
            structure: WebpageStructure from _analyze_form_mathematically.
        """
        try:
            from auto_apply.domain.applications.fsm.universal import (  # noqa: PLC0415
                UniversalApplicationStrategy,
            )
            self._fsm = UniversalApplicationStrategy(
                browser=self._browser,
                profile=self._profile,
                perception_port=self._perception_port,
                interaction_port=self._interaction_port,
            )
        except Exception as exc:
            logger.debug(
                "ApplicationsWorkflow: FSM instantiation failed (non-fatal): %s", exc
            )
            self._fsm = None

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

            if field_type is None or str(field_type).upper() in ("UNKNOWN", "NONE"):
                label_text = label_pairs.get(field_el, "")
                if label_text:
                    _, score = self._text_matcher.find_best_match(label_text, [])
                    if score > 0.7:
                        pass

            classifications[field_el] = field_type

        return classifications

    def _fill_standard_fields(self, classifications: dict) -> int:
        """Fill non-custom fields using profile data via SemanticFiller.

        Args:
            classifications: Dict of field element → FieldType.

        Returns:
            Count of fields successfully filled.
        """
        filled = 0
        structure_label_pairs = {}

        for field_el, field_type in classifications.items():
            type_name = str(field_type).upper() if field_type else "UNKNOWN"
            if type_name in ("UNKNOWN", "CUSTOM_OPEN_ENDED", "NONE"):
                continue

            label_text = structure_label_pairs.get(field_el, "")
            try:
                value = self._semantic_filler.get_value_for_field(field_type, label_text)
            except Exception as exc:
                logger.debug("SemanticFiller failed for %s: %s", type_name, exc)
                continue

            if not value:
                continue

            try:
                self._interaction_port.fill(field_el, str(value))
                self._event_bus.publish(
                    Event.FORM_FIELD_FILLED,
                    {
                        "field_label": label_text,
                        "field_type": type_name,
                        "strategy": "semantic_filler",
                    },
                )
                filled += 1
            except Exception as exc:
                logger.warning(
                    "ApplicationsWorkflow: fill failed | type=%s label=%s error=%s",
                    type_name, label_text, exc,
                )
                try:
                    self._event_bus.publish(
                        Event.FORM_FIELD_FAILED,
                        {"field_label": label_text, "field_type": type_name, "error": str(exc)},
                    )
                except Exception:
                    pass

        return filled

    def _generate_custom_answers(self, classifications: dict, structure) -> int:
        """Generate answers for custom/unknown text fields using GPT4All or SpaCy fallback.

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
                    score = self._text_matcher.get_similarity(label_text, desc)
                except Exception:
                    score = 0.0
                scored.append((score, exp))
            scored.sort(reverse=True)
            best_exp = scored[0][1] if scored else None
            best_desc = getattr(best_exp, "description", "") or "" if best_exp else ""

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
                        max_tokens=self._cfg("applications.custom_answer_max_tokens", 150),
                    )
                    if answer:
                        self._gpt4all_invoked = True
                except Exception as exc:
                    logger.warning(
                        "ApplicationsWorkflow: GPT4All generate failed: %s", exc
                    )
                    answer = None

            if not answer:
                logger.debug(
                    "ApplicationsWorkflow: GPT4All unavailable for custom answer, "
                    "using SpaCy-ranked experience paragraph"
                )
                answer = best_desc

            if not answer:
                continue

            try:
                self._interaction_port.fill(field_el, answer)
                self._event_bus.publish(
                    Event.FORM_FIELD_FILLED,
                    {
                        "field_label": label_text,
                        "field_type": type_name,
                        "strategy": "gpt4all" if self._gpt4all_invoked else "spacy_fallback",
                    },
                )
                filled += 1
            except Exception as exc:
                logger.warning(
                    "ApplicationsWorkflow: custom fill failed | label=%s error=%s",
                    label_text, exc,
                )
                try:
                    self._event_bus.publish(
                        Event.FORM_FIELD_FAILED,
                        {"field_label": label_text, "field_type": type_name, "error": str(exc)},
                    )
                except Exception:
                    pass

        return filled

    def _handle_file_uploads(self, structure) -> None:
        """Upload resume and cover letter files.

        Args:
            structure: WebpageStructure with file fields.
        """
        personal = getattr(self._profile, "personal_info", None)
        resume_path = getattr(personal, "resume_path", None)
        cover_letter = getattr(personal, "cover_letter", None)

        fields = getattr(structure, "fields", []) or []
        for field_el in fields:
            try:
                el_type = getattr(field_el, "element_type", "") or ""
                el_name = getattr(field_el, "name", "") or ""
                el_label = getattr(field_el, "label", "") or ""

                is_file = (
                    el_type == "file"
                    or "file" in el_name.lower()
                    or "upload" in el_label.lower()
                )
                if not is_file:
                    continue

                is_resume = any(
                    kw in (el_name + el_label).lower()
                    for kw in ("resume", "cv", "curriculum")
                )
                is_cover = any(
                    kw in (el_name + el_label).lower()
                    for kw in ("cover", "letter", "motivation")
                )

                if is_resume and resume_path:
                    self._file_handler.upload(field_el, str(resume_path))
                elif is_cover and cover_letter:
                    cover_str = str(cover_letter)
                    if cover_str.endswith((".pdf", ".doc", ".docx", ".txt")):
                        self._file_handler.upload(field_el, cover_str)
                    else:
                        self._interaction_port.fill(field_el, cover_str)
            except Exception as exc:
                logger.warning(
                    "ApplicationsWorkflow: file upload failed for field: %s", exc
                )

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
            buttons = self._get_clickable_elements()
            next_button = None
            for btn in buttons:
                btn_text = getattr(btn, "text", "") or ""
                _, score = self._text_matcher.find_best_match(
                    btn_text.lower(), self._NEXT_BUTTON_LABELS
                )
                if score > 0.7:
                    next_button = btn
                    break

            if next_button is None:
                return False

            self._interaction_port.click(next_button)
            self._wait_for_dom_stable()
            self._pages_navigated += 1
            return True

        except Exception as exc:
            logger.debug("ApplicationsWorkflow: multi-page navigation failed: %s", exc)
            return False

    def _handle_interruptions(self, job: Job) -> bool:
        """Dismiss banners and check for CAPTCHA or suspicious redirects.

        Args:
            job: The current job (for context data).

        Returns:
            True to continue, False to pause/abort.
        """
        try:
            self._interruption_handler.handle()
        except Exception:
            pass

        try:
            browser_state = None
            if hasattr(self._browser, "get_current_state"):
                browser_state = self._browser.get_current_state()

            page_source = getattr(self._browser, "page_source", "") or ""
            captcha_indicators = [
                "recaptcha", "hcaptcha", "cf-turnstile", "captcha",
                "i am not a robot", "verify you are human",
            ]
            if any(ind in page_source.lower() for ind in captcha_indicators):
                logger.info(
                    "ApplicationsWorkflow: CAPTCHA detected | url=%s",
                    getattr(self._browser, "current_url", "unknown"),
                )
                try:
                    self._event_bus.publish(Event.CAPTCHA_DETECTED, {"job_url": job.url})
                    self._task_queue.queue_task(
                        WorkUnit(
                            priority=1,
                            task_type=TaskType.HANDLE_CAPTCHA,
                            payload=job,
                            source="applications_workflow",
                            context_data={
                                "return_state": "applying",
                                "return_url": getattr(self._browser, "current_url", job.url),
                            },
                        )
                    )
                except Exception:
                    pass
                return False
        except Exception as exc:
            logger.debug("ApplicationsWorkflow: interruption check failed: %s", exc)

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
                    ctx = type("ctx", (), {"job": job, "url": current_url})()
                    if self._interrupt_policy.should_pause(
                        Checkpoint.ON_SUSPICIOUS_REDIRECT, ctx
                    ):
                        if self._approval_gate is not None:
                            choice = self._approval_gate(
                                "Suspicious redirect detected. Continue?",
                                ["continue", "skip"],
                                f"redirect_{job.url}",
                            )
                            if choice == "skip":
                                return False
                        else:
                            return False
                except Exception:
                    pass
        except Exception as exc:
            logger.debug("ApplicationsWorkflow: redirect check failed: %s", exc)

        return True

    def _submit_application(self, job: Job) -> bool:
        """Perform pre-submit HITL check, find submit button, click, and scan confirmation.

        Args:
            job: The job being applied to.

        Returns:
            True on successful submission, False otherwise.
        """
        try:
            ctx = type("ctx", (), {"job": job})()
            if self._interrupt_policy.should_pause(Checkpoint.BEFORE_FORM_SUBMIT, ctx):
                if self._approval_gate is not None:
                    choice = self._approval_gate(
                        "Submit application?",
                        ["submit", "skip"],
                        f"submit_{job.url}",
                    )
                    if choice == "skip":
                        logger.info(
                            "ApplicationsWorkflow: user skipped submission | job=%s",
                            job.title,
                        )
                        return False
        except Exception as exc:
            logger.debug("ApplicationsWorkflow: HITL submit check failed: %s", exc)

        try:
            buttons = self._get_clickable_elements()
            submit_button = None
            for btn in buttons:
                btn_text = getattr(btn, "text", "") or ""
                _, score = self._text_matcher.find_best_match(
                    btn_text.lower(), self._SUBMIT_KEYWORDS
                )
                if score > 0.7:
                    submit_button = btn
                    break

            if submit_button is None:
                logger.warning(
                    "ApplicationsWorkflow: no submit button found | job=%s", job.title
                )
                return False

            self._interaction_port.click(submit_button)

            try:
                if hasattr(self._dom_observer, "wait_for_dom_stable"):
                    self._dom_observer.wait_for_dom_stable(timeout=15.0)
            except Exception:
                pass

            page_source = getattr(self._browser, "page_source", "") or ""
            for pattern in _COOLDOWN_PATTERNS:
                match = pattern.search(page_source)
                if match:
                    months = int(match.group(1))
                    if hasattr(job, "metadata"):
                        job.metadata["company_cooldown_days"] = months * 30
                    logger.info(
                        "ApplicationsWorkflow: cooldown detected %d months | job=%s",
                        months, job.title,
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

            try:
                if hasattr(self._job_repo, "mark_applied"):
                    self._job_repo.mark_applied(job, self._session_id)
            except Exception as exc:
                logger.warning("ApplicationsWorkflow: mark_applied failed: %s", exc)

            self._event_bus.publish(
                Event.APPLICATION_SUBMITTED,
                {
                    "job_title": job.title,
                    "company": job.company,
                    "url": job.url,
                },
            )
            return True

        except Exception as exc:
            logger.warning(
                "ApplicationsWorkflow: submission failed | job=%s error=%s",
                job.title, exc,
            )
            return False

    def _record_application_outcome(self, result: bool) -> None:
        """Persist result and publish the final application event.

        Args:
            result: True if application was submitted successfully.
        """
        job = self._current_job
        if job is None:
            return

        status = "APPLIED" if result else "FAILED"
        try:
            if hasattr(self._job_repo, "mark_applied"):
                self._job_repo.mark_applied(job, self._session_id, status=status)
        except Exception as exc:
            logger.warning("ApplicationsWorkflow: outcome persistence failed: %s", exc)

        event = Event.APPLICATION_SUBMITTED if result else Event.APPLICATION_FAILED
        payload = {
            "job_url": job.url,
            "job_title": job.title,
            "company": job.company,
            "ats": job.metadata.get("ats") if hasattr(job, "metadata") else None,
            "pages_navigated": self._pages_navigated,
            "fields_filled": self._fields_filled,
            "used_gpt4all": self._gpt4all_invoked,
        }
        try:
            self._event_bus.publish(event, payload)
        except Exception as exc:
            logger.warning("ApplicationsWorkflow: event publish failed: %s", exc)

        if self._research_collector is not None:
            try:
                self._research_collector.record_signal(
                    event,
                    {
                        "ats": payload["ats"],
                        "pages_navigated": self._pages_navigated,
                        "fields_filled": self._fields_filled,
                        "used_gpt4all": self._gpt4all_invoked,
                        "result": result,
                    },
                )
            except Exception:
                pass

    def run(self, job: Job, session_id: str | None = None) -> bool:
        """Apply to a single job end to end.

        Navigates to the application form, fills all fields using profile data,
        handles multi-page flows and interruptions, and submits the application.

        The three intelligence layers used in order:
          1. Mathematical: WebpageAnalyzer + Hungarian algorithm (form structure)
          2. Linguistic: SpaCy via TextMatcher (field classification, label similarity)
          3. Generative: GPT4All via TextGenerationPort (custom question answers)

        Each layer degrades gracefully if its dependency is unavailable.

        Args:
            job: The approved Job to apply to. Must have job.url set.
            session_id: Optional session identifier for persistence records.

        Returns:
            True if application was submitted successfully.
            False on any unrecoverable failure (CAPTCHA, redirect, form error, HITL skip).
        """
        self._current_job = job
        self._pages_navigated = 0
        self._fields_filled = 0
        self._gpt4all_invoked = False
        self._session_id = session_id

        logger.info(
            "ApplicationsWorkflow.run() | job=%s company=%s", job.title, job.company
        )

        if not self._navigate_to_application(job):
            self._record_application_outcome(False)
            return False

        if not self._handle_interruptions(job):
            self._record_application_outcome(False)
            return False

        while True:
            structure = self._analyze_form_mathematically()
            self._instantiate_form_fsm(structure)
            classifications = self._classify_all_fields(structure)
            self._fields_filled += self._fill_standard_fields(classifications)
            self._fields_filled += self._generate_custom_answers(classifications, structure)
            self._handle_file_uploads(structure)

            if not self._handle_interruptions(job):
                self._record_application_outcome(False)
                return False

            has_next = self._navigate_multi_page_flow()
            if not has_next:
                break

        result = self._submit_application(job)
        self._record_application_outcome(result)

        # ❯❯❯ Close the tab that was opened for the application if any ❮❮❮
        if self._context_manager:
            self._context_manager.close_current_tab_and_return()

        logger.info(
            "ApplicationsWorkflow.run() complete | result=%s pages=%d fields=%d gpt4all=%s",
            result, self._pages_navigated, self._fields_filled, self._gpt4all_invoked,
        )
        return result