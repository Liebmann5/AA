"""Pins for the Phase-0 comparators and the token digest (package P0-1).

Each test is a counter-example that broke a looser rule, named in its
docstring. Two families of proof:

* pins that would also fail if pointed at ``option_matching.same_value`` /
  ``normalize`` today (ß, x², José, the +1 suffix, the extension fold, the
  empty pair) — the divergences are the point, and are marked as such;
* pins that share ground with the typing path (a reformatted phone mask, a
  basename-only file display) — the new module must not regress what the
  typing path gets right.

The comparators and the digest are pure: no I/O, no clock, no randomness, and
no value may appear in a log line or an exception message.
"""

from __future__ import annotations

import pytest

from auto_apply.domain.services.comparators import (
    CmpResult,
    Tri,
    canonical_value,
    cmp_choice,
    cmp_date_iso,
    cmp_digits,
    cmp_email,
    cmp_file,
    cmp_identity,
    cmp_text_long,
    digest_canonical,
)


# ─────────────────────────────────────────────────────────────────────────────
# Identity (names, short text)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "a,b",
    [
        ("  Alice  Smith ", "alice smith"),     # case + whitespace fold
        ("Alice\u200bSmith", "AliceSmith"),     # zero-width space stripped, words join
        ("Élodie", "élodie"),                   # case folds, accents kept
    ],
)
def test_identity_matches_after_fold(a, b):
    assert cmp_identity(a, b).tri is Tri.MATCH


@pytest.mark.parametrize(
    "a,b,why",
    [
        ("Maße", "Masse", "casefold() would equate ß with ss; str.lower() must not"),
        ("x²", "x2", "NFKC would equate the superscript; NFC must not"),
        ("José", "Jose", "accents are not stripped (accepted incompleteness)"),
        ("İ", "i", "Turkish dotted I does not fold to i on this path"),
        ("Alice\u200bSmith", "Alice Smith", "zero-width removal joins the words; it does not add a space"),
    ],
)
def test_identity_mismatch(a, b, why):
    result = cmp_identity(a, b)
    assert result.tri is Tri.MISMATCH, why


@pytest.mark.parametrize("a,b", [("", ""), ("", "x"), ("   ", "  ")])
def test_identity_empty_is_incomparable(a, b):
    """Empty is not evidence — and is not a match."""
    assert cmp_identity(a, b).tri is Tri.INCOMPARABLE
    assert cmp_identity(a, b).evidence == "empty"


# ─────────────────────────────────────────────────────────────────────────────
# Digits (phones) — decision 3: MATCH or INCOMPARABLE, never MISMATCH
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "a,b",
    [
        ("(555) 123-4567", "5551234567"),          # mask reformatting
        ("+1 (555) 123-4567", "+15551234567"),      # both carry +
        ("12-345", "123-45"),                       # grouping is cosmetic
        ("（５５５）１２３ー４５６７", "5551234567"),  # full-width digits fold
    ],
)
def test_digits_match(a, b):
    assert cmp_digits(a, b).tri is Tri.MATCH


def test_digits_plus_one_side_is_incomparable():
    """The measured defect: "+1 5551234567" vs "5551234567" must not match."""
    result = cmp_digits("+1 5551234567", "5551234567")
    assert result.tri is Tri.INCOMPARABLE
    assert result.evidence == "plus-mismatch"


def test_digits_one_sided_extension_is_incomparable():
    """"5551234567 ext 89" must not fold its extension into the digit string."""
    result = cmp_digits("5551234567 ext 89", "555123456789")
    assert result.tri is Tri.INCOMPARABLE
    assert result.evidence == "extension-present"


def test_digits_two_sided_extension_is_incomparable():
    """Phase 0 does not parse extensions, so even matching ones defer."""
    result = cmp_digits("+1 555 123 4567 ext 9", "+1 (555) 123-4567 ext. 9")
    assert result.tri is Tri.INCOMPARABLE


@pytest.mark.parametrize(
    "a,b,evidence",
    [
        ("", "", "no-digits"),
        ("abc", "def", "no-digits"),
        ("555-1234", "555-0123", "digits-differ"),
    ],
)
def test_digits_incomparable(a, b, evidence):
    result = cmp_digits(a, b)
    assert result.tri is Tri.INCOMPARABLE
    assert result.evidence == evidence


def test_digits_never_mismatch():
    """Decision 3: there is no MISMATCH for phones in Phase 0."""
    for a, b in [("1", "2"), ("+1555", "555"), ("555", "5555"), ("abc", "")]:
        assert cmp_digits(a, b).tri is not Tri.MISMATCH


# ─────────────────────────────────────────────────────────────────────────────
# Email
# ─────────────────────────────────────────────────────────────────────────────

def test_email_local_part_case_is_significant():
    """"A@b.com" vs "a@b.com": the local part is case-sensitive by spec."""
    assert cmp_email("A@b.com", "a@b.com").tri is Tri.MISMATCH


def test_email_domain_folds_case_and_idna():
    assert cmp_email("nick@Example.COM", "nick@example.com").tri is Tri.MATCH
    assert cmp_email("nick@bücher.de", "nick@xn--bcher-kva.de").tri is Tri.MATCH


def test_email_domain_difference_is_mismatch():
    assert cmp_email("nick@example.com", "nick@gmail.com").tri is Tri.MISMATCH


@pytest.mark.parametrize("a,b", [("not-an-email", "nick@example.com"), ("@example.com", "a@example.com")])
def test_email_unparseable_is_incomparable(a, b):
    assert cmp_email(a, b).tri is Tri.INCOMPARABLE


# ─────────────────────────────────────────────────────────────────────────────
# Dates (declared format only)
# ─────────────────────────────────────────────────────────────────────────────

def test_date_same_under_declared_format():
    assert cmp_date_iso("2026-01-15", "2026-01-15", declared_format="%Y-%m-%d").tri is Tri.MATCH
    assert cmp_date_iso("01/15/2026", "01/15/2026", declared_format="%m/%d/%Y").tri is Tri.MATCH


def test_date_two_valid_different_dates_are_mismatch():
    """A wrong date is MISMATCH, not INCOMPARABLE, when both sides parse."""
    assert cmp_date_iso("2026-01-15", "2026-01-16", declared_format="%Y-%m-%d").tri is Tri.MISMATCH


def test_date_undeclared_format_is_incomparable():
    """Nothing is ever guessed: no format, no verdict."""
    assert cmp_date_iso("2026-01-15", "2026-01-15", declared_format=None).tri is Tri.INCOMPARABLE
    assert cmp_date_iso("01/15/2026", "2026-01-15", declared_format="%Y-%m-%d").tri is Tri.INCOMPARABLE


# ─────────────────────────────────────────────────────────────────────────────
# Choice (exact set of (value, label))
# ─────────────────────────────────────────────────────────────────────────────

def test_choice_matches_regardless_of_order_and_label_folding():
    chosen = [("ca", "California"), ("nv", "Nevada")]
    selected = [("nv", " nevada "), ("ca", "California")]
    assert cmp_choice(chosen, selected).tri is Tri.MATCH


def test_choice_placeholder_readback_is_nothing_selected():
    chosen = [("ca", "California")]
    selected = [("", "--")]  # a placeholder shown as selected
    result = cmp_choice(chosen, selected)
    assert result.tri is Tri.MISMATCH
    assert result.evidence == "nothing-selected"


def test_choice_different_sets_mismatch():
    assert cmp_choice([("ca", "California")], [("nv", "Nevada")]).tri is Tri.MISMATCH


def test_choice_both_empty_is_incomparable():
    assert cmp_choice([], []).tri is Tri.INCOMPARABLE


def test_choice_duplicate_labels_or_values_are_incomparable():
    chosen = [("a", "One")]
    selected = [("a", "One")]
    dup_labels = [("a", "One"), ("b", "One")]
    dup_values = [("a", "One"), ("a", "Two")]
    assert cmp_choice(chosen, selected, options=dup_labels).tri is Tri.INCOMPARABLE
    assert cmp_choice(chosen, selected, options=dup_values).tri is Tri.INCOMPARABLE


def test_choice_malformed_input_is_incomparable():
    assert cmp_choice("not-pairs", []).tri is Tri.INCOMPARABLE
    assert cmp_choice([], "not-pairs").tri is Tri.INCOMPARABLE


# ─────────────────────────────────────────────────────────────────────────────
# File uploads
# ─────────────────────────────────────────────────────────────────────────────

def test_file_matches_on_basename_with_fakepath():
    """A browser shows C:\\fakepath\\name; the basename decides."""
    result = cmp_file(
        "/home/user/Resume.PDF",
        file_count=1,
        shown_name="C:\\fakepath\\resume.pdf",
    )
    assert result.tri is Tri.MATCH


def test_file_no_file_is_mismatch():
    assert cmp_file("resume.pdf", file_count=0).tri is Tri.MISMATCH
    assert cmp_file("resume.pdf", file_count=2).tri is Tri.MISMATCH
    assert cmp_file("resume.pdf", file_count=1, error_state=True).tri is Tri.MISMATCH
    assert cmp_file("resume.pdf", file_count=1, shown_name="other.pdf").tri is Tri.MISMATCH


def test_file_unproven_shapes_are_incomparable():
    assert cmp_file("resume.pdf", file_count=1, shown_name="").tri is Tri.INCOMPARABLE
    assert cmp_file("", file_count=1, shown_name="x.pdf").tri is Tri.INCOMPARABLE


# ─────────────────────────────────────────────────────────────────────────────
# Long text (paragraph structure kept)
# ─────────────────────────────────────────────────────────────────────────────

def test_text_long_matches_with_different_intra_paragraph_whitespace():
    written = "First   paragraph\nwith lines.\n\nSecond paragraph."
    readback = "First paragraph\nwith lines.\n\nSecond paragraph."
    assert cmp_text_long(written, readback).tri is Tri.MATCH


def test_text_long_paragraph_collapse_is_mismatch():
    """A page that erases the paragraph break did not store what was written."""
    assert cmp_text_long("one\n\ntwo", "one two").tri is Tri.MISMATCH


def test_text_long_truncation_is_incomparable_never_replanned():
    written = "abcdefghij"          # the field clips at 4
    result = cmp_text_long(written, "abcd", max_length=4)
    assert result.tri is Tri.INCOMPARABLE
    assert result.evidence == "truncated"


def test_text_long_empty_is_incomparable():
    assert cmp_text_long("", "").tri is Tri.INCOMPARABLE


# ─────────────────────────────────────────────────────────────────────────────
# Canonical forms
# ─────────────────────────────────────────────────────────────────────────────

def test_canonical_identity_and_empty():
    assert canonical_value("identity", "  Alice Smith ") == b"alice smith"
    assert canonical_value("identity", "   ") is None


def test_canonical_digits_and_extension():
    assert canonical_value("digits", "+1 (555) 123-4567") == b"+15551234567"
    assert canonical_value("digits", "5551234567 ext 9") is None
    assert canonical_value("digits", "no digits") is None


def test_canonical_email_keeps_local_case():
    assert canonical_value("email", "Nick@Bücher.de") == "Nick@xn--bcher-kva.de".encode("utf-8")
    assert canonical_value("email", "not-an-email") is None


def test_canonical_date_iso_only():
    assert canonical_value("date", "2026-01-15") == b"2026-01-15"
    assert canonical_value("date", "01/15/2026") is None


def test_canonical_choice_sorted_and_malformed_none():
    got = canonical_value("choice", [("b", "B"), ("a", " A ")])
    assert got == "a\x1fa\x1eb\x1fb".encode("utf-8")
    assert canonical_value("choice", "not-pairs") is None


def test_canonical_file_basename():
    assert canonical_value("file", "/x/y/Resume.PDF") == b"resume.pdf"
    assert canonical_value("file", "") is None


def test_canonical_unknown_kind_raises_without_values():
    with pytest.raises(ValueError) as excinfo:
        canonical_value("bogus-kind-ZZSECRET", "value")
    assert "ZZSECRET" not in str(excinfo.value)  # the kind is echoed nowhere either


# ─────────────────────────────────────────────────────────────────────────────
# The token digest (AA-TOKEN-v2)
# ─────────────────────────────────────────────────────────────────────────────

_PAIRS = [
    ("q.first", "identity", "  Alice "),
    ("q.phone", "digits", "+1 (555) 123-4567"),
    ("q.date", "date", "2026-01-15"),
]


def test_digest_is_deterministic():
    assert digest_canonical(_PAIRS) == digest_canonical(_PAIRS)


def test_digest_ignores_key_order():
    assert digest_canonical(_PAIRS) == digest_canonical(list(reversed(_PAIRS)))


def test_digest_avalanche_on_one_character():
    changed = [("q.first", "identity", "  AliceX ")] + _PAIRS[1:]
    assert digest_canonical(changed) != digest_canonical(_PAIRS)


def test_digest_framing_is_prefix_free():
    """Without length framing, ("ab","c") and ("a","bc") would collide."""
    left = digest_canonical([("ab", "identity", "c")])
    right = digest_canonical([("a", "identity", "bc")])
    assert left != right


def test_digest_tag_binds_kind():
    """Same key, same bytes, different kind → different digest."""
    as_text = digest_canonical([("k", "identity", "2026-01-15")])
    as_date = digest_canonical([("k", "date", "2026-01-15")])
    assert as_text != as_date


def test_digest_raw_tier_differs_from_canonical():
    """A date that is not ISO digsests RAW, and differs from the canonical form."""
    raw = digest_canonical([("k", "date", "15/01/2026")])
    canon = digest_canonical([("k", "date", "2026-01-15")])
    assert raw != canon


@pytest.mark.parametrize(
    "pairs,error",
    [
        ([("k", "identity", "x"), ("k", "digits", "1")], "duplicate question key"),
        ([("k", "bogus-kind", "x")], "unknown comparator kind"),
        ([("", "identity", "x")], "question keys must be non-empty strings"),
        ([("just-a-string",)], "each entry must be a (question key, kind, value) triple"),
    ],
)
def test_digest_rejects_bad_input(pairs, error):
    with pytest.raises(ValueError) as excinfo:
        digest_canonical(pairs)
    assert str(excinfo.value) == error


def test_digest_error_messages_carry_no_values():
    """The token binds values; its errors must never repeat them."""
    with pytest.raises(ValueError) as excinfo:
        digest_canonical([("k", "identity", "ZZSECRET"), ("k", "digits", "1")])
    assert "ZZSECRET" not in str(excinfo.value)
