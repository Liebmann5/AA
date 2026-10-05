"""Guard pins for the apply route (item 12B, deliverables 4 and 8).

GUARDS, not teeth — they pass on the tree that introduced them and fail on
regressions:

  * the ContextManager wiring going missing again (it was built and never
    passed for months — this codebase's signature defect);
  * a site-specific host or selector sneaking into the route, which must
    stay host-agnostic by design (R-1).
"""

from __future__ import annotations

from pathlib import Path

_PKG_ROOT = Path(__file__).resolve().parents[2]
_SRC = _PKG_ROOT / "src" / "auto_apply"

_COMPOSITION_ROOT = _SRC / "infrastructure" / "composition_root.py"
_ROUTE_FILES = [
    _SRC / "application" / "workflows" / "applications_workflow.py",
    _SRC / "application" / "workflows" / "vetting_workflow.py",
    _SRC / "domain" / "services" / "apply_target.py",
]

#: Hosts from the measured runs that must never appear in the route code.
#: The route works on every site BECAUSE it knows none of them.
_FORBIDDEN_HOSTS = (
    "linkedin",
    "careerbuilder",
    "glassdoor",
    "ziprecruiter",
    "jobrapido",
    "sourcingsquare",
    "indeed",
)


def test_context_manager_is_constructed_and_passed() -> None:
    src = _COMPOSITION_ROOT.read_text(encoding="utf-8")
    assert "ContextManager(" in src, (
        "build_orchestrator no longer constructs a ContextManager — an "
        "apply control that opens a new tab will strand AA on the posting."
    )
    assert "context_manager=_context_manager" in src, (
        "build_orchestrator constructs ContextManager but does not pass it "
        "to ApplicationsWorkflow — the built-but-never-connected defect "
        "this pin exists to catch."
    )


def test_no_site_specific_hosts_in_the_apply_route() -> None:
    offenders: list[str] = []
    for path in _ROUTE_FILES:
        text = path.read_text(encoding="utf-8").lower()
        for host in _FORBIDDEN_HOSTS:
            if host in text:
                offenders.append(f"{path.name}: {host}")
    assert not offenders, (
        "Site-specific hosts in the apply route — the route must stay "
        "host-agnostic (R-1). Found: " + ", ".join(offenders)
    )
