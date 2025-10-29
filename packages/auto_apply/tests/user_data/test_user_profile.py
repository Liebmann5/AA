import pytest
from pydantic import ValidationError
from auto_apply.user_data.user_profile import UserProfile
import copy
from pathlib import Path

# The `valid_profile_data` fixture is automatically available from conftest.py

def test_valid_profile_loads_successfully(valid_profile_data):
    """
    GIVEN: A dictionary with valid user profile data.
    WHEN: A UserProfile object is created from it.
    THEN: No errors should be raised and the data should be parsed correctly.
    """
    # ARRANGE & ACT
    # No need to use `try...except`, Pydantic will raise an error if validation fails.
    # If this line completes without an error, the test is halfway to passing.
    profile = UserProfile.parse_obj(valid_profile_data)

    # ASSERT
    assert profile.personal_info.first_name == "Bruce"
    assert isinstance(profile.personal_info.resume_path, Path)
    assert profile.personal_info.resume_path.exists()
    assert profile.links.linkedin_url == "https://www.linkedin.com/in/brucedickinson"


def test_missing_required_field_fails_validation(valid_profile_data):
    """
    GIVEN: Profile data missing a required field (e.g., `last_name`).
    WHEN: A UserProfile object is created.
    THEN: A Pydantic ValidationError should be raised.
    """
    # ARRANGE
    invalid_data = copy.deepcopy(valid_profile_data)
    del invalid_data["personal_info"]["last_name"]

    # ACT & ASSERT
    # `pytest.raises` is a context manager that asserts an exception MUST be raised.
    # The test will fail if an exception is NOT raised.
    with pytest.raises(ValidationError) as excinfo:
        UserProfile.parse_obj(invalid_data)

    # Optional: We can inspect the error message to be more specific.
    error_string = str(excinfo.value)
    assert "personal_info -> last_name" in (error_string)
    assert "field required" in (error_string)


def test_invalid_email_fails_validation(valid_profile_data):
    """
    GIVEN: Profile data with a malformed email address.
    WHEN: A UserProfile object is created.
    THEN: A Pydantic ValidationError should be raised for the email field.
    """
    # ARRANGE
    invalid_data = copy.deepcopy(valid_profile_data)
    invalid_data["personal_info"]["email"] = "not-an-email"

    # ACT & ASSERT
    with pytest.raises(ValidationError, match="value is not a valid email address"):
        UserProfile.parse_obj(invalid_data)


# --- Tests for our custom `resume_path` validator ---

def test_resume_path_must_exist(valid_profile_data):
    """
    GIVEN: Profile data with a resume_path that does not exist on the filesystem.
    WHEN: A UserProfile object is created.
    THEN: A ValidationError should be raised with our custom error message.
    """
    # ARRANGE
    invalid_data = copy.deepcopy(valid_profile_data)
    invalid_data["personal_info"]["resume_path"] = "/path/to/a/non_existent_file.pdf"

    # ACT & ASSERT
    # We use `match=` to assert the error message contains a specific string.
    with pytest.raises(ValidationError, match="Resume file not found at path"):
        UserProfile.parse_obj(invalid_data)


def test_resume_path_must_be_a_file(valid_profile_data, tmp_path: Path):
    """
    GIVEN: Profile data with a resume_path that points to a directory.
    WHEN: A UserProfile object is created.
    THEN: A ValidationError should be raised with our custom error message.
    """
    # ARRANGE
    invalid_data = copy.deepcopy(valid_profile_data)
    # tmp_path is a directory, so we point the resume_path to it.
    invalid_data["personal_info"]["resume_path"] = str(tmp_path)

    # ACT & ASSERT
    with pytest.raises(ValidationError, match="The path provided is a directory, not a file"):
        UserProfile.parse_obj(invalid_data)

# --- Tests for Derived Properties ---

def test_full_name_property(valid_profile_data):
    """
    GIVEN: A valid UserProfile object.
    WHEN: The `full_name` property is accessed.
    THEN: It should return the correctly formatted full name.
    """
    # ARRANGE
    # Test case 1: No middle initial
    profile_no_middle = UserProfile.parse_obj(valid_profile_data)

    # Test case 2: With a middle initial
    data_with_middle = copy.deepcopy(valid_profile_data)
    data_with_middle["personal_info"]["middle_initial"] = "P"
    profile_with_middle = UserProfile.parse_obj(data_with_middle)

    # ACT & ASSERT
    assert profile_no_middle.full_name == "Bruce Dickinson"
    assert profile_with_middle.full_name == "Bruce P. Dickinson"


def test_signature_property(valid_profile_data):
    """
    GIVEN: A valid UserProfile object.
    WHEN: The `signature` property is accessed.
    THEN: It should return the first and last name.
    """
    # ARRANGE
    profile = UserProfile.parse_obj(valid_profile_data)

    # ACT & ASSERT
    assert profile.signature == "Bruce Dickinson"