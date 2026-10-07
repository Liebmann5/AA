"""Single-source ratchet for pointer, wheel, scroll-JS and click input (call 2).

After the input census, the ONLY code in src/ allowed to drive raw pointer
movement, wheel input, scroll-JS or element clicks is:

    * the interaction tool — application/services/page_action/*
    * the two browser adapters — selenium_adapter.py, playwright_adapter.py

Everything else either went through the tool, or is listed in the LEDGER
below with a reason and a hit ceiling, in the style of
test_module_reachability.KNOWN_UNREACHABLE: a ratchet, so the count can only
go down. A file that outgrows its ceiling — or any NEW file appearing in the
report — fails the pin.

Modules already in the reachability pin's KNOWN_UNREACHABLE inventory are
skipped: they are tracked debt there and cannot sit on a live call path;
when one gets wired, it loses that exemption and this pin then applies to it.
"""
from __future__ import annotations

import ast
from pathlib import Path

_PKG_ROOT = Path(__file__).resolve().parents[2]
_SRC_DIR = _PKG_ROOT / "src" / "auto_apply"
_PAGE_ACTION = _SRC_DIR / "application" / "services" / "page_action"

_ALLOWED_FILES = frozenset({
    _SRC_DIR / "adapters" / "secondary" / "browser" / "selenium_adapter.py",
    _SRC_DIR / "adapters" / "secondary" / "browser" / "playwright_adapter.py",
})

#: path-relative-to-src -> (reason, max hits). A missing file is skipped
#: silently — two entries below name modules this change retires, so the
#: pin is green both before and after the retire.py step runs.
LEDGER: dict[str, tuple[str, int]] = {
    "infrastructure/resilient_driver.py": (
        "legacy click helper + overlay dismissal pending a caller census "
        "(call 3 retires or delegates); the wrapper is also a port forwarder",
        6,
    ),
    "adapters/secondary/resolution/captcha_adapter.py": (
        "the audio resolver clicks inside a challenge widget BY DESIGN; the "
        "tool's ladder refuses challenge widgets, so routing it would kill "
        "the resolver — ruled with the suspend/resume contract (predicate 10)",
        1,
    ),
    "adapters/secondary/interaction/handlers/base.py": (
        "no-tool fallback for direct construction in tests; production "
        "always injects the tool",
        1,
    ),
    "adapters/secondary/discovery/strategies/navigators.py": (
        "no-tool fallback for direct construction in tests; every production "
        "provider now injects the tool (Indeed wired in call 3)",
        1,
    ),
    "adapters/secondary/navigation/interruption.py": (
        "no-tool fallback for adapter call sites that construct the handler "
        "bare; the composition root injects the tool",
        1,
    ),
    "adapters/secondary/discovery/strategies/toolbar_locator.py": (
        "WIRE-LATER module (skipped while unreachable); when wired, its "
        "no-tool fallback is covered by this entry",
        1,
    ),
    "adapters/secondary/interaction/execution_strategies.py": (
        "RETIRED in this change — moot once retire.py runs (missing files "
        "are skipped)",
        3,
    ),
    "adapters/secondary/evasion/components/session.py": (
        "RETIRED in this change — moot once retire.py runs (missing files "
        "are skipped)",
        2,
    ),
}

#: Substring patterns that no caller outside the allowlist may contain.
_SCRIPT_PATTERNS = (
    "window.scrollTo(",
    "window.scrollBy(",
    "scrollIntoView(",
    "arguments[0].click()",
    "ActionChains(",
    "ActionBuilder(",
    ".move_mouse_by_offset(",
    ".move_mouse_to_element(",
    ".perform_mouse_fidget(",
)


def _element_click_hits(path: Path) -> int:
    """Count ``x.click()`` calls where x is a bare local name (an element),
    never a port/tool receiver (self, anything containing port/tool/locator).
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return 0
    hits = 0
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr != "click" or not isinstance(node.func.value, ast.Name):
            continue
        receiver = node.func.value.id.lower()
        if receiver == "self" or "port" in receiver or "tool" in receiver or "locator" in receiver:
            continue
        hits += 1
    return hits


def _unreachable_inventory() -> frozenset[str]:
    """The reachability pin's orphan inventory, imported so the two pins can
    never disagree about which modules are dead. Unreachable modules cannot
    bypass anything; when one is wired it loses the exemption and this pin
    then applies."""
    try:
        from .test_module_reachability import KNOWN_UNREACHABLE
    except Exception:  # pragma: no cover - the architecture package moved
        return frozenset()
    return frozenset(KNOWN_UNREACHABLE)


def _iter_violations() -> list[str]:
    failures: list[str] = []
    unreachable = _unreachable_inventory()
    for path in sorted(_SRC_DIR.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        if path.is_relative_to(_PAGE_ACTION) or path in _ALLOWED_FILES:
            continue
        rel = path.relative_to(_SRC_DIR).as_posix()
        dotted = "auto_apply." + rel[:-3].replace("/", ".")
        if dotted in unreachable:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        hits = sum(text.count(p) for p in _SCRIPT_PATTERNS) + _element_click_hits(path)
        if hits == 0:
            continue
        entry = LEDGER.get(rel)
        if entry is None:
            failures.append(f"UNLEDGERED RAW INPUT SITE — {rel}: {hits} hit(s)")
        elif hits > entry[1]:
            failures.append(
                f"LEDGER CEILING EXCEEDED — {rel}: {hits} hit(s) > ceiling "
                f"{entry[1]} (reason: {entry[0]})"
            )
    return failures


def test_no_raw_input_paths_outside_the_tool_and_adapters() -> None:
    failures = _iter_violations()
    assert not failures, (
        "\nSINGLE-SOURCE REPORT — raw pointer/wheel/scroll/click input found "
        "outside the interaction tool and the two browser adapters\n"
        + "=" * 72
        + "\n"
        + "\n".join(failures)
        + "\n"
    )


def test_the_allowlist_is_exact_and_present() -> None:
    """The allowlist is the tool plus the two adapters — and it exists."""
    assert _PAGE_ACTION.is_dir(), "the interaction tool package is missing"
    for path in sorted(_ALLOWED_FILES):
        assert path.is_file(), f"allowlisted adapter missing: {path}"


def test_every_ledger_entry_has_a_reason_and_a_positive_ceiling() -> None:
    for rel, (reason, ceiling) in LEDGER.items():
        assert reason.strip(), f"ledger entry without a reason: {rel}"
        assert ceiling >= 1, f"ledger ceiling must be >= 1: {rel}"


def test_the_behavior_module_no_longer_feeds_the_discovery_adapters() -> None:
    """The routed census sites must not re-import the evasion behaviour
    module. (behavior.py's own retirement is gated on a caller grep — see
    the change notes — but THESE files are off it either way.)"""
    for rel in (
        "adapters/secondary/discovery/strategies/engine_strategies.py",
        "adapters/secondary/discovery/strategies/navigators.py",
        "adapters/secondary/discovery/providers/google.py",
        "adapters/secondary/discovery/providers/bing.py",
        "adapters/secondary/discovery/strategies/toolbar_locator.py",
        "infrastructure/composition_root.py",
    ):
        text = (_SRC_DIR / rel).read_text(encoding="utf-8", errors="replace")
        assert "evasion.components import behavior" not in text, (
            f"{rel} still imports the evasion behaviour module"
        )
