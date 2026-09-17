"""ISO 639-1 / ISO 3166-1 alpha-2 locale normalisation — the single answering site.

Predicate 13: "what locale is this?" Two call sites used to answer it with
two different APIs and two different (broken) normalisations:

  * application/services/i18n.py's detect_locale() split locale.getlocale()
    output naively, fabricating codes like ("c", "US") and
    ("english", "UNITED STATES") — then logged "locale file not found" for
    files those values could never name.
  * adapters/secondary/browser/selenium_provider.py used
    locale.getdefaultlocale(), an API deprecated since 3.11 and removed in
    3.15, and produced different answers on the same machine.

Both now call normalize_locale() here. The function is pure: a locale string
in, ISO codes out (or None when the value cannot be mapped). It performs no
I/O of its own and is safe to use from any layer — that is why it lives in
domain, the only layer both an application service (i18n) and a secondary
adapter (selenium_provider) are permitted to import.

Windows note: locale.getlocale() on Windows reports English language names
(e.g. 'English_United States'), not ISO codes. The two tables below map those
English names to ISO codes. Entries are sourced from Microsoft's locale name
registry and trimmed to the languages/regions AA's own UI language list
(application/services/i18n.py LANGUAGE_DISPLAY_NAMES) already covers — they
exist only because Windows cannot report codes directly, so they are a
Windows-only shim, not a translation table.
"""

from __future__ import annotations

# Values that mean "no locale configured", not a language.
_NO_LOCALE_VALUES: frozenset[str] = frozenset({"C", "POSIX"})

# Windows getlocale() reports English language names, not ISO 639-1 codes.
# Source: Microsoft locale name registry (locale name → English display name).
# Trimmed to the languages AA's LANGUAGE_DISPLAY_NAMES already covers.
_WINDOWS_LANGUAGE_TO_ISO: dict[str, str] = {
    "english": "en",
    "spanish": "es",
    "french": "fr",
    "german": "de",
    "portuguese": "pt",
    "italian": "it",
    "dutch": "nl",
    "polish": "pl",
    "japanese": "ja",
    "korean": "ko",
    "chinese": "zh",
    "arabic": "ar",
    "hebrew": "he",
    "hindi": "hi",
    "russian": "ru",
    "turkish": "tr",
    "swedish": "sv",
    "norwegian": "no",
    "danish": "da",
    "finnish": "fi",
    "thai": "th",
    "vietnamese": "vi",
    "indonesian": "id",
    "ukrainian": "uk",
    "czech": "cs",
    "romanian": "ro",
    "hungarian": "hu",
    "greek": "el",
    "bulgarian": "bg",
    "persian": "fa",
    "urdu": "ur",
    "bengali": "bn",
    "tamil": "ta",
    "swahili": "sw",
    "malay": "ms",
    "filipino": "tl",
}

# Windows region names → ISO 3166-1 alpha-2 country codes.
# Same source and same trimming rule as the language table above.
_WINDOWS_REGION_TO_ISO: dict[str, str] = {
    "united states": "US",
    "united kingdom": "GB",
    "canada": "CA",
    "mexico": "MX",
    "brazil": "BR",
    "spain": "ES",
    "france": "FR",
    "germany": "DE",
    "italy": "IT",
    "portugal": "PT",
    "netherlands": "NL",
    "poland": "PL",
    "japan": "JP",
    "china": "CN",
    "korea": "KR",
    "australia": "AU",
    "india": "IN",
    "russia": "RU",
    "turkey": "TR",
    "sweden": "SE",
    "norway": "NO",
    "denmark": "DK",
    "finland": "FI",
    "thailand": "TH",
    "vietnam": "VN",
    "indonesia": "ID",
    "ukraine": "UA",
    "czechia": "CZ",
    "czech republic": "CZ",
    "romania": "RO",
    "hungary": "HU",
    "greece": "GR",
    "bulgaria": "BG",
    "iran": "IR",
    "pakistan": "PK",
    "bangladesh": "BD",
    "malaysia": "MY",
    "philippines": "PH",
}


def normalize_locale(raw: str | None) -> tuple[str, str | None] | None:
    """Normalise an OS locale string to (ISO 639-1 lang, ISO 3166-1 alpha-2 country).

    Returns ``(lang, country)`` on success — country may be None when the
    input carries no region, and callers apply their own default. Returns
    ``None`` when the value cannot be mapped to a real code; the caller then
    falls back and logs what the OS actually reported, which is a different
    fact from "the locale file is missing".

    Handles at minimum:
      * ``C`` / ``POSIX`` — these mean "no locale configured", not a language.
      * Codeset and modifier suffixes — ``en_US.UTF-8``, ``ca_ES@euro``.
      * Hyphen/underscore variants — ``en-GB`` and ``en_GB`` are identical.
      * Bare language codes — ``es`` → ``("es", None)``.
      * Windows English language/region names — ``English_United States``
        → ``("en", "US")``, ``Spanish_Spain`` → ``("es", "ES")``.

    Three-letter ISO 639-2 codes (e.g. "eng") are deliberately not guessed;
    they return None and are logged by the caller as unrecognised, which is
    honest and keeps the table small.

    Args:
        raw: A locale string, typically ``locale.getlocale()[0]`` or a
            user-provided profile value.

    Returns:
        ``(lang, country)`` or ``None``.
    """
    if not raw or not raw.strip():
        return None

    value = raw.strip()
    # Strip codeset (".UTF-8") and modifier ("@euro") suffixes.
    value = value.split(".", 1)[0].split("@", 1)[0].strip()
    if not value:
        return None

    # The C and POSIX locales mean "no locale configured", not a language.
    if value.upper() in _NO_LOCALE_VALUES:
        return None

    value = value.replace("-", "_")
    parts = [p for p in value.split("_") if p]
    if not parts:
        return None
    lang_part = parts[0]
    region_part = "_".join(parts[1:]) if len(parts) > 1 else None

    # ISO-shaped input: ll or ll_CC (any case).
    if len(lang_part) == 2 and lang_part.isalpha():
        lang = lang_part.lower()
        if region_part is None:
            return (lang, None)
        region = region_part.upper()
        if len(region) == 2 and region.isalpha():
            return (lang, region)
        region_code = _WINDOWS_REGION_TO_ISO.get(
            region_part.lower().replace("_", " ").strip()
        )
        if region_code is not None:
            return (lang, region_code)
        return None

    # Windows English language name (with optional region).
    lang_code = _WINDOWS_LANGUAGE_TO_ISO.get(lang_part.lower())
    if lang_code is not None:
        if region_part is None:
            return (lang_code, None)
        region_code = _WINDOWS_REGION_TO_ISO.get(
            region_part.lower().replace("_", " ").strip()
        )
        if region_code is not None:
            return (lang_code, region_code)
        region = region_part.upper()
        if len(region) == 2 and region.isalpha():
            return (lang_code, region)

    return None
