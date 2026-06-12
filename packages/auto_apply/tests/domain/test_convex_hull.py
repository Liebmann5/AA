"""Unit tests for domain/services/convex_hull.py — Andrew's Monotone Chain algorithm."""

import math

import pytest

from auto_apply.domain.services.convex_hull import (
    _cross_product,
    compute_convex_hull,
    hull_distance,
)


# ── _cross_product ────────────────────────────────────────────────────────────

def test_cross_product_counter_clockwise():
    # O=(0,0), A=(1,0), B=(0,1) → left turn → positive
    assert _cross_product((0, 0), (1, 0), (0, 1)) > 0


def test_cross_product_clockwise():
    # O=(0,0), A=(0,1), B=(1,0) → right turn → negative
    assert _cross_product((0, 0), (0, 1), (1, 0)) < 0


def test_cross_product_collinear():
    assert _cross_product((0, 0), (1, 1), (2, 2)) == pytest.approx(0.0)


# ── compute_convex_hull ───────────────────────────────────────────────────────

def test_empty_input():
    assert compute_convex_hull([]) == []


def test_single_point():
    assert compute_convex_hull([(5.0, 3.0)]) == [(5.0, 3.0)]


def test_two_points():
    hull = compute_convex_hull([(0.0, 0.0), (10.0, 10.0)])
    assert len(hull) == 2


def test_three_collinear_points():
    hull = compute_convex_hull([(0.0, 0.0), (5.0, 0.0), (10.0, 0.0)])
    # Collinear — hull should contain at minimum the endpoints
    assert len(hull) >= 2
    points_set = set(hull)
    assert (0.0, 0.0) in points_set
    assert (10.0, 0.0) in points_set


def test_square_four_corners():
    points = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    hull = compute_convex_hull(points)
    assert len(hull) == 4
    hull_set = set(hull)
    for p in points:
        assert p in hull_set


def test_interior_point_excluded():
    points = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (5.0, 5.0)]
    hull = compute_convex_hull(points)
    assert (5.0, 5.0) not in hull
    assert len(hull) == 4


def test_duplicate_points_removed():
    points = [(0.0, 0.0), (0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    hull = compute_convex_hull(points)
    assert len(hull) == 4


def test_triangle():
    points = [(0.0, 0.0), (10.0, 0.0), (5.0, 10.0)]
    hull = compute_convex_hull(points)
    assert len(hull) == 3


def test_hull_is_counter_clockwise():
    """Hull should be returned in counter-clockwise order."""
    points = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    hull = compute_convex_hull(points)
    # Compute signed area: positive = CCW
    n = len(hull)
    area = sum(
        hull[i][0] * hull[(i + 1) % n][1] - hull[(i + 1) % n][0] * hull[i][1]
        for i in range(n)
    )
    assert area > 0, "Hull should be counter-clockwise (positive signed area)"


# ── hull_distance ────────────────────────────────────────────────────────────

def test_hull_distance_disjoint_hulls():
    hull_a = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    hull_b = [(20.0, 0.0), (30.0, 0.0), (30.0, 10.0), (20.0, 10.0)]
    dist = hull_distance(hull_a, hull_b)
    assert dist == pytest.approx(10.0)


def test_hull_distance_touching_hulls():
    hull_a = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    hull_b = [(10.0, 0.0), (20.0, 0.0), (20.0, 10.0), (10.0, 10.0)]
    dist = hull_distance(hull_a, hull_b)
    assert dist == pytest.approx(0.0)


def test_hull_distance_diagonal():
    hull_a = [(0.0, 0.0)]
    hull_b = [(3.0, 4.0)]
    dist = hull_distance(hull_a, hull_b)
    assert dist == pytest.approx(5.0)  # 3-4-5 triangle


def test_hull_distance_same_point():
    hull_a = [(5.0, 5.0)]
    hull_b = [(5.0, 5.0)]
    assert hull_distance(hull_a, hull_b) == pytest.approx(0.0)
