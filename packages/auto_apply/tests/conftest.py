import pytest
import copy

# This is a special pytest file for defining shared fixtures.

@pytest.fixture(scope="session")
def valid_profile_data() -> dict:
    """
    A session-scoped fixture that provides a valid, baseline user profile
    as a dictionary. The resume_path is set to this file itself, which
    guarantees it exists during the test run.

    Using `scope="session"` means this dictionary is created only once for the
    entire test session, which is slightly more efficient.
    """
    return {
        "personal_info": {
            "first_name": "Bruce",
            "last_name": "Dickinson",
            "email": "bruce@ironmaiden.com",
            "phone_number": "911-555-1980",
            "street_address": "123 Iron Maiden Ave",
            "city": "London",
            "state": "N/A",
            "zip_code": "E10",
            "country": "United Kingdom",
            # This is a great trick: use the path to a file we know exists in the repo.
            "resume_path": __file__
        },
        "links": {
            "linkedin": "https://www.linkedin.com/in/brucedickinson",
            "github": "https://github.com/brucedickinson",
            "portfolio": "https://www.ironmaiden.com"
        },
        "education": [],
        "work_experience": [],
        "eeo_info": {},
        "search_preferences": {
            "desired_job_titles": ["Software Engineer"]
        }
    }