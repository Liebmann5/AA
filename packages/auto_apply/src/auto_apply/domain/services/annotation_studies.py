"""The labelling studies AA ships (item 5).

Each study is data: a versioned question set. Adding a study is adding a
value here and a source of items for it; nothing else changes. Choice keys
are stored forever — change wording freely, but never reuse or rename a
key; retire it in a new version instead.

* ``block-pages`` — item 5a. When AA's quick block scan said "blocked" and
  its weighted check said "not blocked", the page was saved to
  ``detector_samples/``. A person says which was right.
* ``my-applications`` — item 5b, the human arm of the paired audit. Each
  application the person makes by hand is logged with the gates they met,
  so AA's own record of the same postings can be compared with a person's.
"""

from __future__ import annotations

from auto_apply.domain.models.annotation import Choice, Question, Study

__all__ = ["BLOCK_PAGES", "MY_APPLICATIONS", "STUDIES", "study_by_id"]

#: Answers to block-pages "what" that mean the page really was blocking.
BLOCKING_KINDS: frozenset[str] = frozenset({"challenge", "wall"})
#: Answers that mean it was not.
NOT_BLOCKING_KINDS: frozenset[str] = frozenset({"page", "error"})

BLOCK_PAGES = Study(
    id="block-pages",
    title="Block pages",
    purpose=(
        "AA's two block checks disagreed on these pages. You say what each "
        "page really was, and AA learns which check to trust."
    ),
    version=1,
    item_noun="page",
    questions=(
        Question(
            id="what",
            prompt="What is this page?",
            kind="one",
            choices=(
                Choice(
                    "challenge",
                    "A challenge",
                    "CAPTCHA, 'verify you are human', a puzzle",
                ),
                Choice(
                    "wall",
                    "A wall",
                    "sign in to continue, access denied, account required",
                ),
                Choice(
                    "page", "A normal page", "a job posting, a form, a careers page"
                ),
                Choice("error", "An error page", "404, empty, 'something went wrong'"),
                Choice("unsure", "Can't tell", "the saved copy doesn't show enough"),
            ),
            help="Judge what a person would face on this page, not how it looks saved.",
        ),
        Question(
            id="passable",
            prompt="Could a person get past it by hand?",
            kind="one",
            choices=(
                Choice("yes", "Yes"),
                Choice("no", "No"),
                Choice("unsure", "Can't tell"),
            ),
            ask_if=("what", ("challenge", "wall")),
        ),
        Question(
            id="note",
            prompt="Anything worth remembering? (Enter to skip)",
            kind="text",
            required=False,
        ),
    ),
)

#: Gates a person can meet while applying. Keys line up with AA's own
#: vocabulary where one exists (captcha / login wall in ApplicationEvidence,
#: salary history in form_observations), so the two arms can be compared.
GATE_CHOICES: tuple[Choice, ...] = (
    Choice("account", "Had to create an account or sign in"),
    Choice("email_verify", "Had to verify an email or phone"),
    Choice("captcha", "A CAPTCHA or 'are you human' check"),
    Choice("assessment", "A test, quiz or long questionnaire"),
    Choice("salary_history", "Asked my current or past pay"),
    Choice("salary_expectation", "Asked my expected pay"),
    Choice("demographics", "Asked demographic / EEO questions"),
    Choice("resume_retype", "Re-typed my resume after uploading it"),
    Choice("cover_letter", "A cover letter was required"),
    Choice("redirect", "Sent to a different site to apply"),
    Choice("broken", "Broken link or the posting was gone"),
    Choice("none", "None of these", exclusive=True),
)

MY_APPLICATIONS = Study(
    id="my-applications",
    title="My applications (paired audit)",
    purpose=(
        "Log the applications you make by hand. Your gates, time and outcome "
        "are the human side of the audit AA's own records are measured against."
    ),
    version=1,
    item_noun="application",
    questions=(
        Question(
            id="platform",
            prompt="Where did you apply?",
            kind="one",
            choices=(
                Choice("workday", "Workday"),
                Choice("greenhouse", "Greenhouse"),
                Choice("lever", "Lever"),
                Choice("icims", "iCIMS"),
                Choice("taleo", "Taleo / Oracle"),
                Choice("ashby", "Ashby"),
                Choice("linkedin", "LinkedIn Easy Apply"),
                Choice("indeed", "Indeed Apply"),
                Choice("company_site", "The company's own site"),
                Choice("other", "Somewhere else"),
                Choice("unknown", "Not sure"),
            ),
        ),
        Question(
            id="gates",
            prompt="Which of these did you run into? (pick all that apply)",
            kind="many",
            choices=GATE_CHOICES,
        ),
        Question(
            id="pay_shown",
            prompt="Did the posting show the pay?",
            kind="one",
            choices=(
                Choice("range", "Yes, a range"),
                Choice("single", "Yes, one number"),
                Choice("none", "No"),
            ),
        ),
        Question(
            id="location",
            prompt="Location exactly as the posting wrote it (Enter to skip)",
            kind="text",
            required=False,
            help="AA checks its own location reader against what you type.",
        ),
        Question(
            id="minutes",
            prompt="About how many minutes did it take?",
            kind="number",
        ),
        Question(
            id="outcome",
            prompt="How did it end?",
            kind="one",
            choices=(
                Choice("submitted", "Submitted"),
                Choice("gave_up", "I gave up"),
                Choice("blocked", "Something stopped me"),
                Choice("not_finished", "Not finished yet"),
            ),
        ),
        Question(
            id="note",
            prompt="Anything worth remembering? (Enter to skip)",
            kind="text",
            required=False,
        ),
    ),
)

STUDIES: tuple[Study, ...] = (BLOCK_PAGES, MY_APPLICATIONS)


def study_by_id(study_id: str) -> Study:
    for study in STUDIES:
        if study.id == study_id:
            return study
    raise KeyError(study_id)
