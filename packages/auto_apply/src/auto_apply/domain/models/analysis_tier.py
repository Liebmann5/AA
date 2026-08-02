
"""The extraction tier a page is analysed with.

Lives in the domain because it is a shared vocabulary, not an implementation
detail of the router: Discovery, Vetting and Applications all need to name a
tier, and an adapter must be able to honour a forced one without importing an
application service.

Tiers are ordered cheapest to most expensive. The router picks one per page;
``force_analysis_tier`` in config pins every page to a single tier instead,
which is what makes a deterministic comparison between tiers possible.
"""

from enum import Enum, auto


class PageAnalysisTier(Enum):
    """Analysis tiers ordered from cheapest to most expensive."""

    STRUCTURED_DATA = auto()    # JSON-LD present -> skip scraping
    KNOWN_PLATFORM = auto()     # Known ATS with explicit selectors
    CSS_EXTRACTION = auto()     # DOMScanner + FieldClassifier
    FULL_MATH_DOM = auto()      # MathDOM + Hungarian

    @classmethod
    def from_name(cls, name: str | None) -> "PageAnalysisTier | None":
        """Parse a config value into a tier, tolerantly.

        Args:
            name: A tier name such as ``"FULL_MATH_DOM"``. Case and surrounding
                whitespace are ignored. Empty, missing or unrecognised values
                return None, which means "do not force a tier" — a typo in
                config must not be able to pin extraction to something
                unintended, and must never raise during startup.

        Returns:
            The matching tier, or None.
        """
        if not name:
            return None
        key = str(name).strip().upper()
        return cls.__members__.get(key)
