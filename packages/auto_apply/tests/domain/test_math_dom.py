"""Unit tests for domain/models/math_dom.py — structural equality and hashability."""

import pytest

from auto_apply.domain.models.math_dom import DOMNode


# ── Structural equality ──────────────────────────────────────────────────────

def test_domnode_structural_equality():
    n1 = DOMNode(tag="div", attributes=(("class", "foo"),), children=())
    n2 = DOMNode(tag="div", attributes=(("class", "foo"),), children=())
    assert n1 == n2, "Identical DOMNodes must be equal"
    assert hash(n1) == hash(n2), "Identical DOMNodes must have same hash"


def test_domnode_structural_inequality():
    n1 = DOMNode(tag="div", attributes=(("class", "foo"),), children=())
    n2 = DOMNode(tag="div", attributes=(("class", "bar"),), children=())
    assert n1 != n2


def test_domnode_equality_includes_geometry():
    from auto_apply.domain.models.math_dom import Geometry
    n1 = DOMNode(tag="div", geometry=Geometry(0, 0, 100, 50))
    n2 = DOMNode(tag="div", geometry=Geometry(10, 10, 100, 50))
    assert n1 != n2


# ── get_attribute helper ─────────────────────────────────────────────────────

def test_domnode_get_attribute():
    node = DOMNode(
        tag="input",
        attributes=(("type", "text"), ("id", "name")),
        children=(),
    )
    assert node.get_attribute("type") == "text"
    assert node.get_attribute("missing", "default") == "default"

    # Duplicate keys: should return the LAST value
    node2 = DOMNode(
        tag="input",
        attributes=(("type", "text"), ("type", "password")),
        children=(),
    )
    assert node2.get_attribute("type") == "password"


def test_domnode_get_attribute_no_attributes():
    node = DOMNode(tag="div")
    assert node.get_attribute("any") == ""


# ── attrs_as_dict helper ─────────────────────────────────────────────────────

def test_domnode_attrs_as_dict():
    node = DOMNode(
        tag="div",
        attributes=(("class", "card"), ("id", "j1")),
        children=(),
    )
    d = node.attrs_as_dict()
    assert d == {"class": "card", "id": "j1"}


# ── Set / dict deduplication ─────────────────────────────────────────────────

def test_domnode_in_set():
    n1 = DOMNode(tag="div", attributes=(("class", "card"),), children=())
    n2 = DOMNode(tag="div", attributes=(("class", "card"),), children=())
    assert len({n1, n2}) == 1


def test_domnode_in_dict():
    n1 = DOMNode(tag="div", attributes=(("class", "card"),), children=())
    n2 = DOMNode(tag="div", attributes=(("class", "card"),), children=())
    d = {n1: "value"}
    assert d[n2] == "value"


# ── Construction edge cases ──────────────────────────────────────────────────

def test_domnode_empty_attributes_and_children():
    node = DOMNode(tag="p")
    assert node.attributes == ()
    assert node.children == ()
    assert node.get_attribute("x") == ""


def test_domnode_with_children():
    child = DOMNode(tag="span", depth=1)
    parent = DOMNode(tag="div", depth=0, children=(child,))
    assert len(parent.children) == 1
    assert parent.children[0] is child