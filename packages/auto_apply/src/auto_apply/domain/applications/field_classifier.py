"""Provides intelligence for identifying the purpose of form fields.

This module acts as the 'eyes' of the Application Engine. It analyzes a DOM
element (Input, Select, Textarea) and determines its semantic purpose (e.g.,
'first_name', 'resume_upload', 'education_start_date') using a combination
of label text analysis, attribute inspection, and context.
"""

import logging
from enum import Enum, auto

from auto_apply.domain.ports.browser_port import ElementInterface

logger = logging.getLogger(__name__)


class FieldType(Enum):
    UNKNOWN = auto()
    FIRST_NAME = auto()
    LAST_NAME = auto()
    EMAIL = auto()
    PHONE = auto()
    RESUME = auto()
    COVER_LETTER = auto()
    LINKEDIN = auto()
    GITHUB = auto()
    PORTFOLIO = auto()
    ADDRESS = auto()
    CITY = auto()
    STATE = auto()
    ZIP = auto()
    COUNTRY = auto()
    EDUCATION = auto()
    EXPERIENCE = auto()
    AUTHORIZATION = auto()  # "Are you authorized to work?"
    RACE = auto()
    GENDER = auto()
    VETERAN = auto()
    DISABILITY = auto()


class FieldClassifier:
    """Classifies form elements into known semantic types."""

    _DEFAULT_SYNONYMS: dict[str, list[str]] = {
        "first_name": ["first name", "given name", "forename"],
        "last_name": ["last name", "surname", "family name"],
        "email": ["email", "email address"],
        "phone": ["phone", "phone number", "mobile number", "cellphone"],
        "resume": ["resume", "cv", "curriculum vitae", "upload resume"],
        "cover_letter": ["cover letter", "cover"],
        "linkedin": ["linkedin", "linkedin profile", "linkedin url"],
        "github": ["github"],
        "portfolio": ["portfolio", "website", "personal site"],
        "address": ["address", "street", "street address"],
        "city": ["city", "town"],
        "state": ["state", "province"],
        "zip": ["zip", "zip code", "postal code"],
        "country": ["country"],
        "education": ["education", "school", "university", "college"],
        "experience": ["experience", "work experience", "employment"],
        "authorization": [
            "authorized",
            "work authorization",
            "legal to work",
        ],
        "race": ["race", "ethnicity"],
        "gender": ["gender", "sex"],
        "veteran": ["veteran"],
        "disability": ["disability"],
    }

    def __init__(self, synonyms: dict[str, list[str]] | None = None) -> None:
        """Initialise with an optional synonyms dictionary.

        Args:
            synonyms: A mapping of field keys (e.g. 'first_name') to lists of
                matching keywords. If None, a built‑in default mapping is used.
        """
        self.synonyms = synonyms if synonyms is not None else self._DEFAULT_SYNONYMS

    def classify(self, element: ElementInterface) -> FieldType:
        """Determines the semantic type of a form element.

        Strategy:
        1. Check the associated <label> text (strongest signal).
        2. Check 'name', 'id', 'placeholder', or 'aria-label' attributes.
        3. Check surrounding text context.

        Args:
            element (ElementInterface): The form field to analyze.

        Returns:
            FieldType: The detected type, or FieldType.UNKNOWN.
        """
        signals = self._extract_signals(element)

        for field_key, keywords in self.synonyms.items():
            field_type = self._map_key_to_enum(field_key)
            if field_type == FieldType.UNKNOWN:
                continue

            for signal in signals:
                if any(k == signal for k in keywords):
                    return field_type
                if any(k in signal for k in keywords):
                    return field_type

        return FieldType.UNKNOWN

    def _extract_signals(self, element: ElementInterface) -> list[str]:
        """Extracts text clues from an element's attributes."""
        signals = []

        attrs = ("name", "id", "placeholder", "aria-label", "data-automation-id")
        for attr in attrs:
            val = element.get_attribute(attr)
            if val:
                signals.append(val.lower().replace("_", " ").strip())

        # Label check: in a real DOM, find the <label for="id">. For now we
        # assume the element or wrapper carries accessible label text, or that
        # the driver exposes an accessible_name attribute.

        # Fallback parent-text scan would go here (expensive — deferred).

        return signals

    def _map_key_to_enum(self, key: str) -> FieldType:
        """Maps string keys from settings to FieldType enum."""
        try:
            return FieldType[key.upper()]
        except KeyError:
            return FieldType.UNKNOWN