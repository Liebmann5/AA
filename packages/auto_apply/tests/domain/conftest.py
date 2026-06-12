"""Domain-layer shared fixtures.

NodeMap is defined here so that test modules in tests/domain/ can do
``from conftest import NodeMap`` without relying on sys.path tricks that
break when pytest has already cached the domain-level conftest module.
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
