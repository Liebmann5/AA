"""Data model for the AdminPolicy — the top tier of AA's configuration hierarchy.

AdminPolicy represents settings that the device owner has locked in place.
Once applied, they override all user settings and runtime defaults for every
session on this device. Typical use cases: a shared lab computer where a
system administrator limits which browsers AA may use, or a researcher who
has fixed certain data collection settings for study consistency.

Security Model (Library Mode):
    AA delegates policy protection to the host Operating System's file system.
    IT administrators drop aa_policy.json next to the application root and set
    OS-level file permissions to read-only for standard users. AA respects the
    file contents; the OS protects the file from tampering.

    This is NOT cryptographic signing — it is OS-permission-gated enforcement,
    the same model used by Chrome/Firefox enterprise policies. The distinction
    matters: on FAT32/exFAT file systems (USB drives), file permissions are not
    enforced, so the policy file is user-editable. This is acceptable because
    USB-portable usage implies the user IS the administrator of their own tool.

Three-Tier Hierarchy Reminder:
    AdminPolicy  (this file — top)     <- overrides everything below
    UserSettings (profile.settings)    <- overrides RuntimeDefaults
    RuntimeDefaults (_RUNTIME_DEFAULTS in capabilities_registry.py)

Who Writes AdminPolicy:
    PolicyManager.create_template_policy() generates a template file.
    IT administrators edit and deploy it. AA never writes to this file at
    runtime — it is strictly read-only from AA's perspective.

Who Reads AdminPolicy:
    CapabilitiesRegistry.build() loads AdminPolicy once per session via
    PolicyManager.load_admin_policy() and merges it into effective_config.
    PolicyEnforcement then validates that the loaded UserProfile does not
    conflict with any admin constraint.

Example:
    >>> from core.models.policy import AdminPolicy
    >>>
    >>> policy = AdminPolicy(
    ...     allowed_browsers=["firefox"],
    ...     force_headless=True,
    ...     force_humanization=True,
    ...     force_respect_robots_txt=True,
    ...     min_action_delay_seconds=3.0,
    ... )
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AdminPolicy:
    """Immutable device-level configuration constraints.

    Every field is Optional. A None value means "no admin constraint on this
    setting" — the user setting or runtime default wins. A non-None value
    means the admin has explicitly locked that setting and the user cannot
    override it.

    Fields are grouped by concern:

    Browser Constraints:
        allowed_browsers: Whitelist of permitted browser names. BrowserCascade
            filters its candidate list against this. None = all permitted.
        blocked_tools: Tools explicitly prohibited (e.g., "undetected_chromedriver").

    Session Limits:
        max_applications_per_session: Hard cap on applications per run.

    Behavior Overrides:
        force_headless: If True, browser always runs headless.

    Safety & Compliance Overrides:
        force_humanization: If True, human behavior simulation cannot be
            disabled. Critical for institutional deployments where bot
            detection flags could create liability for the host organization.
        force_respect_robots_txt: If True, robots.txt compliance cannot be
            disabled. Protects institutional networks from policy violations.
        min_action_delay_seconds: Minimum delay between browser actions.
            Admin can enforce a floor to prevent aggressive automation.
            None means the user's preference or runtime default applies.

    Data Collection:
        disable_research_collection: If True, research data collection is
            permanently disabled on this device regardless of user consent.

    Arbitrary Overrides:
        config_overrides: Key-value pairs that override any key in the
            effective_config dict. Escape hatch for constraints not covered
            by the explicit fields above.

    Metadata:
        created_at: ISO 8601 datetime when policy was written.
        created_by: Who set the policy (e.g., "IT_Admin").
        policy_version: Semantic version for the policy format.
    """

    # -- Browser constraints ------------------------------------------------
    allowed_browsers: list[str] | None = None
    blocked_tools:    list[str] | None = None

    # -- Session limits -----------------------------------------------------
    max_applications_per_session: int | None = None

    # -- Behavior overrides -------------------------------------------------
    force_headless: bool | None = None

    # -- Safety & compliance overrides --------------------------------------
    force_humanization:        bool | None  = None
    force_respect_robots_txt:  bool | None  = None
    min_action_delay_seconds:  float | None = None

    # -- Data collection ----------------------------------------------------
    disable_research_collection: bool | None = None

    # -- Arbitrary config overrides -----------------------------------------
    config_overrides: dict[str, Any] = field(default_factory=dict)

    # -- Metadata -----------------------------------------------------------
    created_at:     str | None = None
    created_by:     str | None = None
    policy_version: str = "1.0.0"

    # =====================================================================
    # CONSTRUCTION
    # =====================================================================

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AdminPolicy:
        """Deserializes an AdminPolicy from a plain dict (e.g., loaded JSON).

        Unknown keys are silently ignored so old policy files remain valid
        after AA upgrades add new policy fields.

        Args:
            data: Dict representation of the policy, as stored on disk.

        Returns:
            A fully populated AdminPolicy instance.
        """
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)

    @classmethod
    def empty(cls) -> AdminPolicy:
        """Returns a no-constraint AdminPolicy.

        Equivalent to having no policy file at all — every field is None
        or its zero-value default. Used in tests and as a safe fallback.

        Returns:
            An AdminPolicy where no constraint is active.
        """
        return cls()

    # =====================================================================
    # SERIALIZATION
    # =====================================================================

    def to_dict(self) -> dict[str, Any]:
        """Serializes this policy to a JSON-serializable dict.

        Returns:
            A dict suitable for json.dumps(). None values are included so
            round-tripping through from_dict() is lossless.
        """
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        """Serializes this policy to a formatted JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    # =====================================================================
    # CONSTRAINT QUERY HELPERS
    # =====================================================================

    def is_browser_allowed(self, browser_name: str) -> bool:
        """Returns True if this browser is permitted by admin policy.

        If allowed_browsers is None, all browsers are permitted.
        """
        if self.allowed_browsers is None:
            return True
        return browser_name.lower() in [b.lower() for b in self.allowed_browsers]

    def is_tool_blocked(self, tool_name: str) -> bool:
        """Returns True if this tool is explicitly blocked by admin policy."""
        if self.blocked_tools is None:
            return False
        return tool_name.lower() in [t.lower() for t in self.blocked_tools]

    def get_session_limit(self, user_limit: int | None, default_limit: int) -> int:
        """Returns the effective max applications per session.

        The admin cap, if set, is the ceiling. The user preference may
        set a value below it but never above.
        """
        user_effective = user_limit if user_limit is not None else default_limit
        if self.max_applications_per_session is not None:
            return min(user_effective, self.max_applications_per_session)
        return user_effective

    def is_field_locked(self, field_name: str) -> bool:
        """Returns True if the given admin policy field has been set.

        Used by the SettingsEditor to determine which UI elements to disable.

        Args:
            field_name: The AdminPolicy attribute name to check.

        Returns:
            True if the field has a non-None value (admin has locked it).
        """
        value = getattr(self, field_name, None)
        if field_name == "config_overrides":
            return bool(value)
        return value is not None

    def has_any_constraint(self) -> bool:
        """Returns True if any admin constraint is active."""
        return any([
            self.allowed_browsers is not None,
            self.blocked_tools is not None,
            self.max_applications_per_session is not None,
            self.force_headless is not None,
            self.force_humanization is not None,
            self.force_respect_robots_txt is not None,
            self.min_action_delay_seconds is not None,
            self.disable_research_collection is not None,
            bool(self.config_overrides),
        ])

    def __repr__(self) -> str:
        active = [
            f for f in [
                "allowed_browsers" if self.allowed_browsers is not None else None,
                "blocked_tools" if self.blocked_tools is not None else None,
                "max_apps" if self.max_applications_per_session is not None else None,
                "force_headless" if self.force_headless else None,
                "force_humanization" if self.force_humanization else None,
                "force_robots_txt" if self.force_respect_robots_txt else None,
                f"min_delay={self.min_action_delay_seconds}s" if self.min_action_delay_seconds is not None else None,  # noqa: E501
                "no_research" if self.disable_research_collection else None,
                f"overrides({len(self.config_overrides)})" if self.config_overrides else None,  # noqa: E501
            ]
            if f is not None
        ]
        return f"AdminPolicy(active=[{', '.join(active) or 'none'}])"