"""Intelligent text matching and NLP services for Vetting and Application workflows.

Uses a two-tier progressive enhancement strategy:
    Tier 1: SpaCy (en_core_web_lg → en_core_web_md — vector-verified at load;
        en_core_web_sm is excluded: it ships no word vectors, so its
        doc.similarity() emits W007 and returns inflated scores — R-6/CB-4)
    Tier 2: stdlib difflib.SequenceMatcher (always available)

SentenceTransformers is NOT used — SpaCy is the sole NLP library.

SpaCy capabilities used:
    - doc.similarity(doc2)  — cosine similarity via word vectors (md/lg only)
    - PhraseMatcher          — fast skill/keyword extraction against a vocabulary
    - doc.ents               — named entity recognition (GPE, ORG, LOC, PERSON)
    - doc.sents              — sentence segmentation

Install:
    pip install "auto-apply[nlp]"
    python -m spacy download en_core_web_lg

Without SpaCy, the system falls back to difflib (reduced accuracy, fully functional).
"""
from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from typing import Any

logger = logging.getLogger(__name__)

try:
    import spacy as _spacy  # noqa: PLC0415
except ImportError:
    _spacy = None  # type: ignore[assignment]


class TextMatcher:
    """Unified interface for text similarity, entity extraction, and NLP utilities.

    Abstracts the underlying engine. Workflows call get_similarity(), find_best_match(),
    extract_entities(), split_sentences(), and load_skills_vocabulary() without
    knowing whether SpaCy or difflib is active.
    """

    def __init__(self, prefer_small: bool = False) -> None:
        self._engine_type: str = "basic"
        self._nlp: Any = None
        self._phrase_matcher: Any = None
        self._vectors_verified: bool = False
        self._fallback_reason: str | None = None
        self._initialize_engine(prefer_small=prefer_small)

    @property
    def engine_type(self) -> str:
        """Active engine tier: 'spacy_lg' | 'spacy_md' | 'basic' (difflib)."""
        return self._engine_type

    @property
    def vectors_verified(self) -> bool:
        """True iff a vector-bearing SpaCy model passed the load-time check.

        This is the R-6 capability self-check result, exposed as session
        evidence. When False, all similarity scoring is difflib (Tier 2) —
        by honest choice, not silent degradation.
        """
        return self._vectors_verified

    @property
    def fallback_reason(self) -> str | None:
        """Why Tier 2 is active, when it is: 'spacy_not_installed' |
        'no_model_installed' | 'no_vector_bearing_model'. None on Tier 1."""
        return self._fallback_reason

    def _initialize_engine(self, prefer_small: bool = False) -> None:
        """Load the best available SpaCy model; fall back to difflib.

        Args:
            prefer_small: If True, try smaller models first to reduce memory pressure
                on low‑resource hardware.
        """
        if _spacy is None:
            self._fallback_reason = "spacy_not_installed"
            logger.info(
                "TextMatcher: SpaCy not installed - using stdlib difflib (Tier 2)"
            )
            return

        # en_core_web_sm is deliberately excluded (R-6/CB-4): it ships no
        # static word vectors, so doc.similarity() falls back to tok2vec —
        # W007 and inflated scores. Low-resource sessions try md first
        # (smaller footprint); sm is never an option on any hardware.
        model_order = (
            ("en_core_web_md", "en_core_web_lg")
            if prefer_small
            else ("en_core_web_lg", "en_core_web_md")
        )

        saw_load_failure = False
        saw_vectorless_model = False

        for model_name in model_order:
            try:
                candidate = _spacy.load(model_name)
            except OSError:
                saw_load_failure = True
                continue

            # One-time capability self-check: the model must ship word vectors.
            # Doc.has_vector is NOT a valid check — on vector-less models it
            # still returns True via tok2vec (the CB-4 defect). n_keys is the
            # honest signal, checked once here instead of per similarity call.
            n_keys = getattr(
                getattr(getattr(candidate, "vocab", None), "vectors", None),
                "n_keys",
                0,
            )
            if not n_keys:
                saw_vectorless_model = True
                logger.warning(
                    "TextMatcher: %s loaded but ships no word vectors "
                    "(vocab.vectors.n_keys == 0) - rejecting it; doc.similarity() "
                    "on a vector-less model emits W007 and returns inflated scores.",
                    model_name,
                )
                continue

            self._nlp = candidate
            self._engine_type = f"spacy_{model_name.split('_')[-1]}"
            self._vectors_verified = True
            logger.info(
                "TextMatcher: SpaCy loaded and vector-verified (%s, vectors=%d)",
                model_name,
                n_keys,
            )
            return

        # No qualifying model: honest Tier 2, with the reason on the record.
        self._fallback_reason = (
            "no_vector_bearing_model" if saw_vectorless_model else "no_model_installed"
        )
        logger.info(
            "TextMatcher: no vector-bearing SpaCy model available (%s) - "
            "using stdlib difflib (Tier 2). Install one with: "
            "python -m spacy download en_core_web_md",
            "models present but vector-less"
            if saw_vectorless_model
            else "none installed"
            if saw_load_failure
            else "no qualifying models",
        )

    def get_similarity(self, text_a: str, text_b: str) -> float:
        """Calculate a similarity score between two strings in [0.0, 1.0].

        Args:
            text_a: First text string.
            text_b: Second text string.

        Returns:
            Float in [0.0, 1.0]. Higher = more similar.
        """
        if not text_a or not text_b:
            return 0.0

        if self._nlp is not None:
            return self._match_spacy(text_a, text_b)

        return self._match_basic(text_a, text_b)

    def find_best_match(self, query: str, candidates: list[str]) -> tuple[str, float]:
        """Find the best matching string from a list of candidates.

        Args:
            query: The reference string to match against.
            candidates: List of strings to compare.

        Returns:
            Tuple of (best_matching_candidate, score).
        """
        best_score = -1.0
        best_match = ""

        for candidate in candidates:
            score = self.get_similarity(query, candidate)
            if score > best_score:
                best_score = score
                best_match = candidate

        return best_match, best_score

    def extract_entities(self, text: str) -> dict[str, list[str]]:
        """Extract named entities and skills from text.

        Uses SpaCy NER + PhraseMatcher when available. Falls back to regex-only
        extraction under the difflib tier.

        Args:
            text: Raw text to analyze (job description, label text, etc.)

        Returns:
            Dict with keys:
                'skills'           — list[str]: matched skill/tech terms
                'locations'        — list[str]: GPE + LOC entity strings
                'organizations'    — list[str]: ORG entity strings
                'experience_years' — list[str]: strings like "3", "5+" found in text

            Never raises — returns empty lists on error.
        """
        result: dict[str, list[str]] = {
            "skills": [],
            "locations": [],
            "organizations": [],
            "experience_years": [],
        }

        year_pattern = re.compile(
            r"(\d+\+?)\s*(?:to\s*\d+\s*)?years?",
            re.IGNORECASE,
        )
        result["experience_years"] = year_pattern.findall(text)

        if self._nlp is None:
            return result

        try:
            doc = self._nlp(text[:10_000])

            for ent in doc.ents:
                if ent.label_ in ("GPE", "LOC"):
                    result["locations"].append(ent.text)
                elif ent.label_ == "ORG":
                    result["organizations"].append(ent.text)

            if self._phrase_matcher is not None:
                matches = self._phrase_matcher(doc)
                for _, start, end in matches:
                    result["skills"].append(doc[start:end].text)

            for key in result:
                seen: set[str] = set()
                deduped: list[str] = []
                for item in result[key]:
                    normalized = item.lower()
                    if normalized not in seen:
                        seen.add(normalized)
                        deduped.append(item)
                result[key] = deduped

        except Exception as exc:
            logger.warning("TextMatcher.extract_entities failed: %s", exc)

        return result

    def split_sentences(self, text: str) -> list[str]:
        """Split text into sentences.

        Uses SpaCy sentence segmentation when available. Falls back to regex.

        Args:
            text: Text to split.

        Returns:
            List of sentence strings, empty strings filtered out.
        """
        if self._nlp is not None:
            try:
                doc = self._nlp(text[:5_000])
                return [sent.text.strip() for sent in doc.sents if sent.text.strip()]
            except Exception as exc:
                logger.warning("TextMatcher.split_sentences (spacy) failed: %s", exc)

        parts = re.split(r"(?<=[.!?])\s+", text)
        return [p.strip() for p in parts if p.strip()]

    def load_skills_vocabulary(self, skills: list[str]) -> None:
        """Seed the PhraseMatcher with skill/tech terms from the user's profile.

        Must be called after TextMatcher construction and before extract_entities()
        calls that need skill matching. Safe to call multiple times — replaces vocabulary.

        Under the difflib tier: no-op (logs at DEBUG level).

        Args:
            skills: List of skill/technology strings.
                    Example: ['Python', 'SQL', 'Docker', 'React', 'AWS']
        """
        if self._nlp is None:
            logger.debug(
                "TextMatcher.load_skills_vocabulary: SpaCy unavailable, no-op."
            )
            return

        if not skills:
            return

        try:
            from spacy.matcher import PhraseMatcher  # noqa: PLC0415

            self._phrase_matcher = PhraseMatcher(self._nlp.vocab, attr="LOWER")
            patterns = [self._nlp.make_doc(skill) for skill in skills]
            self._phrase_matcher.add("SKILLS", patterns)
            logger.debug(
                "TextMatcher: PhraseMatcher loaded with %d skill terms.", len(skills)
            )
        except Exception as exc:
            logger.warning("TextMatcher.load_skills_vocabulary failed: %s", exc)
            self._phrase_matcher = None

    def _match_spacy(self, text_a: str, text_b: str) -> float:
        """Compute SpaCy similarity, falling back to token overlap for sm model.

        Args:
            text_a: First text string.
            text_b: Second text string.

        Returns:
            Similarity score in [0.0, 1.0].
        """
        try:
            doc_a = self._nlp(text_a)
            doc_b = self._nlp(text_b)

            if not doc_a.has_vector or not doc_b.has_vector:
                tokens_a = {t.lower_ for t in doc_a if not t.is_stop and not t.is_punct}
                tokens_b = {t.lower_ for t in doc_b if not t.is_stop and not t.is_punct}
                if not tokens_a or not tokens_b:
                    return 0.0
                return len(tokens_a & tokens_b) / max(len(tokens_a | tokens_b), 1)

            return float(doc_a.similarity(doc_b))
        except Exception as exc:
            logger.warning("TextMatcher._match_spacy failed: %s", exc)
            return self._match_basic(text_a, text_b)

    def _match_basic(self, text_a: str, text_b: str) -> float:
        """Compute similarity using stdlib SequenceMatcher.

        Args:
            text_a: First text string.
            text_b: Second text string.

        Returns:
            Similarity score in [0.0, 1.0].
        """
        return SequenceMatcher(None, text_a.lower(), text_b.lower()).ratio()