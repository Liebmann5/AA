"""Pin: documented install commands must reference extras that exist, and the
type gate must not lie about the Python floor.

Defect class, three sightings: (1) the retired run.bat invoked pip against an
extras selector named for development tooling that was never declared
anywhere — that tooling lived in the workspace-root PEP 735 dependency group,
which pip's extras selector cannot read — so the command installed nothing
and the scripted test run aborted at collection on `import hypothesis`.
(2) CONTRIBUTING.md §1.1 documented the same command. (3) The Docker test
image shipped the same collection failure. Fourth, adjacent instance: the
workspace-root mypy config set python_version = "3.12" while
packages/auto_apply declares requires-python = ">=3.10" — the type gate was
checking AA against semantics AA does not support.

These checks read the two manifests with a structural reader instead of
tomllib (stdlib only on 3.11+; AA's floor is 3.10 and this file must run
there on the stdlib alone). It is a contract reader for two specific
manifests — not a general TOML parser. Do not grow it into one.

What this pin cannot catch: the contents or versions inside an extra;
commands that are valid but fail at runtime (network, platform); install
commands in files it does not scan (CI YAML, Dockerfiles, TODO documents);
resolution drift inside the ranges it blesses. Those belong to CI and to
uv.lock, not to this file.
"""

from __future__ import annotations

import re
from pathlib import Path

_INFRA_DIR = Path(__file__).resolve().parent          # .../auto_apply/tests/infrastructure
_PACKAGE_DIR = _INFRA_DIR.parent.parent               # .../packages/auto_apply
_REPO_ROOT = _PACKAGE_DIR.parent.parent               # .../AA (workspace root)

ROOT_PYPROJECT = _REPO_ROOT / "pyproject.toml"
PACKAGE_PYPROJECT = _PACKAGE_DIR / "pyproject.toml"
CONTRIBUTING = _PACKAGE_DIR / "CONTRIBUTING.md"
PACKAGE_README = _PACKAGE_DIR / "README.md"
ROOT_README = _REPO_ROOT / "README.md"

_BARE_KEY = re.compile(r"^([A-Za-z0-9_-]+)\s*=", re.MULTILINE)
_UV_SYNC_EXTRA = re.compile(r"uv\s+sync\s+--extra\s+([A-Za-z0-9_-]+)")
_UV_SYNC_GROUP = re.compile(r"uv\s+sync\s+--group\s+([A-Za-z0-9_-]+)")
_EXTRA_SYNTAX = re.compile(r"auto_apply\[([^\]]+)\]")
_EDITABLE_EXTRA = re.compile(r"pip\s+install(?:\s+--?\w+)*\s+-e\s+\S*?\[([^\]]+)\]")
_REQUIRES_PY = re.compile(r'requires-python\s*=\s*">=([0-9.]+)"')
_MYPY_PY_VER = re.compile(r'^python_version\s*=\s*"([0-9.]+)"', re.MULTILINE)

_DEV_GROUP_TOOLS = (
    "pytest", "pytest-mock", "pytest-cov", "hypothesis",
    "mypy", "ruff", "black",
    "mkdocs", "mkdocs-material", "mkdocstrings-python",
)


def _section_text(path: Path, header: str) -> str:
    """Return the lines of *path* between *header* and the next [section] header."""
    lines = path.read_text(encoding="utf-8").splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip() == header:
            start = i + 1
            break
    if start is None:
        raise AssertionError(f"{header} not found in {path.name}")
    end = len(lines)
    for j in range(start, len(lines)):
        if lines[j].strip().startswith("["):
            end = j
            break
    return "\n".join(lines[start:end])


def _section_keys(path: Path, header: str) -> set[str]:
    return set(_BARE_KEY.findall(_section_text(path, header)))


def _documented_commands() -> list[tuple[str, str]]:
    """(document_name, text) for every file whose commands AA asks humans to run."""
    docs = []
    for path in (CONTRIBUTING, PACKAGE_README, ROOT_README):
        if path.is_file():
            docs.append((path.name, path.read_text(encoding="utf-8")))
    return docs


def test_documented_install_commands_reference_real_extras() -> None:
    pkg_extras = _section_keys(PACKAGE_PYPROJECT, "[project.optional-dependencies]")
    root_groups = _section_keys(ROOT_PYPROJECT, "[dependency-groups]")

    offenders: list[str] = []
    for doc_name, text in _documented_commands():
        for name in _UV_SYNC_EXTRA.findall(text):
            if name not in pkg_extras:
                offenders.append(f"{doc_name}: 'uv sync --extra {name}' — no such extra")
        for name in _UV_SYNC_GROUP.findall(text):
            if name not in root_groups:
                offenders.append(f"{doc_name}: 'uv sync --group {name}' — no such group")
        for blob in _EXTRA_SYNTAX.findall(text):
            for name in blob.split(","):
                name = name.strip()
                if name and name not in pkg_extras:
                    offenders.append(f"{doc_name}: 'auto_apply[{name}]' — no such extra")
        for blob in _EDITABLE_EXTRA.findall(text):
            for name in blob.split(","):
                name = name.strip()
                if name and name not in pkg_extras:
                    offenders.append(
                        f"{doc_name}: 'pip install -e …[{name}]' — no such extra "
                        f"(extras != PEP 735 groups; this is the run.bat defect class)"
                    )

    assert not offenders, (
        "Documented install commands reference extras/groups that do not exist "
        "(the command is a lie — it would install nothing):\n"
        + "\n".join(f"  {o}" for o in offenders)
    )


def test_mypy_python_version_matches_requires_python_floor() -> None:
    pkg_text = PACKAGE_PYPROJECT.read_text(encoding="utf-8")
    floor_match = _REQUIRES_PY.search(pkg_text)
    assert floor_match is not None, "requires-python not found in package pyproject.toml"
    floor = floor_match.group(1)

    root_text = ROOT_PYPROJECT.read_text(encoding="utf-8")
    gate_match = _MYPY_PY_VER.search(root_text)
    assert gate_match is not None, "python_version not found in workspace-root [tool.mypy]"
    gate = gate_match.group(1)

    assert gate == floor, (
        f"the type gate checks AA against Python {gate} but AA declares support "
        f"for {floor}+ — the gate must not lie about the floor (see the numpy "
        f"stub history in the workspace-root [tool.mypy] comment)"
    )


def test_dev_tooling_is_declared_only_in_the_workspace_group() -> None:
    """Dev tooling has exactly one home: the workspace-root dependency group.

    Duplicating it into package extras is how the two declarations drifted
    apart the first time (the docs extra once carried mkdocs while the dev
    group carried the same list).
    """
    extras_text = _section_text(PACKAGE_PYPROJECT, "[project.optional-dependencies]")
    leaks = [tool for tool in _DEV_GROUP_TOOLS if f'"{tool}"' in extras_text]
    assert not leaks, (
        f"dev tooling is declared in package extras as well as the workspace "
        f"group: {leaks}. One declaration, one home — the workspace-root "
        f"[dependency-groups] entry."
    )
