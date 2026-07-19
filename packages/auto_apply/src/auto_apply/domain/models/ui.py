"""Defines the generic data models for UI perception and interaction planning.

This module acts as the shared language between the DOM Scanner (Perception),
the Reasoning Engine (Logic), and the Interaction Executor (Action). By decoupling
the visual representation of the page from the browser driver, we enable
pure-logic planning that is testable and robust against driver crashes.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, PrivateAttr

# We use 'Any' for element_ref to avoid circular imports with BrowserInterface,
# but in practice, this will hold an ElementInterface object.


class UIElementType(Enum):
    """Categorizes the semantic role of a UI element."""
    UNKNOWN = "unknown"
    TEXT_INPUT = "text_input"
    TEXT_AREA = "text_area"
    SELECT = "select"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    BUTTON = "button"
    LINK = "link"
    FILE_UPLOAD = "file_upload"
    STATIC_TEXT = "static_text"
    CONTAINER = "container"  # e.g., a Job Card or Form Section


class InteractionType(Enum):
    """Defines the specific action to be performed on an element."""
    CLICK = "click"
    TYPE = "type"
    SELECT_OPTION = "select_option"
    UPLOAD_FILE = "upload_file"
    HOVER = "hover"
    WAIT_FOR = "wait_for"
    VERIFY_TEXT = "verify_text"  # For auditing/validation


class UIElement(BaseModel):
    """Represents a single, interactable component discovered on a webpage.

    This class serves as a platform-agnostic wrapper around a live DOM element.
    It carries both the technical reference needed to interact with it and the
    semantic metadata needed to understand it.
    """

    id: str = Field(..., description="A unique internal hash identifying this element within the current snapshot.")  # noqa: E501

    # --- Semantic Data (The 'What') ---
    element_type: UIElementType = Field(UIElementType.UNKNOWN, description="The classified functional role of the element.")  # noqa: E501
    name: str | None = Field(None, description="The internal field name (e.g., 'first_name', 'q').")  # noqa: E501
    label: str | None = Field(None, description="The human-readable label associated with this element.")  # noqa: E501
    placeholder: str | None = Field(None, description="Placeholder text found inside the element.")  # noqa: E501

    # --- Constraints (The 'Rules') ---
    is_required: bool = Field(False, description="Whether the form requires this field to be filled.")  # noqa: E501
    is_visible: bool = Field(True, description="Whether the element is currently visible to the user.")  # noqa: E501
    options: list[str] = Field(default_factory=list, description="Available options for Select/Radio elements.")  # noqa: E501
    validation_pattern: str | None = Field(None, description="Regex pattern for input validation (if detected).")  # noqa: E501

    # --- Technical Reference (The 'Link') ---
    # We store the driver-specific element (WebElement/Locator) here privately.
    # It is excluded from serialization (JSON dumps) to prevent crashes.
    _element_ref: Any = PrivateAttr(default=None)

    def set_reference(self, element: Any) -> None:
        """Attaches the live browser element reference to this model.

        Args:
            element (Any): The ElementInterface object from the active driver.
        """
        self._element_ref = element

    def get_reference(self) -> Any:
        """Retrieves the live browser element reference.

        Returns:
            Any: The stored ElementInterface object.

        Raises:
            ValueError: If the reference has not been set or is lost.
        """
        if self._element_ref is None:
            raise ValueError(f"UIElement '{self.id}' has no live browser reference attached.")  # noqa: E501
        return self._element_ref


class UIModel(BaseModel):
    """A complete snapshot of a webpage's interactive elements."""

    url: str = Field(..., description="The URL of the scanned page.")
    title: str = Field(..., description="The page title.")
    elements: list[UIElement] = Field(default_factory=list, description="All discovered UI elements.")  # noqa: E501

    def find_element_by_id(self, element_id: str) -> UIElement | None:
        """Finds a UIElement by its ID."""
        for element in self.elements:
            if element.id == element_id:
                return element
        return None

    def get_elements_by_type(self, element_type: UIElementType) -> list[UIElement]:
        """Filters elements by type."""
        return [e for e in self.elements if e.element_type == element_type]


class PlannedAction(BaseModel):
    """A discrete instruction for the Executor to perform on a specific element.

    This represents the atomic unit of work in the 'Act' phase.
    """

    target_element_id: str = Field(..., description="The ID of the UIElement to act upon.")  # noqa: E501
    action_type: InteractionType = Field(..., description="The physical action to perform.")  # noqa: E501

    # --- Action Data ---
    value: Any | None = Field(None, description="The data to input (text, option value, file path).")  # noqa: E501

    # --- Reasoning Metadata ---
    reasoning: str = Field(..., description="Why the Solver chose this action (for debugging/auditing).")  # noqa: E501
    confidence_score: float = Field(1.0, description="0.0 to 1.0 score indicating certainty of the match.")  # noqa: E501

    # --- Execution Flags ---
    is_critical: bool = Field(True, description="If True, failure of this action aborts the plan.")  # noqa: E501
    encrypted_value: bool = Field(False, description="If True, 'value' should be treated as sensitive (masked in logs).")  # noqa: E501

    ui_element: UIElement | None = Field(None, exclude=True)

class InteractionPlan(BaseModel):
    """A comprehensive sequence of actions to achieve a high-level goal.

    The Solver produces this object after analyzing the UIModel and UserProfile.
    The Executor consumes this object to drive the browser.
    """

    goal_description: str = Field(..., description="Human-readable summary (e.g., 'Fill Application Form').")  # noqa: E501
    actions: list[PlannedAction] = Field(default_factory=list, description="The ordered sequence of steps to execute.")  # noqa: E501

    def add_action(self, action: PlannedAction) -> None:
        """Appends a new action to the plan.

        Args:
            action (PlannedAction): The configured action to append.
        """
        self.actions.append(action)

    def estimated_duration(self) -> float:
        """Estimates the execution time based on action types.

        Returns:
            float: Estimated seconds to complete the plan.
        """
        # Simple heuristic: Typing takes longer than clicking
        duration = 0.0
        for action in self.actions:
            if action.action_type == InteractionType.TYPE:
                duration += 2.0
            else:
                duration += 1.0
        return duration