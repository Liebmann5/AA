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


def _tr(key: str, default: str) -> str:
    """Translate *key*, falling back to *default* when the locale lacks it.

    New settings keys land in the locale resources out of band; until a
    locale file carries them, the UI must still render. Three miss shapes
    are covered: get_text raising, returning "", or echoing the key.
    """
    try:
        value = get_text(key)
    except Exception:
        return default
    return value if value and value != key else default


def locale_text(key: str) -> str:
    """The active locale's text for *key*, or *key* itself when it has none.

    For text the window does not list in get_strings(), such as the query
    builder's note templates: the caller falls back when it gets the key back.
    """
    return _tr(key, key)


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

        # --- Settings: pointer & scroll behaviour (ADR 018, layer 0) ---
        "motion_profile_label": _tr("settings.motion_profile_label", "Pointer & scroll behaviour:"),
        "motion_profile_note": _tr(
            "settings.motion_profile_note",
            "Natural is right for almost everyone. Instant removes all human pacing — use it only for tests.",
        ),
        "motion_option_human": _tr("settings.motion_option_human", "Natural (recommended)"),
        "motion_option_careful": _tr("settings.motion_option_careful", "Careful — slower, hardest to detect"),
        "motion_option_instant": _tr("settings.motion_option_instant", "Instant — no human pacing (tests only)"),
        "motion_profile_locked": _tr(
            "settings.motion_profile_locked",
            "Behaviour profile locked by your System Administrator.",
        ),
        "stealth_driver_label": _tr("settings.stealth_driver_label", "Use stealth browser driver when available"),
        "stealth_driver_note": _tr(
            "settings.stealth_driver_note",
            "Chrome only, needs undetected-chromedriver. Does not change pacing — pacing comes from the behaviour profile above.",
        ),

        # --- Query builder window (File → Build a Search…) ---
        "builder.window_title": _tr("builder.window_title", "Build a Search"),
        "builder.engine_label": _tr("builder.engine_label", "Search engine:"),
        "builder.target_label": _tr("builder.target_label", "Search within:"),
        "builder.target.surface": _tr("builder.target.surface", "Everything it finds"),
        "builder.target.platform": _tr("builder.target.platform", "A hiring platform"),
        "builder.target.company": _tr("builder.target.company", "One company"),
        "builder.platform_label": _tr("builder.platform_label", "Platform:"),
        "builder.company_label": _tr("builder.company_label", "Company careers page link:"),
        "builder.terms_label": _tr("builder.terms_label", "Search words:"),
        "builder.location_label": _tr("builder.location_label", "Location:"),
        "builder.any_of_label": _tr("builder.any_of_label", "Any of these:"),
        "builder.exclude_label": _tr("builder.exclude_label", "Without:"),
        "builder.in_title_label": _tr("builder.in_title_label", "In the title:"),
        "builder.defaults_label": _tr("builder.defaults_label", "From your profile:"),
        "builder.pick_one": _tr("builder.pick_one", "Pick one…"),
        "builder.options_label": _tr("builder.options_label", "Options:"),
        "builder.option_not_set": _tr("builder.option_not_set", "(not set)"),
        "builder.preview_label": _tr("builder.preview_label", "Result:"),
        "builder.recent_label": _tr("builder.recent_label", "Recent searches:"),
        "builder.recent_placeholder": _tr("builder.recent_placeholder", "Choose one to reuse…"),
        "builder.recent_empty_label": _tr("builder.recent_empty_label", "No recent searches yet"),
        "builder.copy_text": _tr("builder.copy_text", "Copy search text"),
        "builder.copy_link": _tr("builder.copy_link", "Copy link"),
        "builder.open_link": _tr("builder.open_link", "Open link"),
        "builder.keep": _tr("builder.keep", "Keep"),
        "builder.clear_recent": _tr("builder.clear_recent", "Clear recent"),
        "builder.close": _tr("builder.close", "Close"),
        "builder.error": _tr("builder.error", "Could not build that search"),
        "builder.nothing_built": _tr("builder.nothing_built", "Nothing to build yet — add at least one search word."),
        "builder.status.no_result": _tr("builder.status.no_result", "Build a search first."),
        "builder.status.copied_text": _tr("builder.status.copied_text", "Search text copied and kept."),
        "builder.status.copied_link": _tr("builder.status.copied_link", "Link copied and kept."),
        "builder.status.opened": _tr("builder.status.opened", "Link opened in your browser; the search was kept."),
        "builder.status.kept": _tr("builder.status.kept", "Search kept."),
        "builder.status.cleared": _tr("builder.status.cleared", "Recent searches cleared."),
        "builder.status.recent_loaded": _tr("builder.status.recent_loaded", "Showing a remembered search. Edit the fields to build a new one."),
        "builder.status.recent_unavailable": _tr("builder.status.recent_unavailable", "That search used a site that is not available here."),
        "builder.result.bar": _tr("builder.result.bar", "Search bar"),
        "builder.result.link": _tr("builder.result.link", "Link"),
    }