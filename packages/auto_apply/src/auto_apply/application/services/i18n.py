"""Internationalization (i18n) and localization (l10n) infrastructure.

This module is the single source of truth for all user-facing text in AA.
Every string the user sees — whether in the GUI, CLI, log output, or
session report — originates from this module. Nothing else in the codebase
contains hardcoded user-facing strings.

Design Philosophy:
    AA is a global tool. Language, currency, date format, number format,
    and text direction (LTR/RTL) are all first-class configuration axes.
    The user's locale is auto-detected at startup and can be overridden
    in settings. All locale data is resolved through this module.

How It Works:
    1. At startup, detect_locale() reads the OS locale.
    2. The user can override via settings (preferred_language, preferred_currency).
    3. get_text(key) returns the localized string for the active locale.
    4. format_currency(amount) returns a locale-appropriate currency string.
    5. format_date(dt) returns a locale-appropriate date string.

Adding a New Language:
    1. Create a new JSON file in resources/locales/<lang_code>.json
    2. Copy en.json as a template.
    3. Translate all values (keys stay in English).
    4. The new language is automatically available — no code changes needed.

Thread Safety:
    The locale registry is set once at startup and is read-only after that.
    All public functions are safe to call from any thread.

Example:
    >>> from auto_apply.application.services.i18n import get_text, format_currency
    >>> get_text("session.starting")
    'Starting job hunt session...'
    >>> format_currency(75000, "salary")
    '$75,000'
"""

# Layer: application
# Depends on: domain

import json
import locale
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Currency Configuration
# ─────────────────────────────────────────────────────────────────────────────

CURRENCY_CONFIG: dict[str, dict[str, Any]] = {
    "USD": {"symbol": "$",  "name": "US Dollar",        "decimal_places": 2, "symbol_before": True,  "thousands_sep": ",", "decimal_sep": "."},  # noqa: E501
    "EUR": {"symbol": "€",  "name": "Euro",             "decimal_places": 2, "symbol_before": True,  "thousands_sep": ".", "decimal_sep": ","},  # noqa: E501
    "GBP": {"symbol": "£",  "name": "British Pound",    "decimal_places": 2, "symbol_before": True,  "thousands_sep": ",", "decimal_sep": "."},  # noqa: E501
    "JPY": {"symbol": "¥",  "name": "Japanese Yen",     "decimal_places": 0, "symbol_before": True,  "thousands_sep": ",", "decimal_sep": "."},  # noqa: E501
    "CAD": {"symbol": "C$", "name": "Canadian Dollar",  "decimal_places": 2, "symbol_before": True,  "thousands_sep": ",", "decimal_sep": "."},  # noqa: E501
    "AUD": {"symbol": "A$", "name": "Australian Dollar", "decimal_places": 2, "symbol_before": True,  "thousands_sep": ",", "decimal_sep": "."},  # noqa: E501
    "MXN": {"symbol": "$",  "name": "Mexican Peso",     "decimal_places": 2, "symbol_before": True,  "thousands_sep": ",", "decimal_sep": "."},  # noqa: E501
    "BRL": {"symbol": "R$", "name": "Brazilian Real",   "decimal_places": 2, "symbol_before": True,  "thousands_sep": ".", "decimal_sep": ","},  # noqa: E501
    "INR": {"symbol": "₹",  "name": "Indian Rupee",     "decimal_places": 2, "symbol_before": True,  "thousands_sep": ",", "decimal_sep": "."},  # noqa: E501
    "CNY": {"symbol": "¥",  "name": "Chinese Yuan",     "decimal_places": 2, "symbol_before": True,  "thousands_sep": ",", "decimal_sep": "."},  # noqa: E501
    "KRW": {"symbol": "₩",  "name": "South Korean Won", "decimal_places": 0, "symbol_before": True,  "thousands_sep": ",", "decimal_sep": "."},  # noqa: E501
    "CHF": {"symbol": "CHF","name": "Swiss Franc",      "decimal_places": 2, "symbol_before": True,  "thousands_sep": "'", "decimal_sep": "."},  # noqa: E501
    "SEK": {"symbol": "kr", "name": "Swedish Krona",    "decimal_places": 2, "symbol_before": False, "thousands_sep": " ", "decimal_sep": ","},  # noqa: E501
    "NOK": {"symbol": "kr", "name": "Norwegian Krone",  "decimal_places": 2, "symbol_before": False, "thousands_sep": " ", "decimal_sep": ","},  # noqa: E501
    "PLN": {"symbol": "zł", "name": "Polish Zloty",     "decimal_places": 2, "symbol_before": False, "thousands_sep": " ", "decimal_sep": ","},  # noqa: E501
    "TRY": {"symbol": "₺",  "name": "Turkish Lira",     "decimal_places": 2, "symbol_before": True,  "thousands_sep": ".", "decimal_sep": ","},  # noqa: E501
    "ZAR": {"symbol": "R",  "name": "South African Rand","decimal_places": 2, "symbol_before": True,  "thousands_sep": " ", "decimal_sep": "."},  # noqa: E501
    "AED": {"symbol": "د.إ","name": "UAE Dirham",       "decimal_places": 2, "symbol_before": True,  "thousands_sep": ",", "decimal_sep": "."},  # noqa: E501
    "SAR": {"symbol": "﷼",  "name": "Saudi Riyal",      "decimal_places": 2, "symbol_before": True,  "thousands_sep": ",", "decimal_sep": "."},  # noqa: E501
    "NGN": {"symbol": "₦",  "name": "Nigerian Naira",   "decimal_places": 2, "symbol_before": True,  "thousands_sep": ",", "decimal_sep": "."},  # noqa: E501
    "PHP": {"symbol": "₱",  "name": "Philippine Peso",  "decimal_places": 2, "symbol_before": True,  "thousands_sep": ",", "decimal_sep": "."},  # noqa: E501
    "COP": {"symbol": "$",  "name": "Colombian Peso",   "decimal_places": 0, "symbol_before": True,  "thousands_sep": ".", "decimal_sep": ","},  # noqa: E501
    "EGP": {"symbol": "E£", "name": "Egyptian Pound",   "decimal_places": 2, "symbol_before": True,  "thousands_sep": ",", "decimal_sep": "."},  # noqa: E501
}

# Maps OS locale prefixes to default currency codes.
LOCALE_TO_CURRENCY: dict[str, str] = {
    "en_US": "USD", "en_GB": "GBP", "en_CA": "CAD", "en_AU": "AUD",
    "en_IN": "INR", "en_ZA": "ZAR", "en_NG": "NGN", "en_PH": "PHP",
    "ja": "JPY",  "ko": "KRW",  "zh": "CNY",
    "de": "EUR",  "fr": "EUR",  "it": "EUR",  "es": "EUR",  "nl": "EUR",  "pt_BR": "BRL",  # noqa: E501
    "es_MX": "MXN", "es_CO": "COP",
    "sv": "SEK",  "nb": "NOK",  "no": "NOK",  "pl": "PLN",
    "tr": "TRY",  "ar_AE": "AED", "ar_SA": "SAR", "ar_EG": "EGP",
}

# Languages with right-to-left text direction.
RTL_LANGUAGES = frozenset({"ar", "he", "fa", "ur"})

# Maps language codes to their native display names for the settings UI.
LANGUAGE_DISPLAY_NAMES: dict[str, str] = {
    "en": "English",         "es": "Español",          "fr": "Français",
    "de": "Deutsch",         "it": "Italiano",         "pt": "Português",
    "ja": "日本語",           "ko": "한국어",            "zh": "中文",
    "ar": "العربية",          "he": "עברית",            "hi": "हिन्दी",
    "ru": "Русский",         "pl": "Polski",           "tr": "Türkçe",
    "nl": "Nederlands",     "sv": "Svenska",          "no": "Norsk",
    "da": "Dansk",           "fi": "Suomi",            "th": "ไทย",
    "vi": "Tiếng Việt",      "id": "Bahasa Indonesia", "ms": "Bahasa Melayu",
    "tl": "Tagalog",         "uk": "Українська",       "cs": "Čeština",
    "ro": "Română",          "hu": "Magyar",           "el": "Ελληνικά",
    "bg": "Български",       "fa": "فارسی",            "ur": "اردو",
    "bn": "বাংলা",            "ta": "தமிழ்",             "sw": "Kiswahili",
}


# ─────────────────────────────────────────────────────────────────────────────
# Locale State (set once at startup, read-only after)
# ─────────────────────────────────────────────────────────────────────────────

class _LocaleState:
    """Singleton holding the active locale configuration for this session."""

    def __init__(self) -> None:
        self.language_code: str = "en"
        self.country_code: str = "US"
        self.currency_code: str = "USD"
        self.is_rtl: bool = False
        self._strings: dict[str, str] = {}
        self._fallback_strings: dict[str, str] = {}

    def configure(
        self,
        language: str | None = None,
        country: str | None = None,
        currency: str | None = None,
        locales_dir: Path | None = None,
    ) -> None:
        """Configures the locale state for this session.

        Called once at startup by SessionController. After this call,
        all get_text() and format_*() calls use the configured locale.

        Args:
            language: ISO 639-1 language code (e.g., "en", "es", "ja").
                If None, auto-detected from the OS.
            country: ISO 3166-1 country code (e.g., "US", "GB", "JP").
                If None, auto-detected from the OS.
            currency: ISO 4217 currency code (e.g., "USD", "GBP").
                If None, inferred from language + country.
            locales_dir: Path to the directory containing locale JSON files.
                If None, uses the default resources/locales/ directory.
        """
        if language is None or country is None:
            detected_lang, detected_country = detect_locale()
            language = language or detected_lang
            country = country or detected_country

        self.language_code = language.lower()
        self.country_code = country.upper()
        self.is_rtl = self.language_code in RTL_LANGUAGES

        # Resolve currency
        if currency:
            self.currency_code = currency.upper()
        else:
            locale_key = f"{self.language_code}_{self.country_code}"
            self.currency_code = LOCALE_TO_CURRENCY.get(
                locale_key,
                LOCALE_TO_CURRENCY.get(self.language_code, "USD"),
            )

        # Load string bundles
        if locales_dir is None:
            locales_dir = Path(__file__).parent.parent.parent / "resources" / "locales"

        self._fallback_strings = _load_string_bundle(locales_dir / "en.json")
        if self.language_code != "en":
            self._strings = _load_string_bundle(
                locales_dir / f"{self.language_code}.json"
            )
        else:
            self._strings = self._fallback_strings

        logger.info(
            "Locale configured | lang=%s country=%s currency=%s rtl=%s",
            self.language_code, self.country_code, self.currency_code, self.is_rtl,
        )

    def get_string(self, key: str, **kwargs: Any) -> str:
        """Returns the localized string for a given key.

        Falls back to English if the key is missing in the active locale.
        Falls back to the raw key if missing everywhere (prevents crashes
        from missing translations).

        Args:
            key: Dot-separated string key (e.g., "session.starting").
            **kwargs: Format variables to interpolate into the string.

        Returns:
            The localized, formatted string.
        """
        template = self._strings.get(key) or self._fallback_strings.get(key, key)
        try:
            return template.format(**kwargs) if kwargs else template
        except (KeyError, IndexError):
            logger.warning("String format error | key=%s kwargs=%s", key, kwargs)
            return template


_state = _LocaleState()


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def configure_locale(
    language: str | None = None,
    country: str | None = None,
    currency: str | None = None,
    locales_dir: Path | None = None,
) -> None:
    """Configures the application locale. Call once at startup.

    Args:
        language: ISO 639-1 language code, or None for auto-detect.
        country: ISO 3166-1 country code, or None for auto-detect.
        currency: ISO 4217 currency code, or None for auto-infer.
        locales_dir: Path to locale JSON files, or None for default.
    """
    _state.configure(language, country, currency, locales_dir)


def get_text(key: str, **kwargs: Any) -> str:
    """Returns the localized string for the given key.

    This is the primary function all UI and CLI code calls to get
    user-facing text. Never hardcode strings — always use get_text().

    Args:
        key: Dot-separated key matching a key in the locale JSON.
        **kwargs: Named format variables.

    Returns:
        The localized string with variables interpolated.

    Example:
        >>> get_text("session.jobs_found", count=42)
        'Found 42 jobs'
    """
    return _state.get_string(key, **kwargs)


def format_currency(amount: float, salary_context: bool = False) -> str:
    """Formats a number as a currency string in the active locale.

    Args:
        amount: The numeric amount.
        salary_context: If True, formats as a salary (may abbreviate
            large numbers, e.g., "$75K" in some locales).

    Returns:
        A locale-appropriate currency string.

    Example:
        >>> format_currency(75000)
        '$75,000.00'
        >>> format_currency(75000, salary_context=True)
        '$75,000'
    """
    config = CURRENCY_CONFIG.get(_state.currency_code, CURRENCY_CONFIG["USD"])

    decimal_places = 0 if salary_context else config["decimal_places"]
    if config["decimal_places"] == 0:
        decimal_places = 0

    # Format the number
    abs_amount = abs(amount)
    integer_part = int(abs_amount)
    fractional_part = abs_amount - integer_part

    # Apply thousands separator
    int_str = ""
    s = str(integer_part)
    for i, digit in enumerate(reversed(s)):
        if i > 0 and i % 3 == 0:
            int_str = config["thousands_sep"] + int_str
        int_str = digit + int_str

    if decimal_places > 0:
        frac_str = f"{fractional_part:.{decimal_places}f}"[2:]  # strip "0."
        formatted = f"{int_str}{config['decimal_sep']}{frac_str}"
    else:
        formatted = int_str

    symbol = config["symbol"]
    if config["symbol_before"]:
        result = f"{symbol}{formatted}"
    else:
        result = f"{formatted} {symbol}"

    if amount < 0:
        result = f"-{result}"

    return result


def format_date(dt: datetime, style: str = "medium") -> str:
    """Formats a datetime in the active locale's convention.

    Args:
        dt: The datetime to format.
        style: "short" (MM/DD), "medium" (Mon DD, YYYY), or "long".

    Returns:
        A locale-appropriate date string.
    """
    if style == "short":
        return dt.strftime("%m/%d/%Y")
    elif style == "long":
        return dt.strftime("%B %d, %Y %H:%M:%S")
    else:
        return dt.strftime("%b %d, %Y")


def format_number(value: float, decimal_places: int = 0) -> str:
    """Formats a number with locale-appropriate separators.

    Args:
        value: The number to format.
        decimal_places: Number of decimal places.

    Returns:
        A formatted number string.
    """
    config = CURRENCY_CONFIG.get(_state.currency_code, CURRENCY_CONFIG["USD"])
    integer_part = int(abs(value))
    s = str(integer_part)
    int_str = ""
    for i, digit in enumerate(reversed(s)):
        if i > 0 and i % 3 == 0:
            int_str = config["thousands_sep"] + int_str
        int_str = digit + int_str

    if decimal_places > 0:
        frac = abs(value) - integer_part
        frac_str = f"{frac:.{decimal_places}f}"[2:]
        result = f"{int_str}{config['decimal_sep']}{frac_str}"
    else:
        result = int_str

    return f"-{result}" if value < 0 else result


def get_active_language() -> str:
    """Returns the active ISO 639-1 language code."""
    return _state.language_code


def get_active_currency() -> str:
    """Returns the active ISO 4217 currency code."""
    return _state.currency_code


def is_rtl() -> bool:
    """Returns True if the active language uses right-to-left text."""
    return _state.is_rtl


def get_available_languages() -> dict[str, str]:
    """Returns a dict of available language codes to their native names.

    Used by the settings UI to populate the language selector dropdown.
    """
    return dict(LANGUAGE_DISPLAY_NAMES)


def get_available_currencies() -> dict[str, str]:
    """Returns a dict of available currency codes to their display names.

    Used by the settings UI to populate the currency selector dropdown.
    """
    return {code: conf["name"] for code, conf in CURRENCY_CONFIG.items()}


# ─────────────────────────────────────────────────────────────────────────────
# Internal Helpers
# ─────────────────────────────────────────────────────────────────────────────

def detect_locale() -> tuple[str, str]:
    """Detects the OS locale and returns (language_code, country_code).

    Returns:
        A tuple of (language, country) strings. Falls back to ("en", "US")
        if detection fails.
    """
    try:
        raw = locale.getlocale()[0]
        if raw:
            parts = raw.replace("-", "_").split("_")
            lang = parts[0].lower()
            country = parts[1].upper() if len(parts) > 1 else "US"
            return lang, country
    except Exception:
        logger.debug("Locale auto-detection failed — falling back to en_US")

    return "en", "US"


def _load_string_bundle(path: Path) -> dict[str, str]:
    """Loads a locale JSON file and flattens it into a dot-keyed dict.

    The JSON file can be nested:
        {"session": {"starting": "Starting..."}}
    This becomes:
        {"session.starting": "Starting..."}

    Args:
        path: Path to the JSON locale file.

    Returns:
        A flat dict mapping dot-separated keys to string values.
    """
    if not path.exists():
        logger.warning("Locale file not found | path=%s", path)
        return {}

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return _flatten_dict(data)
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Failed to load locale file | path=%s error=%s", path, exc)
        return {}


def _flatten_dict(d: dict, prefix: str = "") -> dict[str, str]:
    """Recursively flattens a nested dict into dot-separated keys."""
    result = {}
    for key, value in d.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            result.update(_flatten_dict(value, full_key))
        else:
            result[full_key] = str(value)
    return result