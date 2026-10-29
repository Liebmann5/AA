"""Pins for the per-host navigation floor (host pacing).

New-surface pins; each names the mutation it catches. The floor comes from
config, jitter from the seeded RNG — never a literal on this path.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from auto_apply.application.services.host_pacing import HostPacer


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _pacer(clock, sleeps, **kwargs):
    return HostPacer(sleeper=sleeps.append, clock=clock, **kwargs)


def test_first_contact_to_a_host_does_not_wait():
    """Catches: a floor applied to first contact."""
    clock = _Clock()
    sleeps: list[float] = []
    pacer = _pacer(clock, sleeps, min_interval_s=1.0, max_interval_s=2.0)
    assert pacer.wait_for_url("https://google.com/search?q=x") == 0.0
    assert sleeps == []


def test_second_contact_too_soon_waits_for_the_floor():
    """Catches: no wait between consecutive same-host navigations."""
    clock = _Clock()
    sleeps: list[float] = []
    pacer = _pacer(clock, sleeps, min_interval_s=2.0, max_interval_s=2.0)
    pacer.wait_for_url("https://google.com/a")
    clock.now += 0.5
    waited = pacer.wait_for_url("https://google.com/b")
    assert waited == 1.5
    assert sleeps == [1.5]


def test_different_hosts_are_not_spaced():
    """Catches: a global (not per-host) floor."""
    clock = _Clock()
    sleeps: list[float] = []
    pacer = _pacer(clock, sleeps, min_interval_s=2.0, max_interval_s=2.0)
    pacer.wait_for_url("https://google.com/a")
    assert pacer.wait_for_url("https://bing.com/a") == 0.0
    assert sleeps == []


def test_host_keys_normalise_case_and_port():
    """Catches: 'GOOGLE.com:443' and 'google.com' treated as different hosts."""
    clock = _Clock()
    sleeps: list[float] = []
    pacer = _pacer(clock, sleeps, min_interval_s=2.0, max_interval_s=2.0)
    pacer.wait_for_url("https://GOOGLE.com:443/a")
    waited = pacer.wait_for_url("https://google.com/b")
    assert waited == 2.0


def test_floor_equal_to_ceiling_draws_no_randomness():
    """Catches: an RNG draw when the range is empty (would break determinism)."""
    clock = _Clock()
    sleeps: list[float] = []
    rng = MagicMock()
    rng.uniform.side_effect = AssertionError("no draw expected")
    pacer = _pacer(clock, sleeps, min_interval_s=1.5, max_interval_s=1.5, rng=rng)
    pacer.wait_for_url("https://google.com/a")
    pacer.wait_for_url("https://google.com/b")
    assert sleeps == [1.5]


def test_jitter_uses_the_seeded_rng():
    """Catches: jitter from anywhere but the injected RNG. One draw per call,
    every call, so the number of draws never depends on timing."""
    clock = _Clock()
    sleeps: list[float] = []
    rng = MagicMock()
    rng.uniform.return_value = 0.25
    pacer = _pacer(clock, sleeps, min_interval_s=1.0, max_interval_s=2.0, rng=rng)
    pacer.wait_for_url("https://google.com/a")
    waited = pacer.wait_for_url("https://google.com/b")
    assert rng.uniform.call_count == 2
    assert all(c.args == (0.0, 1.0) for c in rng.uniform.call_args_list)
    assert waited == 1.25


def test_reservations_accumulate_without_clock_advance():
    """Catches: the reservation not recorded before sleeping (thread race).
    With the clock frozen, the third call must queue behind the second's
    reserved slot (2.0s), not behind the first contact (1.0s)."""
    clock = _Clock()
    sleeps: list[float] = []
    pacer = _pacer(clock, sleeps, min_interval_s=1.0, max_interval_s=1.0)
    pacer.wait_for_url("https://google.com/a")
    pacer.wait_for_url("https://google.com/b")
    pacer.wait_for_url("https://google.com/c")
    assert sleeps == [1.0, 2.0]
