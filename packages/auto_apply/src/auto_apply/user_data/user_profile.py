"""Defines the comprehensive Pydantic data models for a user's "persona".

This module contains a set of strongly-typed, validated data models that
collectively represent all the information about a user that might be required
for a job application. Using Pydantic ensures that the data loaded from the
user's JSON profile is complete, correct, and in the expected format, which
prevents a wide class of runtime errors.
"""
from typing import List, Literal, Optional
from pydantic import BaseModel, Field, EmailStr, HttpUrl
from pathlib import Path
from pydantic import BaseModel, Field, EmailStr, HttpUrl, validator

WorkplaceType = Literal["in-office", "hybrid", "remote"]
Gender = Literal["Male", "Female", "Non-binary", "Decline to self-identify"]
Race = Literal[
    "Hispanic or Latino",
    "White (Not Hispanic or Latino)",
    "Black or African American",
    "Native Hawaiian or other Pacific Islander",
    "Asian",
    "American Indian or Alaska Native",
    "Two or more Races (Not Hispanic or Latino)",
    "Decline to self-identify",
]
BrowserType = Literal["chrome", "firefox", "edge", "safari", "any"]

class PersonalInfo(BaseModel):
    """A model for the user's basic personal and contact information.

    Attributes:
        resume_path: A path to the user's resume file. The validator ensures
            that this path is resolved to an absolute path and that the file
            actually exists on the system before proceeding.
    """
    first_name: str
    middle_initial: Optional[str] = None
    last_name: str
    email: EmailStr
    phone_number: str
    street_address: str
    city: str
    state: str
    zip_code: str
    country: str = "United States"
    resume_path: Path

    @validator('resume_path', pre=True)
    def resume_must_exist_and_be_a_file(cls, v) -> Path:
        """Validates that the resume path points to a real, existing file."""
        if not isinstance(v, str):
            if isinstance(v, Path):
                return v
            raise TypeError('Resume path must be a string')

        resolved_path = Path(v).expanduser().resolve()

        if not resolved_path.exists():
            raise ValueError(f"Resume file not found at path: {resolved_path}")
        if not resolved_path.is_file():
            raise ValueError(f"The path provided is a directory, not a file: {resolved_path}")

        return resolved_path

class ProfessionalLinks(BaseModel):
    """A model for URLs to professional networking sites and portfolios.

    Uses aliases to allow the JSON file to use simple keys like "linkedin"
    while the Python code uses more descriptive attribute names like "linkedin_url".
    """
    linkedin_url: Optional[HttpUrl] = Field(None, alias="linkedin")
    github_url: Optional[HttpUrl] = Field(None, alias="github")
    portfolio_url: Optional[HttpUrl] = Field(None, alias="portfolio")

class Education(BaseModel):
    """Represents a single entry in the user's educational history."""
    school: str
    degree: str
    discipline: str
    start_date: str
    end_date: str
    gpa: Optional[str] = None

class WorkExperience(BaseModel):
    """Represents a single past or present job in the user's work history."""
    company: str
    title: str
    start_date: str
    end_date: Optional[str] = "Present"
    is_current_job: bool = False
    description: Optional[str] = None

class EEOInfo(BaseModel):
    """A model for optional Equal Employment Opportunity (EEO) information.

    This data is highly sensitive and should always be optional.
    The names are verbose to be explicit about what they are.
    """
    gender: Optional[Gender] = None
    race_ethnicity: Optional[Race] = Field(None, alias="race")
    # TODO: Update the answers/options available
    veteran_status: Optional[bool] = Field(None, alias="veteran")
    disability_status: Optional[bool] = Field(None, alias="disability")

class JobSearchPreferences(BaseModel):
    """Defines the user's criteria for a single job search session."""
    preferred_browser: BrowserType = "any"
    desired_job_titles: List[str] = Field(..., min_items=1)
    preferred_locations: List[str] = Field(default_factory=list)
    workplace_types: List[WorkplaceType] = Field(
        default=["in-office", "hybrid", "remote"]
    )
    experience_level: List[str] = Field(None, alias="experienceLevel")
    expected_salary: Optional[int] = Field(None, alias="salaryExpectations")

class UserProfile(BaseModel):
    """The complete, unified data model for a user persona.

    This is the top-level model that aggregates all other data models in this
    module. It represents the entire `default_profile.json` file.

    This model is loaded from a JSON file, not from .env.
    """
    personal_info: PersonalInfo
    links: ProfessionalLinks
    education: List[Education]
    work_experience: List[WorkExperience]
    eeo_info: EEOInfo = Field(default_factory=EEOInfo)
    search_preferences: JobSearchPreferences

    @property
    def full_name(self) -> str:
        """A derived property to get the user's full name as a formatted string."""
        if self.personal_info.middle_initial:
            return (
                f"{self.personal_info.first_name} "
                f"{self.personal_info.middle_initial}. "
                f"{self.personal_info.last_name}"
            )
        return f"{self.personal_info.first_name} {self.personal_info.last_name}"

    @property
    def signature(self) -> str:
        """A derived property to get a simple signature string."""
        return f"{self.personal_info.first_name} {self.personal_info.last_name}"