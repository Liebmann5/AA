"""Delete-scope arithmetic for the uninstaller — the safety core.

Every deletion the uninstaller performs passes through require_deletable()
immediately before the delete — never at plan time only: the check and the
act are adjacent so a path swapped between scan and delete is re-judged at
the moment it matters. Containment is computed on FULLY RESOLVED paths;
the delete itself removes links, never their targets.

The filesystem-touching primitive (realpath) is injected, so the arithmetic
is testable without touching a disk — sans-IO where it matters most.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

RealPath = Callable[[str], str]


class OutOfScopeError(RuntimeError):
    """A path slated for deletion is not inside any root AA may delete."""


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def is_within(path: Path, root: Path, *, realpath: RealPath = os.path.realpath) -> bool:
    """True when path's FULLY RESOLVED location is root itself or beneath it."""
    resolved = _norm(realpath(str(path)))
    base = _norm(realpath(str(root)))
    return resolved == base or resolved.startswith(base + os.sep)


def require_deletable(
    path: Path, roots: tuple[Path, ...], *, realpath: RealPath = os.path.realpath
) -> Path:
    """Return the resolved path, or raise OutOfScopeError.

    Called immediately before every single delete.
    """
    if any(is_within(path, root, realpath=realpath) for root in roots):
        return Path(realpath(str(path)))
    raise OutOfScopeError(
        f"refusing to delete {path} — it resolves outside every permitted root "
        f"({', '.join(str(r) for r in roots)})"
    )


def is_link(path: Path) -> bool:
    """True for symlinks and (3.12+) junctions: delete the link, never follow."""
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or bool(is_junction is not None and is_junction())
