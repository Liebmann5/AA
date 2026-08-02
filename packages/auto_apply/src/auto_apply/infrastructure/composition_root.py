"""Composition root — the only wiring layer.

This module is the ONLY place in the codebase that may import from both
``adapters/`` and ``domain/`` simultaneously. Every concrete adapter,
filter, engine, and port dependency is constructed here and injected into
the components that need them.

`CapabilitiesRegistry` is re-exported here for backward compatibility; new
code should import it directly from `auto_apply.infrastructure.registry`.

Example:
    >>> from auto_apply.infrastructure.composition_root import build_orchestrator
    >>> orchestrator = build_orchestrator(registry)
    >>> orchestrator.run()
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from auto_apply.application.services.i18n import configure_locale
from auto_apply.application.services.mathematical_web_analyzer import MathematicalWebAnalyzer
from auto_apply.domain.config import (
    DB_PATH,
    IS_FROZEN,
    USER_DATA_DIR,
)
from auto_apply.domain.models.timing import BehaviorParameters
from auto_apply.domain.ports.browser_port import BrowserInterface
from auto_apply.infrastructure.registry import (
    CapabilitiesRegistry,
    _GEO_DB_PATH,
)
from auto_apply.infrastructure.browser_cascade import BrowserCascade
from auto_apply.infrastructure.driver_registry import DriverRegistry
from auto_apply.infrastructure.browser_lease_manager import BrowserLeaseManager
from auto_apply.adapters.secondary.browser.selenium_provider import SeleniumProvider
from auto_apply.adapters.secondary.browser.playwright_provider import PlaywrightProvider

if TYPE_CHECKING:
    from auto_apply.application.agent.orchestrator import AgentOrchestrator
    #from auto_apply.application.agent.task_kernel import TaskKernel
    from auto_apply.domain.models.profile import UserProfile
    from auto_apply.application.services.session_controller import SessionController

# Re-export so existing callers don't break.
__all__ = ["CapabilitiesRegistry", "build_orchestrator", "build_session", "build_session_controller"]

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# CONSTANTS
# --------------------------------------------------------------------------

# BrowserLeaseManager MUST always be created with max_concurrent=1.
# The lease wraps a SINGLE shared browser driver instance.  Any value above 1
# permits concurrent access to the same instance, which is the exact bug the
# lease exists to prevent.  Never derive this from config or session plan.
_MAX_LEASES_PER_SHARED_DRIVER = 1


# --------------------------------------------------------------------------
# MAIN WIRING FUNCTION
# --------------------------------------------------------------------------

def build_orchestrator(  # noqa: PLR0914
    registry: CapabilitiesRegistry,
    driver: "BrowserInterface | None" = ...,  # type: ignore[assignment]
) -> "AgentOrchestrator":
    """Assembles and returns a fully wired AgentOrchestrator.

    This is the single authorised place in the codebase that may import from
    both ``adapters/`` and ``domain/`` simultaneously. Every concrete adapter,
    filter, engine, and port dependency is constructed here and injected into
    the components that need them. Callers receive an orchestrator that is
    ready to call ``.run()``.

    Wiring order:
        0. Browser cascade → driver or None
        1. Persistence adapters — DatabaseManager, JobRepository, GeoDatabaseRepository
        2. Domain filters       — ThrottlingFilter, SpatialLocationFilter, logic filters
        3. Shared ports         — perception, interaction, reasoning, interrupt policy
        4. Discovery providers  — GoogleProvider, BingProvider, IndeedProvider
        4b. Workflows           — DiscoveryWorkflow, VettingWorkflow, ApplicationsWorkflow
        5. Capability profile   — built from registry + driver status, injected into DB
        6. AgentOrchestrator    — dispatches each TaskType to its workflow

    Args:
        registry: A fully initialised CapabilitiesRegistry for this environment.
        driver: Pre-acquired browser driver. Pass ``None`` to skip the cascade
            entirely (static/BS4 perception only). Omit to run the cascade.

    Returns:
        A fully wired AgentOrchestrator ready to call ``.run()``.
    """
    # ── 0. Browser cascade → driver or None ──────────────────────────────────
    from auto_apply.adapters.secondary.browser.playwright_adapter import (  # noqa: PLC0415
        PlaywrightAdapter,
    )
    from auto_apply.adapters.secondary.browser.selenium_adapter import (  # noqa: PLC0415
        SeleniumAdapter,
    )

    # Build BehaviorParameters early so we can seed randomness for providers
    # and adapters — must happen before any browser instance is created.
    _effective_config = registry.get_all_effective_config()
    behavior_params = BehaviorParameters.from_config(_effective_config)

    _cascade_skipped = driver is not ...
    if _cascade_skipped:
        # Caller supplied a driver (or explicit None) — skip the cascade.
        pass
    else:
        driver_registry = DriverRegistry()
        try:
            driver_registry.register(SeleniumProvider())
        except Exception as _exc:
            logger.warning("build_orchestrator: SeleniumProvider registration failed: %s", _exc)
        try:
            driver_registry.register(PlaywrightProvider())
        except Exception as _exc:
            logger.warning("build_orchestrator: PlaywrightProvider registration failed: %s", _exc)

        adapter_map = {
            "selenium": lambda raw: SeleniumAdapter(
                raw,
                rng=behavior_params.make_rng("selenium.adapter"),
            ),
            "playwright": lambda raw: PlaywrightAdapter(
                page=raw,
                browser=raw._pw_browser,
                playwright=raw._pw_playwright,
                rng=behavior_params.make_rng("playwright.adapter"),
            ),
        }

        # Re-register providers with seeded RNG instances
        try:
            driver_registry.register(
                SeleniumProvider(rng=behavior_params.make_rng("selenium.provider"))
            )
        except Exception as _exc:
            logger.warning("build_orchestrator: SeleniumProvider registration failed: %s", _exc)
        try:
            driver_registry.register(
                PlaywrightProvider()  # PlaywrightProvider does not use randomness yet
            )
        except Exception as _exc:
            logger.warning("build_orchestrator: PlaywrightProvider registration failed: %s", _exc)

        cascade = BrowserCascade(registry, driver_registry=driver_registry, adapter_map=adapter_map)
        driver = cascade.acquire_driver()

    if driver is None:
        logger.info(
            "build_orchestrator: no browser driver — falling back to static perception"
        )

    # ── Audit observer (defined before its first use) ─────────────────────
    # Observation only: records what extraction saw, never changes it.
    from auto_apply.application.services.auditing.discovery_math_auditor import (  # noqa: PLC0415
        DiscoveryMathAuditor,
    )

    _extraction_observer = DiscoveryMathAuditor()

    # ── Retrieve the frozen SessionPlan ──────────────────────────────────────
    plan = registry.get_session_plan()

    # ── Build the mathematical perception adapter (only when a live browser exists) ──
    math_perception_port = None
    if driver is not None:
        try:
            from auto_apply.adapters.secondary.perception.math_dom_adapter import MathDOMAdapter  # noqa: PLC0415
            math_perception_port = MathDOMAdapter(browser=driver, observer=_extraction_observer)
        except Exception as _exc:
            logger.debug("build_orchestrator: MathDOMAdapter unavailable: %s", _exc)

    # ── Shared MathematicalWebAnalyzer (injected into engines) ─────────────────
    math_analyzer = MathematicalWebAnalyzer(perception_port=math_perception_port) if math_perception_port is not None else None

    # ── 1. Persistence adapters ───────────────────────────────────────────────
    from auto_apply.adapters.secondary.persistence.database import (  # noqa: PLC0415
        DatabaseManager,
    )
    from auto_apply.adapters.secondary.persistence.geodatabase import (  # noqa: PLC0415
        GeoDatabaseRepository,
    )
    from auto_apply.adapters.secondary.persistence.job_repository import (  # noqa: PLC0415
        JobRepository,
    )

    db_manager = DatabaseManager()
    job_repo = JobRepository(db_manager)
    geo_db = GeoDatabaseRepository(_GEO_DB_PATH)

    # ── 2. Domain filters — injected with their port dependencies ─────────────
    from auto_apply.domain.vetting.logic_filters import (  # noqa: PLC0415
        CompanyBlacklistFilter,
        LocationLogicFilter,
        TitleLogicFilter,
    )
    from auto_apply.domain.vetting.spatial_filter import (  # noqa: PLC0415
        SpatialLocationFilter,
    )
    from auto_apply.domain.vetting.throttling_filter import (  # noqa: PLC0415
        ThrottlingFilter,
    )

    profile = registry.get_active_profile()

    # ── Activate the session locale ──────────────────────────────────────────
    # The i18n subsystem defaults to en/US/USD until configured. The GUI wires
    # this for its own labels, but a headless or CLI session never does, so
    # every non-GUI run ignored ApplicationConfig.locale and es.json was never
    # loaded. Read the profile's locale here and let None fall through to
    # detect_locale() -- which is exactly what configure_locale already does.
    # This keeps the user's reading language separate from any job jurisdiction:
    # only the interface language is set here.
    _app_config = getattr(profile, "app_config", None)
    _profile_locale = getattr(_app_config, "locale", None)
    configure_locale(language=_profile_locale)
    resources = registry.get_runtime_profile()

    filter_pipeline = [
        ThrottlingFilter(
            profile,
            job_repo,
            cooldown_days_default=registry.get_effective_config(
                "cooldown_days_default", 180
            ),
        ),
        SpatialLocationFilter(profile, geo_db),
        LocationLogicFilter(profile),
        CompanyBlacklistFilter(profile),
        TitleLogicFilter(profile),
    ]

    # ── 2b. NLP text matching — one shared instance across all workflows ───────
    from auto_apply.application.services.text_matching import TextMatcher  # noqa: PLC0415

    text_matcher = TextMatcher(prefer_small=registry.is_low_resource_environment())
    _search_prefs = getattr(profile, "search_preferences", None)
    _profile_skills = getattr(_search_prefs, "skills", []) or []
    if _profile_skills:
        text_matcher.load_skills_vocabulary(_profile_skills)

    # ── 2c. GPT4All text generation adapter (lazy-loaded on first call) ────────
    from auto_apply.adapters.secondary.reasoning.gpt4all_adapter import (  # noqa: PLC0415
        GPT4AllAdapter,
    )

    gpt4all_adapter = None if registry.is_low_resource_environment() else GPT4AllAdapter()

    # ── 2d. NLP-powered vetting filters (ordered cheapest→most expensive) ──────
    from auto_apply.domain.vetting.experience_filter import ExperienceFilter  # noqa: PLC0415
    from auto_apply.domain.vetting.hard_skills_filter import HardSkillsFilter  # noqa: PLC0415
    from auto_apply.domain.vetting.role_alignment_filter import RoleAlignmentFilter  # noqa: PLC0415

    filter_pipeline.extend([
        ExperienceFilter(profile),
        HardSkillsFilter(profile),
        RoleAlignmentFilter(profile, similarity_port=text_matcher),
    ])

    # ── 3. Shared ports for the workflow layer ────────────────────────────────
    from auto_apply.application.agent.event_bus import EventBus  # noqa: PLC0415

    event_bus = EventBus()

    from auto_apply.adapters.secondary.interaction.human_like_adapter import (  # noqa: PLC0415
        InteractionExecutor,
    )
    from auto_apply.adapters.secondary.perception.dom_adapter import (  # noqa: PLC0415
        DOMScanner,
    )
    from auto_apply.adapters.secondary.reasoning.rule_based_adapter import (  # noqa: PLC0415
        FormSolver,
    )

    if driver is not None:
        perception_strategy = registry.get_effective_config("perception_strategy", "math")
        use_math = (
            perception_strategy == "math"
            or (not registry.is_low_resource_environment() and perception_strategy == "auto")
        )
        if use_math:
            from auto_apply.adapters.secondary.perception.math_perception_adapter import (  # noqa: PLC0415
                MathPerceptionAdapter,
            )
            perception_port = MathPerceptionAdapter(driver)
        else:
            perception_port = DOMScanner(driver)
    else:
        # Zero-browser fallback: static HTML perception via BeautifulSoup.
        from auto_apply.adapters.secondary.network.urllib_http_client import (  # noqa: PLC0415
            UrllibHTTPClient,
        )
        from auto_apply.adapters.secondary.perception.bs4_adapter import (  # noqa: PLC0415
            BS4PerceptionAdapter,
        )

        perception_port = BS4PerceptionAdapter(UrllibHTTPClient())
        logger.info(
            "build_orchestrator: no browser driver — using BS4PerceptionAdapter (static HTML only)"
        )

    # ── The shared element-interaction tool ───────────────────────────────────
    # PageActionService owns every click, all pacing, and the seeded RNG; the
    # InteractionExecutor injected into the engines delegates to it. The RNG
    # namespace is allocated unconditionally so seeded stream allocation does
    # not depend on whether a driver was acquired.
    from auto_apply.application.services.page_action.service import (  # noqa: PLC0415
        PageActionService,
    )

    interaction_pacing_rng = behavior_params.make_rng("interaction.pacing")

    page_action_tool = (
        PageActionService(browser=driver, registry=registry, rng=interaction_pacing_rng)
        if driver is not None
        else None
    )

    # ── DOM readiness ─────────────────────────────────────────────────────
    # Built here rather than beside the workflow so the handlers can have it
    # too: ONE observer instance is shared by the Applications engine and
    # every form handler. Budgets come from config, never from literals.
    dom_readiness = None
    if driver is not None:
        try:
            from auto_apply.adapters.secondary.interaction.dom_observer import (  # noqa: PLC0415
                DOMObserver,
            )
            _readiness_cfg = registry.get_all_effective_config()
            dom_readiness = DOMObserver(
                browser=driver,
                stability_timeout_s=_readiness_cfg.get(
                    "dom_stabilization_timeout_s", 3.0
                ),
                poll_interval_s=_readiness_cfg.get(
                    "dom_stabilization_poll_interval_s", 0.25
                ),
            )
        except Exception as _exc:
            logger.debug("build_orchestrator: DOMObserver unavailable: %s", _exc)

    interaction_port = (
        InteractionExecutor(
            driver,
            text_matcher=text_matcher,
            page_action=page_action_tool,
            readiness=dom_readiness,
        )
        if driver is not None
        else None
    )
    # ── Page-advance collaborators ────────────────────────────────────────
    # Built once and shared. Discovery adapters receive them instead of
    # importing scrolling and pagination across the layer boundary.
    _page_scroller = None
    _paginator = None
    _max_pages_per_query = 1

    # ── Audit observers ───────────────────────────────────────────────────
    # Observation only: these record what extraction saw and never change
    # what it produces. Adapters receive them instead of importing the
    # auditing services across the layer boundary.
    _audit_reporter = None

    # ── Forced extraction tier (opt-in capability, off by default) ────────
    # Empty/absent/unrecognised leaves tier selection exactly as it was.
    from auto_apply.domain.models.analysis_tier import PageAnalysisTier  # noqa: PLC0415

    _forced_tier = PageAnalysisTier.from_name(
        registry.get_all_effective_config().get("force_analysis_tier")
    )
    if _forced_tier is not None:
        logger.info(
            "build_orchestrator: extraction tier forced to %s for every page",
            _forced_tier.name,
        )

    reasoning_port = FormSolver(profile, text_matcher=text_matcher)

    from auto_apply.domain.ports.interrupt_policy_port import ProfileBasedInterruptPolicy  # noqa: PLC0415
    app_config = getattr(profile, "app_config", None)
    _configured_checkpoints = getattr(app_config, "human_review_checkpoints", None)
    interrupt_policy = ProfileBasedInterruptPolicy(_configured_checkpoints)

    _ats_registry = None
    try:
        from auto_apply.adapters.secondary.discovery.ats_registry import (  # noqa: PLC0415
            ATSRegistry,
        )
        _ats_registry = ATSRegistry()
    except Exception as _exc:
        logger.debug("build_orchestrator: ATSRegistry unavailable: %s", _exc)

    # ── Build PageUnderstandingPort adapter (if driver available) ────────────
    page_understanding_port = None
    if driver is not None:
        try:
            from auto_apply.adapters.secondary.perception.math_dom_adapter import (  # noqa: PLC0415
                MathDOMAdapter,
                MathPageUnderstandingAdapter,
            )
            from auto_apply.domain.services.dom_segmentation import (  # noqa: PLC0415
                MathFormUnderstandingService,
            )
            # Reuse the same MathDOMAdapter instance we already created for
            # math_perception_port, or build a new one if we didn't create it
            # above (should not happen, but be safe).
            math_dom = math_perception_port if math_perception_port is not None else MathDOMAdapter(browser=driver, observer=_extraction_observer)
            form_svc = MathFormUnderstandingService()
            page_understanding_port = MathPageUnderstandingAdapter(math_dom, form_svc)
        except Exception as _exc:
            # WARNING, not debug. Substituting the Null adapter silently
            # disables single-script SERP extraction for the whole session and
            # discovery falls back to the slow DOM miner with no console trace
            # of why. This exact except-swallow already hid a NameError that
            # disabled the math perception adapter on every real browser run.
            logger.warning(
                "build_orchestrator: MathPageUnderstandingAdapter could not be "
                "built (%s) — using NullPageUnderstandingAdapter. Fast SERP "
                "extraction is DISABLED for this session; discovery will use "
                "the DOM miner.", _exc,
            )
            from auto_apply.domain.ports.page_understanding_port import NullPageUnderstandingAdapter
            page_understanding_port = NullPageUnderstandingAdapter()

    # Always provide a valid port — never None.
    if page_understanding_port is None:
        from auto_apply.domain.ports.page_understanding_port import NullPageUnderstandingAdapter
        page_understanding_port = NullPageUnderstandingAdapter()

    # ── 4. Discovery providers ────────────────────────────────────────────────
    providers = []

    if driver is not None:
        from auto_apply.adapters.secondary.discovery.providers.bing import (  # noqa: PLC0415
            BingProvider,
        )
        from auto_apply.adapters.secondary.discovery.providers.google import (  # noqa: PLC0415
            GoogleProvider,
        )
        from auto_apply.adapters.secondary.discovery.providers.indeed import (  # noqa: PLC0415
            IndeedProvider,
        )
        from auto_apply.adapters.secondary.evasion.manager import (  # noqa: PLC0415
            EvasionManager,
        )

        try:
            _indeed_evasion_manager = EvasionManager(driver)
        except Exception as _exc:
            logger.warning(
                "build_orchestrator: EvasionManager construction failed for "
                "IndeedProvider — proceeding without evasion checking: %s",
                _exc,
            )
            _indeed_evasion_manager = None

        from auto_apply.application.services.navigation.pagination import (  # noqa: PLC0415
            InfiniteScrollStrategy,
            PaginationHandler,
        )

        _nav_cfg = registry.get_all_effective_config()
        _discovery_cfg = _nav_cfg.get("discovery") or {}
        _max_pages_per_query = max(
            1,
            int(
                _discovery_cfg.get(
                    "max_pages_per_query",
                    _nav_cfg.get("max_pages_per_query", 1),
                )
            ),
        )
        _page_scroller = InfiniteScrollStrategy(
            driver,
            scroller=page_action_tool,
            settle_s=_nav_cfg.get("infinite_scroll_settle_s", 2.0),
        )
        _paginator = PaginationHandler(driver, interaction_port)

        from auto_apply.application.services.auditing.reporter import (  # noqa: PLC0415
            AuditReporter,
        )

        _audit_reporter = AuditReporter(driver)

        providers = [
            GoogleProvider(
                browser=driver,
                ats_registry=_ats_registry,
                page_understanding_port=page_understanding_port,
                scroller=_page_scroller,
                paginator=_paginator,
                max_pages=_max_pages_per_query,
                observer=_extraction_observer,
                reporter=_audit_reporter,
                forced_tier=_forced_tier,
            ),
            BingProvider(
                browser=driver,
                scroller=_page_scroller,
                paginator=_paginator,
                max_pages=_max_pages_per_query,
                observer=_extraction_observer,
                reporter=_audit_reporter,
                forced_tier=_forced_tier,
            ),
            IndeedProvider(
                browser=driver,
                evasion_manager=_indeed_evasion_manager,
                scroller=_page_scroller,
                paginator=_paginator,
                max_pages=_max_pages_per_query,
                observer=_extraction_observer,
                reporter=_audit_reporter,
                forced_tier=_forced_tier,
            ),
        ]

    from auto_apply.adapters.secondary.discovery.strategies.serp_strategy import (  # noqa: PLC0415
        GenericSERPStrategy,
    )

    search_prefs_for_miner = profile.search_preferences if hasattr(profile, "search_preferences") else None

    def _company_page_miner(browser: BrowserInterface) -> list:
        return GenericSERPStrategy(
            browser=browser,
            search_prefs=search_prefs_for_miner,
            source_tag="CompanyDirect",
            scroller=_page_scroller,
            paginator=_paginator,
            max_pages=_max_pages_per_query,
            observer=_extraction_observer,
            reporter=_audit_reporter,
            forced_tier=_forced_tier,
        ).execute()

    # Single-URL careers-page scraper for DISCOVER_COMPANY tasks: navigate the
    # live browser to the URL and extract listings via the math subsystem.
    # Omitted (None) without a browser — DiscoveryWorkflow degrades gracefully.
    _company_page_scraper = None
    if driver is not None and math_analyzer is not None:
        def _company_page_scraper(careers_url: str) -> list:  # noqa: F811
            driver.get(careers_url)
            return math_analyzer.extract_job_listings()

    # ── Browser lease for single shared driver ────────────────────────────────
    # Must use a hardcoded capacity of 1, never derived from any config or
    # session-plan value — see the constant definition at the top of this file.
    browser_lease = None
    if driver is not None:
        browser_lease = BrowserLeaseManager(driver, max_concurrent=_MAX_LEASES_PER_SHARED_DRIVER)

    # ── Research observer (consent-gated) ─────────────────────────────────────
    from auto_apply.domain.ports.research_port import NullResearchObserver  # noqa: PLC0415

    research_observer = NullResearchObserver()

    if registry.is_research_enabled():
        try:
            from auto_apply.adapters.secondary.research.sqlite_consent_repository import (  # noqa: PLC0415
                SqliteConsentRepository,
            )
            from auto_apply.application.services.research_consent import (  # noqa: PLC0415
                ResearchConsentManager,
            )

            _consent_db = USER_DATA_DIR / "research_consent.db"
            _signals_db = USER_DATA_DIR / "research_signals.db"

            _consent_repo = SqliteConsentRepository(
                consent_db_path=_consent_db,
                research_db_path=_signals_db,
            )
            _consent_mgr = ResearchConsentManager(_consent_repo)

            if _consent_mgr.is_active():
                from auto_apply.adapters.secondary.research.signal_aggregator import (  # noqa: PLC0415
                    ResearchSignalAggregator,
                )
                _aggregator = ResearchSignalAggregator(
                    db_path=_signals_db,
                    consent_version=_consent_mgr.consent_version,
                )
                _aggregator.start()
                research_observer = _aggregator
                logger.info(
                    "Research pipeline active (consent granted, version=%s)",
                    _consent_mgr.consent_version,
                )
            else:
                logger.info("Research disabled: consent not granted by user")
        except Exception as _exc:
            logger.warning(
                "Research observer failed to initialize — using NullResearchObserver: %s",
                _exc,
            )

    # ── 5. Capability profile — gates task types based on driver availability ──
    _capability_profile = registry.build_capability_profile(driver is not None)
    db_manager.set_capability_profile(_capability_profile)
    logger.info(
        "Capability profile active | mode=%s browser=%s workers=%d",
        _capability_profile.mode_name,
        _capability_profile.browser_framework or "none",
        _capability_profile.max_browser_workers,
    )

    # ── 4b. Workflow orchestrators ────────────────────────────────────────────
    from auto_apply.application.services.data_processing.deduplication_manager import (  # noqa: PLC0415
        DeduplicationManager,
    )
    from auto_apply.application.workflows import (  # noqa: PLC0415
        ApplicationsWorkflow,
        DiscoveryWorkflow,
        VettingWorkflow,
    )

    dedup = DeduplicationManager()

    # ── Deterministic RNG streams ──────────────────────────────────────────────
    # BehaviorParameters is already constructed above (see cascade section).
    apps_workflow_rng = behavior_params.make_rng("applications_workflow")

    # ── Page feedback service (learning loop) ────────────────────────────────
    from auto_apply.application.services.page_analysis_router import PageAnalysisRouter

    page_feedback_repo = None
    page_feedback_service = None
    try:
        from auto_apply.adapters.secondary.persistence.page_feedback_repository import (
            PageFeedbackRepository,
        )
        from auto_apply.application.services.page_feedback_service import (
            PageFeedbackService,
        )

        _feedback_db_path = USER_DATA_DIR / "page_feedback.db"
        page_feedback_repo = PageFeedbackRepository(_feedback_db_path)
        page_feedback_service = PageFeedbackService(page_feedback_repo)
        logger.info("build_orchestrator: page feedback service initialized")
    except Exception as _exc:
        logger.debug(
            "build_orchestrator: page feedback service unavailable — "
            "PageAnalysisRouter will use static rules only (error: %s)",
            _exc,
        )

    # ── PageAnalysisRouter with optional feedback ───────────────────────────
    page_analysis_router = PageAnalysisRouter(
        ats_registry=_ats_registry,
        feedback_service=page_feedback_service,
        forced_tier=_forced_tier,
    )

    discovery_workflow = DiscoveryWorkflow(
        profile=profile,
        providers=providers,
        task_queue=db_manager,
        event_bus=event_bus,
        dedup=dedup,
        text_matcher=text_matcher,
        ats_registry=_ats_registry,
        company_page_miner=_company_page_miner,
        company_page_scraper=_company_page_scraper,
        plan=plan,
        browser_lease=browser_lease,
        research_observer=research_observer,
        provider_order_rng=behavior_params.make_rng("discovery.provider_order"),
    )

    vetting_workflow = VettingWorkflow(
        profile=profile,
        filters=filter_pipeline,
        job_repo=job_repo,
        task_queue=db_manager,
        event_bus=event_bus,
        text_matcher=text_matcher,
        text_generation_port=gpt4all_adapter,
        perception_port=perception_port,
        config=_effective_config,
        research_observer=research_observer,
    )

    # ApplicationsWorkflow — try to construct each optional component.
    _field_classifier = None
    _semantic_filler = None
    _webpage_analyzer = None
    _interruption_handler = None
    _dom_observer = None

    try:
        from auto_apply.domain.applications.field_classifier import (  # noqa: PLC0415
            FieldClassifier,
        )
        _field_classifier = FieldClassifier()
    except Exception as _exc:
        logger.debug("build_orchestrator: FieldClassifier unavailable: %s", _exc)

    try:
        from auto_apply.domain.applications.semantic_filler import (  # noqa: PLC0415
            SemanticFiller,
        )
        _semantic_filler = SemanticFiller(profile)
    except Exception as _exc:
        logger.debug("build_orchestrator: SemanticFiller unavailable: %s", _exc)

    if driver is not None:
        try:
            from auto_apply.adapters.secondary.perception.math_dom_adapter import (  # noqa: PLC0415
                MathDOMAdapter,
            )
            from auto_apply.application.services.webpage_analyzer import (  # noqa: PLC0415
                WebpageAnalyzer,
            )
            from auto_apply.domain.services.dom_segmentation import (  # noqa: PLC0415
                MathFormUnderstandingService,
            )
            _webpage_analyzer = WebpageAnalyzer(
                perception_port=MathDOMAdapter(browser=driver, observer=_extraction_observer),
                reasoning_port=MathFormUnderstandingService(),
            )
        except Exception as _exc:
            logger.debug("build_orchestrator: WebpageAnalyzer unavailable: %s", _exc)

        try:
            from auto_apply.application.services.navigation.interruption import (  # noqa: PLC0415
                InterruptionHandler,
            )
            _interruption_handler = InterruptionHandler(
                browser=driver,
                interactor=interaction_port,
            )
        except Exception as _exc:
            logger.debug(
                "build_orchestrator: InterruptionHandler unavailable: %s", _exc
            )

        # Reuse the single observer built above — one instance, one config
        # source, shared by the workflow and the handlers.
        _dom_observer = dom_readiness

    applications_workflow = ApplicationsWorkflow(
        profile=profile,
        browser=driver,
        perception_port=perception_port,
        interaction_port=interaction_port,
        webpage_analyzer=_webpage_analyzer,
        field_classifier=_field_classifier,
        semantic_filler=_semantic_filler,
        text_matcher=text_matcher,
        file_handler=None,
        interruption_handler=_interruption_handler,
        dom_observer=_dom_observer,
        ats_registry=_ats_registry,
        job_repo=job_repo,
        task_queue=db_manager,
        event_bus=event_bus,
        interrupt_policy=interrupt_policy,
        navigation=page_action_tool,
        reasoning_port=reasoning_port,
        text_generation_port=gpt4all_adapter,
        config=_effective_config,
        research_observer=research_observer,
        browser_lease=browser_lease,       # enforce concurrency safety
        rng=apps_workflow_rng,
        page_analysis_router=page_analysis_router,  # <<< NEW
        plan=plan,
    )

    # ── 6. Orchestrator — all dependencies injected ───────────────────────────
    from auto_apply.application.agent.orchestrator import AgentOrchestrator  # noqa: PLC0415
    from auto_apply.domain.config import CHECKPOINTS_DIR  # noqa: PLC0415
    from auto_apply.adapters.secondary.resolution.captcha_adapter import (  # noqa: PLC0415
        CaptchaResolutionService,
    )
    from auto_apply.adapters.secondary.network.network_monitor import (  # noqa: PLC0415
        NetworkHealthMonitor,
    )

    captcha_resolver = CaptchaResolutionService(registry=registry)

    # Network monitor is always created; browser monitor only when driver exists.
    network_monitor = NetworkHealthMonitor(event_bus=event_bus)
    browser_monitor = None
    if driver is not None and not registry.is_low_resource_environment():
        try:
            from auto_apply.adapters.secondary.browser.browser_monitor import (  # noqa: PLC0415
                BrowserHealthMonitor,
            )
            browser_monitor = BrowserHealthMonitor(driver=driver, event_bus=event_bus)
        except ImportError:
            logger.debug("BrowserHealthMonitor not available — skipping")
    elif driver is not None:
        logger.info(
            "build_orchestrator: low-resource environment — BrowserHealthMonitor disabled"
        )

    CHECKPOINTS_DIR.mkdir(parents=True, exist_ok=True)

    # ── Job posting resolver (RESOLVE_JOB_URL) ────────────────────────────────
    from auto_apply.application.services.job_posting_resolver import (  # noqa: PLC0415
        JobPostingResolver,
    )
    from auto_apply.adapters.secondary.evasion.components.behavior import (  # noqa: PLC0415
        simulate_idle_time,
    )
    job_posting_resolver = JobPostingResolver(idle_simulator=simulate_idle_time)

    # ── Optional CLI progress display (Wave M — Session Observability) ────────
    # Constructed here, not by the orchestrator itself, since composition_root
    # is the only layer allowed to import the concrete CLI adapter. Missing
    # TTY / piped output / library computer all degrade gracefully to None —
    # progress display is a convenience, not a requirement.
    try:
        from auto_apply.adapters.primary.cli.progress import (  # noqa: PLC0415
            SessionProgressDisplay,
        )
        progress_display = SessionProgressDisplay()
    except ImportError:
        progress_display = None

    orchestrator = AgentOrchestrator(
        profile=profile,
        resources=resources,
        registry=registry,
        task_queue=db_manager,
        db=job_repo,
        event_bus=event_bus,
        driver=driver,
        captcha_resolver=captcha_resolver,
        browser_monitor=browser_monitor,
        network_monitor=network_monitor,
        job_posting_resolver=job_posting_resolver,
        progress=progress_display,
    )

    orchestrator._workflows = {  # type: ignore[attr-defined]
        "DiscoveryWorkflow": discovery_workflow,
        "VettingWorkflow": vetting_workflow,
        "ApplicationsWorkflow": applications_workflow,
    }

    # ── Attach SessionPlan ────────────────────────────────────────────────────
    orchestrator.session_plan = plan

    # ── 5b. Attach BehaviorParameters for timing (built once, at the top of
    # this function, so every RNG consumer and this reference share the exact
    # same instance rather than risking two independently-constructed copies).
    orchestrator.behavior_parameters = behavior_params

    logger.info(
        "build_orchestrator complete | providers=%d driver=%s",
        len(providers),
        "yes" if driver is not None else "no",
    )

    return orchestrator


def build_session_controller(profile: "UserProfile") -> "SessionController":
    """Factory that builds a fully‑wired SessionController for *profile*.

    This is the single entry point used by the GUI and CLI launch sequences.
    It runs the full boot sequence (registry → orchestrator → controller)
    and performs the post‑construction initialisation that was previously
    buried inside the now‑removed ``from_profile`` classmethod.

    Args:
        profile: A loaded and validated UserProfile.

    Returns:
        A SessionController instance ready to call ``.initialize_session()``.
    """
    from auto_apply.application.services.session_controller import SessionController  # noqa: PLC0415
    from auto_apply.domain.models.profile import UserProfile  # noqa: PLC0415

    # 1. Build authoritative configuration
    registry = CapabilitiesRegistry.build(user_profile=profile)

    # 2. Build the fully wired orchestrator
    orchestrator = build_orchestrator(registry)

    # 3. Assemble the controller (all deps injected)
    controller = SessionController(
        registry=registry,
        db=orchestrator.task_queue,      # DatabaseManager implements WorkQueuePort
        orchestrator=orchestrator,
    )

    # 4. Post‑construction initialisation (previously inside from_profile)
    controller._perform_startup_recovery()   # reset stuck IN_PROGRESS tasks
    controller._wire_approval_gate()         # bind HITL gate to workflow

    return controller


def build_session(master_password: str | None = None):
    """Initializes infrastructure and returns a ready ProfileRepository.

    This is the pre-session setup helper called by main.py before launching
    the GUI or CLI. It:
        1. Creates and initializes the DatabaseManager (ensures WAL mode, tables).
        2. Creates a ProfileRepository with the optional master password.

    Returns:
        ProfileRepository ready to list and load profiles.

    Raises:
        RuntimeError: If database initialization fails.
    """
    from auto_apply.adapters.secondary.persistence.database import (  # noqa: PLC0415
        DatabaseManager,
    )
    from auto_apply.adapters.secondary.persistence.profile_repository import (  # noqa: PLC0415
        ProfileRepository,
    )

    DatabaseManager()  # Initializes DB / creates tables if absent.
    return ProfileRepository(master_password=master_password)