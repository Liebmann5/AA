"""Top-level shared fixtures: DOMNode and Geometry building blocks.

NodeMap
-------
DOMNode is @dataclass(frozen=True) but its ``attributes: dict`` and
``children: list`` fields make it unhashable at runtime.  Production
functions that accept a ``parent_map: dict[DOMNode, DOMNode | None]``
only need ``parent_map.get(node)`` / ``parent_map[node]`` — they never
require Python to hash the node as a standard dict key.

NodeMap satisfies that interface using ``id()`` for key lookups, so
tests can build meaningful parent relationships without hitting the
unhashable-DOMNode bug.
"""

import pytest

from auto_apply.domain.models.math_dom import DOMNode, Geometry


class NodeMap:
    """Identity-keyed mapping usable wherever ``dict[DOMNode, ...]`` is expected.

    Uses ``id(node)`` internally so unhashable DOMNode objects can serve
    as logical keys without triggering ``TypeError: unhashable type: 'dict'``.
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
        attributes={"type": "text", "name": "first_name", "placeholder": "First Name"},
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
        attributes={"type": "text", "name": "email", "placeholder": "Email"},
        geometry=Geometry(x=100, y=100, width=200, height=40),
        depth=1,
    )
    return DOMNode(tag="form", depth=0, children=[lbl, inp])
