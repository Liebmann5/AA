"""Defines the contract for reading and classifying page state."""

from abc import ABC, abstractmethod

from auto_apply.domain.applications.fsm.states import ApplicationState
from auto_apply.domain.models.ui import UIModel


class PerceptionPort(ABC):
    """Abstract interface for observing the current state of a web page.

    Implementations live in ``adapters/secondary/interaction/`` and translate
    raw DOM/accessibility trees into the domain's own data structures.
    """

    @abstractmethod
    def navigate(self, url: str) -> None:
        """Navigates the browser to the given URL and waits for the page to load.

        Must be called before :meth:`scan_page` when moving to a new page.
        The adapter is responsible for any post-load waiting logic.

        Args:
            url: The fully qualified URL to navigate to.
        """

    @abstractmethod
    def scan_page(self) -> UIModel:
        """Returns a full snapshot of the current page's interactive elements.

        Returns:
            A :class:`~auto_apply.domain.models.ui.UIModel` describing every
            interactable element found on the current page.
        """

    @abstractmethod
    def get_current_state(self) -> ApplicationState:
        """Classifies the current page into an :class:`ApplicationState` value.

        Used by FSM strategies to decide which action to take next. The
        adapter is responsible for heuristic analysis (ARIA roles, button
        text, DOM structure) and mapping the result to the domain enum.

        Returns:
            The detected :class:`~auto_apply.domain.applications.fsm.states.ApplicationState`
            for the current UI context.
        """  # noqa: E501

    @abstractmethod
    def get_page_text(self) -> str:
        """Returns the visible text content of the current page.

        This is the canonical text-extraction path used by vetting NLP. It must
        work identically for live-browser and zero-browser perception modes:
        implementations read whatever the current page state is (after
        :meth:`navigate`) and return its human-visible text, with script/style
        content excluded.

        Returns:
            The page's visible text, or an empty string when no page has been
            loaded or text cannot be extracted. Never raises.
        """
