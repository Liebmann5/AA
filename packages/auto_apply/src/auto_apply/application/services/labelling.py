"""LabellingService — the labelling tool's behaviour, for any surface (item 5).

Implements LabellingPort over an AnnotationStorePort and one ItemSourcePort
per queue-style study. Studies without a source are open-ended: the person
adds the items themselves (the paired audit's logged applications).

Labelling is blind: next_item() hands a surface the item's display fields
only, and reveal() — what AA concluded — is meant to be called after
record() has stored the answer. The CLI does exactly that; a GUI must too.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from auto_apply.domain.models.annotation import (
    Annotation,
    AnswerValue,
    Item,
    Study,
    answers_problems,
)
from auto_apply.domain.ports.annotation_port import (
    AnnotationStorePort,
    ItemSourcePort,
    StudyProgress,
)
from auto_apply.domain.services.annotation_analysis import (
    current_labels,
    insight_lines,
    reveal_lines,
)

__all__ = ["LabellingService"]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class LabellingService:
    """Drives labelling for every study AA ships."""

    def __init__(
        self,
        studies: tuple[Study, ...],
        store: AnnotationStorePort,
        sources: tuple[ItemSourcePort, ...] = (),
        annotator: str = "me",
        clock: Callable[[], str] = _utc_now,
    ) -> None:
        self._studies = {s.id: s for s in studies}
        self._order = tuple(s.id for s in studies)
        self._store = store
        self._sources = {s.study_id: s for s in sources}
        self._annotator = annotator
        self._clock = clock

    # ── reading ─────────────────────────────────────────────────────────

    def study(self, study_id: str) -> Study:
        return self._studies[study_id]

    def _items(self, study_id: str) -> list[Item]:
        source = self._sources.get(study_id)
        if source is not None:
            return source.items()
        return self._store.items(study_id)

    def _mine(self, study: Study) -> dict[str, Annotation]:
        return current_labels(
            study,
            (
                a
                for a in self._store.annotations(study.id)
                if a.annotator == self._annotator
            ),
        )

    def progress(self) -> tuple[StudyProgress, ...]:
        out = []
        for study_id in self._order:
            study = self._studies[study_id]
            items = self._items(study_id)
            ids = {i.item_id for i in items}
            labels = {k: v for k, v in self._mine(study).items() if k in ids}
            out.append(
                StudyProgress(
                    study=study,
                    total=len(items),
                    done=sum(1 for a in labels.values() if not a.skipped),
                    skipped=sum(1 for a in labels.values() if a.skipped),
                    open_ended=study_id not in self._sources,
                )
            )
        return tuple(out)

    def next_item(self, study_id: str) -> Item | None:
        """Unlabelled items first, in source order; then skipped ones, so a
        skip means 'later', not 'never'."""
        study = self._studies[study_id]
        labels = self._mine(study)
        items = self._items(study_id)
        for item in items:
            if item.item_id not in labels:
                return item
        for item in items:
            label = labels.get(item.item_id)
            if label is not None and label.skipped:
                return item
        return None

    def view_path(self, item: Item) -> Path | None:
        source = self._sources.get(item.study_id)
        return source.prepare_view(item) if source is not None else None

    # ── writing ─────────────────────────────────────────────────────────

    def log_item(self, study_id: str, url: str, title: str) -> Item:
        """A person-created item. Its id is a digest of the URL, so logging
        the same posting twice revises one item instead of making two."""
        url = url.strip()
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        display = tuple(
            (k, v) for k, v in (("title", title.strip()), ("url", url)) if v
        )
        item = Item(
            study_id=study_id,
            item_id=digest,
            title=title.strip() or url or "untitled",
            display=display,
        )
        self._store.add_item(item)
        return item

    def record(
        self, item: Item, answers: dict[str, AnswerValue], seconds: float
    ) -> list[str]:
        study = self._studies[item.study_id]
        problems = answers_problems(study, answers)
        if problems:
            return problems
        self._store.append(
            Annotation(
                study_id=study.id,
                study_version=study.version,
                item_id=item.item_id,
                annotator=self._annotator,
                answers=tuple(sorted(answers.items())),
                recorded_at=self._clock(),
                seconds_spent=round(max(seconds, 0.0), 1),
            )
        )
        return []

    def skip(self, item: Item) -> None:
        study = self._studies[item.study_id]
        self._store.append(
            Annotation(
                study_id=study.id,
                study_version=study.version,
                item_id=item.item_id,
                annotator=self._annotator,
                answers=(),
                recorded_at=self._clock(),
                skipped=True,
            )
        )

    # ── what it means ───────────────────────────────────────────────────

    def reveal(self, item: Item, answers: dict[str, AnswerValue]) -> tuple[str, ...]:
        return reveal_lines(self._studies[item.study_id], item, answers)

    def insights(self, study_id: str) -> tuple[str, ...]:
        study = self._studies[study_id]
        mine = [
            a
            for a in self._store.annotations(study_id)
            if a.annotator == self._annotator
        ]
        return insight_lines(study, self._items(study_id), mine)
