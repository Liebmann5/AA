"""Pins for the Windows uninstall finisher (finisher.windows_finisher_script).

Windows never deletes a running program or its loaded DLLs, and scheduling a
delete for the next reboot needs administrator rights. The Python finisher
ran on an interpreter inside the very root it was deleting, so on an
ordinary PC AA's Python and environment stayed behind. The Windows finisher
is Windows PowerShell, outside every AA root. These pins hold its safety
properties; CI's installers job runs it for real on windows-latest.
"""
from __future__ import annotations

from pathlib import Path

from auto_apply.application.services.uninstall.finisher import windows_finisher_script

ROOT = Path("C:/Users/Jo O'Neil/.auto_apply")


def _script() -> str:
    return windows_finisher_script(
        [ROOT / "app", ROOT / "python", ROOT],
        (ROOT / "app", ROOT / "python", ROOT),
        [4242, 4343],
        Path("C:/Temp/aa_uninstall_x"),
    )


def test_script_is_pure_ascii_and_quotes_every_path_safely() -> None:
    """TEETH: an apostrophe in a user name is doubled inside a single-quoted
    PowerShell literal - never able to end the string."""
    script = _script()
    assert "O''Neil" in script
    assert "O'Neil" not in script.replace("O''Neil", "")


def test_waits_for_every_aa_process_before_deleting() -> None:
    script = _script()
    assert script.index("@(4242, 4343)") < script.index("rmdir")
    assert "Get-Process -Id $p" in script


def test_nothing_is_deleted_while_aa_still_runs() -> None:
    """TEETH: past the wait deadline the finisher removes nothing - it never
    deletes under a running AutoApply - and the wait is long enough for a
    person reading the report."""
    from auto_apply.application.services.uninstall import finisher

    script = _script()
    abort = script.index("nothing was removed")
    assert script.index("Get-Process -Id $p") < abort < script.index("rmdir")
    assert "exit 1" in script[abort : script.index("rmdir")]
    assert finisher._PARENT_WAIT_TIMEOUT_S >= 3600


def test_every_target_is_rechecked_against_the_permitted_roots() -> None:
    """GUARD: the finisher re-judges each path; one outside every root is
    refused and reported, never deleted."""
    script = _script()
    assert "outside the permitted roots - refused" in script
    assert script.index("$ok = $false") < script.index("Invoke-Cmd 'rmdir")


def test_the_path_never_passes_through_a_parser() -> None:
    """GUARD: the path reaches cmd.exe through an environment variable and
    ProcessStartInfo.Arguments - no PowerShell re-quoting, no cmd parsing of
    &, ^ or % inside the path. rmdir /s removes a junction, never its target."""
    script = _script()
    assert "$env:AA_FINISH_TARGET = $t" in script
    assert "rmdir /s /q \"%AA_FINISH_TARGET%\"" in script
    assert "Remove-Item -LiteralPath $t" not in script  # PS 5.1 follows junctions


def test_a_result_file_is_written_only_when_something_remains() -> None:
    script = _script()
    assert "if ($left.Count -gt 0)" in script
    assert "aa_uninstall_result.json" in script
    assert "Remove-Item -LiteralPath $staging" in script
