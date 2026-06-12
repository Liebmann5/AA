"""Defines the data model for negotiated system resources.

This object represents the 'Strategy' decided by the Resource Manager.
It tells the rest of the application exactly what tools are available
and safe to use for this specific session.
"""

from typing import Literal

from pydantic import BaseModel, Field


class RuntimeProfile(BaseModel):
    """A blueprint for the resources allocated to a session."""

    # --- Browser Strategy ---
    browser_framework: Literal["selenium", "playwright", "unresolved"] = Field(
        "unresolved", description="The underlying engine to use; resolved by BrowserCascade."
    )
    browser_name: str = Field(
        ..., description="The specific browser executable (e.g., 'chrome', 'firefox')."
    )
    headless: bool = Field(
        True, description="Whether to run without a GUI."
    )
    use_stealth: bool = Field(
        True, description="Whether to apply anti-bot evasion patches."
    )

    # NEW: Explicit flag for using 'undetected-chromedriver' vs standard
    use_stealth_driver: bool = Field(
        False, description="Use specialized stealth binary if available."
    )

    # --- Performance Strategy ---
    max_concurrency: int = Field(
        1, description="How many parallel tasks (tabs/browsers) are safe to run."
    )

    # --- Intelligence Strategy ---
    ai_enabled: bool = Field(
        False, description="Whether local AI models (Torch/LLM) are allowed."
    )
    nlp_engine: Literal["basic", "spacy", "transformer"] = Field(
        "basic", description="The text matching engine to use (basic/spacy/transformer)."  # noqa: E501
    )

    # --- Future Extensibility ---
    # use_gpu: bool = False
    # enable_network_interception: bool = False
