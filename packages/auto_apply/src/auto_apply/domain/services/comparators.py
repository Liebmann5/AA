"""Typed comparators and canonical forms — the verify path's ground truth.

Phase 0, package P0-1. Two jobs:

1. **Comparators.** Each ``cmp_*`` function compares what AA wrote with what
   the page shows on read-back, and answers ``MATCH``, ``MISMATCH`` or
   ``INCOMPARABLE``. The asymmetry is deliberate and load-bearing:

   * ``MISMATCH`` never asserts the site is wrong — it means the fill did not
     take as written; the engine re-plans once, then asks.
   * ``INCOMPARABLE`` means the page shows nothing AA can soundly compare (a
     masked display, an ambiguous phone shape, an undeclared date format). The
     outcome is UNPROVEN, and UNPROVEN asks — it never re-plans in a loop and
     never silently passes.

2. **Canonical forms.** ``canonical_value(kind, value)`` returns the bytes a
   comparator considers meaning-preserving for its kind, or ``None`` when no
   canonical form exists for that value. ``digest_canonical`` frames
   ``(question key, kind, value)`` triples into the one-use submit token's
   digest (``AA-TOKEN-v2``): fixed-width big-endian lengths and a one-byte tag
   (kind index shifted left, raw-flag bit) make the framing prefix-free. A
   value with no canonical form is digested RAW (NFC) with the raw bit set, so
   a change to an unparseable value is always detected.

The verify path only. The typing path keeps ``option_matching.same_value`` —
mask-tolerant *entry* comparison — which this module does not touch and does
not replace.

Soundness and its documented limits (each is a counter-example that broke a
looser rule):

* text is NFC + zero-width-strip + ``str.lower()`` — never ``casefold()``
  ("Maße" ≠ "Masse"), never NFKC ("x²" ≠ "x2"). Accents are not stripped:
  "José" ≠ "Jose" is an accepted incompleteness, as is Turkish İ.
* phones are digits + "+" only: no calling-code table, so anything that is not
  provably equal is INCOMPARABLE — including every digit difference (there is
  no MISMATCH for phones in Phase 0: a digit difference may be a missing
  country code, which Phase 0 cannot tell apart from a wrong number).
* an email's local part is case-sensitive by spec, so it is compared exactly.
* dates compare only under a declared format; nothing is ever guessed.
* a choice compares the exact set of (value, label) pairs; a duplicate label
  or value anywhere in the option set makes the whole answer incomparable.
* a long text keeps its paragraph structure; a page-clipped value is
  INCOMPARABLE ("truncated"), so it is asked about instead of re-planned.

No logging anywhere in this module, and no exception message interpolates a
value: comparators see values, and values never leave the caller.
"""

from __future__ import annotations

import hashlib
import re
import struct
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from typing import Any

from auto_apply.domain.applications.option_matching import is_placeholder

__all__ = [
    "TOKEN_MAGIC",
    "KIND_INDEX",
    "KIND_IDENTITY", "KIND_DIGITS", "KIND_EMAIL", "KIND_DATE",
    "KIND_CHOICE", "KIND_FILE", "KIND_TEXT_LONG",
    "Tri", "CmpResult",
    "cmp_identity", "cmp_digits", "cmp_email", "cmp_date_iso",
    "cmp_choice", "cmp_file", "cmp_text_long",
    "canonical_value", "digest_canonical",
]

#: Magic prefix of the one-use submit token's digest (AA_ENGINE_MATH §3).
TOKEN_MAGIC = b"AA-TOKEN-v2"

KIND_IDENTITY = "identity"
KIND_DIGITS = "digits"
KIND_EMAIL = "email"
KIND_DATE = "date"
KIND_CHOICE = "choice"
KIND_FILE = "file"
KIND_TEXT_LONG = "text_long"

#: The kind table. The digest's tag byte is ``(index << 1) | raw_flag``.
KIND_INDEX = {
    KIND_IDENTITY: 0,
    KIND_DIGITS: 1,
    KIND_EMAIL: 2,
    KIND_DATE: 3,
    KIND_CHOICE: 4,
    KIND_FILE: 5,
    KIND_TEXT_LONG: 6,
}


class Tri(Enum):
    """The three-way comparison verdict. INCOMPARABLE is not MISMATCH."""

    MATCH = auto()
    MISMATCH = auto()
    INCOMPARABLE = auto()


@dataclass(frozen=True)
class CmpResult:
    """One comparison verdict with an enum-keyed evidence string."""

    tri: Tri
    evidence: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Shared normalisers
# ─────────────────────────────────────────────────────────────────────────────

_WS = re.compile(r"\s+")
#: An extension marker at the end of a phone string: "ext 89", "ext. 89",
#: "extension 89", "x89", "#89". One-sided *or* two-sided, it makes the
#: comparison incomparable — Phase 0 does not parse extensions.
_EXT_RE = re.compile(r"(?:\bext(?:ension)?\b\.?|[#xX])\s*\d+\s*$", re.IGNORECASE)


def _fold_text(value: Any) -> str:
    """NFC → strip zero-width/format chars (Cf) → ``str.lower()`` → collapse
    whitespace. Deliberately never ``casefold()`` (ß) and never NFKC (x²);
    accents are kept, so "José" ≠ "Jose"."""
    if value is None:
        return ""
    s = unicodedata.normalize("NFC", str(value))
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Cf")
    return _WS.sub(" ", s.lower()).strip()


def _digits_of(text: str) -> str:
    """Every decimal digit, ASCII-folded (Arabic-Indic, Devanagari, full-width
    digits read the same as 0-9)."""
    return "".join(str(unicodedata.decimal(ch)) for ch in text if ch.isdecimal())


def _basename(text: str) -> str:
    """The last path segment, with both separators (a browser shows
    ``C:\\fakepath\\name.pdf`` for an uploaded file)."""
    return text.replace("\\", "/").rsplit("/", 1)[-1]


def _paragraphs(text: str) -> list[str]:
    """Blank-line-separated paragraphs, each folded; empties dropped."""
    return [p for p in (_fold_text(part) for part in re.split(r"\n\s*\n", text)) if p]


# ─────────────────────────────────────────────────────────────────────────────
# Comparators
# ─────────────────────────────────────────────────────────────────────────────

def cmp_identity(a: Any, b: Any) -> CmpResult:
    """Names and short text: folded equality. Empty is not evidence."""
    fa, fb = _fold_text(a), _fold_text(b)
    if not fa or not fb:
        return CmpResult(Tri.INCOMPARABLE, "empty")
    if fa == fb:
        return CmpResult(Tri.MATCH, "identical-after-fold")
    return CmpResult(Tri.MISMATCH, "text-differs")


def cmp_digits(a: Any, b: Any) -> CmpResult:
    """Phones, Phase 0: MATCH only when the digit strings are equal and both
    values carry an explicit ``+``, or neither does and their lengths are
    equal. Everything else is INCOMPARABLE — there is no MISMATCH here,
    because a digit difference may be a missing country code, which Phase 0
    cannot tell from a wrong number.

    The length test is part of the stated rule; under equal digit strings it
    can never fire (equal strings have equal length), and it is kept as
    stated.
    """
    sa = "" if a is None else str(a)
    sb = "" if b is None else str(b)
    da, db = _digits_of(sa), _digits_of(sb)
    if not da or not db:
        return CmpResult(Tri.INCOMPARABLE, "no-digits")
    if _EXT_RE.search(sa) or _EXT_RE.search(sb):
        return CmpResult(Tri.INCOMPARABLE, "extension-present")
    plus_a, plus_b = "+" in sa, "+" in sb
    if plus_a != plus_b:
        return CmpResult(Tri.INCOMPARABLE, "plus-mismatch")
    if da != db:
        return CmpResult(Tri.INCOMPARABLE, "digits-differ")
    if not plus_a and len(da) != len(db):
        return CmpResult(Tri.INCOMPARABLE, "length-differs")
    return CmpResult(Tri.MATCH, "digits-equal")


def _parse_email(text: str) -> tuple[str, str] | None:
    """(local part, IDNA-lowercased domain), or None when it cannot be parsed."""
    local, sep, domain = text.strip().rpartition("@")
    if not sep or not local or not domain:
        return None
    try:
        domain_ascii = domain.encode("idna").decode("ascii").lower()
    except UnicodeError:
        return None
    if not domain_ascii:
        return None
    return local, domain_ascii


def cmp_email(a: Any, b: Any) -> CmpResult:
    """Local part exact (case is significant there); domain via IDNA, folded."""
    pa = _parse_email("" if a is None else str(a))
    pb = _parse_email("" if b is None else str(b))
    if pa is None or pb is None:
        return CmpResult(Tri.INCOMPARABLE, "unparseable")
    local_a, domain_a = pa
    local_b, domain_b = pb
    if domain_a != domain_b:
        return CmpResult(Tri.MISMATCH, "domain-differs")
    if local_a != local_b:
        return CmpResult(Tri.MISMATCH, "local-part-differs")
    return CmpResult(Tri.MATCH, "email-equal")


def cmp_date_iso(a: Any, b: Any, *, declared_format: str | None) -> CmpResult:
    """Both sides parsed under the declared format only. Two valid different
    dates are MISMATCH; anything unparseable or undeclared is INCOMPARABLE."""
    if not declared_format:
        return CmpResult(Tri.INCOMPARABLE, "format-undeclared")
    try:
        da = datetime.strptime(str(a).strip(), declared_format).date()
        db = datetime.strptime(str(b).strip(), declared_format).date()
    except (ValueError, TypeError):
        return CmpResult(Tri.INCOMPARABLE, "unparseable")
    if da == db:
        return CmpResult(Tri.MATCH, "same-date")
    return CmpResult(Tri.MISMATCH, "different-date")


def _option_pairs(pairs: Any) -> list[tuple[str, str]] | None:
    """A list of (value, folded label), or None when the shape is wrong."""
    out: list[tuple[str, str]] = []
    try:
        iterator = iter(pairs)
    except TypeError:
        return None
    for item in iterator:
        try:
            value, label = item
        except (TypeError, ValueError):
            return None
        out.append((str(value), _fold_text(label)))
    return out


def cmp_choice(chosen: Any, selected: Any, *, options: Any = ()) -> CmpResult:
    """The exact set of (value, label) pairs written vs shown selected.

    Identity is the (value, label) pair itself; a duplicate value or a
    duplicate label anywhere in the full option set makes the answer
    incomparable. A placeholder shown as selected reads as "nothing
    selected".
    """
    opts = _option_pairs(options)
    if opts is None:
        return CmpResult(Tri.INCOMPARABLE, "malformed-options")
    values = [v for v, _label in opts]
    labels = [label for _v, label in opts]
    if len(set(values)) != len(values) or len(set(labels)) != len(labels):
        return CmpResult(Tri.INCOMPARABLE, "duplicate-options")
    chosen_set = _option_pairs(chosen)
    selected_set = _option_pairs(selected)
    if chosen_set is None or selected_set is None:
        return CmpResult(Tri.INCOMPARABLE, "malformed")
    selected = {(v, l) for v, l in selected_set if not is_placeholder(l)}
    wanted = set(chosen_set)
    if not wanted and not selected:
        return CmpResult(Tri.INCOMPARABLE, "empty")
    if not selected:
        return CmpResult(Tri.MISMATCH, "nothing-selected")
    if not wanted:
        return CmpResult(Tri.MISMATCH, "unexpected-selection")
    if wanted == selected:
        return CmpResult(Tri.MATCH, "sets-equal")
    return CmpResult(Tri.MISMATCH, "sets-differ")


def cmp_file(
    intended_basename: Any,
    *,
    file_count: Any,
    shown_name: Any = "",
    error_state: bool = False,
) -> CmpResult:
    """A file upload: one file, its basename matches, no upload-error state.

    ``file_count`` and the shown name come from the page; a page that shows
    no name is INCOMPARABLE, not wrong.
    """
    intended = _fold_text(_basename(str(intended_basename) if intended_basename else ""))
    if not intended:
        return CmpResult(Tri.INCOMPARABLE, "no-intended-file")
    try:
        count = int(file_count)
    except (TypeError, ValueError):
        return CmpResult(Tri.INCOMPARABLE, "count-unknown")
    if count == 0:
        return CmpResult(Tri.MISMATCH, "no-file-attached")
    if count != 1:
        return CmpResult(Tri.MISMATCH, "multiple-files")
    if error_state:
        return CmpResult(Tri.MISMATCH, "upload-error")
    shown = _fold_text(_basename(str(shown_name) if shown_name else ""))
    if not shown:
        return CmpResult(Tri.INCOMPARABLE, "name-not-shown")
    if shown != intended:
        return CmpResult(Tri.MISMATCH, "name-differs")
    return CmpResult(Tri.MATCH, "file-attached")


def cmp_text_long(written: Any, readback: Any, *, max_length: int | None = None) -> CmpResult:
    """Long text with paragraph structure kept. A value clipped to the field's
    ``max_length`` is INCOMPARABLE ("truncated") — asked about, never
    re-planned."""
    w = "" if written is None else str(written)
    r = "" if readback is None else str(readback)
    if not w.strip() or not r.strip():
        return CmpResult(Tri.INCOMPARABLE, "empty")
    if (
        max_length is not None
        and len(r) == max_length
        and r != w
        and w.startswith(r)
    ):
        return CmpResult(Tri.INCOMPARABLE, "truncated")
    if _paragraphs(w) == _paragraphs(r):
        return CmpResult(Tri.MATCH, "paragraphs-equal")
    return CmpResult(Tri.MISMATCH, "paragraphs-differ")


# ─────────────────────────────────────────────────────────────────────────────
# Canonical forms and the token digest
# ─────────────────────────────────────────────────────────────────────────────

def canonical_value(kind: str, value: Any) -> bytes | None:
    """The canonical bytes for ``value`` under ``kind``, or None (the RAW tier).

    None means: no meaning-preserving canonical form exists for this value,
    so the digest binds it RAW instead — a change is always detected.
    """
    if kind == KIND_IDENTITY:
        folded = _fold_text(value)
        return folded.encode("utf-8") if folded else None
    if kind == KIND_TEXT_LONG:
        joined = "\n\n".join(_paragraphs("" if value is None else str(value)))
        return joined.encode("utf-8") if joined else None
    if kind == KIND_DIGITS:
        s = "" if value is None else str(value)
        digits = _digits_of(s)
        if not digits or _EXT_RE.search(s):
            return None
        return (b"+" if "+" in s else b"") + digits.encode("ascii")
    if kind == KIND_EMAIL:
        parsed = _parse_email("" if value is None else str(value))
        if parsed is None:
            return None
        return f"{parsed[0]}@{parsed[1]}".encode("utf-8")
    if kind == KIND_DATE:
        try:
            parsed_date = datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None
        return parsed_date.isoformat().encode("ascii")
    if kind == KIND_CHOICE:
        pairs = _option_pairs(value)
        if pairs is None:
            return None
        canon = sorted(f"{v}\x1f{label}" for v, label in pairs)
        if not canon:
            return None
        return "\x1e".join(canon).encode("utf-8")
    if kind == KIND_FILE:
        name = _fold_text(_basename(str(value) if value else ""))
        return name.encode("utf-8") if name else None
    raise ValueError("unknown comparator kind")


def digest_canonical(pairs: Iterable[tuple[str, str, Any]]) -> str:
    """The AA-TOKEN-v2 digest of ``(question key, kind, value)`` triples.

    Framing: MAGIC ‖ per triple, sorted by key bytes —
    ``u64be(len(key)) ‖ key ‖ tag ‖ u64be(len(payload)) ‖ payload`` where
    ``tag = (kind_index << 1) | raw_flag``. Fixed-width lengths make the
    framing prefix-free; sorting makes key order irrelevant; the tag binds
    kind and tier. Returns the SHA-256 hex digest.

    Raises ValueError (never interpolating any value) on a duplicate or empty
    key, an unknown kind, or a malformed triple: a malformed token input is a
    programming error, and the token layer treats it as do-not-arm.
    """
    items: list[tuple[bytes, int, bytes]] = []
    seen: set[bytes] = set()
    for entry in pairs:
        try:
            key, kind, value = entry
        except (TypeError, ValueError) as exc:
            raise ValueError("each entry must be a (question key, kind, value) triple") from exc
        if not isinstance(key, str) or not key.strip():
            raise ValueError("question keys must be non-empty strings")
        if kind not in KIND_INDEX:
            raise ValueError("unknown comparator kind")
        key_bytes = key.encode("utf-8")
        if key_bytes in seen:
            raise ValueError("duplicate question key")
        seen.add(key_bytes)
        payload = canonical_value(kind, value)
        raw_flag = 0
        if payload is None:
            raw_flag = 1
            payload = unicodedata.normalize("NFC", "" if value is None else str(value)).encode(
                "utf-8", "surrogatepass"
            )
        tag = (KIND_INDEX[kind] << 1) | raw_flag
        items.append((key_bytes, tag, payload))
    items.sort(key=lambda item: item[0])
    hasher = hashlib.sha256()
    hasher.update(TOKEN_MAGIC)
    for key_bytes, tag, payload in items:
        hasher.update(struct.pack(">Q", len(key_bytes)))
        hasher.update(key_bytes)
        hasher.update(bytes([tag]))
        hasher.update(struct.pack(">Q", len(payload)))
        hasher.update(payload)
    return hasher.hexdigest()
