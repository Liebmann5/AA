"""Provides utilities for atomic file operations.

This module ensures data integrity during hardware failures (power loss, crashes).
It implements the 'Write-Replace' pattern to prevent file corruption.
"""

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

def atomic_write_json(file_path: Path, data: Any) -> None:
    """Writes a dictionary to a JSON file atomically.

    This function writes data to a temporary file first, ensuring the disk write
    is complete and valid. Only then does it replace the target file.

    If the power fails during write, the original file remains untouched.
    If the power fails during replace, the OS guarantees the operation completes
    or rolls back (mostly atomic on modern filesystems).

    Args:
        file_path (Path): The final destination path.
        data (Any): The JSON-serializable data to write.
    """
    # Ensure parent dir exists
    file_path.parent.mkdir(parents=True, exist_ok=True)

    # Create a temp file in the same directory (crucial for atomic rename across filesystems)  # noqa: E501
    # We use delete=False because we want to rename it, not have it auto-deleted
    tmp_fd, tmp_path = tempfile.mkstemp(dir=file_path.parent, suffix=".tmp")

    try:
        with os.fdopen(tmp_fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno()) # Force write to physical disk platter/SSD

        # The Atomic Swap
        os.replace(tmp_path, file_path)

    except Exception as e:
        logger.error(f"Atomic write failed for {file_path}: {e}")
        # Cleanup the garbage temp file
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise