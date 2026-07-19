"""Unit tests for BehaviorParameters.make_rng reproducibility and independence."""

import pytest

from auto_apply.domain.models.timing import BehaviorParameters, TimingProfile


class TestMakeRngUnseeded:
    """When random_seed is None, make_rng returns an unseeded Random instance."""

    def test_unseeded_returns_random_instance(self):
        params = BehaviorParameters(random_seed=None)
        rng = params.make_rng()
        assert isinstance(rng, __import__("random").Random)

    def test_unseeded_does_not_raise_on_namespaces(self):
        params = BehaviorParameters(random_seed=None)
        rng = params.make_rng("a", "b")
        assert isinstance(rng, __import__("random").Random)


class TestMakeRngDeterministic:
    """When random_seed is set, make_rng returns deterministic streams."""

    def test_same_seed_same_namespace_same_sequence(self):
        params = BehaviorParameters(random_seed=42)
        rng1 = params.make_rng("comp.A")
        rng2 = params.make_rng("comp.A")

        # Consume several values and verify identical output.
        for _ in range(10):
            assert rng1.random() == rng2.random()

    def test_same_seed_same_namespaces_tuple_same_sequence(self):
        params = BehaviorParameters(random_seed=42)
        rng1 = params.make_rng("comp.A", "attempt.1")
        rng2 = params.make_rng("comp.A", "attempt.1")
        for _ in range(5):
            assert rng1.random() == rng2.random()

    def test_same_seed_different_namespace_different_sequence(self):
        params = BehaviorParameters(random_seed=42)
        rng_a = params.make_rng("a")
        rng_b = params.make_rng("b")
        first_a = rng_a.random()
        first_b = rng_b.random()
        # They should differ with very high probability.
        assert first_a != first_b

        # Consume more values to confirm the streams are not simply shifted.
        for _ in range(20):
            assert rng_a.random() != rng_b.random()

    def test_same_seed_different_namespaces_independent(self):
        """Different namespace sets must produce sequences that are not
        just different starting points in the same global stream."""
        params = BehaviorParameters(random_seed=99)
        rng1 = params.make_rng("alpha")
        rng2 = params.make_rng("beta")
        # Compare a short sequence to ensure they differ immediately.
        seq1 = [rng1.random() for _ in range(5)]
        seq2 = [rng2.random() for _ in range(5)]
        assert seq1 != seq2
        # Also verify that the sequences remain distinct.
        for _ in range(10):
            assert rng1.random() != rng2.random()

    def test_different_seeds_produce_different_streams(self):
        """Even with the same namespace, different base seeds diverge."""
        params_a = BehaviorParameters(random_seed=1)
        params_b = BehaviorParameters(random_seed=2)
        rng_a = params_a.make_rng("shared")
        rng_b = params_b.make_rng("shared")
        assert rng_a.random() != rng_b.random()

    def test_empty_namespace_is_allowed(self):
        params = BehaviorParameters(random_seed=777)
        rng = params.make_rng()
        assert isinstance(rng, __import__("random").Random)
        # Multiple calls without namespaces produce the same seed (empty string)
        rng2 = params.make_rng()
        assert rng.random() == rng2.random()

    def test_reproducibility_across_separate_instances(self):
        """Two independent BehaviorParameters with the same seed produce
        identical streams for the same namespace."""
        params1 = BehaviorParameters(random_seed=123)
        params2 = BehaviorParameters(random_seed=123)
        rng1 = params1.make_rng("x", "y")
        rng2 = params2.make_rng("x", "y")
        for _ in range(8):
            assert rng1.random() == rng2.random()