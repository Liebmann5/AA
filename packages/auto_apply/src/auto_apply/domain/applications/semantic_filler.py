"""Provides logic to select the correct user data for a specific field type.

This module connects the ``FieldClassifier`` results to the ``UserProfile`` data.
Simple field-to-profile mappings are handled directly; complex decisions
(work authorisation, open-ended questions) return safe defaults until
reasoning ports are injected.
"""

import logging
from typing import Any

from auto_apply.domain.applications.field_classifier import FieldType
from auto_apply.domain.models.profile import UserProfile

logger = logging.getLogger(__name__)

# Maps FieldTypes that correspond directly to a single profile value.
# Adding a new simple mapping requires one line here, not a new branch.
_DIRECT_MAPPINGS = {
    FieldType.FIRST_NAME: lambda p: p.personal_info.first_name,
    FieldType.LAST_NAME: lambda p: p.personal_info.last_name,
    FieldType.EMAIL: lambda p: p.personal_info.email,
    FieldType.PHONE: lambda p: p.personal_info.phone_number,
    FieldType.LINKEDIN: lambda p: str(p.links.linkedin_url),
    FieldType.GITHUB: lambda p: str(p.links.github_url),
    FieldType.PORTFOLIO: lambda p: str(p.links.portfolio_url),
    FieldType.RESUME: lambda p: str(p.personal_info.resume_path),
}


class SemanticFiller:
    """Determines the value to input into a form field."""

    def __init__(self, profile: UserProfile) -> None:
        self.profile = profile

    def get_value_for_field(
        self, field_type: FieldType, label_text: str = ""
    ) -> Any:
        """Returns the data value to enter for a classified field.

        Args:
            field_type: The classified type of the field.
            label_text: The visible question/label text. Used as context for
                UNKNOWN fields.

        Returns:
            The string, boolean, or file path to enter/select, or ``None`` if
            no mapping exists.
        """
        getter = _DIRECT_MAPPINGS.get(field_type)
        if getter is not None:
            return getter(self.profile)

        if field_type == FieldType.AUTHORIZATION:
            # Eligibility logic requires a ReasoningPort injected by
            # infrastructure. "Yes" is the safe default in the interim.
            return "Yes"

        if field_type == FieldType.UNKNOWN and label_text:
            logger.info(
                "No direct mapping for unknown field; returning career summary. "
                "label=%r",
                label_text,
            )
            return self.profile.career_summary

        return None
