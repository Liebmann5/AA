"""Pins: vetting judges a title against what the user asked for (the
profile's titles AND the title this session searched for), and a title that
names a target role in full matches it (domain/vetting/title_targets.py).

Owner run 2026-11-08: a session searching "Software Engineer" rejected
a Cloudflare "Software Engineer - Load Balancing" posting as "Low Relevance"
against a profile listing "Backend Engineer" and "Fullstack Engineer";
difflib rated "Senior Software Engineer, Backend" below 0.6 for "Backend
Engineer".
"""
from __future__ import annotations

from difflib import SequenceMatcher

import pytest

from auto_apply.domain.models.job import Job
from auto_apply.domain.vetting.logic_filters import TitleLogicFilter
from auto_apply.domain.vetting.role_alignment_filter import RoleAlignmentFilter
from auto_apply.domain.vetting.title_targets import names_role, target_titles


@pytest.fixture
def backend_profile(minimal_valid_profile):
    minimal_valid_profile.search_preferences.desired_job_titles = [
        "Backend Engineer", "Fullstack Engineer",
    ]
    return minimal_valid_profile


def _job(title: str, searched: str = "") -> Job:
    job = Job(title=title, company="Cloudflare", source="google",
              url="https://boards.greenhouse.io/cloudflare/jobs/7012345")
    if searched:
        job.metadata["search_title"] = searched
    return job


class _Similarity:
    """difflib, the measure the live filter fell back on."""

    def get_similarity(self, a: str, b: str) -> float:
        return SequenceMatcher(None, a.lower(), b.lower()).ratio()


@pytest.mark.parametrize(
    "title,target,named",
    [
        ("Senior Software Engineer, Backend", "Backend Engineer", True),
        ("Software Engineer - Load Balancing", "Software Engineer", True),
        ("Junior Python Dev at Google", "Python Dev", True),
        ("Backend Developer", "Backend Engineer", False),
        ("Engineering Manager", "Software Engineer", False),
        ("C++ Engineer", "C++ Engineer", True),
        ("Anything", "", False),
    ],
)
def test_a_title_names_a_role_when_it_holds_every_word_of_it(title, target, named):
    assert names_role(title, target) is named


def test_the_searched_title_joins_the_profile_titles_once(backend_profile):
    job = _job("x", searched="software engineer")
    assert target_titles(backend_profile, job) == [
        "Backend Engineer", "Fullstack Engineer", "software engineer",
    ]
    again = _job("x", searched="Backend engineer")
    assert target_titles(backend_profile, again) == ["Backend Engineer", "Fullstack Engineer"]


def test_the_title_filter_accepts_the_role_the_session_searched_for_teeth(backend_profile):
    """TEETH: difflib rates this title 0.34 and 0.36 against the profile's
    two titles, under the 0.4 floor, so it was rejected as low relevance."""
    job = _job("Software Engineer - Load Balancing at Cloudflare", searched="Software Engineer")
    assert TitleLogicFilter(backend_profile).check(job) == (True, "Title Match")


def test_the_role_filter_accepts_a_longer_title_that_names_the_role_teeth(backend_profile):
    """TEETH: difflib scored the pair below the 0.6 threshold."""
    job = _job("Senior Software Engineer, Backend")
    assert _Similarity().get_similarity(job.title, "Backend Engineer") < 0.6
    passed, reason = RoleAlignmentFilter(backend_profile, _Similarity()).check(job)
    assert passed and reason == "role_ok:names 'Backend Engineer'"


def test_an_unrelated_title_is_still_rejected(backend_profile):
    job = _job("Account Executive, Enterprise Sales", searched="Software Engineer")
    assert TitleLogicFilter(backend_profile).check(job)[0] is False
    assert RoleAlignmentFilter(backend_profile, _Similarity()).check(job)[0] is False


def test_negative_keywords_still_win_over_a_named_role(backend_profile):
    """Containment does not bypass the hard block for entry-level users."""
    backend_profile.search_preferences.experience_level = ["Entry Level"]
    job = _job("Senior Software Engineer, Backend", searched="Software Engineer")
    passed, reason = TitleLogicFilter(backend_profile).check(job)
    assert not passed and "senior" in reason
