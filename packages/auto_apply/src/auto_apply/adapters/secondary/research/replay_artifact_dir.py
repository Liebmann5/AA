"""ReplayArtifactDir — a replay's files written to one folder, byte for byte.

Bytes in, bytes out: no text mode, so no newline translation on Windows
(the defect that makes a "deterministic" file differ between operating
systems). Each file is written to ``<name>.partial`` and then renamed, so
a crash never leaves a half-written artifact under its real name.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

__all__ = ["ReplayArtifactDir"]


class ReplayArtifactDir:
    """ReplayArtifactSinkPort over one folder."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def write(self, files: Mapping[str, bytes]) -> str:
        self._directory.mkdir(parents=True, exist_ok=True)
        for name in sorted(files):
            if "/" in name or "\\" in name or name in ("", ".", ".."):
                raise ValueError(f"not a plain file name: {name!r}")
            target = self._directory / name
            partial = target.with_name(name + ".partial")
            partial.write_bytes(files[name])
            partial.replace(target)
        return str(self._directory)
