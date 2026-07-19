"""Startup reconciliation between AdminPolicy and UserSettings.

PolicyEnforcement runs exactly once during CapabilitiesRegistry.build(),
after all three config tiers have been loaded and merged. Its job is to
verify that the resolved effective configuration does not violate any
AdminPolicy constraint, and to correct or log any conflicts it finds.

Why This Is a Separate Class:
    The three-tier merge in CapabilitiesRegistry._merge_config() produces
    the effective config by applying layers in order. That is mechanical.
    PolicyEnforcement is the semantic validation pass — it asks "does this
    result make sense and is it compliant?" Those are different concerns
    and belong in different places.

What PolicyEnforcement Does:
    1. Validates that the active browser preference is admin-allowed.
       If not, replaces it with the first allowed browser and logs a warning.
    2. Validates that no blocked tool is marked as available.
       Removes blocked tools from the effective available list.
    3. Validates the session limit does not exceed the admin cap.
       Silently clamps it downward if it does.
    4. Enforces headless mode if the admin requires it.
    5. Enforces research collection prohibition if the admin requires it.
    6. Logs a concise summary of every constraint that was applied.

What PolicyEnforcement Does NOT Do:
    - It does not raise exceptions on policy violations. A violation is a
      configuration conflict, not a programming error. The correct response
      is correction + logging, not crashing the session.
    - It does not write to disk. It operates on the in-memory effective_config
      dict inside the registry. The user's saved settings are left untouched.
    - It does not prompt the user. Enforcement is silent and automatic.
      The session report and admin audit log record what was changed.

Example:
    >>> registry = CapabilitiesRegistry.build()
    >>> # PolicyEnforcement is called automatically inside build().
    >>> # Direct use:
    >>> from auto_apply.adapters.secondary.security.policy_enforcement import PolicyEnforcement
    >>> PolicyEnforcement(registry).enforce()
"""  # noqa: E501

import logging
from typing import TYPE_CHECKING

from auto_apply.domain.models.policy import AdminPolicy

if TYPE_CHECKING:
    from auto_apply.infrastructure.composition_root import CapabilitiesRegistry

logger = logging.getLogger(__name__)


class PolicyEnforcement:
    """Reconciles effective configuration against AdminPolicy constraints.

    Constructed with a fully built CapabilitiesRegistry and mutates its
    effective_config in-place to satisfy all active admin constraints.

    Args:
        registry: The fully initialized CapabilitiesRegistry. Must have
            completed the three-tier merge before PolicyEnforcement runs.

    Example:
        >>> enforcement = PolicyEnforcement(registry)
        >>> enforcement.enforce()
    """

    def __init__(self, registry: "CapabilitiesRegistry") -> None:
        """Initializes policy enforcement with the active registry.

        Args:
            registry: The CapabilitiesRegistry to validate and correct.
        """
        self._registry = registry
        self._policy: AdminPolicy = registry.get_admin_policy() or AdminPolicy.empty()
        self._config: dict = registry._effective_config  # Direct reference for mutation.  # noqa: E501
        self._violations: list[str] = []

    # =========================================================================
    # ENTRY POINT
    # =========================================================================

    def enforce(self) -> None:
        """Runs all policy enforcement checks in sequence.

        Called once by CapabilitiesRegistry.build() after three-tier merge.
        Applies corrections in-place and logs a summary when done.

        If no AdminPolicy is active, returns immediately — no-op.
        """
        if not self._policy.has_any_constraint():
            logger.debug("PolicyEnforcement: no active admin policy constraints")
            return

        logger.info("PolicyEnforcement: applying admin policy constraints...")

        self._enforce_browser_preference()
        self._enforce_blocked_tools()
        self._enforce_session_limit()
        self._enforce_headless()
        self._enforce_research_prohibition()

        self._log_summary()

    # =========================================================================
    # INDIVIDUAL ENFORCEMENT CHECKS
    # =========================================================================

    def _enforce_browser_preference(self) -> None:
        """Ensures the preferred browser order only includes allowed browsers.

        If the user's top preference is blocked by admin policy, removes
        blocked browsers from the preference list entirely. BrowserCascade
        will then naturally skip to the first allowed option.

        If NO installed browser is allowed, logs a critical error — the
        session will fail when BrowserCascade finds an empty candidate list,
        which is the correct and visible failure mode.
        """
        if self._policy.allowed_browsers is None:
            return  # No browser restriction active.

        allowed = [b.lower() for b in self._policy.allowed_browsers]
        current_order: list[str] = self._config.get("preferred_browser_order", [])

        current_order[0] if current_order else "none"

        # Filter preference list to only admin-allowed browsers.
        filtered = [b for b in current_order if b.lower() in allowed]

        if filtered != current_order:
            removed = [b for b in current_order if b not in filtered]
            self._config["preferred_browser_order"] = filtered
            msg = (
                f"Browser preference modified by admin policy: "
                f"removed {removed}, allowed={allowed}, "
                f"new first choice='{filtered[0] if filtered else 'NONE'}'"
            )
            self._violations.append(msg)
            logger.warning("PolicyEnforcement: %s", msg)

        if not filtered:
            logger.critical(
                "PolicyEnforcement: admin policy allows %s but NONE of these "
                "are installed. BrowserCascade will fail at session start.",
                allowed,
            )

    def _enforce_blocked_tools(self) -> None:
        """Removes blocked tools from the available tools list.

        CapabilitiesRegistry.is_tool_available() already checks
        AdminPolicy.is_tool_blocked() directly, so this enforcement step
        is belt-and-suspenders — it also purges them from the capabilities
        snapshot so nothing can accidentally bypass the registry query.
        """
        if not self._policy.blocked_tools:
            return

        blocked = [t.lower() for t in self._policy.blocked_tools]
        capabilities = self._registry._capabilities
        original = list(capabilities.available_tools)

        # Remove blocked tools from the detected capabilities snapshot.
        capabilities.available_tools = [
            t for t in capabilities.available_tools
            if t.lower() not in blocked
        ]

        removed = [t for t in original if t not in capabilities.available_tools]
        if removed:
            msg = f"Tools blocked by admin policy: {removed}"
            self._violations.append(msg)
            logger.warning("PolicyEnforcement: %s", msg)

    def _enforce_session_limit(self) -> None:
        """Clamps max_applications_per_session to the admin cap if exceeded.

        The three-tier merge may have set a user preference above the admin
        maximum. This corrects it downward silently.
        """
        admin_cap = self._policy.max_applications_per_session
        if admin_cap is None:
            return

        current = self._config.get("max_applications_per_session", admin_cap)

        if current > admin_cap:
            self._config["max_applications_per_session"] = admin_cap
            msg = (
                f"max_applications_per_session clamped: "
                f"{current} → {admin_cap} (admin cap)"
            )
            self._violations.append(msg)
            logger.warning("PolicyEnforcement: %s", msg)

    def _enforce_headless(self) -> None:
        """Forces headless mode if the admin policy requires it.

        If force_headless is True, the user's headless preference is
        overridden. The headless flag is applied to the effective_config
        and to the RuntimeProfile if it has already been built.
        """
        if not self._policy.force_headless:
            return

        if not self._config.get("headless_mode", False):
            self._config["headless_mode"] = True
            msg = "headless_mode forced True by admin policy"
            self._violations.append(msg)
            logger.warning("PolicyEnforcement: %s", msg)

    def _enforce_research_prohibition(self) -> None:
        """Disables research collection if the admin policy prohibits it.

        This overrides the user's opt-in consent. The user is not shown
        an error — research is simply silently disabled. The session report
        notes that research was admin-prohibited.

        This is the correct behavior for enterprise environments where
        data collection policies apply regardless of individual preference.
        """
        if not self._policy.disable_research_collection:
            return

        if self._config.get("enable_research_collection", False):
            self._config["enable_research_collection"] = False
            msg = "research collection disabled by admin policy (overrides user opt-in)"
            self._violations.append(msg)
            logger.warning("PolicyEnforcement: %s", msg)

    # =========================================================================
    # SUMMARY LOGGING
    # =========================================================================

    def _log_summary(self) -> None:
        """Logs a concise enforcement summary for the session audit log.

        An empty violations list means the policy was already satisfied —
        no corrections were needed.
        """
        if not self._violations:
            logger.info(
                "PolicyEnforcement: all admin constraints satisfied — "
                "no corrections needed"
            )
            return

        logger.info(
            "PolicyEnforcement: applied %d correction(s):",
            len(self._violations),
        )
        for i, msg in enumerate(self._violations, 1):
            logger.info("  [%d] %s", i, msg)

    # =========================================================================
    # AUDIT EXPORT (for session report)
    # =========================================================================

    def get_violations(self) -> list[str]:
        """Returns the list of corrections applied during enforcement.

        Each entry is a human-readable description of a conflict that was
        found and corrected. An empty list means nothing was changed.

        Returns:
            List of correction description strings.
        """
        return list(self._violations)