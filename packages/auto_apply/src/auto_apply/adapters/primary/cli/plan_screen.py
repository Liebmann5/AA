"""The --print-plan surface: show what a session would search, then exit.

Composition stays in main.py; every print lives here (the consent-screen
precedent), so main.py's pinned print-site count does not move. Offline by
construction: no browser, no network — the preview is computed from the
session plan and the planner only.
"""

from __future__ import annotations

from auto_apply.application.services.i18n import configure_locale, get_text
from auto_apply.domain.models.ui_contract import (
    EntryPoint,
    SessionRequest,
    format_search_plan_preview,
    parse_platform_names,
)
from auto_apply.infrastructure.composition_root import build_search_plan_preview

__all__ = ["run_print_plan"]


def run_print_plan(args, profile_repo) -> int:
    """Render the plan preview for the given flags. Returns the exit code."""
    configure_locale(language=None)
    profile = None
    try:
        names = [n for n in profile_repo.list_profiles() if n != "default_profile"]
        chosen = names[0] if names else "default_profile"
        profile = profile_repo.load_profile(chosen)
    except Exception:
        profile = None
    if profile is None:
        print(get_text("searchplan.cli.no_profile"))  # noqa: T201
        return 1
    request = SessionRequest(
        entry=EntryPoint.SEARCH,
        platforms=parse_platform_names(getattr(args, "platforms", None)),
    )
    preview = build_search_plan_preview(profile, request)
    for line in format_search_plan_preview(preview, translate=get_text):
        print(line)  # noqa: T201
    return 0
