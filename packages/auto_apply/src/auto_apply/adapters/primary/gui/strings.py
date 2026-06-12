"""User Interface text resources — driven by the i18n service.

All user-facing strings are loaded from resources/locales/*.json via the
application i18n service. This module exposes a single get_strings() function
that callers use to obtain a flat dict of UI labels for the active locale.

Locale detection order:
    1. Explicit lang_code argument.
    2. OS locale (via i18n.configure_locale auto-detection).
    3. English fallback if the locale file is unavailable.
"""

from auto_apply.application.services.i18n import configure_locale, get_text


def get_strings(lang_code: str | None = None) -> dict[str, str]:
    """Returns a flat dict of UI labels for the given locale.

    Args:
        lang_code: ISO 639-1 language code override (e.g. 'es').
                   If None, the OS locale is auto-detected.

    Returns:
        Dict mapping UI label keys to localized strings.
    """
    configure_locale(language=lang_code)
    t = get_text

    return {
        # --- Meta ---
        "app_title": t("app.name"),

        # --- Wizard ---
        "wizard_title": t("gui.wizard_title"),
        "step_1_title": t("gui.step_1_title"),
        "step_2_title": t("gui.step_2_title"),
        "step_3_title": t("gui.step_3_title"),

        # Inputs
        "lbl_job_titles": t("gui.lbl_job_titles"),
        "lbl_location": t("gui.lbl_location"),
        "lbl_paste_links": t("gui.lbl_paste_links"),

        # Filters
        "chk_skip_applied": t("gui.chk_skip_applied"),
        "chk_min_salary": t("gui.chk_min_salary"),
        "chk_throttling": t("gui.chk_throttling"),

        # Strategy
        "lbl_processing_mode": t("gui.lbl_processing_mode"),
        "opt_adaptive": t("gui.opt_adaptive"),
        "opt_collect": t("gui.opt_collect"),
        "opt_stream": t("gui.opt_stream"),
        "chk_headless": t("settings.headless_mode"),

        # Navigation
        "btn_back": t("wizard.btn_back"),
        "btn_next": t("wizard.btn_next"),
        "btn_start": t("dashboard.btn_start"),

        # --- Dashboard ---
        "dashboard_title": t("dashboard.title"),
        "stats_section_title": t("gui.stats_section_title"),
        "log_section_title": t("gui.log_section_title"),
        "status_idle": t("gui.status_idle"),

        # Metrics
        "metric_discovered": t("dashboard.discovered"),
        "metric_vetted": t("dashboard.vetted"),
        "metric_applied": t("dashboard.applied"),
        "metric_failed": t("dashboard.failed"),
    }
