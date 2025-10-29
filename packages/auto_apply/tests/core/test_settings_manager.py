import pytest
import json
from pathlib import Path
from pydantic import ValidationError

from auto_apply.core.settings_manager import SettingsManager
from auto_apply.user_data.user_profile import UserProfile
from auto_apply.exceptions import ProfileConfigurationError

# We use the valid_profile_data fixture defined in tests/conftest.py
# It gives us a consistent, valid dictionary to start with for our tests.

def test_load_valid_profile_successfully(tmp_path: Path, valid_profile_data):
    """
    GIVEN: A valid profile JSON file exists in a 'profiles' directory.
    WHEN: The SettingsManager's `.profile` property is accessed.
    THEN: The UserProfile object should be correctly created and returned.
    """
    # ARRANGE
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    profile_path = profiles_dir / "default_profile.json"
    profile_path.write_text(json.dumps(valid_profile_data))

    # Instantiate the manager. We don't need to mock anything as we're pointing
    # it directly to our temporary file system.
    manager = SettingsManager(profile_name="default_profile")
    # Override the path to point to our temporary directory.
    manager.profiles_dir = profiles_dir
    manager.profile_path = profile_path

    # ACT
    profile = manager.profile

    # ASSERT
    assert isinstance(profile, UserProfile)
    assert profile.full_name == "Bruce Dickinson"
    assert profile.search_preferences.desired_job_titles == ["Software Engineer"]


def test_profile_not_found_raises_error(tmp_path: Path):
    """
    GIVEN: The profile JSON file does not exist.
    WHEN: The SettingsManager's `.profile` property is accessed.
    THEN: A ProfileConfigurationError should be raised.
    """
    # ARRANGE
    manager = SettingsManager(profile_name="non_existent_profile")
    manager.profiles_dir = tmp_path # Point it to an empty temp directory

    # ACT & ASSERT
    with pytest.raises(ProfileConfigurationError, match="not found"):
        _ = manager.profile


def test_invalid_json_raises_error(tmp_path: Path):
    """
    GIVEN: A profile file contains malformed JSON.
    WHEN: The SettingsManager attempts to load it.
    THEN: A ProfileConfigurationError should be raised with a JSON decoding message.
    """
    # ARRANGE
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    profile_path = profiles_dir / "bad.json"
    profile_path.write_text('{"key": "value",}') # Invalid trailing comma

    manager = SettingsManager(profile_name="bad")
    manager.profiles_dir = profiles_dir
    manager.profile_path = profile_path

    # ACT & ASSERT
    with pytest.raises(ProfileConfigurationError, match="Error decoding JSON"):
        _ = manager.profile


def test_profile_with_missing_required_field_raises_validation_error(tmp_path: Path, valid_profile_data):
    """
    GIVEN: A profile file is missing a required Pydantic field (e.g., email).
    WHEN: The SettingsManager attempts to load it.
    THEN: A ProfileConfigurationError should be raised containing the Pydantic validation details.
    """
    # ARRANGE
    import copy
    invalid_data = copy.deepcopy(valid_profile_data)
    del invalid_data["personal_info"]["email"] # Remove a required field

    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    profile_path = profiles_dir / "invalid.json"
    profile_path.write_text(json.dumps(invalid_data))

    manager = SettingsManager(profile_name="invalid")
    manager.profiles_dir = profiles_dir
    manager.profile_path = profile_path

    # ACT & ASSERT
    with pytest.raises(ProfileConfigurationError) as excinfo:
        _ = manager.profile

    # Check that the exception message from our code contains the underlying
    # Pydantic error details, which is great for user feedback.
    error_string = str(excinfo.value)  # The error message from Pydantic is nested. We just need to check for the key parts.
    assert "personal_info -> email" in str(error_string)
    assert "field required" in str(error_string)

def test_lazy_loading_of_profile(mocker, tmp_path: Path):
    """
    GIVEN: A SettingsManager instance.
    WHEN: The `.profile` property is accessed multiple times.
    THEN: The internal `_load_profile` method should only be called once.
    """
    # ARRANGE
    manager = SettingsManager()

    # We will mock the internal _load_profile method directly.
    mock_load = mocker.patch.object(manager, "_load_profile", return_value="PROFILE_LOADED_ONCE")

    # ACT
    # Access the property multiple times
    profile1 = manager.profile
    profile2 = manager.profile
    profile3 = manager.profile

    # ASSERT
    # The expensive load method should have been called only the first time.
    mock_load.assert_called_once()

    # And the returned value should be the same cached object every time.
    assert profile1 == "PROFILE_LOADED_ONCE"
    assert profile2 == "PROFILE_LOADED_ONCE"
    assert profile3 == "PROFILE_LOADED_ONCE"