---
title: "Building a Search"
status: needs-review
last_verified: 2026-10-28
verified_against: "application/services/query_builder.py, adapters/primary/cli/search_builder_screen.py, adapters/primary/gui/search_window.py"
audience: users
---

# Building a Search

The query builder composes a search you run yourself, in your own browser. It
automates nothing: it never opens a page, never logs in, and never applies
anywhere. It writes the search-bar text and a link for the site you choose,
and then you decide what to do with them.

## What it is for

AA's automated discovery is the agent's job. The builder is the opposite: a
way for you to write a precise search by hand — one site, one hiring platform,
or one company's careers page — using only the syntax AA has verified for that
site. You get exactly what the site supports, and anything it cannot express
is refused or noted in plain words, never silently dropped.

## Search-bar text versus the link

Most sites give you two forms of the same search:

- **Search-bar text** — what you paste into the site's own search box.
- **A link** — the same search as a web address you can open or share.

Some settings exist **only in the link** — there is nothing you can type that
does the same thing. Google's "newer than 24 hours" filter is the example:
the link carries it (`tbs=qdr:d`); the nearest thing you can type is
`after:2026-01-01`, which is a fixed date, not a rolling window. When a
setting is link-only, the builder says so.

## What the platform labels mean

Every hiring platform in the picker records how well its search restriction is
verified:

- **No label** — measured by hand, or vendor-documented.
- **Unverified** — recorded from a sample URL but not yet hand-measured.
- **Third-party** — reported by others, not yet confirmed by AA.

A platform's status is raised by a person, not by AA: follow the checklist in
[Verifying Platform Search Data](../developer_guide/verifying_platform_search.md)
— paste the query, check the results are all from that platform, and record
the outcome in the platform's descriptor.

## Recent searches

The builder remembers your five most recent searches, but **only** when you
copy, open, or keep one — never as you type. They are stored as plain text in
`query_builder_recent.json` inside AA's data folder (the same folder as your
logs and reports). "Clear recent" forgets all of them. Uninstalling AA removes
the file with the rest of the data folder.

## The two ways in

- **GUI:** File → Build a Search… . Works before you have a profile or a
  session. Pick an engine, choose what to search within (everything it finds,
  a hiring platform, or one company), and the result previews as you type.
- **CLI:** `python -m auto_apply --search`, or the scripted
  `--search-*` flags. The full flag list is in the
  [command-line reference](../reference/cli.md).

Both produce the same search and remember it the same way — that is pinned by
the test suite, not just intended.
