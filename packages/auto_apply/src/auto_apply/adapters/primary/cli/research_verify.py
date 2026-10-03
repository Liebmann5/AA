"""Render research-bundle verification for ``--verify-research`` (item 10).

Every print lives here, in the primary adapter, so main.py's pinned
print-site count does not move — the ``--label`` / ``--research``
precedent. The checks themselves are the secondary verifier, reached
through composition_root (primary adapters do not import secondary
adapters directly).
"""
from __future__ import annotations

from pathlib import Path

from auto_apply.infrastructure.composition_root import verify_research_bundle

__all__ = ["run_verify_research"]


def run_verify_research(bundle_dir: Path) -> int:
    """Verify one bundle and print the outcome.

    Exit codes: 0 — the bundle is intact; 1 — verification failed;
    2 — not a bundle folder.
    """
    if not bundle_dir.is_dir():
        print(f"Not a bundle folder: {bundle_dir}")  # noqa: T201
        return 2
    result = verify_research_bundle(bundle_dir)
    print(f"Research bundle verification: {bundle_dir}")  # noqa: T201
    for line in result.checks:
        print(f"  ✓ {line}")  # noqa: T201
    for line in result.failures:
        print(f"  ✗ {line}")  # noqa: T201
    if result.fingerprint:
        print(f"  Signing-key fingerprint: {result.fingerprint}")  # noqa: T201
    if not result.signed:
        print(  # noqa: T201
            "  ! This bundle is UNSIGNED (declared in index.json): the "
            "exporting installation had no signing key, so the bundle-level "
            "signature could not be checked. Everything else was checked."
        )
    for line in result.notes:
        print(f"  - {line}")  # noqa: T201
    if result.ok:
        print("Result: OK — this bundle is intact.")  # noqa: T201
        return 0
    print(f"Result: FAILED — {len(result.failures)} problem(s) found.")  # noqa: T201
    return 1
