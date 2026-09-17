"""Contract for profile persistence, as the GUI needs it.

The GUI is a primary adapter. It was importing the concrete
``adapters.secondary.persistence.profile_repository.ProfileRepository`` for its
type annotations — a primary adapter naming a secondary adapter, which is the
one direction hexagonal architecture has no story for: two adapters coupled to
each other with the domain standing to one side.

The methods below are ``ProfileRepository``'s full public surface, so nothing
narrows and the concrete class satisfies this structurally without changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from auto_apply.domain.models.profile import UserProfile


@runtime_checkable
class ProfileRepositoryPort(Protocol):
    """Load, save and enumerate user profiles."""

    storage_dir: Path
    """Directory holding the managed profile files.

    Declared because the CLI reports it back to the user after saving a new
    profile. It is part of the concrete repository's public surface already;
    naming it here keeps the port a complete description of what callers use
    rather than a partial one that forces a cast at the one site that needs it.
    """

    def list_profiles(self) -> list[str]:
        """Return the names of every stored profile."""
        ...

    def load_profile(self, name_or_path: str) -> UserProfile | None:
        """Load and validate a profile by name or path. None if absent."""
        ...

    def save_profile(self, *args: object, **kwargs: object) -> object:
        """Persist a profile.

        Signature intentionally loose: the concrete implementation's keyword
        arguments are still in flux, and pinning them here would make this port
        a second place to edit on every change without adding a guarantee the
        GUI relies on.
        """
        ...

    def import_profile(self, source_path: Path) -> Path:
        """Copy an external profile file into the managed profile directory."""
        ...

    def export_profile(self, name: str, destination_dir: Path, overwrite: bool = False) -> Path:
        """Export a stored profile as plaintext JSON to a user-chosen directory.

        The custody complement of import_profile: a person who can bring a
        profile in can take one away — which matters on a borrowed or library
        machine, where the profile store is not theirs.

        The exported file is plaintext JSON BY DESIGN (portable to any
        machine, any repository, any vault state). The stored profile and its
        encryption state are never touched: the destination may never be
        inside the profile store, the method never writes bytes back to it.

        Returns:
            The written file path.

        Raises:
            ValueError: For a path-traversal name or destination, a
                destination that is not an existing directory, a destination
                inside the profile store, or a profile that cannot be loaded.
            FileExistsError: When the destination file exists and
                ``overwrite`` is False.
        """
        ...

    def delete_profile(self, name: str) -> bool:
        """Remove a stored profile. True if something was deleted."""
        ...
