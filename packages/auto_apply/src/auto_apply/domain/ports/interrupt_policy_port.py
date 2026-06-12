"""Port for human-in-the-loop interrupt policy decisions.

The InterruptPolicy Protocol answers one question: "Should the agent pause
here and ask the user before proceeding?"  Concrete implementations can range
from "always pause" (for careful users) to "never pause" (for fully autonomous
runs) to profile-driven policies that read user-configured checkpoints.

The Checkpoint enum defines every point in the application pipeline where a
pause could be inserted.  Each Checkpoint maps to a user-facing question and
a set of standard options.

Design notes:
    - The policy is stateless — it receives full context and returns a bool.
    - InterruptPolicy is never called from domain/ directly; the engine
      (ApplicationEngine) receives it via constructor injection.
    - ProfileBasedInterruptPolicy is the default concrete implementation and
      lives here because it depends only on stdlib and domain models.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from auto_apply.domain.models.job import Job

logger = logging.getLogger(__name__)


class Checkpoint(Enum):
    """Every point in the pipeline where a HITL pause can be inserted."""

    AFTER_VETTING = auto()
    """Job passed all filters; agent is about to open the application form."""

    BEFORE_FORM_SUBMIT = auto()
    """Agent has filled the form and is about to click Submit."""

    ON_AMBIGUOUS_SUBMISSION = auto()
    """The page after submit does not clearly show success or failure."""

    ON_SUSPICIOUS_REDIRECT = auto()
    """The form navigated to an unexpected URL mid-session."""

    ON_LOW_CONFIDENCE_FIELD = auto()
    """A form field could not be mapped to the profile with high confidence."""


@dataclass(frozen=True)
class ApplicationContext:
    """Snapshot of the current application context at the moment of a checkpoint.

    Passed to InterruptPolicy.should_pause() so the policy can make an
    informed decision without coupling to the engine internals.

    Attributes:
        checkpoint: Which checkpoint triggered the evaluation.
        job_title: The job title being applied to (may be empty string).
        company: The company being applied to (may be empty string).
        url: The current page URL.
        field_label: Relevant form field label (for ON_LOW_CONFIDENCE_FIELD).
        confidence: Confidence score [0..1] for the field mapping (or None).
    """
    checkpoint: Checkpoint
    job_title: str = ""
    company: str = ""
    url: str = ""
    field_label: str = ""
    confidence: float | None = None


@runtime_checkable
class InterruptPolicy(Protocol):
    """Decides whether the agent should pause at a given checkpoint.

    Args:
        checkpoint: The Checkpoint enum value being evaluated.
        ctx: The current ApplicationContext snapshot.

    Returns:
        True → agent must pause and emit HUMAN_APPROVAL_REQUESTED.
        False → agent continues without pausing.
    """

    def should_pause(self, checkpoint: Checkpoint, ctx: ApplicationContext) -> bool:
        ...


class ProfileBasedInterruptPolicy:
    """Reads the user's configured checkpoints list from their profile.

    Constructs from ``app_config.human_review_checkpoints``, which is a
    ``list[str]`` of Checkpoint names (e.g. ``["BEFORE_FORM_SUBMIT"]``).

    Falls back to the DEFAULT_CHECKPOINTS set when the profile field is
    absent or empty.

    Args:
        configured_checkpoints: List of Checkpoint name strings from the
            user's ApplicationConfig.  Pass ``None`` to use the default set.
    """

    DEFAULT_CHECKPOINTS: frozenset[Checkpoint] = frozenset({
        Checkpoint.BEFORE_FORM_SUBMIT,
        Checkpoint.ON_SUSPICIOUS_REDIRECT,
    })

    def __init__(self, configured_checkpoints: list[str] | None = None) -> None:
        if configured_checkpoints:
            parsed: set[Checkpoint] = set()
            for name in configured_checkpoints:
                try:
                    parsed.add(Checkpoint[name.upper()])
                except KeyError:
                    logger.warning(
                        "ProfileBasedInterruptPolicy: unknown checkpoint %r — ignored",
                        name,
                    )
            self._active = frozenset(parsed) if parsed else self.DEFAULT_CHECKPOINTS
        else:
            self._active = self.DEFAULT_CHECKPOINTS

        logger.debug(
            "ProfileBasedInterruptPolicy: active checkpoints=%s",
            [c.name for c in self._active],
        )

    def should_pause(self, checkpoint: Checkpoint, ctx: ApplicationContext) -> bool:
        """Returns True if *checkpoint* is in the active set."""
        return checkpoint in self._active


class NeverInterruptPolicy:
    """Never pauses — fully autonomous operation.

    Useful for headless/scheduled runs where no human is available to respond.
    """

    def should_pause(self, checkpoint: Checkpoint, ctx: ApplicationContext) -> bool:
        return False


class AlwaysInterruptPolicy:
    """Pauses at every checkpoint — maximum human oversight."""

    def should_pause(self, checkpoint: Checkpoint, ctx: ApplicationContext) -> bool:
        return True
