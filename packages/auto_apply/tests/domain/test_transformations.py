"""Unit tests for domain/services/transformations.py — affine transform and ray casting."""

import math

import pytest

from auto_apply.domain.services.transformations import (
    apply_affine_transform,
    calculate_true_polygon,
    parse_transform_matrix,
    point_in_polygon,
)


# ── parse_transform_matrix ───────────────────────────────────────────────────

def test_parse_identity_matrix():
    result = parse_transform_matrix("matrix(1, 0, 0, 1, 0, 0)")
    assert result == pytest.approx([1.0, 0.0, 0.0, 1.0, 0.0, 0.0])


def test_parse_translation_matrix():
    result = parse_transform_matrix("matrix(1, 0, 0, 1, 50, 100)")
    assert result is not None
    assert result[4] == pytest.approx(50.0)
    assert result[5] == pytest.approx(100.0)


def test_parse_none_returns_none():
    assert parse_transform_matrix("none") is None


def test_parse_empty_returns_none():
    assert parse_transform_matrix("") is None


def test_parse_malformed_returns_none():
    assert parse_transform_matrix("rotate(45deg)") is None


def test_parse_matrix_with_spaces():
    result = parse_transform_matrix("matrix(1, 0, 0, 1, 10.5, 20.5)")
    assert result is not None
    assert result[4] == pytest.approx(10.5)


def test_parse_non_integer_values():
    result = parse_transform_matrix("matrix(0.866, 0.5, -0.5, 0.866, 0, 0)")
    assert result is not None
    assert len(result) == 6


# ── apply_affine_transform ───────────────────────────────────────────────────

def test_identity_transform_no_change():
    identity = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
    x, y = apply_affine_transform(10.0, 20.0, identity, 0.0, 0.0)
    assert x == pytest.approx(10.0)
    assert y == pytest.approx(20.0)


def test_translation_matrix():
    matrix = [1.0, 0.0, 0.0, 1.0, 5.0, 10.0]
    x, y = apply_affine_transform(0.0, 0.0, matrix, 0.0, 0.0)
    assert x == pytest.approx(5.0)
    assert y == pytest.approx(10.0)


def test_90_degree_rotation():
    # 90° CCW: matrix(0, 1, -1, 0, 0, 0) — rotating point (10,0) around (0,0)
    matrix = [0.0, 1.0, -1.0, 0.0, 0.0, 0.0]
    x, y = apply_affine_transform(10.0, 0.0, matrix, 0.0, 0.0)
    assert x == pytest.approx(0.0, abs=1e-9)
    assert y == pytest.approx(10.0, abs=1e-9)


def test_scale_matrix():
    matrix = [2.0, 0.0, 0.0, 2.0, 0.0, 0.0]
    x, y = apply_affine_transform(5.0, 5.0, matrix, 0.0, 0.0)
    assert x == pytest.approx(10.0)
    assert y == pytest.approx(10.0)


def test_transform_around_origin():
    # Identity around a non-zero origin should leave the point unchanged
    identity = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
    x, y = apply_affine_transform(50.0, 50.0, identity, 25.0, 25.0)
    assert x == pytest.approx(50.0)
    assert y == pytest.approx(50.0)


# ── calculate_true_polygon ────────────────────────────────────────────────────

def test_no_transform_returns_axis_aligned_corners():
    polygon = calculate_true_polygon(10.0, 20.0, 100.0, 50.0, "none")
    assert len(polygon) == 4
    assert (10.0, 20.0) in polygon      # top-left
    assert (110.0, 20.0) in polygon     # top-right
    assert (110.0, 70.0) in polygon     # bottom-right
    assert (10.0, 70.0) in polygon      # bottom-left


def test_identity_transform_same_as_no_transform():
    no_transform = calculate_true_polygon(0.0, 0.0, 100.0, 100.0, "none")
    identity = calculate_true_polygon(0.0, 0.0, 100.0, 100.0, "matrix(1, 0, 0, 1, 0, 0)")
    for p_a, p_b in zip(no_transform, identity):
        assert p_a[0] == pytest.approx(p_b[0])
        assert p_a[1] == pytest.approx(p_b[1])


def test_transform_returns_four_corners():
    polygon = calculate_true_polygon(0.0, 0.0, 200.0, 100.0, "matrix(1, 0, 0, 1, 0, 0)")
    assert len(polygon) == 4


# ── point_in_polygon ──────────────────────────────────────────────────────────

def test_point_inside_square():
    square = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]
    assert point_in_polygon(50.0, 50.0, square)


def test_point_outside_square():
    square = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]
    assert not point_in_polygon(200.0, 200.0, square)
    assert not point_in_polygon(-1.0, 50.0, square)


def test_point_inside_triangle():
    triangle = [(0.0, 0.0), (100.0, 0.0), (50.0, 100.0)]
    assert point_in_polygon(50.0, 40.0, triangle)


def test_point_outside_triangle():
    triangle = [(0.0, 0.0), (100.0, 0.0), (50.0, 100.0)]
    assert not point_in_polygon(0.0, 100.0, triangle)


def test_point_on_horizontal_edge_boundary():
    square = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]
    # Edge case — result is implementation-defined but must not crash
    result = point_in_polygon(50.0, 0.0, square)
    assert isinstance(result, bool)


def test_center_of_rotated_element_inside():
    # A 100×100 element at origin rotated 45° — center should still be inside
    polygon = calculate_true_polygon(
        0.0, 0.0, 100.0, 100.0, "matrix(0.707, 0.707, -0.707, 0.707, 0, 0)"
    )
    cx = sum(p[0] for p in polygon) / 4
    cy = sum(p[1] for p in polygon) / 4
    assert point_in_polygon(cx, cy, polygon)
