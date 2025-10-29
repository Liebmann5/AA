"""Central repository for all user-facing UI strings.

This module provides a simple framework for internationalization (i18n). By
centralizing all user-facing text into dictionaries, the application can be
easily translated into new languages. The UI code should import the `get_strings`
function and retrieve all text from it, rather than using hardcoded strings.

To add a new language:
1.  Copy the `LANG_EN` dictionary and rename it (e.g., `LANG_DE` for German).
2.  Translate all the string values in the new dictionary.
3.  Update the `get_strings` function to recognize the new language code.
"""
import locale

LANG_EN = {
    "app_title": "AutoApply",
    "wizard_title": "Welcome to AutoApply - First-Time Setup",
    "wizard_intro": "It looks like this is your first time! A profile has been created for you.",
    "wizard_instruction": "Please open the file below and fill in your details before proceeding.",
    "wizard_file_path_label": "Your Profile File Path:",
    "wizard_acknowledge_button": "I Have Edited My Profile, Continue",
    # Add more strings as we build the UI
}

LANG_ES = {
    "app_title": "AutoApply",
    "wizard_title": "Bienvenido a AutoApply - Configuración Inicial",
    "wizard_intro": "¡Parece que esta es tu primera vez! Se ha creado un perfil para ti.",
    "wizard_instruction": "Por favor, abre el archivo a continuación y completa tus datos antes de continuar.",
    "wizard_file_path_label": "Ruta de tu Archivo de Perfil:",
    "wizard_acknowledge_button": "He Editado Mi Perfil, Continuar",
    # Translate
}

def get_strings(lang_code: str = None) -> dict:
    """Selects and returns the appropriate language dictionary.

    This function attempts to detect the user's default system language. If a
    translation exists for that language, it returns the corresponding
    dictionary. Otherwise, it defaults to English.

    Args:
        lang_code: An optional language code (e.g., "en_US", "es_ES"). If None,
            it will be auto-detected from the user's operating system locale.

    Returns:
        A dictionary containing all the UI strings for the selected language.
    """
    if lang_code is None:
        try:
            lang_code = locale.getdefaultlocale()[0]
        except Exception:
            lang_code = "en"

    if lang_code.startswith('es'):
        return LANG_ES
    else:
        return LANG_EN