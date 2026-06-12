"""
domain/web_math_core/algorithms/entropy.py

Information Theory utilities to detect randomized, bot-trap strings.

Anti-bot systems (like Cloudflare Turnstile or DataDome) inject fake input fields
with randomized names (e.g., name="a7x9f_p"). Standard fields use semantic, low-entropy
names (e.g., name="first_name").

By measuring Entropy Density and Consonant Ratios, we deterministically identify traps
without relying on hardcoded blacklist dictionaries.
"""

import math


def calculate_shannon_entropy(text: str) -> float:
    """Calculate the raw Shannon Entropy of a string."""
    if not text:
        return 0.0

    length = len(text)
    frequencies: dict[str, int] = {}
    for char in text:
        frequencies[char] = frequencies.get(char, 0) + 1

    entropy = 0.0
    for count in frequencies.values():
        probability = count / length
        entropy -= probability * math.log2(probability)

    return entropy

def calculate_entropy_density(text: str) -> float:
    """
    Calculates normalized entropy (0.0 to 1.0).
    Solves the problem where short strings naturally have low raw entropy.
    """
    if not text or len(text) <= 1:
        return 0.0

    actual_entropy = calculate_shannon_entropy(text)
    # The maximum possible entropy for a string of this length
    max_entropy = math.log2(len(text))

    return actual_entropy / max_entropy if max_entropy > 0 else 0.0

def calculate_consonant_ratio(text: str) -> float:
    """Calculates the ratio of consonants to total letters (ignores numbers/symbols)."""
    vowels = set("aeiouAEIOU")
    letters = [c for c in text if c.isalpha()]

    if not letters:
        return 0.0

    consonants = [c for c in letters if c not in vowels]
    return len(consonants) / len(letters)

def is_randomized_trap_string(text: str) -> bool:
    """
    Combines Information Theory and Linguistic heuristics to flag trap strings.

    Args:
        text: The attribute value to check (e.g., input node's 'name' or 'id').

    Returns:
        True if the string mathematically resembles a generated hash/trap.
    """
    if not text or len(text) < 5:
        # Too short to be a reliable hash trap
        return False

    density = calculate_entropy_density(text)
    consonant_ratio = calculate_consonant_ratio(text)

    # A standard word like "password" has density ~0.9 but a consonant ratio of ~0.71.
    # A hash like "x7f9a2p" has density ~1.0 and a consonant ratio of 1.0 (no vowels).
    # If it is exceptionally dense OR it completely lacks vowels, it's a trap.
    if density > 0.95 and consonant_ratio > 0.85:
        return True

    # Strings with numbers intermixed randomly (not just at the end like 'email2')
    numeric_ratio = len([c for c in text if c.isdigit()]) / len(text)
    if numeric_ratio > 0.3 and density > 0.85:
        return True

    return False
