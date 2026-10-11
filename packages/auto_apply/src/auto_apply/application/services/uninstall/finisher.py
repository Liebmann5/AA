"""The detached finisher — deletes AA's own runtime after AA exits.

A running process cannot delete its own interpreter (Windows locks the
venv's python.exe; a frozen exe locks itself). The pattern here: the engine
writes a PAYLOAD to the OS temp dir and re-launches THIS installation
detached — ``sys.executable --finisher-payload <path>``, which under
PyInstaller is the exe itself, so no staged script copy and no import of a
half-deleted package is ever needed. main.py dispatches that flag before
anything else (with directory creation suppressed).

The finisher waits for the parent's pid to die, re-validates every path
against the payload's permitted roots (a payload is never trusted — it
names what may be deleted), deletes, and reports into its own result file.
Anything still locked on Windows is scheduled for deletion at next reboot
via MoveFileExW. An interrupted finisher is not a failure mode: every
delete is idempotent, so the next uninstall run simply resumes.

WINDOWS runs a different finisher. A Python finisher would itself run on an
interpreter inside the root it is deleting (AA's own Python, or the venv's
python.exe redirector), and Windows never deletes a running program or its
loaded DLLs; MoveFileExW's reboot scheduling needs administrator rights, so
on an ordinary or library PC those files simply stayed. The Windows finisher
is Windows PowerShell 5.1 - outside every AA root, present on every Windows
10 and 11 - handed its instructions inline (-EncodedCommand, so there is no
payload file to tamper with). It waits for AA and every AA program above it
(the venv redirector, uv.exe) to exit, re-checks each path against the
permitted roots, and deletes with cmd's rmdir, which removes a junction
without following it.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from auto_apply.application.services.uninstall.guarded_delete import guarded_remove
from auto_apply.application.services.uninstall.scoping import (
    OutOfScopeError,
    require_deletable,
)

PAYLOAD_NAME = "aa_uninstall_payload.json"
RESULT_NAME = "aa_uninstall_result.json"
#: How long the finisher waits for AutoApply to exit. Long on purpose: the
#: person may leave the uninstall report open as long as they like, and the
#: finisher must neither give up (AA's runtime would stay behind) nor delete
#: while AA still runs. Past it, the finisher removes NOTHING and says so; the
#: next --uninstall resumes.
_PARENT_WAIT_TIMEOUT_S = 6 * 3600.0


@dataclass
class FinisherResult:
    removed: list[str] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)
    scheduled_for_reboot: list[str] = field(default_factory=list)


def build_payload(
    paths: list[Path], allowed_roots: tuple[Path, ...] | list[Path], parent_pid: int
) -> dict:
    """The finisher's instructions: what to delete, and what it may never leave."""
    return {
        "v": 1,
        "parent_pid": parent_pid,
        "paths": [str(p) for p in paths],
        "roots": [str(r) for r in allowed_roots],
    }


def validate_payload(payload: dict, *, realpath=os.path.realpath) -> tuple[list[Path], tuple[Path, ...]]:
    """Return (paths, roots); raise OutOfScopeError on ANY escape.

    The finisher re-judges the payload it was handed: instructions are not
    authority.
    """
    paths = [Path(p) for p in payload.get("paths", [])]
    roots = tuple(Path(r) for r in payload.get("roots", []))
    if not roots:
        raise OutOfScopeError("payload names no permitted roots — refusing to delete anything")
    for path in paths:
        require_deletable(path, roots, realpath=realpath)
    return paths, roots


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        import psutil

        return bool(psutil.pid_exists(pid))
    except Exception:  # noqa: BLE001 — a finisher must not crash on a probe
        return False


def _schedule_delete_on_reboot(path: Path) -> bool:
    """MoveFileExW(MOVEFILE_DELAY_UNTIL_REBOOT). Windows only; False elsewhere."""
    if os.name != "nt":
        return False
    import ctypes

    windll: Any = getattr(ctypes, "windll", None)
    if windll is None:
        return False
    try:
        return bool(windll.kernel32.MoveFileExW(str(path), None, 0x4))
    except Exception:  # noqa: BLE001
        return False


def run_finisher(
    payload: dict,
    *,
    wait_for_parent: bool = True,
    realpath=os.path.realpath,
    sleep=time.sleep,
) -> FinisherResult:
    """The finisher's work, synchronous and directly testable."""
    result = FinisherResult()
    paths, roots = validate_payload(payload, realpath=realpath)
    if wait_for_parent:
        deadline = time.monotonic() + _PARENT_WAIT_TIMEOUT_S
        while _pid_alive(int(payload.get("parent_pid", -1))):
            if time.monotonic() > deadline:
                result.failed.append(
                    {"path": "<parent>", "error": "parent process never exited — aborting"}
                )
                return result
            sleep(0.5)
    for path in paths:
        try:
            guarded_remove(path, roots, realpath=realpath)
            result.removed.append(str(path))
        except OutOfScopeError as exc:
            result.failed.append({"path": str(path), "error": str(exc)})
        except OSError as exc:
            if _schedule_delete_on_reboot(path):
                result.scheduled_for_reboot.append(str(path))
            else:
                result.failed.append({"path": str(path), "error": f"{type(exc).__name__}: {exc}"})
    return result


def _ps_literal(text: str) -> str:
    """A PowerShell single-quoted string literal (only ' needs escaping)."""
    return "'" + text.replace("'", "''") + "'"


def windows_finisher_script(
    paths: list[Path], roots: tuple[Path, ...] | list[Path], pids: list[int], staging: Path
) -> str:
    """The Windows finisher, as PowerShell 5.1 source. Pure: testable anywhere."""
    pid_list = ", ".join(str(int(p)) for p in pids) or "0"
    targets = ", ".join(_ps_literal(str(x)) for x in paths)
    root_list = ", ".join(_ps_literal(str(r)) for r in roots)
    return "\n".join([
        "$ErrorActionPreference = 'SilentlyContinue'",
        f"$staging = {_ps_literal(str(staging))}",
        "# Arguments go to cmd.exe verbatim (no PowerShell re-quoting); the path",
        "# travels in an environment variable, so no character in it is parsed.",
        "function Invoke-Cmd([string]$line) {",
        "    $si = New-Object System.Diagnostics.ProcessStartInfo",
        "    $si.FileName = 'cmd.exe'; $si.Arguments = '/d /c ' + $line",
        "    $si.UseShellExecute = $false; $si.CreateNoWindow = $true",
        "    $pr = [System.Diagnostics.Process]::Start($si); $pr.WaitForExit()",
        "}",
        f"$deadline = (Get-Date).AddSeconds({int(_PARENT_WAIT_TIMEOUT_S)})",
        f"$pids = @({pid_list})",
        "foreach ($p in $pids) {",
        "    while ((Get-Process -Id $p -ErrorAction SilentlyContinue) -and ((Get-Date) -lt $deadline)) { Start-Sleep -Milliseconds 300 }",
        "}",
        "# Still running at the deadline: delete NOTHING (a running AA holds its files).",
        "if (@($pids | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue }).Count -gt 0) {",
        f"    [IO.File]::WriteAllText((Join-Path $staging '{RESULT_NAME}'), (ConvertTo-Json @{{failed = @('AutoApply was still running - nothing was removed. Close it and run the uninstall again.')}}))",
        "    exit 1",
        "}",
        f"$roots = @({root_list})",
        "$left = New-Object System.Collections.ArrayList",
        f"foreach ($t in @({targets})) {{",
        "    $full = [IO.Path]::GetFullPath($t).TrimEnd('\\')",
        "    $ok = $false",
        "    foreach ($r in $roots) {",
        "        $rf = [IO.Path]::GetFullPath($r).TrimEnd('\\')",
        "        if (($full -ieq $rf) -or $full.StartsWith($rf + '\\', [StringComparison]::OrdinalIgnoreCase)) { $ok = $true }",
        "    }",
        "    if (-not $ok) { [void]$left.Add($t + ' (outside the permitted roots - refused)'); continue }",
        "    for ($i = 0; ($i -lt 40) -and (Test-Path -LiteralPath $t); $i++) {",
        "        $env:AA_FINISH_TARGET = $t",
        "        if (Test-Path -LiteralPath $t -PathType Container) { Invoke-Cmd 'rmdir /s /q \"%AA_FINISH_TARGET%\"' }",
        "        else { Invoke-Cmd 'del /f /q \"%AA_FINISH_TARGET%\"' }",
        "        if (Test-Path -LiteralPath $t) { Start-Sleep -Milliseconds 500 }",
        "    }",
        "    if (Test-Path -LiteralPath $t) { [void]$left.Add($t) }",
        "}",
        "if ($left.Count -gt 0) {",
        f"    [IO.File]::WriteAllText((Join-Path $staging '{RESULT_NAME}'), (ConvertTo-Json @{{failed = @($left)}}))",
        "} else {",
        "    Remove-Item -LiteralPath $staging -Recurse -Force",
        "}",
        "",
    ])


def _aa_process_chain(roots: tuple[Path, ...]) -> list[int]:
    """This process plus every ancestor whose program lives inside a root
    being deleted (the venv redirector, uv.exe) - all must exit first."""
    pids = [os.getpid()]
    try:
        import psutil  # noqa: PLC0415 - as in _pid_alive: a finisher never fails on an import

        from auto_apply.application.services.uninstall.scoping import is_within  # noqa: PLC0415

        for parent in psutil.Process(os.getpid()).parents():
            try:
                exe = parent.exe()
            except Exception:  # noqa: BLE001 - access denied: not ours to wait for
                continue
            if exe and any(is_within(Path(exe), r) for r in roots):
                pids.append(parent.pid)
    except Exception:  # noqa: BLE001 - waiting for fewer is still correct, just slower
        pass
    return pids


def _launch_windows_finisher(
    paths: list[Path], roots: tuple[Path, ...], staging: Path
) -> None:
    import base64  # noqa: PLC0415 - Windows only

    script = windows_finisher_script(paths, roots, _aa_process_chain(roots), staging)
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    powershell = Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    subprocess.Popen(
        [str(powershell) if powershell.exists() else "powershell.exe",
         "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-EncodedCommand", encoded],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        cwd=str(staging),  # never a folder being deleted
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )


def launch_detached(paths: list[Path], allowed_roots: tuple[Path, ...]) -> Path:
    """Stage a payload in the OS temp dir and re-launch AA detached.

    The staging dir is the OS's own temp — the one place outside AA's roots
    a finisher artifact may appear, and the finisher removes it when done
    (or schedules it at reboot).
    """
    staging = Path(tempfile.mkdtemp(prefix="aa_uninstall_"))
    if os.name == "nt":
        _launch_windows_finisher(paths, allowed_roots, staging)
        return staging
    payload_path = staging / PAYLOAD_NAME
    payload_path.write_bytes(
        json.dumps(build_payload(paths, allowed_roots, os.getpid()), indent=2).encode("utf-8")
    )
    if getattr(sys, "frozen", False):
        # The frozen exe parses AA's own flags (main.py handles
        # --finisher-payload before anything else).
        cmd = [sys.executable, "--finisher-payload", str(payload_path)]
    else:
        # Source and managed mode: sys.executable is the Python interpreter,
        # which knows no such option (D3, measured: 'unknown option', exit
        # 2, and the report still claimed a handoff). It must run AA as a
        # module. In managed mode this interpreter lives inside the root
        # being deleted: locked on Windows, which the reboot scheduling
        # below exists for.
        cmd = [sys.executable, "-m", "auto_apply", "--finisher-payload", str(payload_path)]
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(cmd, cwd=str(staging), **kwargs)
    return staging


def run_and_report(payload_path: Path) -> int:
    """The --finisher-payload entry point: run, write the result file, clean up."""
    payload = json.loads(payload_path.read_bytes().decode("utf-8"))
    try:
        result = run_finisher(payload)
    except OutOfScopeError as exc:
        result = FinisherResult(failed=[{"path": "<payload>", "error": str(exc)}])
    staging = payload_path.parent
    # A result file is a TRACE — write one only when there is something to
    # explain (D3, measured: the staging dir and its unread result file were
    # left in the OS temp folder on macOS and Linux). A clean finish leaves
    # nothing behind; the engine's report tells the user this rule.
    if result.failed or result.scheduled_for_reboot:
        (staging / RESULT_NAME).write_bytes(
            json.dumps(
                {
                    "removed": result.removed,
                    "failed": result.failed,
                    "scheduled_for_reboot": result.scheduled_for_reboot,
                },
                indent=2,
            ).encode("utf-8")
        )
    try:
        payload_path.unlink()
    except OSError:
        _schedule_delete_on_reboot(payload_path)
    try:
        staging.rmdir()
    except OSError:
        # Non-empty only when a result file exists to explain why.
        _schedule_delete_on_reboot(staging)
    return 0 if not result.failed else 1
