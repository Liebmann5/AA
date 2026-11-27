---
title: Adding or Reviewing a Form Language
status: needs-review
last_verified: 2026-11-21
verified_against: "domain/applications/form_lexicon.py, domain/applications/form_language.py, tests/domain/test_form_lexicon.py, resources/locales/"
audience: contributors
---

# Adding or Reviewing a Form Language

AA reads application forms through one data file of words,
`src/auto_apply/domain/applications/form_lexicon.py`
([ADR-025](../adr/025_forms_in_any_language.md)). Adding a language, or
reviewing one, means editing that file. No code changes.

There are two separate kinds of language work in AA:

| You want AA to… | Edit |
|---|---|
| read forms written in a language | `domain/applications/form_lexicon.py` |
| speak to the person in a language | `resources/locales/<code>.json` (copy `en.json`) |

## The one rule that matters

Each class is **safety** or **permissive**:

* a **safety** word makes AA more careful (it asks the person). A wrong safety
  word costs a question. When unsure whether a word means "send", or names a
  topic only the person may answer, include it;
* a **permissive** word lets AA act on its own: click "next", fill a field from
  the profile. A wrong permissive word makes AA act wrongly. **When unsure,
  leave it out** — a missing word only makes AA ask.

The classes, and which is which, are listed at the top of
`form_lexicon.py`.

## Steps

1. Add your language under its ISO 639-1 code, copying the classes from
   English that you can fill truthfully. Write words naturally, with their
   accents: matching folds case and accents away.
2. Use the term syntax when a plain word is not enough:
   * `word*` — any word starting with `word` (Turkish, Finnish and other
     languages that add endings);
   * `*stem*` — `stem` inside a longer word (German and Dutch compounds);
   * `!term` — the whole label is exactly `term` (a one-character label);
   * `=Word` — case matters.
   Chinese, Japanese, Korean, Thai, Lao, Khmer and Myanmar terms are found
   anywhere in the text automatically.
3. For `yes` and `no`, list the words that make up a whole answer ("Ja",
   "Nein"). A word that means yes in one language and no in another fails the
   pins.
4. For `step` and `step_connector`, list your language's word for "step" and
   the word between the numbers ("von" in "Schritt 2 von 4").
5. For the application-flow classes (ADR-026): `assessment` (a test or
   assessment), `must_complete` ("must be completed before we review"),
   `choose` ("pick", "select"), `exactly`, and the permissive `at_most` ("up
   to"), `at_least`, `or_more` and `all_that_apply`. Add your number words to
   `NUMBER_WORDS` (index 0 is one). An `at_most` word that could also mean
   "exactly" must be left out: it would let AA tick fewer or more than asked.
6. Set your language in `REVIEW`: `unreviewed` if you wrote it from a
   dictionary, `reviewed` if a native speaker checked it.
7. Bump `LEXICON_VERSION` (today's date, then a counter).
8. Run the pins:

   ```bash
   cd packages/auto_apply
   ../../.venv/bin/python -m pytest tests/domain/test_form_lexicon.py tests/domain/test_form_language.py tests/domain/test_selection_limits.py tests/domain/test_external_steps.py -q -p no:cacheprovider
   ```

## Reviewing a language

Read your language's block and check, for each class, that every word means
what its class says *on a job application form*. Pay most attention to
`next` (a word that could also mean "send" there must be removed) and to the
`field.*` classes (a word that names two different fields must be removed).
Then set `REVIEW` to `reviewed`.
