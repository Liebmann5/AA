"""Defines the application's runtime configuration and static paths.

This module uses Pydantic to validate settings loaded from environment variables
or defaults. It also defines the static filesystem paths used for persistence.

This module detects if the application is running frozen (as an .exe on a USB).
If so, it forces data storage to be relative to the executable, preventing data
leaks onto the host library computer. (Portable mode)
{Crucially, it implements "Portable Path Detection" to ensure that when running
from a Flash Drive (compiled state), all data is stored relative to the
executable, not in the host user's home directory.}

Four run modes (resolved by ``get_run_mode()``):
    portable-frozen   — PyInstaller .exe; data lives next to the executable
    portable-source   — Python source on a USB drive (PORTABLE marker file present)
    env-override      — ``AA_DATA_DIR`` env var explicitly set
    development       — normal dev; data in ``dev_data/`` at project root
"""

import os
import sys
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# ═════════════════════════════════════════════════════════════════════════════
# PORTABILITY DETECTION
# ═════════════════════════════════════════════════════════════════════════════

IS_FROZEN: bool = getattr(sys, "frozen", False)
"""True when running as a PyInstaller-compiled executable."""


def get_app_root() -> Path:
    """The directory that "owns" the AA installation.

    - Frozen:    the folder containing ``AutoApply.exe``
    - Source:    the ``src/auto_apply`` package directory (2 levels up from this file)
    """
    if IS_FROZEN:
        return Path(sys.executable).parent
    # __file__ → domain/config.py → domain/ → auto_apply/ → src/
    return Path(__file__).resolve().parent.parent


APP_ROOT: Path = get_app_root()


def _resolve_portable_root() -> Path | None:
    """Detect if running from a USB drive in source mode.

    Walks up from ``APP_ROOT`` looking for a ``PORTABLE`` marker file (an empty
    plain-text file with no extension). If found, returns the directory
    containing it — the USB drive root.

    Returns ``None`` if no marker is found within 6 levels of ``APP_ROOT``.

    Example USB drive layout::

        E:\\
        ├── PORTABLE                  ← marker
        ├── AA\\                       ← source code
        │   └── packages\\...
        └── data\\                    ← data (created automatically)
    """
    search = APP_ROOT
    for _ in range(6):
        if (search / "PORTABLE").exists():
            return search
        parent = search.parent
        if parent == search:
            break
        search = parent
    return None


def _determine_user_data_dir() -> Path:
    """Resolve ``USER_DATA_DIR`` using the environment-aware priority chain.

    Priority (highest wins):
        1. ``AA_DATA_DIR`` env var — explicit override set by launcher scripts
        2. Frozen mode — ``data/`` next to the executable
        3. Source-mode USB — ``data/`` at the ``PORTABLE`` marker root
        4. Development — ``dev_data/`` at the project root
    """
    # Priority 1: explicit env var (set by launch_portable.bat / .sh)
    env_data = os.environ.get("AA_DATA_DIR")
    if env_data:
        return Path(env_data)

    # Priority 2: frozen (PyInstaller) — always portable
    if IS_FROZEN:
        return APP_ROOT / "data"

    # Priority 3: source mode on USB drive (PORTABLE marker file present)
    portable_root = _resolve_portable_root()
    if portable_root is not None:
        return portable_root / "data"

    # Priority 4: normal development
    # config.py → domain/ → auto_apply/ → src/ → auto_apply (package root)
    # dev_data/ sits 2 levels above src/auto_apply
    return APP_ROOT.parent.parent / "dev_data"


# ═════════════════════════════════════════════════════════════════════════════
# DYNAMIC DATA PATHS
# ═════════════════════════════════════════════════════════════════════════════

USER_DATA_DIR: Path = _determine_user_data_dir()
"""Root of all user-specific data. Its location depends on the run mode."""

PROFILES_DIR: Path = USER_DATA_DIR / "profiles"
LOG_DIR: Path = USER_DATA_DIR / "logs"
DB_PATH: Path = USER_DATA_DIR / "aa_data.db"
CHECKPOINTS_DIR: Path = USER_DATA_DIR / "checkpoints"
SCREENSHOTS_DIR: Path = USER_DATA_DIR / "screenshots"
REPORTS_DIR: Path = USER_DATA_DIR / "reports"
RESEARCH_DIR: Path = USER_DATA_DIR / "research"

# Browser profile (Chromium user-data-dir).
# ``USER_DATA_DIR`` env var is set by the launcher to keep the profile on the
# drive rather than under the host user's home directory.
BROWSER_PROFILE_DIR: Path = Path(
    os.environ.get("USER_DATA_DIR", str(USER_DATA_DIR / "cache" / "chromium_profile"))
)

# Temp directory — redirected to drive in portable mode to prevent host
# pollution.  ``TEMP`` / ``TMPDIR`` are set by the launcher scripts.
TEMP_DIR: Path = Path(
    os.environ.get("TEMP")
    or os.environ.get("TMPDIR")
    or os.environ.get("TMP")
    or str(USER_DATA_DIR / "tmp")
)

# ═════════════════════════════════════════════════════════════════════════════
# ENSURE HIERARCHY EXISTS
# ═════════════════════════════════════════════════════════════════════════════

for _d in (
    USER_DATA_DIR,
    PROFILES_DIR,
    LOG_DIR,
    CHECKPOINTS_DIR,
    SCREENSHOTS_DIR,
    REPORTS_DIR,
    RESEARCH_DIR,
    BROWSER_PROFILE_DIR,
    TEMP_DIR,
):
    _d.mkdir(parents=True, exist_ok=True)


# ═════════════════════════════════════════════════════════════════════════════
# MODE DETECTION HELPER
# ═════════════════════════════════════════════════════════════════════════════

def get_run_mode() -> str:
    """Returns a human-readable description of the current run mode.

    One of:
        - ``"portable-frozen"``  — PyInstaller .exe
        - ``"portable-source"``  — source on USB with PORTABLE marker
        - ``"env-override"``     — ``AA_DATA_DIR`` env var set
        - ``"development"``      — normal dev mode
    """
    if IS_FROZEN:
        return "portable-frozen"
    if _resolve_portable_root() is not None:
        return "portable-source"
    if os.environ.get("AA_DATA_DIR"):
        return "env-override"
    return "development"


# ═════════════════════════════════════════════════════════════════════════════
# PYDANTIC SETTINGS (unchanged — kept for backward compatibility)
# ═════════════════════════════════════════════════════════════════════════════

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
