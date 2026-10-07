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
    managed           — created by ``--install``/the bootstrap; ``AA_MANAGED_ROOT``
                        names the root, data lives at ``<root>/data``
    env-override      — ``AA_DATA_DIR`` env var explicitly set
    development       — normal dev; data in ``dev_data/`` at project root

Import side effects: path CONSTANTS are computed at import; directory
CREATION is not unconditional — it is skipped when ``AA_NO_CREATE_DIRS=1``
(set by main.py's pre-import parse for ``--uninstall``), so the path that
removes the data home never recreates it on the way in. Bootstrap callers
(logging setup, build_session) call :func:`ensure_data_dirs` explicitly.
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

    # Priority 4: managed install (the --install / bootstrap launcher sets
    # AA_MANAGED_ROOT). Explicit AA_DATA_DIR still wins above — the launcher
    # sets both to the same answer.
    managed_root = os.environ.get("AA_MANAGED_ROOT")
    if managed_root:
        return Path(managed_root) / "data"

    # Priority 5: normal development
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

# The ONE research database. The collector (composition_root), the purge
# (SqliteConsentRepository, via injection) and the exporter (main.py) all
# consume this constant; the filename literal is spelled in no other src
# file, and tests/research/test_research_data_home.py pins that.
RESEARCH_DB_PATH: Path = RESEARCH_DIR / "research_signals.db"

# The private Ed25519 research-provenance key. Deliberately OUTSIDE
# RESEARCH_DIR (and REPORTS_DIR): every instruction that tells a user where
# their research data lives names research/, so the key must not be inside
# it — a user who zips "the research folder" to contribute must never ship
# the key that signs their rows.
PROVENANCE_KEY_PATH: Path = USER_DATA_DIR / "provenance_key.pem"

# The private research salt (the company_id HMAC key and the page-copy nonce
# key). Generated by AA when research consent is granted; the
# AA_RESEARCH_SALT environment variable overrides it when set. Beside the
# provenance key for the same reason as the key: private, and outside every
# folder a "share your research data" instruction names.
RESEARCH_SALT_PATH: Path = USER_DATA_DIR / "research_salt.txt"

# Cleaned copies of the job pages AA read (item 6), kept on this device only
# when the person turned page copies on. Inside RESEARCH_DIR, so withdrawing
# from research deletes them with everything else.
PAGE_COPIES_DIR: Path = RESEARCH_DIR / "page_copies"

# Browser profile (Chromium user-data-dir). ``AA_BROWSER_PROFILE_DIR`` wins;
# the legacy ``USER_DATA_DIR`` env var (set by older launchers — a generic
# name that is NOT the USER_DATA_DIR constant above) is still honoured so
# those launchers keep working.
BROWSER_PROFILE_DIR: Path = Path(
    os.environ.get("AA_BROWSER_PROFILE_DIR")
    or os.environ.get("USER_DATA_DIR")
    or str(USER_DATA_DIR / "cache" / "chromium_profile")
)

# Temp directory. AA's own temp root is ALWAYS inside the data home unless
# AA_TEMP_DIR says otherwise. BEHAVIOUR CHANGE (lifecycle work): this used to
# inherit the host's TEMP/TMPDIR/TMP, which meant AA claimed — and mkdir'd,
# and would have enumerated at uninstall — a directory the OS owns. The
# launcher scripts still redirect TEMP/TMPDIR themselves; that governs
# third-party libraries, not this constant.
TEMP_DIR: Path = Path(
    os.environ.get("AA_TEMP_DIR") or str(USER_DATA_DIR / "tmp")
)

# geckodriver's --profile-root for snap-confined Firefox (consumed by
# selenium_provider._create_firefox). Previously ~/.auto_apply — the one
# measured write outside the data home. The legacy location is in the
# uninstaller's discovery list so older installs are still cleaned. On a USB
# drive, snap's removable-media plug governs readability; AA_GECKO_PROFILE_ROOT
# is the escape hatch.
GECKO_PROFILE_ROOT_DIR: Path = Path(
    os.environ.get("AA_GECKO_PROFILE_ROOT")
    or str(USER_DATA_DIR / "cache" / "gecko_profile_root")
)

# Selenium Manager's driver cache, contained in-process so even a direct
# ``python -m auto_apply`` cannot spill drivers into ~/.cache/selenium
# (measured on Lubuntu) — and its usage-statistics phone-home is opted out.
# setdefault, never assignment: an explicit user choice always wins.
SELENIUM_CACHE_DIR: Path = USER_DATA_DIR / "cache" / "selenium"
os.environ.setdefault("SE_CACHE_PATH", str(SELENIUM_CACHE_DIR))
os.environ.setdefault("SE_AVOID_STATS", "1")

# GPT4All model directory — consumed by gpt4all_adapter (model_path=).
GPT4ALL_MODELS_DIR: Path = Path(
    os.environ.get("GPT4ALL_MODELS_DIR") or str(USER_DATA_DIR / "cache" / "gpt4all")
)

# ── Lifecycle roots (the uninstall authority) ──────────────────────────────
# None of these is created at import or by ensure_data_dirs(); each is made
# lazily by its writer, so the uninstall path recreates nothing.
FOOTPRINT_LEDGER_PATH: Path = USER_DATA_DIR / "footprint_ledger.jsonl"
INSTANCES_DIR: Path = USER_DATA_DIR / "instances"
RESEARCH_HOLD_PATH: Path = USER_DATA_DIR / "research_retention.json"

# ═════════════════════════════════════════════════════════════════════════════
# ENSURE HIERARCHY EXISTS
# ═════════════════════════════════════════════════════════════════════════════

CREATION_MARKER_NAME: str = ".aa_created_root"


def ensure_creation_marker(root: Path) -> None:
    """Write the creation tombstone IF (and only if) this call creates *root*.

    The uninstaller removes a root directory wholesale only when it can show
    AA created it; this marker is that proof (the package-receipt precedent:
    pkgutil, MSI). A folder that predates AA never gets one, so a
    pre-existing data folder keeps its owner contents — only AA's own known
    entries inside it are ever removed.
    """
    if root.exists():
        return
    root.mkdir(parents=True, exist_ok=True)
    import json as _json  # noqa: PLC0415
    from datetime import datetime, timezone  # noqa: PLC0415

    (root / CREATION_MARKER_NAME).write_text(
        _json.dumps(
            {
                "created_by": "auto_apply",
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def ensure_data_dirs() -> None:
    """Create the data directory hierarchy. Idempotent.

    Importing this module used to create these nine directories as a side
    effect. That defeats any command whose purpose is to REMOVE the
    hierarchy: the import alone would recreate the data home it is about to
    delete, and a verify-after-delete would find it again. Creation is now a
    function; the legacy import-time call below is kept for every existing
    consumer, and skipped when AA_NO_CREATE_DIRS=1 (the uninstall path).
    """
    ensure_creation_marker(USER_DATA_DIR)
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


if os.environ.get("AA_NO_CREATE_DIRS") != "1":
    ensure_data_dirs()


# ═════════════════════════════════════════════════════════════════════════════
# MODE DETECTION HELPER
# ═════════════════════════════════════════════════════════════════════════════

def get_run_mode() -> str:
    """Returns a human-readable description of the current run mode.

    One of:
        - ``"portable-frozen"``  — PyInstaller .exe
        - ``"portable-source"``  — source on USB with PORTABLE marker
        - ``"managed"``          — ``--install``/bootstrap managed root
        - ``"env-override"``     — ``AA_DATA_DIR`` env var set
        - ``"development"``      — normal dev mode
    """
    if IS_FROZEN:
        return "portable-frozen"
    if _resolve_portable_root() is not None:
        return "portable-source"
    if os.environ.get("AA_MANAGED_ROOT"):
        return "managed"
    if os.environ.get("AA_DATA_DIR"):
        return "env-override"
    return "development"


def get_install_root() -> Path:
    """Best-effort answer to "where is AA installed", by run mode.

    Frozen: the folder holding the executable (the whole folder is AA's
    umbrella, and the uninstaller's finisher removes it after AA exits).
    Managed: ``AA_MANAGED_ROOT`` (the ``--install``/bootstrap launcher sets
    it; the finisher removes that root's AA-created contents after exit).
    Source: the ``packages/auto_apply`` package root — INFORMATIONAL only:
    a source checkout is never deleted by the uninstaller (it is the
    developer's own tree, removed with the developer's own tools).
    """
    if IS_FROZEN:
        return APP_ROOT
    managed = os.environ.get("AA_MANAGED_ROOT")
    if managed:
        return Path(managed)
    # config.py → domain → auto_apply → src → packages/auto_apply
    return Path(__file__).resolve().parents[3]


# ═════════════════════════════════════════════════════════════════════════════
# PYDANTIC SETTINGS (unchanged — kept for backward compatibility)
# ═════════════════════════════════════════════════════════════════════════════

class EvasionConfig(BaseModel):
    """Settings for bot-detection evasion and CAPTCHA handling."""
    enable_captcha_detection: bool = True
    # on_captcha_detected is deleted. It had three definitions (here: "stop";
    # EvasionManager's constructor default: "skip"; runtime_defaults.yaml:
    # "skip") and zero live readers — the retired EvasionManager was its only
    # consumer and returned False identically for every value. Challenge
    # handling is ruled behaviour per path, not a policy: discovery aborts
    # the provider page (D5 gate); the application path pauses in place
    # (gate-crossing ruling A). The YAML key is removed with it.


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
