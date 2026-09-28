"""Pure string derivations for job-posting research observations.

These three helpers were moved here verbatim from ``DiscoveryWorkflow``
(application/workflows/discovery_workflow.py), where they lived as
``@staticmethod`` members reachable only through a sibling workflow;
``ApplicationsWorkflow`` carried a second, body-identical copy of
``_infer_jurisdiction``. One definition of each now lives in the domain,
where every workflow can reach it without importing another workflow.

They are pure string→string mappings: no I/O, no state, no imports outside
the stdlib. "Verbatim" includes two known substring-matching warts, which a
later item owns fixing deliberately:

* ``infer_jurisdiction("Chicago, IL")`` returns ``"CA"`` — "ca" is a
  substring of "chicago" and the CA clause is checked first.
* ``infer_jurisdiction("Washington, DC")`` returns ``"WA"`` — the
  "washington" term matches the WA clause before the DC clause is reached.

tests/workflows/test_posting_observation.py pins the exact current
behaviour — warts included and labelled — so the future fix is a visible,
deliberate change rather than silent drift.
"""
from __future__ import annotations

from urllib.parse import urlparse


def infer_jurisdiction(location: str) -> str | None:
    """Map a raw location string to a jurisdiction code used in pay_transparency_laws.yaml.

    Returns None if no match can be confidently made.
    """
    if not location:
        return None
    loc = location.lower()
    # State / city shorthand matches
    if any(term in loc for term in ("ca", "california", "san francisco", "los angeles", "san diego")):
        return "CA"
    if any(term in loc for term in ("ny", "new york", "nyc", "brooklyn", "queens", "manhattan")):
        return "NYC"
    if any(term in loc for term in ("wa", "washington", "seattle")):
        return "WA"
    if any(term in loc for term in ("co", "colorado", "denver")):
        return "CO"
    if any(term in loc for term in ("il", "illinois", "chicago")):
        return "IL"
    if any(term in loc for term in ("md", "maryland", "baltimore")):
        return "MD"
    if any(term in loc for term in ("hi", "hawaii", "honolulu")):
        return "HI"
    if any(term in loc for term in ("dc", "washington dc", "washington d.c.")):
        return "DC"
    if any(term in loc for term in ("nj", "new jersey", "newark")):
        return "NJ"
    if any(term in loc for term in ("ma", "massachusetts", "boston")):
        return "MA"
    if any(term in loc for term in ("mn", "minnesota", "minneapolis")):
        return "MN"
    return None


def infer_metro_area(location: str) -> str | None:
    """Map a location string to a Metropolitan Statistical Area (MSA) key used in col_index.yaml.

    Returns the exact dictionary key expected by the cost-of-living data, or None if no match.
    """
    if not location:
        return None
    loc = location.lower()
    # Prioritize more specific matches first
    mapping = {
        ("san francisco", "sf bay", "bay area"): "San Francisco-Oakland-Berkeley, CA",
        ("san jose", "silicon valley"): "San Jose-Sunnyvale-Santa Clara, CA",
        ("new york", "nyc", "brooklyn", "queens", "manhattan"): "New York-Newark-Jersey City, NY-NJ",
        ("los angeles", "la", "santa monica", "culver city"): "Los Angeles-Long Beach-Anaheim, CA",
        ("seattle", "bellevue"): "Seattle-Tacoma-Bellevue, WA",
        ("boston", "cambridge", "somerville"): "Boston-Cambridge-Newton, MA-NH",
        ("washington", "dc", "arlington", "alexandria"): "Washington-Arlington-Alexandria, DC-VA-MD-WV",
        ("san diego",): "San Diego-Chula Vista-Carlsbad, CA",
        ("denver", "aurora", "boulder"): "Denver-Aurora-Lakewood, CO",
        ("austin", "round rock", "georgetown"): "Austin-Round Rock-Georgetown, TX",
        ("chicago",): "Chicago-Naperville-Elgin, IL-IN-WI",
        ("portland",): "Portland-Vancouver-Hillsboro, OR-WA",
        ("miami", "fort lauderdale", "pompano"): "Miami-Fort Lauderdale-Pompano Beach, FL",
        ("atlanta", "sandy springs", "alpharetta"): "Atlanta-Sandy Springs-Alpharetta, GA",
        ("dallas", "fort worth", "arlington"): "Dallas-Fort Worth-Arlington, TX",
        ("phoenix", "mesa", "chandler"): "Phoenix-Mesa-Chandler, AZ",
        ("minneapolis", "st paul", "bloomington"): "Minneapolis-St. Paul-Bloomington, MN-WI",
        ("philadelphia", "camden", "wilmington"): "Philadelphia-Camden-Wilmington, PA-NJ-DE-MD",
        ("charlotte", "concord", "gastonia"): "Charlotte-Concord-Gastonia, NC-SC",
        ("raleigh", "cary"): "Raleigh-Cary, NC",
        ("nashville", "murfreesboro", "franklin"): "Nashville-Davidson--Murfreesboro--Franklin, TN",
        ("columbus",): "Columbus, OH",
        ("indianapolis", "carmel", "anderson"): "Indianapolis-Carmel-Anderson, IN",
        ("pittsburgh",): "Pittsburgh, PA",
        ("st louis", "st. louis"): "St. Louis, MO-IL",
        ("cincinnati",): "Cincinnati, OH-KY-IN",
        ("cleveland", "elyria"): "Cleveland-Elyria, OH",
        ("detroit", "warren", "dearborn"): "Detroit-Warren-Dearborn, MI",
        ("kansas city",): "Kansas City, MO-KS",
        ("memphis",): "Memphis, TN-MS-AR",
        ("oklahoma city",): "Oklahoma City, OK",
        ("birmingham", "hoover"): "Birmingham-Hoover, AL",
    }
    for keywords, msa in mapping.items():
        if any(kw in loc for kw in keywords):
            return msa
    return None


def looks_like_generic_apply_url(url: str) -> bool:
    """Detect if an 'Apply' link is broken or just drops the user on a homepage.

    Returns True if the URL scheme is mailto: or the path is empty / root.
    """
    if not url:
        return False
    try:
        parsed = urlparse(url)
        if parsed.scheme == "mailto":
            return True
        # Normalize path to remove trailing slash
        path = parsed.path.rstrip("/")
        if not path or path == "":
            return True
        return False
    except Exception:
        return False
