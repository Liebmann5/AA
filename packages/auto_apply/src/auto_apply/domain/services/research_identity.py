"""
The one place that mints a research identity.

Two construction rules, both load-bearing:

1. ONE DEFINITION. ``company_id`` is a join key across ``research_signals``
   and ``application_outcomes``. It was previously minted in two places with
   two incompatible constructions — HMAC-SHA256(key=salt) in the detector
   path, SHA-256(name + salt) in the application path — and a salted digest
   of the same input under two constructions is two different values, so the
   join returned nothing instead of failing. Every research company identity
   in the tree now comes from ``compute_company_id`` below.

2. NO DEFAULT SALT, EVER. Both retired sites fell back to the literal
   ``"default_dev_salt"`` when the environment variable was unset — a salt
   published in the source tree, which is not anonymisation. An unset or
   blank salt is fatal: ``resolve_research_salt`` raises ``ResearchSaltError``.
   Where that raise surfaces is a deliberate choice — ResearchSignalAggregator
   resolves the salt at construction so "research enabled, salt unset"
   refuses the session instead of being swallowed inside a detector's
   try/except.

3. ONE CANONICAL FORM. The HMAC message is the output of
   ``_normalise_company_name`` — stripped of invisible format characters,
   then Unicode-compatibility form, casefolded, whitespace-collapsed — and
   nothing more. The form is a fixed point: normalising it again changes
   nothing. Differences that cannot carry meaning are collapsed;
   everything that might (punctuation, legal-entity suffixes) is left to
   under-split rather than risk one fabricated merge. See the function
   docstring for the full reasoning.

4. ABSENCE IS NOT A NAME. ``Job.company`` is a required string, so
   discovery producers that cannot extract a company invent display
   placeholders ("Unknown" and friends). Hashing a placeholder merged every
   unnameable employer into one fabricated, joinable identity — the
   empty-string defect one layer up. The placeholders in
   ``ABSENT_COMPANY_TOKENS`` canonicalise to None.

This module is domain code: no I/O beyond reading one environment variable,
no imports outside the stdlib and ``domain.constants``.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import unicodedata

from auto_apply.domain.constants import RESEARCH_SALT_ENV_VAR

__all__ = [
    "ABSENT_COMPANY_TOKENS",
    "ResearchSaltError",
    "resolve_research_salt",
    "salt_available",
    "compute_company_id",
]


class ResearchSaltError(ValueError):
    """The research salt is unset or blank while research collection needs it.

    Subclasses ValueError so any pre-existing handler for malformed
    configuration still catches it; the name exists so callers can catch
    exactly this and nothing else.
    """


def resolve_research_salt() -> str:
    """Return the configured research salt, or raise.

    The value is used VERBATIM — leading or trailing whitespace is part of
    the salt — but a value that is empty or whitespace-only is treated as
    unset, because a whitespace-only salt is a configuration accident, not a
    choice. The literal ``"default_dev_salt"`` is NOT special-cased: it is a
    legal (bad) salt, and magic-stringing it would be a second hidden
    default.

    Raises:
        ResearchSaltError: If the variable is unset, empty, or whitespace-only.
    """
    salt = os.environ.get(RESEARCH_SALT_ENV_VAR, "")
    if not salt.strip():
        raise ResearchSaltError(
            f"{RESEARCH_SALT_ENV_VAR} is unset or blank and research collection "
            "requires it. There is no default: a fallback salt is published in "
            "the source tree, and a published salt is not anonymisation — rows "
            "produced under one are treated as compromised and nulled by "
            "ResearchSignalAggregator's one-time migration. Set "
            f"{RESEARCH_SALT_ENV_VAR} to a private, stable value before running "
            "with research consent active."
        )
    return salt


def salt_available() -> bool:
    """True when a research salt is configured, False when it is not.

    The boolean half of resolve_research_salt: the consent service and the
    composition root ask this question before anything is constructed, so a
    missing salt surfaces as a STATUS (research inactive, reason NO_SALT)
    instead of an exception from inside a constructor. The raise in
    resolve_research_salt is unchanged — anything that actually writes still
    hard-requires the salt.
    """
    try:
        resolve_research_salt()
    except ResearchSaltError:
        return False
    return True


#: Display strings that mean "the producer could not name a company", matched
#: AFTER canonicalisation. The canonical research answer to any of these is
#: absence (None), never an identity: discovery producers emit the literal
#: "Unknown" when extraction fails, and hashing it merged every unnameable
#: employer in the corpus into one fabricated entity with a fabricated
#: response rate. The set is deliberately tiny and exact-match — "X" is a
#: real employer, and no length or pattern rule can tell a placeholder from
#: a name; only these constants can. A producer that invents a NEW
#: placeholder must add it here, in the change that introduces it.
ABSENT_COMPANY_TOKENS: frozenset[str] = frozenset({"unknown", "n/a", "none"})


def _normalise_company_name(company_name: str) -> str:
    """The canonical form every research company identity is minted from.

    Only differences that cannot carry meaning in any jurisdiction are
    collapsed, in an order chosen so each step's output feeds the next:

      1. format characters (Unicode category Cf — zero-width spaces, join
         controls, soft hyphens, bidi marks) are removed FIRST: invisible
         extraction noise that renders identically to its absence. This
         includes ZWNJ, which is orthographic in Persian and some Indic
         scripts; spellings with and without it are variants of one word,
         so that merge is accepted. FIRST because removing one can leave
         two combining marks adjacent in non-canonical order: stripped
         after NFKC, the result was not a fixed point (measured 173 of
         300,000 fuzzed strings, e.g. "Cafe" + U+0301 + U+200B + U+0323),
         so a raw name and the same name already normalised minted two ids;
      2. NFKC — compatibility characters (full-width Latin, ligatures,
         squared CJK symbols) fold to their ordinary forms, and canonically
         equivalent spellings (NFC vs NFD) become byte-identical;
      3. casefold — aggressive caseless matching: "Straße" and "STRASSE"
         meet where ``lower()`` left them apart. Turkish "İ" casefolds to
         two code points and stays distinct from "i" — accepted, because
         the distinction is meaningful in Turkish and unknowable without a
         locale AA does not ask for;
      4. NFKC again — casefolding can introduce decomposed sequences;
      5. every run of whitespace (space, tab, newline, NBSP, ideographic
         space …) collapses to one ASCII space, ends stripped.

    The result is a fixed point - normalising it again changes nothing -
    pinned by test_canonical_form_is_a_fixed_point__teeth and __guard.

    What is deliberately NOT touched: punctuation and legal-entity suffixes.
    "Acme Corp", "Acme Corp.", "Acme Corporation" and "ACME" stay distinct.
    That is under-splitting, and it is the chosen error: a false split
    dilutes a real employer's counts across rows that are each still
    truthful, while a false merge FABRICATES one entity out of several —
    and for a per-employer research result the fabricated number is the
    worse outcome. Suffix stripping is also jurisdiction-bound by
    construction (Inc, Ltd, GmbH, S.A., K.K., 株式会社…): any list AA
    shipped would be an English-flavoured guess at every legal system at
    once, and suffixes carry real legal meaning (an Ltd and a plc sharing
    a stem are different companies). See the module docstring, rule 3.
    """
    text = "".join(ch for ch in company_name if unicodedata.category(ch) != "Cf")
    text = unicodedata.normalize("NFKC", text)
    text = text.casefold()
    text = unicodedata.normalize("NFKC", text)
    return " ".join(text.split())


def compute_company_id(company_name: str | None) -> str | None:
    """Mint THE research company identity:
    HMAC-SHA256(key=salt, msg=_normalise_company_name(name))[:16].

    The salt is the HMAC key — it is never appended to the message; keying is
    what makes the digest unforgeable without the salt.

    Returns None — WITHOUT resolving the salt — for a falsy name, for a name
    that canonicalises to nothing, and for the placeholder display strings in
    ``ABSENT_COMPANY_TOKENS``: absence of a company is not a company named
    "", "Unknown" is not a company either, and a run that never observes a
    real company must not be gated on configuration it never uses.
    """
    if not company_name:
        return None
    canonical = _normalise_company_name(company_name)
    if not canonical or canonical in ABSENT_COMPANY_TOKENS:
        return None
    salt = resolve_research_salt()
    company_id: str = hmac.new(
        salt.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:16]
    return company_id
