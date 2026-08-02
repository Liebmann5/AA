"""Automation candidates for browser cascade."""

from dataclasses import dataclass
from typing import List, Optional, Dict


@dataclass(frozen=True)
class AutomationCandidate:
    framework: str
    browser_type: str
    source: str  # "bundled", "os", or "none"


CANDIDATE_PRIORITY: List[AutomationCandidate] = [
    AutomationCandidate("playwright", "chromium", "bundled"),
    AutomationCandidate("playwright", "firefox", "bundled"),
    AutomationCandidate("playwright", "webkit", "bundled"),
    AutomationCandidate("selenium", "chrome", "os"),
    AutomationCandidate("selenium", "firefox", "os"),
    AutomationCandidate("selenium", "edge", "os"),
    AutomationCandidate("selenium", "safari", "os"),
    AutomationCandidate("static", "none", "none"),
]


# Default framework preference. Overridable per-machine via the ``framework_order``
# config key (runtime_defaults.yaml) or an admin policy override, so the cascade's
# framework tier is parametric rather than hardcoded. Frameworks are agnostic and
# swappable: adding one to CANDIDATE_PRIORITY and naming it here (or in config) slots
# it in with no change to the ordering logic.
DEFAULT_FRAMEWORK_ORDER: List[str] = ["playwright", "selenium", "camoufox"]


def _order_frameworks(
    framework_order: Optional[List[str]], present: List[str]
) -> List[str]:
    """Resolve the framework emission order: configured order first (minus
    ``static``, which is always the final fallback), then any present framework
    not named in the config (safety), preserving CANDIDATE_PRIORITY order for the
    remainder. Deterministic for a given input."""
    order = framework_order or DEFAULT_FRAMEWORK_ORDER
    resolved = [f for f in order if f != "static" and f in present]
    resolved += [f for f in present if f not in resolved]
    return resolved


def build_filtered_candidates(
    available_frameworks: List[str],
    os_browsers: List[str],
    framework_native_map: Dict[str, List[str]],
    admin_policy: Optional[object],
    framework_order: Optional[List[str]] = None,
) -> List[AutomationCandidate]:
    """Filter the candidate priority list against actual environment capabilities.

    Args:
        available_frameworks: Framework names that are installed/available.
        os_browsers: OS-installed browsers that are allowed by policy.
        framework_native_map: Mapping from framework to its bundled browser IDs.
        admin_policy: Optional admin policy object with an ``allowed_browsers``
            attribute (list of allowed browser names).

    Returns:
        Filtered list in priority order, removing candidates whose framework
        or browser is unavailable or blocked.
    """
    def _is_browser_allowed(browser: str) -> bool:
        if admin_policy and hasattr(admin_policy, 'allowed_browsers') and admin_policy.allowed_browsers:
            return browser in admin_policy.allowed_browsers
        return True

    # Group the (framework, browser, source) template by framework so the framework
    # tier can be reordered by config without disturbing the browser order within a
    # framework. static is handled last as the guaranteed fallback.
    non_static = [c for c in CANDIDATE_PRIORITY if c.framework != "static"]
    static_candidates = [c for c in CANDIDATE_PRIORITY if c.framework == "static"]
    seen_fw: set = set()
    frameworks_present = [
        c.framework for c in non_static
        if not (c.framework in seen_fw or seen_fw.add(c.framework))
    ]

    result = []
    for framework in _order_frameworks(framework_order, frameworks_present):
        if framework not in available_frameworks:
            continue
        for candidate in [c for c in non_static if c.framework == framework]:
            if candidate.source == "bundled":
                native_browsers = framework_native_map.get(candidate.framework, [])
                if candidate.browser_type not in native_browsers:
                    continue
                if not _is_browser_allowed(candidate.browser_type):
                    continue
            elif candidate.source == "os":
                if candidate.browser_type not in os_browsers:
                    continue
                # os_browsers already filtered by admin policy; double-check safety
                if not _is_browser_allowed(candidate.browser_type):
                    continue
            else:
                continue  # unknown source, skip

            result.append(candidate)

    result.extend(static_candidates)  # guaranteed final fallback
    return result