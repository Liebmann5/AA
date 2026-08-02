"""Reproducibility regression tests — end‑to‑end proof that deterministic seeding
works after the make_rng() and rng‑propagation refactors.

These tests are entirely offline: no live browser, no network, no real I/O.
They use stdlib mocking to capture the effect of seeded randomness on the
components that have been wired with ``rng`` parameters:

    - SeleniumAdapter.perform_mouse_fidget()
    - SeleniumProvider._get_user_agent()
    - ApplicationsWorkflow._lazy_scroll_to_top()

For each component, a positive test shows that two *independent* instances
created with ``BehaviorParameters.make_rng("namespace")`` from the same base
seed produce identical sequences of observable external calls, and a negative
test shows that two **different** base seeds produce different sequences.

The file also includes a structural sanity check on ``BehaviorParameters``
itself (already covered in ``tests/domain/test_timing.py``, but repeated here
for the regression suite to be self‑contained).

Intended location: ``tests/infrastructure/test_reproducibility.py``
"""

import random
import time
from unittest.mock import MagicMock, call, patch

import pytest

from auto_apply.domain.models.session_plan import SessionPlan
from auto_apply.domain.models.timing import BehaviorParameters, TimingProfile
from auto_apply.application.workflows.applications_workflow import ApplicationsWorkflow
from auto_apply.adapters.secondary.browser.selenium_adapter import SeleniumAdapter
from auto_apply.adapters.secondary.browser.selenium_provider import SeleniumProvider

# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _make_session_behavior(seed: int | None) -> BehaviorParameters:
    """Return a ``BehaviorParameters`` with *seed* and a default TimingProfile."""
    return BehaviorParameters(random_seed=seed, timing=TimingProfile())


def _call_collector(func):
    """Decorator that stores every (args, kwargs) invocation of *func* in a list."""
    history: list[tuple] = []

    def wrapper(*args, **kwargs):
        history.append((args, kwargs))
        return func(*args, **kwargs)

    wrapper.history = history
    wrapper.func = func
    return wrapper


# ----------------------------------------------------------------------
# 1. BehaviorParameters.make_rng() — structural sanity
# ----------------------------------------------------------------------

class TestMakeRngDeterminism:
    """Verify the core building block: same seed → same stream."""

    def test_same_seed_same_namespace_same_sequence(self):
        bp = _make_session_behavior(42)
        rng1 = bp.make_rng("test.comp")
        rng2 = bp.make_rng("test.comp")
        for _ in range(10):
            assert rng1.random() == rng2.random()

    def test_different_seeds_produce_different_sequences(self):
        bp_a = _make_session_behavior(42)
        bp_b = _make_session_behavior(99)
        rng_a = bp_a.make_rng("test.comp")
        rng_b = bp_b.make_rng("test.comp")
        # Probability of accidental equality with 10 floats is vanishingly small.
        seq_a = [rng_a.random() for _ in range(10)]
        seq_b = [rng_b.random() for _ in range(10)]
        assert seq_a != seq_b

    def test_different_namespaces_produce_uncorrelated_streams(self):
        bp = _make_session_behavior(42)
        rng_a = bp.make_rng("test.alpha")
        rng_b = bp.make_rng("test.beta")
        # The first value already differs with very high probability.
        assert rng_a.random() != rng_b.random()


# ----------------------------------------------------------------------
# 2. SeleniumAdapter — mouse fidget offsets
# ----------------------------------------------------------------------

class TestSeleniumAdapterReproducibility:
    """
    ``perform_mouse_fidget()`` uses ``self._rng.randint(-5, 5)`` to choose a
    small offset and then moves both forward and backward.  We capture the
    ``ActionChains.move_by_offset()`` calls and prove reproducibility.
    """

    @pytest.fixture(autouse=True)
    def _patch_actions(self):
        """Replace SeleniumAdapter's internal ``_ActionChains`` with a mock.

        Not autospec'd: ``_ActionChains`` is a lazily-populated module
        global (stays ``None`` until ``_ensure_selenium()`` first runs), so
        an autospec snapshot taken before that point would spec against
        ``None`` (non-callable) rather than the real ``ActionChains``
        class — and whether that's already happened depends on test
        execution order elsewhere in the suite. A plain MagicMock avoids
        depending on that timing entirely.

        Also force ``_ensure_selenium()`` to run BEFORE the patch is
        applied: it's the lazy-import step that populates ``_ActionChains``
        (among other Selenium globals) the first time any SeleniumAdapter
        is constructed in this process, and if that first call happens
        *during* this test (i.e. after the patch is already active), it
        overwrites the patched mock with the real ActionChains class,
        silently undoing the patch. Running it here first makes the patch
        reliable regardless of what has or hasn't run earlier in the suite.
        """
        from auto_apply.adapters.secondary.browser.selenium_adapter import (
            _ensure_selenium,
        )
        _ensure_selenium()

        patcher = patch(
            "auto_apply.adapters.secondary.browser.selenium_adapter._ActionChains",
        )
        self.mock_action_class = patcher.start()
        yield
        patcher.stop()

    def _make_adapter(self, seed: int) -> SeleniumAdapter:
        """Return a ``SeleniumAdapter`` backed by a mock driver and a seeded RNG."""
        mock_driver = MagicMock()
        rng = _make_session_behavior(seed).make_rng("selenium.adapter")
        return SeleniumAdapter(driver=mock_driver, rng=rng)

    def _captured_fidget_offsets(self) -> tuple[tuple[int, int], tuple[int, int]]:
        """
        Call ``perform_mouse_fidget()`` on a freshly mocked adapter and return the
        two (x, y) offset pairs that were passed to ``move_by_offset``.
        """
        # Re‑create the adapter inside the test so the mock is fresh every time.
        mock_instance = self.mock_action_class.return_value
        mock_instance.move_by_offset.return_value = mock_instance

        adapter = self._make_adapter(seed=42)  # seed arbitrary; test overrides the rng anyway
        adapter.perform_mouse_fidget()

        # Forward move
        forward_call = mock_instance.move_by_offset.call_args_list[0]
        fx, fy = forward_call[0]
        # Backward move
        backward_call = mock_instance.move_by_offset.call_args_list[1]
        bx, by = backward_call[0]
        return (fx, fy), (bx, by)

    def test_same_seed_same_fidget_offsets(self):
        """Two adapters from the same seed produce identical mouse offsets."""
        # Run twice and compare the tuples.
        offsets1 = self._captured_fidget_offsets()
        # Reset the mock so we get a clean second capture.
        self.mock_action_class.reset_mock()
        offsets2 = self._captured_fidget_offsets()
        assert offsets1 == offsets2, (
            f"Expected identical fidget offsets with same seed, "
            f"got {offsets1} vs {offsets2}"
        )

    def test_different_seeds_different_fidget_offsets(self):
        """Different base seeds produce different mouse offsets."""
        # We'll construct two adapters with seeds that are guaranteed different
        # and verify the captured offsets differ.
        rng_a = _make_session_behavior(seed=7).make_rng("selenium.adapter")
        rng_b = _make_session_behavior(seed=77).make_rng("selenium.adapter")

        mock = self.mock_action_class.return_value
        mock.move_by_offset.return_value = mock

        # First seed
        adapter_a = SeleniumAdapter(driver=MagicMock(), rng=rng_a)
        adapter_a.perform_mouse_fidget()
        offsets_a = (
            (mock.move_by_offset.call_args_list[0][0], mock.move_by_offset.call_args_list[1][0])
        )
        # Reset mock to capture new calls
        self.mock_action_class.reset_mock()
        mock.move_by_offset.reset_mock()

        # Second seed
        adapter_b = SeleniumAdapter(driver=MagicMock(), rng=rng_b)
        adapter_b.perform_mouse_fidget()
        offsets_b = (
            (mock.move_by_offset.call_args_list[0][0], mock.move_by_offset.call_args_list[1][0])
        )
        assert offsets_a != offsets_b, "Different seeds should give different fidget offsets"


# ----------------------------------------------------------------------
# 3. SeleniumProvider — user‑agent rotation (rng.choice)
# ----------------------------------------------------------------------

class TestSeleniumProviderReproducibility:
    """Prove that the seeded RNG control user‑agent selection deterministically."""

    def _mock_config(self, rotate: bool) -> dict:
        return {"rotate_user_agent": rotate, "user_agent": "custom-static"}

    def test_same_seed_same_ua_sequence(self):
        """When rng is seeded, ``_get_user_agent()`` with ``rotate_user_agent=True``
        returns the same sequence across two provider instances."""
        bp = _make_session_behavior(123)
        rng1 = bp.make_rng("selenium.provider")
        rng2 = bp.make_rng("selenium.provider")

        provider1 = SeleniumProvider(rng=rng1)
        provider2 = SeleniumProvider(rng=rng2)

        config = self._mock_config(rotate=True)
        # Call three times to accumulate a sequence
        seq1 = [provider1._get_user_agent(config) for _ in range(5)]
        seq2 = [provider2._get_user_agent(config) for _ in range(5)]
        assert seq1 == seq2, (
            f"Expected identical UA sequences from same seed, got {seq1} vs {seq2}"
        )

    def test_different_seeds_different_ua_sequence(self):
        """Different seeds cause different UA selections."""
        rng_a = _make_session_behavior(42).make_rng("selenium.provider")
        rng_b = _make_session_behavior(99).make_rng("selenium.provider")

        provider_a = SeleniumProvider(rng=rng_a)
        provider_b = SeleniumProvider(rng=rng_b)

        config = self._mock_config(rotate=True)
        seq_a = [provider_a._get_user_agent(config) for _ in range(5)]
        seq_b = [provider_b._get_user_agent(config) for _ in range(5)]
        assert seq_a != seq_b, "Different seeds should produce different UA sequences"

    def test_static_ua_ignores_rng(self):
        """When ``rotate_user_agent=False`` the provider returns the static UA,
        which is unaffected by the seed (always the same string)."""
        rng = _make_session_behavior(1).make_rng("selenium.provider")
        provider = SeleniumProvider(rng=rng)
        config = self._mock_config(rotate=False)
        ua = provider._get_user_agent(config)
        # _get_user_agent returns config["user_agent"] verbatim when
        # rotate_user_agent is False (see selenium_provider.py) — the
        # static UA configured in _mock_config is "custom-static", and the
        # point of this test is that it passes through unchanged,
        # completely ignoring the seeded RNG.
        assert ua == "custom-static"


# ----------------------------------------------------------------------
# 4. ApplicationsWorkflow — lazy‑scroll sleep timing
# ----------------------------------------------------------------------

class TestApplicationsWorkflowReproducibility:
    """
    ``_lazy_scroll_to_top`` is the only randomness‑touching part of the
    ApplicationsWorkflow that currently receives an ``rng`` parameter.
    It calls ``time.sleep(…)`` with a value from ``self._rng.uniform(…))``.
    """

    @pytest.fixture
    def minimal_mocks(self, mock_profile) -> tuple:
        """Return the minimum set of mocks required to construct the workflow."""
        return (
            mock_profile,
            MagicMock(),  # browser
            MagicMock(),  # job_repo
            MagicMock(),  # task_queue
            MagicMock(),  # event_bus
            MagicMock(),  # text_matcher
        )

    def _build_workflow(self, seed: int, mock_browser, **kwargs) -> ApplicationsWorkflow:
        """Create a fully mocked ``ApplicationsWorkflow`` with a seeded ``rng``."""
        from unittest.mock import MagicMock

        rng = _make_session_behavior(seed).make_rng("applications_workflow")
        # All mandatory constructor arguments must be supplied, but we mock
        # everything except the ones we might need to inspect.
        default_kwargs = dict(
            profile=MagicMock(),
            browser=mock_browser,
            perception_port=None,
            interaction_port=None,
            webpage_analyzer=None,
            field_classifier=None,
            semantic_filler=None,
            text_matcher=MagicMock(),
            file_handler=None,
            interruption_handler=None,
            dom_observer=None,
            ats_registry=None,
            job_repo=MagicMock(),
            task_queue=MagicMock(),
            event_bus=MagicMock(),
            interrupt_policy=MagicMock(),
            text_generation_port=None,
            rng=rng,
            plan=SessionPlan(session_id="repro"),
        )
        default_kwargs.update(kwargs)
        return ApplicationsWorkflow(**default_kwargs)

    def _captured_sleep(self, seed: int) -> list[float]:
        """Construct a workflow with *seed*, call ``_lazy_scroll_to_top()``,
        and return the list of float arguments passed to ``time.sleep``.
        """
        mock_browser = MagicMock()
        # We need to ensure that the browser's ``execute_script`` doesn't fail.
        mock_browser.execute_script.return_value = None

        with patch("time.sleep", autospec=True) as sleep_mock:
            wf = self._build_workflow(seed, mock_browser)
            wf._lazy_scroll_to_top()

        # _lazy_scroll_to_top calls time.sleep exactly once with a float.
        calls = [
            args[0] for args, _kwargs in sleep_mock.call_args_list
        ]
        assert len(calls) == 1, "Expected a single time.sleep call"
        return calls

    def test_same_seed_same_sleep_duration(self):
        """Two independent workflow instances with the same seed produce
        identical sleep durations for the lazy‑scroll pause."""
        d1 = self._captured_sleep(seed=42)
        d2 = self._captured_sleep(seed=42)
        assert d1 == d2, (
            f"Expected identical sleep durations with same seed, got {d1} vs {d2}"
        )

    def test_different_seeds_different_sleep_duration(self):
        """Two independent workflow instances with different seeds should
        (with very high probability) produce different sleep durations."""
        d1 = self._captured_sleep(seed=10)
        d2 = self._captured_sleep(seed=20)
        assert d1 != d2, (
            f"Expected different sleep durations with different seeds, but both returned {d1}"
        )


# ----------------------------------------------------------------------
# 5. Composition‑root wiring (stub – philosophy test)
# ----------------------------------------------------------------------

class TestCompositionRootNamespacing:
    """
    Structural test proving that ``build_orchestrator`` uses distinct
    namespaces when calling ``BehaviorParameters.make_rng()`` for each
    component, rather than sharing one RNG instance or forgetting to inject
    any at all.

    This is a static assertion; it does not exercise the actual cascade or
    browser startup, but it does confirm that the call‑site pattern in
    ``composition_root.py`` is intact after future refactors.
    """

    def test_build_orchestrator_make_rng_called_with_at_least_four_namespaces(self):
        """Verify that ``make_rng()`` is invoked with at least four different
        namespace strings during a normal (non‑static, driver‑provided) build.
        """
        bp_mock = MagicMock(wraps=_make_session_behavior(0))
        bp_mock.make_rng = MagicMock(
            side_effect=lambda *ns: _make_session_behavior(0).make_rng(*ns)
        )

        def _fake_acquire_driver(self):
            """Simulate a successful cascade acquisition.

            The real acquire_driver() only calls the adapter_map["selenium"]
            / adapter_map["playwright"] lambdas (which is where
            make_rng("selenium.adapter") / make_rng("playwright.adapter")
            actually live) if a real, installed browser is detected on the
            machine running the test — never guaranteed in CI or a
            container. Exercising both lambdas directly here proves they're
            each still correctly wired to a namespaced make_rng() call,
            without depending on a real browser being present.
            """
            raw = MagicMock()
            raw._pw_browser = MagicMock()
            raw._pw_playwright = MagicMock()
            self._adapter_map["selenium"](raw)
            self._adapter_map["playwright"](raw)
            return None  # fall back to static mode; only the RNG wiring matters here

        with (
            patch(
                "auto_apply.infrastructure.composition_root.BehaviorParameters"
            ) as mock_bp_cls,
            patch(
                "auto_apply.infrastructure.composition_root.BrowserCascade.acquire_driver",
                new=_fake_acquire_driver,
            ),
            # Playwright is an OPTIONAL dependency; this test must pass without
            # it. build_orchestrator imports PlaywrightAdapter *inside the
            # function* (composition_root.py:96) and the adapter_map lambda
            # closes over that local binding — so the patch must be active
            # before build_orchestrator runs, and must target the adapter
            # module (there is no composition_root.PlaywrightAdapter attribute
            # to patch). Patching the constructor still evaluates its
            # arguments, so make_rng("playwright.adapter") is observed exactly
            # as it would be in production.
            patch(
                "auto_apply.adapters.secondary.browser.playwright_adapter"
                ".PlaywrightAdapter"
            ),
        ):
            # composition_root.py calls BehaviorParameters.from_config(...)
            # (a classmethod), not BehaviorParameters(...) directly — patching
            # only `return_value` on the class mock would leave from_config()
            # returning an unrelated, uninstrumented auto-mock instead of
            # bp_mock. Wire the classmethod's return value explicitly.
            mock_bp_cls.from_config.return_value = bp_mock

            # We call build_orchestrator with a real‑enough registry and a
            # mock driver so that the adapter/injector paths execute.
            from auto_apply.infrastructure.composition_root import build_orchestrator
            from auto_apply.infrastructure.registry import CapabilitiesRegistry

            registry = CapabilitiesRegistry.build(
                user_profile=_minimal_profile(),
            )

            # Do NOT pass driver= here: composition_root.py's own sentinel
            # check (`driver is not ...`) treats "driver explicitly passed"
            # as "skip the cascade entirely", which would skip exactly the
            # adapter_map/selenium.provider code path this test exists to
            # verify. Omitting it lets the (patched) cascade run instead.
            _ = build_orchestrator(registry)

        # Collect the unique namespace arguments passed to make_rng
        namespaces = set()
        for call_args in bp_mock.make_rng.call_args_list:
            # make_rng(*namespaces)
            namespaces.add(tuple(call_args[0]))

        required = {
            ("selenium.adapter",),
            ("playwright.adapter",),
            ("selenium.provider",),
            ("applications_workflow",),
            ("discovery.provider_order",),
            ("interaction.pacing",),
        }
        missing = required - namespaces
        assert not missing, (
            f"build_orchestrator did not call make_rng() with these expected "
            f"namespaces: {sorted(missing)}. Full calls: {sorted(namespaces)}"
        )


def _minimal_profile():
    """Return a user profile that is valid enough to satisfy CapabilitiesRegistry."""
    from auto_apply.domain.models.profile import UserProfile
    return UserProfile.model_validate({
        "profile_name": "repro-test",
        "personal_info": {
            "first_name": "A",
            "last_name": "B",
            "email": "a@b.com",
            "phone_number": "000",
            "street_address": "",
            "city": "",
            "state": "",
            "zip_code": "",
        },
        "links": {},
        "career_summary": "Reproducibility test profile, written to satisfy the fifty character minimum length requirement.",
        "search_preferences": {
            "desired_job_titles": ["Engineer"],
            "preferred_locations": ["Remote"],
        },
        "politeness_settings": {},
    })