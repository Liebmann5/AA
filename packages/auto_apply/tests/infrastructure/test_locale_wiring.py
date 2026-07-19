"""The locale the user configures must reach the running session.

The finding
-----------
AA ships a complete internationalization subsystem in
``application/services/i18n.py``: ``configure_locale``, ``get_text``,
``format_currency``, ``format_date``, ``format_number``, ``is_rtl`` (right-to-
left support), a ``_LocaleState`` singleton that separates ``language_code``
from ``country_code`` from ``currency_code``, and ``detect_locale()`` which
reads the OS locale. Two translation bundles exist and are populated:
``resources/locales/en.json`` and ``resources/locales/es.json`` (13 fully
translated key groups — session, discovery, vetting, application strings).

``configure_locale`` is called from exactly two places, both in the GUI
(``ui_schema.py`` and ``gui/strings.py``). Nothing on the session-building path
calls it. ``composition_root`` never mentioned locale. ``ApplicationConfig.locale``
(``str | None``) is one of the seven merged-but-unread profile fields pinned by
``test_config_contract.py``.

So ``_LocaleState`` stayed at its constructor defaults for every session AA had
ever run: ``language_code="en"``, ``country_code="US"``, ``currency_code="USD"``.
A user whose profile set ``locale="es"`` got English anyway, and ``es.json``
was never opened. This is the same built-then-unplugged pattern as the page
feedback loop and the dead SessionPlan fields: a working subsystem with no call
site.

The design insight worth preserving
------------------------------------
``_LocaleState`` already separates *interface language* (what the user reads)
from *country* (which jurisdiction's rules apply). That separation is correct
and rare — a user in Mexico applying to a job in the UK should read Spanish while
AA reasons about UK rules. The fix must not collapse the two back together.

The smallest fix
----------------
``composition_root`` calls ``configure_locale(language=<profile locale>)`` once,
early, using ``ApplicationConfig.locale`` and letting ``None`` fall through to
``detect_locale()`` — which is exactly what ``configure_locale``'s own signature
already does. One call. No new taxonomy, no translation layer, no jurisdiction
database.
"""

from __future__ import annotations

import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "auto_apply"


def test_composition_root_configures_locale() -> None:
    """The session-building path must set the active locale, not just the GUI."""
    root = (SRC / "infrastructure" / "composition_root.py").read_text(encoding="utf-8")
    tree = ast.parse(root)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "configure_locale"
    ]
    assert calls, (
        "composition_root never calls configure_locale. The i18n subsystem is "
        "fully built and only wired into the GUI, so every non-GUI session runs "
        "in hardcoded en/US/USD regardless of ApplicationConfig.locale. es.json "
        "is never loaded. Add one configure_locale() call on the build path, "
        "reading the profile locale and letting None auto-detect."
    )


def test_locale_separates_language_from_country() -> None:
    """A user's reading language and a job's jurisdiction are different axes."""
    from auto_apply.application.services.i18n import _LocaleState  # noqa: PLC0415

    state = _LocaleState()
    assert hasattr(state, "language_code") and hasattr(state, "country_code"), (
        "_LocaleState must keep language_code and country_code as separate "
        "fields. Collapsing them breaks the case AA's i18n was designed for: "
        "reading one language while applying under another country's rules."
    )


def test_spanish_bundle_is_loadable() -> None:
    """The translation that exists should actually load and format."""
    from auto_apply.application.services.i18n import (  # noqa: PLC0415
        configure_locale,
        get_active_language,
        get_text,
    )

    try:
        configure_locale(language="es")
        assert get_active_language() == "es", (
            "configure_locale(language='es') did not activate Spanish, even "
            "though resources/locales/es.json exists."
        )
        rendered = get_text("session.starting")
        assert rendered and rendered != "session.starting", (
            "get_text returned the raw key — es.json did not load."
        )
    finally:
        configure_locale(language="en")  # restore default for other tests