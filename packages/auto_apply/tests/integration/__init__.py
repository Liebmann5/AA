"""Integration tests for AutoApply.

Tests in this directory may require a live browser, network access, or
a full SQLite database.  They are separated from fast unit tests so CI
can run unit tests quickly and integration tests on a schedule.

Run:
    uv run pytest tests/integration/ -v
    uv run pytest tests/integration/ -m "not browser" -v   # skip browser tests
"""
