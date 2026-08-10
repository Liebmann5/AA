"""S8h pins — spaCy vector guard (R-6 ruling).

Pin labels (honest, per standing method):
  A  TEETH (source-level) — en_core_web_sm must not appear as a quoted model
     name anywhere in text_matching.py. Pre-stage it appears in both
     load-order tuples -> fails.
  B  TEETH (mock-level) — a model that loads with n_keys == 0 must be
     REJECTED, not adopted. Pre-stage it is accepted (has_vector is the wrong
     check), so matcher._nlp is not None -> fails.
  E  TEETH (ordering) — prefer_small must try md first and must never load
     sm. Pre-stage the low-resource order is (sm, md, lg): sm loads first and
     is accepted -> fails.
  C  BEHAVIOUR-PRESERVING — a vector-bearing model loads and is used,
     identically on both trees (asserts only pre-existing attributes).
  D  BEHAVIOUR-PRESERVING — no spaCy at all keeps the difflib path and its
     exact similarity values, identically on both trees.

The fakes emulate only what _initialize_engine touches: spacy.load() and
vocab.vectors.n_keys. No real spaCy install is needed to run these.
"""
from __future__ import annotations

import logging
from pathlib import Path

import auto_apply.application.services.text_matching as tm
from auto_apply.application.services.text_matching import TextMatcher


class _FakeVectors:
    def __init__(self, n_keys: int) -> None:
        self.n_keys = n_keys


class _FakeVocab:
    def __init__(self, n_keys: int) -> None:
        self.vectors = _FakeVectors(n_keys)


class _FakeNLP:
    """Minimal spaCy model stand-in for the load-time check."""

    def __init__(self, n_keys: int) -> None:
        self.vocab = _FakeVocab(n_keys)


class _FakeSpacy:
    """Module stand-in: load() returns a model with a configurable vector store."""

    def __init__(self, n_keys_by_model: dict[str, int]) -> None:
        self._n_keys_by_model = n_keys_by_model
        self.loaded: list[str] = []

    def load(self, model_name: str):
        self.loaded.append(model_name)
        if model_name not in self._n_keys_by_model:
            raise OSError(f"model {model_name} not found")
        return _FakeNLP(self._n_keys_by_model[model_name])


# --------------------------------------------------------------------------
# Pin A (TEETH): sm appears nowhere as a loadable model
# --------------------------------------------------------------------------

def test_sm_model_is_not_in_any_load_order() -> None:
    src = Path(tm.__file__).read_text(encoding="utf-8")
    assert '"en_core_web_sm"' not in src and "'en_core_web_sm'" not in src, (
        "en_core_web_sm is still present as a loadable model in "
        "text_matching.py — it ships no word vectors and inflates "
        "similarity scores (CB-4)"
    )


# --------------------------------------------------------------------------
# Pin B (TEETH): vector-less model is rejected; honest Tier 2 is logged
# --------------------------------------------------------------------------

def test_vectorless_model_is_rejected_and_tier2_logged(monkeypatch, caplog) -> None:
    fake = _FakeSpacy({"en_core_web_lg": 0, "en_core_web_md": 0})
    monkeypatch.setattr(tm, "_spacy", fake)

    with caplog.at_level(
        logging.INFO, logger="auto_apply.application.services.text_matching"
    ):
        matcher = TextMatcher()

    assert matcher._nlp is None, (
        "a model with vocab.vectors.n_keys == 0 was adopted as the engine — "
        "the load-time guard is still checking the wrong thing"
    )
    assert matcher.vectors_verified is False
    assert matcher.fallback_reason == "no_vector_bearing_model"
    assert any("difflib" in r.message for r in caplog.records), (
        "the honest Tier-2 fallback must be logged, not silent"
    )


# --------------------------------------------------------------------------
# Pin E (TEETH): prefer_small tries md first and never touches sm
# --------------------------------------------------------------------------

def test_prefer_small_tries_md_first_and_never_loads_sm(monkeypatch) -> None:
    fake = _FakeSpacy(
        {
            "en_core_web_md": 400_000,
            "en_core_web_lg": 500_000,
            "en_core_web_sm": 0,
        }
    )
    monkeypatch.setattr(tm, "_spacy", fake)

    TextMatcher(prefer_small=True)

    assert fake.loaded[0] == "en_core_web_md", (
        f"low-resource sessions must try md first; got order {fake.loaded}"
    )
    assert "en_core_web_sm" not in fake.loaded, (
        "sm was loaded — the vector-less model is still in a load order"
    )


# --------------------------------------------------------------------------
# Pin C (BEHAVIOUR-PRESERVING): vector-bearing model loads and is used
# --------------------------------------------------------------------------

def test_vector_bearing_model_is_accepted(monkeypatch) -> None:
    fake = _FakeSpacy({"en_core_web_lg": 500_000, "en_core_web_md": 400_000})
    monkeypatch.setattr(tm, "_spacy", fake)

    matcher = TextMatcher()

    assert matcher._nlp is not None
    assert matcher._engine_type == "spacy_lg"
    assert fake.loaded == ["en_core_web_lg"], (
        "the first qualifying model must win; no further loads should happen"
    )


# --------------------------------------------------------------------------
# Pin D (BEHAVIOUR-PRESERVING): no spaCy -> difflib, values unchanged
# --------------------------------------------------------------------------

def test_no_spacy_falls_back_to_difflib_unchanged(monkeypatch) -> None:
    monkeypatch.setattr(tm, "_spacy", None)

    matcher = TextMatcher()

    assert matcher._nlp is None
    assert matcher.get_similarity("python engineer", "python engineer") == 1.0
    assert matcher.get_similarity("python", "java") < 1.0
