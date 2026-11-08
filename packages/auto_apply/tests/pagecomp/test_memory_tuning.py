"""S7: domain memory (ALG-020) and self-tuning (ALG-019)."""

from __future__ import annotations

import math

from pagecomp import memory as M
from pagecomp import tuning as T
from pagecomp.doc import from_html
from pagecomp.tools import default_registry

EXP = M.Expectations(min_records=5, max_records=50, title_link_bijection=True)
GOOD = {"records": 10, "titles": ["a"] * 10, "links": [f"u{i}" for i in range(10)]}
BAD = {"records": 0}


def test_region_hash_ignores_classes_and_text_not_structure():
    a = from_html('<main class="x1"><ul><li>a</li><li>b</li></ul></main>')
    b = from_html('<main class="zz9"><ul><li>other</li><li>text</li></ul></main>')
    c = from_html('<main><div><li>a</li></div></main>')
    assert M.region_hash(a) == M.region_hash(b) != M.region_hash(c)


def test_verified_on_every_use_and_quarantined_at_two_failures():
    mem = M.DomainMemory()
    mem.store("boards.example.com", "r1", {"strategy": "runs"}, EXP, now=0)
    out, _ = mem.use("jobs.example.com", "r1", 10, lambda h: GOOD)   # same registrable domain
    assert out is GOOD
    assert mem.use("boards.example.com", "r1", 20, lambda h: BAD) == (None, "record count 0 outside [5, 50]")
    assert mem.use("boards.example.com", "r1", 30, lambda h: BAD)[0] is None
    assert mem.lookup("boards.example.com", "r1", 40) is None
    assert "example.com|r1" in mem.retired and any(e.kind == "quarantined" for e in mem.log)


def test_expiry_and_renewal_after_three_passes():
    mem = M.DomainMemory(ttl_days=30)
    mem.store("x.example", "r", {}, EXP, now=0)
    for t in (1, 2, 3):
        mem.use("x.example", "r", t * M.DAY, lambda h: GOOD)
    e = mem.lookup("x.example", "r", 4 * M.DAY)
    assert math.isclose(e.expires, 3 * M.DAY + 30 * M.DAY)
    assert mem.lookup("x.example", "r", 40 * M.DAY) is None and any(ev.kind == "expired" for ev in mem.log)


def test_capacity_lru_eviction_is_logged():
    mem = M.DomainMemory(capacity=3)
    for i in range(5):
        mem.store(f"s{i}.example", "r", {}, EXP, now=i)
    assert len(mem.entries) == 3 and sum(1 for e in mem.log if e.kind == "evicted") == 2


def test_json_round_trip_and_snapshot_hash():
    mem = M.DomainMemory()
    mem.store("x.example", "r", {"k": 1}, EXP, now=5)
    back = M.DomainMemory.from_json(mem.to_json())
    assert back.snapshot_hash() == mem.snapshot_hash()
    assert M.DomainMemory.from_json("not json").entries == {}


def test_sign_test_holm_wilson():
    assert math.isclose(T.sign_test_p(10, 0), 1 / 1024)
    assert T.sign_test_p(0, 0) == 1.0
    r = T.holm({"a": 0.001, "b": 0.004, "c": 0.04}, 0.01)
    assert r == {"a": True, "b": True, "c": False}
    lo, hi = T.wilson_interval(8, 10)
    assert 0.49 < lo < 0.5 and 0.94 < hi < 0.95


def test_sample_size_matches_the_corrected_blueprint_figure():
    assert T.discordant_sites_needed(alpha=0.05) in (15, 16)
    assert 22 <= T.discordant_sites_needed(alpha=0.01) <= 30


def _outcomes(wins, losses, ties=0):
    out = []
    i = 0
    while sum(1 for o in out if o.correct_new and not o.correct_old) < wins:
        s = f"site{i}"
        i += 1
        if not T.holdout(s):
            out.append(T.SiteOutcome(s, False, True))
    while sum(1 for o in out if o.correct_old and not o.correct_new) < losses:
        s = f"site{i}"
        i += 1
        if not T.holdout(s):
            out.append(T.SiteOutcome(s, True, False))
    return out


def test_tuner_accepts_only_significant_bounded_changes_next_session():
    reg = default_registry()
    base = reg.default_params()
    tuner = T.Tuner()
    new, props = tuner.propose(base, reg.specs(), {("records", "tau"): (0.95, _outcomes(30, 2))}, guards={})
    p = props[0]
    assert p.accepted and math.isclose(p.new, 0.75 + 0.1 * (0.99 - 0.3))   # clipped to 10% of range
    assert new.hash != base.hash and new.for_tool("records")["tau"] == p.new
    # cooldown: the same parameter cannot move again for 5 cycles
    _, props2 = tuner.propose(new, reg.specs(), {("records", "tau"): (0.6, _outcomes(30, 2))}, guards={})
    assert props2[0].reason == "cooldown"
    assert tuner.rollback(True, new).hash == base.hash


def test_tuner_says_no_change_on_thin_or_unsafe_evidence():
    reg = default_registry()
    base = reg.default_params()
    tuner = T.Tuner()
    same, props = tuner.propose(base, reg.specs(), {
        ("records", "tau"): (0.8, _outcomes(5, 0)),
        ("formread", "c_trap"): (20.0, _outcomes(40, 0)),
    })
    assert same.hash == base.hash
    reasons = {p.param: p.reason for p in props}
    assert reasons["tau"].startswith("insufficient evidence")
    assert reasons["c_trap"] == "safety parameter: never tuned"


def test_non_inferiority_guard_blocks_a_change_that_hurts_another_family():
    reg = default_registry()
    tuner = T.Tuner()
    same, props = tuner.propose(reg.default_params(), reg.specs(),
                                {("records", "tau"): (0.8, _outcomes(30, 1))},
                                guards={"application_form": (80, 100, 95, 100)})
    assert not props[0].accepted and props[0].reason.startswith("non-inferiority failed")


def test_missing_guard_evidence_never_passes():
    """Review finding (2026-11-08): a guard with zero observations, or no
    guards at all, let a change through. Missing evidence must block it."""
    reg = default_registry()
    for guards, why in ((None, "no guard evidence given"),
                        ({"application_form": (0, 0, 0, 0)}, "application_form (no observations)"),
                        ({"application_form": (90, 100, 0, 0)}, "application_form (no observations)")):
        _, props = T.Tuner().propose(reg.default_params(), reg.specs(),
                                   {("records", "tau"): (0.8, _outcomes(30, 1))}, guards=guards)
        assert not props[0].accepted and props[0].reason == "non-inferiority failed: " + why
    _, props = T.Tuner().propose(reg.default_params(), reg.specs(),
                               {("records", "tau"): (0.8, _outcomes(30, 1))},
                               guards={"application_form": (1000, 1000, 1000, 1000)})
    assert props[0].accepted
    # Equal accuracy on 100 pages is *not* evidence of non-inferiority at a
    # 1-point margin: the Newcombe bound is about -0.068.
    assert T.diff_lower_bound(95, 100, 95, 100) < -0.06
