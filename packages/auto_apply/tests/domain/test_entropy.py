"""Unit tests for domain/services/entropy.py — pure information-theory utilities."""

from auto_apply.domain.services.entropy import (
    calculate_consonant_ratio,
    calculate_entropy_density,
    calculate_shannon_entropy,
    is_randomized_trap_string,
)


# ── calculate_shannon_entropy ────────────────────────────────────────────────

def test_shannon_entropy_empty_string():
    assert calculate_shannon_entropy("") == 0.0


def test_shannon_entropy_uniform_string():
    # All identical characters → zero entropy
    assert calculate_shannon_entropy("aaaa") == 0.0


def test_shannon_entropy_max_two_chars():
    # "ab" each occurs once — entropy = 1.0 bit
    assert calculate_shannon_entropy("ab") == 1.0


def test_shannon_entropy_positive_for_varied_string():
    assert calculate_shannon_entropy("hello") > 0.0


# ── calculate_entropy_density ────────────────────────────────────────────────

def test_entropy_density_empty():
    assert calculate_entropy_density("") == 0.0


def test_entropy_density_single_char():
    assert calculate_entropy_density("a") == 0.0


def test_entropy_density_all_unique_chars():
    # "abcde" — every character distinct → density near 1.0
    density = calculate_entropy_density("abcde")
    assert density > 0.9


def test_entropy_density_repeated_chars_low():
    density = calculate_entropy_density("aaaa")
    assert density == 0.0


def test_entropy_density_range():
    density = calculate_entropy_density("password")
    assert 0.0 <= density <= 1.0


# ── calculate_consonant_ratio ────────────────────────────────────────────────

def test_consonant_ratio_no_letters():
    assert calculate_consonant_ratio("12345!@#") == 0.0


def test_consonant_ratio_all_vowels():
    assert calculate_consonant_ratio("aeiouAEIOU") == 0.0


def test_consonant_ratio_all_consonants():
    assert calculate_consonant_ratio("bcdfghjklmn") == 1.0


def test_consonant_ratio_mixed():
    # "password": p-s-s-w-r-d = 6 consonants, a-o = 2 vowels → 6/8 = 0.75
    ratio = calculate_consonant_ratio("password")
    assert abs(ratio - 0.75) < 0.01


# ── is_randomized_trap_string ────────────────────────────────────────────────

def test_normal_field_name_not_trapped():
    assert not is_randomized_trap_string("first_name")
    assert not is_randomized_trap_string("email_address")
    assert not is_randomized_trap_string("phone_number")
    assert not is_randomized_trap_string("password")


def test_too_short_not_trapped():
    assert not is_randomized_trap_string("")
    assert not is_randomized_trap_string("ab")
    assert not is_randomized_trap_string("xyz")


def test_random_hash_string_trapped():
    # "x7f9p2kd" — high entropy, high consonant ratio, high numeric ratio
    assert is_randomized_trap_string("x7f9p2kdmn")


def test_all_consonant_high_entropy_trapped():
    # "wbxzkpfvhm" — unique consonants only, max entropy density
    assert is_randomized_trap_string("wbxzkpfvhm")


def test_numeric_heavy_string_trapped():
    # "a1b2c3d4e5" — numeric ratio > 0.3 and high density
    assert is_randomized_trap_string("a1b2c3d4e5")


def test_semantic_field_with_numbers_not_trapped():
    # "email2" ends with a digit but is still semantic → short enough to skip
    assert not is_randomized_trap_string("em2")


def test_long_all_vowel_not_trapped():
    # All vowels → consonant_ratio = 0, can't be trapped by consonant rule
    assert not is_randomized_trap_string("aeiouaeiou")
