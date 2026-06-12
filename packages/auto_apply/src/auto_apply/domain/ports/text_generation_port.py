"""Port defining the contract for open-ended local text generation.

Separated from ReasoningPort because:
- ReasoningPort.devise_plan() returns a structured InteractionPlan for UI automation.
- TextGenerationPort.generate() returns a raw string for human-readable answers.

These are fundamentally different contracts. GPT4AllAdapter satisfies
TextGenerationPort; it raises NotImplementedError on devise_plan() — it is only
injected where TextGenerationPort is expected.

Concrete implementation: adapters/secondary/reasoning/gpt4all_adapter.py
Fallback: pass None — all consumers of this port check for None before calling.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class TextGenerationPort(Protocol):
    """Contract for a local, offline, zero-API-key text generation model."""

    def generate(
        self,
        prompt: str,
        max_tokens: int | None = None,
    ) -> str | None:
        """Generate a text response for the given prompt.

        Args:
            prompt: The full prompt string to send to the model.
            max_tokens: Optional token budget override. Uses adapter default if None.

        Returns:
            Generated text string, or None if the model is unavailable or fails.
            Never raises — callers must handle None explicitly.
        """
        ...
