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
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from auto_apply.application.services.i18n import configure_locale
from auto_apply.application.services.mathematical_web_analyzer import MathematicalWebAnalyzer
from auto_apply.domain.config import (
    DB_PATH,
    FOOTPRINT_LEDGER_PATH,
    INSTANCES_DIR,
    IS_FROZEN,
    PAGE_COPIES_DIR,
    PROVENANCE_KEY_PATH,
    REPORTS_DIR,
    RESEARCH_DB_PATH,
    RESEARCH_SALT_PATH,
    USER_DATA_DIR,
    ensure_data_dirs,
    get_install_root,
    get_run_mode,
)
from auto_apply.domain.exceptions import BrowserSetupError
from auto_apply.domain.models.timing import BehaviorParameters
from auto_apply.domain.ports.browser_port import BrowserInterface
from auto_apply.domain.ports.navigation_port import InterruptionHandlerPort, NullInterruptionHandler
from auto_apply.infrastructure.registry import (
    CapabilitiesRegistry,
    _GEO_DB_PATH,
)
from auto_apply.infrastructure.browser_cascade import BrowserCascade
from auto_apply.infrastructure.driver_registry import DriverRegistry
from auto_apply.infrastructure.browser_lease_manager import BrowserLeaseManager
from auto_apply.adapters.secondary.browser.selenium_provider import SeleniumProvider
from auto_apply.adapters.secondary.browser.playwright_provider import PlaywrightProvider

# ── Lifecycle re-exports (the primary adapters' sanctioned route) ─────────
# The research-consent precedent: primary adapters never import application
# services directly; they take these names from the wiring layer (the reach
# pin in tests/architecture/test_safety_pins.py holds that inventory).
from auto_apply.application.services import lifecycle_wording
from auto_apply.application.services.install.bootstrap_pins import load_pins
from auto_apply.application.services.install.engine import (
    InstallEngine,
    InstallEnvironment,
    InstallError,
)
from auto_apply.application.services.uninstall.engine import (
    UninstallEngine,
    UninstallEnvironment,
    UninstallRefused,
)
from auto_apply.application.services.uninstall.model import (
    ResearchDecision,
    UninstallDecision,
    UninstallReport,
)

if TYPE_CHECKING:
    from auto_apply.application.agent.orchestrator import AgentOrchestrator
    #from auto_apply.application.agent.task_kernel import TaskKernel
    from auto_apply.domain.models.profile import UserProfile
    from auto_apply.application.services.research_consent import ResearchConsentManager
    from auto_apply.domain.ports.page_copy_port import PageCopierPort
    from auto_apply.application.services.session_controller import SessionController
    from auto_apply.domain.ports.profile_repository_port import ProfileRepositoryPort
    from auto_apply.application.services.instance_registry import InstanceRegistry
    from auto_apply.adapters.secondary.research.research_exporter import (
        ExportResult,
    )
    from auto_apply.adapters.secondary.research.research_verifier import (
        VerifyResult,
    )
    from auto_apply.domain.models.replay import ReplayReport

# Re-export so existing callers don't break.
__all__ = [
    "CapabilitiesRegistry",
    "InstallEngine",
    "InstallEnvironment",
    "InstallError",
    "ResearchDecision",
    "UninstallDecision",
    "UninstallEngine",
    "UninstallEnvironment",
    "UninstallRefused",
    "UninstallReport",
    "build_orchestrator",
    "build_page_copier",
    "build_research_consent",
    "build_session",
    "build_session_controller",
    "export_research_bundle",
    "lifecycle_wording",
    "load_pins",
    "research_public_key_fingerprint",
    "run_replay",
    "verify_research_bundle",
]

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# CONSTANTS
# --------------------------------------------------------------------------

# BrowserLeaseManager MUST always be created with max_concurrent=1.
# The lease wraps a SINGLE shared browser driver instance.  Any value above 1
# permits concurrent access to the same instance, which is the exact bug the
# lease exists to prevent.  Never derive this from config or session plan.
_MAX_LEASES_PER_SHARED_DRIVER = 1


def _warn_if_legacy_research_db() -> None:
    """Warn when a pre-relocation research database exists.

    The collector used to write USER_DATA_DIR / <filename>; the one home is
    now RESEARCH_DB_PATH (research/ under the data directory). No real user
    can have research data (consent has no production caller), so this is a
    signpost for developer machines, not a migration: AA never moves or
    deletes the old file — its -wal sidecar may hold the only copy of its
    last rows. The path is derived from RESEARCH_DB_PATH's parts so the
    filename literal stays spelled in exactly one src file (domain/config).
    """
    legacy = RESEARCH_DB_PATH.parent.parent / RESEARCH_DB_PATH.name
    if legacy == RESEARCH_DB_PATH or not legacy.exists():
        return
    logger.warning(
        "Legacy research database found at %s — it is no longer read or "
        "written. Research data now lives at %s. AA will not move or delete "
        "the old file; move it yourself if you want the rows, delete it if "
        "not.",
        legacy,
        RESEARCH_DB_PATH,
    )


def build_research_consent(
    registry: CapabilitiesRegistry | None = None,
) -> "ResearchConsentManager":
    """Build the research-consent service — the one answer to "is research on?".

    Two call sites:
      * build_orchestrator / build_session_controller, which pass the session
        registry so the offered flag and the admin policy come from the
        enforced three-tier merge (PolicyEnforcement has already run inside
        registry.build());
      * the user surfaces (GUI settings, CLI) BEFORE any session exists,
        which pass nothing — the offered flag is the runtime default and the
        admin policy is read from disk directly.

    The returned service records grant()/withdraw() in the consent database;
    grants take effect at the next session build. A service a session was
    built with also stops the running observer on withdrawal, and the
    controller stops it at shutdown (FORK 3).

    Args:
        registry: The session registry, or None for pre-session use.
    """
    from auto_apply.adapters.secondary.research.sqlite_consent_repository import (  # noqa: PLC0415
        SqliteConsentRepository,
    )
    from auto_apply.application.services.research_consent import (  # noqa: PLC0415
        ResearchConsentManager,
    )

    if registry is not None:
        is_offered = bool(registry.is_research_offered())
        policy = registry.get_admin_policy()
    else:
        from auto_apply.adapters.secondary.persistence.policy_manager import (  # noqa: PLC0415
            PolicyManager,
        )
        from auto_apply.infrastructure.registry import _RUNTIME_DEFAULTS  # noqa: PLC0415

        is_offered = bool(_RUNTIME_DEFAULTS.get("enable_research_collection", True))
        policy = PolicyManager.load_admin_policy()

    from auto_apply.adapters.secondary.security.data_protection import (  # noqa: PLC0415
        provision_research_salt,
        read_research_salt,
    )
    from auto_apply.domain.services.research_identity import (  # noqa: PLC0415
        configure_salt_file_reader,
    )

    # Wire the ONE salt-file seam (V1): the domain resolves through this
    # reader; the manager provisions through this callable. Both point at
    # the secondary adapter where the salt lives, beside the key.
    configure_salt_file_reader(lambda: read_research_salt(RESEARCH_SALT_PATH))

    repo = SqliteConsentRepository(
        consent_db_path=USER_DATA_DIR / "research_consent.db",
        research_db_path=RESEARCH_DB_PATH,
        provenance_key_path=PROVENANCE_KEY_PATH,
        page_copies_dir=PAGE_COPIES_DIR,
        research_salt_path=RESEARCH_SALT_PATH,
    )
    return ResearchConsentManager(
        repo,
        is_offered=is_offered,
        # `is True`, deliberately: the policy field is tri-state and only an
        # explicit True prohibits. It also keeps MagicMock-built registries
        # (tests) from reading as prohibitions.
        admin_prohibited=getattr(policy, "disable_research_collection", None) is True,
        provision_salt=lambda: provision_research_salt(RESEARCH_SALT_PATH),
    )


def _positive_int_setting(registry: CapabilitiesRegistry, key: str) -> int:
    """A positive int setting from the effective config; anything else falls
    back to runtime_defaults.yaml's value (via the parity-pinned
    _RUNTIME_DEFAULTS), never to a second literal here (Absolute Rule 2)."""
    from auto_apply.infrastructure.registry import _RUNTIME_DEFAULTS  # noqa: PLC0415

    value = registry.get_effective_config(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return int(_RUNTIME_DEFAULTS[key])
    return value


def build_page_copier(
    registry: CapabilitiesRegistry,
    consent_service: "ResearchConsentManager",
    profile: object,
    research_active: bool,
) -> "PageCopierPort":
    """Expire old page copies, then build the session's page copier (item 6).

    Expiry runs on EVERY build, whatever the consent state: copies kept
    before the person turned page copies off (choosing to keep them) still
    reach their deletion date. A copier that keeps pages is built only when
    research is actually recording this session AND the person agreed to
    page copies; it re-reads that agreement before every copy, and the
    background writer re-reads it before every write, so turning copies off
    mid-session stops the next one. Anything else gets NullPageCopier,
    which reads and keeps nothing.

    Writes go through QueuedPageCopyStore: vetting reads and cleans the
    page, the disk work happens on a background writer ("Non-Blocking by
    Design", docs/research_module/index.md).
    """
    from datetime import date  # noqa: PLC0415

    from auto_apply.adapters.secondary.research.queued_page_store import (  # noqa: PLC0415
        QueuedPageCopyStore,
    )
    from auto_apply.adapters.secondary.research.warc_page_store import (  # noqa: PLC0415
        WarcPageStore,
    )
    from auto_apply.application.services.page_copier import (  # noqa: PLC0415
        NullPageCopier,
        PageCopier,
        own_details,
    )
    from auto_apply.domain.models.page_copy import derive_nonce  # noqa: PLC0415
    from auto_apply.domain.services.research_identity import (  # noqa: PLC0415
        ResearchSaltError,
        resolve_research_salt,
    )

    keep_days = _positive_int_setting(registry, "page_copy_keep_days")
    max_mb = _positive_int_setting(registry, "page_copy_max_mb")
    store = WarcPageStore(PAGE_COPIES_DIR, max_bytes=max_mb * 1024 * 1024)
    try:
        expired = store.expire(date.today(), keep_days)
        if expired:
            logger.info("Page copies | deleted %d copies older than %d days", expired, keep_days)
    except Exception as exc:  # noqa: BLE001 — expiry retries at the next build
        logger.warning("Page copies | expiry failed (%s); retried next session", type(exc).__name__)

    if not research_active or not consent_service.should_copy_pages():
        return NullPageCopier()
    try:
        key = resolve_research_salt().encode("utf-8")
    except ResearchSaltError:
        # should_collect() checked the key; one that vanished since means no
        # copies, not copies under a weaker nonce.
        logger.warning("Page copies | research key unavailable; no copies this session")
        return NullPageCopier()
    values, names = own_details(getattr(profile, "personal_info", None))
    logger.info("Page copies | on: cleaned job pages are kept on this device")
    return PageCopier(
        QueuedPageCopyStore(store, allowed=consent_service.should_copy_pages),
        own_values=values,
        own_names=names,
        allowed=consent_service.should_copy_pages,
        nonce=lambda content: derive_nonce(key, content),
    )


def export_research_bundle(fmt: str = "csv", export_root: Path | None = None) -> "ExportResult":
    """Export the research database as one verifiable bundle — the consent
    screens' route to the exporter (FORK 5).

    Primary adapters may not import the secondary exporter
    (tests/architecture/test_safety_pins.py EXPECTED_REACHES), so the CLI
    research screen and the GUI research window call this helper instead.
    main.py's --export-research keeps its own inline path; both construct
    the same ResearchExporter over the same two paths.

    Callers check domain.config.RESEARCH_DB_PATH.exists() first for the
    nothing-to-export case — the exporter opens the database read-only and
    raises for a missing file, which a screen should never have to render.

    Args:
        fmt: 'csv', 'ndjson', or 'parquet'. A plain str, validated here,
            because the ExportFormat Literal lives in the secondary adapter
            the screens may not import.
        export_root: Where the bundle directory is written. Defaults to
            REPORTS_DIR (inside the data home). The uninstaller passes the
            user's chosen folder — a bundle written inside the data home
            would be deleted moments later.

    Raises:
        ValueError: For an unknown format.
        ExportError: For any database or filesystem failure (a missing
            optional dependency degrades to CSV instead — that is not an
            error here, exactly as in main.py's --export-research).
    """
    from auto_apply.adapters.secondary.research.research_exporter import (  # noqa: PLC0415
        ExportFormat,
        ResearchExporter,
    )

    # A typed lookup narrows the plain str to the exporter's Literal without
    # a cast or a type: ignore.
    formats: dict[str, ExportFormat] = {"csv": "csv", "ndjson": "ndjson", "parquet": "parquet"}
    if fmt not in formats:
        raise ValueError(
            f"Unsupported format {fmt!r}. Accepted values: csv, ndjson, parquet"
        )
    exporter = ResearchExporter(
        db_path=RESEARCH_DB_PATH,
        export_root=export_root or REPORTS_DIR,
        provenance_key_path=PROVENANCE_KEY_PATH,
    )
    return exporter.export(formats[fmt])


def research_public_key_fingerprint() -> str | None:
    """The installation's research public-key fingerprint, for both consent
    surfaces to show (F5): SHA-256 of the raw public key bytes, hex.

    Read-only — opening a consent screen must never mint a key, so this
    returns None when no key exists yet (one is generated the first time
    research data is recorded or a bundle is exported).
    """
    from auto_apply.adapters.secondary.security.data_protection import (  # noqa: PLC0415
        read_public_key_fingerprint,
    )

    return read_public_key_fingerprint(PROVENANCE_KEY_PATH)


def verify_research_bundle(bundle_dir: Path) -> "VerifyResult":
    """Verify a research export bundle offline — the CLI's route to the
    verifier, mirroring export_research_bundle (primary adapters may not
    import the secondary adapters directly)."""
    from auto_apply.adapters.secondary.research.research_verifier import (  # noqa: PLC0415
        verify_bundle,
    )

    return verify_bundle(bundle_dir)


def run_replay(corpus_dir: Path, out_dir: Path | None = None) -> "ReplayReport":
    """Replay a corpus of kept page copies and write the artifact (item 7).

    No browser, no network, no research database and no research key: the
    replay is a pure function of the corpus and this AA version
    (domain/services/replay.py). Composition only — the corpus reader, the
    byte-exact writer and the version are chosen here.

    Args:
        corpus_dir: A folder of ``*.warc.gz`` page copies (for example
            AA's own ``research/page_copies``, or a corpus someone shared).
        out_dir: Where to write; default ``reports/replay_<corpus digest
            prefix>`` in AA's data folder, so the same corpus always lands
            in the same place.

    Raises:
        FileNotFoundError: corpus_dir is not a folder.
    """
    import platform  # noqa: PLC0415
    from importlib import metadata  # noqa: PLC0415

    from auto_apply.adapters.secondary.research.replay_artifact_dir import (  # noqa: PLC0415
        ReplayArtifactDir,
    )
    from auto_apply.adapters.secondary.research.warc_replay_corpus import (  # noqa: PLC0415
        WarcReplayCorpus,
    )
    from auto_apply.application.services.replay_service import (  # noqa: PLC0415
        ReplayService,
    )

    try:
        aa_version = metadata.version("auto_apply")
    except metadata.PackageNotFoundError:
        aa_version = "unknown"

    def sink_for(corpus_digest: str) -> ReplayArtifactDir:
        return ReplayArtifactDir(out_dir or REPORTS_DIR / f"replay_{corpus_digest[:12]}")

    return ReplayService(
        WarcReplayCorpus(corpus_dir),
        sink_for,
        aa_version=aa_version,
        environment={
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "os": platform.system(),
        },
    ).run()


# --------------------------------------------------------------------------
# MAIN WIRING FUNCTION
# --------------------------------------------------------------------------

def build_orchestrator(  # noqa: PLR0914
    registry: CapabilitiesRegistry,
    driver: "BrowserInterface | None" = ...,  # type: ignore[assignment]
    research_consent: "ResearchConsentManager | None" = None,
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
            entirely (construction-only callers and tests — no perception or
            interaction adapters are built then). Omit to run the cascade.
        research_consent: The session's consent service, built by the caller
            via :func:`build_research_consent` so the SAME instance can be
            injected into the SessionController (mid-session withdrawal and
            shutdown reach the running observer through it). None builds an
            internal one — fine for construction-only callers, but nothing
            outside this function can then stop the observer.

    Ownership:
        The returned orchestrator owns the acquired driver's lifetime from
        this point. It is released exactly once, by
        ``AgentOrchestrator.shutdown()`` — reached from run()'s own exit and
        from ``SessionController.shutdown()``. Callers must not close the
        driver themselves.

    Returns:
        A fully wired AgentOrchestrator ready to call ``.run()``.

    Raises:
        BrowserSetupError: When the browser cascade ran and no driver could be
            acquired. STATIC_ASSISTED and the static-fetch discovery strategy
            are deleted (ruled 2026-09-08): a degraded session that can only
            idle and fail is worse for the user than an accurate refusal up
            front. Callers that pass ``driver=None`` explicitly (construction-
            only paths and tests) bypass this refusal by sentinel.
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

    if driver is None and not _cascade_skipped:
        # The cascade ran and could not produce a driver. STATIC_ASSISTED and
        # the static-fetch discovery strategy are deleted (ruled 2026-09-08):
        # a degraded session that can only idle and fail is worse for the user
        # than an accurate refusal up front. Refuse here, before any session
        # machinery is constructed.
        _refuse_no_browser(registry, cascade)

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
            # Both caps read through the typed EffectiveConfig — the first
            # two live callers of get_effective_settings().
            # daily_application_limit: the per-UTC-day cap, counted across
            # sessions. Sourced from the daily knob, NOT from
            # max_applications_per_session — those are different windows, and
            # feeding the session number in here made a user's configured
            # daily limit a dead write while silently capping every day at the
            # session number. The session cap is enforced separately by
            # AgentOrchestrator._session_cap_reached, so both still apply.
            # max_applications_per_company: YAML default 3; AdminPolicy has
            # no per-company field, so no policy clamp applies to this knob.
            daily_application_limit=(
                registry.get_effective_settings().daily_application_limit
            ),
            max_applications_per_company=(
                registry.get_effective_settings().max_applications_per_company
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

    from auto_apply.domain.ports.perception_port import PerceptionPort  # noqa: PLC0415

    perception_port: PerceptionPort | None

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
        # Explicit driver=None (construction-only callers and tests): no
        # perception adapter is constructed. BS4PerceptionAdapter's only
        # consumer was this branch; it is retired with the static mode.
        # Both workflows already degrade correctly on a None perception port
        # (VettingWorkflow returns the job title; ApplicationsWorkflow guards
        # every scan_page call).
        perception_port = None

    # ── The shared element-interaction tool ───────────────────────────────────
    # PageActionService owns every click, all pacing, and the seeded RNG; the
    # InteractionExecutor injected into the engines delegates to it. The RNG
    # namespace is allocated unconditionally so seeded stream allocation does
    # not depend on whether a driver was acquired.
    from auto_apply.application.services.page_action.service import (  # noqa: PLC0415
        PageActionService,
    )

    interaction_pacing_rng = behavior_params.make_rng("interaction.pacing")
    motion_pointer_rng = behavior_params.make_rng("motion.pointer")
    motion_wheel_rng = behavior_params.make_rng("motion.wheel")

    page_action_tool = (
        PageActionService(
            browser=driver,
            registry=registry,
            rng=interaction_pacing_rng,
            pointer_rng=motion_pointer_rng,
            wheel_rng=motion_wheel_rng,
        )
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

    from auto_apply.domain.ports.page_understanding_port import PageUnderstandingPort  # noqa: PLC0415

    page_understanding_port: PageUnderstandingPort | None = None

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

    # ── Research consent + observer ───────────────────────────────────────────
    # The consent service is built ALWAYS — it is the one answer to "is
    # research on?", for this build and (via the controller) for the user
    # surfaces. Only the AGGREGATOR is conditional, on
    # consent_service.should_collect(): consent granted and current, research
    # offered, no admin prohibition, and a salt available (FORK 1). Built
    # BEFORE the discovery providers so it can be injected into them:
    # providers hand it to the fast extractor and the SERP strategy, which
    # emit discovery-surface observations (§4b).
    from auto_apply.domain.ports.research_consent_port import (  # noqa: PLC0415
        ResearchConsentState,
    )
    from auto_apply.domain.ports.research_port import (  # noqa: PLC0415
        NullResearchObserver,
        ResearchObserverPort,
        ResearchSessionPort,
    )

    research_observer: ResearchObserverPort = NullResearchObserver()
    # The same object seen through its session-lifetime port (item 3): the
    # orchestrator stops it at teardown and reports its accounting.
    research_session: ResearchSessionPort = NullResearchObserver()

    consent_service = (
        research_consent
        if research_consent is not None
        else build_research_consent(registry)
    )
    _warn_if_legacy_research_db()

    if consent_service.is_active():
        # The salt is provisioned at grant; retry creation here so a grant
        # made when creation failed (read-only folder, transient error)
        # heals at the next session build instead of staying INACTIVE.
        consent_service.ensure_salt()

    if consent_service.should_collect():
        # Imported BEFORE the try so the `except ResearchSaltError` clause below
        # can never evaluate an unbound name: an early failure inside the try
        # would otherwise raise NameError from the handler itself.
        from auto_apply.domain.services.research_identity import (  # noqa: PLC0415
            ResearchSaltError,
        )

        try:
            from auto_apply.adapters.secondary.research.signal_aggregator import (  # noqa: PLC0415
                ResearchSignalAggregator,
            )
            _aggregator = ResearchSignalAggregator(
                db_path=RESEARCH_DB_PATH,
                consent_version=consent_service.consent_version,
                provenance_key_path=PROVENANCE_KEY_PATH,
            )
            _aggregator.start()
            # Registered BEFORE any workflow can observe: this registration is
            # the channel that lets a mid-session withdrawal — and session
            # shutdown — stop the running aggregator (FORK 3).
            consent_service.register_observer(_aggregator)
            research_observer = _aggregator
            research_session = _aggregator
            logger.info(
                "Research pipeline active (consent granted, version=%s)",
                consent_service.consent_version,
            )
        except ResearchSaltError as _exc:
            # A granted consent must never stop AA from starting (FORK 4 —
            # Option A, ruled 2026-10-01). should_collect() already checked
            # the salt; this catch covers a salt that vanished between the
            # check and the constructor. Research stays OFF, loudly, and the
            # session continues. Rows are never written without a private
            # salt because no aggregator exists to write them.
            logger.error(
                "build_orchestrator: research consent is granted but the "
                "research salt is unavailable (%s) — research is OFF for "
                "this session. The session is not affected.",
                _exc,
            )
        except Exception as _exc:
            logger.warning(
                "Research observer failed to initialize — using NullResearchObserver: %s",
                _exc,
            )
    else:
        _consent_status = consent_service.status()
        if _consent_status.state is ResearchConsentState.INACTIVE:
            # The user granted consent and expects collection — say plainly
            # why it is not happening (the surfaces show the same reason via
            # status()).
            logger.warning(
                "Research consent granted but collection is inactive | reason=%s",
                _consent_status.reason.value,
            )
        else:
            logger.info(
                "Research collection not active | state=%s",
                _consent_status.state.value,
            )

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
        from auto_apply.adapters.secondary.navigation.pagination import (  # noqa: PLC0415
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
        _paginator = (
            PaginationHandler(driver, interaction_port)
            if interaction_port is not None
            else None
        )

        from auto_apply.application.services.auditing.reporter import (  # noqa: PLC0415
            AuditReporter,
        )

        _audit_reporter = AuditReporter(driver)

        # ── Silent-degradation detector (S8k) ─────────────────────────────
        _degradation_detector = None
        try:
            from auto_apply.adapters.secondary.persistence.harvest_baseline_repository import (  # noqa: PLC0415
                HarvestBaselineRepository,
            )
            from auto_apply.application.services.auditing.degradation_detector import (  # noqa: PLC0415
                SilentDegradationDetector,
            )

            _baseline_repo = HarvestBaselineRepository(
                USER_DATA_DIR / "harvest_baselines.db"
            )
            _degradation_detector = SilentDegradationDetector(
                baseline_store=_baseline_repo,
                config=_effective_config.get("discovery", {}),
                event_bus=event_bus,
                deterministic=plan.is_deterministic,
            )
        except Exception as _exc:
            logger.warning(
                "build_orchestrator: degradation detector unavailable — "
                "providers run without the silent-degradation guard: %s",
                _exc,
            )

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
                degradation_detector=_degradation_detector,
                research_observer=research_observer,
                readiness=dom_readiness,
            ),
            BingProvider(
                browser=driver,
                page_understanding_port=page_understanding_port,
                scroller=_page_scroller,
                paginator=_paginator,
                max_pages=_max_pages_per_query,
                observer=_extraction_observer,
                reporter=_audit_reporter,
                forced_tier=_forced_tier,
                degradation_detector=_degradation_detector,
                research_observer=research_observer,
                readiness=dom_readiness,
            ),
            IndeedProvider(
                browser=driver,
                page_understanding_port=page_understanding_port,
                scroller=_page_scroller,
                paginator=_paginator,
                max_pages=_max_pages_per_query,
                observer=_extraction_observer,
                reporter=_audit_reporter,
                forced_tier=_forced_tier,
                degradation_detector=_degradation_detector,
                research_observer=research_observer,
                readiness=dom_readiness,
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

    # ── 5. Capability profile — gates task types based on driver availability ──
    _capability_profile = registry.build_capability_profile(
        driver is not None,
        research_consent=consent_service.is_active(),
        research_signals_active=research_observer.is_enabled,
    )
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
        page_copier=build_page_copier(
            registry,
            consent_service,
            profile,
            research_active=not isinstance(research_observer, NullResearchObserver),
        ),
    )

    # ── Context manager — tab/window switching for offsite apply clicks ────
    # Measured 2026-09-10: this class existed (and was constructed inside
    # other adapters) but was NEVER passed to ApplicationsWorkflow, so an
    # Apply control that opened a new tab stranded AA on the posting. Built
    # here for the same reason as the lease: the composition root is the
    # only layer that may construct adapters.
    _context_manager = None
    if driver is not None:
        try:
            from auto_apply.adapters.secondary.browser.context_manager import (  # noqa: PLC0415
                ContextManager,
            )
            _context_manager = ContextManager(driver)
        except Exception as _exc:
            logger.warning(
                "build_orchestrator: ContextManager unavailable — apply "
                "clicks that open a new tab cannot be followed: %s",
                _exc,
            )

    # ApplicationsWorkflow — try to construct each optional component.
    _field_classifier = None
    _semantic_filler = None
    _webpage_analyzer = None
    _interruption_handler: InterruptionHandlerPort = NullInterruptionHandler()
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
            from auto_apply.adapters.secondary.navigation.interruption import (  # noqa: PLC0415
                InterruptionHandler,
            )
            _interruption_handler = InterruptionHandler(browser=driver)
        except Exception as _exc:
            logger.warning(
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
        context_manager=_context_manager,  # follow new tabs after apply clicks
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
            from auto_apply.domain.ports.liveness_port import LivenessPort  # noqa: PLC0415
            if isinstance(driver, LivenessPort):
                browser_monitor = BrowserHealthMonitor(driver=driver, event_bus=event_bus)
            else:
                logger.info(
                    "build_orchestrator: driver does not support liveness probing — "
                    "browser health monitor disabled"
                )
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
        session_plan=plan,
        driver=driver,
        captcha_resolver=captcha_resolver,
        browser_monitor=browser_monitor,
        network_monitor=network_monitor,
        job_posting_resolver=job_posting_resolver,
        progress=progress_display,
        workflows={
            "DiscoveryWorkflow": discovery_workflow,
            "VettingWorkflow": vetting_workflow,
            "ApplicationsWorkflow": applications_workflow,
        },
        behavior_parameters=behavior_params,
        # The same instance the workflows observe through — aggregator or
        # Null — seen through its session-lifetime port (item 3).
        research_session=research_session,
    )

    logger.info(
        "build_orchestrator complete | providers=%d driver=%s",
        len(providers),
        "yes" if driver is not None else "no",
    )

    return orchestrator


def _refuse_no_browser(registry: CapabilitiesRegistry, cascade: BrowserCascade) -> None:
    """Refuse to build a session when no browser can be launched.

    Prints an actionable refusal to the user's terminal and raises
    BrowserSetupError so entry points exit non-zero. Detects and informs only —
    it downloads, installs, and modifies nothing on the user's machine.

    A 3-second accurate refusal is better for the worst-case user than a
    22-second session that idles and reports a failure they have to read a
    traceback to understand.
    """
    message_lines = [
        "",
        "AutoApply could not start: no usable browser was found on this machine.",
        "",
    ]

    attempt_log = cascade.get_attempt_log()
    if attempt_log:
        message_lines.append("Browsers tried:")
        for browser_name, succeeded, error in attempt_log:
            detail = f" — {error}" if error else ""
            message_lines.append(f"    [FAILED] {browser_name}{detail}")
    else:
        message_lines.append(
            "No browser or browser framework was detected on this machine, "
            "so nothing could be tried."
        )

    message_lines += [
        "",
        "AutoApply automates real websites and cannot run without a browser.",
        "What you can do:",
        "  1. Install Chrome, Firefox, or Edge (Safari on macOS), then run again.",
        "  2. Point AA at a portable browser binary instead:",
        "       AA_BROWSER_BINARY_PATH=/path/to/chrome-or-chromium",
        "       AA_FIREFOX_BINARY_PATH=/path/to/firefox",
        "     Snap-installed Firefox: point AA_FIREFOX_BINARY_PATH at the real",
        "     in-snap executable, e.g. /snap/firefox/current/usr/lib/firefox/firefox",
    ]

    policy = registry.get_admin_policy()
    # Bound to a typed local and tested with `is not None`: a getattr-with-
    # default guard was opaque to mypy here (list[str] | None reaching join).
    # Semantics: None is the ONLY "no restriction" state per AdminPolicy's own
    # contract ("None = all permitted"). An empty list is NOT "no restriction"
    # — it is the most restrictive policy there is, an administrator allowing
    # nothing, and silencing it would hide the reason AA cannot start from the
    # exact managed-machine user this refusal exists to inform.
    allowed_browsers: list[str] | None = (
        policy.allowed_browsers if policy is not None else None
    )
    if allowed_browsers is not None:
        if allowed_browsers:
            message_lines += [
                "",
                "Note: an admin policy on this machine restricts browsers to: "
                + ", ".join(allowed_browsers)
                + ". Only those will be tried.",
            ]
        else:
            message_lines += [
                "",
                "Note: an admin policy on this machine allows NO browsers. "
                "The policy must be corrected or removed before AutoApply "
                "can start.",
            ]
    message_lines.append("")

    message = "\n".join(message_lines)
    logger.error(
        "build_orchestrator: refusing startup — no browser available"
    )
    print(message, file=sys.stderr)
    raise BrowserSetupError(message)


def _register_exit_shutdown(
    controller: "SessionController",
    instances: "InstanceRegistry | None" = None,
) -> None:
    """Registers a WEAK atexit hook that shuts *controller* down at interpreter exit.

    This is the last-resort release net for exits nobody named: a sys.exit
    on a path without a finally, an unhandled exception, a signal handler
    that exits the process. The explicit paths — run()'s own exit and
    SessionController.shutdown() from the GUI close, the CLI finally, or the
    next Start — run first and make this a no-op.

    The reference is deliberately weak. A strong one would pin every
    controller — and its live browser, against the shared --user-data-dir —
    until process exit, turning "controller dropped without shutdown" from a
    case garbage collection currently rescues into a guaranteed refusal of
    the next build. With the weak form, a controller still reachable at exit
    is shut down explicitly; one already collected is left to the GC rescue
    that works today. A killed process (SIGKILL, Task Manager, power loss)
    runs no atexit hooks; nothing in-process can cover that.
    """
    import atexit  # noqa: PLC0415
    import weakref  # noqa: PLC0415

    controller_ref = weakref.ref(controller)

    def _shutdown_if_alive() -> None:
        instance = controller_ref()
        try:
            if instance is not None:
                try:
                    instance.shutdown()
                except Exception:  # noqa: BLE001 — an atexit hook must never raise
                    pass
        finally:
            # The instance record must go even when the controller was
            # already collected — otherwise the registry reports a dead
            # process as live until the next liveness sweep.
            if instances is not None:
                try:
                    instances.unregister()
                except Exception:  # noqa: BLE001 — an atexit hook must never raise
                    pass

    atexit.register(_shutdown_if_alive)


def build_session_controller(
    profile: "UserProfile",
    profile_repo: "ProfileRepositoryPort | None" = None,
) -> "SessionController":
    """Factory that builds a fully‑wired SessionController for *profile*.

    This is the single entry point used by the GUI and CLI launch sequences.
    It runs the full boot sequence (registry → orchestrator → controller)
    and performs the post‑construction initialisation that was previously
    buried inside the now‑removed ``from_profile`` classmethod.

    Args:
        profile: A loaded and validated UserProfile.
        profile_repo: Optional ProfileRepositoryPort for custody operations
            (export_profile). The CLI and GUI pass the repository they already
            own; without it, controller.export_profile raises a clear error.

    Returns:
        A SessionController instance ready to call ``.initialize_session()``.

    Lifecycle:
        The caller owns ending the session: call ``controller.shutdown()``
        on every exit path (window close, CLI exit, the next Start). It
        releases the browser whether or not a run is active. The weak
        atexit hook registered below is the last resort for exits no caller
        named — it cannot help a killed process, and it deliberately does
        not pin the controller; see ``_register_exit_shutdown``.
    """
    from auto_apply.application.services.session_controller import SessionController  # noqa: PLC0415
    from auto_apply.domain.models.profile import UserProfile  # noqa: PLC0415

    # 1. Build authoritative configuration
    registry = CapabilitiesRegistry.build(user_profile=profile)

    # 2. Build the research-consent service, then the fully wired orchestrator.
    # The consent service comes first so the session's research observer can
    # register with it; the SAME instance is injected into the controller
    # below, so a mid-session withdrawal and shutdown both reach the running
    # observer (FORK 3). The pre-session surfaces use the same builder with
    # no registry.
    research_consent = build_research_consent(registry)
    orchestrator = build_orchestrator(registry, research_consent=research_consent)

    # 3. Assemble the controller (all deps injected). If assembly fails after
    # the orchestrator exists, its browser has no owner yet — release it here
    # rather than stranding it against the shared profile directory.
    try:
        controller = SessionController(
            registry=registry,
            db=orchestrator.task_queue,      # DatabaseManager implements WorkQueuePort
            orchestrator=orchestrator,
            profile_repo=profile_repo,
            research_consent=research_consent,
        )
    except Exception:
        orchestrator.shutdown()
        raise

    # 4. Post‑construction initialisation (previously inside from_profile)
    controller._perform_startup_recovery()   # reset stuck IN_PROGRESS tasks
    controller._wire_approval_gate()         # bind HITL gate to workflow

    # 5. Instance registry — how a future uninstall tells this process is
    # alive. A DIRECTORY of per-process records, not a lock: a lock goes
    # stale on SIGKILL and forbids legitimate concurrent instances; liveness
    # is re-checked on read, PID-reuse included.
    from auto_apply.application.services.instance_registry import InstanceRegistry  # noqa: PLC0415

    instances = InstanceRegistry(INSTANCES_DIR)
    instances.register()

    # 6. Last-resort release net — see _register_exit_shutdown. Covers exits
    # no caller names (a stray sys.exit, an unhandled exception) by shutting
    # the controller down at interpreter exit IF it is still alive. Cannot
    # cover a killed process (SIGKILL, Task Manager, power loss); nothing
    # in-process can.
    _register_exit_shutdown(controller, instances=instances)

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

    # Bootstrap creates the hierarchy explicitly; the import-time creation
    # in domain.config is suppressed on the uninstall path
    # (AA_NO_CREATE_DIRS), which never reaches this function.
    ensure_data_dirs()
    DatabaseManager()  # Initializes DB / creates tables if absent.
    # Record how this AA arrived — the uninstaller reads the ledger instead
    # of guessing the install route (last roots record wins).
    from auto_apply.application.services.footprint_ledger import (  # noqa: PLC0415
        FootprintLedger,
    )

    FootprintLedger(FOOTPRINT_LEDGER_PATH).record_roots(
        run_mode=get_run_mode(),
        data_root=USER_DATA_DIR,
        install_root=get_install_root(),
    )
    return ProfileRepository(master_password=master_password)
