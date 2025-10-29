"""
A settings editor widget for the AutoApply UI.

This module contains the `SettingsEditor`, a `ttk.Frame` that provides users
with a simple interface to manage their application settings.
"""
import tkinter as tk
from tkinter import ttk, filedialog
from ..core.settings_manager import SettingsManager

class SettingsEditor(ttk.Frame):
    """A UI frame that provides a button to open the user's profile file.

    Currently, this class provides a simple, direct way for a user to edit
    their settings by opening the `default_profile.json` file in their system's
    default text editor. Future versions could expand this frame to include
    individual widgets for each setting.
    """

    def __init__(self, parent, **kwargs):
        """Initializes the SettingsEditor frame.

        Args:
            parent: The parent tkinter widget that this frame will be placed in.
            **kwargs: Additional keyword arguments to pass to the `ttk.Frame` constructor.
        """
        super().__init__(parent, **kwargs)

        label = ttk.Label(self, text="Your settings are stored in your profile file.")
        label.pack(pady=10)

        edit_button = ttk.Button(self, text="Edit My Profile File", command=self._edit_profile)
        edit_button.pack(pady=10)

    def _edit_profile(self) -> None:
        """A placeholder to demonstrate opening the profile.

        Opens the default profile file in the user's default system editor.

        This function uses a cross-platform approach to open the profile file,
        making it easy for the user to edit their details without having to
        manually find the file on their system. It uses `os.startfile` on
        Windows and the `open` or `xdg-open` command on macOS and Linux,
        respectively.
        """
        from ..core.first_run_setup import DEFAULT_PROFILE_PATH
        import os, subprocess, sys
        try:
            if sys.platform == "win32": os.startfile(DEFAULT_PROFILE_PATH)
            else: subprocess.call(["open" if sys.platform == "darwin" else "xdg-open", DEFAULT_PROFILE_PATH])
        except Exception as e:
            print(f"Error opening profile: {e}")