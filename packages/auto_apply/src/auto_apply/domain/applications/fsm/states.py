"""Defines the states and context for application workflows.

This module provides the shared enumerations and data structures used by the
Finite State Machine (FSM) strategies to navigate complex job applications.
"""

from dataclasses import dataclass, field
from enum import Enum, auto


class ApplicationState(Enum):
    """Represents the current phase of a job application workflow."""

    UNKNOWN = auto()

    # Pre-Application
    INITIAL_START = auto()           # "Apply" / "Easy Apply" button visible
    LOGIN_WALL = auto()              # Forced login required

    # Active Application
    FORM_STEP = auto()               # Active inputs present (general)
    UPLOAD_STEP = auto()             # Specific step asking for Resume/CV
    REVIEW_STEP = auto()             # "Review your application" screen
    MODAL_OPEN = auto()              # A modal/dialog is blocking the form

    # Redirect / Navigation
    REDIRECT_TO_CAREERS_PAGE = auto()  # Landed on a company careers listing page
    REDIRECT_TO_LIST = auto()          # Multiple job cards visible; not a single form
    INDEED_TAB_SWITCHED = auto()       # Indeed: job-list tab is active instead of form

    # Processing
    SUBMITTING = auto()              # Spinner / loading state

    # Human-in-the-loop
    AWAITING_HUMAN = auto()          # Paused; waiting for human approval or input

    # Terminal States
    SUCCESS = auto()                 # "Application sent" / confetti
    ERROR = auto()                   # Validation errors visible
    ALREADY_APPLIED = auto()         # "You applied on..." text
    CLOSED = auto()                  # "No longer accepting applications"
    CRITICAL_FAILURE = auto()        # Unrecoverable technical error


# Valid outgoing transitions for each state.
# Used by FSM strategies to validate state progression and by the
# orchestrator to detect stuck / illegal transitions.
VALID_APPLICATION_TRANSITIONS: dict[ApplicationState, frozenset[ApplicationState]] = {
    ApplicationState.UNKNOWN: frozenset({
        ApplicationState.UNKNOWN,
        ApplicationState.INITIAL_START,
        ApplicationState.FORM_STEP,
        ApplicationState.LOGIN_WALL,
        ApplicationState.REDIRECT_TO_LIST,
        ApplicationState.REDIRECT_TO_CAREERS_PAGE,
    }),
    ApplicationState.INITIAL_START: frozenset({
        ApplicationState.FORM_STEP,
        ApplicationState.UPLOAD_STEP,
        ApplicationState.REVIEW_STEP,
        ApplicationState.LOGIN_WALL,
        ApplicationState.MODAL_OPEN,
        ApplicationState.REDIRECT_TO_LIST,
        ApplicationState.REDIRECT_TO_CAREERS_PAGE,
        ApplicationState.INDEED_TAB_SWITCHED,
    }),
    ApplicationState.FORM_STEP: frozenset({
        ApplicationState.FORM_STEP,
        ApplicationState.UPLOAD_STEP,
        ApplicationState.REVIEW_STEP,
        ApplicationState.SUBMITTING,
        ApplicationState.ERROR,
        ApplicationState.MODAL_OPEN,
        ApplicationState.REDIRECT_TO_LIST,
        ApplicationState.AWAITING_HUMAN,
    }),
    ApplicationState.UPLOAD_STEP: frozenset({
        ApplicationState.FORM_STEP,
        ApplicationState.REVIEW_STEP,
        ApplicationState.SUBMITTING,
        ApplicationState.ERROR,
        ApplicationState.MODAL_OPEN,
    }),
    ApplicationState.REVIEW_STEP: frozenset({
        ApplicationState.SUBMITTING,
        ApplicationState.FORM_STEP,
        ApplicationState.ERROR,
        ApplicationState.AWAITING_HUMAN,
    }),
    ApplicationState.SUBMITTING: frozenset({
        ApplicationState.SUCCESS,
        ApplicationState.ERROR,
        ApplicationState.FORM_STEP,
    }),
    ApplicationState.MODAL_OPEN: frozenset({
        ApplicationState.FORM_STEP,
        ApplicationState.REVIEW_STEP,
        ApplicationState.UPLOAD_STEP,
        ApplicationState.INITIAL_START,
    }),
    ApplicationState.ERROR: frozenset({
        ApplicationState.FORM_STEP,
        ApplicationState.UPLOAD_STEP,
        ApplicationState.REVIEW_STEP,
        ApplicationState.CRITICAL_FAILURE,
    }),
    ApplicationState.LOGIN_WALL: frozenset({
        ApplicationState.FORM_STEP,
        ApplicationState.INITIAL_START,
    }),
    ApplicationState.INDEED_TAB_SWITCHED: frozenset({
        ApplicationState.INITIAL_START,
        ApplicationState.FORM_STEP,
        ApplicationState.REDIRECT_TO_LIST,
    }),
    ApplicationState.AWAITING_HUMAN: frozenset({
        ApplicationState.FORM_STEP,
        ApplicationState.REVIEW_STEP,
        ApplicationState.CRITICAL_FAILURE,
    }),
    # Terminal / redirect states have no valid outgoing transitions.
    ApplicationState.SUCCESS: frozenset(),
    ApplicationState.CLOSED: frozenset(),
    ApplicationState.ALREADY_APPLIED: frozenset(),
    ApplicationState.REDIRECT_TO_LIST: frozenset(),
    ApplicationState.REDIRECT_TO_CAREERS_PAGE: frozenset(),
    ApplicationState.CRITICAL_FAILURE: frozenset(),
}


@dataclass
class WorkflowContext:
    """Tracks the progress of a specific application attempt."""

    steps_taken: int = 0
    fields_filled: int = 0
    errors_encountered: list[str] = field(default_factory=list)
    max_steps: int = 25  # Safety circuit breaker
