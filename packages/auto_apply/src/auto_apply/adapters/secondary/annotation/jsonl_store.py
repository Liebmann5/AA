"""JsonlAnnotationStore — labels as append-only JSON Lines, one file per study.

Why JSON Lines: a label set is small, precious and long-lived. One record
per line is readable in any editor, diffs cleanly, survives a crash mid-run
(at worst the last line is cut, and a cut line is skipped and counted on
read rather than failing the file), and is never rewritten — a revised
answer is a new line, so the history of every judgement is kept.

Bytes are written exactly: UTF-8, "\\n" line endings on every platform,
keys sorted, so the same labels produce the same file anywhere.

Files, under the root (USER_DATA_DIR/annotations in production):
    <study>.labels.jsonl   every Annotation, in the order recorded
    <study>.items.jsonl    items a person created (logged applications)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from auto_apply.domain.models.annotation import AnswerValue, Annotation, Item

logger = logging.getLogger(__name__)

__all__ = ["JsonlAnnotationStore"]


def _answer_out(value: AnswerValue) -> Any:
    return list(value) if isinstance(value, tuple) else value


def _answer_in(value: Any) -> AnswerValue:
    if isinstance(value, list):
        return tuple(str(v) for v in value)
    if isinstance(value, bool):
        raise ValueError("boolean is not an answer")
    if isinstance(value, (int, float)):
        return float(value)
    return str(value)


class JsonlAnnotationStore:
    """AnnotationStorePort over JSON Lines files."""

    def __init__(self, root: Path) -> None:
        self._root = root
        #: Lines that could not be read on the last load, per file name.
        self.unreadable: dict[str, int] = {}

    def _path(self, study_id: str, kind: str) -> Path:
        return self._root / f"{study_id}.{kind}.jsonl"

    def _append(self, path: Path, record: dict[str, Any]) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n"
        with path.open("ab") as fh:
            fh.write(line.encode("utf-8"))

    def _read(self, path: Path) -> list[dict[str, Any]]:
        if not path.is_file():
            return []
        records: list[dict[str, Any]] = []
        bad = 0
        for raw in path.read_bytes().split(b"\n"):
            if not raw.strip():
                continue
            try:
                record = json.loads(raw.decode("utf-8"))
                if not isinstance(record, dict):
                    raise ValueError("not an object")
                records.append(record)
            except (ValueError, UnicodeDecodeError):
                bad += 1
        if bad:
            self.unreadable[path.name] = bad
            logger.warning(
                "JsonlAnnotationStore: %d unreadable line(s) in %s were skipped",
                bad,
                path.name,
            )
        return records

    # ── annotations ─────────────────────────────────────────────────────

    def append(self, annotation: Annotation) -> None:
        self._append(
            self._path(annotation.study_id, "labels"),
            {
                "study": annotation.study_id,
                "version": annotation.study_version,
                "item": annotation.item_id,
                "annotator": annotation.annotator,
                "answers": {k: _answer_out(v) for k, v in annotation.answers},
                "recorded_at": annotation.recorded_at,
                "seconds": annotation.seconds_spent,
                "skipped": annotation.skipped,
                "notes": dict(annotation.notes),
            },
        )

    def annotations(self, study_id: str) -> list[Annotation]:
        out: list[Annotation] = []
        for r in self._read(self._path(study_id, "labels")):
            try:
                out.append(
                    Annotation(
                        study_id=str(r["study"]),
                        study_version=int(r["version"]),
                        item_id=str(r["item"]),
                        annotator=str(r["annotator"]),
                        answers=tuple(
                            sorted(
                                (str(k), _answer_in(v)) for k, v in r["answers"].items()
                            )
                        ),
                        recorded_at=str(r["recorded_at"]),
                        seconds_spent=float(r.get("seconds", 0.0)),
                        skipped=bool(r.get("skipped", False)),
                        notes={str(k): str(v) for k, v in r.get("notes", {}).items()},
                    )
                )
            except (KeyError, TypeError, ValueError, AttributeError):
                name = self._path(study_id, "labels").name
                self.unreadable[name] = self.unreadable.get(name, 0) + 1
        return out

    # ── person-created items ────────────────────────────────────────────

    def add_item(self, item: Item) -> None:
        self._append(
            self._path(item.study_id, "items"),
            {
                "study": item.study_id,
                "item": item.item_id,
                "title": item.title,
                "display": [list(pair) for pair in item.display],
            },
        )

    def items(self, study_id: str) -> list[Item]:
        latest: dict[str, Item] = {}
        for r in self._read(self._path(study_id, "items")):
            try:
                item = Item(
                    study_id=str(r["study"]),
                    item_id=str(r["item"]),
                    title=str(r["title"]),
                    display=tuple((str(k), str(v)) for k, v in r.get("display", [])),
                )
            except (KeyError, TypeError, ValueError):
                continue
            latest.pop(item.item_id, None)  # re-logged: moves to its newest place
            latest[item.item_id] = item
        return list(latest.values())
