"""Tests for MathFormUnderstandingService._is_required.

DOMNode.get_attribute() returns "" for a missing attribute, never None, so
requiredness must test for the attribute's presence, not for None. Before the
fix every field was reported as required.
"""

import pytest

from auto_apply.domain.models.math_dom import DOMNode
from auto_apply.domain.services.dom_segmentation import MathFormUnderstandingService


def _input(*attributes: tuple[str, str]) -> DOMNode:
    return DOMNode(tag="input", attributes=(("name", "field"), *attributes))


def test_a_field_without_required_markers_is_optional__teeth():
    assert MathFormUnderstandingService._is_required(_input()) is False


@pytest.mark.parametrize("value", ["", "required", "true"])
def test_the_required_attribute_makes_a_field_required_whatever_its_value(value):
    assert MathFormUnderstandingService._is_required(_input(("required", value))) is True


def test_aria_required_true_makes_a_field_required():
    assert MathFormUnderstandingService._is_required(_input(("aria-required", "TRUE"))) is True


def test_aria_required_false_leaves_a_field_optional__teeth():
    assert MathFormUnderstandingService._is_required(_input(("aria-required", "false"))) is False
