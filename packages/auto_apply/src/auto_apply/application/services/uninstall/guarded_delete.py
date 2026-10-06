"""Guarded recursive deletion — the only delete the uninstaller performs."""
from __future__ import annotations

import os
from pathlib import Path

from auto_apply.application.services.uninstall.scoping import (
    is_link,
    require_deletable,
)


def guarded_remove(
    path: Path, roots: tuple[Path, ...], *, realpath=os.path.realpath
) -> None:
    """Remove a file, link, or tree.

    Every non-link entry is re-checked with require_deletable immediately
    before its own delete, so a swap between the plan's scan and this walk
    is re-judged at the moment it matters. A LINK is different: its own
    location is its parent's resolved path plus its name, so the parent is
    what gets checked — the target is never consulted and never followed
    (D4: resolving the link itself refused the delete of a perfectly
    in-scope link, and the report then lied about a failure). Missing paths
    are not an error: that is what makes an interrupted run resumable.
    """
    if is_link(path):
        require_deletable(path.parent, roots, realpath=realpath)
        path.unlink(missing_ok=True)
        return
    require_deletable(path, roots, realpath=realpath)
    if not path.exists():
        return
    if not path.is_dir():
        path.unlink(missing_ok=True)
        return
    for child in sorted(path.iterdir()):
        guarded_remove(child, roots, realpath=realpath)
    try:
        path.rmdir()
    except FileNotFoundError:
        pass
