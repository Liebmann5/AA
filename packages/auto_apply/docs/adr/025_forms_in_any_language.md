---
title: "ADR-025: Application Forms in Any Language — Structure, Words, the Person"
status: needs-review
last_verified: 2026-11-21
verified_against: "domain/applications/form_lexicon.py, domain/applications/form_language.py, domain/applications/form_localization.py, domain/applications/option_matching.py, domain/applications/answers.py, application/services/form_engine.py, adapters/secondary/perception/pagecomp_form.py; tests/domain/test_form_lexicon.py, test_form_language.py, test_form_localization.py, tests/integration/test_form_engine_browsers.py::test_a_german_two_step_form (Playwright and Selenium, local fixtures only)"
audience: contributors
---

# ADR-025: Application Forms in Any Language — Structure, Words, the Person

**Status:** Proposed — built and pinned against local fixtures; the word lists
for languages other than English await native-speaker review; not yet proven
on live sites `[BUILT]`
**Date:** 2026-11-21
**Deciders:** Nicholas Liebmann
**Related:** [ADR-023](023_application_step_engine.md) (the engine),
[ADR-024](024_accessibility_accommodations.md) (the person's side of the same
work), [pagecomp BLUEPRINT](../pagecomp/BLUEPRINT.md) (CT-NFR-021: structure
first, lexicons only add evidence), [adding a form language](../developer_guide/adding_a_form_language.md)

---

## Context

Until this decision the engine's words were English (recorded as E2E-X1):
which control sends the application, which questions only the person may
answer, which answers belong to one employer, yes and no, placeholders, step
indicators. On a German form AA could not tell "Absenden" was a submit
control, would not have known "Staatsangehörigkeit" was a question only the
person answers, and could not read "Schritt 2 von 4". A tool meant for every
job seeker reads every employer's form, in whatever language it is written.

The two directions of error are not equal. Misreading a word as *safer* than
it is ("Envoyer" read as harmless) can send an application or answer a
protected question; misreading a word as *riskier* only makes AA ask the
person. The design follows from that asymmetry.

## Decision

### 1. Three layers, in the order AA trusts them

1. **Structure, in every language.** Markup needs no lexicon: `autocomplete`
   tokens, input types, `required`/`aria-required`, `aria-current="step"`, and
   option *values* such as ISO country codes. The reader (pagecomp) already
   uses structure first; the adapter now also reports the declared `lang`, the
   `aria-current="step"` position, and short visible texts holding exactly two
   numbers (any digits) for the language layer to read.
2. **Words, as data** (`form_lexicon.py`, read by `form_language.py`).
3. **The person.** What neither settles is asked — in AA's window, with the
   form's own words shown as written. **AA never translates a question it is
   going to answer.**

### 2. Safety words everywhere, permissive words only where the page is

Every class of words is either:

* **safety** — a match makes AA more careful: `submit`, `not_submit`, `back`,
  `protected`, `company_relative`, `answer_company_relative`, `open_ended`,
  `decline`, `placeholder`, `required`, `yes`/`no`. These are matched **in
  every language at once**, whatever the page claims: a French "Envoyer" on a
  page declared English still stops AA;
* **permissive** — a match lets AA act alone: `next` (click unconfirmed),
  `field.<type>` (fill from the profile), `optional`, `step`,
  `step_connector`. These are matched only in the step's **candidate
  languages**: the declared `lang` of the form (or document), every language
  whose *own* words appear at least twice on the step (a word several
  lexicons share, such as "email" or "telefon", proves nothing), the
  languages of the dominant writing system (Hangul → Korean), and English.

Pages often declare the wrong language (a template's `lang="en"` over a German
form) or none; the evidence count corrects the first and the script rule
helps with the second. A language AA has no words for degrades to structure
plus the person.

### 3. What the words decide

`form_localization.localize_step` applies the words to each step the engine
reads, whatever perception produced it (an agnostic seam: it runs in the
engine, not the adapter), and records every change as evidence:

* **buttons** — a control the reader left unclassified, or called submit only
  because of its HTML type, whose text is a "next" word of a candidate
  language ("Avanti", "Далее", "次へ") becomes `next` (`role_source =
  lexicon(it)`), exactly as the reader treats "Next". Never when its text also
  says it sends something in any language, and never for a "review" word
  ("Überprüfen", "確認画面へ" keep the reader's verdict and are confirmed, as
  "Review" is). The engine's own rule still applies: a submit-type Next is
  clicked unconfirmed only when the step position (structure or a same-language
  "Step N of M") shows more steps follow;
* **field types** — a question the reader typed only by its widget gets the
  type its label names in a candidate language; structural types are never
  overridden; long labels stay questions;
* **one bare "name" beside its other half** becomes that half ("Prénom" +
  "Nom", "Nombre" + "Apellidos", "Vorname" + "Name");
* **requiredness** — an UNKNOWN question with a required word in any language
  becomes REQUIRED; an optional word in a candidate language makes it OPTIONAL;
* **step position** — from `aria-current="step"`, or a short text with a step
  word, exactly two numbers, and a slash or connector of the **same** language
  as the step word ("Schritt 2 von 4", "第2步，共4步", "4단계 중 2단계"). The
  smaller number is the step, so the order languages put them in does not
  matter; any decimal digits are read.

Elsewhere: protected questions (`answers.is_protected`), company-specific
memory scoping, yes/no option polarity, "prefer not to say", placeholders and
the submit rule (`FormButton.may_submit`) all use the safety classes. A legal
yes/no (work authorisation, sponsorship) is answered from the profile only
when AA can read the question in English, whose negative-phrasing and
country rules it has, **and** the form can be in no other language (the
engine passes the step's candidate languages to every answer source as
`AnswerContext.form_locales`): an English loanword such as "Visa-Sponsoring"
in a German question does not make the question English, because its
negation ("kein") is German. Otherwise the person answers it.

### 4. Folding and matching

Text is compared after `form_language.fold`: NFKC (full-width forms,
ligatures), case-folded (`ß` → `ss`, Turkish `İ` → `i`), accents removed from
Latin, Greek, Arabic and Hebrew letters, Russian `ё` read as `е`,
bidirectional and zero-width controls dropped, punctuation read as a space.
Marks that belong to the word in other scripts (Devanagari vowel signs, Thai
tone marks, Japanese voicing) are kept. Terms written in Chinese, Japanese,
Korean, Thai, Lao, Khmer or Myanmar script are found anywhere in the text;
`!term` means the whole text (a lone 名 is "given name", 会社名 is not);
`*stem*` finds German compounds; `=Word` is case-sensitive (English "us", not
"US"). A word that would mean yes in one language and no in another is never
used (pinned: the sets are disjoint).

### 5. Options by code, and the person's words untranslated

`match_option` reads an option's `value` as well as its label: a country or
state listed by ISO code is matched in any language. A country named only in
another language with no code is not matched — the person is asked. When the
form is in another language than AA speaks to the person in, the prompt says
so and shows the questions as the form words them (ADR-024).

### 6. Evidence

Each question records how its meaning was known (`structure`,
`lexicon(<lang>)`, `widget`), and each attempt records the declared language,
the candidate languages, and `LEXICON_VERSION` (`ApplicationEvidence`:
`question_typing`, `form_language`, `form_locales`, `lexicon_version`): the
form's language coverage, and which word lists produced each decision.

## Coverage

English is the baseline AA was built and tested on. German, French, Spanish,
Italian, Portuguese, Dutch, Polish, Swedish, Danish, Norwegian (Bokmål),
Finnish, Czech, Turkish, Russian, Ukrainian, Japanese, Chinese, Korean,
Arabic, Hebrew, Hindi, Indonesian and Vietnamese have word lists written from
standard vocabulary and marked **unreviewed** in `form_lexicon.REVIEW` until a
native speaker reviews them. Languages with no word list (Greek, Thai, and
most of the world's languages) are read by structure, and everything else is
asked.

## Consequences

* A form in a covered language is filled as an English one is; a form in any
  language is never made less safe by its language.
* The reader's own small vocabulary and AA's lexicon are deliberately
  separate — perception evidence and decision rules — and a pin keeps every
  word the reader treats as navigation or submission known to AA in the same
  sense (`test_every_reader_navigation_or_submit_word_is_known_to_aa`).
* Translators extend one data file; the pins check its syntax.

## Limits and open work

* No native speaker has reviewed the non-English lists.
* Country and state names in other languages are matched only through option
  codes (a CLDR-derived table, or the optional Babel package, could add names;
  both bring licensing and size questions to settle first).
* AA's own interface ships in English and Spanish only (`resources/locales`);
  right-to-left layout of AA's windows is not addressed.
* Dates and numbers typed into a form are entered as the profile holds them;
  locale-specific date formats are not converted.
* A form that declares no language and shows none of the words AA knows in
  another language reads as English; a legal question on it is still
  answered from the profile only when its own words are English.

## Verification

`tests/domain/test_form_lexicon.py`, `tests/domain/test_form_language.py`,
`tests/domain/test_form_localization.py`, `tests/domain/test_option_matching.py`,
`tests/domain/test_application_answers.py` (legal questions in other languages and
on forms that may be in another language),
`tests/application/test_accessibility_language_pins.py`,
`tests/application/test_form_engine.py` (German step indicators and prompts),
and in real browsers `test_a_german_two_step_form` (declared German, no
autocomplete tokens, a submit-type "Fortfahren" clicked without confirmation
because "Schritt 1 von 2" shows another step, ISO codes behind German country
names, the gender question asked of the person).
