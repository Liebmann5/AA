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

import logging
import time
from typing import TYPE_CHECKING

from auto_apply.domain.ports.browser_port import BrowserInterface
from auto_apply.infrastructure.registry import (
    CapabilitiesRegistry,
    _GEO_DB_PATH,
)
from auto_apply.infrastructure.browser_cascade import BrowserCascade
from auto_apply.infrastructure.driver_registry import DriverRegistry
from auto_apply.infrastructure.providers.selenium_provider import SeleniumProvider
from auto_apply.infrastructure.providers.playwright_provider import PlaywrightProvider
from auto_apply.application.services.mathematical_web_analyzer import MathematicalWebAnalyzer

if TYPE_CHECKING:
    from auto_apply.application.agent.orchestrator import AgentOrchestrator

# Re-export so existing callers don't break.
__all__ = ["CapabilitiesRegistry", "build_orchestrator", "build_session", "build_session_controller"]

logger = logging.getLogger(__name__)


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
        1. Persistence adapters — DatabaseManager, JobRepository, GeoDatabaseRepository
        2. Domain filters       — ThrottlingFilter, SpatialLocationFilter, logic filters
        3. Shared ports         — perception, interaction, reasoning, interrupt policy
        4. Discovery providers  — GoogleProvider, BingProvider, IndeedProvider
        4b. Workflows           — DiscoveryWorkflow, VettingWorkflow, ApplicationsWorkflow
        5. AgentOrchestrator    — dispatches each TaskType to its workflow

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
            "selenium": lambda raw: SeleniumAdapter(raw),
            "playwright": lambda raw: PlaywrightAdapter(
                page=raw,
                browser=raw._pw_browser,
                playwright=raw._pw_playwright,
            ),
        }

        cascade = BrowserCascade(registry, driver_registry=driver_registry, adapter_map=adapter_map)
        driver = cascade.acquire_driver()

    if driver is None:
        logger.info(
            "build_orchestrator: no browser driver — falling back to static perception"
        )

    # ── Retrieve the frozen SessionPlan ──────────────────────────────────────
    plan = registry.get_session_plan()

    # ── Shared MathematicalWebAnalyzer (injected into engines) ─────────────────
    math_analyzer = MathematicalWebAnalyzer(browser=driver) if driver is not None else None

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
    resources = registry.get_runtime_profile()

    filter_pipeline = [
        ThrottlingFilter(profile, job_repo),
        SpatialLocationFilter(profile, geo_db),
        LocationLogicFilter(profile),
        CompanyBlacklistFilter(profile),
        TitleLogicFilter(profile),
    ]

    # ── 2b. NLP text matching — one shared instance across all workflows ───────
    from auto_apply.application.services.text_matching import TextMatcher  # noqa: PLC0415

    text_matcher = TextMatcher()
    _search_prefs = getattr(profile, "search_preferences", None)
    _profile_skills = getattr(_search_prefs, "skills", []) or []
    if _profile_skills:
        text_matcher.load_skills_vocabulary(_profile_skills)

    # ── 2c. GPT4All text generation adapter (lazy-loaded on first call) ────────
    from auto_apply.adapters.secondary.reasoning.gpt4all_adapter import (  # noqa: PLC0415
        GPT4AllAdapter,
    )

    gpt4all_adapter = GPT4AllAdapter()

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

    interaction_port = (
        InteractionExecutor(driver, text_matcher=text_matcher)
        if driver is not None
        else None
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
            math_dom = MathDOMAdapter(browser=driver)
            form_svc = MathFormUnderstandingService()
            page_understanding_port = MathPageUnderstandingAdapter(math_dom, form_svc)
        except Exception as _exc:
            logger.debug("build_orchestrator: MathPageUnderstandingAdapter unavailable: %s", _exc)

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
        from auto_apply.application.agent.context import (  # noqa: PLC0415
            ExecutionContext,
        )

        provider_context = ExecutionContext(
            profile=profile,
            session_id=f"session_{int(time.time())}",
        )

        search_prefs = getattr(profile, "search_preferences", None)

        providers = [
            GoogleProvider(
                browser=driver,
                context=provider_context,
                ats_registry=_ats_registry,
                page_understanding_port=page_understanding_port,
            ),
            BingProvider(browser=driver, context=provider_context),
        ]

        if search_prefs is not None:
            providers.append(
                IndeedProvider(browser=driver, search_prefs=search_prefs)
            )

    from auto_apply.adapters.secondary.discovery.strategies.serp_strategy import (  # noqa: PLC0415
        GenericSERPStrategy,
    )

    search_prefs_for_miner = profile.search_preferences if hasattr(profile, "search_preferences") else None

    def _company_page_miner(browser: BrowserInterface) -> list:
        return GenericSERPStrategy(
            browser=browser,
            search_prefs=search_prefs_for_miner,
            source_tag="CompanyDirect",
        ).execute()

    # Single-URL careers-page scraper for DISCOVER_COMPANY tasks: navigate the
    # live browser to the URL and extract listings via the math subsystem.
    # Omitted (None) without a browser — DiscoveryWorkflow degrades gracefully.
    _company_page_scraper = None
    if driver is not None and math_analyzer is not None:
        def _company_page_scraper(careers_url: str) -> list:  # noqa: F811
            driver.get(careers_url)
            return math_analyzer.extract_job_listings()

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

    _effective_config = registry.get_all_effective_config()

    # ── Research collector (wired into ApplicationsWorkflow) ────────────────
    from auto_apply.application.services.research.collector import ResearchCollector  # noqa: PLC0415

    research_collector = ResearchCollector(
        enabled=registry.is_research_enabled(),
        event_bus=event_bus,
        session_id="build_orchestrator",
    )

    # ** DiscoveryWorkflow now receives the SessionPlan instead of the raw config dict **
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
                perception_port=MathDOMAdapter(browser=driver),
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

        try:
            from auto_apply.adapters.secondary.interaction.dom_observer import (  # noqa: PLC0415
                DOMObserver,
            )
            _dom_observer = DOMObserver(browser=driver)
        except Exception as _exc:
            logger.debug("build_orchestrator: DOMObserver unavailable: %s", _exc)

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
        text_generation_port=gpt4all_adapter,
        config=_effective_config,
        research_collector=research_collector,
    )

    # ── 5. Orchestrator — all dependencies injected ───────────────────────────
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
    )

    orchestrator._workflows = {  # type: ignore[attr-defined]
        "DiscoveryWorkflow": discovery_workflow,
        "VettingWorkflow": vetting_workflow,
        "ApplicationsWorkflow": applications_workflow,
    }

    # ── Attach SessionPlan ────────────────────────────────────────────────────
    orchestrator.session_plan = plan

    # ── 5b. Build BehaviorParameters for timing (already present) ─────────────
    from auto_apply.domain.models.timing import BehaviorParameters  # noqa: PLC0415

    behavior_params = BehaviorParameters.from_config(_effective_config)
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