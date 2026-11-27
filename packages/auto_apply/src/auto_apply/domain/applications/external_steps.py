"""Steps an application sends the person to: assessments and other forms.

Some applications stop being about the candidate's background: a page turns
into a timed test, or the form says "complete the assessment at the link
below — applications without it will not be reviewed", or points to another
questionnaire that "must be completed before submitting". None of this is
marked required in the page's code; the requirement is in the words.

AA's position (docs/adr/026):

* AA **never takes a test for the person** — answering a skills or
  personality test on someone's behalf misrepresents them, and tests are
  often timed. A page that is a test (``is_test_step``) is handed to the
  person; with no one to hand it to, the application stops there.
* AA **never follows these links itself**. It recognises them
  (``external_steps``), tells the person before anything is submitted, and
  records them: how often employers demand assessments, where, and in what
  words, is research data (assessment burden).

Recognition is structure first, words second:

* the link's host is a known assessment platform (``ASSESSMENT_HOSTS`` —
  data; extend it), or
* the words around the link name an assessment (lexicon class
  ``assessment``, any language), or
* the words around a link to another site make it a condition of being
  considered (``must_complete``, any language).

A page is a test when its structure says so: an ARIA ``role=timer`` is
shown, or an in-page code editor. Words alone ("assessment" in a heading)
never make a page a test.

Pure and deterministic: the standard library and the lexicon only.
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass

from auto_apply.domain.applications.form_language import says
from auto_apply.domain.applications.form_model import FormStep, QuestionKind

#: Hosts of assessment and pre-employment testing platforms (a host or any
#: subdomain of it). Data: add a platform here when one is met.
ASSESSMENT_HOSTS: tuple[str, ...] = (
    "hackerrank.com", "codility.com", "codesignal.com", "coderbyte.com", "testdome.com",
    "devskiller.com", "hackerearth.com", "codingame.com", "qualified.io", "karat.com",
    "byteboard.dev", "imocha.io", "mettl.com", "testgorilla.com", "criteriacorp.com",
    "shl.com", "talentcentral.shl.com", "cut-e.com", "talentlens.com",
    # Aon's tests (formerly cut-e) run on MapTQ; its own aon.com is a
    # corporate site, so only the assessment subdomain is listed.
    "maptq.com", "assessment.aon.com",
    "wonderlic.com", "pymetrics.ai", "pymetrics.com", "harver.com", "hirevue.com",
    "plum.io", "vervoe.com", "eskill.com", "canditech.io", "glider.ai", "alva-labs.com",
    "assessfirst.com", "thomas.co", "predictiveindex.com", "traitify.com", "sova.ai",
    "maki-people.com", "willo.video", "spark-hire.com", "sparkhire.com", "myinterview.com",
)

#: How much of a link's surrounding text is kept in records.
_TEXT_CAP = 120


@dataclass(frozen=True)
class ExternalStep:
    """Something the form sends the person to.

    Attributes:
        kind: ``assessment`` or ``external_form``.
        host: The link's host ("" when the step was named without a link).
        required: The page's words make it a condition of being considered.
        evidence: How AA knew: ``host``, ``words`` (the assessment words),
            ``must_complete`` — joined with ``+``.
        text: The link's own text (or the question's label), shortened.
        href: The link, for the person. Never written to research records
            (it can carry a candidate token); the host is.
    """

    kind: str
    host: str
    required: bool
    evidence: str
    text: str
    href: str = ""


def host_of(href: str) -> str:
    try:
        host = urllib.parse.urlsplit(href).hostname or ""
    except ValueError:
        return ""
    return host.lower().removeprefix("www.")


def is_assessment_host(host: str) -> bool:
    host = (host or "").lower()
    return any(host == h or host.endswith("." + h) for h in ASSESSMENT_HOSTS)


def _form_host(step: FormStep) -> str:
    return host_of(step.url)


def external_steps(step: FormStep) -> tuple[ExternalStep, ...]:
    """The assessments and other forms this step sends the person to."""
    out: list[ExternalStep] = []
    seen: set[str] = set()
    own = _form_host(step)
    for link in step.links:
        href = (link.href or "").strip()
        if not href.lower().startswith(("http://", "https://")) or href in seen:
            continue
        host = host_of(href)
        words = f"{link.text} {link.context}"
        by_host = is_assessment_host(host)
        by_words = says(words, "assessment")
        # Only "must complete" wording, never a bare "required": the form's
        # own "Required fields are marked *" sits near every link.
        required = says(words, "must_complete")
        elsewhere = bool(host) and host != own and not host.endswith("." + own) \
            and not own.endswith("." + host)
        if by_host or by_words:
            kind = "assessment"
        elif required and elsewhere:
            kind = "external_form"
        else:
            continue
        seen.add(href)
        evidence = "+".join(e for e, on in (("host", by_host), ("words", by_words),
                                           ("must_complete", required)) if on)
        out.append(ExternalStep(kind, host, required, evidence,
                                (link.text or link.context or host)[:_TEXT_CAP], href))
    # A question that names a required assessment without a link ("I have
    # completed the HackerRank test — required").
    for q in step.questions:
        words = f"{q.label} {q.description}"
        # The question is the condition when its words say the assessment
        # must be done, or when it is a single required tick box naming one
        # (an attestation: "I have completed the coding test"). A required
        # radio or text question ("Have you taken an assessment with us
        # before?") asks about the past and is not a condition.
        attests = q.kind == QuestionKind.CHECKBOX and (
            q.is_required or says(words, "required"))
        why = ("must_complete" if says(words, "must_complete") else
               "attestation" if attests else "")
        if says(words, "assessment") and why:
            key = "question:" + q.key
            if key not in seen:
                seen.add(key)
                out.append(ExternalStep("assessment", "", True, "words+" + why,
                                        (q.label or q.description)[:_TEXT_CAP]))
    return tuple(out)


def is_test_step(step: FormStep) -> tuple[str, ...]:
    """Structural signs that this page is a test, not an application step:
    a timer, a code editor, or being on an assessment platform at all (a
    redirect from the application to the test)."""
    signals = [s for s in step.test_signals if s in ("role=timer", "code-editor")]
    if is_assessment_host(_form_host(step)):
        signals.append("assessment-host")
    return tuple(signals)


__all__ = ["ASSESSMENT_HOSTS", "ExternalStep", "external_steps", "host_of",
           "is_assessment_host", "is_test_step"]
