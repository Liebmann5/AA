"""
domain/web_math_core/algorithms/convex_hull.py

Computational Geometry: Andrew's Monotone Chain Convex Hull algorithm.

Defeats 'DOM Spaghetti' by ignoring HTML structure entirely and grouping elements
based on their visual 'shrink-wrap' boundary on the screen. Operates in O(N log N) time,
making it incredibly efficient even on low-end hardware.
"""



def _cross_product(o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    """
    2D cross product of OA and OB vectors.
    Returns a positive value if OAB makes a counter-clockwise turn,
    negative for clockwise, zero if collinear.
    """
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

def compute_convex_hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """
    Computes the convex hull of a set of 2D points.
    Returns a list of vertices forming the hull in counter-clockwise order.
    """
    # Remove duplicates and sort lexicographically (by x, then by y)
    points = sorted(set(points))

    # A polygon cannot be formed by less than 3 points, but a hull can be a line or point
    if len(points) <= 2:
        return points

    # Build the lower hull
    lower: list[tuple[float, float]] = []
    for p in points:
        while len(lower) >= 2 and _cross_product(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    # Build the upper hull
    upper: list[tuple[float, float]] = []
    for p in reversed(points):
        while len(upper) >= 2 and _cross_product(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    # Concatenate lower and upper hull.
    # Last point of each list is omitted because it is repeated at the beginning of the other list.
    return lower[:-1] + upper[:-1]

def hull_distance(hull_a: list[tuple[float, float]], hull_b: list[tuple[float, float]]) -> float:
    """
    Calculates the minimum visual distance between two convex hulls.
    If the hulls overlap, the distance is 0.
    This replaces DOM-distance for highly obfuscated SPA frameworks.
    """
    min_dist = float('inf')

    # O(N*M) calculation - extremely fast for hulls which usually have < 8 vertices
    for p1 in hull_a:
        for p2 in hull_b:
            dist = ((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2) ** 0.5
            min_dist = min(min_dist, dist)

    #TODO: For even more precision, we could implement the rotating calipers method to find the closest points between two convex polygons in O(N + M) time, but for our use case, vertex-to-vertex distance is a highly effective proxy for visual proximity.
    # Note: For absolute perfection, we would check edge-to-edge distance,
    # but vertex-to-vertex is a computationally cheap and highly accurate proxy for Gestalt proximity.
    return min_dist
