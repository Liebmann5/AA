"""Minimum-cost assignment (Kuhn 1955, Munkres 1957), O(n^3), square input.

Ported from AA ``domain/services/label_input_pairing.hungarian_assign``
(potentials form, 1-indexed). ``pad`` builds the square matrix for a
partial assignment the way 06 section 4 specifies: dummy columns at a
finite cost ``c0`` so a row prefers "unassigned" to a bad match, dummy rows
at 0 so an unused column is free. ``c0 = 0`` would make every dummy free
and every pairing optional, which is the Bible 9.4 P0 bug.
"""

from __future__ import annotations


def assign(cost: list[list[float]]) -> list[int]:
    """``col[r]`` for each row ``r`` of a square matrix."""
    n = len(cost)
    if n == 0:
        return []
    inf = float("inf")
    u = [0.0] * (n + 1)
    v = [0.0] * (n + 1)
    p = [0] * (n + 1)
    way = [0] * (n + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [inf] * (n + 1)
        used = [False] * (n + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], inf, 0
            row = cost[i0 - 1]
            for j in range(1, n + 1):
                if not used[j]:
                    cur = row[j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    col = [-1] * n
    for j in range(1, n + 1):
        if p[j]:
            col[p[j] - 1] = j - 1
    return col


def assign_partial(cost: list[list[float]], c0: float) -> list[int]:
    """Rows x cols (rectangular) -> chosen col per row, or -1 for "none".

    Square size ``R + C``: ``[cost | c0·I-ish]`` over ``[0 | 0]``. A row
    takes a real column only when that is cheaper than ``c0``.
    """
    if c0 <= 0:
        raise ValueError("c0 must be positive (a free dummy makes pairing meaningless)")
    r = len(cost)
    c = len(cost[0]) if r else 0
    n = r + c
    big = c0 * 1000.0 + 1e6
    m = [[0.0] * n for _ in range(n)]
    for i in range(r):
        for j in range(c):
            m[i][j] = cost[i][j]
        for j in range(c, n):
            m[i][j] = c0 if j - c == i else big
    # dummy rows (r..n-1): free on real columns and on the dummy columns
    col = assign(m)
    return [x if x < c else -1 for x in col[:r]]
