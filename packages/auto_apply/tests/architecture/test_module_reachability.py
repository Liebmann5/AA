"""Pins: module reachability, import-ability, and internal name resolution.

Three checks over ``src/auto_apply``:

1. REACHABILITY (characterization). BFS from the entry points over import
   edges. Every import statement in a file — module-level or lazy, absolute
   ``auto_apply.*`` only — counts as an edge; that is how the lazily-wired
   composition root keeps its providers reachable. A module no entry point
   can reach is either an orphan or a mistake. Exemptions live in
   KNOWN_UNREACHABLE: the orphan inventory, one-line reason + disposition
   tag (WIRE-LATER · RETIRE-CANDIDATE · PLANNED · TEST-ONLY) per entry.

2. IMPORTABILITY (teeth). Every src module is imported once in a subprocess
   and failures are reported as BROKEN INTERNAL IMPORT. This is the check
   that caught the four modules deleted on 2026-08-30 — compileall never
   imports, so it cannot catch this class of bug; a real import can.

3. NAME RESOLUTION (R-C; teeth proven by fixture, R-D). For every top-level,
   non-TYPE_CHECKING ``from auto_apply.X import NAME`` where ``auto_apply.X``
   resolves to a module FILE, verify NAME is bound at module scope in that
   file. Skipped: TYPE_CHECKING imports, package targets, targets containing
   ``import *`` (undecidable), targets that do not parse, and submodule
   imports (``auto_apply.X.NAME`` resolves to a file). Reported as
   BROKEN INTERNAL NAME alongside category 2. The check finds zero on the
   current tree because the four modules that proved the gap were deleted
   before it existed — the regression fixture in fixtures/broken_name_case.py
   reconstructs telemetry.py's exact shape and the third test asserts the
   check flags it. Without that fixture this would be a coverage pin wearing
   a teeth label.

MAX_EXEMPTIONS is a CEILING, not an equality (R-E): a lower count is
success — remove entries as modules get wired; only adding an exemption may
push the count up, and only with a written reason. Stale exemptions (a
module became reachable) are reported separately and fail the pin.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from ._binding import top_level_bindings

_PKG_ROOT = Path(__file__).resolve().parents[2]
_SRC_DIR = _PKG_ROOT / "src" / "auto_apply"

ENTRY_POINTS = [
    "auto_apply.__main__",
    "auto_apply.main",
    "auto_apply.adapters.primary.cli.startup",
    "auto_apply.adapters.primary.gui.app",
    "auto_apply.infrastructure.composition_root",
]


# ─────────────────────────────────────────────────────────────────────────────
# Exemption inventory — the current orphans, each with a one-line reason and a
# disposition tag. Wiring a module deletes its entry here AND usually one in
# KNOWN_UNWIRED_PORTS (test_port_wiring.py) — the same fact shows in both pins.
# ─────────────────────────────────────────────────────────────────────────────

KNOWN_UNREACHABLE: dict[str, tuple[str, str]] = {
    "auto_apply.adapters.primary.gui.ui_handler": (
        "WIRE-LATER",
        "UIMessageHandler logging bridge; the GUI builds the dashboard "
        "directly in gui/app.py and this handler is constructed nowhere",
    ),
    "auto_apply.adapters.secondary.browser.browser_lifecycle": (
        "WIRE-LATER",
        "BrowserManager context manager; the orchestrator closes the driver "
        "via ResilientDriver/_teardown instead",
    ),
    "auto_apply.adapters.secondary.browser.static_fetch_adapter": (
        "PLANNED",
        "empty stub for the zero-browser fetch adapter (Bible 7.1); "
        "BS4PerceptionAdapter currently covers static perception",
    ),
    "auto_apply.adapters.secondary.discovery.components.toolbar_navigator": (
        "WIRE-LATER",
        "careers-link discovery for company homepages; DISCOVER_COMPANY goes "
        "through composition_root._company_page_scraper instead",
    ),
    "auto_apply.adapters.secondary.discovery.strategies.linkedin_easy_apply": (
        "WIRE-LATER",
        "LinkedIn Easy Apply FSM strategy (Bible P3-13); no strategy registry "
        "selects it. Note: its InteractionPort annotation is what keeps that "
        "port wired",
    ),
    "auto_apply.adapters.secondary.discovery.strategies.selector_loader": (
        "WIRE-LATER",
        "YAML selector loader for ToolbarElementLocator (AD-9); nothing calls "
        "SearchEngineStrategy.set_locator so it is never constructed",
    ),
    "auto_apply.adapters.secondary.discovery.strategies.toolbar_locator": (
        "WIRE-LATER",
        "selector+fallback locator (AD-9); wired only via set_locator, which "
        "has no caller",
    ),
    "auto_apply.adapters.secondary.evasion.auditor": (
        "WIRE-LATER",
        "fingerprint audit display using requests; evasion audit wiring "
        "deferred (Bible 16)",
    ),
    "auto_apply.adapters.secondary.evasion.captcha_handler": (
        "WIRE-LATER",
        "AudioCaptchaSolver scaffold whose solve() returns False; the "
        "orchestrator uses CaptchaResolutionService "
        "(resolution/captcha_adapter.py) instead",
    ),
    "auto_apply.adapters.secondary.evasion.components.session": (
        "WIRE-LATER",
        "SessionManager persona persistence + warmup (Bible 16.1); the "
        "cascade/orchestrator do not construct it yet",
    ),
    "auto_apply.adapters.secondary.evasion.fingerprint_chrome": (
        "WIRE-LATER",
        "CDP spoof suite; no caller — evasion fingerprinting is not applied "
        "by the cascade yet",
    ),
    "auto_apply.adapters.secondary.evasion.fingerprint_firefox": (
        "WIRE-LATER",
        "Firefox JS spoof suite; no caller — same unwired evasion layer as "
        "fingerprint_chrome",
    ),
    "auto_apply.adapters.secondary.evasion.fingerprinting": (
        "WIRE-LATER",
        "FingerprintMasker entry point for the two spoof suites above; "
        "constructed nowhere",
    ),
    "auto_apply.adapters.secondary.interaction.api_direct_adapter": (
        "PLANNED",
        "empty stub for the headless APIDirectAdapter interaction path "
        "(Bible 7.4)",
    ),
    "auto_apply.adapters.secondary.interaction.execution_strategies": (
        "WIRE-LATER",
        "Stealth/Instant strategies for InteractionExecutor; the composition "
        "root builds the executor without a strategy",
    ),
    "auto_apply.adapters.secondary.network.network": (
        "RETIRE-CANDIDATE",
        "empty module with no content and no plan reference; retire to "
        "docs/old_retired_files/ if nothing claims it",
    ),
    "auto_apply.adapters.secondary.network.resilient_http": (
        "WIRE-LATER",
        "requests-based retry client; UrllibHTTPClient is the wired default "
        "(Bible 22.2 lists HTTPX/requests as an upgrade path)",
    ),
    "auto_apply.adapters.secondary.network.watchdog": (
        "RETIRE-CANDIDATE",
        "ConnectionWatchdog duplicates what NetworkHealthMonitor now covers "
        "(connectivity monitoring); no caller",
    ),
    "auto_apply.adapters.secondary.perception.aom_adapter": (
        "WIRE-LATER",
        "AOM scanner/resolver; perception_strategy='aom' is a documented "
        "option the composition root does not implement",
    ),
    "auto_apply.adapters.secondary.persistence.atomic": (
        "WIRE-LATER",
        "atomic_write_json helper; ProfileRepository duplicates the same "
        "pattern inline (_atomic_write_text/_bytes) — dedupe when touched",
    ),
    "auto_apply.adapters.secondary.reasoning.asp_adapter": (
        "PLANNED",
        "Clingo ASP form reasoning (Bible P3-5); cross-ref "
        "KNOWN_UNWIRED_PORTS/ILogicSolver",
    ),
    "auto_apply.adapters.secondary.reasoning.llm_adapter": (
        "PLANNED",
        "empty stub for the vendor-agnostic LLM slot (Bible 17.2)",
    ),
    "auto_apply.adapters.secondary.research.sqlite_audit_repository": (
        "WIRE-LATER",
        "audit persistence adapter; AuditCoordinator exists but the "
        "composition root never builds either (consent-gated research audit "
        "mode)",
    ),
    "auto_apply.adapters.secondary.resolution.logic_adapter": (
        "PLANNED",
        "empty stub for the LogicAdapter resolution port impl (Bible 4.2)",
    ),
    "auto_apply.application.agent.watchdog": (
        "WIRE-LATER",
        "ProviderWatchdog (Bible Phase 5); the orchestrator accepts it but "
        "the composition root passes watchdog=None",
    ),
    "auto_apply.application.services.accessibility": (
        "WIRE-LATER",
        "a11y theming config; the GUI never calls configure_accessibility yet",
    ),
    "auto_apply.application.services.audit_coordinator": (
        "WIRE-LATER",
        "correspondence-audit scheduler; consent-gated research mode not "
        "wired in the composition root",
    ),
    "auto_apply.application.services.auditing.browser_audit": (
        "WIRE-LATER",
        "BrowserAuditor fingerprint snapshot; AuditReporter does not use it",
    ),
    "auto_apply.application.services.location.haversine": (
        "WIRE-LATER",
        "HaversineCalculator implements DistanceCalculatorPort, but "
        "SpatialLocationFilter inlines the same math — cross-ref "
        "KNOWN_UNWIRED_PORTS/DistanceCalculatorPort",
    ),
    "auto_apply.domain.applications.fsm.base": (
        "WIRE-LATER",
        "BaseApplicationStrategy ABC; its only importer is "
        "linkedin_easy_apply.py, itself unreachable",
    ),
    "auto_apply.domain.browser_state": (
        "RETIRE-CANDIDATE",
        "audit snapshot models used only by the unwired evasion/auditor.py; "
        "0 other importers, no standing ruling",
    ),
    "auto_apply.domain.models.execution": (
        "RETIRE-CANDIDATE",
        "SchedulingMode/ExecutionConfiguration predate SessionPlan; "
        "0 importers, no standing ruling",
    ),
    "auto_apply.domain.models.plan": (
        "RETIRE-CANDIDATE",
        "empty module; 0 importers",
    ),
    "auto_apply.domain.models.task_lifecycle": (
        "RETIRE-CANDIDATE",
        "TaskLifecycleState; 0 importers — the work_queue stores raw status "
        "strings (AD-2)",
    ),
    "auto_apply.domain.ports.accessibility_port": (
        "WIRE-LATER",
        "unreachable because its port IAccessibilityScanner has no consumer "
        "— same fact, two pins; cross-ref KNOWN_UNWIRED_PORTS",
    ),
    "auto_apply.domain.ports.audit_port": (
        "WIRE-LATER",
        "AuditRepositoryPort HAS a consumer (audit_coordinator.py) but that "
        "consumer is itself unwired, so nothing reachable imports this module",
    ),
    "auto_apply.domain.ports.environment_capabilities_port": (
        "WIRE-LATER",
        "unreachable because EnvironmentCapabilitiesProvider has no consumer "
        "(PolicyEnforcement uses the broader RegistryPort) — same fact, two pins",
    ),
    "auto_apply.domain.ports.health_monitor_port": (
        "WIRE-LATER",
        "unreachable because HealthMonitor has no consumer (orchestrator "
        "holds monitors as Any) — same fact, two pins",
    ),
    "auto_apply.domain.ports.interaction_primitives_port": (
        "WIRE-LATER",
        "unreachable because PageActionPrimitives/DomReadinessPort/"
        "PageNavigationPort have no executable consumers — same fact, two pins",
    ),
    "auto_apply.domain.ports.page_classification_port": (
        "WIRE-LATER",
        "unreachable because PageClassifierPort has no consumer "
        "(GenericSERPStrategy constructs PageClassifier concretely) — same "
        "fact, two pins",
    ),
    "auto_apply.domain.ports.raw_driver_port": (
        "WIRE-LATER",
        "unreachable because SupportsRawDriver/SupportsRawPage have no "
        "consumer (callers use getattr probes) — same fact, two pins",
    ),
    "auto_apply.domain.ports.reasoning_port": (
        "WIRE-LATER",
        "unreachable because ReasoningPort and ILogicSolver have no "
        "executable consumers — same fact, two pins",
    ),
    "auto_apply.domain.ports.serp_extraction_port": (
        "WIRE-LATER",
        "unreachable because SerpExtractionPort has no consumer "
        "(GenericSERPStrategy takes fast_extractor untyped) — same fact, "
        "two pins",
    ),
    "auto_apply.domain.ports.text_generation_port": (
        "WIRE-LATER",
        "unreachable because TextGenerationPort has no consumer (workflows "
        "take text_generation_port untyped) — same fact, two pins",
    ),
    "auto_apply.domain.retry": (
        "RETIRE-CANDIDATE",
        "retry decorator; 0 importers, no standing ruling",
    ),
    "auto_apply.domain.services.entropy": (
        "WIRE-LATER",
        "dead as one chain with occlusion + honeypot_detection (0 importers "
        "each); standing ruling is keep-and-wire — wiring one revives all three",
    ),
    "auto_apply.domain.services.honeypot_detection": (
        "WIRE-LATER",
        "dead as one chain with entropy + occlusion; standing ruling is "
        "keep-and-wire",
    ),
    "auto_apply.domain.services.occlusion": (
        "WIRE-LATER",
        "dead as one chain with entropy + honeypot_detection; standing "
        "ruling is keep-and-wire",
    ),
    "auto_apply.domain.services.transformations": (
        "WIRE-LATER",
        "CSS-transform polygon math for the math subsystem; no current "
        "consumer in dom_segmentation",
    ),
    "auto_apply.resources.research": (
        "PLANNED",
        "empty package marker for future research data assets",
    ),
}

# Ceiling, not equality (R-E). A lower count is success.
MAX_EXEMPTIONS = 50


# ─────────────────────────────────────────────────────────────────────────────
# Reachability scan
# ─────────────────────────────────────────────────────────────────────────────


def _iter_src_files() -> list:
    return [
        p
        for p in sorted(_SRC_DIR.rglob("*.py"))
        if "__pycache__" not in p.parts
    ]


def _module_name_for(path: Path) -> str:
    rel = path.relative_to(_SRC_DIR).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(["auto_apply"] + parts)


def _scan() -> dict:
    """Parse every src module; build the module set and the import-edge map."""
    info: dict = {}
    modules: set = set()
    packages: set = set()
    for path in _iter_src_files():
        name = _module_name_for(path)
        rel = path.relative_to(_PKG_ROOT).as_posix()
        modules.add(name)
        if path.name == "__init__.py":
            packages.add(name)
        raw_edges: set = set()
        syntax_error = False
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            syntax_error = True
            tree = None
        if tree is not None:
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "auto_apply" or alias.name.startswith(
                            "auto_apply."
                        ):
                            raw_edges.add(alias.name)
                elif isinstance(node,ast.ImportFrom):
                    if node.level == 0:
                       base = node.module
                       if not base or not (
                           base == "auto_apply" or base.startswith("auto_apply.")
                       ):
                           continue
                    else:
                        # Relative import. src/ has only two (network/__init__.py)
                        # and dropping them makes robots + throttler look orphaned.
                        container = (
                            name if name in packages else name.rpartition(".")[0]
                        )
                        parts = container.split(".") if container else []
                        up = node.level - 1
                        if up > len(parts):
                            continue  # relative import above src/; skip
                        if up:
                            parts = parts[: len(parts) -up]
                        if node.module:
                            parts = parts + node.module.split(".")
                        base = ".".join(parts) if parts else ""
                        if not base:
                            continue  # relative import to src/ itself; skip
                    raw_edges.add(base)
                    # ` from pkg import name` imports pkg/name.py as a side effect.
                    # Without this edge, modules imported that way look unreachable.
                    for alias in node.names:
                        if alias.name != "*":
                            raw_edges.add(f"{base}.{alias.name}")
        info[name] = {
            "raw_edges": raw_edges,
            "edges": set(),
            "syntax_error": syntax_error,
            "rel": rel,
        }

    # Resolve raw import targets down to modules that actually exist. A target
    # may name a namespace package (a directory with no __init__.py, e.g.
    # adapters/secondary/evasion/components), which is not a module - leaving it
    # on the frontier makes the BFS raise KeyError.
    for record in info.values():
        resolved: set = set()
        for target in record["raw_edges"]:
            parts = target.split(".")
            for i in range(len(parts), 0, -1):
                candidate = ".".join(parts[:i])
                if candidate in modules:
                    resolved.add(candidate)
        record["edges"] = resolved

    return {
        "info": info,
        "modules": modules,
        "entries": set(ENTRY_POINTS),
    }


def _ceiling_failure() -> str:
    if len(KNOWN_UNREACHABLE) > MAX_EXEMPTIONS:
        return (
            f"EXEMPTION CEILING EXCEEDED: {len(KNOWN_UNREACHABLE)} exemptions "
            f"recorded but MAX_EXEMPTIONS={MAX_EXEMPTIONS}. A count BELOW the "
            "ceiling is success — remove entries as modules get wired; only a "
            "new orphan may push the count up, and only with a written reason."
        )
    return ""


def test_every_src_module_is_reachable_from_an_entry_point() -> None:
    """Every module must have an import path from at least one entry point."""
    scan = _scan()
    info = scan["info"]
    modules = scan["modules"]
    entries = sorted(scan["entries"])

    failures: list[str] = []

    missing_entries = [e for e in entries if e not in modules]
    if missing_entries:
        failures.append("ENTRY POINT MISSING — the pin's own seed list is broken:")
        for entry in missing_entries:
            failures.append(f"  proof: '{entry}' maps to no file under src/")

    reached: set = set()
    stack = [e for e in entries if e in modules]
    reached.update(stack)
    while stack:
        current = stack.pop()
        for target in info[current]["edges"]:
            if target not in reached:
                reached.add(target)
                stack.append(target)
        parent = current.rpartition(".")[0]
        if parent and parent in modules and parent not in reached:
            reached.add(parent)
            stack.append(parent)

    unparsed = sorted(n for n in modules if info[n]["syntax_error"])
    unreachable = sorted(
        n for n in modules if n not in reached and not info[n]["syntax_error"]
    )

    flag_lines: dict[str, list[str]] = {}
    for name in unreachable:
        flag_lines[name] = [
            f"UNREACHABLE MODULE — {name}\n"
            f"  proof: parses cleanly; 0 inbound import edges from any entry "
            f"point\n"
            f"  file: {info[name]['rel']}"
        ]

    flagged = set(flag_lines)
    unexpected = sorted(flagged - set(KNOWN_UNREACHABLE))
    stale = sorted(set(KNOWN_UNREACHABLE) - flagged)

    if unexpected:
        failures.append("UNEXEMPTED REACHABILITY FAILURES:")
        for name in unexpected:
            failures.extend(flag_lines[name])
    if stale:
        failures.append("")
        failures.append("STALE EXEMPTIONS (module is reachable now — remove these):")
        failures.extend(f"  {name}" for name in stale)
    if unparsed:
        failures.append("")
        failures.append(
            f"NOTE: {len(unparsed)} module(s) excluded here because they do not "
            "parse — see test_src_modules_are_importable for those."
        )
        failures.extend(f"  {name}" for name in unparsed)
    count_failure = _ceiling_failure()
    if count_failure:
        failures.append("")
        failures.append(count_failure)

    assert not failures, (
        "\nREACHABILITY REPORT — BFS over runtime import edges from entry "
        "points: " + ", ".join(entries) + "\n"
        + "=" * 72
        + "\n"
        + "\n".join(failures)
        + "\n"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Importability + name resolution (R-C)
# ─────────────────────────────────────────────────────────────────────────────

_IMPORT_PROBE = r"""
import importlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root.parent))
failures = []
for path in sorted(root.rglob("*.py")):
    if "__pycache__" in path.parts:
        continue
    parts = list(path.relative_to(root).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    mod = "auto_apply" + ("." + ".".join(parts) if parts else "")
    try:
        importlib.import_module(mod)
    except Exception as exc:
        failures.append([mod, "%s: %s" % (type(exc).__name__, exc)])
print(json.dumps(failures))
"""


def _is_type_checking(test: ast.expr) -> bool:
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


def _iter_top_level_import_froms(tree: ast.Module):
    """Yield ImportFrom nodes at module scope, recursing into module-level
    if (non-TYPE_CHECKING) / try / with bodies, never into def/class bodies."""
    def _block(stmts):
        for node in stmts:
            if isinstance(node, ast.ImportFrom):
                yield node
            elif isinstance(node, ast.If):
                if _is_type_checking(node.test):
                    continue
                yield from _block(node.body)
                yield from _block(node.orelse)
            elif isinstance(node, ast.Try):
                yield from _block(node.body)
                for handler in node.handlers:
                    yield from _block(handler.body)
                yield from _block(node.orelse)
                yield from _block(node.finalbody)
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                yield from _block(node.body)

    yield from _block(tree.body)


def _resolve_module_file(dotted: str):
    """Resolve 'auto_apply.x.y' to a module FILE path, or None if it is a
    package or does not exist."""
    parts = dotted.split(".")
    if not parts or parts[0] != "auto_apply":
        return None
    candidate = _SRC_DIR.joinpath(*parts[1:]).with_suffix(".py")
    return candidate if candidate.is_file() else None


def _is_package(dotted: str) -> bool:
    parts = dotted.split(".")
    if not parts or parts[0] != "auto_apply":
        return False
    return (_SRC_DIR.joinpath(*parts[1:]) / "__init__.py").is_file()


def _has_star_import(path: Path) -> bool:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return True  # unparsable target: skip, reported elsewhere
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and any(a.name == "*" for a in node.names):
            return True
    return False


@dataclass
class _BrokenName:
    importer_rel: str
    lineno: int
    imported_name: str
    target_dotted: str
    target_rel: str

    def report(self) -> str:
        return (
            f"BROKEN INTERNAL NAME — {self.importer_rel}:{self.lineno} imports "
            f"'{self.imported_name}' from {self.target_dotted} "
            f"({self.target_rel}), which binds no such name at module scope"
        )


def _broken_from_import_names(path: Path) -> list:
    """R-C: for each top-level, non-TYPE_CHECKING 'from auto_apply.X import
    NAME' in *path* where auto_apply.X resolves to a module file, verify NAME
    is bound at module scope in that file."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []
    importer_rel = path.relative_to(_PKG_ROOT).as_posix() if path.is_relative_to(_PKG_ROOT) else path.as_posix()
    broken: list = []
    for node in _iter_top_level_import_froms(tree):
        if node.level != 0 or not node.module:
            continue
        dotted = node.module
        if dotted != "auto_apply" and not dotted.startswith("auto_apply."):
            continue
        target_file = _resolve_module_file(dotted)
        if target_file is None:
            # Package target, missing module (the import probe reports that),
            # or submodule import — all skipped per R-C.
            if _is_package(dotted):
                continue
            submodule_hits = any(
                _resolve_module_file(f"{dotted}.{alias.name}") is not None
                for alias in node.names
            )
            if submodule_hits:
                continue
            continue
        if _has_star_import(target_file):
            continue  # undecidable
        try:
            bindings = top_level_bindings(target_file)
        except SyntaxError:
            continue  # unparsable target: the import probe reports it
        target_rel = target_file.relative_to(_PKG_ROOT).as_posix()
        for alias in node.names:
            if alias.name != "*" and alias.name not in bindings:
                broken.append(
                    _BrokenName(
                        importer_rel=importer_rel,
                        lineno=node.lineno,
                        imported_name=alias.name,
                        target_dotted=dotted,
                        target_rel=target_rel,
                    )
                )
    return broken


def test_src_modules_are_importable() -> None:
    """Every src module imports cleanly, and every top-level internal
    from-import names something that actually exists."""
    failures: list[str] = []

    # ── 1. Real-import check in a subprocess (teeth) ────────────────────────
    proc = subprocess.run(
        [sys.executable, "-c", _IMPORT_PROBE, str(_SRC_DIR)],
        capture_output=True,
        text=True,
        timeout=600,
    )
    stdout_lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
    import_failures: list = []
    if stdout_lines:
        try:
            import_failures = json.loads(stdout_lines[-1])
        except json.JSONDecodeError:
            pass
    if proc.returncode != 0 and not import_failures:
        failures.append(
            "IMPORT PROBE ITSELF FAILED — the pin cannot check anything:\n"
            + (proc.stderr or "").strip()[:800]
        )
    for mod, err in import_failures:
        failures.append(f"BROKEN INTERNAL IMPORT — {mod}: {err}")

    # ── 2. Name-resolution check (R-C) ──────────────────────────────────────
    for path in _iter_src_files():
        for broken in _broken_from_import_names(path):
            failures.append(broken.report())

    assert not failures, (
        "\nIMPORTABILITY REPORT — subprocess import of every src module plus "
        "top-level internal from-import name resolution\n"
        + "=" * 72
        + "\n"
        + "\n".join(failures)
        + "\n"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Regression fixture teeth (R-D)
# ─────────────────────────────────────────────────────────────────────────────


def test_name_resolution_check_flags_broken_internal_names() -> None:
    """The R-C check must flag the exact shape that deleted telemetry.py had:
    a top-level from-import of a name that does not exist in the target
    module. The fixture also carries a good import; it must not be flagged."""
    fixture = Path(__file__).resolve().parent / "fixtures" / "broken_name_case.py"
    assert fixture.is_file(), f"regression fixture missing: {fixture}"

    broken = _broken_from_import_names(fixture)

    assert len(broken) == 1, (
        "expected exactly one BROKEN INTERNAL NAME from the fixture "
        f"(telemetry.py's shape), got: {[b.report() for b in broken]}"
    )
    hit = broken[0]
    assert hit.imported_name == "APP_DATA_DIR", hit.report()
    assert hit.target_dotted == "auto_apply.domain.config", hit.report()
