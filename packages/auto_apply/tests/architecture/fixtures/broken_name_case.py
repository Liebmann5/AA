"""Regression fixture for the BROKEN INTERNAL NAME check (R-D, Batch 1).

Reconstructs the exact shape of telemetry.py, deleted 2026-08-30: a
top-level from-import of a name that does not exist in the target module.
The second import is real and must NOT be flagged — it guards the check
against false positives.

THIS FILE IS DATA. It must never be imported by the suite; the name check
reads it as text. Importing it raises ImportError by design.
"""

from auto_apply.domain.config import APP_DATA_DIR  # noqa: F401 — does not exist; that is the point
from auto_apply.domain.events import Event  # noqa: F401 — exists; guards against false positives
