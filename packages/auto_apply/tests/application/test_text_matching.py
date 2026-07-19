"""Tests for TextMatcher hardware‑aware model selection."""

from unittest.mock import patch, MagicMock

import pytest

from auto_apply.application.services.text_matching import TextMatcher


@pytest.fixture
def mock_spacy_load():
    """Mock spaCy.load to simulate model availability."""
    with patch("auto_apply.application.services.text_matching._spacy", create=True) as mock_spacy:
        mock_spacy.load = MagicMock()
        yield mock_spacy


def set_mock_spacy(mock_spacy, available_models: set[str]):
    """Configure mock_spacy.load to raise OSError unless model is in available_models."""
    def _load(name):
        if name in available_models:
            return MagicMock()
        raise OSError(f"Model '{name}' not found.")
    mock_spacy.load.side_effect = _load


class TestPreferSmallModelSelection:

    def test_prefer_small_true_selects_sm_model(self, mock_spacy_load):
        """When prefer_small is True and all models are present, the first tried is sm."""
        set_mock_spacy(mock_spacy_load, {"en_core_web_sm", "en_core_web_md", "en_core_web_lg"})
        matcher = TextMatcher(prefer_small=True)
        # The engine type should indicate the smallest available model was loaded.
        # In this case sm is available first, so it should be "spacy_sm".
        assert matcher._engine_type == "spacy_sm"

    def test_prefer_small_true_falls_back_to_md_if_sm_unavailable(self, mock_spacy_load):
        """When sm is missing, the engine should load md."""
        set_mock_spacy(mock_spacy_load, {"en_core_web_md", "en_core_web_lg"})
        matcher = TextMatcher(prefer_small=True)
        assert matcher._engine_type == "spacy_md"

    def test_prefer_small_true_falls_back_to_lg_if_sm_md_unavailable(self, mock_spacy_load):
        """When only lg is available, it should load lg."""
        set_mock_spacy(mock_spacy_load, {"en_core_web_lg"})
        matcher = TextMatcher(prefer_small=True)
        assert matcher._engine_type == "spacy_lg"

    def test_prefer_small_true_falls_back_to_basic_if_nothing_available(self, mock_spacy_load):
        """When no spaCy model can be loaded, the engine defaults to 'basic'."""
        set_mock_spacy(mock_spacy_load, set())
        matcher = TextMatcher(prefer_small=True)
        assert matcher._engine_type == "basic"


class TestDefaultModelSelection:

    def test_default_prefer_large_model(self, mock_spacy_load):
        """With prefer_small=False (default), lg is tried first."""
        set_mock_spacy(mock_spacy_load, {"en_core_web_lg", "en_core_web_md", "en_core_web_sm"})
        matcher = TextMatcher()  # prefer_small defaults to False
        assert matcher._engine_type == "spacy_lg"

    def test_default_falls_back_to_md_if_lg_unavailable(self, mock_spacy_load):
        """When lg is missing, md is selected."""
        set_mock_spacy(mock_spacy_load, {"en_core_web_md", "en_core_web_sm"})
        matcher = TextMatcher()
        assert matcher._engine_type == "spacy_md"

    def test_default_falls_back_to_sm_if_lg_md_unavailable(self, mock_spacy_load):
        """When only sm is available, it is used."""
        set_mock_spacy(mock_spacy_load, {"en_core_web_sm"})
        matcher = TextMatcher()
        assert matcher._engine_type == "spacy_sm"