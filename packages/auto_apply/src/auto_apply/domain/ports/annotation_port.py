"""Ports for human labelling (item 5).

Three contracts keep the labelling tool layered like the rest of AA:

* AnnotationStorePort — where labels (and items a person creates, such as
  a logged application) are kept. Implemented by the append-only JSONL store.
* ItemSourcePort — where items to label come from for one study (saved
  detector pages today; captured postings or log lines later).
* LabellingPort — what a surface (CLI now, GUI later) drives: pick a study,
  get the next item, record answers, see the reveal and the insights. The
  surfaces depend on this port only, never on the service behind it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from auto_apply.domain.models.annotation import AnswerValue, Annotation, Item, Study

__all__ = [
    "AnnotationStorePort",
    "ItemSourcePort",
    "LabellingPort",
    "StudyProgress",
]


@runtime_checkable
class AnnotationStorePort(Protocol):
    """Append-only storage for annotations and person-created items."""

    def append(self, annotation: Annotation) -> None:
        """Record one annotation. Never rewrites earlier records."""
        ...

    def annotations(self, study_id: str) -> list[Annotation]:
        """Every annotation recorded for a study, oldest first."""
        ...

    def add_item(self, item: Item) -> None:
        """Record an item a person created (e.g. a logged application)."""
        ...

    def items(self, study_id: str) -> list[Item]:
        """Person-created items for a study, oldest first, latest per id."""
        ...


@runtime_checkable
class ItemSourcePort(Protocol):
    """Items to label for one study, from somewhere AA already saved them."""

    @property
    def study_id(self) -> str: ...

    def items(self) -> list[Item]:
        """Every item available to label, in a stable order."""
        ...

    def prepare_view(self, item: Item) -> Path | None:
        """A local file that is safe to open for viewing the item, or None."""
        ...


@dataclass(frozen=True)
class StudyProgress:
    """Where a person stands in one study."""

    study: Study
    total: int  # items available (open-ended studies: items logged)
    done: int  # items with a current, non-skipped label
    skipped: int  # items whose latest record is a skip
    open_ended: bool  # the person adds items (an audit) rather than works a queue


@runtime_checkable
class LabellingPort(Protocol):
    """What a labelling surface drives."""

    def progress(self) -> tuple[StudyProgress, ...]: ...

    def next_item(self, study_id: str) -> Item | None:
        """The next item without a current label, or None when all are done."""
        ...

    def log_item(self, study_id: str, url: str, title: str) -> Item:
        """Create an item in an open-ended study (a logged application)."""
        ...

    def view_path(self, item: Item) -> Path | None: ...

    def record(
        self, item: Item, answers: dict[str, AnswerValue], seconds: float
    ) -> list[str]:
        """Validate and store answers. Returns problems; empty means stored."""
        ...

    def skip(self, item: Item) -> None: ...

    def reveal(self, item: Item, answers: dict[str, AnswerValue]) -> tuple[str, ...]:
        """What AA concluded about the item, set against the person's answer.
        Only ever called after the answers are stored (blind labelling)."""
        ...

    def insights(self, study_id: str) -> tuple[str, ...]: ...
