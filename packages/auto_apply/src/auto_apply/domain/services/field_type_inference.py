"""Deterministic field type classification using attribute and text heuristics.

This module provides a scoring‑based classifier that maps a DOM input node
(and its associated label text) to a canonical `FieldType` enum. No machine
learning is used; all rules are explicit and auditable.
"""

from __future__ import annotations

from collections import defaultdict

from auto_apply.domain.models.math_dom import DOMNode
from auto_apply.domain.models.math_webpage import FieldType


class FieldTypeClassifier:
    """Classify form fields into semantic types based on heuristics.

    This class is stateless and can be instantiated once and reused.
    """

    # Weights for different evidence sources
    WEIGHT_TYPE_ATTR = 20       # input type attribute (e.g., email, tel)
    WEIGHT_AUTOCOMPLETE = 15    # autocomplete attribute
    WEIGHT_NAME_ID = 12         # name or id attribute
    WEIGHT_LABEL = 10           # label text or placeholder
    WEIGHT_ARIA = 8             # aria-label
    WEIGHT_CONTEXT = 5          # parent/ancestor hints

    def __init__(self) -> None:
        """Initialize with keyword mappings."""
        # Keyword sets for each field type
        self.keywords: dict[FieldType, set[str]] = self._build_keyword_sets()

    def classify(self, input_node: DOMNode, label_text: str = "") -> FieldType:
        """Return the most likely semantic type for the given input node.

        Args:
            input_node: The DOM input element.
            label_text: Pre‑extracted label text (may be empty).

        Returns:
            The inferred FieldType. If no strong evidence, returns FieldType.TEXT
            or FieldType.UNKNOWN.
        """
        scores: dict[FieldType, float] = defaultdict(float)

        # 1. Type attribute
        type_attr = input_node.attributes.get("type", "").lower()
        self._score_type_attribute(type_attr, scores)

        # 2. Autocomplete
        autocomplete = input_node.attributes.get("autocomplete", "").lower()
        self._score_text(autocomplete, self.WEIGHT_AUTOCOMPLETE, scores)

        # 3. Name and ID
        name = input_node.attributes.get("name", "").lower()
        id_attr = input_node.attributes.get("id", "").lower()
        self._score_text(name, self.WEIGHT_NAME_ID, scores)
        self._score_text(id_attr, self.WEIGHT_NAME_ID, scores)

        # 4. Placeholder
        placeholder = input_node.attributes.get("placeholder", "").lower()
        self._score_text(placeholder, self.WEIGHT_LABEL, scores)

        # 5. ARIA label
        aria_label = input_node.attributes.get("aria-label", "").lower()
        self._score_text(aria_label, self.WEIGHT_ARIA, scores)

        # 6. Provided label text
        self._score_text(label_text.lower(), self.WEIGHT_LABEL, scores)

        # 7. Tag‑specific handling
        if input_node.tag == "select":
            scores[FieldType.SELECT] += 5
        elif input_node.tag == "textarea":
            scores[FieldType.TEXT] += 5

        # 8. File input specifics
        if type_attr == "file":
            if self._contains_any(label_text, ["resume", "cv", "curriculum"]):
                scores[FieldType.RESUME_UPLOAD] += 30
            elif self._contains_any(label_text, ["cover", "letter"]):
                scores[FieldType.COVER_LETTER_UPLOAD] += 30

        # Choose highest scoring type
        if not scores:
            # Fallback based on input type
            if type_attr == "email":
                return FieldType.EMAIL
            if type_attr == "tel":
                return FieldType.TELEPHONE
            if type_attr == "file":
                return FieldType.RESUME_UPLOAD
            return FieldType.TEXT

        best_type = max(scores.items(), key=lambda x: x[1])[0]
        return best_type

    def _score_type_attribute(self, type_attr: str, scores: dict[FieldType, float]) -> None:
        """Add scores based on the 'type' attribute."""
        mapping = {
            "email": FieldType.EMAIL,
            "tel": FieldType.TELEPHONE,
            "number": FieldType.NUMBER,
            "date": FieldType.DATE,
            "password": FieldType.PASSWORD,
            "file": FieldType.RESUME_UPLOAD,  # generic; will be refined
        }
        if type_attr in mapping:
            scores[mapping[type_attr]] += self.WEIGHT_TYPE_ATTR

    def _score_text(self, text: str, weight: float, scores: dict[FieldType, float]) -> None:
        """Add weight to any FieldType whose keywords appear in the text."""
        if not text:
            return
        for field_type, keywords in self.keywords.items():
            if self._contains_any(text, keywords):
                scores[field_type] += weight

    @staticmethod
    def _contains_any(text: str, keywords: set[str]) -> bool:
        """Return True if any keyword is a substring of text."""
        text_lower = text.lower()
        return any(kw in text_lower for kw in keywords)

    @staticmethod
    def _build_keyword_sets() -> dict[FieldType, set[str]]:
        """Define the canonical keyword sets for each field type."""
        return {
            FieldType.EMAIL: {"email", "e-mail", "mail"},
            FieldType.TELEPHONE: {"phone", "tel", "mobile", "cell", "contact"},
            FieldType.FIRST_NAME: {"first", "given", "forename"},
            FieldType.LAST_NAME: {"last", "surname", "family"},
            FieldType.FULL_NAME: {"full name", "your name", "name"},
            FieldType.STREET_ADDRESS: {"address", "street", "addr"},
            FieldType.CITY: {"city", "town"},
            FieldType.STATE: {"state", "province", "region"},
            FieldType.ZIP_CODE: {"zip", "postal", "postcode", "pin"},
            FieldType.COUNTRY: {"country", "nation"},
            FieldType.LINKEDIN_URL: {"linkedin"},
            FieldType.GITHUB_URL: {"github"},
            FieldType.PORTFOLIO_URL: {"portfolio", "website", "url"},
            FieldType.WORK_AUTHORIZATION: {"authorized", "eligible", "work authorization"},
            FieldType.SPONSORSHIP: {"sponsor", "visa", "sponsorship"},
            FieldType.GENDER: {"gender", "sex"},
            FieldType.RACE: {"race", "ethnicity"},
            FieldType.VETERAN: {"veteran", "military"},
            FieldType.DISABILITY: {"disability", "disabled"},
            FieldType.RESUME_UPLOAD: {"resume", "cv", "curriculum"},
            FieldType.COVER_LETTER_UPLOAD: {"cover letter", "cover"},
            FieldType.SUBMIT_BUTTON: set(),
            FieldType.NEXT_BUTTON: set(),
            FieldType.PREVIOUS_BUTTON: set(),
        }
