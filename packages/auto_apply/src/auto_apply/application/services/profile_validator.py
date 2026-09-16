"""Pre-session profile completeness and authenticity check.

Called by SessionController.initialize_session() before seeding any tasks.
Returns a list of warnings and a list of blocking errors.

Two layers of checking:

    1. Completeness — are the fields a session needs actually present?
       (This is the original contract, unchanged.)

    2. Authenticity — does this profile still contain template placeholder
       data? The bundled templates in resources/templates/ carry a
       placeholder identity ("Bruce Dickinson", a fake reference, a fake
       work history, placeholder legal declarations). A profile assembled by
       copying the template passes every completeness check while asserting
       a stranger's identity and legally consequential declarations on the
       user's behalf. The contamination check below reads the template
       files themselves (never hardcoded placeholder values) and flags any
       identity-scoped field still identical to them.

Contamination collision rule (the line, stated):
    A leaf value counts as EVIDENCE only when it is BOTH
        * identity-scoped  — personal_info, links, references,
          work_experience, education, career_summary, legal_info.
          search_preferences, eeo_info, app_config and the rest are
          preference/config, not identity, and are never checked. A real
          user's "Software Engineer" job title must not trip the check.
        * distinctive      — not a bool, not None, not empty, not a member
          of any Literal enum vocabulary declared in
          domain/models/profile.py (computed from the models via get_args,
          not hardcoded), not a common geo string, and either email-shaped,
          phone-shaped, or at least _MIN_DISTINCTIVE_LEN characters long.
    Booleans, None, empty strings, numbers, and short enum-like values can
    NEVER trip the check on their own — a user who genuinely answers
    "authorized: true" or lives in "London" must not be accused of
    template contamination.

Contamination severity rule (stated, and load-bearing):
    * Exactly 1 match  -> WARNING, session proceeds. A real person can
      share ONE value with the template without having copied it — the
      template's education entry is "Queen Mary University of London", and
      a real graduate of that school typing their own education must not
      be blocked and accused of using template data.
    * 2 or more matches -> BLOCKING ERROR, session does not start. Someone
      who actually copied the template trips on email AND phone AND
      address AND career_summary AND links — several distinctive identity
      fields at once. Two or more matches is a coincidence that does not
      happen by accident at that rate; one match is a coincidence that
      legitimately does.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from importlib import resources as importlib_resources
from typing import TYPE_CHECKING, get_args

from auto_apply.domain.models.profile import (
    BrowserType,
    EmploymentType,
    Gender,
    NameSuffix,
    Race,
    SalaryFormat,
    UserProfile,
    VeteranStatus,
    VisaSponsorshipType,
    WorkplaceType,
)

if TYPE_CHECKING:
    from auto_apply.domain.models.capability_profile import ResolvedCapabilityProfile

logger = logging.getLogger(__name__)

# The name of the bundled template profile as it appears in PROFILES_DIR.
# Defined here — and only here — so consumers (the GUI bootstrap) never
# need to repeat the literal.
TEMPLATE_PROFILE_NAME: str = "default_profile"

# ---------------------------------------------------------------------------
# Template contamination machinery
# ---------------------------------------------------------------------------

# Identity-scoped top-level sections of UserProfile. Only these are checked.
# search_preferences / eeo_info / app_config / politeness are preference and
# config data, not identity — real users legitimately share those values.
_IDENTITY_SECTIONS: frozenset[str] = frozenset(
    {
        "personal_info",
        "links",
        "references",
        "work_experience",
        "education",
        "career_summary",
        "legal_info",
    }
)

# Geo values a real user shares with the template constantly.
_COMMON_GEO: frozenset[str] = frozenset({"United States", "United Kingdom"})

_EMAIL_RE = re.compile(r"\S+@\S+\.\S+")
_PHONE_RE = re.compile(r"[\d\s()+\-.]{7,}")
_MIN_DISTINCTIVE_LEN = 12

_LITERAL_TYPES = (
    NameSuffix,
    WorkplaceType,
    EmploymentType,
    Gender,
    Race,
    VeteranStatus,
    BrowserType,
    SalaryFormat,
    VisaSponsorshipType,
)

_ENUM_VOCAB: frozenset[str] = frozenset(
    str(option) for literal in _LITERAL_TYPES for option in get_args(literal)
)


def _walk_leaves(data, prefix: str = ""):
    """Yield (dotted_path, scalar_value) pairs for every scalar leaf.

    Lists are traversed WITHOUT adding an index to the path, but descent
    into each item's dict continues, so a value inside
    education[0].school is reported as "education.school" (the section plus
    the item's own keys), not as bare "education". The fully dotted leaf
    path is what the error and warning messages show to the user, because
    it points at the exact field to fix.
    """
    if isinstance(data, dict):
        for key, value in data.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            yield from _walk_leaves(value, child)
    elif isinstance(data, (list, tuple)):
        for item in data:
            yield from _walk_leaves(item, prefix)
    else:
        yield prefix, data


def _is_distinctive(value) -> bool:
    """The collision rule's 'distinctive' half, exactly as documented above."""
    if value is None or isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return False
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text:
        return False
    if text in _ENUM_VOCAB or text in _COMMON_GEO:
        return False
    if _EMAIL_RE.fullmatch(text) or _PHONE_RE.fullmatch(text):
        return True
    return len(text) >= _MIN_DISTINCTIVE_LEN


def _template_value_set() -> frozenset[str]:
    """Distinctive scalar values found in any bundled template file.

    Read fresh on every call: template files are small, and validate_profile
    runs once per session start, so a cache would only add global state.

    Two templates exist in the repository today (resources/templates/
    default_profile.json and template_profile.json) and they do not agree on
    content — one of them does not even parse as a UserProfile. Reading
    every *.json in the templates package covers both realities and any
    template added later, without this function needing to know their names.
    """
    values: set[str] = set()
    try:
        template_dir = importlib_resources.files("auto_apply.resources.templates")
    except Exception as exc:
        logger.warning(
            "profile_validator: cannot locate templates package (%s) — "
            "contamination check skipped",
            exc,
        )
        return frozenset()
    try:
        entries = list(template_dir.iterdir())
    except Exception as exc:
        logger.warning(
            "profile_validator: cannot read templates directory (%s) — "
            "contamination check skipped",
            exc,
        )
        return frozenset()
    for entry in entries:
        if not entry.name.endswith(".json"):
            continue
        try:
            document = json.loads(entry.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(
                "profile_validator: template file %s unreadable (%s) — skipped",
                entry.name,
                exc,
            )
            continue
        for _path, value in _walk_leaves(document):
            if _is_distinctive(value):
                values.add(value.strip())
    return frozenset(values)


def _contamination_evidence(profile: UserProfile) -> list[tuple[str, str]]:
    """Return (path, value) pairs for every identity field matching a template.

    The walk covers the WHOLE identity of the profile — not five fields —
    so a fake reference, a fake work-history description, and placeholder
    legal declarations are all caught without a list of field names that
    would go stale. Returns [] for a clean profile, and also returns []
    when the template files cannot be read: never block a user because the
    checker itself failed (that failure is logged upstream).
    """
    template_values = _template_value_set()
    if not template_values:
        return []

    evidence: list[tuple[str, str]] = []
    dumped = profile.model_dump(mode="python")
    for path, value in _walk_leaves(dumped):
        if not path or path.split(".")[0] not in _IDENTITY_SECTIONS:
            continue
        if isinstance(value, str) and value.strip() in template_values:
            evidence.append((path, value.strip()))
    return evidence


def find_template_contamination(profile: UserProfile) -> list[str]:
    """Return the identity-scoped profile paths still holding template data.

    Paths are fully dotted leaf paths (e.g. "education.school"), as produced
    by _walk_leaves. Returns [] for a clean profile.
    """
    return [path for path, _value in _contamination_evidence(profile)]


def _apply_contamination_check(
    result: "ProfileValidationResult", profile: UserProfile
) -> None:
    """Apply the contamination severity rule (see the module docstring).

    * 2+ matches  -> blocking errors, one per field. A template copy trips
      on several distinctive identity fields at once; that rate of
      coincidence does not happen by accident.
    * exactly 1   -> a warning naming the field and the value, session
      proceeds. A real person can share one value with the template — the
      canonical case is a genuine graduate of the template's school.
    """
    try:
        evidence = _contamination_evidence(profile)
    except Exception as exc:  # the checker must never block a session
        logger.warning(
            "profile_validator: contamination check failed (%s) — skipped", exc
        )
        return

    if len(evidence) >= 2:
        for path, value in evidence:
            result.add_error(
                f"{path} still contains template placeholder data "
                f"({value!r:.60}) — replace it with your own information "
                f"(Settings → About you)."
            )
    elif len(evidence) == 1:
        path, value = evidence[0]
        result.add_warning(
            f"{path} matches a value also found in AA's bundled template "
            f"({value!r:.60}) — if this is genuinely yours, you can ignore "
            f"this warning."
        )


# ---------------------------------------------------------------------------
# Existing contract — unchanged below this line except the one integration
# call inside validate_profile().
# ---------------------------------------------------------------------------


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
    """Check profile completeness and authenticity for the requested session mode.

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

    # ── Authenticity: is this profile still claiming template identity? ──
    # Runs in every mode, independently of the completeness checks above.
    _apply_contamination_check(result, profile)

    return result
