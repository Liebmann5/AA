"""Makes the 'auto_apply' package executable.

This file serves as the entry point when the package is run directly
using the '-m' flag: python -m auto_apply

The sys.path insertion ensures that 'auto_apply' is importable as a
top-level package regardless of the current working directory. This is
a safety net — in development, 'pip install -e .' achieves the same
thing, but USB-portable users may not have run pip.
"""

import sys
from pathlib import Path

# Ensure the 'src/' directory is on Python's import path so that
# 'from auto_apply.core...' works from any working directory.
# This line is idempotent — adding a path that's already present is harmless.
_src_dir = str(Path(__file__).resolve().parent.parent)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from auto_apply.main import main  # noqa: E402

if __name__ == "__main__":
    main()
