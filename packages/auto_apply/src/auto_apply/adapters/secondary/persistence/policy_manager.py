"""Handles the loading of the enterprise Admin Policy file.

This module implements the "Library Mode" zero-intrusiveness security model.
Instead of prompting for OS-level admin credentials (which breaks portability,
causes antivirus flags, and fails on restricted networks), it strictly looks
for an aa_policy.json file in the application's root directory.

Security Delegation:
    AA delegates policy protection to the host Operating System's file system.
    IT administrators drop aa_policy.json next to the executable and set
    the OS file permissions to "Read-Only" for standard users. AA respects
    the file; the OS protects the file.

    This approach is identical to how Chrome and Firefox deploy enterprise
    policies — no elevation prompts, no admin APIs, just a file the app
    reads and the OS protects.
"""

import json
import logging
from pathlib import Path

from auto_apply.domain.config import APP_ROOT
from auto_apply.domain.models.policy import AdminPolicy

logger = logging.getLogger(__name__)


class PolicyManager:
    """Repository for reading device-level admin constraints.

    This class is the single mechanism for loading the Admin Policy file.
    No other code in AA reads aa_policy.json directly.

    The file is loaded once per session by CapabilitiesRegistry.build().
    """

    POLICY_FILE_NAME = "aa_policy.json"

    @staticmethod
    def load_admin_policy(search_dir: Path | None = None) -> AdminPolicy | None:
        """Locates and loads the admin policy file if it exists.

        Args:
            search_dir: Optional override for testing. Defaults to APP_ROOT.

        Returns:
            The parsed AdminPolicy, or None if no file exists.
        """
        target_dir = search_dir or APP_ROOT
        policy_path = target_dir / PolicyManager.POLICY_FILE_NAME

        if not policy_path.exists():
            logger.debug(
                "No admin policy file found at %s — running unrestricted",
                policy_path,
            )
            return None

        try:
            logger.info("Admin policy detected at %s — loading", policy_path)

            with open(policy_path, encoding="utf-8") as f:
                data = json.load(f)

            policy = AdminPolicy.from_dict(data)
            logger.info("Admin policy loaded | %s", policy)
            return policy

        except json.JSONDecodeError as exc:
            # Malformed file is a potential tamper indicator. Log critically
            # but fail safe by returning None (unrestricted mode).
            logger.critical(
                "Admin policy file is malformed (invalid JSON) | error=%s", exc
            )
            return None

        except Exception as exc:
            logger.error(
                "Unexpected error reading admin policy | error=%s", exc
            )
            return None

    @staticmethod
    def create_template_policy(target_dir: Path | None = None) -> Path:
        """Generates a template policy file for IT administrators.

        Creates aa_policy.json with all available constraint fields documented.
        Administrators edit this file to lock down the settings they need,
        then set it to read-only via OS file permissions.

        Args:
            target_dir: Where to write the template. Defaults to APP_ROOT.

        Returns:
            The Path to the generated template file.
        """
        target = (target_dir or APP_ROOT) / PolicyManager.POLICY_FILE_NAME

        template = {
            "_comment": (
                "AutoApply Admin Policy — Edit this file then set it to "
                "read-only via OS file permissions. Fields set to null are "
                "user-controlled. Non-null values override user settings."
            ),
            "policy_version": "1.0.0",
            "created_by": "IT_Admin",

            # Browser constraints
            "allowed_browsers": ["firefox", "chrome"],
            "blocked_tools": ["undetected_chromedriver"],

            # Session limits
            "max_applications_per_session": 50,

            # Behavior overrides
            "force_headless": True,

            # Safety & compliance — institutional devices should lock these
            "force_humanization": True,
            "force_respect_robots_txt": True,
            "min_action_delay_seconds": 2.0,

            # Data collection
            "disable_research_collection": True,

            # Arbitrary config overrides (any key from _RUNTIME_DEFAULTS)
            "config_overrides": {
                "log_retention_days": 7,
            },
        }

        with open(target, "w", encoding="utf-8") as f:
            json.dump(template, f, indent=4)

        logger.info("Generated template admin policy at %s", target)
        return target
