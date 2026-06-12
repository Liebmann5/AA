"""
domain/web_math_core/algorithms/transformations.py

Pure Python implementation of 2D Affine Transformations and Polygon Collision.

Defeats CSS Transform traps (rotate, skew, matrix). Calculates the exact true
polygon of an element on the screen, avoiding the "dead space" created by standard
Axis-Aligned Bounding Boxes (AABB).
"""

import re

# Matches standard 2D matrix from computed_styles: "matrix(a, b, c, d, tx, ty)"
_MATRIX_RE = re.compile(r"matrix\(([^)]+)\)")

def parse_transform_matrix(transform_str: str) -> list[float] | None:
    """Parses a CSS transform matrix string into a list of 6 floats."""
    if not transform_str or transform_str == "none":
        return None
    match = _MATRIX_RE.search(transform_str)
    if match:
        try:
            return[float(x.strip()) for x in match.group(1).split(',')]
        except ValueError:
            return None
    return None

def apply_affine_transform(
    x: float, y: float,
    matrix: list[float],
    origin_x: float, origin_y: float
) -> tuple[float, float]:
    """
    Applies a 2D affine transformation matrix to a point (x,y) around an origin.
    matrix = [a, b, c, d, tx, ty]

    Formula:
    x' = a*x + c*y + tx
    y' = b*x + d*y + ty
    """
    a, b, c, d, tx, ty = matrix

    # Translate to origin, apply transform, translate back
    rel_x = x - origin_x
    rel_y = y - origin_y

    new_x = (a * rel_x) + (c * rel_y) + tx + origin_x
    new_y = (b * rel_x) + (d * rel_y) + ty + origin_y

    return new_x, new_y

def calculate_true_polygon(
    x: float, y: float, w: float, h: float, transform_str: str
) -> list[tuple[float, float]]:
    """
    Calculates the 4 exact corners of an element after CSS transformations.
    Returns a list of (x,y) tuples representing the polygon.
    """
    matrix = parse_transform_matrix(transform_str)

    # Standard corners (Top-Left, Top-Right, Bottom-Right, Bottom-Left)
    corners =[
        (x, y),
        (x + w, y),
        (x + w, y + h),
        (x, y + h)
    ]

    if not matrix:
        return corners

    # CSS transforms are calculated from the center of the element by default (50% 50%)
    center_x = x + (w / 2.0)
    center_y = y + (h / 2.0)

    transformed_corners =[
        apply_affine_transform(cx, cy, matrix, center_x, center_y)
        for cx, cy in corners
    ]

    return transformed_corners

def point_in_polygon(px: float, py: float, polygon: list[tuple[float, float]]) -> bool:
    """
    Ray Casting Algorithm to determine if a point is strictly inside a polygon.
    Crucial for ensuring clicks land on heavily skewed/rotated CSS elements.
    """
    inside = False
    n = len(polygon)

    for i in range(n):
        p1x, p1y = polygon[i]
        p2x, p2y = polygon[(i + 1) % n]

        # Does the ray from (px, py) to infinity cross this edge?
        if min(p1y, p2y) < py <= max(p1y, p2y) and px <= max(p1x, p2x):
            # Calculate x-intersection of the ray with the edge
            if p1y != p2y:
                x_inters = (py - p1y) * (p2x - p1x) / (p2y - p1y) + p1x

            # If the point is to the left of the intersection, the ray crosses the edge
            if p1x == p2x or px <= x_inters:
                inside = not inside

    return inside
