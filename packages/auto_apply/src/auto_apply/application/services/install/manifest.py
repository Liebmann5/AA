"""The install manifest (<root>/install.json) — what --install built, and
how every component arrived.

Two consumers:
  * the uninstaller: components recorded "preexisting" (a --source checkout,
    the interpreter that ran the installer) are never deleted;
  * upgrades/repairs: AA-origin components may be replaced; pre-existing
    ones are left alone.

Atomic writes (temp file + os.replace) so an interrupted install never
leaves a half-written manifest.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

MANIFEST_NAME = "install.json"

#: The install receipt (<root>/install_receipt.json) — the uninstaller's
#: proof of which top-level entries AA created in a managed root (D1:
#: package-receipt precedent, pkgutil/MSI). The constant is also the
#: uninstaller's fallback for roots installed before receipts existed.
RECEIPT_NAME = "install_receipt.json"
MANAGED_RECEIPT_ENTRIES: tuple[str, ...] = (
    "uv",
    "python",
    "uv-cache",
    "app",
    "bin",
    "data",
    "tmp",
    "install.json",
    RECEIPT_NAME,
    ".install_pins.txt",
)


@dataclass(frozen=True)
class InstallManifest:
    root: Path
    installed_at: str
    uv_version: str
    python_version: str
    project_dir: Path | None
    project_origin: str  # "aa" | "preexisting"
    components: dict[str, str] = field(default_factory=dict)
    runner_python: str = ""
    runner_python_origin: str = "preexisting"


def write_manifest(
    root: Path,
    *,
    uv_version: str,
    python_version: str,
    project_dir: Path | None,
    project_origin: str,
    components: dict[str, str],
    runner_python: Path,
    runner_python_origin: str,
) -> Path:
    """Write <root>/install.json atomically. Re-running overwrites (repair)."""
    payload = {
        "version": 1,
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "uv_version": uv_version,
        "python_version": python_version,
        "project_dir": str(project_dir) if project_dir is not None else None,
        "project_origin": project_origin,
        "components": components,
        "runner_python": str(runner_python),
        "runner_python_origin": runner_python_origin,
    }
    tmp = root / (MANIFEST_NAME + ".tmp")
    tmp.write_bytes((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    os.replace(tmp, root / MANIFEST_NAME)
    return root / MANIFEST_NAME


def load_manifest(root: Path) -> InstallManifest | None:
    """Read the manifest, or None when there is none (not a managed install)."""
    path = root / MANIFEST_NAME
    if not path.exists():
        return None
    data = json.loads(path.read_bytes().decode("utf-8"))
    project = data.get("project_dir")
    return InstallManifest(
        root=root,
        installed_at=str(data.get("installed_at", "")),
        uv_version=str(data.get("uv_version", "")),
        python_version=str(data.get("python_version", "")),
        project_dir=Path(project) if project else None,
        project_origin=str(data.get("project_origin", "aa")),
        components={str(k): str(v) for k, v in (data.get("components") or {}).items()},
        runner_python=str(data.get("runner_python", "")),
        runner_python_origin=str(data.get("runner_python_origin", "preexisting")),
    )
