"""Pre-session profile completeness check.

Called by SessionController.initialize_session() before seeding any tasks.
Returns a list of warnings and a list of blocking errors.

Warnings can be ignored. Blocking errors halt the session with a helpful
message (not a cryptic exception deep in the application workflow).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from auto_apply.domain.models.capability_profile import ResolvedCapabilityProfile
    from auto_apply.domain.models.profile import UserProfile


@dataclass
class ProfileValidationResult:
    """Result of profile completeness check.

    Attributes:
        is_valid: False if any blocking errors were found. The session
            should not start when this is False.
        errors: Human-readable messages describing problems that prevent
            the session from functioning correctly (e.g. missing email,
            empty career summary).
        warnings: Advisory messages about optional gaps that the session
            can tolerate (e.g. missing phone number, no work experience).
        missing_for_gpt4all: Suggestions for improving AI-generated
            custom question answers. Never blocking — purely informational.
    """

    is_valid: bool = True
    errors: list[str] = field(default_factory=list)          # blocking
    warnings: list[str] = field(default_factory=list)        # advisory
    missing_for_gpt4all: list[str] = field(default_factory=list)  # nice-to-have

    def add_error(self, msg: str) -> None:
        """Record a blocking error and mark the result as invalid."""
        self.errors.append(msg)
        self.is_valid = False

    def add_warning(self, msg: str) -> None:
        """Record an advisory warning (does not block the session)."""
        self.warnings.append(msg)

    def format_for_cli(self) -> str:
        """Render all issues as a human-readable block for terminal display.

        Returns:
            A multi-line string suitable for printing directly to stdout.
            Returns a single "profile is complete" line when no issues exist.
        """
        lines: list[str] = []
        if self.errors:
            lines.append("  \u2717 BLOCKING ISSUES (session cannot start):")
            for e in self.errors:
                lines.append(f"    \u2022 {e}")
        if self.warnings:
            lines.append("  \u26a0 ADVISORY (session will start but may have gaps):")
            for w in self.warnings:
                lines.append(f"    \u2022 {w}")
        if self.missing_for_gpt4all:
            lines.append("  \U0001f4a1 TIP — for better custom question answers, also add:")
            for m in self.missing_for_gpt4all:
                lines.append(f"    \u2022 {m}")
        return "\n".join(lines) if lines else "  \u2713 Profile is complete"


def validate_profile(
    profile: "UserProfile",
    capability: "ResolvedCapabilityProfile | None" = None,
    mode: str = "discovery",
) -> ProfileValidationResult:
    """Check profile completeness for the requested session mode.

    Args:
        profile: The loaded UserProfile to validate.
        capability: Optional capability profile. When provided and
            ``capability.has_browser`` is True, stricter checks for
            application-mode fields (resume path, phone) are applied.
        mode: Session mode — ``"discovery"`` | ``"direct"`` | ``"vet"``
            | ``"company"``.  ``"direct"`` and ``"apply"`` trigger the
            same strict checks as a live-browser capability profile.

    Returns:
        A :class:`ProfileValidationResult` with errors, warnings, and
        GPT4All improvement suggestions.
    """
    result = ProfileValidationResult()
    info = profile.personal_info

    # ── Required for ALL modes ───────────────────────────────────────────
    if not getattr(info, "first_name", "").strip():
        result.add_error(
            "personal_info.first_name is empty — required for all form fills"
        )
    if not getattr(info, "last_name", "").strip():
        result.add_error(
            "personal_info.last_name is empty — required for all form fills"
        )
    if not getattr(info, "email", "").strip():
        result.add_error(
            "personal_info.email is empty — required for all form fills"
        )

    career_summary = getattr(profile, "career_summary", "") or ""
    if not career_summary.strip():
        result.add_error(
            "career_summary is empty — required for AI-powered custom question "
            "answering. Add 3–5 sentences about your background."
        )
    elif len(career_summary) < 50:
        result.add_warning(
            "career_summary is very short (< 50 chars). "
            "Longer summaries produce better GPT4All answers."
        )

    prefs = getattr(profile, "search_preferences", None)
    if prefs is None:
        result.add_error(
            "search_preferences is missing — no jobs to search for"
        )
    else:
        desired = getattr(prefs, "desired_job_titles", None) or []
        if not desired:
            result.add_error(
                "search_preferences.desired_job_titles is empty — "
                "add at least one job title to search for"
            )

    # ── Required for APPLY mode (direct apply or after vetting) ─────────
    is_apply_mode = mode in ("direct", "apply") or (
        capability is not None and capability.has_browser
    )

    if is_apply_mode:
        resume_path = getattr(info, "resume_path", None)
        if not resume_path:
            result.add_warning(
                "personal_info.resume_path is not set — file upload fields "
                "will be skipped. Set this to your resume PDF for complete "
                "applications."
            )
        else:
            # Existence check goes through the portable accessor, not the raw
            # field: get_resolved_resume_path() re-roots relative paths against
            # PROFILES_DIR at runtime and returns None when the file is missing.
            resolved = info.get_resolved_resume_path()
            if resolved is None:
                result.add_error(
                    f"personal_info.resume_path points to a file that does not "
                    f"exist: {resume_path}. Fix the path or remove it."
                )

        phone = getattr(info, "phone_number", "") or ""
        if not phone.strip():
            result.add_warning(
                "personal_info.phone_number is empty — phone fields will be blank"
            )

        work_exp = getattr(profile, "work_experience", None) or []
        if not work_exp:
            result.missing_for_gpt4all.append(
                "work_experience — at least one entry greatly improves "
                "custom answer quality"
            )

    # ── Advisory for ALL modes ───────────────────────────────────────────
    work_exp = getattr(profile, "work_experience", None) or []
    if not work_exp:
        result.add_warning(
            "work_experience is empty — vetting filters that check experience "
            "may behave oddly"
        )

    return result
