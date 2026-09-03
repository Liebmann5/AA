"""Pin: every port declared in domain/ports/ is wired — implemented and consumed.

What this pin checks, and what it deliberately does not check.

For every Protocol/ABC class discovered in ``src/auto_apply/domain/ports/``:

  IMPLEMENTER — at least one concrete class in src/ either
    (a) explicitly subclasses the port (``class X(ThePort)``), or
    (b) STRUCTURALLY satisfies it: the class defines every member the port
        declares (R-A). This codebase uses ``typing.Protocol`` structurally;
        structural implementers do NOT import the port, and requiring the
        import was measured to over-flag (24 → 33, breaking nine legitimately
        wired ports). The import is therefore not required.

  CONSUMER — at least one file other than the port's own file references the
    port name in an EXECUTABLE position: an annotation, a call, a base class,
    an isinstance, an assignment. Two rules (R-B):

    1. Only an EXPLICIT-subclass implementer removes its file from the
       consumer scan. A structural implementer stays eligible — a file may
       legitimately define a structural test double and consume the port in
       the same module (e.g. application/services/research_consent.py).
    2. A bare import is NOT consumption. The name must appear outside its own
       ImportFrom alias, outside ``if TYPE_CHECKING:`` blocks, and not inside
       a string annotation.

Failure modes (both are flagged per port):

  PORT WITHOUT IMPLEMENTER — nothing implements the contract.
  PORT WITHOUT CONSUMER    — something implements it, nothing calls it.

Exemptions live in KNOWN_UNWIRED_PORTS. The dict is the orphan inventory:
every entry carries a one-line reason and a disposition tag from exactly
WIRE-LATER · RETIRE-CANDIDATE · PLANNED · TEST-ONLY. MAX_EXEMPTIONS is a
CEILING, not an equality (R-E): a lower count is success — remove entries as
ports get wired; only adding exemptions should ever push the count up, and
adding one requires a written reason. Stale exemptions (the port got wired)
are reported separately and fail the pin.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

_PKG_ROOT = Path(__file__).resolve().parents[2]
_SRC_DIR = _PKG_ROOT / "src" / "auto_apply"
_PORTS_DIR = _SRC_DIR / "domain" / "ports"

_PORT_BASE_NAMES = frozenset({"Protocol", "ABC"})


# ─────────────────────────────────────────────────────────────────────────────
# Exemption inventory — the current unwired ports, each with a one-line reason
# and a disposition tag. Wiring a port deletes its entry here AND usually one
# in KNOWN_UNREACHABLE (test_module_reachability.py) — the same fact shows up
# in both pins.
# ─────────────────────────────────────────────────────────────────────────────

KNOWN_UNWIRED_PORTS: dict[str, tuple[str, str]] = {
    "ATSPort": (
        "PLANNED",
        "per-platform ATS adapters are future work (Bible 15.4 step 3); "
        "ATSRegistryPort is the live contract — flagged both implementer-less "
        "and consumer-less",
    ),
    "Repository": (
        "PLANNED",
        "generic 4-method ABC predates JobRepositoryPort; nothing implements "
        "it and JobRepositoryPort is what the orchestrator actually consumes",
    ),
    "DiscoveryProviderPort": (
        "WIRE-LATER",
        "providers are consumed duck-typed by DiscoveryWorkflow (untyped "
        "list); typing the workflow against the port is a batch-2 change",
    ),
    "DistanceCalculatorPort": (
        "WIRE-LATER",
        "implemented by HaversineCalculator but SpatialLocationFilter inlines "
        "the haversine math — same fact flags location/haversine.py unreachable",
    ),
    "DomReadinessPort": (
        "WIRE-LATER",
        "handlers receive readiness as an untyped constructor param; no "
        "signature names the port",
    ),
    "EnvironmentCapabilitiesProvider": (
        "WIRE-LATER",
        "PolicyEnforcement is typed against the broader RegistryPort and calls "
        "get_environment_capabilities() through it instead",
    ),
    "ExtractionObserverPort": (
        "WIRE-LATER",
        "injected through duck-typed observer= constructor params across the "
        "discovery adapters; no signature names the port",
    ),
    "FeedbackRepositoryPort": (
        "WIRE-LATER",
        "PageFeedbackService references it only via a TYPE_CHECKING import and "
        "a string annotation — the pin's own rules exclude both",
    ),
    "HealthMonitor": (
        "WIRE-LATER",
        "the orchestrator holds monitors as Any and calls run/stop/is_healthy "
        "duck-typed",
    ),
    "IAccessibilityScanner": (
        "WIRE-LATER",
        "the whole AOM chain is unwired: aom_adapter.py is unreachable and the "
        "scanner is constructed nowhere",
    ),
    "ILogicSolver": (
        "PLANNED",
        "ASP reasoning is P3-5; ClingoFormSolver is constructed nowhere and "
        "asp_adapter.py is unreachable",
    ),
    "InterruptPolicy": (
        "WIRE-LATER",
        "ApplicationsWorkflow receives interrupt_policy untyped; only "
        "duck-typed should_pause calls exist",
    ),
    "PageActionPrimitives": (
        "WIRE-LATER",
        "handlers receive page_action untyped; the port is the three-verb "
        "contract docstring only",
    ),
    "PageAuditReporterPort": (
        "WIRE-LATER",
        "injected as untyped reporter= params; sibling of ExtractionObserverPort",
    ),
    "PageClassifierPort": (
        "WIRE-LATER",
        "GenericSERPStrategy constructs the concrete PageClassifier instead of "
        "receiving the port",
    ),
    "PageNavigationPort": (
        "WIRE-LATER",
        "ApplicationsWorkflow receives navigation untyped (page_action_tool); "
        "no annotation names the port",
    ),
    "ReasoningPort": (
        "WIRE-LATER",
        "ApplicationsWorkflow takes reasoning_port=None untyped; the "
        "composition root passes it but nothing annotates it",
    ),
    "ResolutionInterface": (
        "WIRE-LATER",
        "the orchestrator types captcha_resolver as Any | None",
    ),
    "SerpExtractionPort": (
        "WIRE-LATER",
        "GenericSERPStrategy takes fast_extractor untyped; docstring-only "
        "mentions otherwise",
    ),
    "SupportsRawDriver": (
        "WIRE-LATER",
        "callers probe get_raw_driver with getattr/hasattr instead of "
        "isinstance against the port (context_manager.py, aom_adapter.py)",
    ),
    "SupportsRawPage": (
        "WIRE-LATER",
        "same getattr-probe pattern as SupportsRawDriver",
    ),
    "TextGenerationPort": (
        "WIRE-LATER",
        "workflows take text_generation_port=None untyped; GPT4AllAdapter "
        "implements it structurally",
    ),
}

# Ceiling, not equality (R-E). A lower count is success.
MAX_EXEMPTIONS = 22


# ─────────────────────────────────────────────────────────────────────────────
# Scan machinery
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class _PortInfo:
    name: str
    rel_file: str
    required_members: frozenset


@dataclass
class _ModuleScan:
    rel_file: str
    ok: bool
    class_bases: dict[str, list[str]] = field(default_factory=dict)
    class_members: dict[str, set] = field(default_factory=dict)
    class_is_port: dict[str, bool] = field(default_factory=dict)
    name_uses: set = field(default_factory=set)


def _is_type_checking(test: ast.expr) -> bool:
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


def _dotted(expr: ast.expr) -> str:
    """Best-effort dotted name for a base/decorator expression."""
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        base = _dotted(expr.value)
        return f"{base}.{expr.attr}" if base else expr.attr
    if isinstance(expr, ast.Subscript):
        return _dotted(expr.value)
    if isinstance(expr, ast.Call):
        return _dotted(expr.func)
    return ""


def _is_port_class(node: ast.ClassDef) -> bool:
    for base in node.bases:
        if _dotted(base).split(".")[-1] in _PORT_BASE_NAMES:
            return True
    for kw in node.keywords:
        if kw.arg == "metaclass" and _dotted(kw.value).split(".")[-1] == "ABCMeta":
            return True
    return False


def _target_names(target: ast.expr) -> set:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, ast.Attribute):
        return {target.attr}
    if isinstance(target, (ast.Tuple, ast.List)):
        names: set = set()
        for elt in target.elts:
            names |= _target_names(elt)
        return names
    return set()


def _class_members(node: ast.ClassDef) -> set:
    """All member names a class defines: methods, class-level assignments,
    and self.<attr> assignments anywhere in its body (the latter is what lets
    a structural match see e.g. ``storage_dir`` on ProfileRepository)."""
    members: set = set()
    for sub in ast.walk(node):
        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
            members.add(sub.name)
        elif isinstance(sub, ast.Assign):
            for t in sub.targets:
                members |= _target_names(t)
        elif isinstance(sub, ast.AnnAssign):
            members |= _target_names(sub.target)
    return members


def _executable_name_uses(tree: ast.Module) -> set:
    """Names appearing in executable positions: any Name/Attribute load,
    excluding everything inside ``if TYPE_CHECKING:`` blocks. ImportFrom
    aliases are not Name nodes, so a bare import never counts (R-B-2)."""
    uses: set = set()

    class _Visitor(ast.NodeVisitor):
        def visit_If(self, node: ast.If) -> None:
            if _is_type_checking(node.test):
                return  # TYPE_CHECKING-only: does not count
            self.generic_visit(node)

        def visit_Name(self, node: ast.Name) -> None:
            if isinstance(node.ctx, ast.Load):
                uses.add(node.id)

        def visit_Attribute(self, node: ast.Attribute) -> None:
            if isinstance(node.ctx, ast.Load):
                uses.add(node.attr)
            self.generic_visit(node)

    _Visitor().visit(tree)
    return uses


def _iter_src_files() -> list:
    return [
        p
        for p in sorted(_SRC_DIR.rglob("*.py"))
        if "__pycache__" not in p.parts
    ]


def _scan_module(path: Path) -> _ModuleScan:
    rel = path.relative_to(_PKG_ROOT).as_posix()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return _ModuleScan(rel_file=rel, ok=False)

    scan = _ModuleScan(rel_file=rel, ok=True)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            scan.class_bases[node.name] = [_dotted(b) for b in node.bases]
            scan.class_members[node.name] = _class_members(node)
            scan.class_is_port[node.name] = _is_port_class(node)
    scan.name_uses = _executable_name_uses(tree)
    return scan


def _scan_all_modules() -> dict:
    return {p.as_posix(): _scan_module(p) for p in _iter_src_files()}


def _discover_ports() -> dict:
    """Find every Protocol/ABC class declared in domain/ports/ and record the
    members a concrete implementation must define."""
    ports: dict[str, _PortInfo] = {}
    for path in sorted(_PORTS_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        rel = path.relative_to(_PKG_ROOT).as_posix()
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and _is_port_class(node):
                members = frozenset(
                    m
                    for m in _class_members(node)
                    if not (m.startswith("__") and m.endswith("__"))
                )
                ports[node.name] = _PortInfo(
                    name=node.name, rel_file=rel, required_members=members
                )
    return ports


# ─────────────────────────────────────────────────────────────────────────────
# The pin
# ─────────────────────────────────────────────────────────────────────────────


def test_every_port_in_domain_ports_is_wired() -> None:
    ports = _discover_ports()
    scans = _scan_all_modules()

    assert ports, (
        f"No ports discovered under {_PORTS_DIR} — path resolution is broken, "
        "not the codebase."
    )

    flag_lines: dict[str, list[str]] = {}

    for port_name in sorted(ports):
        port = ports[port_name]

        # (rel_file, class_name, is_explicit_subclass)
        implementers: list[tuple[str, str, bool]] = []
        for scan in scans.values():
            if not scan.ok:
                continue
            for cls_name, bases in scan.class_bases.items():
                if cls_name == port_name or scan.class_is_port.get(cls_name, False):
                    continue
                if any(
                    b == port_name or b.endswith("." + port_name) for b in bases
                ):
                    implementers.append((scan.rel_file, cls_name, True))
                elif port.required_members and port.required_members.issubset(
                    scan.class_members.get(cls_name, set())
                ):
                    implementers.append((scan.rel_file, cls_name, False))

        # R-B-1: only EXPLICIT subclass implementers leave the consumer scan.
        # Structural implementers stay eligible to be counted as consumers.
        implementer_files = {rel for rel, _cls, explicit in implementers if explicit}

        consumers = sorted(
            scan.rel_file
            for scan in scans.values()
            if scan.ok
            and scan.rel_file != port.rel_file
            and scan.rel_file not in implementer_files
            and port_name in scan.name_uses
        )

        lines: list[str] = []
        if not implementers:
            members = ", ".join(sorted(port.required_members)) or "<none declared>"
            lines.append(
                f"PORT WITHOUT IMPLEMENTER — {port_name} ({port.rel_file})\n"
                f"  proof: no concrete class in src/ subclasses '{port_name}' or "
                f"defines all of {{{members}}}"
            )
        if not consumers:
            impl_desc = (
                ", ".join(f"{cls}@{rel}" for rel, cls, _e in implementers[:4])
                or "<none>"
            )
            lines.append(
                f"PORT WITHOUT CONSUMER — {port_name} ({port.rel_file})\n"
                f"  proof: implementer(s): {impl_desc}; the name '{port_name}' "
                f"appears in no executable position in any other file "
                f"(docstrings, string annotations, bare imports, and "
                f"TYPE_CHECKING-only imports do not count)"
            )
        if lines:
            flag_lines[port_name] = lines

    flagged = set(flag_lines)
    unexpected = sorted(flagged - set(KNOWN_UNWIRED_PORTS))
    stale = sorted(set(KNOWN_UNWIRED_PORTS) - flagged)

    failures: list[str] = []
    if unexpected:
        failures.append("UNEXEMPTED PORT WIRING FAILURES:")
        for name in unexpected:
            failures.extend(flag_lines[name])
    if stale:
        failures.append("")
        failures.append("STALE EXEMPTIONS (the port is wired now — remove these):")
        failures.extend(f"  {name}" for name in stale)
    if len(KNOWN_UNWIRED_PORTS) > MAX_EXEMPTIONS:
        failures.append("")
        failures.append(
            f"EXEMPTION CEILING EXCEEDED: {len(KNOWN_UNWIRED_PORTS)} exemptions "
            f"recorded but MAX_EXEMPTIONS={MAX_EXEMPTIONS}. A count BELOW the "
            "ceiling is success — remove entries as ports get wired; only a "
            "newly unwired port may push the count up, and only with a written reason."
        )

    assert not failures, (
        "\nPORT WIRING REPORT — AST scan of src/ "
        "(docstring-only mentions and bare imports never count)\n"
        + "=" * 72
        + "\n"
        + "\n".join(failures)
        + "\n"
    )
