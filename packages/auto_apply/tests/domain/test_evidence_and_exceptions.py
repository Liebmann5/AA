"""S8j pins — ApplicationEvidence extra="forbid" (R-7) + exception renames (R-9).

Pin labels (honest, per standing method):
  1   TEETH — ApplicationEvidence(job_url=...) must raise ValidationError.
      Pre-stage the unknown kwarg is silently dropped (extra defaults to
      "ignore"), so no exception is raised and the pin fails.
  3   TEETH — AutoApplyException must be defined exactly once in
      exceptions.py. Pre-stage it is defined twice -> fails.
  4   TEETH — the name ScrapingError must be retired; both precise names
      must exist. Pre-stage fails on both counts.
  5b  TEETH — CaptchaChallengeError must be a subclass of the single live
      AutoApplyException. Pre-stage it inherits from the ORPHANED first-block
      class object, which is not the class the name resolves to -> fails.
      This is the exact armed trap R-9 targets.
  2   BEHAVIOUR-PRESERVING — construction with all real fields works on both
      trees.
  5a  BEHAVIOUR-PRESERVING — the live names (ApplicationError,
      InfrastructureError, ConfigurationError) keep their meaning and root
      relationships on both trees.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

import auto_apply
from auto_apply.domain.models.application_evidence import ApplicationEvidence

_EXCEPTIONS_PY = (
    Path(auto_apply.__file__).resolve().parent / "domain" / "exceptions.py"
)


# --------------------------------------------------------------------------
# R-7 — ApplicationEvidence
# --------------------------------------------------------------------------

def test_application_evidence_rejects_unknown_fields() -> None:
    """job_url is NOT a field of ApplicationEvidence — the documented trap
    that let fail-loud pins pass while writing corrupt records."""
    with pytest.raises(ValidationError):
        ApplicationEvidence(
            pre_submit_url="https://example.com/job/1",
            page_title_before="Engineer",
            job_url="https://example.com/job/1",  # type: ignore[call-arg]
        )


def test_application_evidence_accepts_all_real_fields() -> None:
    ev = ApplicationEvidence(
        attempt_id="session:1",
        pre_submit_url="https://example.com/job/1",
        page_title_before="Engineer",
        outcome="SUBMITTED",
        confidence=0.95,
    )
    assert ev.is_likely_success is True
    assert bool(ev) is True


# --------------------------------------------------------------------------
# R-9 — exceptions.py
# --------------------------------------------------------------------------

def test_autoapplyexception_defined_exactly_once() -> None:
    src = _EXCEPTIONS_PY.read_text(encoding="utf-8")
    count = src.count("class AutoApplyException(Exception):")
    assert count == 1, (
        f"AutoApplyException is defined {count} times in exceptions.py — "
        f"the second definition silently wins at import time"
    )


def test_scrapingerror_name_retired_for_precise_names() -> None:
    src = _EXCEPTIONS_PY.read_text(encoding="utf-8")
    assert "class ScrapingError(" not in src, (
        "ScrapingError still exists — R-9 rules that neither duplicate "
        "keeps the ambiguous name"
    )
    assert "class PageInterpretationError(" in src
    assert "class ExtractionPhaseError(" in src


def test_captcha_challenge_error_joins_the_single_hierarchy() -> None:
    from auto_apply.domain.exceptions import (
        AutoApplyException,
        CaptchaChallengeError,
    )

    assert issubclass(CaptchaChallengeError, AutoApplyException), (
        "CaptchaChallengeError must inherit from the single live "
        "AutoApplyException — pre-S8j it inherited from the orphaned "
        "first-block class object that no except clause could reach"
    )


def test_live_exception_names_unchanged() -> None:
    from auto_apply.domain.exceptions import (
        ApplicationError,
        AutoApplyException,
        ConfigurationError,
        InfrastructureError,
    )

    assert issubclass(ConfigurationError, AutoApplyException)
    assert issubclass(InfrastructureError, AutoApplyException)
    assert not issubclass(ApplicationError, AutoApplyException), (
        "ApplicationError is a separate root by design — moving it would "
        "change live catch semantics and is out of scope for R-9"
    )
