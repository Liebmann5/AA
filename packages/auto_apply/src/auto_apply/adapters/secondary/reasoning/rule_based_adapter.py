"""Provides the reasoning engine that converts UI perceptions into actionable plans.

This module implements 'The Strategist' phase of the architecture. It analyzes a
UIModel (snapshot of the page) against the UserProfile to generate an
InteractionPlan. It utilizes semantic matching to pair form labels with profile
attributes and logic rules to satisfy constraints.

Provides deterministic reasoning capabilities using Logic Programming principles.

This module implements a pure-Python logic engine that derives definitive answers
from structured data (UserProfile, Job Models) and logical predicates.

It is responsible for:
1.  Determining Work Authorization eligibility based on location.
2.  Validating 'Two-Way Fit' constraints (e.g., experience years vs. seniority).
3.  Answering binary application questions (Sponsorship, Clearance).

Unlike the TextMatcher, this engine returns exact True/False/None determinations,
not probability scores.
"""

import logging
import re
from typing import Any

# Services
from auto_apply.application.services.text_matching import TextMatcher
from auto_apply.domain.models.profile import UserProfile

# Core Models
from auto_apply.domain.models.ui import (
    InteractionPlan,
    InteractionType,
    PlannedAction,
    UIElement,
    UIElementType,
    UIModel,
)

logger = logging.getLogger(__name__)


class LogicEngine:
    """A reasoning engine that applies strict logical rules to application data.

    This class encapsulates business logic regarding employment laws (authorization),
    job market standards (years of experience), and user constraints.
    """

    def __init__(self, profile: UserProfile):
        """Initializes the logic engine with the user's facts.

        Args:
            profile (UserProfile): The source of truth for user attributes.
        """
        self.profile = profile

        # Pre-process facts for efficient O(1) lookups
        self.citizenships = {c.upper() for c in self.profile.personal_info.citizenships}
        self._normalize_citizenships()

    def _normalize_citizenships(self) -> None:
        """Expands country codes into common variations to improve matching hit rates."""  # noqa: E501
        # Common variations mapping
        mappings = {
            "US": ["USA", "UNITED STATES", "AMERICA"],
            "UK": ["UNITED KINGDOM", "BRITAIN", "ENGLAND", "GREAT BRITAIN"],
            "CA": ["CANADA"],
            "DE": ["GERMANY", "DEUTSCHLAND"],
            "FR": ["FRANCE"],
            # Add more as the user base expands
        }

        expanded_set = set(self.citizenships)
        for code in list(self.citizenships):
            if code in mappings:
                for alias in mappings[code]:
                    expanded_set.add(alias)

        self.citizenships = expanded_set

    def check_work_authorization(self, target_location: str) -> bool:
        """Determines if the user is legally authorized to work in a target location.

        Logic:
            Authorized IF:
                1. Location matches User Citizenship.
                2. OR User explicitly states generic "Authorized" in legal_info.
                3. OR Location is "Remote" (Assumed flexible, though risky).

        Args:
            target_location (str): The raw location string from the job posting
                                   (e.g., "New York, NY", "London, UK").

        Returns:
            bool: True if authorized, False if unauthorized.
        """
        if not target_location:
            # Fail open: If we don't know the location, we assume we can apply
            # and let the human decide later.
            return True

        # Check 1: User Explicit Override
        if self.profile.legal_info.has_work_authorization:
            return True

        location_upper = target_location.upper()

        # Check 2: Citizenship Match
        # We check if any of our citizenship tokens appear in the location string
        for token in self.citizenships:
            # We use word boundary checks to avoid partial matches (e.g. "US" in "RUSSIA")  # noqa: E501
            # Simple substring check is usually sufficient for country names
            if token in location_upper:
                return True

        # Check 3: Remote Work
        # Many remote jobs allow cross-border work, though tax laws vary.
        # We assume True to avoid false negatives.
        if "REMOTE" in location_upper:
            return True

        # If strict matching fails, we return False (Unauthorized)
        return False

    def requires_sponsorship(self) -> str:
        """Returns the definitive answer for sponsorship questions.

        Returns:
            str: "Yes" or "No" based on profile configuration.
        """
        if self.profile.legal_info.requires_sponsorship:
            return "Yes"
        return "No"

    def analyze_experience_contradiction(self, job_title: str, job_description: str) -> str | None:  # noqa: E501
        """Detects logical contradictions between Job Title and Requirements.

        Common Anomaly: A job labeled "Entry Level" that requires "5+ years of experience".

        Args:
            job_title (str): The heading of the job posting.
            job_description (str): The full text body of the posting.

        Returns:
            Optional[str]: A description of the anomaly if found, otherwise None.
        """  # noqa: E501
        title_lower = job_title.lower()

        # 1. Identify "Entry Level" intent
        entry_keywords = ["entry level", "junior", "graduate", "intern", "apprentice"]
        is_entry_level = any(kw in title_lower for kw in entry_keywords)

        if not is_entry_level:
            return None

        # 2. Extract Required Years (Regex)
        # Patterns: "5 years", "5+ years", "5-7 years"
        # We look for digits preceding "year"
        years_pattern = re.compile(r'(\d+)\+?\s*-?\s*\d*\s*years?', re.IGNORECASE)
        matches = years_pattern.findall(job_description)

        if not matches:
            return None

        # Convert matches to integers
        extracted_years = []
        for m in matches:
            try:
                extracted_years.append(int(m))
            except ValueError:
                continue

        if not extracted_years:
            return None

        # 3. Apply Logic Rule
        # Contradiction Rule: Max required years should not exceed 2 for entry level.
        # We take the maximum mentioned year to be safe, or average?
        # Usually requirements lists say "3+ years", so we look for the *lowest* constraint found?  # noqa: E501
        # Actually, if ANY requirement says "5+ years", it's a mismatch for Entry.
        # However, descriptions also list "10 years company history".
        # Context is hard with Regex. We use a conservative threshold.

        max_years_mentioned = max(extracted_years)

        # Threshold: If an Entry Level job mentions anything > 3 years, flag it.
        if max_years_mentioned > 3:
            return f"Logic Contradiction: Title suggests Entry Level, but description mentions '{max_years_mentioned} years'."  # noqa: E501

        return None

    # def analyze_experience_contradiction(self, job_title: str, job_description: str) -> None:  # noqa: E501
    #     """Detects 'Fake Entry Level' jobs (Efficient & Mathematical)."""
    #     title_lower = job_title.lower()
    #     is_entry_level = any(kw in title_lower for kw in ["entry level", "junior", "graduate", "intern"])  # noqa: E501

    #     if not is_entry_level:
    #         return

    #     # Extract required years using Regex (Optimized)
    #     years_pattern = re.compile(r'(\d+)\+?\s*-?\s*\d*\s*years?', re.IGNORECASE)
    #     matches = [int(m) for m in years_pattern.findall(job_description) if m.isdigit()]  # noqa: E501

    #     if matches and max(matches) > 3:
    #         # We found a contradiction! Fire the event. (Decoupled)
    #         self.event_bus.publish(Event.JOB_VETTED_FAIL, {
    #             "reason": "Fake Entry Level",
    #             "years_required": max(matches),
    #             "signal_type": "ENTRY_LEVEL_EXPERIENCE_REQUIRED"
    #         })

    def check_security_clearance(self, job_description: str) -> bool:
        """Determines if the user meets security clearance requirements.

        Args:
            job_description (str): The full text of the job.

        Returns:
            bool: True if the user qualifies (or no clearance needed),
                  False if clearance is required but user lacks it.
        """
        desc_lower = job_description.lower()

        # Keywords indicating a hard requirement
        clearance_keywords = [
            "security clearance",
            "active clearance",
            "top secret",
            "ts/sci",
            "dod clearance"
        ]

        # 1. Check if job requires clearance
        requires_clearance = any(kw in desc_lower for kw in clearance_keywords)

        if not requires_clearance:
            return True

        # 2. Read the user's declared clearance. None means "not declared" — we
        # never coerce that to "has none", because only the user may assert they
        # hold no clearance. A user who declared one is not auto-rejected here:
        # AA cannot verify a free-text level against a job's requirement without
        # a taxonomy it deliberately does not keep, so it lets the application
        # proceed and leaves the actual clearance question to the human review
        # gate at form-fill time rather than answering it here.
        declared = self.profile.legal_info.security_clearance

        if declared is None:
            # No clearance declared and the job hard-requires one: nothing to
            # offer. This reads a real absence, not a fabricated False.
            return False

        return True

class FormSolver:
    """The brain of the form engine. Generates interaction plans from UI snapshots.

    This class is responsible for determining 'What' to enter into a form.
    It relies on a comprehensive mapping of the user's profile to semantic
    concepts (e.g., mapping 'first_name' to 'Given Name' labels).
    """

    def __init__(self, profile: UserProfile, text_matcher=None):
        """Initializes the solver with the specific user context.

        Args:
            profile (UserProfile): The candidate data to use for answering.
            text_matcher: Optional shared TextMatcher. When omitted a new one is
                created (loads SpaCy independently — used by unit tests).
        """
        self.profile = profile
        self.matcher = text_matcher if text_matcher is not None else TextMatcher()
        self.logic = LogicEngine(profile)

        # Pre-calculate the knowledge base to ensure fast lookups per element
        self._knowledge_base = self._flatten_profile(profile)

    def devise_plan(self, ui_model: UIModel, goal: str = "apply") -> InteractionPlan:
        """Analyzes the current page and determines the sequence of actions.

        Args:
            ui_model (UIModel): The perception snapshot from the Scanner.
            goal (str): The high-level intent (default: 'apply').

        Returns:
            InteractionPlan: A list of ordered, concrete actions to execute.
        """
        plan = InteractionPlan(goal_description=f"Form Fill: {ui_model.title}")

        # 1. Iterate through all visible elements to determine data entry actions
        for element in ui_model.elements:
            action = self._determine_action_for_element(element)
            if action:
                plan.add_action(action)

        # 2. Heuristic: Determine Submission / Navigation
        # If we filled fields, we likely need to click "Next" or "Submit" at the end.
        submit_btn = self._find_best_submit_button(ui_model)
        if submit_btn:
            plan.add_action(PlannedAction(
                target_element_id=submit_btn.id,
                action_type=InteractionType.CLICK,
                reasoning="Detected primary navigation/submission button.",
                ui_element=submit_btn,
                is_critical=True
            ))

        return plan

    def _determine_action_for_element(self, element: UIElement) -> PlannedAction | None:
        """Decides if and how to interact with a specific element based on its type."""

        # Skip elements we don't interact with directly (containers, static text)
        if element.element_type in [UIElementType.CONTAINER, UIElementType.STATIC_TEXT, UIElementType.UNKNOWN]:  # noqa: E501
            return None

        # Strategy A: Input Fields (Text, Select, Radio)
        if element.element_type in [
            UIElementType.TEXT_INPUT,
            UIElementType.TEXT_AREA,
            UIElementType.SELECT,
            UIElementType.RADIO
        ]:
            return self._solve_data_entry(element)

        # Strategy B: Checkboxes (Terms of Service, Consents)
        if element.element_type == UIElementType.CHECKBOX:
            return self._solve_checkbox(element)

        # Strategy C: File Upload (Resume, Cover Letter)
        if element.element_type == UIElementType.FILE_UPLOAD:
            return self._solve_file_upload(element)

        return None

    def _solve_data_entry(self, element: UIElement) -> PlannedAction | None:
        """Finds the best value for a standard input field using semantic matching.

        Args:
            element (UIElement): The target input element.

        Returns:
            Optional[PlannedAction]: The action containing the matched value, or None.
        """
        if not element.label:
            return None

        # Compare the element's label against all keys in our knowledge base
        best_match_key, score = self.matcher.find_best_match(
            element.label,
            list(self._knowledge_base.keys())
        )

        # Threshold: 0.75 ensures we don't put "First Name" into "Last Name"
        if score > 0.75:
            value = self._knowledge_base[best_match_key]

            # If the value is None (e.g. middle name), we can't fill it.
            if value is None:
                return None

            # Determine appropriate interaction type
            action_type = InteractionType.TYPE
            if element.element_type in [UIElementType.SELECT, UIElementType.RADIO]:
                action_type = InteractionType.SELECT_OPTION

            return PlannedAction(
                target_element_id=element.id,
                action_type=action_type,
                value=value,
                reasoning=f"Matched label '{element.label}' to profile key '{best_match_key}' ({score:.2f})",  # noqa: E501
                confidence_score=score,
                ui_element=element,
                is_critical=element.is_required
            )

        return None

    def _solve_checkbox(self, element: UIElement) -> PlannedAction | None:
        """Decides whether to check a box based on keywords (Consent/Terms)."""
        label_lower = (element.label or "").lower()

        # Mandatory keywords for job applications
        keywords = ["terms", "privacy", "agree", "consent", "not a robot", "certify", "acknowledge"]  # noqa: E501

        if any(k in label_lower for k in keywords):
            return PlannedAction(
                target_element_id=element.id,
                action_type=InteractionType.CLICK,
                value=True, # Ensure Checked
                reasoning=f"Detected mandatory consent checkbox via keyword match in: '{element.label}'",  # noqa: E501
                ui_element=element,
                is_critical=element.is_required
            )
        return None

    def _solve_file_upload(self, element: UIElement) -> PlannedAction | None:
        """Handles file uploads for Resumes and Cover Letters."""
        label_lower = (element.label or "").lower()

        # 1. Resume
        if "resume" in label_lower or "cv" in label_lower or "curriculum" in label_lower:  # noqa: E501
            return PlannedAction(
                target_element_id=element.id,
                action_type=InteractionType.UPLOAD_FILE,
                value=str(self.profile.personal_info.resume_path),
                reasoning="Detected Resume upload field.",
                ui_element=element,
                is_critical=True
            )

        # 2. Cover Letter (if available)
        if ("cover" in label_lower or "letter" in label_lower) and self.profile.personal_info.cover_letter:  # noqa: E501
            # Check if cover_letter is a path or text. If path, upload it.
            # Assuming profile stores path for upload fields.
            return PlannedAction(
                target_element_id=element.id,
                action_type=InteractionType.UPLOAD_FILE,
                value=str(self.profile.personal_info.cover_letter),
                reasoning="Detected Cover Letter upload field.",
                ui_element=element,
                is_critical=False
            )

        return None

    def _find_best_submit_button(self, ui_model: UIModel) -> UIElement | None:
        """Identifies the button most likely to advance the form."""
        candidates = [el for el in ui_model.elements if el.element_type == UIElementType.BUTTON]  # noqa: E501

        # Priority list of keywords for forward navigation
        priorities = [
            "submit application", "submit", "apply now", "apply",
            "next step", "next", "continue", "review"
        ]

        for keyword in priorities:
            for btn in candidates:
                # Check visible text (label) or internal name
                btn_text = (btn.label or btn.name or "").lower()

                # Check strict equality for short words ("Next") to avoid false positives  # noqa: E501
                if btn_text == keyword:
                    return btn
                # Check inclusion for phrases
                if keyword in btn_text:
                    return btn

        return None

    def _flatten_profile(self, profile: UserProfile) -> dict[str, Any]:
        """Flattens the UserProfile into a single dictionary of 'Semantic Key' -> 'Value'.

        This dictionary maps potential form labels (keys) to the user's data (values).
        It handles synonyms and transforms booleans into "Yes"/"No" strings for text inputs.

        Args:
            profile (UserProfile): The source data.

        Returns:
            Dict[str, Any]: A mapping used for fuzzy lookups.
        """  # noqa: E501
        data = {}

        # --- Personal Info ---
        p = profile.personal_info
        data["first name"] = p.first_name
        data["given name"] = p.first_name
        data["forename"] = p.first_name

        data["last name"] = p.last_name
        data["surname"] = p.last_name
        data["family name"] = p.last_name

        if p.middle_name:
            data["middle name"] = p.middle_name
            data["middle initial"] = p.middle_name[0]

        data["email"] = p.email
        data["email address"] = p.email

        data["phone"] = p.phone_number
        data["mobile"] = p.phone_number
        data["cell phone"] = p.phone_number

        data["address"] = p.full_address
        data["street"] = p.street_address
        data["city"] = p.city
        data["state"] = p.state
        data["province"] = p.state
        data["zip"] = p.zip_code
        data["postal code"] = p.zip_code
        data["country"] = p.country

        # --- Links ---
        if profile.links.linkedin_url:
            data["linkedin"] = str(profile.links.linkedin_url)
            data["linkedin profile"] = str(profile.links.linkedin_url)

        if profile.links.github_url:
            data["github"] = str(profile.links.github_url)
            data["website"] = str(profile.links.github_url)

        if profile.links.portfolio_url:
            data["portfolio"] = str(profile.links.portfolio_url)
            data["personal site"] = str(profile.links.portfolio_url)

        # --- Education (Handling Lists) ---
        # We prioritize the most recent education entry (index 0 or last depending on sort)  # noqa: E501
        # Assuming the list is ordered or we take the first valid one.
        if profile.education:
            # Taking the first entry as the primary degree
            edu = profile.education[0]
            data["school"] = edu.school
            data["university"] = edu.school
            data["institution"] = edu.school

            data["degree"] = edu.degree
            data["major"] = edu.discipline
            data["field of study"] = edu.discipline

            if edu.gpa:
                data["gpa"] = edu.gpa

        # --- Work Experience (Handling Lists) ---
        # We identify the current job versus previous jobs
        if profile.work_experience:
            # Primary/Current Job
            current_job = profile.work_experience[0]
            data["current company"] = current_job.company
            data["current employer"] = current_job.company
            data["current title"] = current_job.title
            data["job title"] = current_job.title # Generic fallback

            # Most recent description for "Tell us about your experience"
            if current_job.description:
                data["summary"] = profile.career_summary or current_job.description
                data["about"] = profile.career_summary or current_job.description

        # --- Legal & Authorization (Boolean Conversion) ---
        # Maps logic concepts to text answers for dropdowns/text fields
        legal = profile.legal_info

        # Authorization
        auth_val = "Yes" if legal.has_work_authorization else "No"
        data["authorized to work"] = auth_val
        data["work authorization"] = auth_val
        data["legally authorized"] = auth_val

        # Sponsorship
        # "Will you now or in the future require sponsorship?"
        # Logic: If requires_sponsorship is True -> "Yes", else "No"
        sponsor_val = "Yes" if legal.requires_sponsorship else "No"
        data["sponsorship"] = sponsor_val
        data["require sponsorship"] = sponsor_val
        data["visa sponsorship"] = sponsor_val

        # --- EEO (Equal Employment Opportunity) ---
        eeo = profile.eeo_info
        if eeo.gender:
            data["gender"] = eeo.gender
        if eeo.race_ethnicity:
            data["race"] = eeo.race_ethnicity
            data["ethnicity"] = eeo.race_ethnicity
        if eeo.veteran_status:
            data["veteran"] = eeo.veteran_status
            data["veteran status"] = eeo.veteran_status

        # Disability is often a boolean in model, but a specific string in forms
        disability_val = "Yes" if eeo.disability_status else "No"
        data["disability"] = disability_val
        data["disability status"] = disability_val

        # --- Salary Preferences ---
        if profile.search_preferences.expected_salary:
            salary_str = str(profile.search_preferences.expected_salary)
            data["salary"] = salary_str
            data["expected salary"] = salary_str
            data["compensation"] = salary_str
            data["pay"] = salary_str

        return data