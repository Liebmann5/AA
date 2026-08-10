"""Defines the Pydantic models for a user's complete professional profile.

This module contains a set of strongly-typed, validated data models that
collectively represent all the information about a user that might be required
for a job application. It is designed to be comprehensive, secure, and
extensible. Using Pydantic ensures that the data loaded from the user's JSON
profile is complete, correct, and in the expected format, which prevents a
wide class of runtime errors.

Pydantic V2 Specifics:
- Uses `model_config = ConfigDict(...)` for configuration.
- Enables `validate_assignment=True` to ensure data integrity during GUI edits.
- Uses `mode='before'` for path validators to handle string-to-Path conversion.
"""

from pathlib import Path
from typing import Any, Literal

from auto_apply.domain.config import CHECKPOINTS_DIR

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    HttpUrl,
    field_validator,
)

# --- Type Aliases for controlled vocabularies ---
NameSuffix = Literal["Sr.", "Jr.", "II", "III", "IV", "V"]
WorkplaceType = Literal["in-office", "hybrid", "remote"]
EmploymentType = Literal["full-time", "part-time", "contract", "temporary", "internship"]  # noqa: E501
Gender = Literal["Male", "Female", "Non-binary", "Decline to self-identify"]
Race = Literal[
    "Hispanic or Latino", "White (Not Hispanic or Latino)", "Black or African American",
    "Native Hawaiian or other Pacific Islander", "Asian", "American Indian or Alaska Native",  # noqa: E501
    "Two or more Races (Not Hispanic or Latino)", "Decline to self-identify",
]
VeteranStatus = Literal[
    "I am not a protected veteran",
    "I identify as one or more of the classifications of a protected veteran",
    "I don't wish to answer",
]
BrowserType = Literal["chrome", "firefox", "edge", "safari", "any"]
SalaryFormat = Literal["yearly", "hourly", "monthly"]

VisaSponsorshipType = Literal[
    "H-1B", "H1B Transfer", "H1B Sponsorship",
    "STEM OPT", "CPT", "OPT",
    "L-1", "O-1", "TN", "E-3",
    "E-2", "EB-1", "EB-2", "EB-3",
    "Green Card", "Citizenship", "Other",
]


#Identification Information
class PersonalInfo(BaseModel):
    """A model for the user's basic personal and contact information."""
    # V2 Config: Validate data even when modifying attributes after creation
    model_config = ConfigDict(validate_assignment=True, populate_by_name=True)

    first_name: str
    middle_name: str | None = Field(None, description="Optional middle name.")
    last_name: str
    suffix: NameSuffix | None = Field(None, description="Optional name suffix like Jr., Sr., II.")  # noqa: E501
    email: EmailStr
    phone_number: str
    street_address: str
    city: str
    state: str
    zip_code: str
    country: str = "United States"
    pronouns: str | None = Field(None, description="Optional: e.g., 'he/him', 'she/her', 'they/them'")  # noqa: E501
    citizenships: list[str] = Field(default_factory=list, description="List of 2-letter country codes, e.g., ['US', 'DE']")  # noqa: E501

    resume_path: str | None = Field(
        default=None,
        description=(
            "Path to the resume file. Accepts:\n"
            "  - Absolute path: /home/nick/resume.pdf\n"
            "  - Relative path: resume.pdf  (resolved against PROFILES_DIR)\n"
            "  - Relative with subfolder: documents/resume.pdf\n"
            "Using a relative path ensures portability across machines and USB drives."
        ),
    )
    cover_letter: str | None = Field(None, description="A path to a cover letter file or a raw string.")  # noqa: E501

    @property
    def full_address(self) -> str:
        """Returns the user's full address as a formatted string.

        Returns:
            str: The concatenated address string (Street, City, State Zip).
        """
        return f"{self.street_address}, {self.city}, {self.state} {self.zip_code}"

    @field_validator('resume_path', mode='before')
    @classmethod
    def validate_resume_exists(cls, v: Any) -> Any:
        """Validates format without hitting the OS disk to ensure USB portability."""
        if isinstance(v, (str, Path)):
            # Just ensure it converts to a string safely. 
            # Existence checks happen at the Interaction Layer, not the Domain Layer.
            return str(Path(str(v)).expanduser())
        return v

    @field_validator('cover_letter', mode='before')
    @classmethod
    def validate_cover_letter(cls, v: Any) -> Any:
        """Validates format without hitting the OS disk to ensure USB portability."""
        if isinstance(v, (str, Path)) and str(v).strip():
            return str(Path(str(v)).expanduser())
        return v

    def get_resolved_resume_path(self) -> Path | None:
        """Returns the absolute path to the resume file.

        Resolves relative paths against PROFILES_DIR from domain/config.
        Returns None if resume_path is not set or the file does not exist.

        This is the portable alternative to accessing ``resume_path`` directly.
        On a USB drive where the drive letter may change between machines,
        storing a relative path like ``"resume.pdf"`` and resolving it at
        runtime ensures the file is always found.

        Returns:
            Absolute Path to the resume file, or None if the path is not set
            or the file cannot be found.

        Example:
            >>> info = PersonalInfo(first_name="N", last_name="L", email="n@e.com",
            ...                     resume_path="resume.pdf")
            >>> resolved = info.get_resolved_resume_path()
            >>> # resolved is PROFILES_DIR / "resume.pdf" if that file exists
        """
        if not self.resume_path:
            return None

        from auto_apply.domain.config import PROFILES_DIR

        candidate = Path(self.resume_path)

        # If absolute and exists, use it directly
        if candidate.is_absolute():
            return candidate if candidate.exists() else None

        # If relative, resolve against PROFILES_DIR
        resolved = PROFILES_DIR / candidate
        return resolved if resolved.exists() else None


class ProfessionalLinks(BaseModel):
    """A model for URLs to professional networking sites and portfolios.

    Uses aliases to allow the JSON file to use simple keys like "linkedin"
    while the Python code uses more descriptive attribute names like "linkedin_url".
    """
    model_config = ConfigDict(validate_assignment=True)

    linkedin_url: HttpUrl | None = Field(None, alias="linkedin")
    github_url: HttpUrl | None = Field(None, alias="github")
    portfolio_url: HttpUrl | None = Field(None, alias="portfolio")


class Education(BaseModel):
    """A single entry in the user's educational history."""
    model_config = ConfigDict(validate_assignment=True)

    school: str
    degree: str
    discipline: str
    start_date: str | None = None
    end_date: str | None = None
    #TODO: FIGURE THIS OUT!! (also consider adding validation for GPA format)
    gpa: str | None = None


class WorkExperience(BaseModel):
    """A single past or present job in the user's work history."""
    model_config = ConfigDict(validate_assignment=True)

    company: str
    title: str
    start_date: str
    end_date: str | None = "Present"
    description: str | None = None


class Reference(BaseModel):
    """Contact information for a single professional reference."""
    model_config = ConfigDict(validate_assignment=True)

    name: str
    job_title: str
    company: str
    email: EmailStr
    phone_number: str


class ClearanceDeclaration(BaseModel):
    """A security clearance the user declares they hold.

    Deliberately minimal. ``jurisdiction`` says whose clearance system this
    belongs to; ``level`` is the user's own words for it. AA does not enumerate
    or validate clearance levels — a fixed ``Literal[...]`` of levels would be a
    second source of truth about every country's clearance system, wrong for the
    190 jurisdictions not enumerated and drifting for the ones that are. A
    free-text level the user fills in themselves cannot be wrong about their own
    clearance. A per-jurisdiction picker is a future UX nicety, not a
    correctness requirement, and nothing here forecloses it.
    """

    model_config = ConfigDict(validate_assignment=True)

    jurisdiction: str = Field(description="ISO 3166-1 alpha-2 country whose clearance system this is, e.g. 'US', 'GB'.")  # noqa: E501
    level: str = Field(description="The clearance as the user describes it, in their own words.")  # noqa: E501


class LegalInfo(BaseModel):
    """Optional legal declarations."""
    model_config = ConfigDict(validate_assignment=True)

    #requires_sponsorship: bool | None = Field(None, description="Does the user generally require work visa sponsorship?")  # noqa: E501
    requires_sponsorship: bool = False
    has_work_authorization: bool = True
    non_compete_agreements: list[str] = Field(default_factory=list, description="List of company names the user has a non-compete with.")  # noqa: E501
    # None means "not declared" — an honest absence. It is never coerced to
    # False, because "the user did not tell us" and "the user has no clearance"
    # are different facts, and only the user may assert the second.
    security_clearance: "ClearanceDeclaration | None" = Field(default=None, description="The user's declared security clearance, or None if not declared.")  # noqa: E501
    #TODO: Add more fields as needed
    # "has_work_authorization": true,
    # "work_authorization_details": "Authorized",
    # "has_criminal_record": false,
    # "criminal_record_details": null


class EEOInfo(BaseModel):
    """ A model for Optional Equal Employment Opportunity (EEO) information.

    This data is highly sensitive and should always be optional.
    The names are verbose to be explicit about what they are.
    """
    model_config = ConfigDict(validate_assignment=True)

    gender: Gender | None = None
    race_ethnicity: Race | None = Field(None, alias="race")
    veteran_status: VeteranStatus | None = Field(None, alias="veteran")
    disability_status: bool | None = Field(None, alias="disability")


#! Ask the user if they have any disabilities that would require accommodations then
#! rather than save them just ask users' if they'd like to implement any of these
#! accessibility settings.
class AccessibilityPreferences(BaseModel):
    """User preferences for application accessibility and localization."""
    model_config = ConfigDict(validate_assignment=True)

    ui_language: str = Field("en-US", description="The language code for the UI.")
    prefers_high_contrast: bool = False
    prefers_audio_captchas: bool = False


class JobSearchPreferences(BaseModel):
    """User's criteria and configuration for a job search session."""
    model_config = ConfigDict(validate_assignment=True)

    # Core search criteria
    desired_job_titles: list[str] = Field(..., min_length=1)
    preferred_locations: list[str] = Field(default_factory=list)
    employment_types: list[EmploymentType] = Field(default_factory=list)
    workplace_types: list[WorkplaceType] = Field(default=["in-office", "hybrid", "remote"])  # noqa: E501
    experience_level: list[str] | None = Field(None, alias="experienceLevel")

    # Salary preferences
    expected_salary: int | None = Field(None, alias="salaryExpectations")
    salary_currency: str = "USD"
    salary_format: SalaryFormat = "yearly"

    max_commute_miles: float | None = Field(
        None,
        description="Maximum acceptable one-way commute in miles. None = no limit.",
    )
    skills: list[str] = Field(
        default_factory=list,
        description=(
            "User's self-reported skills and technologies. Used by HardSkillsFilter "
            "to compute overlap with job-required skills. Example: ['Python', 'SQL', 'Docker']."
        ),
    )

    # Best avoided
    blocked_job_titles: list[str] = Field(default_factory=list)
    blocked_locations: list[str] = Field(default_factory=list)
    blocked_companies: list[str] = Field(default_factory=list)
    blocked_vocabulary: list[str] = Field(default_factory=list)  #A way to avoid specific things Ex) diesal mechanic > mechanic || JavaScript  # noqa: E501

class ApplicationPreferences(BaseModel):
    """User preferences for filling out application forms."""
    model_config = ConfigDict(validate_assignment=True)
    earliest_start_date: str | None = Field(None, description="e.g., 'YYYY-MM-DD' or 'Two Weeks'")  # noqa: E501
    cooldown_days: int | None = Field(
        None,
        description=(
            "Days before re-applying to the same company. "
            "None falls back to ThrottlingFilter.DEFAULT_COOLDOWN_DAYS (180)."
        ),
    )


class PolitenessConfig(BaseModel):
    """User-specific settings for rate limiting and robot compliance."""
    model_config = ConfigDict(validate_assignment=True)

    respect_robots_txt: bool = Field(True, description="If false, ignores robots.txt disallow rules.")  # noqa: E501
    default_delay: float = 2.0


class ApplicationConfig(BaseModel):
    """Configuration settings specific to the bot's runtime behavior.

    This separates the 'Human' data from the 'Bot' configuration, allowing
    different runtime strategies for the same person.
    """
    model_config = ConfigDict(validate_assignment=True, populate_by_name=True)

    preferred_browser: BrowserType = Field("any", description="The browser engine to use.")  # noqa: E501
    headless_mode: bool = Field(
        False,
        validation_alias=AliasChoices("headless_mode", "run_headless"),
        description="Run the browser without a visible window (performance / headless hosts).",
    )
    locale: str | None = Field(None, description="Browser locale override.")
    use_proxies: bool = False
    # The proxy endpoint traffic is routed through when use_proxies is on. None
    # means no proxy configured. This is an opt-in advanced feature (paid proxy
    # service, or an advanced/researcher user's own endpoint), off by default.
    # When use_proxies is on and this is None, AA must refuse to launch rather
    # than connect directly — see BrowserCascade._build_config.
    proxy_server: str | None = None
    daily_application_limit: int = 1000
    enable_behavior_humanization: bool = False
    rotate_user_agent: bool = Field(
        False,
        description=(
            "Pick a random user-agent from the built-in pool on each launch. "
            "Consumed by selenium_provider._get_user_agent via the browser "
            "cascade provider config."
        ),
    )
    user_agent: str | None = Field(
        None,
        description=(
            "Fixed user-agent override. When set (and rotate_user_agent is off), "
            "the browser presents this exact UA string. None = use the default."
        ),
    )
    # TODO(future feature): when True, AA should self-tune runtime performance
    # (concurrency, delays, strategy) to the host machine. Intentionally not yet
    # wired to a consumer — planned, not dead. Do not delete.
    auto_optimize_performance: bool = Field(False, description="Let AA figure out how to keep things running efficiently.")  # noqa: E501
    human_review_checkpoints: list[str] | None = Field(
        None,
        description=(
            "HITL checkpoints where the agent pauses for user approval. "
            "Valid values: AFTER_VETTING, BEFORE_FORM_SUBMIT, "
            "ON_AMBIGUOUS_SUBMISSION, ON_SUSPICIOUS_REDIRECT, ON_LOW_CONFIDENCE_FIELD. "
            "Defaults to [BEFORE_FORM_SUBMIT, ON_SUSPICIOUS_REDIRECT] when null."
        ),
    )


class CustomAnswerTemplate(BaseModel):
    """A pre-authored answer for a specific type of application question.

    When ApplicationsWorkflow encounters a custom question, it checks
    ``custom_answer_templates`` for a matching keyword before invoking
    GPT4All.  Keyword matching is fuzzy (SpaCy similarity), so
    ``"why this role"`` will match ``"Why are you interested in this position?"``.

    Attributes:
        keywords: Keywords or phrases this answer applies to.  AA uses
            similarity matching, not exact matching.  Examples:
            ``["why this role", "why this company", "career goals"]``.
        answer: Your pre-written answer.  Keep under 500 characters for
            form compatibility.
        max_length: Truncation limit.  AA will not paste more than this
            many characters into a form field.
    """
    model_config = ConfigDict(frozen=True)

    keywords: list[str] = Field(
        ...,
        min_length=1,
        description=(
            "Keywords or phrases this answer applies to. "
            "AA uses similarity matching, not exact matching. "
            "Examples: ['why this role', 'why this company', 'career goals']"
        ),
    )
    answer: str = Field(
        ...,
        min_length=20,
        description=(
            "Your pre-written answer. Keep under 500 characters for form "
            "compatibility."
        ),
    )
    max_length: int = Field(
        default=500,
        description=(
            "Truncation limit. AA will not paste more than this many "
            "characters into a form field."
        ),
    )


class UserProfile(BaseModel):
    """The complete, unified data model for a user's professional persona.

    This is the top-level model that aggregates all other data models in this
    module. It represents the entire `default_profile.json` file.

    This model is loaded from a JSON file, not from .env.
    """
    model_config = ConfigDict(validate_assignment=True)

    profile_name: str = Field(..., description="A unique name/ID for this profile (e.g., 'Bruce-Engineer').")  # noqa: E501

    # --- Sub-models ---
    personal_info: PersonalInfo
    links: ProfessionalLinks
    education: list[Education] = Field(default_factory=list)
    work_experience: list[WorkExperience] = Field(default_factory=list)
    references: list[Reference] = Field(default_factory=list)
    legal_info: LegalInfo = Field(default_factory=LegalInfo)
    career_summary: str = Field(
        ...,  # The `...` ellipsis here explicitly means "this field is required"
        min_length=1,
        description="A summary of the user's career.  Longer summaries (at least 50 characters) produce better AI-powered answers, but a short summary is accepted for worst-case users."
    )

    eeo_info: EEOInfo = Field(default_factory=EEOInfo)
    accessibility_preferences: AccessibilityPreferences = Field(default_factory=AccessibilityPreferences)  # noqa: E501

    search_preferences: JobSearchPreferences
    application_preferences: ApplicationPreferences = Field(default_factory=ApplicationPreferences)  # noqa: E501

    #Configurations for the bot's behavior
    app_config: ApplicationConfig = Field(default_factory=ApplicationConfig)

    # --- Map the JSON key 'politeness_settings' to this field ---
    politeness: PolitenessConfig = Field(default_factory=PolitenessConfig, alias="politeness_settings")  # noqa: E501

    # --- Custom answer templates (pre-authored answers checked before GPT4All) ---
    custom_answer_templates: list[CustomAnswerTemplate] = Field(
        default_factory=list,
        description=(
            "Pre-authored answers for common custom questions. "
            "AA checks these before invoking GPT4All. "
            "See docs/user_guide/profile_guide.md for examples."
        ),
    )

    def to_json(self) -> str:
        """Serializes(V2) the profile to a JSON string.

        Returns:
            str: The JSON representation of the profile, indented for readability.
        """
        return self.model_dump_json(indent=2, by_alias=True)

    def get_checkpoint_path(self) -> Path:
        """Returns the directory used to store checkpoint files for this profile.

        Each profile gets its own subdirectory under CHECKPOINTS_DIR so that
        concurrent or sequential sessions with different profiles don't
        overwrite each other's recovery state.

        Returns:
            Path: e.g. <dev_data>/checkpoints/Bruce-Engineer
        """
        return CHECKPOINTS_DIR / self.profile_name

    @property
    def full_name(self) -> str:
        """A derived property for the user's full name.

        Returns:
            str: A string value of the users First MiddleInitial. Last name.
        """
        first = self.personal_info.first_name.capitalize()
        last = self.personal_info.last_name.capitalize()

        if self.personal_info.middle_name:
            return (
                f"{first} "
                f"{self.personal_info.middle_name[0].upper()}. "
                f"{last}"
            )
        return f"{first} {last}"

    @property
    def signature(self) -> str:
        """A derived property to get a simple signature string.

        Returns:
            str: A string value of the users First and Last name for use in e-signatures.
        """  # noqa: E501
        return f"{self.personal_info.first_name} {self.personal_info.last_name}"

    @property
    def initials(self) -> str:
        """A derived property to get the users' initial characters.

        Returns:
            str: A string value of the users' initial characters for their first
                then last name
        """
        return f"{self.personal_info.first_name[0].upper()}{self.personal_info.last_name[0].upper()}"  # noqa: E501

    @property
    def settings(self) -> dict:
        """Returns a flat dict of user-configurable settings for config merging.

        The CapabilitiesRegistry's three-tier config merger reads this to
        layer user preferences on top of runtime defaults. This property
        extracts relevant values from app_config and politeness into the
        flat key-value namespace that _merge_config() expects.

        This is a read-only computed property on data already validated
        by Pydantic — it introduces no new file I/O or security surface.

        Returns:
            Dict[str, Any]: Flat settings dict. Keys match the config
                namespace used by _RUNTIME_DEFAULTS in capabilities_registry.py.
        """
        result: dict[str, Any] = {}

        # ── App config settings ───────────────────────────────────────
        if self.app_config:
            ac = self.app_config
            if ac.preferred_browser and ac.preferred_browser != "any":
                result["preferred_browser"] = ac.preferred_browser
            result["headless_mode"] = ac.headless_mode
            result["max_applications_per_session"] = ac.daily_application_limit
            result["enable_behavior_humanization"] = ac.enable_behavior_humanization
            result["auto_optimize_performance"] = ac.auto_optimize_performance

        # ── Politeness settings ───────────────────────────────────────
        if self.politeness:
            pol = self.politeness
            result["respect_robots_txt"] = pol.respect_robots_txt
            if hasattr(pol, "default_delay") and pol.default_delay is not None:
                result["min_action_delay_ms"] = int(pol.default_delay * 1000)

        return result