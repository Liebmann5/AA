"""GPT4All local LLM adapter — zero API keys, fully offline after first model download.

This adapter satisfies TextGenerationPort for open-ended text generation tasks:
  - VettingWorkflow borderline-band reasoning ("Is this job a good fit? YES or NO.")
  - ApplicationsWorkflow custom form question answering

It does NOT implement ReasoningPort.devise_plan(). For structured UI planning,
RuleBasedFormSolver (rule_based_adapter.py) remains the injected adapter.

Install:
    pip install gpt4all

First use:
    The model (~4.7 GB) is downloaded automatically to ~/.cache/gpt4all/ on the
    first call to generate(). Subsequent calls are fully offline.

Thread safety:
    GPT4All models are NOT thread-safe. This adapter serializes all inference
    calls through a threading.Lock(). Multiple workflow threads can safely share
    one GPT4AllAdapter instance.

Graceful degradation:
    If gpt4all is not installed or the model fails to load, generate() returns
    None and logs a single WARNING. The adapter never raises. Callers (VettingWorkflow,
    ApplicationsWorkflow) have explicit fallback paths for None responses.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

try:
    from gpt4all import GPT4All as _GPT4All  # noqa: PLC0415
    _GPT4ALL_AVAILABLE = True
except ImportError:
    _GPT4All = None
    _GPT4ALL_AVAILABLE = False


class GPT4AllAdapter:
    """Local text generation adapter backed by GPT4All / llama.cpp.

    Implements TextGenerationPort (domain/ports/text_generation_port.py).
    """

    _DEFAULT_MODEL = "Meta-Llama-3-8B-Instruct.Q4_0.gguf"

    def __init__(
        self,
        model_name: str = _DEFAULT_MODEL,
        max_tokens: int = 512,
        temp: float = 0.7,
        device: str = "cpu",
    ) -> None:
        """Initialize the adapter (model is NOT loaded until first generate() call).

        Args:
            model_name: GGUF filename. Auto-downloaded to ~/.cache/gpt4all/ if absent.
            max_tokens: Default token budget for generation calls.
            temp: Sampling temperature. Lower = more deterministic.
            device: Inference device. 'cpu' always works; 'gpu' requires CUDA/Metal.
        """
        self._model_name = model_name
        self._max_tokens = max_tokens
        self._temp = temp
        self._device = device
        self._model: Any | None = None
        self._lock = threading.Lock()
        self._load_attempted = False
        self._load_succeeded = False

    def generate(self, prompt: str, max_tokens: int | None = None) -> str | None:
        """Generate a response for the given prompt.

        Thread-safe. Returns None silently if model is unavailable.

        Args:
            prompt: Full prompt string.
            max_tokens: Token budget override. Falls back to self._max_tokens.

        Returns:
            Generated string, or None on any failure.
        """
        with self._lock:
            if not self._load_attempted:
                self._load_attempted = True
                self._load_succeeded = self._ensure_model_loaded()

            if not self._load_succeeded or self._model is None:
                return None

            try:
                with self._model.chat_session():
                    return self._model.generate(
                        prompt=prompt,
                        max_tokens=max_tokens if max_tokens is not None else self._max_tokens,
                        temp=self._temp,
                    )
            except Exception as exc:
                logger.warning("GPT4All generation failed: %s", exc)
                return None

    def devise_plan(self, *args: Any, **kwargs: Any) -> None:
        """Not implemented — GPT4All is for text generation only.

        For structured UI planning, inject RuleBasedFormSolver via ReasoningPort.
        This method exists so the adapter can be stored alongside ReasoningPort
        references without causing AttributeError; it always raises to make
        misconfiguration obvious at test time, not silently at runtime.
        """
        raise NotImplementedError(
            "GPT4AllAdapter does not implement ReasoningPort.devise_plan(). "
            "Inject RuleBasedFormSolver (adapters/secondary/reasoning/rule_based_adapter.py) "
            "where ReasoningPort is required. Inject GPT4AllAdapter only where "
            "TextGenerationPort (domain/ports/text_generation_port.py) is expected."
        )

    def _ensure_model_loaded(self) -> bool:
        """Attempt to load the GPT4All model. Called once, inside the lock.

        Returns:
            True if model loaded successfully, False otherwise.
        """
        if not _GPT4ALL_AVAILABLE:
            logger.warning(
                "GPT4All is not installed. Text generation will be unavailable. "
                "Install with: pip install gpt4all"
            )
            return False

        try:
            self._model = _GPT4All(
                model_name=self._model_name,
                device=self._device,
                verbose=False,
            )
            logger.info(
                "GPT4AllAdapter: model loaded (%s, device=%s)",
                self._model_name,
                self._device,
            )
            return True
        except Exception as exc:
            logger.warning(
                "GPT4AllAdapter: failed to load model '%s': %s. "
                "Text generation will be unavailable.",
                self._model_name,
                exc,
            )
            return False