---
title: "Labelling: Teaching AA What Is True"
status: reviewed
last_verified: 2026-10-02
verified_against: "src/auto_apply/adapters/primary/cli/labeller.py, application/services/labelling.py, domain/services/annotation_studies.py at item 5"
audience: users
---

# Labelling: teaching AA what is true

AA makes judgements all the time: *this page is a CAPTCHA*, *this posting is
in Colorado*. A judgement is only as good as its error rate, and an error rate
needs ground truth: a person saying what was actually there. The labelling
tool is how you give AA that ground truth, a few minutes at a time.

```bash
python -m auto_apply --label
```

It starts no job search and drives no browser. It shows a menu of studies,
asks you questions, and saves each answer the moment you give it. You can quit
whenever you like and pick up where you left off.

## The two studies

### Block pages

When AA's quick block scan says a page is **blocked** and its weighted check
says it is **not**, AA saves the page to `detector_samples/` in its data
directory. You decide which check was right.

For each page:

1. A **safe copy** opens in your browser. Every script, frame, redirect and
   remote load is removed, and the copy is locked so it cannot contact any
   site. What you see is the page's text and layout.
2. You answer **What is this page?**: a challenge, a wall, a normal page, an
   error page, or *can't tell*. For a challenge or a wall, you also answer
   whether a person could get past it by hand.
3. Only then does AA show what its two checks said, and which one you agreed
   with.

### My applications (the paired audit)

Log each application you make **by hand**: the link, the platform, which gates
you ran into (account creation, CAPTCHA, pay-history questions…), whether the
posting showed pay, the location as written, how long it took, and how it
ended. This is the human side of the paired audit. AA's own records of the
same kind of postings are measured against it.

After each one, AA reads the location you typed with its own location reader
and tells you what it understood. If it got the location wrong, say so in the
note, and that location becomes a test case.

## Why you never see AA's answer first

If you saw "AA says: BLOCKED" before answering, you would lean towards it, and
the labels would measure your agreement with AA instead of AA's accuracy. This
is called anchoring. Every study is therefore **blind**: AA's conclusion
appears only after your answer is saved.

## Keys

| Key | What it does |
| --- | --- |
| a number | picks that choice |
| several numbers (`1 3 5`) | picks all of them, for "pick all that apply" |
| `s` | skips this one; it comes back after the rest |
| `o` | opens the saved page again |
| `q` | saves and quits |

## Insights

Choose `i` from the menu, or finish a study, to see what your labels show so
far. Every rate is given with its count, its denominator and a 95% confidence
interval, for example "The quick scan was right on 6 of 18 (33%, 95% CI
16–56%)". Twenty pages give wide intervals, and every page you add narrows
them. Pages marked *can't tell* are counted and reported, never quietly left
out.

## Where the labels live

In the `annotations/` folder of AA's data directory, one file per study:

- `block-pages.labels.jsonl`
- `my-applications.items.jsonl` and `my-applications.labels.jsonl`
- `_view/` — the safe copies of saved pages, which can be deleted at any time

Each line is one answer in plain JSON, so you can open the files in any text
editor. Nothing is ever overwritten. A changed answer is a new line, and the
newest line counts. The files are your own data, kept in AA's data directory,
outside the repository.

## Adding a study

A study is data: a title, a purpose, a version and its questions, defined in
`domain/services/annotation_studies.py`. A study whose items AA already saved
somewhere also needs an item source (see `DetectorSampleSource`). A study
where you add the items yourself, like *My applications*, needs nothing more.

Change a question's wording freely. If you change what a question **means**,
or its choices, raise the study's `version`. Answers given to an older version
are kept on disk, but they are never mixed into the new version's numbers.
