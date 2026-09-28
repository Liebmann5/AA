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

This module is domain code: no I/O beyond reading one environment variable,
no imports outside the stdlib and ``domain.constants``.
"""
from __future__ import annotations

import hashlib
import hmac
import os

from auto_apply.domain.constants import RESEARCH_SALT_ENV_VAR

__all__ = ["ResearchSaltError", "resolve_research_salt", "compute_company_id"]


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


def compute_company_id(company_name: str | None) -> str | None:
    """Mint THE research company identity: HMAC-SHA256(key=salt, msg=name.lower())[:16].

    The salt is the HMAC key — it is never appended to the message; keying is
    what makes the digest unforgeable without the salt.

    Returns None for a falsy name, WITHOUT resolving the salt: absence of a
    company is not a company named "", and a run that never observes a
    company must not be gated on configuration it never uses.
    """
    if not company_name:
        return None
    salt = resolve_research_salt()
    company_id: str = hmac.new(
        salt.encode("utf-8"),
        company_name.lower().encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:16]
    return company_id
