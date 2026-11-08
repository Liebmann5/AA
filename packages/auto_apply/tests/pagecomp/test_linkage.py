"""Record linkage: resolution without a visit, de-duplication, arrival by identifier."""

from __future__ import annotations

import math

from pagecomp import linkage as K

ZACT_CRUMB = K.key_from_breadcrumb("zact-inc.breezy.hr", "4151651bd442-senior-backe...", "Senior Backend Engineer")
ZACT_URL = K.key_from_url("https://zact-inc.breezy.hr/p/4151651bd442-senior-backend-engineer",
                          "Senior Backend Engineer at Zact")


def test_shown_identifier_links_opaque_to_direct():
    links, open_ = K.link([ZACT_CRUMB], [ZACT_URL])
    assert len(links) == 1 and not open_
    assert links[0].right.url.endswith("4151651bd442-senior-backend-engineer")
    assert links[0].bits >= links[0].threshold


def test_truncated_identifier_counts_only_shown_characters():
    cut = K.key_from_breadcrumb("zact-inc.breezy.hr", "4151651b...", "")
    c = K.compare(cut, ZACT_URL)
    assert c is not None and abs(c.bits - (8 * 4.0 - 8.0)) < 1e-9


def test_title_alone_never_links_in_a_block_of_two():
    a = K.key_from_breadcrumb("inallmedia-llc.breezy.hr", "...", "Backend Software Engineer (Applied AI)")
    b1 = K.key_from_url("https://inallmedia-llc.breezy.hr/p/1cd2daa5e5f6-backend-software-engineer-applied-ai",
                        "Backend Software Engineer (Applied AI)")
    b2 = K.key_from_url("https://inallmedia-llc.breezy.hr/p/ec88bd244eda-backend-engineer-1808", "Backend Engineer")
    links, open_ = K.link([a], [b1, b2])
    assert not links and open_ == [a]


def test_different_companies_on_one_ats_are_never_compared():
    other = K.key_from_url("https://onedome.breezy.hr/p/4151651bd442-x", "Senior Backend Engineer")
    assert K.compare(ZACT_CRUMB, other) is None


def test_different_identifiers_mean_different_postings_reposts():
    repost = K.key_from_url("https://zact-inc.breezy.hr/p/9999aaaa1111-senior-backend-engineer",
                            "Senior Backend Engineer")
    c = K.compare(ZACT_URL, repost)
    assert c is not None and c.bits < 0


def test_threshold_is_the_union_bound():
    assert math.isclose(K.threshold(1, 1e-3), math.log2(1000))
    assert math.isclose(K.threshold(1024, 1e-3), 10 + math.log2(1000))


def test_apply_variant_and_cross_engine_copies_dedupe():
    keys = [K.key_from_url(u, "Senior Backend Engineer") for u in (
        "https://volt-labs-inc.breezy.hr/p/236071a7c66a-senior-backend-engineer",
        "https://volt-labs-inc.breezy.hr/p/236071a7c66a-senior-backend-engineer/apply",
        "https://volt-labs-inc.breezy.hr/p/aaaa11112222-staff-engineer")]
    groups = sorted(len(g) for g in K.dedupe(keys))
    assert groups == [1, 2]


def test_arrival_by_identifier_catches_a_same_host_redirect():
    assert K.arrival_bits(ZACT_CRUMB, "https://zact-inc.breezy.hr/p/4151651bd442-senior-backend-engineer") > 30
    assert K.arrival_bits(ZACT_CRUMB, "https://zact-inc.breezy.hr/p/0000aaaa9999-other") < 0
    assert K.arrival_bits(ZACT_CRUMB, "https://ads.example/x") == -math.inf
    no_id = K.key_from_breadcrumb("1001.breezy.hr", "apply", "")
    assert K.arrival_bits(no_id, "https://1001.breezy.hr/p/991a416a4798-backend-engineer") is None
