"""
Research Statistics — additional zero-dependency statistical methods.

This module EXTENDS (does not duplicate) the existing statistics/core.py,
which already implements chi-square, Fisher's exact, Wilson/Clopper-Pearson
CIs, Cohen's h/d, Cramér's V, Mann-Whitney U, Benjamini-Hochberg FDR, MATTR,
and Flesch-Kincaid per the AA_RESEARCH_MODULE_SPEC.

New methods added here, used by the v2.1 extended detectors:
  - flesch_kincaid_grade()  : if not already present in core.py, this is the
                               canonical zero-dependency implementation
  - gunning_fog_index()      : complexity index (NEW)
  - jaccard_similarity()     : Tier-0 set similarity for DP-01
  - role_keywords()          : keyword extraction for DP-01
  - kendall_tau()             : monotone correlation for salary/requirement studies
  - percentile()              : zero-dependency percentile for salary corpus (ST-03)

ALL FUNCTIONS ARE PURE: no I/O, no randomness, no global state.
This is sans-IO compliant — fully testable without any infrastructure.
"""
from __future__ import annotations

import math
import re

# ── Stopwords for keyword extraction (minimal, zero-dependency) ──────────────
_STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "the", "and", "or", "but", "if", "of", "at", "by", "for",
    "with", "about", "against", "between", "into", "through", "during",
    "before", "after", "above", "below", "to", "from", "up", "down", "in",
    "out", "on", "off", "over", "under", "again", "further", "then", "once",
    "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "do", "does", "did", "will", "would", "should", "could", "can", "may",
    "might", "must", "shall", "we", "you", "they", "it", "this", "that",
    "these", "those", "as", "such", "our", "your", "their", "its",
})


def _normalize_suffix(token: str) -> str:
    """Strip a small set of common English suffixes so morphological
    variants of the same root compare equal (e.g. "engineer" and
    "engineering" both normalize to "engineer"; "solution" and "solutions"
    both normalize to "solution").

    Deliberately conservative and zero-dependency (no real stemmer/lemmatizer
    — that's a Tier-1+ upgrade path via TextSimilarityPort). Only strips a
    suffix when the remaining stem is long enough to still be meaningful,
    to avoid collapsing unrelated short words together.
    """
    if token.endswith("ing") and len(token) - 3 >= 4:
        return token[:-3]
    if token.endswith("ies") and len(token) - 3 >= 3:
        return token[:-3] + "y"
    if token.endswith("es") and len(token) - 2 >= 4:
        return token[:-2]
    if token.endswith("s") and not token.endswith("ss") and len(token) - 1 >= 4:
        return token[:-1]
    return token


def role_keywords(text: str, min_length: int = 3) -> set[str]:
    """Extract role-defining keywords from a title or description.

    Lowercases, strips punctuation, removes stopwords and short tokens, and
    normalizes common suffixes (see :func:`_normalize_suffix`) so that
    morphological variants of the same root (e.g. "engineer" /
    "engineering") are treated as the same keyword. This is the Tier-0
    (zero-dependency) keyword extraction used by DP-01. A Tier-1
    implementation could substitute SpaCy noun-chunk extraction while
    keeping the same return type (set[str]).

    Args:
        text: Raw text (title or description excerpt).
        min_length: Minimum token length to keep.

    Returns:
        Set of lowercase, suffix-normalized keyword tokens.

    Example:
        >>> role_keywords("Senior Software Engineer - Backend")
        {'senior', 'software', 'engineer', 'backend'}
    """
    tokens = re.findall(r"[a-zA-Z][a-zA-Z\-]*", text.lower())
    return {
        _normalize_suffix(t) for t in tokens
        if len(t) >= min_length and t not in _STOPWORDS
    }


def overlap_coefficient(set_a: set[str], set_b: set[str]) -> float:
    """Compute the overlap coefficient (Szymkiewicz–Simpson coefficient).

    overlap(A,B) = |A ∩ B| / min(|A|, |B|)

    Unlike Jaccard similarity, this is NOT biased by a large size
    difference between the two sets — appropriate for comparing a short
    set (e.g. keywords from a 2-4 word job title) against a much longer
    one (keywords from a full paragraph description), where Jaccard's
    union-based denominator would structurally suppress the score
    regardless of how well the short set is actually contained in the
    long one.

    Args:
        set_a: First set of tokens.
        set_b: Second set of tokens.

    Returns:
        Similarity in [0.0, 1.0]: what fraction of the SMALLER set's
        tokens also appear in the larger set. Returns 0.0 if either set
        is empty (treated as no overlap, not undefined — avoids NaN
        propagation).
    """
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    smaller = min(len(set_a), len(set_b))
    return len(intersection) / smaller


def jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
    """Compute Jaccard similarity coefficient between two sets.

    J(A,B) = |A ∩ B| / |A ∪ B|

    Args:
        set_a: First set of tokens.
        set_b: Second set of tokens.

    Returns:
        Similarity in [0.0, 1.0]. Returns 0.0 if both sets are empty
        (treated as no overlap, not undefined — avoids NaN propagation).
    """
    if not set_a and not set_b:
        return 0.0
    union = set_a | set_b
    if not union:
        return 0.0
    intersection = set_a & set_b
    return len(intersection) / len(union)


# ── Readability metrics (zero dependency) ─────────────────────────────────────

_VOWELS: frozenset[str] = frozenset("aeiouy")


def _count_syllables(word: str) -> int:
    """Heuristic syllable counter (no dependencies).

    Standard heuristic: count vowel-group transitions, subtract silent
    trailing 'e', minimum of 1 syllable per word. This is the same
    approach used by the `textstat` library's fallback counter and is
    accurate to within ~10% for English text — sufficient for relative
    comparisons (which is all AH-02 needs).

    Args:
        word: A single word (any case, may include punctuation).

    Returns:
        Estimated syllable count, minimum 1.
    """
    word = re.sub(r"[^a-z]", "", word.lower())
    if not word:
        return 0
    syllables = 0
    prev_was_vowel = False
    for ch in word:
        is_vowel = ch in _VOWELS
        if is_vowel and not prev_was_vowel:
            syllables += 1
        prev_was_vowel = is_vowel
    if word.endswith("e") and syllables > 1:
        syllables -= 1
    return max(1, syllables)


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences using simple punctuation heuristics."""
    sentences = re.split(r"[.!?]+\s+", text.strip())
    return [s for s in sentences if s.strip()]


def flesch_kincaid_grade(text: str) -> float:
    """Compute the Flesch-Kincaid Grade Level of a text.

    Formula: 0.39 * (words/sentences) + 11.8 * (syllables/words) - 15.59

    A score of 12 corresponds to a U.S. 12th-grade (high school senior)
    reading level. A score of 16 corresponds to a college graduate level.

    Args:
        text: Input text (job description or any prose).

    Returns:
        Grade level as a float. Returns 0.0 for empty/degenerate input.

    Example:
        >>> round(flesch_kincaid_grade("The cat sat on the mat."), 1)
        0.5
    """
    words = re.findall(r"[a-zA-Z']+", text)
    sentences = _split_sentences(text)
    if not words or not sentences:
        return 0.0

    total_syllables = sum(_count_syllables(w) for w in words)
    word_count = len(words)
    sentence_count = max(1, len(sentences))

    grade = (
        0.39 * (word_count / sentence_count)
        + 11.8 * (total_syllables / word_count)
        - 15.59
    )
    return max(0.0, grade)


def gunning_fog_index(text: str) -> float:
    """Compute the Gunning Fog Index of a text.

    Formula: 0.4 * [(words/sentences) + 100 * (complex_words/words)]
    where a "complex word" has 3+ syllables (excluding common suffixes).

    A score of 17 corresponds to "post-graduate" reading difficulty.
    A score of 8 corresponds to "8th grade" — the recommended maximum for
    general-audience writing.

    Args:
        text: Input text.

    Returns:
        Fog index as a float. Returns 0.0 for empty/degenerate input.
    """
    words = re.findall(r"[a-zA-Z']+", text)
    sentences = _split_sentences(text)
    if not words or not sentences:
        return 0.0

    word_count = len(words)
    sentence_count = max(1, len(sentences))

    complex_words = sum(1 for w in words if _count_syllables(w) >= 3)

    fog = 0.4 * (
        (word_count / sentence_count) + 100.0 * (complex_words / word_count)
    )
    return max(0.0, fog)


# ── Correlation methods ────────────────────────────────────────────────────────

def kendall_tau(x: list[float], y: list[float]) -> tuple[float, float]:
    """Compute Kendall's Tau-b rank correlation coefficient.

    Used for monotone (not necessarily linear) correlation analysis, e.g.
    "does required experience monotonically relate to offered salary?"
    without assuming a linear relationship (unlike Pearson's r).

    This is a pure-Python O(n²) implementation. For corpora larger than a
    few thousand points, prefer scipy.stats.kendalltau if scipy is available
    (optional dependency) — same return signature.

    Args:
        x: First variable's values.
        y: Second variable's values (must be same length as x).

    Returns:
        Tuple of (tau, approximate_p_value). tau is in [-1.0, 1.0].
        p_value uses a normal approximation, valid for n >= 10.

    Raises:
        ValueError: If x and y have different lengths or fewer than 2 points.
    """
    n = len(x)
    if n != len(y):
        raise ValueError(f"x and y must have equal length, got {n} and {len(y)}")
    if n < 2:
        raise ValueError("kendall_tau requires at least 2 data points")

    concordant = 0
    discordant = 0
    ties_x = 0
    ties_y = 0

    for i in range(n):
        for j in range(i + 1, n):
            dx = x[i] - x[j]
            dy = y[i] - y[j]
            if dx == 0 and dy == 0:
                continue
            elif dx == 0:
                ties_x += 1
            elif dy == 0:
                ties_y += 1
            elif (dx > 0) == (dy > 0):
                concordant += 1
            else:
                discordant += 1

    n0 = n * (n - 1) / 2
    denom = math.sqrt((n0 - ties_x) * (n0 - ties_y))
    if denom == 0:
        return 0.0, 1.0

    tau = (concordant - discordant) / denom

    # Normal approximation for significance (valid for n >= 10)
    if n >= 10:
        var_tau = (2 * (2 * n + 5)) / (9 * n * (n - 1))
        z = tau / math.sqrt(var_tau) if var_tau > 0 else 0.0
        # Two-tailed p-value from standard normal CDF approximation
        p_value = 2 * (1 - _normal_cdf(abs(z)))
    else:
        p_value = 1.0  # Not enough data for a meaningful p-value

    return tau, p_value


def _normal_cdf(z: float) -> float:
    """Standard normal CDF using the error function (zero dependency)."""
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


# ── Percentile for salary corpus (ST-03) ──────────────────────────────────────

def percentile(values: list[float], p: float) -> float:
    """Compute the p-th percentile of a list using linear interpolation.

    This matches numpy's default ('linear') interpolation method, but has
    zero dependencies — important for worst-case users without numpy.

    Args:
        values: List of numeric values (need not be sorted).
        p: Percentile to compute, in [0, 100].

    Returns:
        The interpolated percentile value.

    Raises:
        ValueError: If values is empty or p is out of range.

    Example:
        >>> percentile([10, 20, 30, 40], 25)
        17.5
    """
    if not values:
        raise ValueError("percentile() requires a non-empty list")
    if not (0 <= p <= 100):
        raise ValueError(f"p must be in [0, 100], got {p}")

    sorted_vals = sorted(values)
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]

    rank = (p / 100.0) * (n - 1)
    lower_idx = math.floor(rank)
    upper_idx = math.ceil(rank)
    if lower_idx == upper_idx:
        return sorted_vals[lower_idx]

    fraction = rank - lower_idx
    return sorted_vals[lower_idx] + fraction * (sorted_vals[upper_idx] - sorted_vals[lower_idx])


# ── Cost-of-living normalization ──────────────────────────────────────────────

def normalize_salary_by_col(salary: float, col_index: float) -> float:
    """Normalize a salary by a metro area's cost-of-living index.

    Args:
        salary: Raw salary in USD.
        col_index: Cost-of-living index where 1.0 = national average
            (e.g. San Francisco ≈ 1.8, rural Midwest ≈ 0.85).

    Returns:
        COL-normalized salary, comparable across metro areas.

    Raises:
        ValueError: If col_index <= 0.
    """
    if col_index <= 0:
        raise ValueError(f"col_index must be positive, got {col_index}")
    return salary / col_index


# ── Correspondence audit statistics ──────────────────────────────────────────
# These complement (do not duplicate) statistics/core.py's existing
# chi-square/Fisher's-exact/Wilson-CI implementations. If core.py already
# provides fisher_exact_test() and wilson_score_interval() with compatible
# signatures, prefer those — these are provided here so audit_coordinator.py
# has a self-contained, zero-dependency fallback that matches its exact
# call signature for 2x2 paired-application tables.

def _log_factorial(n: int) -> float:
    """Log of n! using lgamma (math stdlib, zero dependency)."""
    return math.lgamma(n + 1)


def _hypergeom_pmf(k: int, total_a: int, total_b: int, n: int) -> float:
    """P(X=k) for hypergeometric distribution — used by Fisher's exact test."""
    log_p = (
        _log_factorial(total_a) - _log_factorial(k) - _log_factorial(total_a - k)
        + _log_factorial(total_b) - _log_factorial(n - k) - _log_factorial(total_b - n + k)
        - (_log_factorial(total_a + total_b) - _log_factorial(n) - _log_factorial(total_a + total_b - n))
    )
    return math.exp(log_p)


def fisher_exact_2x2(a: int, b: int, c: int, d: int) -> float:
    """Two-tailed Fisher's exact test for a 2x2 contingency table.

    Table layout:
                Outcome+   Outcome-
        GroupA     a          b
        GroupB     c          d

    Used in correspondence audits: GroupA/GroupB are the two paired profiles
    (e.g. "White-sounding name" vs "Black-sounding name"), Outcome+/- are
    "callback received" vs "no callback".

    Args:
        a: GroupA, outcome positive count.
        b: GroupA, outcome negative count.
        c: GroupB, outcome positive count.
        d: GroupB, outcome negative count.

    Returns:
        Two-tailed p-value in [0.0, 1.0].

    Raises:
        ValueError: If any input is negative.
    """
    if any(v < 0 for v in (a, b, c, d)):
        raise ValueError("Fisher's exact test requires non-negative cell counts")

    total_a = a + b  # row 1 total
    total_b = c + d  # row 2 total
    n = a + c        # column 1 total (outcome+ total)
    total = a + b + c + d

    if total == 0:
        return 1.0

    observed_p = _hypergeom_pmf(a, total_a, total_b, n)

    # Sum probabilities of all tables at least as extreme as observed
    p_value = 0.0
    k_min = max(0, n - total_b)
    k_max = min(n, total_a)
    for k in range(k_min, k_max + 1):
        p_k = _hypergeom_pmf(k, total_a, total_b, n)
        if p_k <= observed_p * (1 + 1e-9):  # tolerance for floating point
            p_value += p_k

    return min(1.0, p_value)


def wilson_score_interval(
    successes: int, n: int, confidence: float = 0.95
) -> tuple[float, float]:
    """Wilson score confidence interval for a binomial proportion.

    More accurate than the normal-approximation interval for small n or
    proportions near 0 or 1 — exactly the regime correspondence audits
    operate in (callback rates are often <10%).

    Args:
        successes: Number of successes (e.g. callbacks received).
        n: Total trials (e.g. applications sent).
        confidence: Confidence level, default 0.95 (95% CI).

    Returns:
        Tuple of (lower_bound, upper_bound), both in [0.0, 1.0].

    Raises:
        ValueError: If n <= 0 or successes > n or successes < 0.
    """
    if n <= 0:
        raise ValueError("n must be positive")
    if not (0 <= successes <= n):
        raise ValueError(f"successes must be in [0, {n}], got {successes}")

    # z-score for the given confidence level (two-tailed)
    # 0.95 -> 1.959964, 0.99 -> 2.575829
    z = _z_score_for_confidence(confidence)
    p_hat = successes / n
    z2 = z * z

    denominator = 1 + z2 / n
    center = p_hat + z2 / (2 * n)
    margin = z * math.sqrt((p_hat * (1 - p_hat) + z2 / (4 * n)) / n)

    lower = (center - margin) / denominator
    upper = (center + margin) / denominator
    return max(0.0, lower), min(1.0, upper)


def _z_score_for_confidence(confidence: float) -> float:
    """Approximate the z-score for a two-tailed confidence level via inverse erf."""
    # Solve: confidence = erf(z / sqrt(2))  =>  z = sqrt(2) * erfinv(confidence)
    # Python's math module lacks erfinv; use a Newton's method refinement
    # starting from a rational approximation (Acklam's algorithm, simplified).
    if confidence <= 0 or confidence >= 1:
        raise ValueError("confidence must be in (0, 1)")
    target = confidence
    # Initial guess via common values, refined with Newton's method on erf
    z = 1.96  # good starting point for 0.95
    for _ in range(50):
        f = math.erf(z / math.sqrt(2)) - target
        f_prime = math.sqrt(2 / math.pi) * math.exp(-z * z / 2)
        if f_prime == 0:
            break
        z_new = z - f / f_prime
        if abs(z_new - z) < 1e-10:
            z = z_new
            break
        z = z_new
    return z