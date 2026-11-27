"""Pins for reading a posting's own JSON-LD (PagecompPostingReader)."""
from __future__ import annotations

import json

from auto_apply.adapters.secondary.perception.pagecomp_posting import (
    PagecompPostingReader,
)
from auto_apply.domain.ports.structured_posting_port import StructuredPostingPort


def _ld(*postings: dict) -> str:
    blocks = "".join(
        f'<script type="application/ld+json">{json.dumps(p)}</script>' for p in postings
    )
    return f"<html><head>{blocks}</head><body>x</body></html>"


def _posting(title: str, jid: str, company: str = "Acme") -> dict:
    return {
        "@context": "https://schema.org", "@type": "JobPosting", "title": title,
        "hiringOrganization": {"@type": "Organization", "name": company},
        "url": f"https://boards.greenhouse.io/acme/jobs/{jid}",
        "jobLocationType": "TELECOMMUTE",
        "applicantLocationRequirements": {"@type": "Country", "name": "USA"},
    }


def test_the_reader_satisfies_the_port():
    assert isinstance(PagecompPostingReader(), StructuredPostingPort)


def test_one_posting_is_read():
    facts = PagecompPostingReader().read(_ld(_posting("Backend Engineer", "4012345")),
                                         "https://boards.greenhouse.io/acme/jobs/4012345")
    assert facts is not None
    assert (facts.title, facts.company, facts.remote) == ("Backend Engineer", "Acme", True)


def test_of_several_postings_only_the_pages_own_is_taken():
    html = _ld(_posting("Backend Engineer", "4012345"), _posting("Designer", "4099999"))
    facts = PagecompPostingReader().read(html, "https://careers.acme.example/jobs?gh_jid=4099999")
    assert facts is not None and facts.title == "Designer"


def test_an_unresolvable_choice_reads_nothing():
    """Guessing among a board's postings would put another job's facts on
    this one."""
    html = _ld(_posting("Backend Engineer", "4012345"), _posting("Designer", "4099999"))
    assert PagecompPostingReader().read(html, "https://careers.acme.example/jobs") is None


def test_no_structured_data_and_bad_input_read_nothing():
    reader = PagecompPostingReader()
    assert reader.read("<html><body>Backend Engineer</body></html>", "https://x.example/") is None
    assert reader.read("", "https://x.example/") is None
    assert reader.read("<script type='application/ld+json'>{not json", "https://x.example/") is None
