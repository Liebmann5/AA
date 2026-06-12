"""Manages access to static internal assets bundled with the package.

This module abstracts the file system location of resources like default
profiles and templates, ensuring they can be found even when the application
is installed as a package or compiled into an executable.
"""

import json
from importlib import resources
from pathlib import Path
from typing import Any


class AssetsManager:
    """Provides access to bundled package data."""

    @staticmethod
    def get_template_path() -> Path:
        """Returns the path to the template_profile.json file."""
        # Note: Accessing resources relative to the templates package
        # 'auto_apply.resources.templates' needs to exist as a python package (with __init__.py)  # noqa: E501
        # or we treat it as data files.
        # Assuming modern python 3.9+ structure:
        files = resources.files('auto_apply.resources.templates')
        return Path(str(files / "template_profile.json"))

    @staticmethod
    def load_template_profile() -> dict[str, Any]:
        """Reads and returns the default profile template as a dictionary."""
        path = AssetsManager.get_template_path()
        if not path.exists():
            raise FileNotFoundError(f"Template profile not found at {path}")

        with open(path, encoding='utf-8') as f:
            return json.load(f)
