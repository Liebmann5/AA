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


def build_filtered_candidates(
    available_frameworks: List[str],
    os_browsers: List[str],
    framework_native_map: Dict[str, List[str]],
    admin_policy: Optional[object],
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

    result = []
    for candidate in CANDIDATE_PRIORITY:
        if candidate.framework == "static":
            # static fallback is always viable
            result.append(candidate)
            continue

        # Framework must be available
        if candidate.framework not in available_frameworks:
            continue

        if candidate.source == "bundled":
            native_browsers = framework_native_map.get(candidate.framework, [])
            if candidate.browser_type not in native_browsers:
                continue
            if not _is_browser_allowed(candidate.browser_type):
                continue
        elif candidate.source == "os":
            if candidate.browser_type not in os_browsers:
                continue
            # os_browsers already filtered by admin policy; double-check for safety
            if not _is_browser_allowed(candidate.browser_type):
                continue
        else:
            continue  # unknown source, skip

        result.append(candidate)
    return result