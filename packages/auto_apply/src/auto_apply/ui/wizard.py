"""Provides the graphical first-run setup wizard for the application.

This module contains the `SetupWizard`, a Tkinter `Toplevel` window that
guides new users through the initial configuration of their profile.
"""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import subprocess
import sys
import os
import json
from pathlib import Path
from .strings import get_strings

class SetupWizard(tk.Toplevel):
    """A modal dialog that guides the user through the first-time setup process.

    This window appears on the first run of the application. It informs the user
    that a profile has been created, shows them where it is, and provides tools
    to help them edit it (e.g., setting the resume path) before they can
    proceed to the main application.
    """

    def __init__(self, parent, profile_path: str):
        """Initializes the modal setup wizard window.

        Args:
            parent: The parent window (the main `AutoApplyApp` instance).
            profile_path: The absolute string path to the user's profile JSON file.
        """
        super().__init__(parent)
        self.profile_path = profile_path
        self.strings = get_strings()
        self.transient(parent)
        self.title(self.strings['wizard_title'])

        main_frame = ttk.Frame(self, padding="10 10 10 10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        intro_label = ttk.Label(main_frame, text=self.strings['wizard_intro'], wraplength=400)
        intro_label.grid(row=0, column=0, columnspan=2, pady=5)

        instruction_label = ttk.Label(main_frame, text=self.strings['wizard_instruction'], wraplength=400, font="-weight bold")
        instruction_label.grid(row=1, column=0, columnspan=2, pady=10)

        path_label = ttk.Label(main_frame, text=self.strings['wizard_file_path_label'])
        path_label.grid(row=2, column=0, sticky=tk.W, pady=5)

        path_entry = ttk.Entry(main_frame, width=60)
        path_entry.insert(0, self.profile_path)
        path_entry.config(state='readonly')
        path_entry.grid(row=3, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)

        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=4, column=0, columnspan=2, sticky=tk.E, pady=10)

        open_button = ttk.Button(button_frame, text="Open Profile to Edit", command=self._open_profile_file)
        open_button.pack(side=tk.LEFT, padx=5)

        resume_button = ttk.Button(button_frame, text="Set Resume Path...", command=self._set_resume_path)
        resume_button.pack(side=tk.LEFT, padx=5)

        continue_button = ttk.Button(button_frame, text=self.strings['wizard_acknowledge_button'], command=self.destroy)
        continue_button.pack(side=tk.LEFT, padx=5)

        self.grab_set()
        self.wait_window(self)

    def _set_resume_path(self) -> None:
        """Opens a file dialog to select a resume and updates the profile JSON.

        This is a user-friendly helper function. It opens a native file selection
        dialog, allowing the user to browse for their resume. If a file is
        selected, it reads the existing profile JSON, updates the `resume_path`
        field with the correct, normalized path, and writes the data back to the file.
        """
        filepath = filedialog.askopenfilename(
            title="Select Your Resume",
            filetypes=(("PDF Files", "*.pdf"), ("All files", "*.*"))
        )
        if not filepath:
            return

        try:
            with open(self.profile_path, 'r', encoding='utf-8') as f:
                profile_data = json.load(f)

            normalized_path = Path(filepath).as_posix()
            profile_data['personal_info']['resume_path'] = normalized_path

            with open(self.profile_path, 'w', encoding='utf-8') as f:
                json.dump(profile_data, f, indent=2)

            messagebox.showinfo("Success", f"Resume path has been updated in your profile:\n\n{normalized_path}")

        except (IOError, json.JSONDecodeError, KeyError) as e:
            messagebox.showerror("Error", f"Could not update the profile file.\nPlease edit it manually.\n\nError: {e}")

    def _open_profile_file(self) -> None:
        """Opens the profile file in the user's default system text editor.

        This function uses a cross-platform approach to open the profile file,
        making it easy for the user to edit their details without having to
        manually find the file on their system.
        """
        try:
            if sys.platform == "win32":
                os.startfile(self.profile_path)
            elif sys.platform == "darwin":
                subprocess.call(["open", self.profile_path])
            else:
                subprocess.call(["xdg-open", self.profile_path])
        except Exception as e:
            messagebox.showerror("Error", f"Could not open the file automatically.\nPlease open it manually.\n\nError: {e}")

    def get_resume_path():
        """A standalone utility function to open a file dialog for selecting a resume.

        This function creates a temporary, hidden Tkinter root window, displays a
        native file selection dialog, and then destroys the root window. It is a
        self-contained way to get a file path from the user graphically without
        needing a full, pre-existing GUI application.

        Returns:
            The absolute string path to the selected file, or an empty string if
            the user cancels the dialog.
        """
        root = tk.Tk()
        root.withdraw()

        file_path = filedialog.askopenfilename(title="Select your resume")
        root.destroy()

        if not file_path:
            return ""

        return str(Path(file_path).resolve())