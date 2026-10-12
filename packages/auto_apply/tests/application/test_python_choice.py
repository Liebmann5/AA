"""Pins for python_choice.py: AA accommodates the Python a computer already
has, and downloads its own only when it must.

Hermetic: every interpreter is a fake runner answer; nothing is executed.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from auto_apply.application.services.install.python_choice import (
    Candidate,
    PythonChoiceError,
    choose,
    discover,
    macos_tools_present,
)

PIN = "3.12.15"


def _c(path: str, v: tuple[int, int, int], tk: bool = True, managed: bool = False) -> Candidate:
    return Candidate(Path(path), v, tk, managed)


def _choose(cands, **kw):
    args = {
        "pinned_version": PIN,
        "requested": None,
        "previous": None,
        "offline": False,
        "host_discovery": True,
    }
    args.update(kw)
    return choose(cands, **args)


def test_a_suitable_host_python_is_used_and_nothing_is_downloaded() -> None:
    """TEETH: the computer's own Python with tkinter wins - no download."""
    choice = _choose([_c("/usr/bin/python3.12", (3, 12, 3))])
    assert choice.kind == "host" and choice.path == Path("/usr/bin/python3.12")
    assert not choice.download and choice.origin == "preexisting"


def test_ci_proven_minor_beats_a_newer_untested_one() -> None:
    choice = _choose([_c("/a/python3.14", (3, 14, 0)), _c("/b/python3.10", (3, 10, 9))])
    assert choice.path == Path("/b/python3.10")


def test_a_host_without_tkinter_leads_to_aas_own_python() -> None:
    """TEETH (measured 2026-10-10): a Debian system Python has no tkinter;
    AA's own Python, which bundles it, is downloaded instead - and says why."""
    choice = _choose([_c("/usr/bin/python3", (3, 13, 16), tk=False)])
    assert choice.kind == "managed" and choice.download and choice.has_tk
    assert any("no tkinter" in n for n in choice.notes)


def test_no_python_at_all_downloads_the_pinned_one() -> None:
    choice = _choose([])
    assert (choice.kind, choice.version, choice.download) == ("managed", PIN, True)


def test_offline_without_aas_python_falls_back_to_a_cli_only_host() -> None:
    choice = _choose([_c("/usr/bin/python3", (3, 12, 1), tk=False)], offline=True)
    assert choice.kind == "host" and not choice.has_tk
    assert any("--cli" in n for n in choice.notes)


def test_offline_with_nothing_usable_refuses_in_plain_words() -> None:
    with pytest.raises(PythonChoiceError, match="offline"):
        _choose([], offline=True)


def test_a_prepopulated_managed_python_is_not_downloaded_again() -> None:
    choice = _choose([], offline=True, managed_present=True)
    assert choice.kind == "managed" and not choice.download


def test_the_persons_choice_wins() -> None:
    hosts = [_c("/usr/bin/python3.12", (3, 12, 3))]
    assert _choose(hosts, requested="managed").kind == "managed"
    picked = _choose(hosts + [_c("/opt/py/python3.10", (3, 10, 4))], requested="/opt/py/python3.10")
    assert picked.path == Path("/opt/py/python3.10")
    with pytest.raises(PythonChoiceError, match="not usable"):
        _choose(hosts, requested="/nowhere/python")


def test_a_repair_keeps_the_previous_choice() -> None:
    """GUARD: a repair never silently switches interpreters."""
    hosts = [_c("/usr/bin/python3.12", (3, 12, 3))]
    assert _choose(hosts, previous="managed").kind == "managed"
    two = hosts + [_c("/opt/py/python3.10", (3, 10, 4))]
    assert _choose(two, previous="/opt/py/python3.10").path == Path("/opt/py/python3.10")


def test_macos_without_developer_tools_says_why_hosts_were_skipped() -> None:
    choice = _choose([], host_discovery=False)
    assert choice.kind == "managed"
    assert any("Command Line" in n for n in choice.notes)


# ── discovery ───────────────────────────────────────────────────────────────


class _Runner:
    def __init__(self, rows: list[dict], probes: dict[str, dict | None]) -> None:
        self.rows, self.probes = rows, probes
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, cmd, **kw):
        self.calls.append((list(cmd), kw))
        if "list" in cmd:
            return SimpleNamespace(returncode=0, stdout=json.dumps(self.rows), stderr="")
        result = self.probes.get(cmd[0])
        if result is None:
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout=json.dumps(result), stderr="")


def _row(path: str, impl: str = "cpython", variant: str = "default") -> dict:
    return {"path": path, "implementation": impl, "variant": variant}


def _probe(*, v=(3, 12, 3), tk=True, ssl=True, sqlite3=True, bits=64, impl="CPython") -> dict:
    return {"v": list(v), "impl": impl, "bits": bits, "ssl": ssl, "sqlite3": sqlite3, "tkinter": tk}


def test_discovery_probes_and_filters(tmp_path: Path) -> None:
    """TEETH: only CPython >= 3.10, 64-bit, with ssl and sqlite3, outside any
    virtual environment, is a candidate; managed ones are recognised."""
    venv = tmp_path / "proj" / ".venv" / "bin"
    venv.mkdir(parents=True)
    (tmp_path / "proj" / ".venv" / "pyvenv.cfg").write_text("home = /x\n")
    managed_dir = tmp_path / "root" / "python"
    managed_py = managed_dir / "cpython-3.12.15" / "bin" / "python3"
    # Every fake Python lives under tmp_path: "/good/python3" is absolute on
    # macOS and Linux but not on Windows (no drive), where discover() rightly
    # resolves it to C:\\good\\python3 and the fake was then never found.
    def py(name: str) -> str:
        return str(tmp_path / name / "python3")

    rows = [
        _row(py("good")),
        _row(py("old")),
        _row(py("nossl")),
        _row(py("x32")),
        _row(str(venv / "python3")),
        _row(py("pypy"), impl="pypy"),
        _row(py("ft"), variant="freethreaded"),
        _row(py("broken")),
        _row(str(managed_py)),
    ]
    probes = {
        py("good"): _probe(tk=False),
        py("old"): _probe(v=(3, 9, 18)),
        py("nossl"): _probe(ssl=False),
        py("x32"): _probe(bits=32),
        str(venv / "python3"): _probe(),
        str(managed_py): _probe(v=(3, 12, 15)),
        py("broken"): None,
    }
    runner = _Runner(rows, probes)
    found = discover(uv=Path("uv"), uv_env={}, runner=runner, managed_dir=managed_dir, host_discovery=True)
    assert [(str(c.path), c.has_tk, c.managed) for c in found] == [
        (py("good"), False, False),
        (str(managed_py), True, True),
    ]
    probe_cmd = next(c for c, _ in runner.calls if c[0] == py("good"))
    assert "-I" in probe_cmd and "-B" in probe_cmd  # never writes into that Python


def test_without_host_discovery_uv_is_asked_for_managed_pythons_only() -> None:
    runner = _Runner([], {})
    discover(uv=Path("uv"), uv_env={}, runner=runner, managed_dir=Path("/r/python"), host_discovery=False)
    _, kw = runner.calls[0]
    assert kw["env"]["UV_PYTHON_PREFERENCE"] == "only-managed"


def test_macos_tools_check(tmp_path: Path) -> None:
    ok = lambda cmd, **kw: SimpleNamespace(returncode=0, stdout=str(tmp_path), stderr="")  # noqa: E731
    missing = lambda cmd, **kw: SimpleNamespace(returncode=2, stdout="", stderr="error")  # noqa: E731
    assert macos_tools_present(ok) is True
    assert macos_tools_present(missing) is False
