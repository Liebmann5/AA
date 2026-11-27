"""Output models from the mathematical webpage analysis pipeline.

These immutable data classes represent the structured understanding of
a webpage after segmentation, label‑input pairing, and field classification.
They are the domain‑layer results consumed by the Application Layer to
generate UIModels and InteractionPlans.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto

from auto_apply.domain.models.math_dom import DOMNode, Geometry
from auto_apply.domain.models.page_record import FormRecord, ListingDetectionFacts


class LabelSource:
    """Where a field's label came from: the rungs of the pairing ladder.

    Strongest first (06 section 4, CT-ALG-008). Plain strings, so the page
    record can count them without holding page text.
    """

    LABEL_FOR = "label-for"
    WRAPPING_LABEL = "wrapping-label"
    ARIA_LABELLEDBY = "aria-labelledby"
    ARIA_LABEL = "aria-label"
    ACCESSIBLE_NAME = "accessible-name"
    LEGEND = "legend"
    GROUP_LABELLEDBY = "group-aria-labelledby"
    GROUP_HEADING = "group-heading"
    PRECEDING_TEXT = "preceding-text"
    GEOMETRY = "geometry"
    TITLE = "title"
    PLACEHOLDER = "placeholder"
    NONE = "none"


class FieldType(Enum):
    """Canonical field types inferred by mathematical analysis.

    These are pure semantic categories, independent of any UI framework.
    The list is exhaustive for job application forms.
    """

    UNKNOWN = auto()
    TEXT = auto()               # Generic text input
    EMAIL = auto()
    PASSWORD = auto()
    TELEPHONE = auto()
    NUMBER = auto()
    DATE = auto()

    FIRST_NAME = auto()
    LAST_NAME = auto()
    FULL_NAME = auto()
    STREET_ADDRESS = auto()
    CITY = auto()
    STATE = auto()
    ZIP_CODE = auto()
    COUNTRY = auto()

    RESUME_UPLOAD = auto()
    COVER_LETTER_UPLOAD = auto()

    LINKEDIN_URL = auto()
    GITHUB_URL = auto()
    PORTFOLIO_URL = auto()

    # Selection fields
    SELECT = auto()
    CHECKBOX = auto()
    RADIO = auto()

    # Legal / EEO
    WORK_AUTHORIZATION = auto()
    SPONSORSHIP = auto()
    GENDER = auto()
    RACE = auto()
    VETERAN = auto()
    DISABILITY = auto()

    # Buttons
    SUBMIT_BUTTON = auto()
    NEXT_BUTTON = auto()
    PREVIOUS_BUTTON = auto()
    UPLOAD_BUTTON = auto()


@dataclass(frozen=True, slots=True)
class LabeledField:
    """An input element paired with its associated label.

    Attributes:
        input_node: The DOMNode representing the form control.
        label_node: The DOMNode containing the label text (may be None).
        label_text: Cleaned text content of the label (or placeholder/aria).
        inferred_type: Best guess of the field's semantic type.
        is_required: True if field appears mandatory (based on attributes).
        is_honeypot: True if the field is a security trap: decided only on
            evidence that a person cannot see it (CT-ALG-014), never on a name.
        options: For select/radio, list of possible values.
        label_source: The rung of the pairing ladder that gave the label
            (:class:`LabelSource` value), ``"none"`` when no label was found.
        description: Help text (``aria-describedby``, a hint line below the
            field). Never the label.
        requiredness: ``"REQUIRED"``, ``"OPTIONAL"`` or ``"UNKNOWN"``
            (CT-FR-012). ``is_required`` is ``requiredness == "REQUIRED"``.
        required_signals: The signals that decided requiredness.
        hidden_reason: Why a person cannot see the control ("" when visible).
        trap_verdict: ``"TRAP"``, ``"CLEAR"``, ``"UNKNOWN"`` (visible and
            unlabelled: recorded, never filled) or ``"HIDDEN"`` (hidden now
            but labelled like a real field: never filled, re-observed).
        trap_evidence: The evidence behind ``trap_verdict``.
        option_nodes: For a question group, the option controls in order;
            ``options`` holds their labels in the same order.
        topic: For a question group or a checkbox, what the question is about
            (work authorization, sponsorship, EEO), when the label says so.
    """

    input_node: DOMNode
    label_node: DOMNode | None
    label_text: str
    inferred_type: FieldType
    is_required: bool = False
    is_honeypot: bool = False
    options: list[str] = field(default_factory=list)
    label_source: str = "none"
    description: str = ""
    requiredness: str = "UNKNOWN"
    required_signals: tuple[str, ...] = ()
    hidden_reason: str = ""
    trap_verdict: str = "UNKNOWN"
    trap_evidence: tuple[str, ...] = ()
    option_nodes: tuple[DOMNode, ...] = ()
    topic: FieldType = FieldType.UNKNOWN

    @property
    def input_id(self) -> str:
        """Return a stable identifier for the input (based on structural hash)."""
        return self.input_node.structural_hash

    @property
    def is_group(self) -> bool:
        """True for a radio or checkbox question with its options."""
        return bool(self.option_nodes)

    @property
    def is_hidden(self) -> bool:
        """True when a person cannot see the control."""
        return bool(self.hidden_reason)


@dataclass(frozen=True, slots=True)
class FieldCluster:
    """A group of related fields (e.g., a section of a form).

    Clusters are discovered via geometric proximity and DOM containment.

    Attributes:
        fields: List of labeled fields belonging to this cluster.
        bounding_box: Overall bounding box covering all fields.
        section_label: Text of a heading/legend that titles the section.
    """

    fields: list[LabeledField] = field(default_factory=list)
    bounding_box: Geometry | None = None
    section_label: str = ""

    def __post_init__(self) -> None:
        """Compute bounding box if not provided and fields exist."""
        if self.bounding_box is None and self.fields:
            # Compute union of all input geometries
            geoms = [f.input_node.geometry for f in self.fields if f.input_node.geometry]
            if geoms:
                min_x = min(g.x for g in geoms)
                min_y = min(g.y for g in geoms)
                max_x = max(g.x + g.width for g in geoms)
                max_y = max(g.y + g.height for g in geoms)
                object.__setattr__(
                    self,
                    "bounding_box",
                    Geometry(min_x, min_y, max_x - min_x, max_y - min_y),
                )


@dataclass(frozen=True, slots=True)
class FormRegion:
    """A complete form or multi‑step form section.

    A webpage may contain multiple FormRegions (e.g., login form, search form,
    main application form). Each region contains one or more field clusters.

    Attributes:
        root_node: The DOMNode that is the common ancestor of all fields.
        clusters: List of field clusters, in logical order (top‑to‑bottom).
        submit_button: The primary submit button (or None).
        next_button: "Next" button for multi‑step forms (or None).
        is_multi_step: True if the form appears to span multiple pages.
    """

    root_node: DOMNode
    clusters: list[FieldCluster] = field(default_factory=list)
    submit_button: LabeledField | None = None
    next_button: LabeledField | None = None
    previous_button: LabeledField | None = None
    is_multi_step: bool = False
    #: Counters, enumerations and flags about how the form was read (the
    #: form part of the page record, CT-T-018); None when not built.
    record: FormRecord | None = None

    @property
    def all_fields(self) -> list[LabeledField]:
        """Return a flattened list of all fields in this region."""
        result: list[LabeledField] = []
        for cluster in self.clusters:
            result.extend(cluster.fields)
        return result


@dataclass(frozen=True, slots=True)
class WebpageStructure:
    """Complete mathematical decomposition of a webpage.

    This is the top‑level output of the analysis pipeline. It contains
    the full DOM tree and all identified form regions, along with metadata
    about the page.

    Attributes:
        url: The URL of the analyzed page.
        title: Page title.
        dom_root: Root of the extracted DOM tree, or ``None`` when extraction
            failed and the structure is a deliberate empty fallback. Typed as
            optional because two fallback constructors
            (``MathematicalWebAnalyzer.analyze_form`` and
            ``WebpageAnalyzer._build_partial_structure``) legitimately build
            structures without a tree; the previous non-optional annotation
            contradicted those call sites.
        forms: List of detected form regions (in order of appearance).
        job_listings: Nodes that likely represent job cards (if any).

    Page identity (challenge, login wall) is deliberately NOT part of this
    structure: it is answered once by domain/services/page_assessment.py.
    The is_captcha_present / is_login_wall fields that used to sit here
    were written and never read.
    """

    url: str
    title: str
    dom_root: DOMNode | None = None
    forms: list[FormRegion] = field(default_factory=list)
    job_listings: list[DOMNode] = field(default_factory=list)
    #: Numbers from card detection for the S1 trace (None when not run).
    listing_facts: ListingDetectionFacts | None = None

    def get_main_form(self) -> FormRegion | None:
        """Return the largest form region (by field count) or None."""
        if not self.forms:
            return None
        return max(self.forms, key=lambda f: len(f.all_fields))

    def get_all_fields(self) -> list[LabeledField]:
        """Return all labeled fields across all forms."""
        result: list[LabeledField] = []
        for form in self.forms:
            result.extend(form.all_fields)
        return result
