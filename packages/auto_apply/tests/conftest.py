"""Top-level shared fixtures: DOMNode and Geometry building blocks.

NodeMap
-------
DOMNode is now fully hashable (attributes and children are immutable tuples).
The ``NodeMap`` helper is retained for cases where identity‑based mapping is
still needed, but most tests can now use plain ``dict`` with DOMNode keys.
"""

import pytest

from auto_apply.domain.models.math_dom import DOMNode, Geometry
from auto_apply.domain.models.profile import UserProfile


class NodeMap:
    """Identity‑keyed mapping usable wherever ``dict[DOMNode, ...]`` is expected.

    Uses ``id(node)`` internally so even structurally identical nodes can be
    treated as distinct keys (important for parent‑map tests).
    """

    def __init__(self, pairs=()):
        self._store: dict[int, object] = {}
        for k, v in pairs:
            self._store[id(k)] = v

    def get(self, key, default=None):
        return self._store.get(id(key), default)

    def __getitem__(self, key):
        return self._store[id(key)]

    def __setitem__(self, key, value):
        self._store[id(key)] = value

    def __contains__(self, key):
        return id(key) in self._store


@pytest.fixture
def make_geometry():
    def _make(x=0, y=0, width=100, height=50):
        return Geometry(x=x, y=y, width=width, height=height)
    return _make


@pytest.fixture
def visible_geometry():
    return Geometry(x=100, y=100, width=200, height=40)


@pytest.fixture
def zero_geometry():
    return Geometry(x=0, y=0, width=0, height=0)


@pytest.fixture
def offscreen_geometry():
    return Geometry(x=-5000, y=-5000, width=100, height=50)


@pytest.fixture
def input_node():
    return DOMNode(
        tag="input",
        attributes=(("type", "text"), ("name", "first_name"), ("placeholder", "First Name")),
        geometry=Geometry(x=100, y=100, width=200, height=40),
        depth=2,
    )


@pytest.fixture
def label_node():
    return DOMNode(
        tag="label",
        text="First Name",
        geometry=Geometry(x=100, y=70, width=80, height=20),
        depth=2,
    )


@pytest.fixture
def simple_form_root():
    """A minimal form: one label + one input as siblings under a div."""
    lbl = DOMNode(
        tag="label",
        text="Email",
        geometry=Geometry(x=100, y=70, width=60, height=20),
        depth=1,
    )
    inp = DOMNode(
        tag="input",
        attributes=(("type", "text"), ("name", "email"), ("placeholder", "Email")),
        geometry=Geometry(x=100, y=100, width=200, height=40),
        depth=1,
    )
    return DOMNode(tag="form", depth=0, children=(lbl, inp))


# ── Shared, reusable valid‑profile fixture for test stability ────────────────
@pytest.fixture
def minimal_valid_profile() -> UserProfile:
    """Return a minimal but valid `UserProfile` suitable for any test.

    The career_summary is long enough to satisfy Pydantic’s minimum‑length
    constraint (now relaxed to 1 character) while also exceeding the soft
    warning threshold (≥ 50) that `profile_validator` advises.
    """
    return UserProfile.model_validate({
        "profile_name": "test-profile",
        "personal_info": {
            "first_name": "Test",
            "last_name": "User",
            "email": "test@example.com",
            "phone_number": "000-000-0000",
            "street_address": "123 Test St",
            "city": "Testville",
            "state": "TS",
            "zip_code": "00000",
            "country": "United States",
        },
        "links": {},
        "career_summary": "Professional engineer with extensive experience building scalable systems, open-source tools, and test automation frameworks.",
        "search_preferences": {
            "desired_job_titles": ["Software Engineer"],
            "preferred_locations": ["Remote"],
        },
        "politeness_settings": {},
        "app_config": {
            "preferred_browser": "any",
            "run_headless": False,
            "daily_application_limit": 10,
            "enable_behavior_humanization": True,
        },
    })