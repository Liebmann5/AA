"""
Defines the data structure for a
single job posting found during a
search
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class SearchResult:
    """
    A standardized, immutable data
    structure for a found job posting.

    Using a dataclass provides type
    hints, makes the object immutable
    (frozen=True)
    to prevent accidental
    modification, and provides a clear
    structure for
    what constitutes a result.
    """
    url: str
    title: str
    company: str
    source: str