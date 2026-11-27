"""Which roles a job is judged against, and when a title names one.

One rule for the title filters (TitleLogicFilter and RoleAlignmentFilter),
so they cannot disagree about what the user asked for.

What the user asked for is the profile's ``desired_job_titles`` AND the
title this session searched for. A session's search keywords override the
profile for discovery (SessionController._seed_search_tasks). Before this
module, vetting still judged only the profile's titles: on 2026-11-08 a
session searching "Software Engineer" rejected "Software Engineer - Load
Balancing at Cloudflare" as "Low Relevance" against a profile listing
"Backend Engineer" and "Fullstack Engineer". Discovery stamps the searched
title on each job as ``metadata["search_title"]``.

A title NAMES a target role when every word of the target appears in it
("Backend Engineer" in "Senior Software Engineer, Backend"). Character
similarity alone penalises the longer, more specific titles postings use:
difflib rates that pair below 0.6. Containment is a deterministic statement
about the words, so it is checked first; similarity decides the rest.
"""
from __future__ import annotations

import re
from typing import Any

_WORD = re.compile(r"[a-z0-9+#]+")


def title_words(text: str) -> frozenset[str]:
    """The lower-case words of a title (letters, digits, ``+`` and ``#``)."""
    return frozenset(_WORD.findall((text or "").lower()))


def names_role(job_title: str, target: str) -> bool:
    """True when every word of *target* appears in *job_title*."""
    target_words = title_words(target)
    return bool(target_words) and target_words <= title_words(job_title)


def target_titles(profile: Any, job: Any) -> list[str]:
    """The roles *job* is judged against: the profile's desired titles, then
    the title this job was searched for. Case-insensitive duplicates and
    blanks are dropped; order is kept."""
    prefs = getattr(profile, "search_preferences", None)
    titles = list(getattr(prefs, "desired_job_titles", None) or [])
    metadata = getattr(job, "metadata", None)
    if isinstance(metadata, dict):
        searched = str(metadata.get("search_title") or "").strip()
        if searched:
            titles.append(searched)
    seen: set[str] = set()
    out: list[str] = []
    for title in titles:
        key = str(title or "").strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(str(title).strip())
    return out
