"""The main application class for the Tkinter GUI.

This module defines the `AutoApplyApp`, which inherits from `tkinter.Tk` to
create the main application window. It is the root of the GUI and is
responsible for setting the window's initial properties and orchestrating the
first-run setup process.
"""
import tkinter as tk
from tkinter import ttk

from .strings import get_strings
from .wizard import SetupWizard
from ..core.first_run_setup import check_and_run_setup, DEFAULT_PROFILE_PATH

class AutoApplyApp(tk.Tk):
    """The main window and root controller for the AutoApply GUI application.

    This class sets up the main application frame, manages its initial state,
    and handles the critical first-run setup by launching the `SetupWizard`
    if the user's profile has not yet been configured.
    """

    def __init__(self):
        """Initializes the main application window."""
        super().__init__()
        self.strings = get_strings()
        self.title(self.strings['app_title'])
        self.geometry("600x400")

        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        welcome_label = ttk.Label(main_frame, text="Welcome to AutoApply!", font=("-size", 16))
        welcome_label.pack(pady=20)

        start_button = ttk.Button(main_frame, text="Start Applying to Jobs")
        start_button.pack(pady=20)

        self.eval('tk::PlaceWindow . center')

        self.after(100, self.perform_initial_setup)

    def perform_initial_setup(self) -> None:
        """Checks if the application is configured and launches the setup wizard if not.

        This method is called shortly after the main window is initialized. It
        uses the core `check_and_run_setup` function to determine if a profile
        exists. If setup is required, it creates and displays the modal
        `SetupWizard` dialog, pausing the user's interaction with the main
        app until the wizard is completed.
        """
        if not check_and_run_setup():
            SetupWizard(self, str(DEFAULT_PROFILE_PATH.resolve()))