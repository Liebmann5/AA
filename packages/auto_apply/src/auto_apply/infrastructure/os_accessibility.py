"""What the operating system says about the person's assistive technology.

Feature detection, never an assumption (ENGINEERING_PHILOSOPHY: progressive
enhancement). Only one signal is read, and only as a hint:

* **Windows** — ``SystemParametersInfo(SPI_GETSCREENREADER)``: TRUE when a
  screen reviewer has announced itself. Microsoft documents that some
  readers set it and that Narrator, the reader built into Windows, does
  not; other programs can set it too. A hint, then, with false negatives
  and possible false positives — which is why it only switches the terminal
  to its plain, linear output (harmless for anyone) and never overrides a
  choice the person made.
* **Linux, macOS** — no equally cheap, permission-free and dependable
  signal exists (GNOME's setting needs a subprocess and a desktop session;
  VoiceOver's needs privacy permissions), so none is read: the person's
  setting, or ``AA_SCREEN_READER=1`` for a run, decides.

No administrator rights, no network, no extra dependency.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping
from typing import Any

#: The run-scoped switch: set before the first prompt (the profile wizard
#: runs before any profile exists to hold the setting).
SCREEN_READER_ENV = "AA_SCREEN_READER"
_SPI_GETSCREENREADER = 0x0046
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def screen_reader_running() -> bool | None:
    """True/False from the OS where it can say (Windows); None elsewhere."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes  # noqa: PLC0415 — Windows only

        flag = ctypes.c_int(0)
        ok = ctypes.windll.user32.SystemParametersInfoW(  # type: ignore[attr-defined]
            _SPI_GETSCREENREADER, 0, ctypes.byref(flag), 0)
        return bool(flag.value) if ok else None
    except Exception:
        return None


def environment_requests_screen_reader(env: Mapping[str, str] | None = None) -> bool:
    """Did this run ask for screen-reader output (``AA_SCREEN_READER=1``)?"""
    value = (env if env is not None else os.environ).get(SCREEN_READER_ENV, "")
    return value.strip().lower() in _TRUTHY


def presentation_settings(
    section: Mapping[str, Any] | None,
    *,
    explicit_screen_reader: bool | None = None,
    env: Mapping[str, str] | None = None,
    detect: Callable[[], bool | None] = screen_reader_running,
) -> dict[str, Any]:
    """The resolved ``accessibility`` section, with the run's signals applied.

    ``AA_SCREEN_READER=1`` turns screen-reader output on for the run. The
    OS hint turns it on only when the person has not chosen either way
    (``explicit_screen_reader`` is None): a person who turned it off keeps
    it off.
    """
    out = dict(section or {})
    if environment_requests_screen_reader(env):
        out["screen_reader_mode"] = True
    elif explicit_screen_reader is None and not out.get("screen_reader_mode"):
        if detect() is True:
            out["screen_reader_mode"] = True
    return out


__all__ = [
    "SCREEN_READER_ENV", "environment_requests_screen_reader", "presentation_settings",
    "screen_reader_running",
]
