"""Interactive profile creation wizard for first-time users.

Called when PROFILES_DIR contains no user-created .json files (only the
bundled default_profile template). Guides the user through creating a
minimal working profile with the fields AA needs for form filling.

The wizard writes a complete, valid JSON profile to PROFILES_DIR and
returns the path so the caller can load it immediately.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def run_profile_wizard(profiles_dir: Path) -> Path | None:
    """Interactively create a user profile. Returns the path to the new profile.

    Args:
        profiles_dir: Directory where the profile JSON will be saved.

    Returns:
        Absolute Path to the newly created profile file, or None if the user
        exited early (Ctrl+C or EOF).
    """
    print("\n" + "\u2550" * 60)
    print("  Welcome to AutoApply!")
    print("  No profile found. Let's create one now.")
    print("  (Press Ctrl+C at any time to exit)")
    print("\u2550" * 60 + "\n")

    def prompt(question: str, default: str = "", required: bool = False) -> str:
        suffix = f" [{default}]" if default else " (required)" if required else ""
        while True:
            try:
                answer = input(f"  {question}{suffix}: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n\n  Profile creation cancelled.")
                return ""
            if answer:
                return answer
            if default:
                return default
            if not required:
                return ""
            print("  This field is required.")

    print("── Personal Information ─────────────────────────────────────")
    first_name = prompt("First name", required=True)
    if not first_name:
        return None

    last_name    = prompt("Last name", required=True)
    email        = prompt("Email address", required=True)
    phone        = prompt("Phone number")
    linkedin_url = prompt("LinkedIn URL (optional)")
    resume_path  = prompt(
        "Path to your resume PDF",
        default="resume.pdf",
    )
    if resume_path == "resume.pdf":
        print(f"  \u2192 Place your resume at: {profiles_dir / 'resume.pdf'}")

    print()
    print("── Job Search Preferences ───────────────────────────────────")
    job_titles_raw = prompt(
        "Job titles to search for (comma-separated)",
        default="Software Engineer",
    )
    job_titles = [t.strip() for t in job_titles_raw.split(",") if t.strip()]
    location   = prompt("Preferred location (or 'Remote')", default="Remote")

    print()
    print("── Career Summary ──────────────────────────────────────────")
    print("  Write 2-3 sentences about your background.")
    print("  This is used for open-ended form questions.")
    career_summary = prompt("Career summary", required=True)
    if not career_summary:
        return None

    # Build the profile dict — matches UserProfile Pydantic schema
    profile = {
        "profile_name": f"{first_name} {last_name}",
        "personal_info": {
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
            "phone_number": phone,
            "street_address": "",
            "city": "",
            "state": "",
            "zip_code": "",
            "country": "United States",
            "resume_path": resume_path,
        },
        "links": {},
        "education": [],
        "work_experience": [],
        "references": [],
        "legal_info": {
            "requires_sponsorship": False,
            "has_work_authorization": True,
            "non_compete_agreements": [],
        },
        "career_summary": career_summary,
        "search_preferences": {
            "desired_job_titles": job_titles,
            "preferred_locations": [location],
            "skills": [],
            "employment_types": ["full-time"],
            "workplace_types": ["remote", "hybrid"],
        },
        "application_preferences": {},
        "app_config": {
            "preferred_browser": "any",
            "headless_mode": False,
            "daily_application_limit": 50,
            "enable_behavior_humanization": True,
        },
        "politeness_settings": {
            "respect_robots_txt": True,
            "default_delay": 2.0,
        },
        "custom_answer_templates": [],
    }

    if linkedin_url:
        profile["links"]["linkedin"] = linkedin_url

    # Save atomically via temp file
    profiles_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{first_name.lower()}_{last_name.lower()}_profile.json"
    profile_path = profiles_dir / filename

    profile_path.write_text(json.dumps(profile, indent=2), encoding="utf-8")

    print()
    print(f"  \u2713 Profile saved: {profile_path}")
    print()
    print("  Next steps:")
    print(f"  1. Place your resume at: {profiles_dir / resume_path}")
    print(f"  2. Edit {filename} to add work experience and skills")
    print(f"  3. Run AutoApply again to start searching")
    print()

    return profile_path