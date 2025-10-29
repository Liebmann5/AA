"""
Manages the loading and validation of application settings and user profiles.

This acts as the single source of truth for all configuration during runtime.
It is responsible for loading a specified user profile from a JSON file,
validating its contents against the UserProfile model, and making it
accessible to the rest of the application.
"""
import os
import json
from pathlib import Path
from typing import Optional

from pydantic import ValidationError
from ..user_data.user_profile import UserProfile
from ..exceptions import ProfileConfigurationError

from importlib import resources


class SettingsManager:
    """Handles loading and providing access to the active user profile."""

    def __init__(self, profile_name: str = "default_profile"):
        self.profile_name = profile_name
        self._active_profile: Optional[UserProfile] = None
        self.profiles_dir = Path(str(resources.files('auto_apply') / 'profiles'))
        self.profile_path = self.profiles_dir / f"{self.profile_name}.json"

    def _load_profile(self) -> UserProfile:
        """Loads and validates the user profile from itsJSON file."""
        if not self.profile_path.exists():
            raise ProfileConfigurationError(
                f"Profile '{self.profile_name}.json' not found in {self.profiles_dir}."
                "\nPlease ensure the file exists."
            )

        try:
            with open(self.profile_path, 'r', encoding='utf-8') as f:
                profile_data = json.load(f)
            return UserProfile.parse_obj(profile_data)
        except json.JSONDecodeError as e:
            raise ProfileConfigurationError(
                f"Error decoding JSON from {self.profile_path}."
                f"Please check for syntax errors. Details: {e}"
            )
        except ValidationError as e:
            raise ProfileConfigurationError(
                f"Profile data in {self.profile_path} is invalid.\n"
                f"Please correct the following errors:\n{e}"
            )

    @property
    def profile(self) -> UserProfile:
        """
        Public property to access the active user profile.
        Loads the profile on first access (lazy loading).
        """
        if self._active_profile is None:
            self._active_profile = self._load_profile()
        return self._active_profile