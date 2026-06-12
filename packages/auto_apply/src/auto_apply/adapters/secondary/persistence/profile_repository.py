"""Manages the persistence, retrieval, and lifecycle of User Profiles.

This module is the single Data Access Layer for user configuration. It owns:
    - First-run detection and template seeding
    - Atomic writes (crash-safe saves)
    - Optional AES-256 encryption via DataVault
    - Full Pydantic v2 validation on every load
    - Graceful degradation: encrypted → plain JSON → None (never crashes the app)

Encryption contract:
    - No password supplied  → vault is None → plain JSON only
    - Password supplied     → vault encrypts saves and decrypts loads
    - Password wrong        → load returns None, caller decides what to do
    - Unencrypted legacy file opened with a vault → falls back to plain JSON
      (allows migrating existing installs to encryption without data loss)
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from auto_apply.adapters.secondary.security.data_protection import DataVault
from auto_apply.domain.config import PROFILES_DIR
from auto_apply.domain.models.profile import UserProfile
from auto_apply.resources.assets_manager import AssetsManager

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class ProfileRepository:
    """The single source of truth for reading and writing UserProfile objects.

    All filesystem interaction for profiles goes through this class — nothing
    else in the codebase should read or write profile JSON directly.

    Thread safety: each instance owns its own DataVault and file handles.
    Do not share a single instance across threads without external locking.
    """

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(
        self,
        storage_dir: Path = PROFILES_DIR,
        master_password: str | None = None,
    ) -> None:
        """Initialise the repository.

        Args:
            storage_dir:     Directory where .json profile files are stored.
                             Defaults to the portable PROFILES_DIR from config.
            master_password: Optional AES-256 password. Pass None (or empty
                             string) to skip encryption entirely.
        """
        self.storage_dir = storage_dir

        # Empty string == no password == no vault
        self.vault: DataVault | None = (
            DataVault(master_password=master_password, storage_dir=storage_dir)
            if master_password
            else None
        )

        self._ensure_storage_ready()

    # ------------------------------------------------------------------
    # Storage bootstrap
    # ------------------------------------------------------------------

    def _ensure_storage_ready(self) -> None:
        """Create the profile directory and seed a template on first run."""
        try:
            self.storage_dir.mkdir(parents=True, exist_ok=True)
            if not any(self.storage_dir.glob("*.json")):
                logger.info("First run detected: seeding default profile template.")
                self._seed_default_profile()
        except Exception as exc:
            logger.critical("ProfileRepository: storage init failed: %s", exc)
            raise RuntimeError(
                f"Could not initialise profile storage at {self.storage_dir}"
            ) from exc

    def _seed_default_profile(self) -> None:
        """Copy the bundled template asset into storage, or write a minimal fallback."""
        destination = self.storage_dir / "default_profile.json"
        try:
            template_source = AssetsManager.get_template_path()
            if template_source.exists():
                shutil.copy(template_source, destination)
                logger.info("Created default profile at: %s", destination)
            else:
                logger.warning("Template asset missing — writing minimal fallback.")
                self._write_fallback_profile(destination)
        except Exception as exc:
            logger.error("Failed to seed default profile: %s", exc)

    def _write_fallback_profile(self, destination: Path) -> None:
        """Write a hard-coded minimal profile when the template asset is absent."""
        minimal: dict = {
            "profile_name": "Default",
            "personal_info": {
                "first_name": "New",
                "last_name": "User",
                "email": "user@example.com",
                "phone_number": "555-0199",
                "street_address": "Unknown",
                "city": "Unknown",
                "state": "Unknown",
                "zip_code": "00000",
                "resume_path": str(Path.home()),
            },
            "links": {},
            "career_summary": "Please update this profile.",
            "search_preferences": {
                "desired_job_titles": ["Software Engineer"],
            },
        }
        with open(destination, "w", encoding="utf-8") as fh:
            json.dump(minimal, fh, indent=2)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_profiles(self) -> list[str]:
        """Return sorted profile names (stems) for all .json files in storage."""
        try:
            return sorted(f.stem for f in self.storage_dir.glob("*.json"))
        except Exception as exc:
            logger.error("Failed to list profiles: %s", exc)
            return []

    def load_profile(self, name_or_path: str) -> UserProfile | None:
        """Load and validate a profile by name or absolute path.

        Load order:
            1. If a vault is active  → try AES-256 decryption first.
            2. Fallback              → parse as plain JSON (handles templates
                                       and legacy unencrypted files).
            3. Either path           → validate through Pydantic before returning.

        Returns None (never raises) so callers can always do a simple None check.
        """
        target_path = self._resolve_path(name_or_path)
        if target_path is None:
            return None

        raw_bytes = self._read_file(target_path)
        if raw_bytes is None:
            return None

        profile_dict = self._deserialise(raw_bytes, target_path)
        if profile_dict is None:
            return None

        return self._validate(profile_dict, name_or_path)

    def save_profile(
        self,
        profile: UserProfile,
        target_path: Path | None = None,
    ) -> Path:
        """Persist a profile to disk with atomic write guarantees.

        The file is written to a temp path first and then renamed — if the
        process is killed mid-write the original file is never corrupted.

        Returns the absolute path to the saved file.
        Raises OSError if the write fails (callers should show an error dialog).
        """
        destination = target_path or (
            self.storage_dir / f"{profile.profile_name}.json"
        )

        try:
            if self.vault:
                payload = profile.model_dump(by_alias=True)
                self._atomic_write_bytes(destination, self.vault.encrypt_dict(payload))
            else:
                self._atomic_write_text(
                    destination,
                    profile.model_dump_json(indent=2, by_alias=True),
                )
            logger.info("Profile saved: %s", destination.name)
            return destination
        except Exception as exc:
            logger.error("Failed to save profile '%s': %s", profile.profile_name, exc)
            raise OSError(f"Could not save profile: {exc}") from exc

    def import_profile(self, source_path: Path) -> Path:
        """Import an external profile file into local storage after validation.

        Raises:
            FileNotFoundError: if the source file does not exist.
            ValueError:        if the file is not a valid UserProfile.
        """
        if not source_path.exists():
            raise FileNotFoundError(f"Source file not found: {source_path}")
        try:
            profile = UserProfile.model_validate_json(
                source_path.read_text(encoding="utf-8")
            )
        except Exception as exc:
            raise ValueError(f"Invalid profile format: {exc}") from exc
        return self.save_profile(profile)

    def delete_profile(self, name: str) -> bool:
        """Delete a profile by name.

        Returns True if deleted, False if the file was not found.
        Refuses to delete 'default_profile' to preserve the template.
        """
        if name == "default_profile":
            logger.warning("Refusing to delete the default_profile template.")
            return False
        target = self.storage_dir / f"{name}.json"
        if not target.exists():
            logger.warning("Delete requested for non-existent profile: %s", name)
            return False
        try:
            target.unlink()
            logger.info("Profile deleted: %s", name)
            return True
        except Exception as exc:
            logger.error("Failed to delete profile '%s': %s", name, exc)
            return False

    # ------------------------------------------------------------------
    # Private helpers — path resolution
    # ------------------------------------------------------------------

    def _resolve_path(self, name_or_path: str) -> Path | None:
        """Turn a name ('john') or path string into an absolute Path, or None."""
        candidate = Path(name_or_path)

        # Already an absolute path with .json extension
        if candidate.is_absolute() and candidate.suffix == ".json":
            resolved = candidate
        # Name without extension
        elif candidate.suffix != ".json":
            resolved = self.storage_dir / f"{name_or_path}.json"
        # Relative .json path
        else:
            resolved = self.storage_dir / candidate

        if not resolved.exists():
            logger.error("Profile not found: %s", resolved)
            return None
        return resolved

    # ------------------------------------------------------------------
    # Private helpers — deserialisation
    # ------------------------------------------------------------------

    def _read_file(self, path: Path) -> bytes | None:
        """Read raw bytes from a path, returning None on any IO error."""
        try:
            return path.read_bytes()
        except Exception as exc:
            logger.error("Could not read profile file '%s': %s", path, exc)
            return None

    def _deserialise(self, raw_bytes: bytes, source: Path) -> dict | None:
        """Convert raw bytes to a dict.

        Tries vault decryption first (if active), then plain JSON.
        Returns None only if both attempts fail — which means the file is
        genuinely corrupt or was encrypted with a different password.
        """
        # --- Attempt 1: vault decryption ---
        if self.vault:
            try:
                return self.vault.decrypt_dict(raw_bytes)
            except Exception:
                logger.debug(
                    "Vault decryption failed for '%s' — trying plain JSON.", source.name
                )

        # --- Attempt 2: plain JSON ---
        try:
            return json.loads(raw_bytes.decode("utf-8"))
        except Exception as exc:
            logger.error(
                "Profile '%s' could not be parsed as JSON: %s", source.name, exc
            )
            return None

    def _validate(self, data: dict, label: str) -> UserProfile | None:
        """Run Pydantic validation on a raw dict, returning None on failure."""
        try:
            return UserProfile(**data)
        except Exception as exc:
            logger.error("Profile '%s' failed validation: %s", label, exc)
            return None

    # ------------------------------------------------------------------
    # Private helpers — atomic writes
    # ------------------------------------------------------------------

    def _atomic_write_text(self, target: Path, content: str) -> None:
        """Write a string to target atomically (temp file → rename)."""
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp", text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(content)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, target)
        except Exception:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise

    def _atomic_write_bytes(self, target: Path, content: bytes) -> None:
        """Write bytes to target atomically (temp file → rename)."""
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(content)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, target)
        except Exception:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise