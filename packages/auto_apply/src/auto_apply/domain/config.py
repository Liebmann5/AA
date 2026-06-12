"""Defines the application's runtime configuration and static paths.

This module uses Pydantic to validate settings loaded from environment variables
or defaults. It also defines the static filesystem paths used for persistence.

This module detects if the application is running frozen (as an .exe on a USB).
If so, it forces data storage to be relative to the executable, preventing data
leaks onto the host library computer. (Portable mode)
{Crucially, it implements "Portable Path Detection" to ensure that when running
from a Flash Drive (compiled state), all data is stored relative to the
executable, not in the host user's home directory.}
"""

import sys
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# --- PORTABILITY LOGIC ---
# Detect if we are running as a compiled executable (PyInstaller)
IS_FROZEN = getattr(sys, 'frozen', False)

def get_app_root() -> Path:
    """Determines the root directory of the application context.

    Returns:
        Path: The directory containing the executable (if frozen) or the
              project source root (if in development).
    """
    if IS_FROZEN:
        # USB Mode: Point to the folder containing the .exe
        return Path(sys.executable).parent

    # Dev Mode: Point to the package root (src/auto_apply)
    return Path(__file__).parent.parent

APP_ROOT = get_app_root()

# --- DYNAMIC DATA PATHS ---
# All user data is stored relative to the APP_ROOT to ensure portability.
if IS_FROZEN:
    USER_DATA_DIR = APP_ROOT / "data"
else:
    # In Dev, we still use local folders to keep the environment clean
    USER_DATA_DIR = APP_ROOT.parent.parent / "dev_data"

# Ensure hierarchy exists
PROFILES_DIR = USER_DATA_DIR / "profiles"
LOG_DIR = USER_DATA_DIR / "logs"
DB_PATH = USER_DATA_DIR / "aa_data.db"
CHECKPOINTS_DIR = USER_DATA_DIR / "checkpoints"

# Create directories immediately
USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
PROFILES_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)


class EvasionConfig(BaseModel):
    """Settings for bot-detection evasion and CAPTCHA handling."""
    enable_captcha_detection: bool = True
    on_captcha_detected: str = "stop"  # Options: "stop", "notify", "wait_and_retry"


class AppSettings(BaseSettings):
    """The main application settings model."""

    model_config = SettingsConfigDict(env_prefix="AUTO_APPLY_", case_sensitive=False)

    evasion: EvasionConfig = Field(default_factory=EvasionConfig)

    # Synonyms used for heuristic form filling (First Name -> "given name")
    form_field_synonyms: dict[str, list[str]] = {
        "first_name": ["first name", "given name", "forename"],
        "last_name": ["last name", "surname", "family name"],
        "email": ["email", "email address"],
        "phone": ["phone", "phone number", "mobile number", "cellphone"],
        "resume": ["resume", "cv", "curriculum vitae", "upload resume"],
        "linkedin": ["linkedin", "linkedin profile", "linkedin url"],
        "portfolio": ["portfolio", "website", "personal site"],
    }