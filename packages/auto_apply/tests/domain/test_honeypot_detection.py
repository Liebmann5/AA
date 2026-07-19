"""Unit tests for domain/services/honeypot_detection.py."""

import pytest

from auto_apply.domain.models.math_dom import DOMNode, Geometry
from auto_apply.domain.services.honeypot_detection import HoneypotDetector, detect_honeypots


@pytest.fixture
def detector():
    return HoneypotDetector()


def _visible_input(name="first_name", placeholder="First Name"):
    return DOMNode(
        tag="input",
        attributes=(("name", name), ("placeholder", placeholder)),
        geometry=Geometry(x=100, y=100, width=200, height=40),
        depth=2,
    )


# ── Geometry checks ──────────────────────────────────────────────────────────

def test_zero_width_is_honeypot(detector):
    node = DOMNode(
        tag="input",
        attributes=(("name", "email"),),
        geometry=Geometry(x=100, y=100, width=0, height=40),
        depth=2,
    )
    is_hp, reason = detector.is_honeypot(node)
    assert is_hp
    assert "zero size" in reason


def test_zero_height_is_honeypot(detector):
    node = DOMNode(
        tag="input",
        attributes=(("name", "email"),),
        geometry=Geometry(x=100, y=100, width=200, height=0),
        depth=2,
    )
    is_hp, reason = detector.is_honeypot(node)
    assert is_hp
    assert "zero size" in reason


def test_very_small_area_is_honeypot(detector):
    node = DOMNode(
        tag="input",
        attributes=(("name", "email"),),
        geometry=Geometry(x=100, y=100, width=1, height=1),
        depth=2,
    )
    is_hp, reason = detector.is_honeypot(node)
    assert is_hp
    assert "small" in reason or "size" in reason


def test_offscreen_negative_x_is_honeypot(detector):
    node = DOMNode(
        tag="input",
        attributes=(("name", "email"), ("placeholder", "Email")),
        geometry=Geometry(x=-9999, y=100, width=200, height=40),
        depth=2,
    )
    is_hp, reason = detector.is_honeypot(node)
    assert is_hp
    assert "offscreen" in reason


def test_offscreen_negative_y_is_honeypot(detector):
    node = DOMNode(
        tag="input",
        attributes=(("name", "email"), ("placeholder", "Email")),
        geometry=Geometry(x=100, y=-9999, width=200, height=40),
        depth=2,
    )
    is_hp, reason = detector.is_honeypot(node)
    assert is_hp
    assert "offscreen" in reason


def test_no_geometry_with_placeholder_not_honeypot(detector):
    # No geometry → geometry check skips; "email" not in suspicious set; has placeholder
    node = DOMNode(
        tag="input",
        attributes=(("name", "email"), ("placeholder", "Email")),
        depth=2,
    )
    is_hp, _ = detector.is_honeypot(node)
    assert not is_hp


# ── Suspicious name/id/class checks ─────────────────────────────────────────

@pytest.mark.parametrize("name", [
    "fax", "email2", "confirm_email", "hidden_field",
    "url2", "phone2", "address2", "captcha_input",
    "test_field",
])
def test_suspicious_name_is_honeypot(detector, name):
    node = DOMNode(
        tag="input",
        attributes=(("name", name), ("placeholder", "Fill me in")),
        geometry=Geometry(x=100, y=100, width=200, height=40),
        depth=2,
    )
    is_hp, reason = detector.is_honeypot(node)
    assert is_hp, f"Expected '{name}' to be detected as honeypot"
    assert "suspicious" in reason


def test_suspicious_id_attribute(detector):
    node = DOMNode(
        tag="input",
        attributes=(("id", "email2"), ("placeholder", "Email")),
        geometry=Geometry(x=100, y=100, width=200, height=40),
        depth=2,
    )
    is_hp, reason = detector.is_honeypot(node)
    assert is_hp
    assert "id" in reason


def test_suspicious_class_attribute(detector):
    node = DOMNode(
        tag="input",
        attributes=(("class", "hidden_trap"), ("placeholder", "Fill")),
        geometry=Geometry(x=100, y=100, width=200, height=40),
        depth=2,
    )
    is_hp, reason = detector.is_honeypot(node)
    assert is_hp
    assert "class" in reason


# ── Label presence ───────────────────────────────────────────────────────────

def test_no_label_no_placeholder_is_honeypot(detector):
    node = DOMNode(
        tag="input",
        attributes=(("name", "username"),),
        geometry=Geometry(x=100, y=100, width=200, height=40),
        depth=2,
    )
    is_hp, reason = detector.is_honeypot(node)
    assert is_hp
    assert "no visible label" in reason


def test_placeholder_satisfies_label(detector):
    node = _visible_input(name="username", placeholder="Enter username")
    is_hp, _ = detector.is_honeypot(node)
    assert not is_hp


def test_aria_label_satisfies_label(detector):
    node = DOMNode(
        tag="input",
        attributes=(("name", "username"), ("aria-label", "Username")),
        geometry=Geometry(x=100, y=100, width=200, height=40),
        depth=2,
    )
    is_hp, _ = detector.is_honeypot(node)
    assert not is_hp


# ── Ancestor visibility ─────────────────────────────────────────────────────

def test_hidden_ancestor_is_honeypot(detector):
    """An input whose parent has zero geometry is flagged as a honeypot."""
    parent = DOMNode(
        tag="div",
        attributes=(),
        geometry=Geometry(x=0, y=0, width=0, height=0),
        depth=1,
    )
    child = DOMNode(
        tag="input",
        attributes=(("name", "username"), ("placeholder", "Username")),
        geometry=Geometry(x=100, y=100, width=200, height=40),
        depth=2,
    )
    parent_map = {child: parent, parent: None}
    is_hp, reason = detector.is_honeypot(child, parent_map=parent_map)
    assert is_hp
    assert "ancestor" in reason


# ── detect_honeypots convenience function ────────────────────────────────────

def test_detect_honeypots_returns_only_bad_nodes():
    good = _visible_input(name="first_name", placeholder="First Name")
    bad_geometry = DOMNode(
        tag="input",
        attributes=(("name", "fax"),),
        geometry=Geometry(x=100, y=100, width=0, height=0),
        depth=2,
    )
    bad_name = _visible_input(name="email2", placeholder="Email 2")
    result = detect_honeypots([good, bad_geometry, bad_name])
    assert bad_geometry in result
    assert bad_name in result
    assert good not in result


def test_detect_honeypots_empty_list():
    assert detect_honeypots([]) == []